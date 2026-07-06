"""Command-line entry point. Selects an input source, an output method, and the
matching harness from flags (or a JSON config file) with sensible per-mode
defaults, wires them together, and runs.

Two modes:
  xenia     emulator on this PC. Default: memory input + virtual gamepad (the
            wave-138 config). --input yolo switches to vision.
  hardware  real Xbox 360 over an HDMI capture card + serial controller. Vision
            is the only possible input; serial the only output.

Examples:
  # Best emulator bot (memory + vgamepad), play forever:
  python -m robotron_ai --mode xenia --loop

  # Emulator, vision input instead of memory:
  python -m robotron_ai --mode xenia --input yolo --loop

  # Real Xbox: HDMI capture on device 0, serial controller on COM3:
  python -m robotron_ai --mode hardware --device 0 --port COM3

  # Dry-run the wiring with no real devices:
  python -m robotron_ai --mode xenia --simulate --no-start
"""
import argparse
import json
import os
import sys

from . import brain as brain_mod
from . import control
from . import harness
from . import perception as perc

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_WEIGHTS = os.path.join(_PKG_DIR, "weights", "robotron.pt")

# Per-mode preset defaults. Any value left None on the command line (and absent
# from --config) is filled from here.
MODE_PRESETS = {
    "xenia": dict(input="memory", output="vgamepad", source="window"),
    "hardware": dict(input="yolo", output="serial", source="hdmi"),
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="robotron_ai",
        description="Configurable Robotron 2084 AI player (Xenia emulator or real Xbox).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--mode", choices=["xenia", "hardware"], default="xenia",
                   help="target environment preset")
    p.add_argument("--config", default=None,
                   help="JSON file of defaults (command-line flags still win)")

    io = p.add_argument_group("input / output")
    io.add_argument("--input", choices=["memory", "yolo"], default=None,
                    help="perception source (hardware forces yolo)")
    io.add_argument("--output", choices=["vgamepad", "serial"], default=None,
                    help="controller (hardware forces serial)")
    io.add_argument("--source", choices=["window", "hdmi"], default=None,
                    help="frame source for yolo input")
    io.add_argument("--device", default=None,
                    help="HDMI capture device index or path (hdmi source)")
    io.add_argument("--port", default=None,
                    help="serial port for the hardware controller (e.g. COM3)")
    io.add_argument("--baud", type=int, default=9600, help="serial baud rate")
    io.add_argument("--simulate", action="store_true",
                    help="don't open real devices — print output instead (testing)")

    vis = p.add_argument_group("vision (yolo)")
    vis.add_argument("--weights", default=None,
                     help=f"YOLO weights (default: bundled {os.path.basename(DEFAULT_WEIGHTS)})")
    vis.add_argument("--conf", type=float, default=0.4,
                     help="YOLO confidence floor (raised per-class internally)")
    vis.add_argument("--track", action="store_true",
                     help="use ByteTrack temporal smoothing instead of per-frame predict")
    vis.add_argument("--player-hold", type=int, default=6,
                     help="max blind frames to hold last player position")

    brn = p.add_argument_group("brain")
    brn.add_argument("--hz", type=float, default=15.0,
                     help="decision rate (do not change: planner is tuned for 15)")
    brn.add_argument("--lag-ticks", type=float, default=None,
                     help="latency extrapolation (default: 0.25 memory / 1.0 vision)")
    brn.add_argument("--player-lead", type=float, default=None,
                     help="player forward-prediction ticks (default: 0.45 memory / 0 vision)")
    brn.add_argument("--vel-ema", type=float, default=0.5,
                     help="velocity EMA alpha (1.0 = raw, lower = smoother)")
    brn.add_argument("--no-frame-sync", action="store_true",
                     help="disable 60Hz frame-sync (memory input only)")

    run = p.add_argument_group("run")
    run.add_argument("--loop", action="store_true",
                     help="xenia: replay games back-to-back")
    run.add_argument("--no-start", action="store_true",
                     help="xenia: skip menu navigation (game already running)")
    run.add_argument("--start", action="store_true",
                     help="hardware: send a blind start-button sequence first")
    run.add_argument("--visualize", "--show-overlay", action="store_true",
                     dest="visualize",
                     help="open a live window showing the feed with annotated "
                          "sprite boxes, player, threat vectors, and the chosen "
                          "move/fire (debug/demo). q or close to hide.")
    run.add_argument("--debug", action="store_true", help="verbose per-tick output")
    return p


