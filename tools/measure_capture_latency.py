"""Measure the CAPTURE chain in isolation: GPU HDMI output -> capture card ->
OpenCV frame in this process, against the screen-capture path the emulator
uses. Reports both halves of frame age: how long a change takes to arrive
(latency) and how often a genuinely new frame arrives (freshness).

Run a spare HDMI cable from the PC's video card straight into the capture
card. Windows then sees the card as an extra monitor. This tool opens a
full-screen window on that monitor and watches it two ways at once:

  * through the capture card, opened with the same OpenCV flags the bot
    uses (`--device`, `--capture-backend`, `--capture-fourcc`, `--capture-res`);
  * through a screen read of the same monitor (a GDI grab of a square at its
    centre), which is what the emulator's window capture amounts to.

Phase 1, LATENCY: the window flips black/white at random moments and each
flip is timed down both paths. The screen read sees the window as soon as it
is painted, which is also where the emulator's window capture reads, so the
DIFFERENCE between the two is what the console path pays on the video side:
scan-out, the card's frame latency, the format decode and any driver
buffering. The console's own input-to-output pipeline is not in this figure.

Phase 2, FRESHNESS: the window animates moving shapes for a few seconds and
both paths count how many frames actually CHANGED. A large centred beacon
takes the next colour of a twelve-colour palette on every painted frame, so
a frame can never repeat the one before it and both probes, which watch the
centre, count painted frames exactly. The screen read measures what the PC
painted, so it is the source rate and the card can never beat it. Comparing
the two separates "the card is dropping or repeating frames" from "the
source did not produce one", which is the question a count taken off the
capture card alone cannot answer.

Each probe reduces its view to a fixed-size centre patch before the change
test, so the comparison does not depend on capture resolution. This matters:
a change test that samples a fixed pixel grid sees fewer points at lower
capture resolutions and under-counts them for that reason alone (144 points
at 1080p against 64 at 720p, which is enough on its own to make 720p look
half as fresh).

    .venv\\Scripts\\python -m robotron_ai.tools.measure_capture_latency --list
    .venv\\Scripts\\python -m robotron_ai.tools.measure_capture_latency --monitor 2 --device 0 --capture-backend dshow --capture-fourcc MJPG --capture-res 1920x1080

Run it once per capture setting you want to compare (1920x1080 vs 1280x720,
MJPG vs YUY2). To make a 720p row a fair pass-through test, set that monitor
to 1280x720 in Windows display settings first, so the card is fed 720p the
way the console feeds it. Only numpy, OpenCV and the standard library are
needed.
"""
import argparse
import collections
import ctypes
import ctypes.wintypes as wt
import datetime
import json
import math
import platform
import random
import statistics
import sys
import threading
import time

try:
    import numpy as np
except ImportError:            # pure helpers still importable for tests
    np = None

CHANGE_THR = 8                  # level change that counts as a new frame
SCREEN_ROI = 96                 # px grabbed 1:1 at the monitor centre
HDMI_ROI_FRAC = 0.12            # centre share of the card's frame, matched to it
BEACON_FRAC = 0.25              # centre share the beacon covers, larger than both
SRCCOPY = 0x00CC0020


# ── pure helpers (unit tested) ──────────────────────────────────────────────

def summarize(samples):
    if not samples:
        return dict(n=0)
    s = sorted(samples)
    return dict(n=len(s), median_ms=round(statistics.median(s), 1),
                p10_ms=round(s[int(0.1 * len(s))], 1), p90_ms=round(s[int(0.9 * len(s))], 1),
                min_ms=round(s[0], 1), max_ms=round(s[-1], 1))


def first_crossing(samples, t0, threshold, rising):
    """First sample time strictly after t0 whose level is on the new side of
    threshold (above when rising, below when not). `samples` is an iterable
    of (t, level). Returns the time or None."""
    for t, lv in samples:
        if t <= t0:
            continue
        if (lv > threshold) if rising else (lv < threshold):
            return t
    return None


def pair_diffs(a, b):
    """Per-trial (b - a) over trials where both are present."""
    return [y - x for x, y in zip(a, b) if x is not None and y is not None]


def changed(sig_a, sig_b, threshold=CHANGE_THR):
    """True if two signatures differ by more than `threshold` anywhere.
    Each probe reduces its view to a fixed-size patch first, so a 720p
    capture is not penalised for having fewer source pixels — which is the
    flaw in a change test that samples a fixed pixel grid."""
    if sig_a is None or sig_b is None:
        return True
    return int(np.abs(np.asarray(sig_a, dtype=np.int32)
                      - np.asarray(sig_b, dtype=np.int32)).max()) > threshold


