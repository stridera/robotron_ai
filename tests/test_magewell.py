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


class DeviceClockCardMsTest(unittest.TestCase):
    """card_ms must come entirely off the device's own tick clock, never off
    host datetime.now() — which pymagewell stamps transfer_complete with, and
    which the device_time_to_dev_s round-trip must not touch. Pure logic, no
    pymagewell needed."""

    def test_card_ms_uses_the_device_clock_not_transfer_complete(self):
        from datetime import datetime, timedelta

        class FakeInitTime:
            system_time_as_datetime = datetime(2026, 1, 1, 0, 0, 0)
            device_time_in_s = 1000.0

        class FakeDevice:
            _device_init_time = FakeInitTime()

        class FakeTimestamps:
            buffering_started = FakeInitTime.system_time_as_datetime + timedelta(milliseconds=5)
            buffering_complete = FakeInitTime.system_time_as_datetime + timedelta(milliseconds=15)
            transfer_started = FakeInitTime.system_time_as_datetime + timedelta(milliseconds=6)
            # A coarse, independent host datetime.now() stamp, exactly as
            # pymagewell produces for transfer_complete — 300 ms off, to
            # prove it plays no part in card_ms.
            transfer_complete = FakeInitTime.system_time_as_datetime + timedelta(milliseconds=300)

        class FakeFrame:
            timestamps = FakeTimestamps()

        device = FakeDevice()
        dev_now_s = 1000.020   # 20 ms after init, read on the device's own clock
        out = magewell.frame_timestamps(FakeFrame(), dev_now_s, device)
        # buffering_started is 5 ms after init -> device seconds 1000.005;
        # dev_now_s is 1000.020 -> card_ms = 15.0, unaffected by
        # transfer_complete's 300 ms host-clock stamp above.
        self.assertAlmostEqual(out["card_ms"], 15.0, places=6)

    def test_card_ms_is_none_without_a_device_clock(self):
        """No _get_device_time_in_s reading (dev_now_s=None, as for the mock,
        which has no device clock) -> card_ms stays None, never a fallback
        computed off host datetime.now()."""
        class FakeTimestamps:
            buffering_started = buffering_complete = transfer_started = transfer_complete = None

        class FakeFrame:
            timestamps = FakeTimestamps()

        out = magewell.frame_timestamps(FakeFrame(), None, object())
        self.assertIsNone(out["card_ms"])


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

    def test_sdk_timestamps_are_passed_to_on_frame_ts(self):
        """The mock fills in real datetimes for all four SDK timestamps, so
        this exercises the actual field names (magewell.TIMESTAMP_KEYS),
        not a stand-in. on_frame's (frame, t) signature must stay untouched.
        The mock has no device clock, so card_ms must come back None rather
        than fall back to (and silently mix in) host datetime.now()."""
        seen_frames, seen_ts = [], []
        src = self._source(on_frame=lambda f, t: seen_frames.append((f.shape, t)),
                           on_frame_ts=lambda ts, t: seen_ts.append((ts, t)))
        try:
            deadline = time.time() + 6.0
            while (not seen_ts or not seen_frames) and time.time() < deadline:
                time.sleep(0.05)
        finally:
            src.release()
        self.assertTrue(seen_ts)
        self.assertTrue(seen_frames)
        ts, t = seen_ts[0]
        for key in magewell.TIMESTAMP_KEYS:
            self.assertIn(key, ts)
            self.assertIsNotNone(ts[key], f"{key} was None; the mock should fill it")
        self.assertIn("card_ms", ts)
        self.assertIsNone(ts["card_ms"])
        self.assertEqual(t, seen_frames[0][1])   # same perf_counter as on_frame's

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


@needs_pymagewell
class BuildPerceptionMagewellTest(unittest.TestCase):
    """cli._build_perception(cfg) with --capture-backend magewell, wired to
    the mock device instead of a real card. VisionPerception itself (YOLO) is
    stubbed out: this test is about the capture wiring, not the model."""

    def test_capture_backend_magewell_gives_a_working_source(self):
        import argparse
        import os
        from unittest import mock
        from pymagewell import MockProCaptureDevice
        from pymagewell.pro_capture_device.device_settings import ColourFormat
        from .. import cli

        # The mock only serves RGB24 without ffmpeg installed (see
        # MockDeviceTest above); cli.py always asks for BGR24 (the real
        # card's format), so the substitute device factory downgrades the
        # request before handing it to the mock, same as a real card would
        # just be asked for RGB24 instead. Not a claim about the real card.
        def mock_factory(settings):
            settings.color_format = ColourFormat.RGB24
            return MockProCaptureDevice(settings)

        cfg = argparse.Namespace(
            # The mock only ever serves 1920x1080 (see MockDeviceTest above);
            # request that as the capture size so the transfer succeeds, and
            # let MagewellSource.read() downscale to the model's 1280x720.
            input="yolo", source="hdmi", device=None, capture_res="1920x1080",
            capture_backend="magewell",
            magewell_mode="timer",     # the mock only supports TIMER, not lowlatency
            magewell_chunk=64, capture_fourcc=None, capture_fps=None,
            weights=os.path.abspath(__file__), conf=0.30, track=False,
            player_hold=6, imgsz=None, center_off=None, visualize=False,
            threaded_eye=False, eye_sync=0)

        class StubVisionPerception:
            def __init__(self, source, weights, **kw):
                self.source = source

        with mock.patch.object(magewell, "open_device", mock_factory), \
             mock.patch.object(cli.perc, "VisionPerception", StubVisionPerception):
            perception = cli._build_perception(cfg)
        source = perception.source
        try:
            self.assertEqual(source.info["backend"], "magewell-sdk")
            deadline = time.time() + 6.0
            frame = source.read()
            while frame is None and time.time() < deadline:
                time.sleep(0.05)
                frame = source.read()
            self.assertIsNotNone(frame)
            self.assertEqual(frame.shape, (720, 1280, 3))
        finally:
            source.release()


if __name__ == "__main__":
    unittest.main()
