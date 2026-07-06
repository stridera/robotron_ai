"""robotron_ai — a configurable Robotron 2084 AI player.

One decision core (evolved FSM + clearance planner) driven by swappable input
(guest memory or YOLO vision) and output (virtual gamepad or serial controller),
so the same bot runs on the Xenia emulator and on real Xbox 360 hardware.

Entry point: `python -m robotron_ai` (see cli.py) or `robotron_ai.cli.main()`.
"""
__version__ = "1.0.0"