def centre_rect(w, h, frac):
    """Centred sub-rectangle covering `frac` of each dimension."""
    cw, ch = max(1, int(w * frac)), max(1, int(h * frac))
    return ((w - cw) // 2, (h - ch) // 2, (w - cw) // 2 + cw, (h - ch) // 2 + ch)


# DirectShow hands OpenCV a CONVERTED buffer and reports the GUID of that
# conversion, not the format negotiated with the card. These are the first
# four bytes of the MEDIASUBTYPE_* GUIDs we see in practice.
DSHOW_SUBTYPES = {0xE436EB7A: "RGB8", 0xE436EB7B: "RGB565", 0xE436EB7C: "RGB555",
                  0xE436EB7D: "RGB24", 0xE436EB7E: "RGB32"}


def fourcc_label(v):
    """Human label for a CAP_PROP_FOURCC value, plus whether it can confirm
    the requested capture format."""
    v = int(v) & 0xFFFFFFFF
    if v in DSHOW_SUBTYPES:
        return (f"{DSHOW_SUBTYPES[v]} (0x{v:08x}) - a DirectShow CONVERTED output, so it "
                f"CANNOT confirm which format the card negotiated")
    chars = "".join(chr((v >> (8 * i)) & 0xFF) for i in range(4))
    if all(32 <= ord(c) < 127 for c in chars):
        return f"{chars.strip()} (0x{v:08x})"
    return f"unprintable (0x{v:08x})"


def fourcc_confirms_request(v):
    """True when the reported format is a real 4CC we can compare against the
    one we asked for."""
    v = int(v) & 0xFFFFFFFF
    if v in DSHOW_SUBTYPES:
        return False
    chars = "".join(chr((v >> (8 * i)) & 0xFF) for i in range(4))
    return all(32 <= ord(c) < 127 for c in chars) and bool(chars.strip())


def kept_fraction(source_unique_hz, card_unique_hz):
    """Share of the source's new frames that survived to the card."""
    if not source_unique_hz:
        return None
    return card_unique_hz / source_unique_hz


def derive_sdk_ms(ts):
    """Card-only latency for one frame, from magewell.frame_timestamps:
    `card_ms` (already computed on the device's own clock — see
    magewell.frame_timestamps/device_time_to_dev_s, never mixed with host
    datetime.now()) and `scanout_ms` = buffering_complete - buffering_started
    (both device-clock-mapped datetimes, so plain subtraction is valid, but
    only meaningful in normal mode: in lowlatency mode buffering_complete is
    unset for the still-buffering frame and maps to a bogus datetime, so any
    result outside 0 < x < 100 ms is rejected to None). None (the whole dict)
    if neither figure is available (e.g. the mock, which has no device
    clock)."""
    from robotron_ai.magewell import TIMESTAMP_KEYS
    if all(ts.get(k) is None for k in TIMESTAMP_KEYS) and ts.get("card_ms") is None:
        return None
    card_ms = ts.get("card_ms")
    scanout_ms = None
    bs, bc = ts.get("buffering_started"), ts.get("buffering_complete")
    if bs is not None and bc is not None:
        candidate = (bc - bs).total_seconds() * 1000.0
        if 0 < candidate < 100:
            scanout_ms = candidate
    if card_ms is None and scanout_ms is None:
        return None
    return dict(card_ms=card_ms, scanout_ms=scanout_ms)


# ── probes ──────────────────────────────────────────────────────────────────

class Probe:
    """A sampler thread that records (t, level) for the latency test and
    counts changed frames for the freshness test."""
    def __init__(self, name):
        self.name = name
        self.samples = collections.deque(maxlen=20000)
        self.lock = threading.Lock()
        self.running = True
        self.count = 0
        self.unique = 0
        self.thread = None
        self._prev_sig = None
        self._window = None

    def start(self):
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False

    def push(self, t, level, sig=None):
        self.count += 1
        if sig is not None:
            if changed(self._prev_sig, sig):
                self.unique += 1
            self._prev_sig = sig
        with self.lock:
            self.samples.append((t, level))

    def begin_window(self):
        self._window = (time.perf_counter(), self.count, self.unique)

    def window_rates(self):
        """Sampling and change rates since begin_window()."""
        t0, c0, u0 = self._window
        dt = max(time.perf_counter() - t0, 1e-6)
        return dict(seconds=round(dt, 1), samples=self.count - c0,
                    sampled_hz=round((self.count - c0) / dt, 1),
                    unique=self.unique - u0,
                    unique_hz=round((self.unique - u0) / dt, 1))

    def snapshot(self):
        with self.lock:
            return list(self.samples)

    def level_now(self, window_s=0.3):
        now = time.perf_counter()
        vals = [lv for t, lv in self.snapshot() if t > now - window_s]
        return statistics.median(vals) if vals else None

    def wait_crossing(self, t0, threshold, rising, timeout_s):
        deadline = t0 + timeout_s
        while time.perf_counter() < deadline:
            t = first_crossing(self.snapshot(), t0, threshold, rising)
            if t is not None:
                return (t - t0) * 1000.0
            time.sleep(0.0005)
        return None

    def _loop(self):
        raise NotImplementedError


class ScreenProbe(Probe):
    """A SCREEN_ROI square at the monitor centre, grabbed 1:1. Deliberately
    small: a GDI grab costs ~7 ms of fixed round-trip whatever its size, and
    downscaling the whole monitor instead costs ~28 ms, which would sample
    slower than the screen repaints and undercount new frames. The animation
    puts a colour-cycling beacon under this square so a small view still sees
    every painted frame."""
    def __init__(self, x, y, w, h, roi=SCREEN_ROI):
        super().__init__("screen")
        self.roi = roi
        self.x, self.y = x + w // 2 - roi // 2, y + h // 2 - roi // 2
        self.user32 = ctypes.windll.user32
        self.gdi32 = ctypes.windll.gdi32
        for fn, res, args in [
            (self.user32.GetDC, wt.HDC, [wt.HWND]),
            (self.user32.ReleaseDC, ctypes.c_int, [wt.HWND, wt.HDC]),
            (self.gdi32.CreateCompatibleDC, wt.HDC, [wt.HDC]),
            (self.gdi32.CreateCompatibleBitmap, wt.HBITMAP, [wt.HDC, ctypes.c_int, ctypes.c_int]),
            (self.gdi32.SelectObject, wt.HGDIOBJ, [wt.HDC, wt.HGDIOBJ]),
            (self.gdi32.BitBlt, wt.BOOL, [wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                          ctypes.c_int, wt.HDC, ctypes.c_int, ctypes.c_int,
                                          wt.DWORD]),
            (self.gdi32.GetDIBits, ctypes.c_int, [wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT,
                                                  ctypes.c_void_p, ctypes.c_void_p, wt.UINT]),
            (self.gdi32.DeleteObject, wt.BOOL, [wt.HGDIOBJ]),
            (self.gdi32.DeleteDC, wt.BOOL, [wt.HDC]),
        ]:
            fn.restype, fn.argtypes = res, args

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                        ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
                        ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                        ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                        ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]

        class BITMAPINFO(ctypes.Structure):
            _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]

        self.bmi = BITMAPINFO()
        self.bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        self.bmi.bmiHeader.biWidth = roi
        self.bmi.bmiHeader.biHeight = -roi
        self.bmi.bmiHeader.biPlanes = 1
        self.bmi.bmiHeader.biBitCount = 32
        self.buf = ctypes.create_string_buffer(roi * roi * 4)

    def _loop(self):
        u, g, roi = self.user32, self.gdi32, self.roi
        sdc = u.GetDC(None)
        mdc = g.CreateCompatibleDC(sdc)
        bmp = g.CreateCompatibleBitmap(sdc, roi, roi)
        old = g.SelectObject(mdc, bmp)
        try:
            while self.running:
                g.BitBlt(mdc, 0, 0, roi, roi, sdc, self.x, self.y, SRCCOPY)
                t = time.perf_counter()
                g.GetDIBits(mdc, bmp, 0, roi, self.buf, ctypes.byref(self.bmi), 0)
                arr = np.frombuffer(self.buf, dtype=np.uint8)
                patch = arr.reshape(roi, roi, 4)[:, :, :3].astype(np.int16)
                self.push(t, float(patch.mean()), patch)
        finally:
            g.SelectObject(mdc, old)
            g.DeleteObject(bmp)
            g.DeleteDC(mdc)
            u.ReleaseDC(None, sdc)


