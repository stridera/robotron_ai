import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[2] / 'robotron/mame_score.py'
spec = importlib.util.spec_from_file_location('score', path)
score = importlib.util.module_from_spec(spec)
spec.loader.exec_module(score)


class ScoreMeasurementTests(unittest.TestCase):
    def test_digit_carry_dip_preserves_total_without_double_counting(self):
        events = []
        m = score.ScoreMeasurement(366875, events.append)
        values = [m.observe(n) for n in (366800, 366900, 366900)]
        self.assertEqual(values, [366875, 366900, 366900])
        self.assertEqual(values[-1] - 366875, 25)
        self.assertEqual([e['kind'] for e in events], ['pending', 'settled'])

    def test_carry_across_thousands_then_rescue(self):
        m = score.ScoreMeasurement(369975)
        self.assertEqual(m.observe(360000), 369975)
        self.assertEqual(m.observe(370000), 370000)
        self.assertEqual(m.observe(375000), 375000)

    def test_terminal_garbage_never_becomes_income(self):
        m = score.ScoreMeasurement(572025)
        self.assertEqual(m.observe(41242365), 572025)
        self.assertEqual(m.observe(41242365, terminal=True), 572025)

    def test_persistent_bad_score_is_rejected(self):
        m = score.ScoreMeasurement(5000)
        for _ in range(3):
            self.assertEqual(m.observe(0), 5000)
        with self.assertRaisesRegex(RuntimeError, 'INVALID_SCORE_PERSISTENT'):
            m.observe(0)

    def test_recovery_cannot_be_hidden_by_score_filter(self):
        m = score.ScoreMeasurement(5000)
        with self.assertRaisesRegex(RuntimeError, 'RECOVERED_EPISODE'):
            m.observe(0, terminal=True, recovered=True)


if __name__ == '__main__':
    unittest.main()
