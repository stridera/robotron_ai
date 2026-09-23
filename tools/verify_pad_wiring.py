"""Acceptance test for the direct-wired Xbox 360 pad: drive the real
SerialController and check the pad reports the right buttons.

Run after soldering or reflashing, with the pad's USB plugged into this PC
(not the console) and the right arduino/robotron_pad_* rev flashed on the Uno:

    python -m robotron_ai.tools.verify_pad_wiring --port COM3

It walks all 81 move/fire direction pairs plus Start/Back/A/B, so a swapped
wire or a myPins[] that drifted from control.py shows up as a named failure
rather than as a bot that plays badly. Close the Arduino IDE Serial Monitor
first: it holds the COM port open.
"""
import argparse
import statistics
import sys
import time

from robotron_ai.control import SerialController as SC
from robotron_ai.tools.measure_control_latency import XInputReader, XINPUT_BUTTON

COMPASS = {0: "-", 1: "N", 2: "NE", 3: "E", 4: "SE", 5: "S", 6: "SW", 7: "W", 8: "NW"}
# Which pad button each direction bit means, per half of the byte.
MOVE_BTN = {SC.UP: "DPAD_UP", SC.DOWN: "DPAD_DOWN", SC.RIGHT: "DPAD_RIGHT", SC.LEFT: "DPAD_LEFT"}
FIRE_BTN = {SC.UP: "Y", SC.DOWN: "A", SC.RIGHT: "B", SC.LEFT: "X"}


def expected(move_dir, fire_dir):
    """The set of pad buttons a correct rig reports for this direction pair."""
    out = set()
    for bit, name in MOVE_BTN.items():
        if SC._DIR_MASK[move_dir] & bit:
            out.add(name)
    for bit, name in FIRE_BTN.items():
        if SC._DIR_MASK[fire_dir] & bit:
            out.add(name)
    return out


def held(reader):
    st = reader.read()
    if st is None:
        sys.exit("No pad state readable. Is the 360 pad's USB plugged into this PC?")
    return {n for n, m in XINPUT_BUTTON.items() if st[0] & m}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", default="COM3")
    ap.add_argument("--index", type=int, default=0, help="XInput slot of the pad")
    ap.add_argument("--settle", type=float, default=0.08, help="seconds to wait after each byte")
    args = ap.parse_args(argv)

    reader = XInputReader(args.index)
    ctrl = SerialController(args.port)
    if ctrl.ser is None:
        return 2
    time.sleep(2.5)          # opening the port resets the Uno
    ctrl.neutral()
    time.sleep(0.3)

    idle = held(reader)
    if idle:
        print(f"WARNING: pad already reports {' '.join(sorted(idle))} with nothing sent")

    failures, timings = [], []
    print("      fire:  -   N  NE   E  SE   S  SW   W  NW")
    for mv in range(9):
        row = []
        for fr in range(9):
            want = expected(mv, fr)
            t0 = time.perf_counter()
            ctrl.move_shoot(mv, fr)
            seen = None
            while time.perf_counter() - t0 < args.settle:
                if held(reader) - idle == want:
                    seen = (time.perf_counter() - t0) * 1000.0
                    break
                time.sleep(0.001)
            got = held(reader) - idle
            if got == want:
                row.append("  . ")
                if seen is not None and want:
                    timings.append(seen)
            else:
                row.append("  X ")
                failures.append((mv, fr, want, got))
            ctrl.neutral()
            time.sleep(0.04)
        print(f"move {COMPASS[mv]:>2}: {''.join(row)}")

    print(f"\n{81 - len(failures)}/81 direction pairs correct")
    for mv, fr, want, got in failures[:15]:
        print(f"  FAIL move {COMPASS[mv]:<2} fire {COMPASS[fr]:<2}: "
              f"expected [{' '.join(sorted(want)) or 'nothing'}] "
              f"got [{' '.join(sorted(got)) or 'nothing'}]")

    menu = []
    for label, fn, want in (("press_a", ctrl.press_a, {"A"}),
                            ("press_b", ctrl.press_b, {"B"}),
                            ("press_start", ctrl.press_start, {"START"})):
        import threading
        seen, stop = set(), []

        def watch():
            while not stop:
                seen.update(held(reader) - idle)
                time.sleep(0.002)

        t = threading.Thread(target=watch, daemon=True)
        t.start()
        fn()
        stop.append(1)
        t.join()
        ok = seen == want
        menu.append(ok)
        print(f"  {'PASS' if ok else 'FAIL'} {label}: expected [{' '.join(sorted(want))}] "
              f"saw [{' '.join(sorted(seen)) or 'nothing'}]")

    ctrl.close()
    if timings:
        print(f"\npress latency: median {statistics.median(timings):.1f} ms, "
              f"min {min(timings):.1f}, max {max(timings):.1f} (n={len(timings)})")
    ok = not failures and all(menu)
    print("\nRESULT:", "PASS - the pad matches control.py" if ok else "FAIL - see above")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
