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
    io.add_argument("--capture-backend", choices=["auto", "msmf", "dshow"],
                    default="auto", help="capture API for the card (hdmi)")
    io.add_argument("--capture-fourcc", default=None,
                    help="capture pixel format to request, e.g. MJPG or YUY2")
    io.add_argument("--capture-fps", type=int, default=None,
                    help="capture rate to request from the card, e.g. 60")
    io.add_argument("--capture-res", default=None,
                    help="capture size to request, e.g. 1920x1080 (downscaled "
                         "to 1280x720 for the model)")
    io.add_argument("--probe-capture", action="store_true",
                    help="measure every capture backend/format on --device and "
                         "print the best flags, then exit (no game needed)")
    io.add_argument("--port", default=None,
                    help="serial port for the hardware controller (e.g. COM3)")
    io.add_argument("--baud", type=int, default=9600, help="serial baud rate")
    io.add_argument("--simulate", action="store_true",
                    help="don't open real devices — print output instead (testing)")

    vis = p.add_argument_group("vision (yolo)")
    vis.add_argument("--weights", default=None,
                     help=f"YOLO weights (default: bundled {os.path.basename(DEFAULT_WEIGHTS)})")
    vis.add_argument("--conf", type=float, default=0.30,
                     help="YOLO confidence floor (raised per-class internally). "
                          "0.30 is the validated production setting; note it "
                          "FLOORS the per-class gates, so lower values let the "
                          "hand-tuned per-class table take effect instead")
    vis.add_argument("--track", action="store_true",
                     help="use ByteTrack temporal smoothing instead of per-frame predict")
    vis.add_argument("--player-hold", type=int, default=6,
                     help="max blind frames to hold last player position")
    vis.add_argument("--threaded-eye", action="store_true",
                     help="run capture+inference on a background thread and "
                          "decide on the freshest result (implied by --eye-sync)")
    vis.add_argument("--eye-sync", type=float, default=0.0, metavar="MS",
                     help="eye-synchronised decisions: after MS ms since the "
                          "last decision, decide the moment the next eye "
                          "sample lands (e.g. 55 -> ~14 Hz, vision age 0.82 "
                          "-> 0.51 ticks on the emulator). 0 = fixed clock")
    vis.add_argument("--hold-action", type=int, default=0, metavar="N",
                     help="on a blind tick repeat the last stick command for "
                          "up to N ticks instead of going neutral (0 = off)")
    vis.add_argument("--center-off", default=None,
                     help="manual box-center correction 'dx,dy' in px, added "
                          "to every detection (from offline analysis of the "
                          "telemetry's box_center diagnostic; default none)")
    vis.add_argument("--imgsz", type=int, default=None,
                     help="inference size override (default: model native "
                          "1280). WARNING: 640 measured on hardware round 2 "
                          "breaks classification (player read as Civilian, "
                          "player_visible 0.20) — don't use it; fix speed "
                          "with CUDA torch instead")

    brn = p.add_argument_group("brain")
    brn.add_argument("--hz", type=float, default=15.0,
                     help="decision rate (do not change: planner is tuned for 15)")
    brn.add_argument("--lag-ticks", type=float, default=None,
                     help="latency extrapolation (default: 0.25 memory / 0.3 vision)")
    brn.add_argument("--player-lead", type=float, default=None,
                     help="player forward-prediction ticks "
                          "(default: 0.45 memory / 1.5 vision)")
    brn.add_argument("--vel-ema", type=float, default=0.5,
                     help="velocity EMA alpha (1.0 = raw, lower = smoother)")
    brn.add_argument("--no-frame-sync", action="store_true",
                     help="disable 60Hz frame-sync (memory input only)")

    run = p.add_argument_group("run")
    run.add_argument("--games", type=int, default=0,
                     help="hardware --loop: stop cleanly after N completed "
                          "games (0 = run until Ctrl+C)")
    run.add_argument("--loop", action="store_true",
                     help="replay games back-to-back (hardware: auto-restart "
                          "after game over via the vision-guarded navigator)")
    run.add_argument("--no-start", action="store_true",
                     help="xenia: skip menu navigation (game already running)")
    run.add_argument("--start", action="store_true",
                     help="hardware: send a blind start-button sequence first")
    run.add_argument("--menu-start", action="store_true",
                     help="menu nav may press Start before the A presses "
                          "(default OFF: real-hardware round 1 showed Start "
                          "backs out of the console's menus; A alone is safe)")
    run.add_argument("--visualize-plain", action="store_true",
                     help="with --visualize: show the raw feed without "
                          "detection boxes/arrows")
    run.add_argument("--visualize", "--show-overlay", action="store_true",
                     dest="visualize",
                     help="open a live window showing the feed with annotated "
                          "sprite boxes, player, threat vectors, and the chosen "
                          "move/fire (debug/demo). q or close to hide.")
    run.add_argument("--debug", action="store_true", help="verbose per-tick output")
    run.add_argument("--no-hud", action="store_true",
                     help="hardware: disable HUD OCR bookkeeping (score/wave/"
                          "death tracking read off the video feed)")
    run.add_argument("--hud-log", default=None,
                     help="hardware: per-wave JSONL path for HUD bookkeeping "
                          "(default: robotron_ai/logs/hud_waves.jsonl; "
                          "analysable with robotron/ab_yolo.py --log)")
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
        # serial + hdmi are the hardware DEFAULTS, but explicit flags win:
        # `--mode hardware --source window --output vgamepad` runs the exact
        # hardware code path (vision loop, HUD bookkeeping, guarded menu nav,
        # telemetry) against the emulator — the end-to-end rehearsal rig.
        if args.output != "serial":
            print(f"[cli] hardware mode with --output {args.output} — "
                  f"HARDWARE-SIM (emulator rehearsal), not a real rig")
        if args.source != "hdmi":
            print(f"[cli] hardware mode with --source {args.source} — "
                  f"HARDWARE-SIM (emulator rehearsal), not a real rig")
    if args.input == "yolo" and args.weights is None:
        args.weights = DEFAULT_WEIGHTS
    if args.output == "serial" and args.port is None:
        args.port = "COM3"
        print(f"[cli] no --port given; defaulting serial to {args.port}")

    # Brain defaults depend on the input path's freshness.
    if args.lag_ticks is None:
        args.lag_ticks = (brain_mod.DEFAULT_LAG_MEMORY if args.input == "memory"
                          else brain_mod.DEFAULT_LAG_VISION)
    args.auto_lead = False
    if args.player_lead is None:
        # Per-path leads (2026-07-29 A/B, 30 games/arm): the vision path's
        # calibrator measures actuation at 2.0 ticks INCLUDING pipeline age,
        # so vision leads 1.5 (max wave 14.6 -> 18.0, p=0.003 vs the old
        # shared 0.45); memory keeps the W158-validated 0.45.
        args.player_lead = (brain_mod.DEFAULT_LEAD_MEMORY if args.input == "memory"
                            else brain_mod.DEFAULT_LEAD_VISION)
        # No explicit --player-lead: REAL hardware rigs refine it live from
        # the measured actuation latency (act in ticks varies with the
        # achieved cadence, so no fixed default fits every rig). Gated to the
        # hdmi source: the window-capture hardware-sim runs on the emulator,
        # whose act=2.0/lead=1.5 is A/B-validated — a noisy early
        # estimate must not override it (seen in rehearsal: early median 1.0).
        args.auto_lead = (args.mode == "hardware" and args.source == "hdmi")
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
        cap_size = None
        if cfg.capture_res:
            try:
                cw, ch = (int(v) for v in str(cfg.capture_res).lower().split("x"))
                cap_size = (cw, ch)
            except ValueError:
                sys.exit(f"error: --capture-res wants WxH, got {cfg.capture_res!r}")
        source = perc.HdmiSource(device=0 if dev is None else dev,
                                 backend=cfg.capture_backend,
                                 fourcc=cfg.capture_fourcc,
                                 fps=cfg.capture_fps, cap_size=cap_size)
    else:
        source = perc.XeniaWindowSource()
    if not os.path.exists(cfg.weights):
        sys.exit(f"error: weights not found: {cfg.weights}")
    print(f"[cli] YOLO weights: {cfg.weights}")
    vp = perc.VisionPerception(source, cfg.weights, conf=cfg.conf,
                               track=cfg.track, max_player_hold=cfg.player_hold,
                               imgsz=cfg.imgsz)
    if cfg.center_off:
        try:
            dx, dy = (float(v) for v in str(cfg.center_off).split(","))
            vp.center_off = (dx, dy)
            print(f"[cli] manual box-center correction: ({dx:+.1f}, {dy:+.1f})")
        except ValueError:
            sys.exit(f"error: --center-off wants 'dx,dy', got {cfg.center_off!r}")
    vp.collect_viz = cfg.visualize        # collect screen boxes for the overlay
    if getattr(cfg, "threaded_eye", False) or getattr(cfg, "eye_sync", 0):
        print("[cli] threaded eye: capture+inference on a background thread"
              + (f", eye-sync floor {cfg.eye_sync:.0f} ms" if cfg.eye_sync else ""))
        return perc.ThreadedVisionPerception(vp)
    return vp


