"""Tests for the reversal-based loop-latency estimator and the auto-lead rule.

Run from the package's parent directory:
    python -m unittest robotron_ai.tests.test_reversal -v
"""
import unittest

from .. import harness, telemetry
from ..engine.clearance_planner import DXY


def _run(lag, n_reversals=12, hold=20):
    """A player that follows each command `lag` ticks late at nominal speed;
    commands alternate E/W every `hold` ticks."""
    est = telemetry.ReversalEstimator(DXY)
    x, y = 300.0, 200.0
    cmds = []
    for r in range(n_reversals * 2):
        mv = 3 if r % 2 == 0 else 7
        for _ in range(hold):
            cmds.append(mv)
            eff = cmds[-1 - lag] if len(cmds) > lag else 0
            dx, dy = DXY.get(eff, (0.0, 0.0))
            x += dx
            y += dy
            est.tick(mv, (x, y))
    return est.stats()


class ReversalEstimatorTest(unittest.TestCase):
    def test_measures_injected_lag(self):
        for lag in (1, 2, 3, 4):
            s = _run(lag)
            self.assertEqual(s['median'], lag, s)
            self.assertGreaterEqual(s['n'], 10)
            self.assertEqual(s['unresolved'], 0)

    def test_blind_ticks_do_not_break_it(self):
        est = telemetry.ReversalEstimator(DXY)
        x = 300.0
        cmds = []
        for r in range(40):
            mv = 3 if (r // 10) % 2 == 0 else 7
            cmds.append(mv)
            eff = cmds[-3] if len(cmds) > 2 else 0
            x += DXY.get(eff, (0.0, 0.0))[0]
            est.tick(mv, None if r % 7 == 0 else (x, 200.0))
        s = est.stats()
        self.assertTrue(s['n'] == 0 or s['median'] in (2, 3))

    def test_forty_five_degree_turns_are_ignored(self):
        est = telemetry.ReversalEstimator(DXY)
        x, y = 300.0, 200.0
        for r in range(60):
            mv = 3 if (r // 10) % 2 == 0 else 4      # E then SE: not a reversal
            dx, dy = DXY[mv]
            x += dx
            y += dy
            est.tick(mv, (x, y))
        self.assertEqual(est.stats()['n'], 0)


class AutoLeadRuleTest(unittest.TestCase):
    def test_emulator_stays_at_validated_lead(self):
        self.assertEqual(harness.auto_lead_target(2, True), 1.5)

    def test_console_reversal_of_three_gives_two_and_a_half(self):
        self.assertEqual(harness.auto_lead_target(3, True), 2.5)
        self.assertEqual(harness.auto_lead_target(4, True), 3.5)
        self.assertEqual(harness.auto_lead_target(9, True), 3.5)   # clamp

    def test_legacy_rule_unchanged(self):
        self.assertEqual(harness.auto_lead_target(1.0, False), 1.5)
        self.assertEqual(harness.auto_lead_target(2.0, False), 2.5)


class CalibrationPersistenceTest(unittest.TestCase):
    def test_round_trip(self):
        import tempfile, shutil, os
        d = tempfile.mkdtemp()
        try:
            tel = telemetry.HardwareTelemetry(DXY, out_dir=d)
            x = 300.0
            cmds = []
            for r in range(400):
                mv = 3 if (r // 10) % 2 == 0 else 7
                cmds.append(mv)
                eff = cmds[-4] if len(cmds) > 3 else 0
                x += DXY.get(eff, (0.0, 0.0))[0]
                tel.tick(mv, (x, 200.0), [], None)
            tel.finalize(player_lead=2.5)
            self.assertTrue(os.path.exists(os.path.join(d, telemetry.HardwareTelemetry.CALIBRATION)))
            cal = telemetry.HardwareTelemetry.load_calibration(d)
            self.assertEqual(cal["reversal_median_ticks"], 3)
            self.assertGreaterEqual(cal["reversal_samples"], 12)
            self.assertEqual(harness.auto_lead_target(cal["reversal_median_ticks"], True), 2.5)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_too_few_samples_is_ignored(self):
        import tempfile, shutil, os, json
        d = tempfile.mkdtemp()
        try:
            with open(os.path.join(d, telemetry.HardwareTelemetry.CALIBRATION), "w") as f:
                json.dump(dict(reversal_median_ticks=3, reversal_samples=4), f)
            self.assertIsNone(telemetry.HardwareTelemetry.load_calibration(d))
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TelemetryReportTest(unittest.TestCase):
    def test_report_carries_reversal_stats(self):
        import tempfile, shutil
        d = tempfile.mkdtemp()
        try:
            tel = telemetry.HardwareTelemetry(DXY, out_dir=d)
            x = 300.0
            cmds = []
            for r in range(80):
                mv = 3 if (r // 10) % 2 == 0 else 7
                cmds.append(mv)
                eff = cmds[-4] if len(cmds) > 3 else 0
                x += DXY.get(eff, (0.0, 0.0))[0]
                tel.tick(mv, (x, 200.0), [], None)
            rep = tel.report()
            self.assertIn('reversal_ticks', rep)
            self.assertEqual(rep['reversal_ticks']['median'], 3)
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
