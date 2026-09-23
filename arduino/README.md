# Serial controller firmware

Firmware for the direct-wired Xbox 360 pad: an Arduino Uno driving
optoisolators soldered straight onto the button contacts of a wired 360
controller. It replaces the older X-Arcade path (Uno -> X-Arcade input adapter
-> X-Arcade 360 adapter -> console), which polled at 50 Hz.

Measured on the v1 rig 2026-09-18: press and release land in 9-12 ms, against a
39 ms median through the two X-Arcade adapters. The gain on the console itself
is not measured yet.

| sketch | use it for |
|--------|------------|
| `robotron_pad_v1/` | Strider's shield, the modified one. Pin map measured, all ten confirmed. |
| `robotron_pad_v2/` | Eric's shield, the clean one. Pin map derived from the firmware it has run for years. |
| `pin_probe/` | bring-up only: drives one pin at a time so any shield can be measured. |

## Protocol

One byte per decision tick, defined by `SerialController` in `control.py`. The
high nibble is the move D-pad, the low nibble is the fire direction.

| bit | value | button | meaning | bit | value | button | meaning |
|-----|-------|--------|------------|-----|-------|-------------|------------|
| 0 | 0x01 | Y | fire up | 4 | 0x10 | D-pad up | move up |
| 1 | 0x02 | A | fire down | 5 | 0x20 | D-pad down | move down |
| 2 | 0x04 | B | fire right | 6 | 0x40 | D-pad right | move right |
| 3 | 0x08 | X | fire left | 7 | 0x80 | D-pad left | move left |

`0x00` releases everything. `0xC0` is Start and `0x30` is Back; both are safe
escapes because a direction mask never sets up+down or left+right together.

This is identical on every shield. Only the pin numbers differ, so `myPins[]`
must never be reordered. `tests/test_control_latency.py` fails if any sketch
drifts from `control.py`, reuses a pin, or names a pin outside 2..13.

## Pin maps

The shields are hand-built and their pin order differs. Both use the same ten
pins, D3 to D8 and D10 to D13, just assigned to different buttons.

| Uno pin | v1 | v2 |
|---------|----|----|
| D3 | Back | D-pad up |
| D4 | Start | D-pad down |
| D5 | B | D-pad left |
| D6 | A | D-pad right |
| D7 | Y | X |
| D8 | X | Y |
| D10 | D-pad right | A |
| D11 | D-pad down | B |
| D12 | D-pad up | Start |
| D13 | D-pad left | Back |

D9 is unused on both. D13 drives the Uno's onboard LED, so the bootloader taps
whatever D13 is wired to on every reset, including when a program opens the
serial port. That is D-pad left on v1 and Back on v2.

**v1** was measured pin by pin on the assembled rig, all ten confirmed.

**v2** was derived, not probed. It has run the legacy `serial_pin_monitor`
firmware correctly for years, and that firmware plus the byte layout above pins
every channel down exactly: the legacy sketch drove `leftButton` (D3) from the
move-up bit, so D3 must physically press D-pad up. That matches the one thing
observed directly on the board, which is that D3 hits up where v1 hits Back.
The legacy names were misleading in the same way throughout: it called D10
`xButton` while D10 really presses A.

If Eric's Uno turns out to run a locally modified sketch, the derivation moves.
Probing takes about a minute, below.

## Measure a shield's pin map

Takes about a minute and works for any revision, including a future v3. The
pad's USB goes into the PC, not the console, and the Arduino IDE Serial Monitor
must be closed because it holds the COM port.

1. Flash `pin_probe`.
2. Run `python -m robotron_ai.tools.discover_pad_pins --port COM3`.
3. Paste the block it prints over the pin numbers in the matching sketch.
4. Flash that sketch.

It names any pin that presses nothing, presses two buttons at once, or changes
answer between passes, and refuses to emit a block until the rig is clean.

## Verify after flashing

    python -m robotron_ai.tools.verify_pad_wiring --port COM3

Walks all 81 move/fire pairs plus Start, Back, A and B, and names any wire that
is wrong. For latency only:

    python -m robotron_ai.tools.measure_control_latency --port COM3
