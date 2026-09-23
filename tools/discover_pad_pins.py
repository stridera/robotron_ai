"""Measure which pad button each Arduino pin presses, for any shield revision.

The optoisolator shields are hand-built and their pin order differs between
revisions (v1 and v2 are reversed relative to each other). Rather than guess,
flash arduino/pin_probe and run this:

    python -m robotron_ai.tools.discover_pad_pins --port COM3

It holds each pin in turn, watches the pad over XInput, and prints the measured
map plus a ready-to-paste pin block for arduino/robotron_pad_v1 or _v2. The
pad's USB must be plugged into this PC, not the console, and the Arduino IDE
Serial Monitor must be closed because it holds the COM port.
"""
import argparse
import sys
import time

from robotron_ai.tools.measure_control_latency import XInputReader, XINPUT_BUTTON

FIRST_PIN, LAST_PIN = 2, 13
# XInput name -> the constant name the sketches use for it.
CONST = {"BACK": "backButton", "START": "startButton", "B": "bButton", "A": "aButton",
         "Y": "yButton", "X": "xButton", "DPAD_LEFT": "leftButton",
         "DPAD_RIGHT": "rightButton", "DPAD_DOWN": "downButton", "DPAD_UP": "upButton"}
ORDER = ["backButton", "startButton", None, "bButton", "aButton", "yButton", "xButton",
         None, "leftButton", "rightButton", "downButton", "upButton"]
WIDTH = max(len(c) for c in CONST.values())


def held(reader):
    st = reader.read()
    if st is None:
        sys.exit("No pad state readable. Is the 360 pad's USB plugged into this PC?")
    return {n for n, m in XINPUT_BUTTON.items() if st[0] & m}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", default="COM3")
    ap.add_argument("--index", type=int, default=0, help="XInput slot of the pad")
    ap.add_argument("--hold", type=float, default=0.3, help="seconds to hold each pin")
    ap.add_argument("--rounds", type=int, default=2, help="passes, to catch flaky joints")
    args = ap.parse_args(argv)

    import serial
    reader = XInputReader(args.index)
    try:
        ser = serial.Serial(args.port, 9600)
    except serial.SerialException as e:
        sys.exit(f"Cannot open {args.port}: {e}\n"
                 "Close the Arduino IDE Serial Monitor, it holds the port open.")
    print(f"opened {args.port}, waiting for the Uno to reset...")
    time.sleep(2.5)
    ser.write(b"\x00"); ser.flush(); time.sleep(0.3)

    idle = held(reader)
    if idle:
        print(f"WARNING: pad already reports {' '.join(sorted(idle))} with nothing driven")

    seen = {}
    for rnd in range(args.rounds):
        for pin in range(FIRST_PIN, LAST_PIN + 1):
            ser.write(bytes([pin])); ser.flush()
            t0 = time.perf_counter()
            got = set()
            while time.perf_counter() - t0 < args.hold:
                got |= held(reader) - idle
                time.sleep(0.002)
            ser.write(b"\x00"); ser.flush(); time.sleep(0.08)
            seen.setdefault(pin, []).append(tuple(sorted(got)))
    ser.write(b"\x00"); ser.flush(); ser.close()

    print(f"\nmeasured over {args.rounds} passes:")
    mapping, problems = {}, []
    for pin in range(FIRST_PIN, LAST_PIN + 1):
        obs = seen[pin]
        if len(set(obs)) != 1:
            problems.append(f"D{pin} was inconsistent: {' vs '.join(str(list(o)) for o in obs)}")
            note = "  <-- INCONSISTENT, check the joint"
        elif len(obs[0]) > 1:
            problems.append(f"D{pin} pressed several buttons at once: {list(obs[0])}")
            note = "  <-- more than one button, check for a solder bridge"
        else:
            note = ""
        btn = obs[0][0] if len(set(obs)) == 1 and len(obs[0]) == 1 else None
        if btn:
            mapping[pin] = btn
        print(f"  D{pin:<3} -> {' '.join(obs[0]) or 'nothing':<12}{note}")

    dupes = {b for b in mapping.values() if list(mapping.values()).count(b) > 1}
    for b in sorted(dupes):
        problems.append(f"{b} is driven by more than one pin: "
                        f"{' '.join('D%d' % p for p, v in mapping.items() if v == b)}")
    missing = sorted(set(CONST) - set(mapping.values()))
    if missing:
        problems.append(f"never saw: {' '.join(missing)}")

    if problems:
        print("\nproblems:")
        for p in problems:
            print("  -", p)
        print("\nFix those before pasting anything. A pin that presses nothing is")
        print("usually an unplugged ribbon, a cold joint, or a missing ground.")
        return 1

    by_const = {CONST[b]: p for p, b in mapping.items()}
    print("\nall ten found. Paste this over the pin block in the sketch:\n")
    print(f"// Measured with discover_pad_pins on {time.strftime('%Y-%m-%d')}.")
    for const in ORDER:
        if const is None:
            print()
        else:
            print(f"const int {const:<{WIDTH}} = {by_const[const]};")
    return 0


if __name__ == "__main__":
    sys.exit(main())
