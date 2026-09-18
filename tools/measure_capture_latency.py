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
import math
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


def kept_fraction(source_unique_hz, card_unique_hz):
    """Share of the source's new frames that survived to the card."""
    if not source_unique_hz:
        return None
    return card_unique_hz / source_unique_hz


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
        fcs = "".join(chr((v >> (8 * i)) & 0xFF) for i in range(4)).strip()
        self.desc = (f"{int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x"
                     f"{int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))} {fcs or '?'} "
                     f"{self.cap.get(cv2.CAP_PROP_FPS):.0f}fps (backend {backend or 'auto'})")

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


# ── monitors and the flashing / animating window ────────────────────────────

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


def run(mon, probes, trials, min_gap, max_gap, anim_seconds, anim_fps):
    flasher = Flasher(mon)
    for p in probes:
        p.start()
    results, freshness, painted = {p.name: [] for p in probes}, {}, 0
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

        if anim_seconds > 0:
            print(f"\nfreshness: {anim_seconds:.0f} s of moving shapes "
                  f"(target {anim_fps} fps) ...", flush=True)
            flasher.set(False)
            time.sleep(0.3)
            for p in probes:
                p.begin_window()
            painted = flasher.animate(anim_seconds, anim_fps)
            for p in probes:
                freshness[p.name] = p.window_rates()
    finally:
        for p in probes:
            p.stop()
        flasher.close()
    return report(results, probes, freshness, painted)


def report(results, probes, freshness=None, painted=0):
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
        print()
        print("FRESHNESS (how often a genuinely new frame arrives)")
        for p in probes:
            f = freshness.get(p.name)
            if not f:
                continue
            what = ("what the PC painted, i.e. the source rate"
                    if p.name == "screen" else "what the card delivered")
            print(f"  {p.name:7s}: {f['unique_hz']:5.1f} unique/s  "
                  f"({f['unique']} of {f['samples']} samples in {f['seconds']} s, "
                  f"sampled at {f['sampled_hz']}/s) - {what}")
        src, card = freshness.get("screen"), freshness.get("hdmi")
        if src and card:
            kept = kept_fraction(src["unique_hz"], card["unique_hz"])
            rep["freshness"]["kept_fraction"] = None if kept is None else round(kept, 3)
            print(f"  card kept {kept * 100:.0f}% of the source's new frames"
                  if kept is not None else "  source produced nothing to keep")
            print("    Below ~90% the card or its driver is repeating frames; at ~100% any")
            print("    duplicates seen in a game come from the game, not the capture path.")
            print(f"    Mean frame age adds ~{500.0 / max(card['unique_hz'], 1e-6):.0f} ms"
                  f" (1/(2*unique_hz)) on top of the latency above.")
            print("    The bot decides ~15 times a second and needs 15+ unique/s to see a")
            print("    new picture every tick; 30+ leaves margin.")
        if src and src["sampled_hz"] < 120:
            print(f"    NOTE: the screen probe only sampled {src['sampled_hz']}/s, which is")
            print("    close to the paint rate, so the source figure may be understated.")
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
    ap.add_argument("--trials", type=int, default=40, help="latency flips (0 to skip)")
    ap.add_argument("--gap", default="0.4,0.8", help="random seconds between flips, min,max")
    ap.add_argument("--anim-seconds", type=float, default=10.0,
                    help="seconds of moving shapes for the freshness count (0 to skip)")
    ap.add_argument("--anim-fps", type=int, default=60, help="target paint rate for the shapes")
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
        probes.append(ScreenProbe(mon[0], mon[1], mon[2], mon[3]))
    if not a.no_hdmi:
        w, h = (int(v) for v in a.capture_res.lower().split("x"))
        hp = HdmiProbe(a.device, a.capture_backend, a.capture_fourcc, (w, h))
        print(f"card: {hp.desc}")
        probes.append(hp)
    if not probes:
        sys.exit("nothing to measure")
    lo, hi = (float(v) for v in a.gap.split(","))
    return run(mon, probes, a.trials, lo, hi, a.anim_seconds, a.anim_fps)


if __name__ == "__main__":
    main()
