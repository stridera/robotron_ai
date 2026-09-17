"""Tests for the capture-chain latency tool's pure parts (no hardware)."""
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location(
    "mcap", Path(__file__).resolve().parents[1] / "tools" / "measure_capture_latency.py")
mcap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mcap)


class CaptureLatencyToolTest(unittest.TestCase):
    def test_first_crossing_rising_ignores_samples_before_flip(self):
        s = [(0.0, 200.0), (1.0, 10.0), (1.02, 10.0), (1.05, 220.0), (1.07, 230.0)]
        self.assertEqual(mcap.first_crossing(s, 1.0, 128.0, rising=True), 1.05)

    def test_first_crossing_falling(self):
        s = [(1.0, 250.0), (1.03, 250.0), (1.04, 5.0)]
        self.assertEqual(mcap.first_crossing(s, 1.0, 128.0, rising=False), 1.04)

    def test_first_crossing_none_when_not_seen(self):
        self.assertIsNone(mcap.first_crossing([(1.0, 10.0), (1.1, 10.0)], 1.0, 128.0, True))

    def test_pair_diffs_skips_missing(self):
        self.assertEqual(mcap.pair_diffs([10.0, None, 30.0], [50.0, 60.0, 35.0]), [40.0, 5.0])

    def test_probe_wait_crossing_reports_ms_after_flip(self):
        import time
        p = mcap.Probe("fake")
        now = time.perf_counter()
        p.push(now, 0.0)
        p.push(now + 0.0301, 255.0)
        self.assertAlmostEqual(p.wait_crossing(now, 128.0, True, 1.0), 30.1, places=0)

    def test_summary(self):
        s = mcap.summarize([10.0, 20.0, 30.0, 40.0, 50.0])
        self.assertEqual(s["n"], 5)
        self.assertEqual(s["median_ms"], 30.0)
        self.assertEqual(mcap.summarize([])["n"], 0)


if __name__ == "__main__":
    unittest.main()
