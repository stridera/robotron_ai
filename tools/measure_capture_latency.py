"""Measure the CAPTURE-chain latency in isolation: GPU HDMI output -> capture
card -> OpenCV frame in this process, against the screen-capture path the
emulator uses.

Run a spare HDMI cable from the PC's video card straight into the capture
card. Windows then sees the card as an extra monitor. This tool opens a
full-screen window on that monitor, flips it between black and white at
random moments, and watches for each flip to arrive two ways at once:

  * through the capture card, opened with the same OpenCV flags the bot
    uses (`--device`, `--capture-backend`, `--capture-fourcc`, `--capture-res`);
  * through a screen read of the same monitor (a GDI BitBlt of the desktop),
    which is what the emulator's window capture amounts to.

The screen read sees the window as soon as it is painted (before the desktop
compositor and the cable), which is also where the emulator's window capture
reads. So the DIFFERENCE between the two readings is what the console path
pays on the video side over the emulator path: scan-out, the card's frame
latency, the format decode and any driver buffering. The console's own
input-to-output pipeline is not in this measurement.

    .venv\\Scripts\\python -m robotron_ai.tools.measure_capture_latency --list
    .venv\\Scripts\\python -m robotron_ai.tools.measure_capture_latency --monitor 2 --device 0 --capture-backend dshow --capture-fourcc MJPG --capture-res 1920x1080

Run it once per capture setting you want to compare (1920x1080 vs 1280x720,
MJPG vs YUY2). Only numpy, OpenCV and the standard library are needed.
"""
import argparse
import collections
import ctypes
import ctypes.wintypes as wt
import random
import statistics
import sys
import threading
import time

try:
    import numpy as np
except ImportError:            # pure helpers still importable for tests
    np = None

ROI = 64                        # square sample at the monitor centre, px
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


# ── probes ──────────────────────────────────────────────────────────────────

class Probe:
    """A sampler thread that records (t, level) pairs of the centre ROI."""
    def __init__(self, name):
        self.name = name
        self.samples = collections.deque(maxlen=20000)
        self.lock = threading.Lock()
        self.running = True
        self.count = 0
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False

    def push(self, t, level):
        self.count += 1
        with self.lock:
            self.samples.append((t, level))

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
    """GDI BitBlt of a ROI x ROI square of the desktop at (x, y)."""
    def __init__(self, x, y):
        super().__init__("screen")
        self.x, self.y = x, y
        self.user32 = ctypes.windll.user32
        self.gdi32 = ctypes.windll.gdi32
        for fn, res, args in [
            (self.user32.GetDC, wt.HDC, [wt.HWND]),
            (self.user32.ReleaseDC, ctypes.c_int, [wt.HWND, wt.HDC]),
            (self.gdi32.CreateCompatibleDC, wt.HDC, [wt.HDC]),
            (self.gdi32.CreateCompatibleBitmap, wt.HBITMAP, [wt.HDC, ctypes.c_int, ctypes.c_int]),
            (self.gdi32.SelectObject, wt.HGDIOBJ, [wt.HDC, wt.HGDIOBJ]),
            (self.gdi32.BitBlt, wt.BOOL, [wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                          ctypes.c_int, wt.HDC, ctypes.c_int, ctypes.c_int, wt.DWORD]),
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
        self.bmi.bmiHeader.biWidth = ROI
        self.bmi.bmiHeader.biHeight = -ROI
        self.bmi.bmiHeader.biPlanes = 1
        self.bmi.bmiHeader.biBitCount = 32
        self.buf = ctypes.create_string_buffer(ROI * ROI * 4)

    def _loop(self):
        u, g = self.user32, self.gdi32
        sdc = u.GetDC(None)
        mdc = g.CreateCompatibleDC(sdc)
        bmp = g.CreateCompatibleBitmap(sdc, ROI, ROI)
        old = g.SelectObject(mdc, bmp)
        try:
            while self.running:
                g.BitBlt(mdc, 0, 0, ROI, ROI, sdc, self.x, self.y, SRCCOPY)
                t = time.perf_counter()
                g.GetDIBits(mdc, bmp, 0, ROI, self.buf, ctypes.byref(self.bmi), 0)
                arr = np.frombuffer(self.buf, dtype=np.uint8)
                self.push(t, float(arr.reshape(-1, 4)[:, :3].mean()))
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
        fcs = "".join(chr((v >> (8 * i)) & 0xFF) for i in range(4)).strip()
        self.desc = (f"{int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x"
                     f"{int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))} {fcs or '?'} "
                     f"{self.cap.get(cv2.CAP_PROP_FPS):.0f}fps (backend {backend or 'auto'})")
        self.unique = 0
        self._prev = None

    def _loop(self):
        while self.running:
            if not self.cap.grab():
                time.sleep(0.005)
                continue
            t = time.perf_counter()
            ok, frame = self.cap.retrieve()
            if not ok or frame is None:
                continue
            h, w = frame.shape[:2]
            roi = frame[h // 2 - ROI // 2:h // 2 + ROI // 2, w // 2 - ROI // 2:w // 2 + ROI // 2]
            lv = float(roi.mean())
            if self._prev is None or abs(lv - self._prev) > 2.0:
                self.unique += 1
            self._prev = lv
            self.push(t, lv)
        self.cap.release()


# ── monitors and the flashing window ────────────────────────────────────────

def list_monitors():
    """[(x, y, w, h, name, primary)] in physical pixels."""
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
                    bool(mi.dwFlags & 1)))
        return True

    user32.EnumDisplayMonitors(None, None, PROC(cb), 0)
    return out