class HdmiProbe(Probe):
    """The bot's capture path: cv2.VideoCapture with the same flags, pumped
    continuously like perception.HdmiSource."""
    def __init__(self, device, backend, fourcc, cap_size):
        super().__init__("hdmi")
        import cv2
        self.cv2 = cv2
        be = {None: cv2.CAP_ANY, "auto": cv2.CAP_ANY, "msmf": cv2.CAP_MSMF,
              "dshow": cv2.CAP_DSHOW}[backend.lower() if backend else None]
        self.cap = cv2.VideoCapture(device, be)
        if fourcc:
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
        if cap_size:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, cap_size[0])
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cap_size[1])
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not self.cap.isOpened():
            sys.exit(f"capture device {device!r} did not open")
        v = int(self.cap.get(cv2.CAP_PROP_FOURCC))
        got_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        got_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.info = dict(
            device=device, backend=backend or "auto",
            requested=dict(fourcc=fourcc, width=cap_size[0] if cap_size else None,
                           height=cap_size[1] if cap_size else None),
            reported=dict(fourcc_raw=v, fourcc=fourcc_label(v), width=got_w, height=got_h,
                          fps=self.cap.get(cv2.CAP_PROP_FPS),
                          backend_name=self.cap.getBackendName()),
            size_request_took_effect=(cap_size is None
                                      or (got_w, got_h) == tuple(cap_size)),
            format_request_confirmable=fourcc_confirms_request(v),
        )
        self.desc = (f"{got_w}x{got_h} {self.info['reported']['fourcc']} "
                     f"{self.cap.get(cv2.CAP_PROP_FPS):.0f}fps "
                     f"(backend {self.info['reported']['backend_name']})")

    def print_info(self):
        i = self.info
        print("=== capture device ===")
        print(f"  index {i['device']}, backend requested {i['backend']}, "
              f"in use {i['reported']['backend_name']}")
        print(f"  requested : {i['requested']['fourcc'] or 'default'} "
              f"{i['requested']['width']}x{i['requested']['height']}")
        print(f"  reports   : {i['reported']['fourcc']} "
              f"{i['reported']['width']}x{i['reported']['height']} "
              f"{i['reported']['fps']:.0f} fps")
        if not i["size_request_took_effect"]:
            print("  !! the card did not accept the requested capture size; it is running at")
            print("     the size above, so this run does not measure the setting you asked for")
        if not i["format_request_confirmable"]:
            print("  NOTE: the reported format is the converted buffer OpenCV hands us, so it")
            print("     cannot confirm the card accepted the requested pixel format. Two runs")
            print("     that differ only in --capture-fourcc may be measuring the same thing.")
        if i["reported"]["fps"] <= 0:
            print("  NOTE: the card does not report a frame rate; the freshness phase below")
            print("     measures the delivered and changed rates directly instead.")

    def _loop(self):
        cv2 = self.cv2
        while self.running:
            if not self.cap.grab():
                time.sleep(0.005)
                continue
            t = time.perf_counter()
            ok, frame = self.cap.retrieve()
            if not ok or frame is None:
                continue
            h, w = frame.shape[:2]
            x0, y0, x1, y1 = centre_rect(w, h, HDMI_ROI_FRAC)
            # Fixed 32x32 patch of the same centre area the screen probe
            # watches, so the change test does not depend on capture size.
            patch = cv2.resize(frame[y0:y1, x0:x1], (32, 32),
                               interpolation=cv2.INTER_AREA).astype(np.int16)
            self.push(t, float(patch.mean()), patch)
        self.cap.release()


class MagewellProbe(Probe):
    """The card through Magewell's SDK instead of DirectShow (robotron_ai.magewell).
    `mode` is lowlatency (pull the frame while it is still arriving), normal
    (pull it once complete) or timer."""
    def __init__(self, mode, chunk_lines, cap_size):
        super().__init__("hdmi")
        import cv2
        from robotron_ai import magewell
        self.cv2, self.magewell = cv2, magewell
        self.mode, self.chunk_lines = mode, chunk_lines
        self.cap_size = cap_size or (1280, 720)
        self.source = None
        self.info = dict(backend="magewell-sdk", mode=mode, chunk_lines=chunk_lines,
                         requested=dict(width=self.cap_size[0], height=self.cap_size[1]))
        self.desc = f"{self.cap_size[0]}x{self.cap_size[1]} BGR24 via Magewell SDK, mode {mode}"
        # (t, derived-ms-dict-or-None) per frame, same t as push(), so a
        # trial's crossing time can be matched back to the SDK timestamps
        # for the frame that caused it (see ts_near / the CARD-ONLY report).
        self.ts_log = collections.deque(maxlen=20000)

    def print_info(self):
        print("=== capture device ===")
        print(f"  Magewell SDK (pymagewell), mode {self.mode}"
              + (f", {self.chunk_lines}-line chunks" if self.mode == "lowlatency" else ""))
        print(f"  requested : {self.cap_size[0]}x{self.cap_size[1]} BGR24, scaled on the card")
        print("  the signal the card sees is printed when capture starts")

    def start(self):
        try:
            self.source = self.magewell.MagewellSource(
                width=self.cap_size[0], height=self.cap_size[1], cap_size=self.cap_size,
                mode=self.mode, chunk_lines=self.chunk_lines, on_frame=self._on_frame,
                on_frame_ts=self._on_frame_ts)
        except (ImportError, RuntimeError) as e:
            sys.exit(f"magewell backend: {e}")
        self.info.update(self.source.info)

    def _on_frame(self, frame, t):
        cv2 = self.cv2
        h, w = frame.shape[:2]
        x0, y0, x1, y1 = centre_rect(w, h, HDMI_ROI_FRAC)
        patch = cv2.resize(frame[y0:y1, x0:x1], (32, 32),
                           interpolation=cv2.INTER_AREA).astype(np.int16)
        self.push(t, float(patch.mean()), patch)

    def _on_frame_ts(self, ts, t):
        derived = derive_sdk_ms(ts)
        with self.lock:                 # ts_log is appended here, off the pump thread
            self.ts_log.append((t, derived))

    def ts_near(self, target_t):
        """The derived SDK-ms dict (or None) for the logged frame closest in
        time to `target_t`, i.e. the frame that caused a threshold crossing.
        Snapshots ts_log under the same lock push() uses before searching:
        the pump thread appends to it concurrently, and min() over a deque
        being mutated under it raises "deque mutated during iteration"."""
        with self.lock:
            items = list(self.ts_log)
        if not items:
            return None
        return min(items, key=lambda item: abs(item[0] - target_t))[1]

    def stop(self):
        self.running = False
        if self.source is not None:
            st = self.source.stats()
            self.info["pump"] = st
            if st.get("error"):
                print(f"  !! magewell capture stopped early: {st['error']}")
            self.source.release()


