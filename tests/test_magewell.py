"""The Magewell SDK capture source, driven by pymagewell's mock device.

The mock only offers the timer transfer mode, 1920x1080 RGB24 at 2 fps, so
these tests cover the plumbing (settings, frame delivery, resize, stats,
callback, release) and the frame-index rule; the low-latency path itself can
only be measured on a machine with the card, with
tools/measure_capture_latency.py --capture-backend magewell.

Run from the package's parent directory:
    python -m unittest robotron_ai.tests.test_magewell -v
"""
import time
import unittest

from .. import magewell

needs_pymagewell = unittest.skipUnless(magewell.HAVE_PYMAGEWELL, "pymagewell not installed")


class FrameIndexRuleTest(unittest.TestCase):
    def test_low_latency_pulls_the_frame_being_received(self):
        class Status:
            num_chunks_being_buffered = 5      # pymagewell's name for iNewestBuffering
            last_buffered_frame_index = 4      # iNewestBufferedFullFrame
        self.assertEqual(magewell.frame_index_for_transfer(Status(), "lowlatency"), 5)
        self.assertEqual(magewell.frame_index_for_transfer(Status(), "normal"), 4)
        self.assertEqual(magewell.frame_index_for_transfer(Status(), "timer"), 4)


@needs_pymagewell
class SettingsTest(unittest.TestCase):
    def test_settings_ask_the_card_for_the_model_size_and_mode(self):
        from pymagewell.pro_capture_device.device_settings import TransferMode, ColourFormat
        s = magewell.make_settings(1280, 720, "lowlatency", 128)
        self.assertEqual((s.dimensions.cols, s.dimensions.rows), (1280, 720))
        self.assertEqual(s.color_format, ColourFormat.BGR24)
        self.assertEqual(s.transfer_mode, TransferMode.LOW_LATENCY)
        self.assertEqual(s.num_lines_per_chunk, 128)
        self.assertEqual(magewell.make_settings(1280, 720, "normal").transfer_mode,
                         TransferMode.NORMAL)
        with self.assertRaises(ValueError):
            magewell.make_settings(1280, 720, "fast")
        with self.assertRaises(ValueError):
            magewell.make_settings(1280, 720, "lowlatency", 100)   # not a power of two

    def test_low_latency_device_overrides_only_the_transfer(self):
        from pymagewell.pro_capture_device.pro_capture_device import ProCaptureDevice
        self.assertTrue(issubclass(magewell.LowLatencyProCaptureDevice, ProCaptureDevice))
        self.assertIn("start_a_frame_transfer", vars(magewell.LowLatencyProCaptureDevice))


@needs_pymagewell
class MockDeviceTest(unittest.TestCase):
    def _source(self, **kw):
        from pymagewell import MockProCaptureDevice
        # The mock serves fixed 1920x1080 RGB24 frames, so ask it for that
        # and let read() scale to the model size, as a 1080p card request would.
        return magewell.MagewellSource(width=1280, height=720, cap_size=(1920, 1080),
                                       mode="timer", colour="RGB24",
                                       device_factory=MockProCaptureDevice, quiet=True, **kw)

    def test_frames_arrive_resized_with_stats_and_callback(self):
        seen = []
        src = self._source(on_frame=lambda f, t: seen.append((f.shape, t)))
        try:
            deadline = time.time() + 6.0
            while src.read() is None and time.time() < deadline:
                time.sleep(0.05)
            frame = src.read()
            self.assertIsNotNone(frame, src.stats())
            self.assertEqual(frame.shape, (720, 1280, 3))
            self.assertEqual(frame.dtype.name, "uint8")
            self.assertEqual(seen[0][0], (1080, 1920, 3))    # raw mock frame, pre-resize
            self.assertIsNotNone(src.latest_age_s())
            st = src.stats()
            self.assertGreater(st["pump_hz"], 0)
            self.assertIsNone(st["error"])
            self.assertEqual(src.info["signal"]["width"], 1920)
            self.assertEqual(src.info["mode"], "timer")
        finally:
            src.release()
        self.assertFalse(src._thread.is_alive())

    def test_bad_mode_is_refused_before_touching_a_device(self):
        with self.assertRaises(ValueError):
            magewell.MagewellSource(mode="fastest", device_factory=lambda s: None)

    def test_a_pump_failure_is_reported_not_swallowed(self):
        """A size the mock cannot serve makes its transfer raise ValueError;
        the first version of the pump died silently on exactly that."""
        from pymagewell import MockProCaptureDevice
        src = magewell.MagewellSource(width=1280, height=720, mode="timer", colour="RGB24",
                                      device_factory=MockProCaptureDevice, quiet=True)
        try:
            deadline = time.time() + 6.0
            while src.stats()["error"] is None and time.time() < deadline:
                time.sleep(0.05)
            self.assertIsNotNone(src.stats()["error"])
            self.assertIn("ValueError", src.stats()["error"])
        finally:
            src.release()


if __name__ == "__main__":
    unittest.main()
