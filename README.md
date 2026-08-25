# robotron_ai

A configurable **Robotron 2084 AI player**. One decision core (an evolved
finite-state machine + a minimal-deviation clearance planner that reached
**wave 158** on memory input and **wave 55** on pure vision) driven by
swappable **input** and **output**, so the *same* bot plays on the **Xenia
emulator** and on **real Xbox 360 hardware**.

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

## 🎮 Super simple: run it on your Xbox, step by step

No experience needed. Follow these in order.

**What you need before starting**
1. An **Xbox 360** with *Robotron: 2084* (the XBLA version), plugged into a TV.
2. An **HDMI capture card** (a little USB box; a cheap ~$15 one works). It
   splits or receives the Xbox's HDMI picture and shows up on the computer
   like a webcam.
3. The **serial controller box** (the custom device that plugs into a wired
   Xbox controller and takes commands over USB). Note which COM port Windows
   gives it (Device Manager → Ports → e.g. "COM3").
4. A **Windows PC** with an NVIDIA graphics card (recommended) and
   [Python 3.10 or newer](https://www.python.org/downloads/) installed —
   during install, tick the box that says **"Add Python to PATH."**

**Step 1 — Download the code**
- Go to the GitHub page for this project.
- Click the green **`<> Code`** button → **Download ZIP**.
- Right-click the downloaded file → **Extract All…** → put it somewhere easy,
  like `C:\robotron`.

**Step 2 — Install (one time only)**
- Open the extracted folder, click in the address bar of the window, type
  `cmd`, and press Enter. A black window opens in the right place.
- Copy-paste these two lines, pressing Enter after each. The second one
  downloads a few GB and takes a while — that's normal:

```bash
python -m venv .venv
.venv\Scripts\pip install -r robotron_ai\requirements.txt
```

**Step 3 — Plug things in**
- HDMI capture card → PC (and Xbox video going into it).
- Serial controller box → PC, and its controller plug → Xbox player-1 port.
- Turn on the Xbox and start Robotron so you can see the game on screen.

**Step 4 — Let the bot play**
- In that same black window, paste:

```bash
.venv\Scripts\python -m robotron_ai --mode hardware --device 0 --port COM3
```

- Change `COM3` to your serial port from Device Manager. If you get a black
  or wrong picture, try `--device 1` or `--device 2` (some capture cards show
  up more than once).
- The bot starts the game itself (it presses A, which is safe on every
  screen). You can also just start a game yourself — extra A presses do
  nothing during play.
- **If a message about CPU inference appears** (no CUDA): install the GPU
  version of PyTorch — run BOTH commands, in order (the uninstall matters;
  pip won't replace the CPU version otherwise):
  `.venv\Scripts\pip uninstall torch torchvision torchaudio`
  `.venv\Scripts\pip install torch torchvision --index-url https://download.pytorch.org/whl/cu130`
  (Don't use `--imgsz 640` — it makes the bot misread the player as a
  civilian and freeze.)

**What you should expect**
- The first start takes ~30-60 seconds (the vision model warms up). Then the
  player will start dodging, shooting, and rescuing the family on its own,
  15 decisions per second.
- It plays *well* — typically somewhere in **waves 15-25**, sometimes much
  deeper (its record is wave 55). It will still die eventually; that's
  Robotron.
- Want to watch what it's "seeing"? Add `--visualize` to the command — a
  window opens showing every enemy it detects and the direction it chose.
- To stop it: click the black window and press **Ctrl+C**.

**If something goes wrong**
| Problem | Fix |
|---|---|
| `python` is not recognized | Reinstall Python, tick **Add to PATH** |
| Picture is black / a desktop | Wrong capture device — try `--device 1`, `2`… |
| `cannot open COM3` | Wrong port — check Device Manager → Ports |
| Bot doesn't move | Is the game actually running? Is the controller box plugged into port 1? Try `--visualize` to see if it sees the player |
| It's slow / stuttery | Close other heavy programs; a laptop without an NVIDIA GPU will struggle |

**One more thing — send back the report.** While it plays, the bot writes a
diagnostics folder at `robotron_ai\logs\hardware_report\` (a small
`report.json` plus 2-3 screenshots). When you're done playing, **zip that
folder and send it back** — it automatically answers all the calibration
questions (control latency, capture quality, timing) so the next version can
be tuned for your exact setup. You don't need to read or understand it.

That's the whole thing. Everything below is detail for people who want to
tinker.

---

## Two ways to run it

| | **Xenia (emulator)** | **Real Xbox 360 hardware** |
|---|---|---|
| Input | `memory` (best) or `yolo` | `yolo` (HDMI capture — only option) |
| Output | `vgamepad` (virtual pad) | `serial` (custom controller device) |
| Game state | read from guest RAM | none — vision only |
| Use case | development, best scores | play the real console |

Best results on record: **memory** input W158 / S4,468,300; **vision** input
W55 with repeated full clears (W40+ = every unique wave pattern beaten; the
XBLA wave loop repeats 20-40 after that).

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
  slow to start, then runs at full rate.
- A trained detector ships at `robotron_ai/weights/robotron.pt` (the production
  `yolo6` model) — no training needed to use the vision path.

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

See the **super simple** section above. Short version:

```powershell
# HDMI capture on device 0, serial controller on COM3
.venv\Scripts\python -m robotron_ai --mode hardware --device 0 --port COM3
```

There is no memory access on real hardware, so the bot runs purely from vision:
it plans and acts whenever it can see the player, and goes neutral when it
can't. Start the game yourself, or pass `--start` to have it blindly press
Start + A a few times first. Stop with `Ctrl+C`.

Score, wave, deaths and game-over are still tracked — read **off the video
feed** by HUD OCR (template matching against the game's own bitmap fonts,
auto-harvested on the emulator with memory ground truth and shipped at
`weights/hud_font.npz`). Validated against guest RAM live: wave 93% coverage /
99% accuracy, score ~90% per-frame with monotonic guards on top. You get live
wave lines in the console and a per-wave JSONL (`--hud-log`) in the same
shape the emulator harness writes, so `robotron/ab_yolo.py --log <file>` can
analyse and A/B hardware runs exactly like emulator runs. `--no-hud`
disables it. Deaths are counted from the lives-icon row dropping (nothing
else — a detector losing sight of the player is never treated as a death).
Known limit: the lives-icon row caps at 8 icons, so deaths from a 9+ life
bank don't register — rare outside marathon emulator runs.

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
| `--conf F` | `0.30` | YOLO confidence floor (floors the per-class gates) |
| `--track` | off | ByteTrack temporal smoothing vs per-frame predict |
| `--player-hold N` | `6` | Max blind frames to hold the last player position |
| `--hz F` | `15` | Decision rate — **leave at 15**; if the host can't hold it, the planner auto-rescales its kinematics to the measured cadence |
| `--lag-ticks F` | `0.25` mem / `0.3` vis | Latency extrapolation (vision value is the live-calibrated measurement) |
| `--player-lead F` | `0.45` mem / `1.5` vis | Player forward-prediction ticks (vision 1.5 validated: maxW 14.6→18.0, p=0.003) |
| `--vel-ema F` | `0.5` | Velocity EMA smoothing (1.0 = raw) |
| `--no-frame-sync` | off | Disable 60 Hz frame-sync (memory input only) |
| `--loop` | off | Xenia: replay games back-to-back |
| `--no-start` | off | Xenia: skip menu navigation |
| `--start` | off | Hardware: blind start-button sequence first (rarely needed — menu nav is automatic) |
| `--menu-start` | off | Let menu nav press Start (default A-only: real-console Start backs out of menus) |
| `--imgsz N` | model native (1280) | Inference size; `640` = ~3-4x faster on CPU rigs |
| `--visualize-plain` | off | With `--visualize`: raw feed, no boxes/arrows |
| `--no-hud` | off | Hardware: disable HUD OCR score/wave/death tracking |
| `--hud-log PATH` | `logs/hud_waves.jsonl` | Hardware: per-wave JSONL from HUD OCR (ab_yolo-compatible) |
| `--visualize` / `--show-overlay` | off | Live annotated overlay window (see below) |
| `--simulate` | off | Don't open real devices — print output (testing) |
| `--debug` | off | Verbose per-tick output |
| `--config FILE` | — | JSON of defaults; command-line flags still win |

Vision-path behaviour applied automatically (each individually A/B-validated;
override with the matching env var only if you're experimenting):
- **Fire-at-the-binding-threat** (`VSEARCH_FIREPLAN`): shoot the launcher
  that's boxing you in — close-fired sparks arrive faster than any dodge can
  react, so killing the source is the only defence. The single biggest vision
  win (deaths/wave 1.20 vs 1.38, max wave 21.9 vs 17.5).
- **Widened planner margins** (`VSEARCH_CLEAR_DANGER/MARGIN` 21/12): absorbs
  vision tracking noise; memory keeps 18/10.
- **Projectile track-and-coast**: fast projectiles are tracked and coasted
  through detector misses. (Coasting *all* classes was tried and measured
  worse — phantom threats make the bot timid and starve the rescue economy.)
- **Deadline tick clock**: the loop holds a true 15 Hz; if your machine
  can't, it rescales the planner's per-step kinematics to the real cadence
  instead of silently mispredicting (this is what makes slower hardware rigs
  behave correctly).

### Config file

Put common settings in a JSON file instead of flags. Command-line flags override
it; the file overrides only the built-in defaults.

```json
{
  "mode": "hardware",
  "device": 1,
  "port": "COM5",
  "conf": 0.30,
  "visualize": true
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
  harness.py      TickClock + memory game loop (Xenia) + vision loop (hardware) + menu nav
  visualize.py    live annotated overlay window (--visualize)
  hud_ocr.py      HUD OCR: score/wave/lives off the video feed + bookkeeping
  coords.py       coordinate transforms (game <-> screen px <-> planner px)
  weights/        bundled YOLO detector (robotron.pt — yolo6) + HUD font (hud_font.npz)
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
- **Vision misses enemies** — the per-class gates already favour recall on the
  deadly classes; effective recall near the player measures 0.96-0.98 with
  tracking. If your capture looks different from Xenia output (odd scaler,
  cropping), fix the capture first — retraining is almost never the answer.
- **`[tick] OVERRUN` / cadence warnings** — the machine can't hold 15 Hz. The
  planner auto-rescales so play stays correct, but a GPU-less laptop will be
  noticeably weaker.
