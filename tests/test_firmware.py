"""The two optoisolator shields are wired differently, so their sketches carry
different pin numbers. What must never differ is the result: for any byte the
brain sends, both shields have to press the same buttons on the Xbox.

These tests parse the sketches and simulate them against each shield's recorded
physical wiring, so a typo'd pin or a reordered myPins[] fails here rather than
showing up as a bot that plays badly on one rig and fine on the other.
"""
import re
from pathlib import Path
import unittest

from robotron_ai.control import SerialController as SC

ARDUINO = Path(__file__).resolve().parents[1] / "arduino"

# What each pin physically presses on each board.
# v1: measured pin by pin on the rig, 2026-09-18, all ten confirmed.
# v2: derived from the legacy firmware it has run correctly for years, and
#     cross-checked against Strider's observation that its D3 hits D-pad up.
PHYSICAL = {
    "robotron_pad_v1": {3: "BACK", 4: "START", 5: "B", 6: "A", 7: "Y", 8: "X",
                        10: "DPAD_RIGHT", 11: "DPAD_DOWN", 12: "DPAD_UP", 13: "DPAD_LEFT"},
    "robotron_pad_v2": {3: "DPAD_UP", 4: "DPAD_DOWN", 5: "DPAD_LEFT", 6: "DPAD_RIGHT",
                        7: "X", 8: "Y", 10: "A", 11: "B", 12: "START", 13: "BACK"},
}
# constant name in the sketch -> the button that name claims
CLAIMS = {"backButton": "BACK", "startButton": "START", "bButton": "B", "aButton": "A",
          "yButton": "Y", "xButton": "X", "leftButton": "DPAD_LEFT",
          "rightButton": "DPAD_RIGHT", "downButton": "DPAD_DOWN", "upButton": "DPAD_UP"}
BIT_ORDER = ["yButton", "aButton", "bButton", "xButton",
             "upButton", "downButton", "rightButton", "leftButton"]


def load(rev):
    """Parse a sketch into (pin per constant, myPins order, start mask, back mask)."""
    ino = (ARDUINO / rev / f"{rev}.ino").read_text()
    pins = {}
    for name in CLAIMS:
        m = re.search(rf"const int {name}\s*=\s*(\d+);", ino)
        if m is None:
            raise AssertionError(f"{rev}: {name} not declared")
        pins[name] = int(m.group(1))
    body = ino.split("const int myPins[] = {")[1].split("};")[0]
    order = [ln.split("//")[0].strip().rstrip(",")
             for ln in body.splitlines() if ln.split("//")[0].strip()]
    start = int(re.search(r"startMask\s*=\s*B([01]{8})", ino).group(1), 2)
    back = int(re.search(r"backMask\s*=\s*B([01]{8})", ino).group(1), 2)
    return pins, order, start, back


def buttons_pressed(rev, byte):
    """Simulate the sketch plus that board's wiring: byte in, real buttons out."""
    pins, order, start, back = load(rev)
    wiring = PHYSICAL[rev]
    if byte == 0:
        driven = []
    elif byte == start:
        driven = ["startButton"]
    elif byte == back:
        driven = ["backButton"]
    else:
        driven = [order[i] for i in range(8) if byte & (1 << i)]
    return frozenset(wiring[pins[n]] for n in driven)


class FirmwareRevisionTest(unittest.TestCase):
    REVS = sorted(p.name for p in ARDUINO.glob("robotron_pad_*"))

    def test_there_are_sketches_to_check(self):
        self.assertTrue(self.REVS)

    def test_pin_numbers_match_the_recorded_wiring(self):
        """Each sketch's constants must say what its board actually does."""
        for rev in self.REVS:
            pins, _, _, _ = load(rev)
            with self.subTest(rev=rev):
                self.assertIn(rev, PHYSICAL, f"no recorded wiring for {rev}")
                for name, pin in pins.items():
                    self.assertEqual(PHYSICAL[rev].get(pin), CLAIMS[name],
                                     f"{rev}: {name}=D{pin} but D{pin} presses "
                                     f"{PHYSICAL[rev].get(pin)}")

    def test_pins_are_distinct_and_usable(self):
        for rev in self.REVS:
            pins, _, _, _ = load(rev)
            with self.subTest(rev=rev):
                self.assertEqual(len(set(pins.values())), len(pins), f"{rev} reuses a pin")
                for name, pin in pins.items():
                    self.assertTrue(2 <= pin <= 13, f"{rev}: {name}=D{pin} unusable")

    def test_bit_order_matches_control_py(self):
        """myPins[] is indexed by serial bit. Pin numbers may differ per board;
        this order may not."""
        for rev in self.REVS:
            _, order, start, back = load(rev)
            with self.subTest(rev=rev):
                self.assertEqual(order, BIT_ORDER)
                self.assertEqual(start, SC.START)
                self.assertEqual(back, SC.BACK)

    def test_every_shield_sends_the_xbox_the_same_thing(self):
        """The whole point: same byte in, same buttons out, on every board."""
        for byte in range(256):
            results = {rev: buttons_pressed(rev, byte) for rev in self.REVS}
            self.assertEqual(len(set(results.values())), 1,
                             f"byte 0x{byte:02X} differs between shields: "
                             + "; ".join(f"{r}={sorted(v)}" for r, v in results.items()))

    def test_move_left_shoot_up(self):
        """Strider's example, spelled out: move W, fire N."""
        byte = (SC._DIR_MASK[7] << 4) | SC._DIR_MASK[1]
        self.assertEqual(byte, 0x81)
        for rev in self.REVS:
            with self.subTest(rev=rev):
                self.assertEqual(buttons_pressed(rev, byte), frozenset({"DPAD_LEFT", "Y"}))

    def test_menu_bytes(self):
        for rev in self.REVS:
            with self.subTest(rev=rev):
                self.assertEqual(buttons_pressed(rev, SC.START), frozenset({"START"}))
                self.assertEqual(buttons_pressed(rev, SC.BACK), frozenset({"BACK"}))
                self.assertEqual(buttons_pressed(rev, 0), frozenset())


if __name__ == "__main__":
    unittest.main()
