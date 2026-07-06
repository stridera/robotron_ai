# robotron_ai

A configurable **Robotron 2084 AI player**. One decision core (an evolved
finite-state machine + a minimal-deviation clearance planner that reached
**wave 138**) driven by swappable **input** and **output**, so the *same* bot
plays on the **Xenia emulator** and on **real Xbox 360 hardware**.

```
            INPUT (perception)                 BRAIN                OUTPUT (control)
  ┌─────────────────────────────────┐    ┌──────────────────┐   ┌─────────────────────┐
  │ memory   guest RAM  (Xenia)     │    │ velocity track   │   │ vgamepad  (Xenia)   │
  │ yolo     screen/HDMI + detector ├──▶│ latency predict  ├──▶│ serial    (real HW) │
  └─────────────────────────────────┘    │ FSM + planner    │   └─────────────────────┘
        window capture / HDMI card       └──────────────────┘     move+fire dirs 1..8
```

Everything lands in one **planner pixel space (665×492)** before the brain sees
it, so the input source is completely interchangeable.

---

## Two ways to run it

| | **Xenia (emulator)** | **Real Xbox 360 hardware** |
|---|---|---|
| Input | `memory` (best) or `yolo` | `yolo` (HDMI capture — only option) |
| Output | `vgamepad` (virtual pad) | `serial` (custom controller device) |
| Game state | read from guest RAM | none — vision only |
| Use case | development, best scores | play the real console |

---

## Install

Windows, Python 3.10+.

```powershell
python -m venv .venv
.venv\Scripts\pip install -r robotron_ai\requirements.txt
```

Notes:
- **vgamepad** needs the free **ViGEmBus** driver installed (one-time) for the
  virtual pad to appear to Xenia.
- **ultralytics** pulls in PyTorch; the first `yolo` run compiles kernels and is
  slow to start (a few seconds), then runs at full rate.
- A trained detector ships at `robotron_ai/weights/robotron.pt` — no training
  needed to use the vision path.

---

## Quickstart — Xenia (emulator)

1. Launch the custom **JIT-hook** `xenia_canary.exe` with the Robotron ROM (the
   memory path needs the hooked build; vision works with any build).
2. Run the bot — it navigates the menus itself and plays:

```powershell
# Best config: memory input + virtual gamepad, replay games forever
.venv\Scripts\python -m robotron_ai --mode xenia --loop
```

Vision input instead of memory (same emulator, YOLO drives decisions; memory is
still used only for score/death bookkeeping):

```powershell
.venv\Scripts\python -m robotron_ai --mode xenia --input yolo --loop
```

If the game is already in progress, add `--no-start` to skip menu navigation.

---

## Quickstart — real Xbox 360 hardware

You need:
- an **HDMI capture card** (appears as a webcam / cv2 video device), and
- the **serial controller device** wired to the Xbox controller (the firmware
  reads one byte per update — see *Serial protocol* below).

Start the game on the console, then:

```powershell
# HDMI capture on device 0, serial controller on COM3
.venv\Scripts\python -m robotron_ai --mode hardware --device 0 --port COM3
```

There is no memory access on real hardware, so the bot runs purely from vision:
it plans and acts whenever it can see the player, and goes neutral when it
can't. Start the game yourself, or pass `--start` to have it blindly press
Start + A a few times first. Stop with `Ctrl+C`.

---

## Configuration

Every flag has a sensible per-mode default; you usually only need `--mode` (plus
`--device`/`--port` on hardware).

| Flag | Default | Purpose |
|------|---------|---------|
| `--mode {xenia,hardware}` | `xenia` | Environment preset |
| `--input {memory,yolo}` | mode preset | Perception source (hardware forces `yolo`) |
| `--output {vgamepad,serial}` | mode preset | Controller (hardware forces `serial`) |
| `--source {window,hdmi}` | mode preset | Frame source for `yolo` input |
| `--device N` | `0` | HDMI capture device index/path |
| `--port COMx` | `COM3` | Serial port for the hardware controller |
| `--baud N` | `9600` | Serial baud rate |
| `--weights PATH` | bundled `robotron.pt` | YOLO detector weights |
| `--conf F` | `0.4` | YOLO confidence floor (raised per-class internally) |
| `--track` | off | ByteTrack temporal smoothing vs per-frame predict |
| `--player-hold N` | `6` | Max blind frames to hold the last player position |
| `--hz F` | `15` | Decision rate — **leave at 15**, the planner is tuned for it |
| `--lag-ticks F` | `0.25` mem / `1.0` vis | Latency extrapolation |
| `--player-lead F` | `0.45` mem / `0` vis | Player forward-prediction ticks |
| `--vel-ema F` | `0.5` | Velocity EMA smoothing (1.0 = raw) |
| `--no-frame-sync` | off | Disable 60 Hz frame-sync (memory input only) |
| `--loop` | off | Xenia: replay games back-to-back |
| `--no-start` | off | Xenia: skip menu navigation |
| `--start` | off | Hardware: blind start-button sequence first |
| `--visualize` / `--show-overlay` | off | Live annotated overlay window (see below) |
| `--simulate` | off | Don't open real devices — print output (testing) |
| `--debug` | off | Verbose per-tick output |
| `--config FILE` | — | JSON of defaults; command-line flags still win |

