import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('night', Path(__file__).resolve().parents[1]
                                           / 'tools/run_overnight_mame.py')
night = importlib.util.module_from_spec(spec)
spec.loader.exec_module(night)


def report(delta=.06, low=.01, games=144):
    return dict(complete=True,
                arms={n: dict(completed_valid_games=games, expected_games=games) for n in ('base', 'candidate')},
                comparisons_to_baseline={'candidate': dict(net_delta=delta, bootstrap_95=[low, .10])})


class OvernightQueueTests(unittest.TestCase):
    def test_uncertain_screen_needs_independent_confirmation(self):
        uncertain = report(low=-.02)
        self.assertTrue(night.eligible(uncertain))
        self.assertFalse(night.eligible(uncertain, confirmation=True))
        self.assertTrue(night.eligible(report(games=576), confirmation=True))

    def test_negative_or_incomplete_results_cannot_advance(self):
        self.assertFalse(night.eligible(report(delta=-.02)))
        partial = report()
        partial['complete'] = False
        self.assertFalse(night.eligible(partial))
        partial['complete'] = True
        partial['arms']['candidate']['completed_valid_games'] = 143
        self.assertFalse(night.eligible(partial))


if __name__ == '__main__':
    unittest.main()