def main(argv=None) -> None:
    cfg = resolve_config(argv)
    if cfg.probe_capture:
        # Measurement only: no game, no controller, no model. Prints the
        # ranked capture configurations and the flags to use.
        from . import capture_probe
        dev = cfg.device
        if isinstance(dev, str) and dev.isdigit():
            dev = int(dev)
        capture_probe.probe(0 if dev is None else dev)
        return
    print(f"[cli] mode={cfg.mode} input={cfg.input} output={cfg.output} "
          f"source={cfg.source if cfg.input == 'yolo' else '-'} "
          f"lag={cfg.lag_ticks} lead={cfg.player_lead} "
          f"frame_sync={cfg.frame_sync}")

    brain = brain_mod.ChampionBrain(
        lag_ticks=cfg.lag_ticks, player_lead_ticks=cfg.player_lead,
        vel_ema_alpha=cfg.vel_ema,
        use_coaster=(cfg.input == "yolo"),   # vision only; memory is exact
        debug=cfg.debug)
    controller = _build_controller(cfg)

    from .visualize import Visualizer
    visualizer = Visualizer(enabled=cfg.visualize)

    try:
        if cfg.mode == "hardware":
            # CPU-inference check: the single biggest perf factor found in
            # hardware round 1 (a CPU-bound rig caps near 7 Hz at imgsz 1280).
            try:
                import torch
                if not torch.cuda.is_available():
                    print("[cli] NOTE: torch has no CUDA — inference runs on "
                          "CPU (~7 Hz ceiling). Fix with BOTH commands, in "
                          "order:  pip uninstall torch torchvision torchaudio"
                          "  THEN  pip install torch torchvision --index-url "
                          "https://download.pytorch.org/whl/cu130 . "
                          "Or run with --hz 6. Do NOT use --imgsz 640: it "
                          "breaks player/civilian classification (measured).")
            except Exception:
                pass
            perception = _build_perception(cfg)
            # Telemetry is always on for hardware: the rig owner just sends
            # back logs/hardware_report/ and it answers the port questions
            # (act latency, cadence, capture pacing, detection/HUD health,
            # geometry) without them needing to know what any of it means.
            from .engine.clearance_planner import DXY
            from .telemetry import HardwareTelemetry
            telemetry = HardwareTelemetry(DXY)
            hud_reader = bookkeeper = None
            if not cfg.no_hud:
                from . import hud_ocr
                if os.path.exists(hud_ocr.DEFAULT_FONT):
                    hud_reader = hud_ocr.HudReader()
                    log = cfg.hud_log or os.path.join(_PKG_DIR, "logs",
                                                      "hud_waves.jsonl")

                    def _ev(kind, **kw):
                        if kind == 'game_over':
                            telemetry.game_over(**kw)
                        if kind == 'wave_end':
                            print(f"[hud] === WAVE {kw['wave']} done ===  "
                                  f"deaths {kw['deaths']}  score +{kw['score']}")
                        elif kind == 'death':
                            print(f"[hud]  ** DIED #{kw['deaths']} **  "
                                  f"W{kw['wave']}")
                        elif kind == 'game_over':
                            print(f"[hud] GAME OVER  W{kw['wave']} "
                                  f"S{kw['score']} D={kw['deaths']}")
                        elif kind == 'new_game':
                            print("[hud] new game detected")
                    bookkeeper = hud_ocr.VisionBookkeeper(log_path=log,
                                                          on_event=_ev)
                    print(f"[cli] HUD OCR bookkeeping on — wave log: {log}")
                else:
                    print("[cli] no HUD font (weights/hud_font.npz) — "
                          "running without score/wave bookkeeping")
            harness.play_vision_game(brain, perception, controller,
                                     hz=cfg.hz, start_seq=cfg.start, debug=cfg.debug,
                                     visualizer=visualizer,
                                     bookkeeper=bookkeeper, hud_reader=hud_reader,
                                     loop_games=cfg.loop, telemetry=telemetry,
                                     menu_start=cfg.menu_start,
                                     visualize_plain=cfg.visualize_plain,
                                     auto_lead=cfg.auto_lead,
                                     games_limit=cfg.games,
                                     eye_sync_ms=cfg.eye_sync,
                                     hold_action=cfg.hold_action)
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
