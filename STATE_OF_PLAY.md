# Robotron 2084 bot — state of play (2026-09-06)

A single-page orientation for anyone (or any fresh context) picking this up.
Facts only; every number below comes from a logged run. Deeper detail lives in
the files listed at the end.

## 1. Goal and constraint

Play Robotron 2084 (Xbox 360 XBLA) as deep as possible **from video only** on a
real console operated remotely by Eric: an HDMI capture card feeds a YOLO
detector, a planner decides, a serial adapter drives the pad. Target: wave 100.
The console rig is available only in rounds (Eric sends telemetry back). All
development happens on two test beds:

- **Xenia** (Xbox emulator on the dev PC): the real game code, played through the
  same vision pipeline via window capture and a virtual pad ("hardware-sim").
  ~1 game / 10 min. The only place the late game can be studied.
- **MAME** (arcade Robotron, WSL): 16 instances, ~250x realtime, memory-perfect
  input degraded by a calibrated defect model ("cal_d10": actuation 4 frames,
  1-frame vision age, 10% dropouts, 2 px noise) that reproduces Xenia's vision
  numbers in waves 5-25. 144 games in 16 min. Its late band (W25+) does NOT
  resemble Xenia's and must not be used for late-game questions.

## 2. Architecture (production package `robotron_ai/`)

capture (`perception.py`: `XeniaWindowSource` / `HdmiSource`) -> YOLO detector
(14 classes incl. Player) -> optional `ThreadedVisionPerception` (background
eye) -> `harness.py` decision loop (TickClock 15 Hz, or eye-synchronised) ->
`engine/robotron_fsm.py` (rule FSM with evolved constants: flee radii, fire
tiers, rescue) + `engine/clearance_planner.py` (multi-step clearance search
that overrides the FSM heading when it is in danger, minimal deviation) ->
`control.py` (vgamepad on the sim, serial on the console). Bookkeeping from
video: `hud_ocr.py` (score/wave OCR, lives = icon count; deaths = lives drop).
Telemetry: `telemetry.py` -> `logs/hardware_report/`.

The dev copies used for experiments are `robotron/brain_yolo.py` (vision bot),
`robotron/brain_champion.py` (memory-input bot), `robotron/robotron_fsm.py`,
`robotron/clearance_planner.py`; `robotron/ab_yolo.py` runs interleaved A/Bs on
Xenia; `robotron/mame_lab.py` + `mame_run.sh` + `native_stats.py` run the MAME
proxy. The production and dev FSM copies are re-synced after each experiment (dev gains opt-in knobs first; a fresh-context review on 2026-09-06 caught one lag). The dev clearance planner additionally carries no-op-by-default experiment knobs (ACT_LAG, STICKY, WALL_W, MAXCLR, PROJ_W) that the production planner does not.

## 3. How we measure

