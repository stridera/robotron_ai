"""Capture-card probe — find the backend/format that delivers the most
UNIQUE frames per second.

Why this exists (hardware rounds 6-11): the operator's rig held a perfect
15 Hz decision loop, but the capture card (an Elgato HD60 Pro — a PCIe
1080p60 card, nowhere near its limits) handed back ~44% DUPLICATE frames:
the bot effectively saw ~8 fresh images a second, half the rehearsal rate,
with 60+ detector blind streaks of 20+ frames per session. No GPU fixes
frames that never arrive. Which capture API (Media Foundation vs
DirectShow), pixel format and mode a card runs fast under is card- and
driver-specific, and the only way to know is to measure every combination
on the actual card.

    python -m robotron_ai --mode hardware --probe-capture --device 0

Prints a ranked table; the top line is the flags to add to the normal
command. Nothing here touches the game or the controller.

Each configuration is measured in its OWN subprocess with a timeout: some
backend/mode combinations hang inside the driver on open (seen on a
webcam during development), and a hang must skip one row, not kill the
probe.
"""
import json
import subprocess
import sys
import time

import numpy as np

BACKENDS = ["msmf", "dshow"]
FOURCCS = [None, "MJPG", "YUY2"]
FPSS = [None, 30, 60]
SIZES = [(1280, 720), (1920, 1080)]


def _sig(frame):
    """Cheap frame signature (same subsample telemetry uses)."""
    return frame[::90, ::160].astype(np.int32).sum(axis=2)


def _fourcc_str(v):
    try:
        v = int(v)
        return "".join(chr((v >> (8 * i)) & 0xFF) for i in range(4)).strip()
    except Exception:
        return "?"


def _backend_id(name):
    import cv2
    return {"msmf": cv2.CAP_MSMF, "dshow": cv2.CAP_DSHOW}.get(name, cv2.CAP_ANY)


def measure(device, backend, fourcc=None, fps=None, size=None, seconds=3.0):
    """Open one configuration and measure delivered / unique frame rates.
    `backend` is a name ('msmf'/'dshow'). Returns a dict, or None if the
    configuration would not open."""
    import cv2
    cap = cv2.VideoCapture(device, _backend_id(backend))
    if not cap.isOpened():
        cap.release()
        return None
    try:
        if fourcc:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
        if size:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, size[0])
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, size[1])
        if fps:
            cap.set(cv2.CAP_PROP_FPS, fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        for _ in range(5):                  # first frames after a mode change are stale
            cap.grab()
        n = uniq = 0
        last = None
        t0 = time.time()
        while time.time() - t0 < seconds:
            if not cap.grab():
                continue
            ok, frame = cap.retrieve()
            if not ok or frame is None:
                continue
            n += 1
            s = _sig(frame)
            if last is None or not np.array_equal(s, last):
                uniq += 1
            last = s
        dt = max(time.time() - t0, 1e-6)
        return dict(
            delivered_hz=n / dt, unique_hz=uniq / dt,
            width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            fps_prop=float(cap.get(cv2.CAP_PROP_FPS)),
            fourcc_prop=_fourcc_str(cap.get(cv2.CAP_PROP_FOURCC)),
        )
    finally:
        cap.release()


def _measure_isolated(device, cfg, seconds):
    """Run measure() in a child process with a hard timeout. Returns the
    result dict, None (did not open), or the string 'hung'/'crashed'."""
    spec = dict(device=device, seconds=seconds, **cfg)
    try:
        p = subprocess.run(
            [sys.executable, "-m", "robotron_ai.capture_probe", "--one",
             json.dumps(spec)],
            capture_output=True, text=True, timeout=seconds + 25)
    except subprocess.TimeoutExpired:
        return "hung"
    for line in reversed(p.stdout.splitlines()):
        if line.startswith("RESULT "):
            return json.loads(line[7:])
    return "crashed"


def probe(device=0, seconds=3.0, verbose=True):
    """Try every backend x pixel-format x fps x size combination (each in
    its own process) and print a ranked table. Returns [(config, result)]."""
    try:
        sys.stdout.reconfigure(line_buffering=True)   # progress even when redirected
    except Exception:
        pass
    total = len(BACKENDS) * len(FOURCCS) * len(FPSS) * len(SIZES)
    print(f"[probe] device {device!r}: {total} configurations x {seconds:.0f}s "
          f"— about {total * (seconds + 2) / 60:.0f} minutes. Leave the "
          f"console on a game or the attract mode (moving picture).")
    rows = []
    i = 0
    for bname in BACKENDS:
        for fc in FOURCCS:
            for fps in FPSS:
                for size in SIZES:
                    i += 1
                    cfg = dict(backend=bname, fourcc=fc, fps=fps, size=list(size))
                    label = (f"[probe] {i}/{total} {bname:5s} {fc or 'default':7s} "
                             f"fps={str(fps or 'dflt'):4s} {size[0]}x{size[1]}:")
                    res = _measure_isolated(device, cfg, seconds)
                    if res is None:
                        if verbose:
                            print(f"{label} did not open")
                        continue
                    if isinstance(res, str):
                        if verbose:
                            print(f"{label} {res} (skipped)")
                        continue
                    rows.append((cfg, res))
                    if verbose:
                        print(f"{label} unique {res['unique_hz']:5.1f}/s  delivered "
                              f"{res['delivered_hz']:5.1f}/s  (card says "
                              f"{res['width']}x{res['height']} {res['fourcc_prop']} "
                              f"{res['fps_prop']:.0f}fps)")
    rows.sort(key=lambda r: r[1]["unique_hz"], reverse=True)
    print()
    print("=== capture probe: ranked by UNIQUE frames/s (what the bot actually sees) ===")
    print(f"{'backend':8s} {'fourcc':8s} {'fps':5s} {'size':10s} {'unique/s':>9s} "
          f"{'delivered/s':>12s}")
    for cfg, res in rows[:12]:
        print(f"{cfg['backend']:8s} {cfg['fourcc'] or 'default':8s} "
              f"{str(cfg['fps'] or 'dflt'):5s} "
              f"{cfg['size'][0]}x{cfg['size'][1]:<5d} {res['unique_hz']:9.1f} "
              f"{res['delivered_hz']:12.1f}")
    if rows:
        cfg = rows[0][0]
        flags = [f"--capture-backend {cfg['backend']}"]
        if cfg["fourcc"]:
            flags.append(f"--capture-fourcc {cfg['fourcc']}")
        if cfg["fps"]:
            flags.append(f"--capture-fps {cfg['fps']}")
        flags.append(f"--capture-res {cfg['size'][0]}x{cfg['size'][1]}")
        print()
        print("Best configuration — add these flags to the normal command:")
        print("   " + " ".join(flags))
        print("(the bot needs >= 15 unique frames/s to see every decision tick fresh)")
    else:
        print("No configuration opened — check --device (try 0, 1, 2).")
    return rows


if __name__ == "__main__":
    # Child-process entry: `--one <json spec>` measures a single configuration
    # and prints one RESULT line for the parent to parse.
    if len(sys.argv) >= 3 and sys.argv[1] == "--one":
        spec = json.loads(sys.argv[2])
        size = tuple(spec["size"]) if spec.get("size") else None
        try:
            r = measure(spec["device"], spec["backend"], spec.get("fourcc"),
                        spec.get("fps"), size, spec.get("seconds", 3.0))
        except Exception:
            r = None
        print("RESULT " + json.dumps(r), flush=True)
    else:
        dev = sys.argv[1] if len(sys.argv) > 1 else 0
        probe(int(dev) if str(dev).isdigit() else dev)
