"""The reversal-latency estimator's millisecond figures.

Run from the package's parent directory:
    python -m unittest robotron_ai.tests.test_trace_report_ms -v
"""
import unittest

from .. import trace_report
from ..engine.clearance_planner import DXY


def _rows(tick_s, lag_ticks, n_reversals=6, hold=8, speed=8.0):
    """A player that follows each command `lag_ticks` late, sampled 5 ms
    before each decision; commands alternate E/W every `hold` ticks."""
    E, W = 3, 7
    rows, x, y = [], 300.0, 250.0
    cmds = []
    for r in range(n_reversals + 1):
        cmds += [E if r % 2 == 0 else W] * hold
    for i, c in enumerate(cmds):
        applied = cmds[max(0, i - lag_ticks)]
        dx, dy = DXY[applied]
        x += dx * speed
        y += dy * speed
        rows.append(dict(move=c, player=[x, y], monotonic=i * tick_s,
                         sampled_at=i * tick_s - 0.005))
    return rows


class ReversalMsTest(unittest.TestCase):
    def test_ms_bracket_matches_the_tick_count(self):
        """Round 18: 57 ms ticks, +3 ticks read as seen-by 171 / not-yet 111;
        the emulator's 67 ms ticks at +2 read 117 / 50. Same tick count, a
        different answer in ms, which is why the report prints both."""
        for tick_s, lag in ((0.0571, 3), (0.0667, 2)):
            rl = trace_report.reversal_latency(_rows(tick_s, lag))
            self.assertEqual(rl['median'], lag, (tick_s, rl))
            self.assertAlmostEqual(rl['seen_by_ms'], lag * tick_s * 1000 - 5, delta=1.5)
            self.assertAlmostEqual(rl['not_yet_ms'], (lag - 1) * tick_s * 1000 - 5, delta=1.5)
            self.assertLess(rl['not_yet_ms'], rl['seen_by_ms'])

    def test_rows_without_timestamps_still_report_ticks(self):
        rows = _rows(0.0667, 2)
        for r in rows:
            r.pop('monotonic'); r.pop('sampled_at')
        rl = trace_report.reversal_latency(rows)
        self.assertEqual(rl['median'], 2)
        self.assertIsNone(rl['seen_by_ms'])
        self.assertIsNone(rl['not_yet_ms'])


if __name__ == "__main__":
    unittest.main()