**NET lives per wave = score/25,000 − deaths/wave**, over waves 5-25, unit of
analysis = game, interleaved arms, bootstrap CI by game. Positive NET means the
bot banks lives faster than it loses them. Resolution: Xenia 20 games/arm
≈ ±0.08; MAME 144 games ≈ ±0.04, 576 games ≈ ±0.02. **Rule learned the hard
way (2026-09-05): a 144-game screen that shows +0.03 is not a result; confirm
at 576 before believing it** (the kite sweep's +0.036 regressed to −0.011).

Reference points: memory-input champion on Xenia rides W100-158 at NET ≈ +0.07.
Vision bot before this week: NET ≈ −0.09, mean max wave 13.5, best W26.

## 4. Current shipping configuration (origin/main 60040dd, 2026-09-04)

- **Eye-synchronised decisions** (`--eye-sync 55`, default on): the loop waits
  for the newest frame's detections and acts at once instead of ticking on a
  fixed clock. Measured vision age 0.82 -> 0.51 ticks (55 -> 34 ms) on Xenia.
- **Hold-action 4** (default on): on a blind tick repeat the last stick command
  for up to 4 ticks instead of going neutral.
- **Start ladder** presses A at least 3 times before trusting the in-game sense
  (the attract screen fools the sense: a walking hulk reads as the player).
- Everything else as in round 12 (auto-lead = act + 0.5 ticks, capture flags,
  HUD bookkeeping thresholds).

Evidence: 2x2 factorial on Xenia, 20 games/arm, W5-25:

| arm | deaths/wave | score/wave | NET | games reaching W26 cap |
|---|---|---|---|---|
| base | 1.198 | 27.8k | −0.086 | 6/20 |
| hold-action | 1.179 | 28.2k | −0.051 | 9/20 |
| eye-sync | 1.096 | 27.5k | +0.006 | 10/20 |
| **eye-sync + hold** | **1.085** | **29.3k** | **+0.086** | **14/20** |

Eye-sync main effect p=0.005 (0.001 combined). Replicated direction in a second
A/B (16/arm, d/w 1.10 vs 1.16). Production smoke on the hardware-sim: W19,
bookkeeping flawless, 15 Hz, stale frames 3.5%.

**Uncapped depth, shipping config, 50 Xenia games**: median W28, mean 29.5,
11/26 past W30 in the first batch, records W42, W50 (1.38M), later W55 (1.49M,
on a kite arm). Before this week the all-time vision best was W26.

**Where the lives go now** (50-game uncapped batch; the factorial's +0.086 was a
20-game capped run): W5-25 NET ≈ +0.05; **W25-40 deaths/wave 1.36-1.50,
NET ≈ −0.24**; the bank runs out near W35. Deaths cluster 8-20 s into a wave
(median 16 s), 0% at wave start. Late deaths have the same structure as early
ones (56% within 50 px of a wall, 35% boxed-in with <=2 free headings, same
killer mix: enforcer bullets, cruise missiles, tank shells, grunts) — same
mistakes at a higher rate, no distinct late failure mode.

## 5. Experiment ledger (what was tried, verdict, where)

Latency / loop

| lever | verdict | evidence |
|---|---|---|
| 30 Hz decision loop | dead | Xenia maxW 8.5 vs 20.4 p<.001; MAME NET −0.40 |
| eye-sync | **ship** | above |
| hold-action | ship with eye-sync | flat alone, best arm combined |
| TensorRT engine (detector 21.5 -> 9.2 ms) | no measurable effect (below the resolution of 16/arm + 12/arm); optional | d/w unchanged in both A/Bs |
| vision-age cost curve | NET by age: 0f +0.22, 1f +0.20, 2f +0.11, 3f +0.03, 4f −0.06 (non-linear; ~0.02/frame near zero, ~0.09/frame at 1-2 frames) | MAME LAB_AGE_FRAMES 0..4 |
| lead rule act+0.5 (was act−0.5) | ship (round 12) | MAME 40/arm; 1.0-1.5 flat optimum |

Planner knobs on the MAME proxy (all flat or negative, ≥144 games/arm)

| knob | NET vs base |
|---|---|
| actuation-aware dodge (3 variants), projectile weight, sticky heading, H4/H8, least-bad, EMA, extrapolation lag | flat |
| wall repulsion (VSEARCH_WALL_W), max-clearance (MAXCLR) | significantly negative (economy) |
| CLEAR_MARGIN 14 | −0.099* |
| FSM_THREAT_FIELD | −0.043* |
| FSM_EDGE_DEFLECT | −0.015 ns |
| FSM_SPAWNER_FIRE, radius 250, BRAIN_RESCUE_MULT 1.5 | flat / negative (72/arm) |
| evolved-constant ES, 48 games/candidate, 15 generations | random walk; stopped |
| **KITE mode 1** (circle at idle) | −0.035* (economy loss, no death change) |
| **KITE mode 2** (circle by default, clearance search dodges) | 144: d/w −0.04 but −0.026 NET; tuned (grab 300, ahead 0.9) +0.036 at 144 -> **−0.011 CI[−0.031,+0.010] at 576**; Xenia 12/arm +0.016 ns. **Null.** |
| KITE mode 3 (orbit the enemy centroid) | −0.074* |
| ALWAYS_FIRE (shoot nearest killable when fire idle) | d/w −0.026 (real, small), score −1.4%, NET +0.011 CI[−0.006,+0.029]. Parked. |

Bookkeeping / capture (all shipped, rounds 6-12): color-agnostic HUD OCR,
multi-variant wave templates (Eric's '8'), deaths = lives-drop only, no border
watchdog, glyph-count anchoring, capture probe (dshow MJPG 1080p), stale-frame
metric. Bookkeeping on Eric's rig is complete ("all waves correct, no false
deaths").

Dead ends not to reopen: start games at W24 by memory poke (0x82388E20 is a
display mirror; slot-1 "wave" word is a frame counter); wave-start opening
moves (0% spawn-in deaths); MAME late band as a proxy.

## 5b. 2026-09-06: the age finding and the entity-lead fix (SHIPPED as default)

Exact-state diagnostic (memory entities fed through the unchanged vision loop):
fresh exact state rides W100+ (censored at 16.6M points); exact state aged one
decision tick plays like vision (deaths/wave 1.15 vs 1.14); aging only the
player costs nothing, aging only the entities costs everything. The ~34 ms of
age is upstream of our capture (emulator presentation; the console will be the
same): WGC capture and TensorRT did not reduce the measured lag. So age is
compensated, not removed: the planner extrapolated entities by only 0.2 tick
against a measured 0.55-tick lag, i.e. it acted on positions ~1/3 tick behind
the truth. A/B on real vision (8 games/arm, W5-25):

| entity lead (ticks) | deaths/wave | score/wave | NET | mean max wave |
|---|---|---|---|---|
| 0.2 (old default) | 1.106 | 27.9k | +0.01 | 25.4 |
| **0.7 (new default)** | **1.024** | **29.5k** | **+0.155** | **38.1 (p=0.001)** |
| 1.2 | 1.077 | 28.8k | +0.08 | 31.1 |

Every 0.7 game reached W28+; record W58. Bracketing run (8/arm): lead 0.5 ->
NET +0.12, mean max wave 32.4; 0.7 -> +0.20, 34.5 (pooled 16 games: +0.175,
36.3); 0.9 -> +0.11, 26.6. The optimum is a plateau from 0.5 to 0.9, so the
setting is robust to the console's slightly different lag. Production
`--lag-ticks` vision default 0.3 -> 0.7; dev `ROBOTRON_YOLO_LAG_TICKS` 0.2 ->
0.7. Late band (W25-40) is still ~1.4 deaths/wave: the remaining frontier.
Closed the same day: real-STAY fix (+0.004), model-based threat advance
(−0.026), capture path changes (no lag reduction).

## 6. Open questions / next levers, ranked

1. **Hardware input freshness (Eric's side).** His rig's *actuation* is faster
   than the emulator's (act = 1.0 tick vs 2.0), but its *capture* is worse
   (stale/duplicate frames ~36%). Vision age is the one lever with a measured
   curve, so eye-sync should help there; round 13 build is ready. The curve is
   a MAME proxy finding, not a validated console forecast.
2. **A planner that couples movement and aiming** the way a human circuit
   does. Circling alone did nothing because our fire logic is independent of
   where we walk. This is a design project, not a knob.
3. Late-band (W25-40) economy: only measurable on Xenia (~1 game/12 min, ~10
   band waves per game that reaches it). Any candidate needs ~40 games/arm.
4. Running now (2026-09-05 night): MAME evolver with 288-game candidates
   (`~/mame_logs/evolve288/`); Xenia depth batch of the shipping config.

## 6b. Known quirk under test (found by fresh-context review, 2026-09-06)

All bots (production `brain.py`, dev `brain_champion.py`, `mame_lab.py`) map
the FSM's STAY output to direction 1 = UP: the bot never stands still; every
"hold position" decision walks toward the top wall. Consistent across the
proxy and Xenia, so the proxy is still valid, but it is a plausible contributor
to the wall-death signature. A STAY-as-neutral variant is being tested.

## 7. Operating rules that cost us time to learn

- Never run emulator bots while the user is at the machine (the virtual pad
  hijacks the mouse). Idle detection is only valid with no bot running; a
  foreground-window guard kills bots if Xenia loses focus.
- Xenia and 16 MAME instances together hang MAME sockets (games end at W2/3
  with <100 steps); hung games contribute nothing to band stats.
- `pkill -f` patterns that match the invoking shell self-kill it; anchor on
  argv0. WSL background jobs need `setsid nohup ... < /dev/null & disown`.
- `cal act=` in the dev bot climbs to 2.0 as it saturates; compare like sample
  counts. Root repo `C:\Users\strid\code` has a stray first commit to delete.

## 8. Where the detail is

- Round-by-round history and every number: memory file
  `project_yolo_pipeline_rework.md` (Claude's project memory).
- Scripts and flags: `robotron/SCRIPTS.md`; production flags: `README.md`.
- Latency findings: `robotron/XENIA_LATENCY_CHECKLIST.md`.
- Game internals: `XENIA_MEMORY_MAP.md`, `MAME_ENEMY_MODEL.md`,
  `ROBOTRON_DISASM_REFERENCE.md`, `robotron/SPRITE_DATA.md`.
- A/B logs: `robotron/logs/ab_*.log`, `uncapped.log`; MAME: `~/mame_logs/`.
