"""Video event reset gates; no emulator or memory input."""
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from robotron_ai.harness import HudTrackingReset
from robotron_ai.brain import ChampionBrain
from robotron_ai import harness


class HudResetTests(unittest.TestCase):
    def book(self, wave=1, deaths=0, game='g', over=False):
        return SimpleNamespace(game_id=game, wave=wave, deaths=deaths,
                               game_over_fired=over)

    def test_default_is_inert_and_modes_are_independent(self):
        for death, wave, expected in [(False, False, 0), (True, False, 1),
                                       (False, True, 1), (True, True, 2)]:
            tracker = HudTrackingReset(death=death, wave=wave)
            brain = Mock()
            for book in [self.book(), self.book(deaths=1), self.book(deaths=1),
                         self.book(wave=2, deaths=1)]:
                tracker.update(book, brain)
            self.assertEqual(brain.reset.call_count, expected)

    def test_initial_junk_game_change_skip_and_game_over_do_not_reset(self):
        tracker = HudTrackingReset(death=True, wave=True)
        brain = Mock()
        for book in [self.book(wave=None), self.book(wave=71),
                     self.book(game='new'), self.book(wave=4, game='new'),
                     self.book(wave=5, deaths=1, game='new', over=True)]:
            tracker.update(book, brain)
        brain.reset.assert_not_called()

    def test_real_brain_history_clears_once_and_fresh_tracking_resumes(self):
        brain = ChampionBrain(lag_ticks=.7, use_coaster=True)
        brain.vt.velocities([(100, 100, 'Grunt')])
        brain.coaster.update([(100, 100, 'EnforcerBullet')])
        brain.last_mv = 4
        brain._sample_time = 42
        brain._tracked_sample = ['cached']
        tracker = HudTrackingReset(death=True)
        tracker.update(self.book(), brain)
        tracker.update(self.book(deaths=1), brain)
        self.assertEqual(brain.vt.prev, [])
        self.assertEqual(brain.coaster.tracks, [])
        self.assertEqual(brain.last_mv, 0)
        self.assertIsNone(brain._sample_time)
        self.assertIsNone(brain._tracked_sample)
        self.assertEqual(brain.vt.velocities([(200, 200, 'Grunt')]), [(0, 0)])

    def test_loop_keeps_sending_actions_without_reset_pause(self):
        for enabled in ('0', '1'):
            brain, controller, reader = Mock(), Mock(), Mock()
            brain.decide.return_value = (3, 5)
            perception = Mock(last_frame=object())
            obs = SimpleNamespace(player=(100, 100), entities=[], sampled_at=1)
            perception.perceive.side_effect = [obs] * 9 + [KeyboardInterrupt()]
            book = self.book()
            def feed(*args, **kwargs):
                book.deaths += 1
            book.feed = feed
            with patch.dict('os.environ', {'ROBOTRON_HUD_DEATH_RESET': enabled,
                    'ROBOTRON_HUD_WAVE_RESET': '0', 'ROBOTRON_TRANSITION_DIAGNOSTICS': '0'}), \
                    patch.object(harness, 'ensure_game_running'), \
                    patch.object(harness, 'TickClock'):
                with self.assertRaises(KeyboardInterrupt):
                    harness.play_vision_game(brain, perception, controller,
                        hud_reader=reader, bookkeeper=book, hz=15)
            self.assertEqual(controller.move_shoot.call_count, 9)
            controller.neutral.assert_not_called()
            self.assertEqual(brain.reset.call_count, 2 if enabled == '1' else 0)


if __name__ == '__main__':
    unittest.main()