# ── monitors and the flashing / animating window ────────────────────────────

class POINTL(ctypes.Structure):
    _fields_ = [("x", wt.LONG), ("y", wt.LONG)]


class DEVMODEW(ctypes.Structure):
    _fields_ = [("dmDeviceName", wt.WCHAR * 32), ("dmSpecVersion", wt.WORD),
                ("dmDriverVersion", wt.WORD), ("dmSize", wt.WORD), ("dmDriverExtra", wt.WORD),
                ("dmFields", wt.DWORD), ("dmPosition", POINTL),
                ("dmDisplayOrientation", wt.DWORD), ("dmDisplayFixedOutput", wt.DWORD),
                ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short),
                ("dmYResolution", ctypes.c_short), ("dmTTOption", ctypes.c_short),
                ("dmCollate", ctypes.c_short), ("dmFormName", wt.WCHAR * 32),
                ("dmLogPixels", wt.WORD), ("dmBitsPerPel", wt.DWORD),
                ("dmPelsWidth", wt.DWORD), ("dmPelsHeight", wt.DWORD),
                ("dmDisplayFlags", wt.DWORD), ("dmDisplayFrequency", wt.DWORD),
                ("dmICMMethod", wt.DWORD), ("dmICMIntent", wt.DWORD),
                ("dmMediaType", wt.DWORD), ("dmDitherType", wt.DWORD),
                ("dmReserved1", wt.DWORD), ("dmReserved2", wt.DWORD),
                ("dmPanningWidth", wt.DWORD), ("dmPanningHeight", wt.DWORD)]


def refresh_hz(device_name):
    """The monitor's current refresh rate, which is the hard ceiling on how
    many distinct pictures the HDMI link can carry per second. 0 if unknown."""
    u = ctypes.windll.user32
    u.EnumDisplaySettingsW.restype = wt.BOOL
    u.EnumDisplaySettingsW.argtypes = [wt.LPCWSTR, wt.DWORD, ctypes.POINTER(DEVMODEW)]
    dm = DEVMODEW()
    dm.dmSize = ctypes.sizeof(DEVMODEW)
    if not u.EnumDisplaySettingsW(device_name, 0xFFFFFFFF, ctypes.byref(dm)):
        return 0
    return int(dm.dmDisplayFrequency)


def list_monitors():
    """[(x, y, w, h, name, primary, refresh_hz)] in physical pixels."""
    user32 = ctypes.windll.user32
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        user32.SetProcessDPIAware()

    class MONITORINFOEXW(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT),
                    ("dwFlags", wt.DWORD), ("szDevice", wt.WCHAR * 32)]

    out = []
    PROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HMONITOR, wt.HDC, ctypes.POINTER(wt.RECT), wt.LPARAM)

    def cb(hmon, hdc, rect, lparam):
        mi = MONITORINFOEXW()
        mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
        user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
        r = mi.rcMonitor
        out.append((r.left, r.top, r.right - r.left, r.bottom - r.top, mi.szDevice,
                    bool(mi.dwFlags & 1), refresh_hz(mi.szDevice)))
        return True

    user32.EnumDisplayMonitors(None, None, PROC(cb), 0)
    return out


class DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("DeviceName", wt.WCHAR * 32),
                ("DeviceString", wt.WCHAR * 128), ("StateFlags", wt.DWORD),
                ("DeviceID", wt.WCHAR * 128), ("DeviceKey", wt.WCHAR * 128)]


def display_device_info(device_name):
    """Adapter and attached-monitor names for a `\\\\.\\DISPLAYn` device. The
    monitor string comes from the EDID, so a capture card usually names itself
    here — the quickest confirmation that --monitor points at the card."""
    u = ctypes.windll.user32
    u.EnumDisplayDevicesW.restype = wt.BOOL
    u.EnumDisplayDevicesW.argtypes = [wt.LPCWSTR, wt.DWORD,
                                      ctypes.POINTER(DISPLAY_DEVICEW), wt.DWORD]
    out = {}
    dd = DISPLAY_DEVICEW()
    dd.cb = ctypes.sizeof(DISPLAY_DEVICEW)
    if u.EnumDisplayDevicesW(None, 0, ctypes.byref(dd), 0):
        pass                                    # enumerated below per device
    dd = DISPLAY_DEVICEW()
    dd.cb = ctypes.sizeof(DISPLAY_DEVICEW)
    i = 0
    while u.EnumDisplayDevicesW(None, i, ctypes.byref(dd), 0):
        if dd.DeviceName == device_name:
            out["adapter"] = dd.DeviceString
            break
        i += 1
        dd = DISPLAY_DEVICEW()
        dd.cb = ctypes.sizeof(DISPLAY_DEVICEW)
    mon = DISPLAY_DEVICEW()
    mon.cb = ctypes.sizeof(DISPLAY_DEVICEW)
    if u.EnumDisplayDevicesW(device_name, 0, ctypes.byref(mon), 0):
        out["monitor"] = mon.DeviceString
        out["monitor_id"] = mon.DeviceID
    return out