def resolve_config(argv=None) -> argparse.Namespace:
    """Parse args, layer in --config, apply mode presets, and validate."""
    args = build_parser().parse_args(argv)

    # Layer a JSON config UNDER the command line: only fills values the user
    # didn't set (argparse default None / False).
    if args.config:
        with open(args.config) as f:
            cfg = json.load(f)
        for k, v in cfg.items():
            if hasattr(args, k) and getattr(args, k) in (None, False):
                setattr(args, k, v)

    preset = MODE_PRESETS[args.mode]
    for k in ("input", "output", "source"):
        if getattr(args, k) is None:
            setattr(args, k, preset[k])

    # ── Validate / force mode invariants ──
    if args.mode == "hardware":
        if args.input == "memory":
            sys.exit("error: --mode hardware has no memory access; use --input yolo")
        if args.output != "serial":
            print("[cli] hardware mode: forcing --output serial")
            args.output = "serial"
        args.source = "hdmi"
    if args.input == "yolo" and args.weights is None:
        args.weights = DEFAULT_WEIGHTS
    if args.output == "serial" and args.port is None:
        args.port = "COM3"
        print(f"[cli] no --port given; defaulting serial to {args.port}")

    # Brain defaults depend on the input path's freshness.
    if args.lag_ticks is None:
        args.lag_ticks = (brain_mod.DEFAULT_LAG_MEMORY if args.input == "memory"
                          else brain_mod.DEFAULT_LAG_VISION)
    if args.player_lead is None:
        args.player_lead = (brain_mod.DEFAULT_PLAYER_LEAD if args.input == "memory"
                            else 0.0)
    # Frame-sync only makes sense reading guest memory each tick.
    args.frame_sync = (args.input == "memory") and not args.no_frame_sync
    return args


def _build_controller(cfg):
    if cfg.output == "vgamepad":
        return control.VgamepadController(simulate=cfg.simulate)
    return control.SerialController(cfg.port, baud=cfg.baud, simulate=cfg.simulate)


def _build_perception(cfg):
    if cfg.input == "memory":
        return perc.MemoryPerception()
    # vision
    if cfg.source == "hdmi":
        dev = cfg.device
        if isinstance(dev, str) and dev.isdigit():
            dev = int(dev)
        source = perc.HdmiSource(device=0 if dev is None else dev)
    else:
        source = perc.XeniaWindowSource()
    if not os.path.exists(cfg.weights):
        sys.exit(f"error: weights not found: {cfg.weights}")
    print(f"[cli] YOLO weights: {cfg.weights}")
    vp = perc.VisionPerception(source, cfg.weights, conf=cfg.conf,
                               track=cfg.track, max_player_hold=cfg.player_hold)
    vp.collect_viz = cfg.visualize        # collect screen boxes for the overlay
    return vp


def main(argv=None) -> None:
    cfg = resolve_config(argv)
    print(f"[cli] mode={cfg.mode} input={cfg.input} output={cfg.output} "
          f"source={cfg.source if cfg.input == 'yolo' else '-'} "
          f"lag={cfg.lag_ticks} lead={cfg.player_lead} "
          f"frame_sync={cfg.frame_sync}")

    brain = brain_mod.ChampionBrain(
        lag_ticks=cfg.lag_ticks, player_lead_ticks=cfg.player_lead,
        vel_ema_alpha=cfg.vel_ema, debug=cfg.debug)
    controller = _build_controller(cfg)

    from .visualize import Visualizer
    visualizer = Visualizer(enabled=cfg.visualize)

    try:
        if cfg.mode == "hardware":
            perception = _build_perception(cfg)
            harness.play_vision_game(brain, perception, controller,
                                     hz=cfg.hz, start_seq=cfg.start, debug=cfg.debug,
                                     visualizer=visualizer)
        else:
            # Xenia: memory bookkeeping harness (works for memory OR vision input).
            from .engine.game_state import GameStateReader
            from .engine.xenia_memory import XeniaMemory
            gsr = GameStateReader(XeniaMemory())
            perception = _build_perception(cfg)
            # Memory input has no frame of its own; grab the Xenia window as the
            # overlay backdrop. Vision input reuses the frame YOLO saw.
            backdrop = None
            if cfg.visualize and cfg.input == "memory":
                backdrop = perc.XeniaWindowSource()
            skip_start = cfg.no_start
            while True:
                if not skip_start:
                    harness.wait_for_game_start(controller, gsr)
                w, s, d = harness.play_memory_game(
                    brain, perception, controller, gsr,
                    frame_sync=cfg.frame_sync, hz=cfg.hz,
                    visualizer=visualizer, backdrop=backdrop)
                print(f"[cli] RESULT  wave {w}  score {s}  deaths {d}")
                if not cfg.loop:
                    break
                skip_start = False
                brain.reset()
                perception.reset()
                import time
                time.sleep(2.0)
    except KeyboardInterrupt:
        print("\n[cli] stopped by user")
    finally:
        controller.close()
        visualizer.close()


if __name__ == "__main__":
    main()
