"""Controllers — the output layer. Each turns a (move, fire) direction pair and
menu button presses into real input for one target.

    VgamepadController   virtual Xbox 360 pad, in-process (Xenia). Replaces the
                         old player.py TCP server: the brain calls it directly.
    SerialController     one-byte serial protocol to a custom controller device
                         (real Xbox 360 hardware over an Arduino/Teensy).

Both share the Controller interface so the harness never cares which is active.
Directions are 1..8 (compass N,NE,E,SE,S,SW,W,NW, y-down); 0 = neutral.
"""
from abc import ABC, abstractmethod

from . import coords


class Controller(ABC):
    """Abstract output device. move_shoot() is called every decision tick."""

    @abstractmethod
    def move_shoot(self, move_dir: int, fire_dir: int) -> None:
        """Apply a move direction and a fire direction (each 1..8; 0 = neutral)."""

    @abstractmethod
    def neutral(self) -> None:
        """Release everything (sticks centred, no buttons)."""

    def press_a(self) -> None:      # menu nav — optional per device
        pass

    def press_b(self) -> None:
        pass

    def press_start(self) -> None:
        pass

    def close(self) -> None:
        self.neutral()


# ── Virtual gamepad (Xenia) ─────────────────────────────────────────────────
class VgamepadController(Controller):
    """Direct in-process virtual Xbox 360 pad via vgamepad. The pad appears as
    XInput User 0, which Xenia reads natively — no socket, no separate process.

    If vgamepad (or its ViGEmBus driver) is unavailable, falls back to a
    simulate mode so the rest of the tool still runs for testing.
    """

    def __init__(self, button_tap_s: float = 0.15, simulate: bool = False):
        self.button_tap_s = button_tap_s
        self._vg = None
        self.pad = None
        if not simulate:
            try:
                import vgamepad as vg
                self._vg = vg
                self.pad = vg.VX360Gamepad()
                self.pad.update()
                print("[vgamepad] virtual Xbox 360 pad ready (XInput User 0)")
            except Exception as e:
                print(f"[vgamepad] unavailable ({e}) - SIMULATING output")
        else:
            print("[vgamepad] simulate mode - no real pad")

    def move_shoot(self, move_dir: int, fire_dir: int) -> None:
        mx, my = coords.DIR_TO_STICK.get(move_dir, (0.0, 0.0))
        sx, sy = coords.DIR_TO_STICK.get(fire_dir, (0.0, 0.0))
        if self.pad is None:
            return
        self.pad.left_joystick_float(x_value_float=mx, y_value_float=my)
        self.pad.right_joystick_float(x_value_float=sx, y_value_float=sy)
        self.pad.update()

    def neutral(self) -> None:
        if self.pad is None:
            return
        self.pad.reset()
        self.pad.update()

    def _tap(self, button) -> None:
        if self.pad is None:
            return
        import time
        self.pad.press_button(button=button)
        self.pad.update()
        time.sleep(self.button_tap_s)
        self.pad.release_button(button=button)
        self.pad.update()

    def press_a(self) -> None:
        if self._vg:
            self._tap(self._vg.XUSB_BUTTON.XUSB_GAMEPAD_A)

    def press_b(self) -> None:
        if self._vg:
            self._tap(self._vg.XUSB_BUTTON.XUSB_GAMEPAD_B)

    def press_start(self) -> None:
        if self._vg:
            self._tap(self._vg.XUSB_BUTTON.XUSB_GAMEPAD_START)

    def close(self) -> None:
        self.neutral()


# ── Serial controller (real Xbox hardware) ──────────────────────────────────
class SerialController(Controller):
    """Drives a custom serial controller device over one byte per update.

    Wire format (matches the existing firmware): the high nibble is the move
    D-pad, the low nibble is the fire direction, each a bitmask of
    UP|DOWN|RIGHT|LEFT. Menu buttons are sent as their own bytes.

        byte = (dir_mask[move] << 4) | dir_mask[fire]

    Direction indices 1..8 map exactly to the FSM's compass order, so no
    remapping is needed. If the port can't be opened, falls back to simulate.
    """
    UP, DOWN, RIGHT, LEFT = 1, 2, 4, 8
    BTN_Y, BTN_A, BTN_B, BTN_X = 1, 2, 4, 8
    START = 0b11000000
    BACK = 0b00110000

    # index (0..8) -> D-pad bitmask. 1..8 = N,NE,E,SE,S,SW,W,NW.
    _DIR_MASK = [
        0,
        UP, UP | RIGHT, RIGHT, DOWN | RIGHT,
        DOWN, DOWN | LEFT, LEFT, UP | LEFT,
    ]

    def __init__(self, port: str, baud: int = 9600, button_tap_s: float = 0.3,
                 simulate: bool = False):
        self.button_tap_s = button_tap_s
        self.ser = None
        if not simulate:
            try:
                import serial
                self.ser = serial.Serial(port, baud)
                print(f"[serial] connected to {port} @ {baud}")
            except Exception as e:
                print(f"[serial] cannot open {port} ({e}) - SIMULATING output")
        else:
            print("[serial] simulate mode - no real device")

    def _write(self, val: int) -> None:
        if self.ser is None:
            print(f"[serial] (sim) 0x{val:02X}")
            return
        try:
            self.ser.write(val.to_bytes(1, byteorder="big"))
            self.ser.flush()
            self.ser.flushInput()
        except Exception as e:
            print(f"[serial] write error: {e}")

    def move_shoot(self, move_dir: int, fire_dir: int) -> None:
        m = self._DIR_MASK[move_dir] if 0 <= move_dir <= 8 else 0
        f = self._DIR_MASK[fire_dir] if 0 <= fire_dir <= 8 else 0
        self._write((m << 4) | f)

    def neutral(self) -> None:
        self._write(0)

    def _quick_press(self, byte: int) -> None:
        import time
        time.sleep(self.button_tap_s)
        self._write(byte)
        time.sleep(self.button_tap_s)
        self._write(0)

    def press_a(self) -> None:
        self._quick_press(self.BTN_A)

    def press_b(self) -> None:
        self._quick_press(self.BTN_B)

    def press_start(self) -> None:
        self._quick_press(self.START)

    def close(self) -> None:
        self.neutral()
        if self.ser is not None:
            self.ser.close()