def display_mode(device_name):
    """Current mode of a display device: size, refresh rate, bit depth."""
    u = ctypes.windll.user32
    u.EnumDisplaySettingsW.restype = wt.BOOL
    u.EnumDisplaySettingsW.argtypes = [wt.LPCWSTR, wt.DWORD, ctypes.POINTER(DEVMODEW)]
    dm = DEVMODEW()
    dm.dmSize = ctypes.sizeof(DEVMODEW)
    if not u.EnumDisplaySettingsW(device_name, 0xFFFFFFFF, ctypes.byref(dm)):
        return {}
    return dict(width=int(dm.dmPelsWidth), height=int(dm.dmPelsHeight),
                refresh_hz=int(dm.dmDisplayFrequency), bits_per_pixel=int(dm.dmBitsPerPel))


def desktop_locked():
    """True if the workstation is locked or on a secure desktop, in which case
    no window can be shown and every screen read returns a frozen image. None
    if it cannot be determined."""
    try:
        u = ctypes.windll.user32
        DESKTOP_SWITCHDESKTOP = 0x0100
        h = u.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
        if not h:
            return True
        name = ctypes.create_unicode_buffer(256)
        need = wt.DWORD()
        u.GetUserObjectInformationW(h, 2, name, ctypes.sizeof(name), ctypes.byref(need))
        u.CloseDesktop(h)
        return name.value.lower() not in ("default", "")
    except Exception:
        return None


def environment(chosen=None):
    """Everything needed to interpret a run sent back from another machine."""
    env = dict(
        when=datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        python=sys.version.split()[0],
        os=f"{platform.system()} {platform.release()} {platform.version()}",
        machine=platform.machine(),
        numpy=getattr(np, "__version__", None),
        desktop_locked=desktop_locked(),
    )
    try:
        import cv2
        env["opencv"] = cv2.__version__
    except Exception as e:
        env["opencv"] = f"unavailable ({e})"
    # DPI awareness decides whether Windows reports and accepts physical or
    # scaled pixels. If this is not per-monitor, a full-screen window on a
    # scaled display will not actually cover the monitor.
    try:
        lvl = ctypes.c_int()
        if ctypes.windll.shcore.GetProcessDpiAwareness(None, ctypes.byref(lvl)) == 0:
            env["dpi_awareness"] = {0: "unaware", 1: "system", 2: "per-monitor"}.get(
                lvl.value, lvl.value)
        else:
            env["dpi_awareness"] = "unknown"
    except Exception:
        env["dpi_awareness"] = "unknown"
    mons = []
    for i, m in enumerate(list_monitors(), 1):
        d = dict(index=i, device=m[4], x=m[0], y=m[1], width=m[2], height=m[3],
                 primary=m[5], refresh_hz=m[6] if len(m) > 6 else None)
        d.update(display_mode(m[4]))
        d.update(display_device_info(m[4]))
        d["chosen"] = (i == chosen)
        mons.append(d)
    env["monitors"] = mons
    return env


def print_environment(env):
    print("=== environment ===")
    print(f"  when        : {env['when']}")
    print(f"  os          : {env['os']} ({env['machine']})")
    print(f"  python      : {env['python']}   opencv {env.get('opencv')}   "
          f"numpy {env.get('numpy')}")
    print(f"  dpi aware   : {env.get('dpi_awareness')}")
    if env.get("desktop_locked"):
        print("  !! THE DESKTOP IS LOCKED OR ON A SECURE DESKTOP. No window can be shown")
        print("     and every screen read returns a frozen image. Unlock and rerun.")
    for m in env["monitors"]:
        mark = " <-- using this one" if m.get("chosen") else ""
        print(f"  monitor {m['index']}  : {m['device']} {m['width']}x{m['height']} "
              f"{m.get('refresh_hz')} Hz {m.get('bits_per_pixel', '?')}bpp "
              f"at ({m['x']},{m['y']}){' primary' if m['primary'] else ''}{mark}")
        print(f"              adapter {m.get('adapter', '?')} / monitor "
              f"{m.get('monitor', '?')}")


def describe_monitors(mons):
    for i, m in enumerate(mons, 1):
        hz = f" {m[6]} Hz" if len(m) > 6 and m[6] else ""
        print(f"monitor {i}: {m[4]} {m[2]}x{m[3]}{hz} at ({m[0]},{m[1]})"
              f"{' primary' if m[5] else ''}")


# Twelve saturated hues of roughly even brightness. Even brightness keeps the
# beacon from flickering in luminance while still moving every colour channel
# far more than the change threshold from one frame to the next.
PALETTE = ["#e04a4a", "#e07a2a", "#c2a52a", "#7fb03a", "#3fb060", "#2fae95",
           "#2f9fc0", "#3f7fd0", "#6a63d0", "#9a55c0", "#c44b9e", "#d14a72"]


def make_shapes(w, h, n=12, seed=2084):
    """Shape specs for the freshness animation: big, bright, fast, and spread
    over the whole frame so every thumbnail row has something moving in it."""
    rnd = random.Random(seed)
    kinds = ["rect", "oval", "tri", "bar"]
    out = []
    for i in range(n):
        sw = rnd.randint(int(w * 0.07), int(w * 0.16))
        sh = rnd.randint(int(h * 0.09), int(h * 0.22))
        ang = rnd.uniform(0, 2 * math.pi)
        speed = rnd.uniform(7.0, 15.0)
        out.append(dict(kind=kinds[i % len(kinds)], slot=i,
                        x=rnd.uniform(0, max(1, w - sw)), y=rnd.uniform(0, max(1, h - sh)),
                        w=sw, h=sh,
                        dx=speed * math.cos(ang), dy=speed * math.sin(ang)))
    return out


