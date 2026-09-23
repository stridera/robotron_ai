"""Capture from a Magewell Pro Capture card through Magewell's own SDK,
bypassing DirectShow.

Why this exists (2026-09-22). The console loop is ~55 ms behind the emulator
and ~36 of those are the capture path as measured on the loopback: with
OpenCV's DirectShow backend the card hands over a frame only after it has
been fully received and passed through a driver buffer. Magewell's SDK has a
low-latency mode in which the host starts pulling a frame while the card is
still receiving it, in chunks of 64 lines ("partial notification"). Magewell
measures 1080p60 capture at 32.0 ms in normal mode and 17.7 ms in that mode.
There is no driver checkbox on this card; the mode is only reachable through
the SDK, which is why this module exists.

`pymagewell` (MIT, KCL) wraps the SDK and ships LibMWCapture.dll, so the only
install step is `pip install pymagewell`; the card's normal driver must be
present (it is, DirectShow works through it). Three transfer modes:

    lowlatency  transfer starts when the first 64 lines of a frame have
                landed on the card (Magewell's partial-notification recipe)
    normal      transfer starts when the whole frame is on the card; the
                same event DirectShow waits for, minus its own buffering
    timer       software-timed grabs; the only mode the mock device offers,
                used by the tests on machines without a card

The card scales on-board, so we ask it for 1280x720 BGR24 directly: no
MJPG decode, no colour conversion and no resize on the PC.

One correction to pymagewell's low-latency path. Its start_a_frame_transfer
always transfers `iNewestBufferedFullFrame`, the last COMPLETE frame, in
every mode. Magewell's low-latency recipe transfers `iNewestBuffering`, the
frame that is arriving right now; with the complete frame the partial
notification returns at once and nothing is gained. LowLatencyProCaptureDevice
below makes that one change.

Nothing here is verified against a card yet: this machine has none. The
loopback tool (`tools/measure_capture_latency.py --capture-backend magewell`)
is the test, and it prints hdmi-minus-screen for each mode so the three can be
compared in one sitting.
"""
import threading
import time

import numpy as np

from .perception import FrameSource

MODES = ("lowlatency", "normal", "timer")
DEFAULT_CHUNK_LINES = 64

try:
    import pymagewell as _pm
    from pymagewell.pro_capture_device.device_settings import (
        ProCaptureSettings, ImageSizeInPixels, ColourFormat, TransferMode)
    from pymagewell.pro_capture_device.pro_capture_device import ProCaptureDevice
    from pymagewell.pro_capture_controller import ProCaptureController
    from pymagewell.exceptions import ProCaptureError, WaitForEventTimeout
    HAVE_PYMAGEWELL = True
except ImportError:                             # pragma: no cover - env dependent
    _pm = None
    HAVE_PYMAGEWELL = False


def _need():
    if not HAVE_PYMAGEWELL:
        raise ImportError("the magewell capture backend needs pymagewell: "
                          ".venv\\Scripts\\pip install pymagewell")


def transfer_mode(mode):
    _need()
    try:
        return {"lowlatency": TransferMode.LOW_LATENCY, "normal": TransferMode.NORMAL,
                "timer": TransferMode.TIMER}[mode]
    except KeyError:
        raise ValueError(f"magewell mode must be one of {MODES}, not {mode!r}")


def make_settings(width, height, mode, chunk_lines=DEFAULT_CHUNK_LINES, colour="BGR24"):
    """What we ask the card for. The card scales to width x height itself."""
    _need()
    return ProCaptureSettings(dimensions=ImageSizeInPixels(cols=int(width), rows=int(height)),
                              color_format=ColourFormat[colour],
                              transfer_mode=transfer_mode(mode),
                              num_lines_per_chunk=int(chunk_lines))


def frame_index_for_transfer(buffer_status, mode):
    """Which on-board frame to pull. Low latency: the one being received
    (iNewestBuffering, which pymagewell exposes under the misleading name
    num_chunks_being_buffered). Otherwise the newest complete frame."""
    if mode == "lowlatency":
        return int(buffer_status.num_chunks_being_buffered)
    return int(buffer_status.last_buffered_frame_index)


TIMESTAMP_KEYS = ("buffering_started", "buffering_complete",
                  "transfer_started", "transfer_complete")


def device_time_to_dev_s(dt, init):
    """Invert pymagewell's device_time_to_system_time (device_status.py): map
    one of its mapped datetimes (buffering_started/complete, transfer_started)
    back to the device's own tick clock, so it can be compared to another
    device-clock reading without going through host datetime.now() — which on
    Windows ticks at 15.6 ms and would swamp a sub-frame latency figure."""
    return (dt - init.system_time_as_datetime).total_seconds() + init.device_time_in_s


