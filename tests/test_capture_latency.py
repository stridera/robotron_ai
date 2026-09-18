"""Tests for the capture-chain tool's pure parts (no hardware)."""
import importlib.util
from pathlib import Path
import unittest

import numpy as np

SPEC = importlib.util.spec_from_file_location(
    "mcap", Path(__file__).resolve().parents[1] / "tools" / "measure_capture_latency.py")
mcap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mcap)


def thumb(fill, size=32):
    """Stand-in for the fixed-size centre patch each probe reduces its view
    to before the change test."""
    return np.full((size, size, 3), fill, dtype=np.int16)


class LatencyPartsTest(unittest.TestCase):
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


class FreshnessPartsTest(unittest.TestCase):
    def test_changed_ignores_noise_below_threshold(self):
        self.assertFalse(mcap.changed(thumb(100), thumb(100 + mcap.CHANGE_THR)))
        self.assertTrue(mcap.changed(thumb(100), thumb(100 + mcap.CHANGE_THR + 1)))

    def test_changed_fires_on_a_single_cell(self):
        a, b = thumb(0), thumb(0)
        b[10, 20, 1] = 255
        self.assertTrue(mcap.changed(a, b))

    def test_centre_rect_is_centred_and_scales_with_the_frame(self):
        """Each probe crops the same centre share of its own frame, so a 720p
        and a 1080p capture reduce to the same patch and neither is penalised
        for having fewer source pixels — the flaw in a fixed-grid change
        test, which samples 144 points at 1080p and only 64 at 720p."""
        for w, h in [(1920, 1080), (1280, 720)]:
            x0, y0, x1, y1 = mcap.centre_rect(w, h, 0.25)
            self.assertEqual(x1 - x0, w // 4)
            self.assertEqual(y1 - y0, h // 4)
            self.assertAlmostEqual((x0 + x1) / 2, w / 2, delta=1)
            self.assertAlmostEqual((y0 + y1) / 2, h / 2, delta=1)

    def test_beacon_covers_the_area_both_probes_watch(self):
        """The card's crop must sit inside the beacon, or the freshness count
        would depend on where the moving shapes happen to be."""
        self.assertLess(mcap.HDMI_ROI_FRAC, mcap.BEACON_FRAC)
        for w, h in [(1920, 1080), (3440, 1440)]:
            bx0, by0, bx1, by1 = mcap.centre_rect(w, h, mcap.BEACON_FRAC)
            hx0, hy0, hx1, hy1 = mcap.centre_rect(w, h, mcap.HDMI_ROI_FRAC)
            self.assertLessEqual(bx0, hx0)
            self.assertGreaterEqual(bx1, hx1)
            self.assertLessEqual(by0, hy0)
            self.assertGreaterEqual(by1, hy1)
            self.assertGreaterEqual(bx1 - bx0, mcap.SCREEN_ROI)
            self.assertGreaterEqual(by1 - by0, mcap.SCREEN_ROI)

    def test_first_frame_counts_as_changed(self):
        self.assertTrue(mcap.changed(None, thumb(0)))

    def test_push_counts_only_changed_frames(self):
        p = mcap.Probe("fake")
        p.begin_window()
        p.push(0.0, 0.0, thumb(0))          # first: counts
        p.push(0.1, 0.0, thumb(2))          # within threshold: duplicate
        p.push(0.2, 0.0, thumb(200))        # real change
        p.push(0.3, 0.0, thumb(200))        # identical: duplicate
        w = p.window_rates()
        self.assertEqual(w["samples"], 4)
        self.assertEqual(w["unique"], 2)

    def test_push_without_sig_does_not_count_unique(self):
        p = mcap.Probe("fake")
        p.push(0.0, 1.0)
        self.assertEqual(p.unique, 0)
        self.assertEqual(p.count, 1)

    def test_kept_fraction(self):
        self.assertAlmostEqual(mcap.kept_fraction(60.0, 30.0), 0.5)
        self.assertIsNone(mcap.kept_fraction(0.0, 30.0))


class ShapeAnimationTest(unittest.TestCase):
    def test_shapes_fit_inside_the_frame(self):
        for s in mcap.make_shapes(1920, 1080):
            self.assertGreaterEqual(s["x"], 0)
            self.assertGreaterEqual(s["y"], 0)
            self.assertLessEqual(s["x"] + s["w"], 1920)
            self.assertLessEqual(s["y"] + s["h"], 1080)

    def test_every_frame_moves_a_lot_of_shape_area(self):
        """A shape reversing on top of itself can net near-zero movement for
        one frame (the reason the naive clamp was replaced by a reflection),
        so the guarantee is at the frame level, not per shape."""
        shapes = mcap.make_shapes(1920, 1080)
        for _ in range(500):
            moves = mcap.step_shapes(shapes, 1920, 1080)
            total = sum(abs(dx) + abs(dy) for dx, dy in moves)
            self.assertGreater(total, 40.0)

    def test_consecutive_palette_colors_clear_the_change_threshold(self):
        """The beacon is what guarantees a frame differs from the one before,
        so every step of the palette must move a channel by more than the
        change threshold, including the wrap from the last entry to the
        first."""
        def rgb(c):
            return [int(c[i:i + 2], 16) for i in (1, 3, 5)]
        pal = mcap.PALETTE
        for i in range(len(pal)):
            a, b = rgb(pal[i]), rgb(pal[(i + 1) % len(pal)])
            self.assertGreater(max(abs(x - y) for x, y in zip(a, b)), mcap.CHANGE_THR,
                               f"{pal[i]} -> {pal[(i + 1) % len(pal)]}")

    def test_colors_rotate_so_no_frame_repeats_the_previous_one(self):
        shapes = mcap.make_shapes(1920, 1080)
        for k in range(40):
            a = mcap.frame_colors(shapes, k)
            b = mcap.frame_colors(shapes, k + 1)
            self.assertEqual(len(a), len(shapes))
            for x, y in zip(a, b):
                self.assertNotEqual(x, y)

    def test_shapes_stay_in_bounds_while_bouncing(self):
        shapes = mcap.make_shapes(1920, 1080)
        for _ in range(500):
            mcap.step_shapes(shapes, 1920, 1080)
            for s in shapes:
                self.assertGreaterEqual(s["x"], 0)
                self.assertGreaterEqual(s["y"], 0)
                self.assertLessEqual(s["x"] + s["w"], 1920)
                self.assertLessEqual(s["y"] + s["h"], 1080)


if __name__ == "__main__":
    unittest.main()