def frame_colors(shapes, frame_index):
    """Rotate the palette by one every frame. A shape that happens to reverse
    on top of itself still changes colour, so no frame can repeat the one
    before it however the bounces line up."""
    return [PALETTE[(s["slot"] + frame_index) % len(PALETTE)] for s in shapes]


def step_shapes(shapes, w, h):
    """Advance one frame, reflecting off the edges (never clamping, which
    would stall a shape against a wall). Returns per-shape (dx, dy) actually
    applied, so the caller can move canvas items by the same amount."""
    moves = []
    for s in shapes:
        lim_x, lim_y = max(0.0, w - s["w"]), max(0.0, h - s["h"])
        nx, ny = s["x"] + s["dx"], s["y"] + s["dy"]
        if nx < 0.0:
            nx, s["dx"] = -nx, -s["dx"]
        elif nx > lim_x:
            nx, s["dx"] = 2.0 * lim_x - nx, -s["dx"]
        if ny < 0.0:
            ny, s["dy"] = -ny, -s["dy"]
        elif ny > lim_y:
            ny, s["dy"] = 2.0 * lim_y - ny, -s["dy"]
        nx = min(max(nx, 0.0), lim_x)
        ny = min(max(ny, 0.0), lim_y)
        moves.append((nx - s["x"], ny - s["y"]))
        s["x"], s["y"] = nx, ny
    return moves


