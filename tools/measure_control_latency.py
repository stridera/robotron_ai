"""Measure the CONTROL-chain latency in isolation: serial byte -> Arduino ->
optoisolators -> X-Arcade adapters -> USB controller state on the PC.

The bot's reversal test measures the whole loop (command to pixels); this
splits off the controller side. Plug the X-Arcade Xbox 360 adapter's output
into the PC instead of the console (the adapter kit supports PC), then:

    .venv\\Scripts\\python -m robotron_ai.tools.measure_control_latency --port COM3

It presses A through the serial box, polls the pad state as fast as Windows
allows (XInput; falls back to the legacy joystick API), and reports the
press and release delays over many trials. Subtract the median from the
end-to-end loop time and the remainder is the render/output/capture side.

No dependencies beyond pyserial and the Windows APIs.
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import datetime
import platform
import statistics
import sys
import time

# Serial box protocol (arduino/serial_pin_monitor.ino): bit i -> pin order
# [Y, X, B, A, LEFT, RIGHT, UP, DOWN]; 0 releases everything.
BIT = dict(Y=1, X=2, B=4, A=8, LEFT=16, RIGHT=32, UP=64, DOWN=128)
XINPUT_BUTTON = dict(DPAD_UP=0x0001, DPAD_DOWN=0x0002, DPAD_LEFT=0x0004, DPAD_RIGHT=0x0008,
                     START=0x0010, BACK=0x0020, A=0x1000, B=0x2000, X=0x4000, Y=0x8000)


class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [("wButtons", wt.WORD), ("bLeftTrigger", ctypes.c_ubyte),
                ("bRightTrigger", ctypes.c_ubyte), ("sThumbLX", ctypes.c_short),
                ("sThumbLY", ctypes.c_short), ("sThumbRX", ctypes.c_short),
                ("sThumbRY", ctypes.c_short)]


class XINPUT_STATE(ctypes.Structure):
    _fields_ = [("dwPacketNumber", wt.DWORD), ("Gamepad", XINPUT_GAMEPAD)]


def print_environment(port, baud, trials, button, interval):
    """This runs on someone else's machine and only its output comes back, so
    everything needed to interpret a number has to be printed with it."""
    print("=== environment ===")
    print(f"  when    : {datetime.datetime.now().astimezone().isoformat(timespec='seconds')}")
    print(f"  os      : {platform.system()} {platform.release()} {platform.version()}")
    print(f"  python  : {sys.version.split()[0]}")
    try:
        import serial
        print(f"  pyserial: {serial.__version__}")
    except Exception as e:
        print(f"  pyserial: unavailable ({e})")
    print(f"  serial  : port {port} at {baud} baud, {trials} trials of button {button} "
          f"({interval}s apart)")
    print("  the serial byte is one bit per pin, order [Y, X, B, A, LEFT, RIGHT, UP, DOWN];")
    print("  0 releases everything (arduino/serial_pin_monitor.ino)")


class XInputReader:
    """Reads one XInput pad. Returns (buttons, lx, ly) or None if absent."""
    def __init__(self, index=0):
        self.index = index
        self.dll = None
        self.dll_name = None
        for name in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
            try:
                self.dll = ctypes.WinDLL(name)
                self.dll_name = name
                break
            except OSError:
                continue
        if self.dll is None:
            raise OSError("no XInput DLL")
        self.dll.XInputGetState.argtypes = [wt.DWORD, ctypes.POINTER(XINPUT_STATE)]
        self.dll.XInputGetState.restype = wt.DWORD
        self.state = XINPUT_STATE()

    def read(self):
        if self.dll.XInputGetState(self.index, ctypes.byref(self.state)) != 0:
            return None
        g = self.state.Gamepad
        return (g.wButtons, g.sThumbLX, g.sThumbLY)

    @staticmethod
    def describe(before, after):
        changed = []
        b0, x0, y0 = before
        b1, x1, y1 = after
        for name, mask in XINPUT_BUTTON.items():
            if (b0 & mask) != (b1 & mask):
                changed.append(name)
        if abs(x1 - x0) > 8000 or abs(y1 - y0) > 8000:
            changed.append("LEFT_STICK")
        return changed


class JoyReader:
    """Legacy winmm joystick API fallback (any HID game controller)."""
    class JOYINFOEX(ctypes.Structure):
        _fields_ = [("dwSize", wt.DWORD), ("dwFlags", wt.DWORD), ("dwXpos", wt.DWORD),
                    ("dwYpos", wt.DWORD), ("dwZpos", wt.DWORD), ("dwRpos", wt.DWORD),
                    ("dwUpos", wt.DWORD), ("dwVpos", wt.DWORD), ("dwButtons", wt.DWORD),
                    ("dwButtonNumber", wt.DWORD), ("dwPOV", wt.DWORD),
                    ("dwReserved1", wt.DWORD), ("dwReserved2", wt.DWORD)]

    def __init__(self, index=0):
        self.index = index
        self.dll = ctypes.WinDLL("winmm")
        self.info = self.JOYINFOEX()
        self.info.dwSize = ctypes.sizeof(self.JOYINFOEX)
        self.info.dwFlags = 0xFF   # JOY_RETURNALL

    def read(self):
        if self.dll.joyGetPosEx(self.index, ctypes.byref(self.info)) != 0:
            return None
        i = self.info
        return (i.dwButtons, int(i.dwXpos) - 32767, int(i.dwYpos) - 32767)

    @staticmethod
    def describe(before, after):
        changed = []
        if before[0] != after[0]:
            changed.append(f"buttons 0x{before[0]:x}->0x{after[0]:x}")
        if abs(after[1] - before[1]) > 8000 or abs(after[2] - before[2]) > 8000:
            changed.append("axis")
        return changed


def wait_change(reader, baseline, timeout_s):
    """Spin until the pad state differs from baseline; return (dt_ms, state)."""
    t0 = time.perf_counter()
    while True:
        st = reader.read()
        if st is not None and st != baseline:
            return (time.perf_counter() - t0) * 1000.0, st
        if time.perf_counter() - t0 > timeout_s:
            return None, st


def summarize(samples):
    if not samples:
        return dict(n=0)
    s = sorted(samples)
    return dict(n=len(s), median_ms=round(statistics.median(s), 1),
                p10_ms=round(s[int(0.1 * len(s))], 1), p90_ms=round(s[int(0.9 * len(s))], 1),
                min_ms=round(s[0], 1), max_ms=round(s[-1], 1))


def run(port, baud, trials, interval, button, reader):
    import serial
    ser = serial.Serial(port, baud)
    code = BIT[button]
    press, release = [], []
    what = set()
    try:
        ser.write(b"\x00"); ser.flush()
        time.sleep(0.5)
        for i in range(trials):
            base = reader.read()
            if base is None:
                print("no controller state readable — is the adapter plugged into the PC?")
                return None
            ser.write(bytes([code])); ser.flush()
            dt, st = wait_change(reader, base, 1.0)
            if dt is None:
                print(f"trial {i + 1}: no change seen within 1 s (button {button} = 0x{code:02x})")
            else:
                press.append(dt)
                what.update(reader.describe(base, st))
            time.sleep(interval)
            base = reader.read()
            ser.write(b"\x00"); ser.flush()
            dt, _ = wait_change(reader, base, 1.0)
            if dt is not None:
                release.append(dt)
            time.sleep(interval)
            print(f"trial {i + 1}/{trials}: press {press[-1] if press else '-'} ms  "
                  f"release {release[-1] if release else '-'} ms", flush=True)
    finally:
        try:
            ser.write(b"\x00"); ser.flush(); ser.close()
        except Exception:
            pass
    rep = dict(button=button, changed=sorted(what), press=summarize(press),
               release=summarize(release))
    print()
    print(f"control-chain latency, {button} through the serial box:")
    print(f"  press   : {rep['press']}")
    print(f"  release : {rep['release']}")
    print(f"  what changed on the pad: {rep['changed'] or 'nothing recognised'}")
    print("  (the bot's end-to-end reversal latency on the console is ~200-270 ms;"
          " the remainder after this number is the render/output/capture side)")
    if rep["changed"] and button not in rep["changed"]:
        print(f"  NOTE: we drove the {button} line but the pad reported "
              f"{', '.join(rep['changed'])}. The adapter maps the lines differently on PC")
        print("  than on the console; this measures the timing all the same.")
    press = rep["press"]
    if press.get("n", 0) >= 4 and press.get("p90_ms") and press.get("p10_ms"):
        step = press["p90_ms"] - press["p10_ms"]
        if step > 8.0:
            print(f"  the spread runs {press['p10_ms']}-{press['p90_ms']} ms. If the values sit")
            print(f"  at two or three levels about {step:.0f} ms apart rather than scattered,")
            print("  that is a polling interval in the chain, not jitter: the device samples")
            print(f"  its inputs every ~{step:.0f} ms and a press waits for the next sample.")
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", default="COM3")
    ap.add_argument("--baud", type=int, default=9600)
    ap.add_argument("--trials", type=int, default=40)
    ap.add_argument("--interval", type=float, default=0.4, help="seconds between presses")
    ap.add_argument("--button", default="A", choices=sorted(BIT))
    ap.add_argument("--api", default="auto", choices=["auto", "xinput", "joy"])
    ap.add_argument("--index", type=int, default=0, help="controller index")
    a = ap.parse_args(argv)
    print_environment(a.port, a.baud, a.trials, a.button, a.interval)
    reader = None
    if a.api in ("auto", "xinput"):
        try:
            r = XInputReader(a.index)
            if r.read() is not None:
                reader = r
                print(f"  reader  : XInput controller {a.index} via {r.dll_name}.dll")
        except OSError:
            pass
    if reader is None and a.api in ("auto", "joy"):
        r = JoyReader(a.index)
        if r.read() is not None:
            reader = r
            print(f"  reader  : legacy winmm joystick {a.index} (no XInput pad found)")
    if reader is None:
        sys.exit("no controller visible to Windows. Plug the X-Arcade Xbox 360 "
                 "adapter's USB output into this PC (not the console) and check "
                 "it appears in 'Set up USB game controllers'.")
    return run(a.port, a.baud, a.trials, a.interval, a.button, reader)


if __name__ == "__main__":
    main()