def frame_timestamps(frame, dev_now_s, device):
    """The SDK's own clock for this frame: pymagewell's VideoFrame.timestamps
    (buffering_started/complete, transfer_started/complete — all datetimes
    mapped from the card's tick clock, EXCEPT transfer_complete, which
    pymagewell stamps with a genuine host datetime.now() and must never be
    mixed with the device clock) plus `card_ms`, computed entirely on the
    device clock: time from the first line of this frame reaching the card
    (buffering_started) to Python holding the whole frame (`dev_now_s`, read
    right after transfer_when_ready() returned). None per key, and `card_ms`
    None, if the device did not fill a timestamp or has no device clock (the
    mock has neither) — this must never crash the pump."""
    ts = getattr(frame, "timestamps", None)
    out = {k: getattr(ts, k, None) for k in TIMESTAMP_KEYS} if ts is not None \
        else {k: None for k in TIMESTAMP_KEYS}
    out["card_ms"] = None
    init = getattr(device, "_device_init_time", None)
    bs = out.get("buffering_started")
    if dev_now_s is not None and init is not None and bs is not None:
        out["card_ms"] = (dev_now_s - device_time_to_dev_s(bs, init)) * 1000.0
    return out


if HAVE_PYMAGEWELL:
    from ctypes import addressof
    from datetime import timedelta
    from mwcapture.libmwcapture import (
        MW_SUCCEEDED, MWCAP_VIDEO_DEINTERLACE_BLEND, MWCAP_VIDEO_ASPECT_RATIO_CROPPING,
        MWCAP_VIDEO_COLOR_FORMAT_UNKNOWN, MWCAP_VIDEO_QUANTIZATION_UNKNOWN,
        MWCAP_VIDEO_SATURATION_UNKNOWN)

    class LowLatencyProCaptureDevice(ProCaptureDevice):
        """pymagewell's device with the frame index chosen per mode (see the
        module docstring). Everything else is the parent's."""

        def start_a_frame_transfer(self, frame_buffer):
            ll = self.transfer_mode == TransferMode.LOW_LATENCY
            iframe = frame_index_for_transfer(self.buffer_status, "lowlatency" if ll else "normal")
            seconds_since_init = self._get_device_time_in_s() - self._device_init_time.device_time_in_s
            stamp = self._device_init_time.system_time_as_datetime + timedelta(seconds=seconds_since_init)
            s = self._settings
            result = self.mw_capture_video_frame_to_virtual_address_ex(
                hchannel=self._channel, iframe=iframe, pbframe=addressof(frame_buffer),
                cbframe=s.image_size_in_bytes, cbstride=s.min_stride, bbottomup=False,
                pvcontext=0, dwfourcc=s.color_format.value, cx=s.dimensions.cols,
                cy=s.dimensions.rows, dwprocessswitchs=0,
                cypartialnotify=s.num_lines_per_chunk if ll else 0,
                hosdimage=0, posdrects=0, cosdrects=0, scontrast=100, sbrightness=0,
                ssaturation=100, shue=0, deinterlacemode=MWCAP_VIDEO_DEINTERLACE_BLEND,
                aspectratioconvertmode=MWCAP_VIDEO_ASPECT_RATIO_CROPPING, prectsrc=0,
                prectdest=0, naspectx=0, naspecty=0,
                colorformat=MWCAP_VIDEO_COLOR_FORMAT_UNKNOWN,
                quantrange=MWCAP_VIDEO_QUANTIZATION_UNKNOWN,
                satrange=MWCAP_VIDEO_SATURATION_UNKNOWN)
            if result != MW_SUCCEEDED:
                raise ProCaptureError(f"Frame grab failed with error code {result}")
            return stamp


def channel_count():
    """How many Pro Capture channels the driver reports (0 = no card)."""
    _need()
    from mwcapture.libmwcapture import mw_capture
    c = mw_capture()
    c.mw_capture_init_instance()
    try:
        c.mw_refresh_device()
        return int(c.mw_get_channel_count())
    finally:
        c.mw_capture_exit_instance()


def open_device(settings):
    """A real card, opened with the per-mode frame index. Raises with a
    plain-language message when there is no card or no signal."""
    _need()
    n = channel_count()
    if n <= 0:
        raise RuntimeError("no Magewell Pro Capture channel found: the SDK sees no card. "
                           "Is the Magewell driver installed and the card seated?")
    try:
        return LowLatencyProCaptureDevice(settings)
    except ProCaptureError as e:
        raise RuntimeError(f"Magewell channel 0 did not open: {e}") from e


def describe(device, settings, mode):
    """Everything about the signal and the request that a remote reader
    needs: this runs on someone else's PC and only the text comes back."""
    ss = device.signal_status
    fps = (1.0 / ss.frame_period_s) if ss.frame_period_s else 0.0
    return dict(
        backend="magewell-sdk", mode=mode,
        chunk_lines=settings.num_lines_per_chunk if mode == "lowlatency" else None,
        requested=dict(width=settings.dimensions.cols, height=settings.dimensions.rows,
                       format=settings.color_format.name),
        signal=dict(state=ss.state.name, width=ss.image_dimensions.cols,
                    height=ss.image_dimensions.rows, fps=round(fps, 2),
                    interlaced=ss.interlaced),
        size_request_took_effect=True,      # the card scales to the request
        format_request_confirmable=True,    # the SDK returns the format we asked for
    )


