"""Tests for the control-chain latency tool's pure parts (no hardware)."""
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location(
    "mcl", Path(__file__).resolve().parents[1] / "tools" / "measure_control_latency.py")
mcl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mcl)


class FakeReader:
    def __init__(self, states):
        self.states = list(states)
        self.i = 0

    def read(self):
        s = self.states[min(self.i, len(self.states) - 1)]
        self.i += 1
        return s

    describe = staticmethod(mcl.XInputReader.describe)


class ControlLatencyToolTest(unittest.TestCase):
    def test_serial_bits_match_control_py(self):
        """The tool's byte table must match the bytes the bot actually sends.
        It did not until 2026-09-22 (Y, X, B, A), which is why two rounds of
        measurements reported "drove A, pad said X"."""
        from robotron_ai.control import SerialController as sc
        self.assertEqual(
            mcl.BIT,
            dict(Y=sc.BTN_Y, A=sc.BTN_A, B=sc.BTN_B, X=sc.BTN_X,
                 UP=sc.UP << 4, DOWN=sc.DOWN << 4, RIGHT=sc.RIGHT << 4, LEFT=sc.LEFT << 4))

    def test_wait_change_returns_when_state_differs(self):
        base = (0, 0, 0)
        r = FakeReader([base, base, (mcl.XINPUT_BUTTON["A"], 0, 0)])
        dt, st = mcl.wait_change(r, base, timeout_s=1.0)
        self.assertIsNotNone(dt)
        self.assertEqual(st[0], mcl.XINPUT_BUTTON["A"])
        self.assertEqual(mcl.XInputReader.describe(base, st), ["A"])

    def test_wait_change_times_out(self):
        base = (0, 0, 0)
        r = FakeReader([base])
        dt, _ = mcl.wait_change(r, base, timeout_s=0.02)
        self.assertIsNone(dt)

    def test_describe_sees_stick_and_dpad(self):
        self.assertEqual(mcl.XInputReader.describe((0, 0, 0), (0x0001, 0, 0)), ["DPAD_UP"])
        self.assertEqual(mcl.XInputReader.describe((0, 0, 0), (0, 30000, 0)), ["LEFT_STICK"])

    def test_summary(self):
        s = mcl.summarize([10.0, 20.0, 30.0, 40.0, 50.0])
        self.assertEqual(s["n"], 5)
        self.assertEqual(s["median_ms"], 30.0)
        self.assertEqual(mcl.summarize([])["n"], 0)


if __name__ == "__main__":
    unittest.main()
