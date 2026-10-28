"""Tick-count durations hold their wall-clock length across decision tick
rates, and the console echoes the effective settings at startup.

Run from the package's parent directory:
    python -m unittest robotron_ai.tests.test_tick_scale -v
"""
import contextlib
import io
import time
import unittest

from .. import brain as brain_mod
from .. import cli, harness, knobs
from ..engine import clearance_planner as _cp


class FakeBrain:
    lag_ticks = 0.7
    player_lead_ticks = 1.5

    class coaster:
        ttl = brain_mod.COASTER_TTL


class FakeEye:
    max_player_hold = 6


class ScaleTest(unittest.TestCase):
    def tearDown(self):
        _cp.set_tick_scale(1.0)          # TickClock adaptation moves the planner too

    @staticmethod
    def _drive_clock(tick_s, n=200):
        """A TickClock seeded for the default eye-sync that then measures
        `n` ticks of `tick_s` seconds."""
        clock = harness.TickClock(hz=15.0)
        clock.ref_scale = harness.duration_scale(harness.nominal_tick_s(15.0, 55.0))
        clock.last = 0.0
        t = [0.0]
        orig = time.perf_counter
        time.perf_counter = lambda: t[0]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                for _ in range(n):
                    t[0] += tick_s
                    clock._finish()
        finally:
            time.perf_counter = orig
        return clock

    def test_reference_tick_is_bit_identical(self):
        s = harness.duration_scale(harness.nominal_tick_s(15.0, 55.0))   # the default eye-sync
        self.assertEqual(s, 1.0)
        d = harness.scaled_durations(s, 0.7, 1.5, 4, 6, 3.0)
        self.assertEqual(d, dict(lag_ticks=0.7, player_lead=1.5, hold_action=4,
                                 player_hold=6, coaster_ttl=3.0))
        self.assertIs(d['lag_ticks'], 0.7)               # untouched, not recomputed
        # a measured tick within the loop's 8% deadband never moves the scale
        self.assertEqual(self._drive_clock(0.0590).ref_scale, 1.0)

    def test_scaled_at_43_ms(self):
        s = harness.duration_scale(0.043)
        self.assertAlmostEqual(s, 0.0571 / 0.043, places=6)
        d = harness.scaled_durations(s, 0.7, 1.5, 4, 6, 3.0)
        self.assertAlmostEqual(d['lag_ticks'], 0.7 * s)
        self.assertAlmostEqual(d['player_lead'], 1.5 * s)
        self.assertEqual(d['hold_action'], 5)            # 5.31
        self.assertEqual(d['player_hold'], 8)            # 7.97
        self.assertAlmostEqual(d['coaster_ttl'], 3.0 * s)
        # wall-clock length preserved to rounding
        self.assertAlmostEqual(d['lag_ticks'] * 0.043, 0.7 * 0.0571, places=6)

    def test_off_stays_off(self):
        d = harness.scaled_durations(1.33, 0.7, 1.5, 0, 0, None)
        self.assertEqual((d['hold_action'], d['player_hold'], d['coaster_ttl']), (0, 0, None))

    def test_clock_follows_measured_tick(self):
        clock = self._drive_clock(0.043)
        self.assertAlmostEqual(clock.ref_scale, 0.0571 / 0.043, places=3)

    def test_brain_gets_scaled_values_and_auto_lead_keeps_its_own(self):
        b, eye = FakeBrain(), FakeEye()
        td = harness.TickDurations(b, eye, 4)
        s = harness.duration_scale(0.043)
        self.assertTrue(td.apply(s))
        self.assertAlmostEqual(b.lag_ticks, 0.7 * s)
        self.assertEqual(td.hold_action, 5)
        self.assertEqual(eye.max_player_hold, 8)
        td.lead_auto = True
        b.player_lead_ticks = 2.0                         # auto-lead measured this
        td.apply(1.0)
        self.assertEqual(b.player_lead_ticks, 2.0)
        self.assertEqual(b.lag_ticks, 0.7)

    def test_threaded_eye_player_hold_not_scaled(self):
        class Threaded(FakeEye):
            def wait_new(self, *a, **k):
                pass
        eye = Threaded()
        td = harness.TickDurations(FakeBrain(), eye, 4)
        td.apply(1.33)
        self.assertEqual(eye.max_player_hold, 6)


class StartupBlockTest(unittest.TestCase):
    def setUp(self):
        self._applied = dict(knobs.APPLIED)     # other tests' --knob state
        knobs.APPLIED.clear()

    def tearDown(self):
        knobs.APPLIED.update(self._applied)

    def _block(self, argv, env):
        return "\n".join(cli.startup_block(cli.resolve_config(argv), env))

    def test_block_lists_settings_and_pinned_knobs(self):
        text = self._block(["--mode", "hardware", "--tag", "ab1", "--port", "COM5", "--conf", "0.35",
                            "--eye-sync", "40", "--capture-backend", "magewell",
                            "--sessions-dir", "D:/s"],
                           {"VSEARCH_CLEAR_DANGER": "24", "FSM_HUNT": "2"})
        for want in ("tag=ab1", "sessions=D:/s", "port=COM5", "conf=0.35", "eye-sync=40",
                     "capture=magewell/lowlatency", "FSM_HUNT=2", "VSEARCH_CLEAR_DANGER=24",
                     "hold-action=5", "x1.36"):
            self.assertIn(want, text)
        self.assertLessEqual(len(text.splitlines()), 6)

    def test_default_block_shows_unscaled_values(self):
        text = self._block(["--mode", "hardware"], {})
        self.assertIn("x1.00", text)
        self.assertIn("lag=0.70 lead=1.50 hold-action=4 player-hold=6", text)
        self.assertIn("knobs pinned: none", text)


if __name__ == "__main__":
    unittest.main()