class Flasher:
    """Borderless full-screen window on one monitor: solid black/white for
    the latency flips, moving shapes for the freshness count."""
    def __init__(self, mon):
        import tkinter as tk
        self.tk = tk
        x, y, w, h = mon[:4]
        self.w, self.h = w, h
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.configure(bg="black", cursor="none")
        self.canvas = None
        self.root.update()
        # What the window actually became. If this does not match the monitor
        # rect, the probes are reading something other than the test pattern
        # and every number below is meaningless.
        self.geometry = dict(
            wanted=dict(x=x, y=y, w=w, h=h),
            got=dict(x=self.root.winfo_rootx(), y=self.root.winfo_rooty(),
                     w=self.root.winfo_width(), h=self.root.winfo_height()))
        self.geometry["covers_monitor"] = (
            self.geometry["got"]["w"] >= w and self.geometry["got"]["h"] >= h
            and self.geometry["got"]["x"] <= x and self.geometry["got"]["y"] <= y)

    def print_geometry(self):
        g = self.geometry
        print("=== test window ===")
        print(f"  asked for {g['wanted']['w']}x{g['wanted']['h']} at "
              f"({g['wanted']['x']},{g['wanted']['y']}), got {g['got']['w']}x{g['got']['h']} "
              f"at ({g['got']['x']},{g['got']['y']})")
        if not g["covers_monitor"]:
            print("  !! the window does not cover the monitor. Usually display scaling with")
            print("     the process not per-monitor DPI aware. The readings below are invalid.")

    def set(self, white):
        """Solid fill; returns the moment the repaint was requested."""
        if self.canvas is not None:
            self.canvas.destroy()
            self.canvas = None
        self.root.configure(bg="white" if white else "black")
        self.root.update_idletasks()
        self.root.update()
        return time.perf_counter()

    def animate(self, seconds, target_fps, on_frame=None):
        """Moving shapes for `seconds`. Returns frames actually painted."""
        tk = self.tk
        self.root.configure(bg="black")
        self.canvas = tk.Canvas(self.root, width=self.w, height=self.h,
                                bg="black", highlightthickness=0, bd=0)
        self.canvas.place(x=0, y=0)
        shapes = make_shapes(self.w, self.h)
        ids = []
        for s, color in zip(shapes, frame_colors(shapes, 0)):
            x0, y0, x1, y1 = s["x"], s["y"], s["x"] + s["w"], s["y"] + s["h"]
            if s["kind"] == "rect":
                i = self.canvas.create_rectangle(x0, y0, x1, y1, fill=color, width=0)
            elif s["kind"] == "oval":
                i = self.canvas.create_oval(x0, y0, x1, y1, fill=color, width=0)
            elif s["kind"] == "tri":
                i = self.canvas.create_polygon(x0, y1, (x0 + x1) / 2, y0, x1, y1,
                                               fill=color, width=0)
            else:
                i = self.canvas.create_line(x0, y0, x1, y1, fill=color,
                                            width=max(8, s["h"] // 6))
            ids.append(i)
        # The beacon: a large centred block that takes the next palette colour
        # every painted frame. The moving shapes alone cannot guarantee that a
        # small fixed view changes each frame, and both probes watch the
        # centre, so the beacon is what makes the freshness count exact.
        bx0, by0, bx1, by1 = centre_rect(self.w, self.h, BEACON_FRAC)
        beacon = self.canvas.create_rectangle(bx0, by0, bx1, by1,
                                              fill=PALETTE[0], width=0)
        self.root.update()
        painted = 0
        period = 1.0 / max(target_fps, 1)
        t_end = time.perf_counter() + seconds
        nxt = time.perf_counter()
        while time.perf_counter() < t_end:
            k = painted + 1
            colors = frame_colors(shapes, k)
            for i, (dx, dy), color in zip(ids, step_shapes(shapes, self.w, self.h), colors):
                self.canvas.move(i, dx, dy)
                self.canvas.itemconfig(i, fill=color)
            self.canvas.itemconfig(beacon, fill=PALETTE[k % len(PALETTE)])
            self.root.update_idletasks()
            self.root.update()
            painted += 1
            if on_frame:
                on_frame(painted)
            nxt += period
            slack = nxt - time.perf_counter()
            if slack > 0:
                time.sleep(slack)
            else:
                nxt = time.perf_counter()
        return painted

    def close(self):
        try:
            self.root.destroy()
        except Exception:
            pass


# ── the run ─────────────────────────────────────────────────────────────────

def calibrate(flasher, probes):
    levels = {}
    for white in (False, True):
        flasher.set(white)
        time.sleep(0.8)
        for p in probes:
            levels.setdefault(p.name, {})[white] = p.level_now()
    return levels


def run(mon, probes, trials, min_gap, max_gap, anim_seconds, anim_fps, link_hz=0,
        env=None, json_path=None):
    flasher = Flasher(mon)
    flasher.print_geometry()
    for p in probes:
        if hasattr(p, "print_info"):
            p.print_info()
    print()
    for p in probes:
        p.start()
    results, freshness, painted = {p.name: [] for p in probes}, {}, 0
    calib, anim_elapsed = {}, 0.0
    try:
        time.sleep(0.5)
        levels = calibrate(flasher, probes)
        thr = {}
        for p in probes:
            lo, hi = levels[p.name][False], levels[p.name][True]
            if lo is None or hi is None or hi - lo < 40:
                sys.exit(f"{p.name}: black reads {lo}, white reads {hi}; the probe is not "
                         f"seeing the window. Check --monitor (use --list) and, for the "
                         f"card, that the GPU's HDMI is plugged into it.")
            thr[p.name] = (lo + hi) / 2.0
            calib[p.name] = dict(black=lo, white=hi, threshold=thr[p.name])
            print(f"{p.name}: black {lo:.0f}, white {hi:.0f}, threshold {thr[p.name]:.0f}")
        # calibrate() leaves the window WHITE (it ends on the white=True leg).
        # Trial 1 used to flip to white too, i.e. no change at all, so it
        # measured nothing: force black here so the first trial is a real
        # flip, settling the same 0.8 s calibrate() gives each level.
        flasher.set(False)
        time.sleep(0.8)
        white = True
        card_samples = collections.defaultdict(list)
        for i in range(trials):
            time.sleep(random.uniform(min_gap, max_gap))
            t0 = flasher.set(white)
            line = []
            for p in probes:
                dt = p.wait_crossing(t0, thr[p.name], white, 1.0)
                results[p.name].append(dt)
                if dt is not None and hasattr(p, "ts_near"):
                    derived = p.ts_near(t0 + dt / 1000.0)
                    if derived is not None:
                        card_samples[p.name].append(derived)
                line.append(f"{p.name} {dt:6.1f} ms" if dt is not None else f"{p.name}   -    ")
            tag = "white" if white else "black"
            print(f"trial {i + 1:2d}/{trials} to {tag}: " + "  ".join(line), flush=True)
            white = not white

        for p in probes:
            if not hasattr(p, "ts_near"):
                continue
            print()
            print(f"CARD-ONLY ({p.name}, from the SDK's own device-clock timestamps, "
                  "independent of the PC's display pipeline)")
            samples = card_samples.get(p.name, [])
            if not samples:
                print("  SDK timestamps unavailable")
                p.info["sdk_timestamps"] = None
                continue
            stats = dict(clock="device")
            for key in ("card_ms", "scanout_ms"):
                vals = [s[key] for s in samples if s.get(key) is not None]
                stats[key] = summarize(vals)
                note = "" if key == "card_ms" else \
                    "  (normal mode only: unset in lowlatency, rejected if implausible)"
                print(f"  {key:10s}: {stats[key]}{note}")
            print("    card_ms is what the console path pays for the card alone, on the card's")
            print("    own clock; hdmi_minus_screen minus card_ms is the PC compositor's share,")
            print("    which the console does not pay.")
            p.info["sdk_timestamps"] = stats

        if anim_seconds > 0:
            print(f"\nfreshness: {anim_seconds:.0f} s of moving shapes "
                  f"(target {anim_fps} fps) ...", flush=True)
            flasher.set(False)
            time.sleep(0.3)
            for p in probes:
                p.begin_window()
            t_anim = time.perf_counter()
            painted = flasher.animate(anim_seconds, anim_fps)
            anim_elapsed = time.perf_counter() - t_anim
            for p in probes:
                freshness[p.name] = p.window_rates()
    finally:
        for p in probes:
            p.stop()
        flasher.close()
    rep = report(results, probes, freshness, painted, link_hz, anim_elapsed, anim_fps)
    rep["environment"] = env
    rep["window"] = flasher.geometry
    rep["calibration"] = calib
    rep["capture_device"] = next((p.info for p in probes if hasattr(p, "info")), None)
    rep["trials"] = {k: v for k, v in results.items()}
    if json_path:
        try:
            with open(json_path, "w", encoding="utf-8") as fh:
                json.dump(rep, fh, indent=2, default=str)
            print(f"\nfull report written to {json_path}")
            print("Send that file back along with this console output; it carries the monitor")
            print("mode, the card's reported settings and every per-flip number.")
        except OSError as e:
            print(f"\ncould not write {json_path}: {e}")
    return rep


def report(results, probes, freshness=None, painted=0, link_hz=0,
           anim_elapsed=0.0, anim_target_fps=0):
    rep = {}
    print()
    print("LATENCY (how long a change takes to arrive)")
    for p in probes:
        vals = [v for v in results[p.name] if v is not None]
        rep[p.name] = summarize(vals)
        desc = getattr(p, "desc", "")
        print(f"  {p.name:7s}: {rep[p.name]}{(', ' + desc) if desc else ''}")
    names = [p.name for p in probes]
    if "screen" in names and "hdmi" in names:
        d = pair_diffs(results["screen"], results["hdmi"])
        rep["hdmi_minus_screen"] = summarize(d)
        print(f"  hdmi - screen per flip: {rep['hdmi_minus_screen']}")
        print("    The screen read sees the window as soon as it is painted, which is where")
        print("    the emulator's window capture reads. So this is what the console picture")
        print("    pays over the emulator path: scan-out, card, decode, driver buffering.")
        print("    One 60 Hz frame is 16.7 ms; one decision tick is ~60 ms.")

    if freshness:
        rep["freshness"] = dict(freshness)
        rep["freshness"]["painted_frames"] = painted
        rep["freshness"]["link_hz"] = link_hz
        paint_hz = painted / anim_elapsed if anim_elapsed else 0.0
        rep["freshness"]["paint_hz"] = round(paint_hz, 1)
        rep["freshness"]["paint_target_hz"] = anim_target_fps
        print()
        print("FRESHNESS (how often a genuinely new frame arrives)")
        if link_hz:
            print(f"  the monitor runs at {link_hz} Hz, so the HDMI link cannot carry more")
            print(f"  than {link_hz} distinct pictures a second")
        print(f"  the PC painted {painted} frames in {anim_elapsed:.1f} s = {paint_hz:.1f}/s"
              f" (target {anim_target_fps})")
        if anim_target_fps and paint_hz < 0.9 * anim_target_fps:
            print(f"  !! the animation only reached {paint_hz:.0f}/s of its {anim_target_fps}/s")
            print("     target, so the source itself was the limit, not the card. Close other")
            print("     programs and rerun before reading anything into the card's figure.")
        for p in probes:
            f = freshness.get(p.name)
            if not f:
                continue
            what = ("what reached the desktop, i.e. the source"
                    if p.name == "screen" else "what the card delivered")
            print(f"  {p.name:7s}: {f['unique_hz']:5.1f} unique/s  "
                  f"({f['unique']} of {f['samples']} samples in {f['seconds']} s, "
                  f"sampled at {f['sampled_hz']}/s) - {what}")
        src, card = freshness.get("screen"), freshness.get("hdmi")
        if src and card:
            ceiling = min(src["unique_hz"], link_hz) if link_hz else src["unique_hz"]
            kept = kept_fraction(ceiling, card["unique_hz"])
            rep["freshness"]["kept_fraction"] = None if kept is None else round(kept, 3)
            print(f"  card kept {kept * 100:.0f}% of the {ceiling:.0f}/s the source offered"
                  if kept is not None else "  source produced nothing to keep")
            print("    Below ~90% the card or its driver is repeating frames; at ~100% any")
            print("    duplicates seen in a game come from the game, not the capture path.")
            print(f"    Mean frame age adds ~{500.0 / max(card['unique_hz'], 1e-6):.0f} ms"
                  f" (1/(2*unique_hz)) on top of the latency above.")
            print("    The bot decides ~15 times a second and needs 15+ unique/s to see a")
            print("    new picture every tick; 30+ leaves margin.")
        if src:
            if src["sampled_hz"] < 2.0 * max(link_hz, 1):
                print(f"    NOTE: the screen probe sampled {src['sampled_hz']}/s against a")
                print(f"    {link_hz} Hz link, too little margin to resolve every frame; read")
                print("    the source figure as a floor.")
            elif link_hz and src["unique_hz"] > link_hz * 1.02:
                print(f"    NOTE: the source figure exceeds {link_hz} Hz because a desktop read")
                print("    can catch a half-finished repaint. The link rate is the real")
                print("    ceiling; this only confirms the source was saturating it.")
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--list", action="store_true", help="list monitors and exit")
    ap.add_argument("--monitor", type=int, default=None,
                    help="1-based monitor index from --list (default: the non-primary one)")
    ap.add_argument("--device", type=int, default=0)
    ap.add_argument("--capture-backend", default="dshow",
                    choices=["auto", "msmf", "dshow", "magewell"],
                    help="magewell = the card through Magewell's SDK (pip install pymagewell)")
    ap.add_argument("--magewell-mode", default="lowlatency",
                    choices=["lowlatency", "normal", "timer"],
                    help="magewell backend: pull the frame while it arrives (lowlatency), "
                         "after it is complete (normal), or on a software timer")
    ap.add_argument("--magewell-chunk", type=int, default=64,
                    help="magewell lowlatency: lines per transfer chunk (64, 128, 256)")
    ap.add_argument("--capture-fourcc", default="MJPG")
    ap.add_argument("--capture-res", default="1920x1080", help="WxH requested from the card")
    ap.add_argument("--no-hdmi", action="store_true", help="screen probe only (self-test)")
    ap.add_argument("--no-screen", action="store_true", help="card probe only")
    ap.add_argument("--trials", type=int, default=40, help="latency flips (0 to skip)")
    ap.add_argument("--gap", default="0.4,0.8", help="random seconds between flips, min,max")
    ap.add_argument("--anim-seconds", type=float, default=10.0,
                    help="seconds of moving shapes for the freshness count (0 to skip)")
    ap.add_argument("--anim-fps", type=int, default=0,
                    help="target paint rate for the shapes (default: the monitor's refresh rate)")
    ap.add_argument("--json", default=None,
                    help="where to write the full report (default: capture_report_<stamp>.json)")
    ap.add_argument("--no-json", action="store_true", help="do not write the report file")
    a = ap.parse_args(argv)

    mons = list_monitors()
    if a.list or not mons:
        print_environment(environment())
        return None
    if a.monitor is None:
        cands = [i for i, m in enumerate(mons, 1) if not m[5]]
        if len(cands) != 1:
            describe_monitors(mons)
            sys.exit("pass --monitor N (the one the capture card shows up as)")
        a.monitor = cands[0]
    mon = mons[a.monitor - 1]
    link_hz = mon[6] if len(mon) > 6 else 0
    anim_fps = a.anim_fps or link_hz or 60
    env = environment(chosen=a.monitor)
    env["argv"] = list(argv) if argv is not None else sys.argv[1:]
    print_environment(env)
    print()

    probes = []
    if not a.no_screen:
        probes.append(ScreenProbe(mon[0], mon[1], mon[2], mon[3]))
    if not a.no_hdmi:
        w, h = (int(v) for v in a.capture_res.lower().split("x"))
        if a.capture_backend == "magewell":
            probes.append(MagewellProbe(a.magewell_mode, a.magewell_chunk, (w, h)))
        else:
            probes.append(HdmiProbe(a.device, a.capture_backend, a.capture_fourcc, (w, h)))
    if not probes:
        sys.exit("nothing to measure")
    lo, hi = (float(v) for v in a.gap.split(","))
    json_path = None
    if not a.no_json:
        json_path = a.json or (
            f"capture_report_{datetime.datetime.now():%Y%m%d_%H%M%S}.json")
    return run(mon, probes, a.trials, lo, hi, a.anim_seconds, anim_fps, link_hz,
               env=env, json_path=json_path)


if __name__ == "__main__":
    main()
