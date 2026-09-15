"""Player turn lead and actual-command lifecycle, without gameplay."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from robotron_ai.brain import ChampionBrain, DXY
from robotron_ai import harness


class PlayerHistoryTests(unittest.TestCase):
    def brain(self):
        b = ChampionBrain(0, 1.5)
        b.player_history_lead = True
        b._champion_action = Mock(return_value=(3,3))
        return b

    def test_turn_lead_and_unchanged_straight_default(self):
        for enabled, old, last in ((True,1,3),(True,3,3),(False,1,3)):
            b = self.brain()
            b.player_history_lead = enabled
            b.record_command(old); b.record_command(last); b.last_mv = last
            b.decide((300,200), [])
            got = b._champion_action.call_args.args[0][0][:2]
            expected = tuple(p+1.5*DXY[last][k]+(.5*(DXY[old][k]-DXY[last][k]) if enabled else 0)
                             for k,p in enumerate((300,200)))
            self.assertEqual(got, expected)

    def test_blind_history_and_reset_do_not_change_reacquisition(self):
        for reset in (False,True):
            b = self.brain()
            b.record_command(1); b.record_command(3, controlled=False); b.last_mv = 3
            if reset:
                b.reset(); b.last_mv = 3
                self.assertEqual(b._sent_moves, [])
            b.decide((300,200), [])
            self.assertEqual(b._champion_action.call_args.args[0][0][:2], (314.25,200))

    def test_harness_records_sent_hold_and_neutral_commands(self):
        b = self.brain()
        b.record_command = Mock(wraps=b.record_command)
        seen = SimpleNamespace(player=(300,200), entities=[], sampled_at=1, player_hold_samples=0)
        blind = SimpleNamespace(player=None, entities=[], sampled_at=2, player_hold_samples=0)
        perception = SimpleNamespace(last_frame=None, perceive=Mock(side_effect=[seen]+[blind]*3+[seen,KeyboardInterrupt()]))
        with patch.object(harness, 'TickClock'), patch.object(harness, 'ensure_game_running'), \
                patch.dict('os.environ', {'ROBOTRON_NEUTRAL_LEAD_RESET':'0','ROBOTRON_TRANSITION_DIAGNOSTICS':'0'}):
            with self.assertRaises(KeyboardInterrupt):
                harness.play_vision_game(b, perception, Mock(), hold_action=1)
        self.assertEqual([(c.args[0],c.kwargs['controlled']) for c in b.record_command.call_args_list],
                         [(3,True),(3,False),(0,False),(0,False),(3,True)])


if __name__ == '__main__':
    unittest.main()