def describe_monitors(mons):
    for i, m in enumerate(mons, 1):
        print(f"monitor {i}: {m[4]} {m[2]}x{m[3]} at ({m[0]},{m[1]}){' primary' if m[5] else ''}")


class Flasher:
    """Borderless full-screen tkinter window on one monitor."""
    def __init__(self, mon):
        import tkinter as tk
        x, y, w, h = mon[:4]
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.configure(bg="black", cursor="none")
        self.root.update()

    def set(self, white):
        self.root.configure(bg="white" if white else "black")
        self.root.update_idletasks()
        self.root.update()
        return time.perf_counter()

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


def run(mon, probes, trials, min_gap, max_gap):
    flasher = Flasher(mon)
    for p in probes:
        p.start()
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
            print(f"{p.name}: black {lo:.0f}, white {hi:.0f}, threshold {thr[p.name]:.0f}")
        results = {p.name: [] for p in probes}
        white = True
        for i in range(trials):
            time.sleep(random.uniform(min_gap, max_gap))
            t0 = flasher.set(white)
            line = []
            for p in probes:
                dt = p.wait_crossing(t0, thr[p.name], white, 1.0)
                results[p.name].append(dt)
                line.append(f"{p.name} {dt:6.1f} ms" if dt is not None else f"{p.name}   -    ")
            tag = "white" if white else "black"
            print(f"trial {i + 1:2d}/{trials} to {tag}: " + "  ".join(line), flush=True)
            white = not white
    finally:
        for p in probes:
            p.stop()
        flasher.close()
    return report(results, probes)


def report(results, probes):
    rep = {}
    print()
    for p in probes:
        vals = [v for v in results[p.name] if v is not None]
        rep[p.name] = summarize(vals)
        desc = getattr(p, "desc", "")
        print(f"{p.name:7s}: {rep[p.name]}{(', ' + desc) if desc else ''}")
        if isinstance(p, HdmiProbe):
            print(f"         card delivered {p.count} frames, {p.unique} changed at the centre")
    names = [p.name for p in probes]
    if "screen" in names and "hdmi" in names:
        d = pair_diffs(results["screen"], results["hdmi"])
        rep["hdmi_minus_screen"] = summarize(d)
        print(f"hdmi - screen per flip: {rep['hdmi_minus_screen']}")
        print("  The screen read sees the window as soon as it is painted, before the desktop")
        print("  compositor and the cable, which is also where the emulator's window capture")
        print("  reads. So this difference is what the console picture pays over the emulator")
        print("  path on the video side: scan-out, the card, the format decode and any driver")
        print("  buffering. One 60 Hz frame is 16.7 ms; one decision tick is ~60 ms.")
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--list", action="store_true", help="list monitors and exit")
    ap.add_argument("--monitor", type=int, default=None,
                    help="1-based monitor index from --list (default: the non-primary one)")
    ap.add_argument("--device", type=int, default=0)
    ap.add_argument("--capture-backend", default="dshow", choices=["auto", "msmf", "dshow"])
    ap.add_argument("--capture-fourcc", default="MJPG")
    ap.add_argument("--capture-res", default="1920x1080", help="WxH requested from the card")
    ap.add_argument("--no-hdmi", action="store_true", help="screen probe only (self-test)")
    ap.add_argument("--no-screen", action="store_true", help="card probe only")
    ap.add_argument("--trials", type=int, default=40)
    ap.add_argument("--gap", default="0.4,0.8", help="random seconds between flips, min,max")
    a = ap.parse_args(argv)

    mons = list_monitors()
    if a.list or not mons:
        describe_monitors(mons)
        return None
    if a.monitor is None:
        cands = [i for i, m in enumerate(mons, 1) if not m[5]]
        if len(cands) != 1:
            describe_monitors(mons)
            sys.exit("pass --monitor N (the one the capture card shows up as)")
        a.monitor = cands[0]
    mon = mons[a.monitor - 1]
    print(f"flashing monitor {a.monitor}: {mon[4]} {mon[2]}x{mon[3]} at ({mon[0]},{mon[1]})")

    probes = []
    if not a.no_screen:
        probes.append(ScreenProbe(mon[0] + mon[2] // 2 - ROI // 2, mon[1] + mon[3] // 2 - ROI // 2))
    if not a.no_hdmi:
        w, h = (int(v) for v in a.capture_res.lower().split("x"))
        hp = HdmiProbe(a.device, a.capture_backend, a.capture_fourcc, (w, h))
        print(f"card: {hp.desc}")
        probes.append(hp)
    if not probes:
        sys.exit("nothing to measure")
    lo, hi = (float(v) for v in a.gap.split(","))
    return run(mon, probes, a.trials, lo, hi)


if __name__ == "__main__":
    main()
