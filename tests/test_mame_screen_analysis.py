import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location("analysis", Path(__file__).resolve().parents[1]
                                           / "tools/analyze_collision_mame.py")
analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analysis)


class MameScreenAnalysisTests(unittest.TestCase):
    def test_non_gameplay_score_cannot_create_a_false_winner(self):
        text = '[lab] game 1/1: maxW 21 score 41242365 deaths 24 steps 7066'
        valid, rejected = analysis.completed_games(text, 'turn2', '25004')
        self.assertFalse(valid)
        self.assertEqual(rejected['turn2-25004-0'], 'invalid score: not a multiple of 25')

    def test_worker_error_after_game_line_is_not_counted_as_success(self):
        text = """[lab] game 1/1: maxW 27 score 700000 deaths 21 steps 9000
Traceback (most recent call last):
RuntimeError: emulator shutdown failed
"""
        valid, rejected = analysis.completed_games(text, "base", "9930")
        self.assertFalse(valid)
        self.assertEqual(rejected, {"base-9930-0": "worker traceback"})

    def test_recovery_and_repeated_seed_segment_are_excluded(self):
        text = """[lab] game 1/4: maxW 27 score 700000 deaths 21 steps 9000
[mame_bridge:9930] instance wedged — relaunching
[lab] game 2/4: maxW 3 score 0 deaths 0 steps 205
[lab] game 3/4: maxW 27 score 710000 deaths 20 steps 9001
"""
        valid, rejected = analysis.completed_games(text, "base", "9930")
        self.assertEqual(set(valid), {"base-9930-0"})
        self.assertEqual(set(rejected), {"base-9930-1", "base-9930-2"})
        self.assertNotIn("base-9930-3", valid)  # unfinished fourth game

    def test_smoke_does_not_get_a_spurious_zero_width_confidence_interval(self):
        games = [dict(n=10, d=10, s=250000, wave=15)]
        report = analysis.summarize({"base": games, "four": games}, "base", 144)
        self.assertEqual(report["comparisons_to_baseline"], {})
        self.assertEqual(report["arms"]["base"]["mean_max_wave"], 15)
        self.assertEqual(report["arms"]["base"]["aggregate"]["net_lives_per_wave"], 0)


if __name__ == "__main__":
    unittest.main()
