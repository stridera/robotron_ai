"""Bounded trace and player-loss behavior, without emulators or model inference."""
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from robotron_ai import harness
from robotron_ai.brain import ChampionBrain, DXY
from robotron_ai.perception import VisionPerception
from robotron_ai.tools.production_decision_trace import DecisionTrace


def observations(hold):
    eye = object.__new__(VisionPerception)
    eye.source = Mock(last_read_at=1.0)
    eye.source.read.return_value = object()
    eye._infer = Mock(return_value=SimpleNamespace(boxes=[]))
    eye._parse_boxes = Mock(side_effect=[(p, [], [], p) for p in
        [(100, 100)] + [None] * 7 + [(200, 100)]])
    eye._calibrate_center = Mock()
    eye.max_player_hold = hold
    eye._player_hold = 0
    eye.last_player = None
    return [eye.perceive(None) for _ in range(9)]


class DecisionTraceTests(unittest.TestCase):
    def test_neutral_lead_reset_changes_only_long_neutral_reacquisition(self):
        for enabled, seconds in ((False, .5), (True, .1), (True, .5)):
            brain = ChampionBrain(0, player_lead_ticks=1.5)
            brain._champion_action = Mock(return_value=(3, 5))
            seen = SimpleNamespace(player=(200, 100), entities=[], sampled_at=1,
                                   player_hold_samples=0)
            missing = SimpleNamespace(player=None, entities=[], sampled_at=2,
                                      player_hold_samples=0)
            perception = SimpleNamespace(last_frame=None,
                perceive=Mock(side_effect=[seen] + [missing]*10 + [seen, KeyboardInterrupt()]))
            controller = Mock()
            with patch.object(harness, 'TickClock'), \
                    patch.object(harness, 'ensure_game_running'), \
                    patch.object(harness.time, 'monotonic', side_effect=[10, 10+seconds]), \
                    patch.dict('os.environ', {'ROBOTRON_NEUTRAL_LEAD_RESET': str(int(enabled)),
                        'ROBOTRON_FRESH_PLAYER_ACTION': '0',
                        'ROBOTRON_TRANSITION_DIAGNOSTICS': '0'}):
                with self.assertRaises(KeyboardInterrupt):
                    harness.play_vision_game(brain, perception, controller, hold_action=4)
            sprites = brain._champion_action.call_args.args[0]
            reset = enabled and seconds >= .3
            expected = (200, 100) if reset else (200+DXY[3][0]*1.5, 100+DXY[3][1]*1.5)
            self.assertEqual(sprites[0][:2], expected)
            self.assertEqual(brain._champion_action.call_count, 2)
            self.assertEqual(controller.neutral.call_count, 6)
            self.assertEqual(controller.move_shoot.call_count, 6)
            self.assertEqual(brain.last_mv, 3)

    def test_fresh_control_uses_action_hold_then_neutral_and_recovers(self):
        for enabled in (False, True):
            obs = observations(6)
            self.assertEqual([o.player_hold_samples for o in obs],
                             [0, 1, 2, 3, 4, 5, 6, 0, 0])
            brain, controller = Mock(), Mock()
            brain.decide.return_value = (3, 5)
            perception = SimpleNamespace(last_frame=object(),
                perceive=Mock(side_effect=obs + [KeyboardInterrupt()]))
            observer = Mock()
            book = SimpleNamespace(game_id='g', wave=1, deaths=0,
                game_over_fired=False, feed=Mock())
            with patch.object(harness, 'TickClock'), \
                    patch.object(harness, 'ensure_game_running'), patch.dict('os.environ',
                    {'ROBOTRON_FRESH_PLAYER_ACTION': str(int(enabled))}):
                with self.assertRaises(KeyboardInterrupt):
                    harness.play_vision_game(brain, perception, controller,
                        hold_action=4, decision_observer=observer,
                        hud_reader=Mock(), bookkeeper=book)
            self.assertEqual(brain.decide.call_count, 2 if enabled else 8)
            self.assertEqual(controller.neutral.call_count, 3 if enabled else 0)
            self.assertEqual(controller.move_shoot.call_count, 6 if enabled else 9)
            self.assertEqual(observer.call_count, 9)
            self.assertEqual(brain.decide.call_args.args[0], (200, 100))
            # Control-only flag never changes the visibility passed to HUD.
            self.assertEqual([c.kwargs['player_visible'] for c in book.feed.call_args_list],
                             [True, True, True])

    def test_trace_copies_tracks_and_never_changes_decisions(self):
        obs = observations(6)[1]
        track = dict(x=100, y=200, name='TankShell', vx=5, vy=0, miss=1)
        brain = SimpleNamespace(coaster=SimpleNamespace(tracks=[track]))
        with tempfile.TemporaryDirectory() as temp:
            trace = DecisionTrace(temp)
            trace.record(obs, 3, 5, brain, obs.player)
            track['x'] = 999
            trace.close()
            row = json.loads((Path(temp) / 'decisions.jsonl').read_text())
            self.assertEqual(row['projectile_tracks'][0]['x'], 100)
            self.assertEqual(row['player_hold_samples'], 1)
            self.assertEqual((row['move'], row['fire']), (3, 5))
            self.assertEqual(trace.summary['written'], 1)

    def test_trace_byte_cap_preserves_complete_lines_and_keeps_counting(self):
        with tempfile.TemporaryDirectory() as temp:
            trace = DecisionTrace(temp, max_bytes=1)
            obs = observations(0)[1]
            for _ in range(3):
                trace.record(obs, 0, 0, SimpleNamespace(coaster=None), None)
            trace.close()
            self.assertEqual((Path(temp) / 'decisions.jsonl').stat().st_size, 0)
            self.assertTrue(trace.summary['truncated'])
            self.assertEqual(trace.summary['ticks'], 3)
            self.assertEqual(trace.summary['blind_ticks'], 3)


if __name__ == '__main__':
    unittest.main()