### Config file

Put common settings in a JSON file instead of flags. Command-line flags override
it; the file overrides only the built-in defaults.

```json
{
  "mode": "hardware",
  "device": 1,
  "port": "COM5",
  "conf": 0.35,
  "track": true
}
```

```powershell
.venv\Scripts\python -m robotron_ai --config myrig.json
```

### Live visualization (`--visualize`)

See what the bot sees, in real time. Adds a window showing the game feed with:

- **Entity boxes + labels**, colour-coded by type (threats warm, civilians green,
  electrodes yellow);
- the **player** (cyan ring);
- **threat vectors** — thin red lines to the nearest few non-civilians;
- the chosen **move** (green arrow) and **fire** (orange arrow) directions;
- a **HUD**: wave / score / lives / deaths / current action.

```powershell
# Emulator, memory bot, with the overlay:
.venv\Scripts\python -m robotron_ai --mode xenia --visualize --loop

# Real hardware, watch the YOLO detections live:
.venv\Scripts\python -m robotron_ai --mode hardware --device 0 --port COM3 --visualize
```

Works in both modes. On the memory path it grabs the Xenia window as the backdrop
and draws boxes from guest RAM; on the vision path it draws the YOLO detections on
the exact frame the detector ran on. Rendering happens *after* each action, so it
never delays the bot. Press **q** or close the window to hide it — the bot keeps
playing. (Needs a desktop session; harmless to leave off for headless runs.)

### Dry run (no hardware, no emulator)

```powershell
.venv\Scripts\python -m robotron_ai --mode xenia --simulate --no-start
```

`--simulate` makes the controllers print their output instead of driving a real
device — handy to sanity-check wiring and the decision loop.

---

## Serial protocol (real hardware)

The controller device receives **one byte per update**:

```
  bit  7 6 5 4 | 3 2 1 0
       └─move──┘ └─fire──┘        each nibble = bitmask  UP=1 DOWN=2 RIGHT=4 LEFT=8
```

`byte = (move_mask << 4) | fire_mask`. Menu buttons are their own bytes:
`START = 0xC0`, `BACK = 0x30`, `A = 0x02`. Direction indices 1..8 are compass
N, NE, E, SE, S, SW, W, NW — the exact order the FSM emits, so no remapping is
needed on either side.

---

## Layout

```
robotron_ai/
  cli.py          entry point — config, mode presets, wiring   (python -m robotron_ai)
  brain.py        ChampionBrain: velocity + latency + FSM + clearance planner
  perception.py   MemoryPerception, VisionPerception, frame sources (window / HDMI)
  control.py      Controller ABC, VgamepadController, SerialController
  harness.py      memory game loop (Xenia) + vision game loop (hardware) + menu nav
  visualize.py    live annotated overlay window (--visualize)
  coords.py       coordinate transforms (game <-> screen px <-> planner px)
  weights/        bundled trained YOLO detector (robotron.pt)
  engine/         the proven, tuned libraries (readers, FSM, planner) — not rewritten
```

The `engine/` modules are the byte-for-byte MAME-parity readers, the evolved
FSM, and the clearance planner. The orchestration layer wraps them; it never
reimplements their logic.

---

## Troubleshooting

- **`could not find process xenia_canary.exe`** — Xenia isn't running, or you're
  using `--input memory` without the emulator. Start Xenia (memory path needs the
  JIT-hook build), or use `--input yolo`.
- **`[vgamepad] unavailable`** — install the ViGEmBus driver; the bot falls back
  to printing output so you can still test.
- **`[serial] cannot open COMx`** — wrong port or device not plugged in; check
  Device Manager. The bot simulates output so you can verify decisions.
- **HDMI device won't open** — try a different `--device` index (0, 1, 2…). Some
  cards expose multiple nodes.
- **Vision misses enemies** — lower `--conf`, or retrain the detector on your own
  capture (the per-class gates already favour recall on the deadly classes).