class MagewellSource(FrameSource):
    """The bot's frame source on a Magewell card: same read()/stats()/release()
    surface as perception.HdmiSource, frames pulled on a background thread
    through the SDK. `on_frame(frame, t)` is called from that thread for
    every frame (the loopback tool uses it); `device_factory` lets the tests
    substitute pymagewell's mock device."""

    def __init__(self, width=1280, height=720, mode="lowlatency",
                 chunk_lines=DEFAULT_CHUNK_LINES, colour="BGR24", cap_size=None,
                 device_factory=None, on_frame=None, on_frame_ts=None, quiet=False):
        """`width` x `height` is what read() returns (the model's 1280x720);
        `cap_size` is what the card is asked to deliver, default the same, so
        normally the card does the scaling and read() copies nothing.
        `on_frame_ts(ts, t)` is called from the pump thread alongside
        `on_frame`, with the SDK's own timestamps for that frame (see
        frame_timestamps()) plus the same perf_counter `t`; kept separate from
        `on_frame` so its (frame, t) signature never changes."""
        _need()
        if mode not in MODES:
            raise ValueError(f"magewell mode must be one of {MODES}, not {mode!r}")
        self.w, self.h, self.mode = int(width), int(height), mode
        cw, ch = cap_size if cap_size else (width, height)
        self.settings = make_settings(cw, ch, mode, chunk_lines, colour)
        self.device = (device_factory or open_device)(self.settings)
        try:
            self.controller = ProCaptureController(self.device)   # starts grabbing
        except ProCaptureError as e:
            raise RuntimeError(f"Magewell capture did not start: {e} (no HDMI signal "
                               "on the card's input?)") from e
        self.info = describe(self.device, self.settings, mode)
        if not quiet:
            s = self.info["signal"]
            print(f"[magewell] signal {s['state']} {s['width']}x{s['height']} "
                  f"{s['fps']:.0f}fps -> {cw}x{ch} {colour} via the SDK, "
                  f"mode {mode}" + (f" ({chunk_lines}-line chunks)" if mode == "lowlatency" else ""))
        self._on_frame = on_frame
        self._on_frame_ts = on_frame_ts
        self._lock = threading.Lock()
        self._latest = None
        self._latest_t = None
        self._running = True
        self.error = None
        self.pump_frames = 0
        self.pump_changed = 0
        self.pump_t0 = time.time()
        self._pump_prev = None
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def _pump(self):
        import cv2
        while self._running:
            try:
                frame = self.controller.transfer_when_ready(timeout_ms=2000)
            except WaitForEventTimeout as e:
                # pymagewell shuts the device down on a timeout; nothing
                # more will arrive, so say so once and stop.
                self.error = f"no frame for 2 s: {e}"
                break
            except Exception as e:                  # noqa: BLE001 - a dead pump
                self.error = f"{type(e).__name__}: {e}"    # must be visible
                break
            # Card-clock reading for card_ms, taken immediately: the mock has
            # no device clock, so this is None off it (see frame_timestamps).
            dev_time_fn = getattr(self.device, "_get_device_time_in_s", None)
            dev_now_s = dev_time_fn() if dev_time_fn is not None else None
            t = time.perf_counter()
            arr = frame.as_array()                  # BGR uint8, h x w x 3
            self.pump_frames += 1
            # Publish before the change-test bookkeeping below: read() must
            # never wait on a 64x36 resize + absdiff it does not need.
            with self._lock:
                self._latest, self._latest_t = arr, t
            if self._on_frame_ts is not None:
                self._on_frame_ts(frame_timestamps(frame, dev_now_s, self.device), t)
            tiny = cv2.resize(arr, (64, 36), interpolation=cv2.INTER_AREA)
            if self._pump_prev is None or cv2.absdiff(tiny, self._pump_prev).max() > 8:
                self.pump_changed += 1
            self._pump_prev = tiny
            if self._on_frame is not None:
                self._on_frame(arr, t)
        self._running = False

    def stats(self):
        el = max(time.time() - self.pump_t0, 1e-6)
        return dict(pump_hz=round(self.pump_frames / el, 2),
                    pump_changed_hz=round(self.pump_changed / el, 2),
                    error=self.error)

    def latest_age_s(self):
        with self._lock:
            t = self._latest_t
        return None if t is None else time.perf_counter() - t

    def read(self):
        with self._lock:
            frame = self._latest
        if frame is None:
            return None
        if frame.shape[1] != self.w or frame.shape[0] != self.h:
            import cv2
            frame = cv2.resize(frame, (self.w, self.h), interpolation=cv2.INTER_AREA)
        return frame

    def release(self):
        self._running = False
        self._thread.join(timeout=3.0)
        try:
            self.controller.shutdown()
        except Exception:
            pass
