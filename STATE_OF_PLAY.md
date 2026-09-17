# Robotron 2084 bot — state of play (updated 2026-09-15)

A single-page orientation for anyone (or any fresh context) picking this up.
Facts only; every number below comes from a logged run. The complete history of
every attempt since March 2026, written for non-engineers, is
[WHAT_WE_TRIED.md](WHAT_WE_TRIED.md). This file is self-contained: it no longer
depends on Claude's project-memory notes (their content is folded into the two
docs; see section 8).

## 0a. 2026-09-14/15: fire alternation — waves 117, 90 and 198 on real vision

**The mechanism (from the ROM).** Robotron's fire task (robomame.asm
`$31B9`-`$3235`) fires a laser 2 frames after the fire direction is set or
changed and every 8 frames while it is held; a change clears the count. At our
4-frame decision tick, alternating between two live targets every tick fires
every 4 frames: double laser throughput, with the primary target still hit
every 8 frames. The XBLA game runs the same 6809 bytes, so it transfers.
Implemented as `VSEARCH_FIRE_ALT` in both planners; **default ON for the
vision path since 2026-09-15 (radius 400 px)**, off for memory input,
`--fire-alt` / `--no-fire-alt` on the CLI, env pin wins for A/B purity.

**The confirmation ladder, all in one night** (full record with per-game
numbers in [docs/FIRE_ALT_EXPERIMENT.md](docs/FIRE_ALT_EXPERIMENT.md)):

| stage | games/arm | deaths/wave base -> fire_alt | delta (95% CI) |
|---|---:|---|---|
| MAME proxy screen (cal_d10) | ~131 | 1.127 -> 0.844 | NET +0.309 [+0.266, +0.353] |
| MAME fresh-seed, fresh-process confirmation (LAB_LAG 0.7) | 576 | 1.097 -> 0.828 | NET +0.311 [+0.289, +0.333] |
| radius sweep 100 / 160 / 250 / 400 / unlimited | 144 | — | NET +0.20 / +0.31 / +0.34 / +0.38 / +0.37 |
| Xenia exact state, W25-40, W40 cap | 8 | 1.217 -> 0.758 | +0.46, p < 0.001 |
| Xenia exact state, W5-25 | 8 | 0.780 -> 0.429 | +0.35, p < 0.001 |
| **Xenia real vision, shipping config, W5-25** | 12 | 1.063 -> 0.806 | +0.257 [+0.132, +0.387] |
| **Xenia real vision, W25-40** | 12 | 1.328 -> 1.104 | +0.225 [+0.094, +0.396] |
| Xenia real vision, uncapped, R=400 | 3 | max wave 31 / 16 / 31 vs **117 / 90 / 198** | — |

Income and rescues per wave are unchanged at every stage; the gain is faster
killing. In the real-vision 12/arm run ten of twelve fire_alt games reached the
W40 cap against one of twelve baseline games. Uncapped, the three fire_alt
games reached W117 (3.14M), W90 (2.47M) and **W198 (5.42M, 193 deaths)**,
running 1.02-1.24 deaths/wave above W40 against ~1.1 lives bought per wave:
break-even to slightly positive, the regime the memory-input champion rides to
W100-158. The vision bot's previous record was W60; W198 is the deepest any
bot in this project has reached on any input.

Everything else screened in the same queue lost: discounted 10-step horizon
−0.137, act-lag + age-advance −0.109, and the re-screens of max-clearance
−0.154 and wall repulsion −0.208 on the corrected proxy (closing the
section-5 caveat).

**What this changes in the picture.** Section 6's verdict ("at the ceiling
for this architecture at this latency") assumed the laser rate was fixed. It
was not: the bot had been throwing away half its shots by holding the stick.
The age analysis still stands, but the late band is no longer a bleed. Next:
more uncapped real-vision games for a depth distribution, the console
(round 15 ships with this on), and a 30 Hz fire-stick dither in the
controller layer (a change every 2 frames would fire at the ROM's minimum
interval; the 4-laser cap will bind sooner, so it needs its own screen).

**Operational gotchas from the night:** the Xenia focus guard aborts on a
locked desktop; PowerShell 5.1's `Get-Date -UFormat %s` is seven hours early
(never use it for `--since`); a custom `ROBOTRON_WAVE_LOG` hides the W40 cap
from `ab_yolo`'s emulator-restart check; MAME `.venv` is a dead symlink, use
`.venv-collision`.

## 0. 2026-09-14: the weekend screens, console round 14, and the console instrument

**The weekend (GPT Astra, Sept 12-14, unattended Xenia).** Twelve isolated
opt-in changes were screened at 8-12 games/arm on production Xenia, W25 cap,
oracle-audited NET (timing normalisation, HUD-driven death/wave tracker resets,
fresh-player, neutral-lead, player-bounds, unique velocity matching, static
electrodes, closest-pair coasting, spark birth velocity, player command
history, confirmed-only ghosts). None produced a confirmed gain. The strongest,
confirmed-only projectile ghosts (a coasted track needs a second sighting
before it is kept), read NET +0.186 CI [+0.031, +0.335] at 12/arm and
**−0.026 CI [−0.185, +0.130] on an independent 9/arm replication**; not
promoted. Two MAME screens (two-step turning paths, collision sub-steps) also
lost. Full record: [docs/archive/weekend_20260912/](docs/archive/weekend_20260912/)
(reports) and `logs/weekend_20260912/` in the main checkout (artifacts).
Reviewed 2026-09-15: the twelve opt-in knobs and the weekend automation were
not merged (all null; preserved verbatim on branch `weekend-20260912-raw`);
the fresh-process MAME runner (`tools/run_collision_mame_fresh.py`) was kept
and is what the fire-alternation confirmation ran on.

**Console round 15 (Eric, Sept 15, ten games, fire alternation on, trace on) —
the diagnosis.** Waves 20, 16, 9, 21, 13, 17, 20, 18, 19, 22 (mean 17.5 vs 12
in round 14). The trace's reversal test answers the question section 0 was
written to ask: on the console a move reversal shows on screen **3 ticks
later in 61% of cases and 4 in 26%**, against 2 ticks in 92% on the
emulator. One to two ticks (70-130 ms) of extra loop latency. The controller
box (Arduino Uno, 9600 baud, no debounce or delay, optoisolators as button
presses) is not it; the candidates are the two X-Arcade adapters between the
optos and the console, and the MJPG capture path; round 16's YUY2 session
splits them. Ruled
out by the same trace: player speed (ratio 1.03, controller and scale
correct), eye stalls (sample age 1-3 ms, no gaps), blindness (24%, the same
as the emulator's 19-21%). Consequences visible in the data: the bot flips
heading every tick under the latency (an electrode death shows E, SW, E, SW,
SW, SE in the last six commands), and 32% of deaths have no visible killer
at the collision tick (18% on the emulator), most with a coasted projectile
track nearby. Per band the console runs ~1.5x the emulator's alternation
death rate (W5-9 1.04 vs 0.64, W10-16 1.16 vs 0.79, W17-22 1.33 vs 0.88) at
10-15% lower income. The legacy actuation estimator read 1.0 tick on the
console (a 45-degree turn counts as an instant response), so auto-lead had
set the player lead to 1.5 where the reversal rule gives 2.5. Fixed
2026-09-16: `ReversalEstimator` in telemetry (same definition as the offline
analysis; reproduces the console's 3 and the emulator's 2), auto-lead =
reversal − 0.5, persisted per rig in `rig_calibration.json`; the exit hang
after `--games N` (a daemon inference thread at interpreter teardown) is
fixed; the death-window cap is 120. Round 16 runs with `--player-lead 2.5`
pinned, and optionally a second session with `--capture-fourcc YUY2` to test
whether the compressed capture path carries the delay.

**Console round 16 (Eric, Sept 16, two ten-game sessions, player lead pinned
2.5; second session `--capture-fourcc YUY2`).** MJPG: waves 11, 14, 28, 12,
13, 9, 9, 19, 22, 23 (mean 16.0, console record W28). YUY2: 19, 20, 13, 19,
17, 22, 9, 13, 13, 17 (mean 16.2). Deaths/wave by band vs round 15 (lead 1.5):
W5-9 1.04 -> 1.00 / 0.86, W10-16 1.16 -> 1.05 / 1.22, W17-22 1.33 -> 1.42 /
1.67: **the corrected lead changed nothing**, as the MAME latency lab found in
July (a forward prediction restores the player's position, not the lost
reaction time). Reversal latency with YUY2: +3 in 64%, +4 in 9% (MJPG 57% /
29%), same 54 unique frames/s: **the capture format is not the delay** (caveat:
OpenCV's DirectShow backend reports the converted RGB24 subtype in both logs,
so the switch itself is unverified). Unseen-killer share 30-33%, wall share
34-38%, the same as round 15. Verdict: the extra 1-2 ticks sit in the control
chain (two X-Arcade adapters) or the console's own output, and the bot cannot
compensate them. Round 17 reverts the lead to the legacy auto rule (the
reversal estimator stays as the rig diagnostic; `rig_calibration.json` is
printed, not applied), counts the final game-over death (Eric's catch: the
last life drops no icon, so every game was one death short), and proposes the
hardware test: optoisolators directly on a wired 360 pad's D-pad and A/B/X/Y
contacts, judged by the reversal count in the next trace.

**Controller chain measured in isolation (Eric, Sept 16, adapter USB into the
PC, `tools/measure_control_latency.py`, 39 trials):** press and release land
at ~19.5 or ~39.5 ms, never between, median 39 ms: the X-Arcade adapter chain
polls at 50 Hz. Against a wired pad's 4-8 ms that is ~30 ms, about half a
tick, so the adapters carry only the smaller part of the console's extra 1-2
ticks; the larger part is the console's input-to-output pipeline plus the
capture card's frame latency. The console already outputs 720p (the card is
asked for 1080p and upscales). Next test (free, a spare HDMI cable):
`tools/measure_capture_latency.py`, GPU HDMI into the card, flashes a
full-screen window and times it through the card and through a screen read
at once; the difference is the video side's cost over the emulator path,
and it compares MJPG/YUY2 and 1080p/720p on the PC in minutes. The
direct-pad wiring is second.

**Capture chain measured in isolation (Eric, Sept 16, GPU HDMI into the
Magewell, `tools/measure_capture_latency.py`, MJPG 1920x1080, 40 flips):**
screen read 4 ms, card 41 ms median (p10 36, p90 52), difference **37.5 ms**
(~2.25 frames: scan-out, one frame in card/driver, decode); the card runs a
steady 60 fps. Adapters ~30 + capture ~38 = ~68 ms, just over one tick,
matching the reversal count (3 ticks in most cases, 4 in a quarter). The
console's own pipeline is no slower than the emulator's. **The MAME proxy at
one extra tick of actuation delay (`LAB_ACT_FRAMES=8`, 144/arm, Sept 16)
reproduces the console:** baseline 1.281 d/w, mean max wave 13.0 (console
round 14: 12); fire_alt 1.152 d/w, mean max wave 19.4 (console rounds 15-16:
16-17.5; console fire_alt d/w 1.04-1.33 by band); NET +0.146 [+0.107,
+0.186] against +0.311 at the standard calibration, i.e. the console's
smaller lift too. At two extra ticks (`LAB_ACT_FRAMES=12`, 144/arm):
baseline 1.443 d/w, mean max wave 8.0; fire_alt 1.339 d/w, 11.1 waves; NET
+0.120 [+0.076, +0.164]. The console (16-17.5 waves with fire_alt) sits
between the two levels, nearer one extra tick, as the 68 ms sum predicts;
each extra tick costs ~40% of depth. So there is a console stand-in on the
desk at 12-16 games in parallel (`--calibration LAB_ACT_FRAMES=8`). Fix on the hardware: shave ~40 ms (direct pad ~30 + a capture
setting worth a frame; 1280x720 / YUY2 measurements pending).

**Console round 14 (Eric, Sept 11, five games, current shipping config):**
W9, W9, W22, W9, W11 — the same band as rounds 12-13 (W12/9/12/9/9), while
the emulator went from a W13.5 mean to ~W30 with the same code. Per wave,
with the same HUD bookkeeping on both rigs (HUD deaths undercount true deaths
by ~12%; the emulator column is 135 weekend baseline games):

| wave | emulator deaths/wave | console deaths/wave | emulator score/wave | console score/wave |
|---|---|---|---|---|
| 1 | 0.00 | 0.00 | 4.5k | 4.5k |
| 2 | 0.04 | 0.20 | 7.4k | 5.3k |
| 3 | 0.07 | 0.40 | 17.9k | 17.7k |
| 4 | 0.25 | 0.60 | 17.6k | 19.2k |
| 5 | 0.37 | 0.60 | 45.5k | 46.1k |
| 6 | 0.59 | 0.60 | 22.1k | 23.3k |
| 7 | 0.99 | 0.80 | 26.1k | 29.1k |
| 8 | 0.76 | 1.60 | 22.2k | 21.7k |
| **W1-9** | **0.50** | **0.73** | 21k | 21k |

Same income, ~1.5x the HUD deaths (true deaths from lives bought: three of
the five console games spent 10 lives by W9, ~1.1/wave, against ~0.6 on the
emulator). The excess starts in waves 2-5, which the emulator barely dies in.

What the summary report rules out (console vs the Sept 7 emulator
hardware-sim): arena geometry (border at rows 95-630 / cols 267-1022 in both
captures; the odd player-bounds figure is phantom detections on non-game
screens), cadence (16.2 Hz eye-synced vs 15.0, planner rescaled x0.91),
freshness (stale frames 4.7% vs 2.3%), player visibility (77% vs 81%), HUD
coverage (91% vs 94%), the detector on his frames (clean boxes at the same
confidences), and the emulator's game speed (player 147 px/s vs the 142
calibrated, so Xenia is not running slow). Left unexplained: the console's
command-to-response estimate reads a 1.0-tick median with a 3.0-tick p90,
against a rock-stable 2.0 on the emulator, and the estimator is too coarse
to say what that means. **Nothing the console has ever sent back can say
what kills it.** Fourteen rounds of summaries cannot answer where the player
was, what was next to it, whether the detector saw the killer, or how long a
command takes to show on screen.

**Shipped in this commit: the console instrument** (`trace.py`,
`trace_report.py`, on by default in hardware mode, README "Decision trace and
death windows"). Every decision tick is recorded (player, entities, coasted
projectile tracks, command, blind/held, HUD state), and the 4.5 s of frames
before each HUD death report plus 1 s after are saved as JPEGs — the
collision is ~2.3 s before the report (the death-animation freeze, the blank,
the re-form, then the icons update). `python -m robotron_ai.trace_report
<folder>` turns a returned folder into the numbers below. The same tool run
on 112 weekend baseline emulator games (838k ticks, 2,118 located deaths)
gives the reference the console must be compared against:

| trace_report metric | emulator reference |
|---|---|
| blind ticks | 19% |
| player speed along a held axis command | 147 px/s x, 141 y (calibrated 142/138) |
| 180-degree reversal shows on screen after | +2 ticks in 92% of reversals |
| deaths within 50 px of a wall | 52% |
| killer UNSEEN (nothing lethal within 45 px at the collision tick) | 18% |
| killers | spark 31%, tank shell 14.5%, grunt 11%, cruise missile 10.5%, hulk 6%, spheroid 3%, electrode 1.5% |
| median threats within 60 px at the collision | 1 |
| HUD death report after the collision | 2.29 s median (p90 2.4) |
| HUD deaths / lives the score bought | 0.88 |

Round 15 is therefore: same shipping config, Eric plays five or more games,
sends the folder back, and the first three lines of the report decide the
direction — an UNSEEN share well above 18% is the detector on his capture
chain (retrain on console frames); a reversal latency above +2 or a wide
spread is actuation/age in the serial pad or the card (measure, then lead
constants or hardware); a speed ratio off 1.0 is the controller or scale.
Only then is a console-specific policy change worth a screen.

**Eric's round-14 questions, against the ledger.**
- *Endgame ordering (spawners before the last civilians; keep one grunt alive
  until the family is collected):* not tested as such; it is a new, testable
  idea. Neighbours: rescue-seek and the endgame hunt ship; spawners-first
  lost six times; harder civilian pursuit lost three times; the late-band
  rescue economy is at the exact-state cap (section 5c). Bounded upside, and
  the console's losses are in waves 2-8, so it queues behind the diagnosis.
- *Shooting toward the civilian it is walking to:* real. When nothing is in
  fire range the FSM emits "no fire", and the brain maps that to the move
  direction, so the bot fires along its heading. The nearest measured
  alternative, fire at the nearest killable instead (ALWAYS_FIRE, section 5),
  cut deaths/wave by 0.026 and score by 1.4%, NET +0.011: parked as too
  small to ship on the emulator. Cheap to re-screen once the console's own
  numbers exist.
- *Boxes and collision geometry:* the planner uses box centres only, with
  per-class weights (hulk 2.2, spark/tank shell 1.8, missile 1.6, enforcer
  1.3, grunt 1.0, electrode 0.8) and a 21 px danger radius / 12 px margin on
  vision; no per-object extents. Box height/width errors are cosmetic to it
  as long as the centre is unbiased (≤1.2 px on the emulator). The wide
  wave-10/20 electrodes are a genuine gap in a centre-only model; electrodes
  are 1.5% of emulator deaths. The console trace will show its own share.
- *Hulks:* a laser hit shoves a hulk (asm 471); never-fire-at-hulks lost
  on MAME (−0.69 waves); the binding-threat fire plan shoots a hulk only
  inside 90 px. Hulks are 6% of emulator deaths.
- *Lower-delay capture / another language:* the Magewell Pro Capture is
  already a low-latency PCIe card. The probe picked DirectShow MJPG for
  unique-frame rate, not latency; MJPG adds an encode/decode step and
  DirectShow buffering is invisible to the freshness metric, so a raw format
  (YUY2/NV12) may be lower-latency. The trace's reversal-latency line
  measures the whole loop directly, so round 15 says whether age is the
  console's problem before anything is bought. A language change would not
  help: the loop's own work is ~10 ms; the age lives in the console's output,
  the card, and the detector.

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

**Not in this repo.** Experiments run from two other code trees on the
development machine: the unversioned Windows dev tree `C:\Users\strid\code\robotron\`
(`brain_yolo.py` vision bot, `brain_champion.py` memory-input bot, dev copies of
`robotron_fsm.py` / `clearance_planner.py`, `ab_yolo.py` interleaved Xenia A/Bs,
`mame_lab.py` + `mame_run.sh` + `native_stats.py` for the MAME proxy) and the
MAME-side repo `~/Code/robotron-rl` in WSL (June-July MAME experiments; its
`EXPERIMENT_STATE.md` lab notebook is archived here as
[docs/archive/MAME_EXPERIMENT_LOG.md](docs/archive/MAME_EXPERIMENT_LOG.md)). File names below refer to
those trees. The production and dev FSM copies are re-synced after each
experiment (dev gains opt-in knobs first). The dev clearance planner carries
no-op-by-default experiment knobs (ACT_LAG, STICKY, WALL_W, MAXCLR, PROJ_W,
EXIT_W, SPARK_SLIDE, AGE_ADVANCE, STAY) that the production planner does not.

## 3. How we measure

**NET lives per wave = score/25,000 − deaths/wave**, over waves 5-25, unit of
analysis = game, interleaved arms, bootstrap CI by game. Positive NET means the
bot banks lives faster than it loses them. Resolution: Xenia 20 games/arm
≈ ±0.08; MAME 144 games ≈ ±0.04, 576 games ≈ ±0.02. **Rule learned the hard
way (2026-09-05): a 144-game screen that shows +0.03 is not a result; confirm
at 576 before believing it** (the kite sweep's +0.036 regressed to −0.011).
Same lesson on MAME in June: an analytic value override read +1.05 waves at
N=40 and +0.13 at N=100. Seed-pairing gives almost no variance reduction for
planner agents (same-seed per-game correlation r≈0.18, MAME 2026-07-01), so
only large-N means count. On Xenia, score/wave resolves effects ~100x faster
than deaths/wave (July 28: p=0.001 at 24/arm); never compare across sweeps
(the same config measured NET −0.06 and −0.185 in consecutive sweeps).

Reference points: memory-input champion on Xenia rides W100-158 at NET ≈ +0.07.
Vision bot before September: NET ≈ −0.09, mean max wave 13.5, best W26.

## 4. Current shipping configuration (origin/main 4e42ab2 runtime, 2026-09-07)

- **Eye-synchronised decisions** (`--eye-sync 55`, default on): the loop waits
  for the newest frame's detections and acts at once instead of ticking on a
  fixed clock. Measured vision age 0.82 -> 0.51 ticks (55 -> 34 ms) on Xenia.
- **Hold-action 4** (default on): on a blind tick repeat the last stick command
  for up to 4 ticks instead of going neutral.
- **Entity lead 0.7 ticks** (`--lag-ticks` vision default; section 5b).
- **Start ladder** presses A at least 3 times before trusting the in-game sense
  (the attract screen fools the sense: a walking hulk reads as the player);
  the attract demo is detected by its spotlight vignette and escaped; a game
  over with zero deaths is not counted; game over is emitted once per game.
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

**Uncapped depth.** Eye-sync + hold, lead 0.2 (50 Xenia games): median W28,
mean 29.5, records W42, W50 (1.38M), later W55 (1.49M, on a kite arm). With
lead 0.7 (41 games): mean 29.8, median 31, 51% ≥W30, 15% ≥W40; fresh
confirmation (20 games, all harness fixes): mean 31.4, median 30, 50% ≥W30,
20% ≥W40. Records W58, W60. Before September the all-time vision best was W26.

**Where the lives go now**: W5-25 NET ≈ +0.05; **W25-40 deaths/wave 1.32-1.43**;
the bank runs out in the mid-30s. Deaths cluster 8-20 s into a wave
(median 16 s), 0% at wave start. Late deaths have the same structure as early
ones (56% within 50 px of a wall, 35% boxed-in with <=2 free headings, same
killer mix: enforcer bullets, cruise missiles, tank shells, grunts) — same
mistakes at a higher rate, no distinct late failure mode.

## 5. Experiment ledger — September 2026 (what was tried, verdict, where)

Earlier campaigns (March-August) are in section 5i. The narrative version with
every number is [WHAT_WE_TRIED.md](WHAT_WE_TRIED.md).

Latency / loop

| lever | verdict | evidence |
|---|---|---|
| 30 Hz decision loop | dead | Xenia maxW 8.5 vs 20.4 p<.001; MAME NET −0.40 |
| eye-sync | **ship** | above |
| hold-action | ship with eye-sync | flat alone, best arm combined |
| TensorRT engine (detector 21.5 -> 9.2 ms) | no measurable effect (below the resolution of 16/arm + 12/arm); optional | d/w unchanged in both A/Bs, incl. late band 1.28 vs 1.39 ns |
| vision-age cost curve | NET by age: 0f +0.22, 1f +0.20, 2f +0.11, 3f +0.03, 4f −0.06 (non-linear; ~0.02/frame near zero, ~0.09/frame at 1-2 frames) | MAME LAB_AGE_FRAMES 0..4 |
| lead rule act+0.5 (was act−0.5) | ship (round 12) | MAME 40/arm; 1.0-1.5 flat optimum; 0.5 and 2.5 worse |

Planner knobs on the MAME proxy (all flat or negative, ≥144 games/arm)

| knob | NET vs base |
|---|---|
| actuation-aware dodge (3 variants), projectile weight, sticky heading, H4/H8, least-bad, EMA 0.3/0.8, extrapolation lag 0/0.6 | flat |
| wall repulsion (VSEARCH_WALL_W 0.3/0.6), max-clearance (MAXCLR) | −0.13 / −0.10 / −0.065*. **Caveat:** screened on the proxy build that was missing FSM_RESCUE_SEEK (found 2026-09-04 00:55) and never re-screened after the fix. MAXCLR's verdict also rests on MAME June 30 (global max-clearance override −2.71 waves vs min-deviation +2.57); WALL_W's on edge-deflect (MAME −0.40, proxy −0.015) and the launch-lane/slide results. |
| CLEAR_MARGIN 14 | −0.099* |
| FSM_THREAT_FIELD | −0.043* |
| FSM_EDGE_DEFLECT | −0.015 ns |
| FSM_SPAWNER_FIRE, radius 250, BRAIN_RESCUE_MULT 1.5 | flat / negative (72/arm) |
| evolved-constant ES, 24->48 games/candidate, 14 generations | random walk; stopped. A 288-games/candidate run was started twice and died (arm timeout, then killed for the rig) before producing a result. |
| **KITE mode 1** (circle at idle) | −0.035* (economy loss, no death change) |
| **KITE mode 2** (circle by default, clearance search dodges) | 144: d/w −0.04 but −0.026 NET; tuned (grab 300, ahead 0.9) +0.036 at 144 -> **−0.011 CI[−0.031,+0.010] at 576**; Xenia 12/arm +0.016 ns. **Null.** |
| KITE mode 3 (orbit the enemy centroid) | −0.074* |
| ALWAYS_FIRE (shoot nearest killable when fire idle) | d/w −0.026 (real, small), score −1.4%, NET +0.011 CI[−0.006,+0.029]. Parked. |
| real STAY (FSM STAY as neutral stick, planner-checked) | +0.004 ns (288/arm) |
| model-based threat advance (VSEARCH_AGE_ADVANCE) | −0.026 CI[−0.057,+0.003] |
| spawner-priority fire incl. spheroids/quarks at 300 px | −0.021 ns; score −2.6% (288/arm) |
| exit-preservation cost (VSEARCH_EXIT_W 6 / 2) | early band −0.031 / +0.003; exact-state late band 1.147 vs 1.143 (null), early 0.87 vs 0.77 (worse), W60 caps 4/8 vs 7/8. Closed. |
| class-specific projectile lead (1.0 / 1.3 vs 0.7) | null on Xenia (8/arm) and proxy |
| launch-lane prediction (virtual spark from each enforcer in range) | proxy flat; exact-state late band WORSE with slide (1.15 vs 1.02, p .08) |
| spark wall-slide at full speed (planner physics) | exact-state late band worse (1.11 vs 1.02); proxy null at 576/arm. The existing per-axis clamp already slides sparks at along-wall speed and is the better model. |

Bookkeeping / capture (all shipped, rounds 6-12): color-agnostic HUD OCR,
multi-variant wave templates (Eric's '8'), deaths = lives-drop only, no border
watchdog, glyph-count anchoring, capture probe (dshow MJPG 1080p), stale-frame
metric. Bookkeeping on Eric's rig is complete ("all waves correct, no false
deaths").

Dead ends not to reopen: start games at W24 by memory poke (0x82388E20 is a
display mirror; slot-1 "wave" word is a frame counter); wave-start opening
moves (0% spawn-in deaths); MAME late band as a proxy; the custom 6809
emulator `robotron_native` (freezes at wave 5 / wave 1, 5+ patches failed).

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

## 5c. The economy investigation (2026-09-08) - income is capped

Question: is the late band (W20-40, which repeats forever after W40) a bleed we
could fix by earning more, or a death problem?

**The late band is a rescue economy.** On XBLA every late wave has civilians
(0% zero-rescue waves), ~90% of score is rescue bonus (1000 to 5000 escalating,
then 5000 each), and kills are a few thousand per wave. Two wave types:

| late-band wave type | share | civilians on field (peak) | rescued | left unrescued |
|---|---|---|---|---|
| ordinary | ~80% | ~9 | ~8 | ~1 (tapped) |
| rich brain wave | ~20% | 25-26 | 8-15 | 10-18 |

Measured with a `peak_civ` instrument on the exact-state bot (max civilians
simultaneously on field per wave, logged to the dev tree's `logs/yolo_waves.jsonl`).

**The 17 unrescued civilians on a rich wave are NOT headroom.** The exact-state
bot, with perfect information, also rescues 8 of 25. They are converted to progs
by brains before any bot could reach them. Attempts to capture them:

| variant | mechanism | exact-state late band |
|---|---|---|
| FSM_RESCUE_BRAIN | brain gets fire priority over grunts while civilians present | d/w 1.07 to 1.17, rescues 8.1 to 7.8, score -5%: WORSE |
| (earlier) FSM_SPAWNER_FIRE / BRAIN_RESCUE_MULT | radius / priority tweaks | flat (proxy); BRAIN_RESCUE_MULT is a no-op under RESCUE_SEEK (byte-identical games, MAME July) |
| (earlier, memory bot) civilian boosts brainmult2 / mult2+civ150 / brainmult3 | pursue civilians harder | NET −0.009 / +0.003 / −0.022 vs +0.067 plain: all lost |

The rescue economy is at its cap and easily disturbed. The exact-state bot rides
W100 on the current economy (late-band NET about +0.02, censored 16.6M). Adding
economy is not the lever.

## 5d. The perception diagnostic (2026-09-08) - detection is not the gap

Vision detections vs memory truth, 74k late-band (W25-39) snapshot ticks from
the death rings (dev tree `logs/deaths_yolo/*.json`, fields `mem` and `vis`):

| on-field threats | recall |
|---|---|
| 5-9 | 89% |
| 10-14 | 92% |
| 15-19 | 91% |
| 20-24 | 91% |
| 25-29 | 91% |
| 30+ | 90% |

Recall is flat with density. Per class: Hulk 96, Grunt 95, Electrode 96, Tank 97,
Prog 97, Quark 92, Enforcer 91, Brain 90, Sphereoid ~97 (an earlier "8%" was a
spelling artifact - vision emits `Sphereoid`), TankShell 93, EnforcerBullet 87,
CruiseMissile 78. The projectile figures are lower only because they move more
than the 22 px match radius during the vision-age interval - that is the known
latency, not a miss. False positives 4-6%, falling with density. Player
position error median 0.6 px, p90 4.7 px. **The vision bot sees what the exact
state sees.**

## 5e. Bleed or luck? The Monte Carlo (2026-09-08)

From the shipped bot's own 61-game per-wave record (arm `both`, lead 0.7):

| | value |
|---|---|
| repeat band W20-39 deaths/wave | 1.23 |
| W40+ deaths/wave | 1.40 |
| income (score/25k) | ~1.10 lives/wave |
| net in the repeat band | about -0.13 lives/wave |
| bank of lives at W20 (median) | 4 |

Empirical reach from W20: W40 19%, W50 3%, W60 0% (best W57, W60). Resampling
waves from the record (an optimistic i.i.d. model; real deaths cluster):

| condition | P(reach W100 from W20) | median bust |
|---|---|---|
| current bot | ~2% | W43 |
| deaths/wave -0.10 | 13% | W53 |
| deaths/wave -0.15 | 24% | W62 |
| deaths/wave -0.20 | 37% | W77 |

**W60 is where a strong early bank runs out at -0.13/wave, not luck.** W100 by
luck is effectively zero. The nudge that would make W100 likely (-0.15 to
-0.20 deaths/wave in the repeat band) is exactly the vision-vs-exact age gap
(1.26 vs 1.07).

## 5f. The exact-state harness - how to test a planner idea cheaply

`ROBOTRON_ORACLE=1` runs the unchanged vision loop but replaces the detections
with the emulator's exact memory entities (velocities from the same tracker).
`=2` exact player only; `=3` exact entities only. `ROBOTRON_ORACLE_DELAY_MS`
ages the exact state (with `_DELAY_TARGET=both|entities|player`). Cap games
with `ROBOTRON_MAX_WAVE=40` so every game samples the repeat band; `ab_yolo.py
run --arm name=ENV,ENV --band 25 40` interleaves arms and reports per-band
deaths/wave, score/wave, rescues/wave with bootstrap CIs. 8 games/arm is about
2 h and resolves roughly +/-0.1 deaths/wave in the late band; 16/arm for +/-0.07.

Use it to measure a planner change with perception noise removed. If an idea
does not beat base on exact state, it will not on vision. The bar: late-band
deaths/wave clearly below base (1.02-1.07 in recent runs) with score not down.

## 5g. Knob inventory - what exists, and its status

The dev tree exposes about 110 environment knobs (`grep environ.get` over the
dev bots). Status as of 2026-09-10, so a reviewer does not re-propose closed items.

**Shipped ON in production (verified against `brain.py`, `cli.py` and `engine/`
defaults on 2026-09-10):** eye-sync 55 ms, hold-action 4, entity lead 0.7
(`--lag-ticks`), player lead 1.5 (auto-lead act+0.5 on real HDMI rigs),
velocity EMA 0.5, VSEARCH_ASMDYN=1, VSEARCH_H=6, CLEAR_DANGER/MARGIN 18/10
(memory) and **21/12 on the vision path** (`VISION_MARGINS`), VSEARCH_FIREPLAN
(vision path only), FSM_RESCUE_SEEK=1, FSM_ADJACENT_QUARK=75,
FSM_HULK_DEFLECT=1 (R 60), HUNT via the evolved `fsm_evolved_planner_v2_hunt.json`,
the ProjectileCoaster (TTL 3), yolo6 weights at `--conf 0.30`.

**Correction (2026-09-10).** An earlier version of this list also named
VSEARCH_ACT_LAG, VSEARCH_LEAST_BAD and FSM_BUFFER_SCALE 1.15 as shipped. They
are not: the production planner has no ACT_LAG knob (dev-only, rejected on the
proxy), VSEARCH_LEAST_BAD defaults to 0 (null on Xenia in July and on the proxy
in September), and FSM_BUFFER_SCALE defaults to 1.0 (1.15 was a dev-loop env
setting; its July weak positive did not reproduce in August). LOWCONF
continuation is not in production at all.

**Tested and closed (numbers in sections 5 and 5i):** 30 Hz loop; frameskip 2;
VSEARCH_H raised (never on vision); WALL_W and MAXCLR (see caveat in section 5);
CLEAR_DANGER 14; CLEAR_MARGIN 14; margins 1.3x; FSM_BUFFER_SCALE 1.15 / 1.30;
FSM_OVERRIDE_CLOSE_MOVE_PROJECTILE 70 / 45 (PROJ80 / PROJ52); fire bundle and
CLOSE_FIRE_COUNT_LIMIT; THREAT_FIELD (broad and pincer-gated); EDGE_DEFLECT;
FSM_HULK_NOFIRE; FSM_HULK_PUSH; FSM_NO_SHOOT_SHELLS; FSM_OVERRIDE_HUNT_STANDOFF
60; SPAWNER_FIRE / SPAWNER_ALL / SPAWNER_FIRE_R / MAME SPAWNER_HUNT;
BRAIN_RESCUE_MULT; RESCUE_BRAIN; MAME ORBIT_* genes; KITE modes 1-3 and all
KITE_* geometry; ALWAYS_FIRE (parked); VSEARCH_STAY / LAB_STAY;
VSEARCH_AGE_ADVANCE; VSEARCH_EXIT_W/MIN/STEPS; VSEARCH_SPARK_SLIDE;
ROBOTRON_LAUNCH_LANE/R/SPD; ROBOTRON_YOLO_LAG_PROJ / LAB_LAG_PROJ;
VSEARCH_W_SPARK, W_ENF, PROJ_W, STICKY, ACT_LAG (actuation-aware dodge family);
VSEARCH_LEAST_BAD; ROBOTRON_TRACK_ALL (phantom timidity);
ROBOTRON_TRACK_NOCOAST (lean tracker, null); ROBOTRON_PHANTOM_SOURCES (static
blob, timid); ROBOTRON_LOWCONF (+ WIDE); ROBOTRON_COAST_FIT (harmful);
ROBOTRON_COAST_MS_TURN (harmful); ROBOTRON_AUTOCAL_APPLY (score −1.5k/wave);
per-class conf table (score −2.5k/wave); gates 0.05 (FP flood); ROBOTRON_FOVEA
(catastrophic without crop-trained weights); ROBOTRON_ARENA_CROP (null despite
+6 pt recall, twice); TensorRT / WGC capture (age is upstream); evolved-constant
ES on the proxy (24-48 games/candidate, random walk) and on Xenia vision
(evolve_fsm.py, 8 games/eval, 12 generations, parity).

**Previously listed as "unverified" — all resolved from the campaign notes on
2026-09-10:**

| knob | status | evidence |
|---|---|---|
| FSM_HULK_DEFLECT | **shipped, default ON** | MAME June 29: +1.26 waves paired N=100 (13.04 -> 14.30, 60% win rate) |
| FSM_HULK_NOFIRE | closed, negative | MAME June 29: −0.69 paired over 61 games, declining with N |
| FSM_HULK_PUSH | closed, negative | MAME: recorded as failed ("reactive HULK_PUSH/NOFIRE both failed", MAME log July 1); numbers not carried forward |
| FSM_NO_SHOOT_SHELLS | closed, negative | MAME July 1: −3.04 [−5.2, −0.9] n=94; Xenia vision Aug 5: flat (p>0.48) |
| HUNT_STANDOFF | shipped at the evolved value (~90) | override 60 on Xenia vision Aug 5: flat (p>0.48) |
| ROBOTRON_COAST_FIT | closed, harmful | Xenia vision July 9: mean 10.6 vs 14.4 (n=5); a 4-sighting line fit lags every wall bounce |
| ROBOTRON_COAST_MS_TURN | closed, harmful | Xenia vision July 9 (MSTEER): mean 10.6 vs 14.4 (n=5); curved ghosts over-warn |
| ROBOTRON_TRACK_NOCOAST | closed, null | Xenia vision July 29, 25/arm: d/w 1.198 / 1.202 vs 1.215, score 27.1k / 28.0k vs 28.6k, maxW 16.3 vs 17.0 |
| ROBOTRON_AUTOCAL_APPLY | closed, negative | Xenia vision July 30: score −1,546/wave (p=0.08) |

The "hulk-pin = 30% of deaths" figure came from the MAME taxonomy of early July,
before rescue-seek and the hunt fix. Hulks were 20% of the memory bot's real
deaths on Xenia (July 4) and are **4.9%** of the vision bot's (600 deaths,
September; 6% in the late band).

## 5h. Genuinely untried directions (honest list, with priors)

Nothing below has been measured. Priors are my judgement from the record. The
previous version of this list had five items that turned out to have been
tested (TRACK_NOCOAST, COAST_FIT, hulk handling, NO_SHOOT_SHELLS, a learned
policy); they moved to 5g / 5i.

1. **Hardware age** - on the console the capture card and display path set the
   age (one rig: 40% duplicate frames). A lower-latency capture path is the
   only lever that attacks the residual directly. Not testable from here.
2. **Re-screen WALL_W / MAXCLR on the corrected proxy** - the only direct
   September screens ran without FSM_RESCUE_SEEK. ~1 h of farm time. Prior: low
   (every related test lost), but cheap and it closes a hole in the record.
3. **Exact forward model + beam search over move sequences** ("Stage 3", MAME
   plan of 2026-07-01). The sim-state plumbing exists on the MAME side
   (`MAME_EMIT_SIM=1`, `parse_sim_state()`); the model and search were never
   built. The one planner idea aimed at beating the oracle's capped late band.
   Prior: low-moderate; weeks.
4. **Coupled move+fire ("clear a route, then take it")** - FIREPLAN is a narrow
   version and won on vision; the general joint plan is untested. Prior:
   low-moderate.
5. **30 Hz decisions WITH eye-sync and the 9 ms TensorRT engine** - 30 Hz was
   "dead" before eye-sync existed; untested in the current stack. Prior: low
   (age, not cadence, is the cost; MAME frameskip 2 also lost −2.88), but cheap.
6. **Per-detection age** - extrapolate each entity by the measured age of its
   own frame instead of a global 0.7. Same plateau argument; prior low.
7. **FSM_HULK_PUSH on vision** - lost on MAME; hulks are ~5% of vision deaths.
   Prior: low.
8. **Re-evolve the FSM constants on VISION input at 576+ games/candidate** -
   the Xenia run used 8 games/eval (parity after 12 generations), the proxy runs
   24-48 (random walk). Cost: days of Xenia time per generation. Prior:
   moderate in principle, prohibitive in cost.
9. **A different kind of learned policy** - ~20 conventional variants (RL,
   reward shaping, grid/LSTM/attention networks, BC, DAgger, anchored RL,
   residual RL, curriculum, ExIt) all stayed below the FSM on MAME (best
   learned mean 9.41 vs FSM 12.6; a clone of the W100 champion 6.1-6.5). A new
   attempt would need a structurally different target (e.g. learning planner
   cost terms, not raw actions). Prior: low.

Closed-by-measurement list for reference: section 6, the ledgers in 5 and 5i,
and 5g. Do not spend time on those without a new mechanism.

## 5i. Earlier campaigns (March-August 2026), for completeness

The full narrative with every number is in [WHAT_WE_TRIED.md](WHAT_WE_TRIED.md).
MAME-era numbers are mean wave from wave 1 on perfect input (different seeding
from the later proxy); Xenia vision numbers are mean max wave unless stated.

Architecture (MAME, June-July; log: [docs/archive/MAME_EXPERIMENT_LOG.md](docs/archive/MAME_EXPERIMENT_LOG.md))

| lever | verdict | evidence |
|---|---|---|
| hand-written memory bots (brain2 force field, brain3 goal planner with orbit + spawners-first, brain4) | superseded | Xenia, March: best W7 (brain2 avg 4.7 over 30 games) |
| learned policies (~20 variants) | closed | best anchored RL 9.41 (N=100) vs FSM 12.6; teacher-agnostic (12.7- and 14.3-wave teachers both give ~9.4); W100-champion clone 6.1-6.5 |
| FSM constant evolution (honest reseed fitness) | **ship** | 10.4 -> 11.18 -> 12.72; combteacher (co-evolve ADJACENT_QUARK, HULK_DEFLECT_R) +2.84 paired N=100; planner-in-loop gen 6 +10.25 -> W113, official mean 49.1, max 142 |
| evolution round 2 (both times) | rejected | combteacher2 −0.85; planner_v3b mean 155.6 vs 173.7 |
| save/restore look-ahead search | impossible | MAME save-state lossy for this driver: diverges by step 4 |
| learned value model + analytic 1-step override | parity | N=100 12.32 vs 12.19 (+1.05 at N=40 was seed luck) |
| **minimal-deviation clearance search** (H=6, DANGER 18, MARGIN 10) | **ship** | +2.57 paired N=100 (15.21 vs 12.64); global max-clearance variant −2.71; DANGER 14-24 all +2.6..+3.1 |
| horizon H=8 / 10 / 14 | rejected | June +1.27 / +1.67 vs +2.57 for H=6; July with ASMDYN −4.7 (H10) / −5.7 (H14) |
| ASM-true dynamics (VSEARCH_ASMDYN) | kept, parity | +0.16 [−1.94, +2.27] n=97; the concurrent label fix took the planner 15.2 -> 22.7 |
| FIREPLAN on perfect input | parity | MAME July −0.85 [−3.1, +1.4]; Sept perfect-input +0.089 |
| frameskip 2 | rejected | −2.88 [−5.7, −0.05] n=50 |

FSM structure (MAME, June-July)

| lever | verdict | evidence |
|---|---|---|
| quark kiting (ADJACENT_QUARK 75) | **ship** | +0.72 paired N=100; 50 / 60 / 90 all worse; quark deaths 32% -> 27% |
| hulk deflection (HULK_DEFLECT) | **ship** | +1.26 paired N=100 |
| HULK_NOFIRE / HULK_PUSH | rejected | −0.69 / failed |
| threat field, broad / pincer-gated | rejected | −1.20 (40% win) / −2.65 (26% win) |
| edge deflect | rejected | −0.40 paired N=100 |
| CLOSE_MOVE_QUARK 100 (flee quarks 2x) | wash | −0.38 [−1.77, +1.02] |
| rescue-seek (FSM_RESCUE_SEEK) | **ship** | score +35% (621k vs 459k), wave +1.27 [−0.8, +3.4], income 25.6k/wave |
| endgame hunt (HUNT_KILLABLE, standoff 90) | **ship** | official mean 173.7 vs 49.1; W100+ 76% vs 4% |
| NO_SHOOT_SHELLS | rejected | −3.04 [−5.2, −0.9] n=94 |
| spawner snipe (any range; 250 px below priority) and orbit genes, 3 lag regimes | rejected | snipe −3.0 to −4.5 waves (score 18.2k -> ~13k/wave); orbit −0.9 / −1.9 / −5.1 |

Memory-input bot on Xenia (July)

| lever | verdict | evidence |
|---|---|---|
| 6809 list-walk entity reader (replaces 250 ms accumulator) | **ship** | ceiling W18 -> W39 first game (1.02M) |
| entity extrapolation by LAG_TICKS | **ship** | MAME latency lab: comp K=1 recovers 90% of lag-free depth; Xenia optimum 0.25 after frame-sync |
| actuation-lag cost curve (MAME latency lab, July 4) | measured | action applied A = 0 / 1 / 2 / 4 ticks late: mean wave 42.3 / 18.0 / 7.9 / 3.2; entity extrapolation does not compensate it (comp K=1 + A=1: 14.6 vs 35.1). Motivated player forward prediction. |
| frame-sync + velocity EMA 0.5 + false-death fix | **ship** | real d/w 1.22 -> 1.05 |
| player forward prediction (lead 0.45) | **ship** | W40-58 wall -> W138, then W158 |
| civilian boosts, EMA 0.35, FSM_BUFFER_SCALE 1.3 | rejected | all lost to plain; buffer 1.3 a wash under lag compensation |

Vision bot on Xenia (July-August)

| lever | verdict | evidence |
|---|---|---|
| label-reader fix + offsets (auto_labeler) | **ship** | mAP50 0.38 -> 0.85 |
| Prog gate missing / `--conf` 0.4 floor bugs | fixed | Prog fix: median 15 -> 16, max 16 -> 18 |
| rare-class export fix (snap fast-class boxes) | **ship** | yolo5 mAP50 0.906; NEVER_SEEN deaths 16-22% -> 2% |
| yolov8s-p2 small-object head (yolo6) at conf 0.30 | **ship** | mean parity, d/w 0.898 best, W20+ tail thicker |
| hard-example fine-tune; retrain cycle 2 | null | flat / ties |
| arena-crop training (yolo9) | null | +6 pt MS recall, mean 13.04 vs 13.49 |
| gates 0.05; per-class conf table | rejected | FP flood; score −2,454 (p=0.055) |
| ProjectileCoaster; COAST_TTL 5 -> 3 | **ship** | mean 10.7 -> ~14.5; p90 error 29 -> 19.7 px, 12.9 -> 13.6 |
| EntityTracker (TRACK_ALL); lean tracker (NOCOAST); PHANTOM_SOURCES; LOWCONF v1 / v1.1 / v2; ByteTrack | rejected / null | TRACK_ALL score 22.9k vs 27.7k p<0.001, maxW 10.0 vs 14.6; LOWCONF2 12.08 (−2.4 SE) |
| MSTEER homing coast; COAST_FIT line fit | rejected | both 10.6 vs 14.4 (n=5) |
| fovea 2x crop pass | rejected | games end W1-3 (out-of-distribution scale) |
| threaded vision (July 7) / threaded eye retry (Aug 1) | regressed / **ship** | 10.75 vs ~14.5; retry flat on primaries (p=0.97), shipped on consistent trend + hardware architecture |
| latency constants lead 1.5 / lag 0.3 | **ship** | maxW 14.6 -> 18.0 (p=0.003) |
| YOLO_LAG_TICKS 0.4 (vs 1.0, sync era) | null | 10.75 vs 12.1 (n=4) |
| margins 21/12 (1.15x) vs 23/13 (1.3x) | **ship** 1.15x | 14.4 vs 12.75 |
| FSM_BUFFER_SCALE 1.15 / 1.30 | not shipped / rejected | 1.15 13.71 vs 13.31 in July, flat n=20 in August; 1.30 12.60 (z −1.26), maxW −3.4 (p=0.084) |
| CLOSE_MOVE_PROJECTILE 70 / 45 (PROJ80 / PROJ52) | rejected | 10.6 (d/w unchanged) / 12.2 (d/w better, score worse) vs 13.49 |
| LEASTBAD | null | 14.1 vs 14.4 (n=10) |
| autocal per-game lag; perclass conf; CLEAR_DANGER 14 | rejected / rejected / flat | score −1,546 (p=0.08); −2,454 (p=0.055); flat |
| H=8 on vision | rejected | score −1,280, worst W5-13 drain −0.33/wave |
| VSEARCH_W_SPARK 2.4; VSEARCH_W_ENF 1.9 | null | all p>0.7 / flat |
| **VSEARCH_FIREPLAN** (fire at the clearance-binding threat) | **ship** | d/w 1.20 vs 1.38 (p=0.027), maxW 21.9 vs 17.5 (p=0.007), first positive NET on vision; replicated 40/arm |
| FSM_SPAWNER_FIRE on vision; BRAIN_RESCUE_MULT 1.5 | rejected / flat | score −3,615 (p=0.019), no death gain |
| coordinate descent: fireproj 150, moveproj 80, fire bundle + firecount | null | all flat: constants locally optimal on vision |
| hunt60; noshells | null | p>0.48 (noshells logged the then-record W55 in one game) |
| evolve_fsm.py on Xenia vision (24 dims, mirrored pairs, 8 games/eval) | stopped | 12 generations (gens 1-11 had a MAX_WAVE evaluator bug), evolved mean replay NET −0.067 ≈ parity |

## 6. Where the ceiling is (settled 2026-09-08)

Two investigations on 2026-09-08 closed the last two open levers by measurement.

**Planner economy is capped.** The late band is a rescue economy (~90% of
score is rescue bonus; every late wave has civilians). The rich brain waves
hold 25 civilians and the bot rescues 8 — but so does the EXACT-STATE bot
with perfect information. The other 17 are converted by brains before any
bot could reach them; they are not headroom. The exact-state bot already
rides W100 at late-band NET ≈ +0.02 (censored 16.6M). Adding economy is not
the lever; the brain-suppression variant (FSM_RESCUE_BRAIN) made deaths,
rescues and score all worse.

**Perception is not the gap.** Against memory truth over 74k late-band
snapshots: overall recall 89-92% at every density from 5 to 30+ threats on
field, 90-97% per non-projectile class, false positives 4-6%, player error
median 0.6 px. The vision bot sees what the oracle sees.

**The residual is unextrapolatable age.** Vision late-band deaths/wave
(1.26) equals the exact-state-aged-one-tick-plus-lead-0.7 arm (1.33), not
the fresh exact state (1.07). Lead 0.7 recovers the part of the age that
velocity extrapolation can predict. It cannot recover events inside the
aged interval — a projectile launched, an enemy re-aiming. Only reducing
the age itself helps, and that is upstream in presentation and capture,
where WGC and TensorRT showed no reduction.

**Launch prediction (2026-09-08 overnight) closed too.** The last open
mechanism — dodge the launch instead of the spark, via a virtual spark from
each in-range enforcer — was flat on the proxy and worse on the exact-state
late band, alone and combined with a full-speed wall-slide for sparks. The
planner's existing wall model (spark slides at its along-wall speed) was
already right; giving it full speed over-predicts wall danger and pushes the
bot off the walls into the pack.

**Verdict:** the shipped configuration is at the achievable ceiling for
this architecture at this latency: mean W31, median 30, half of games past
W30, records W58/W60. Reliable W100 on the emulator needs either a planner
that beats the oracle's capped +0.02 late band, or lower age from the
hardware chain. On the console, age is a property of the capture card and
display path; the bracketed lead (0.5-0.9 plateau) is the compensation.

## 6a. Previous lever ranking (superseded)

Where the late-band (W25-40) deaths/wave stands, from the exact-state harness:

| input | W25-40 deaths/wave |
|---|---|
| exact state, fresh (oracle0), lead 0.2 / 0.7 | 1.20 / 1.14 |
| exact state aged ~1 tick, lead 0.7 | 1.33 |
| real vision, lead 0.7 | 1.32-1.46 |
| real vision, old lead 0.2 | 1.36-1.50 |

So after the lead fix, roughly 0.13 of the late-band gap is residual age and
0.05-0.10 is detection quality under density; the planner itself (fresh exact
state) is at 1.20 and still bleeds slightly (income ~1.15 lives/wave there).

1. **Ship round 13 to Eric** (eye-sync, hold-action, lead 0.7, start-ladder
   and demo-phantom fixes). Expect a larger relative gain on the console than
   on the emulator if its lag is similar; the 0.5-0.9 plateau covers drift.
2. **Residual age**: class-specific lead (projectiles vs chasers) and a
   velocity tracker tuned on the oracle harness (exact velocities are
   available there as ground truth). Test on Xenia W5-25 first (cheap), then
   W25-40 at 40 games/arm.
3. **Late-band planner economy**: even fresh exact state is ~break-even at
   W25-40. Candidates in order: exit-preservation cost at the search horizon,
   coupled move+fire (the "clear a route" idea), rescue-sequence value. Use
   the oracle harness (fresh) to test planner changes without perception
   noise, then confirm on vision.
4. **Detection under density**: only worth attacking after 2 and 3; the
   harness says it is the smallest of the three terms.

Closed (do not reopen without a new mechanism): 30 Hz loop; kite/orbit
circling; wall repulsion / max-clearance / larger margins; threat-field;
edge-deflect; spawner-priority fire (brains, and spheroids/quarks at 300 px);
brain-wave rescue multiplier; always-fire; real-STAY; model-based threat
advance; class-specific projectile lead; exit-preservation cost (null late on
exact state, loss early); evolved-constant search on the proxy (24-48
games/candidate) and on Xenia vision (8 games/eval); TensorRT and WGC capture
(age is upstream); wave-start scripts; W24 memory poke.

## 6b. Known quirk (found by fresh-context review, 2026-09-06) - RESOLVED, null

All bots (production `brain.py`, dev `brain_champion.py`, `mame_lab.py`) map
the FSM's STAY output to direction 1 = UP: the bot never stands still; every
"hold position" decision walks toward the top wall. Consistent across the
proxy and Xenia, so the proxy is still valid. The STAY-as-neutral variant
(VSEARCH_STAY / LAB_STAY) measured +0.004 CI[−0.026, +0.035] over 288/arm:
harmless in practice. Knobs remain opt-in.

## 7. Operating rules that cost us time to learn

- Never run emulator bots while the user is at the machine (the virtual pad
  hijacks the mouse). Idle detection is only valid with no bot running; a
  foreground-window guard kills bots if Xenia loses focus. A `git push` that
  raises the 1Password SSH prompt steals the foreground and trips the guard.
- Xenia and 16 MAME instances together hang MAME sockets (games end at W2/3
  with <100 steps); hung games contribute nothing to band stats.
- Never run two window-capture processes on Xenia at once (native crashes);
  pair diagnostics with memory-input bots only.
- `pkill -f` patterns that match the invoking shell self-kill it; anchor on
  argv0. WSL background jobs need `setsid nohup ... < /dev/null & disown`.
- `cal act=` in the dev bot climbs to 2.0 as it saturates; compare like sample
  counts. Root repo `C:\Users\strid\code` has a stray first commit to delete.
- Always dry-run an optimizer before spending compute on it (the first 1+λ ES
  was proven broken by a dry run), and never ship an auto-calibration loop
  unvalidated (box-center auto-apply walked twice on Eric's rig).
- When a config wins, `setdefault` it in the brain that owns it: two validated
  settings were once lost because they lived only in launcher env vars.

## 8. Where the detail is

**In this repo:**
- Every attempt since March 2026, with numbers, verdicts and reasons:
  [WHAT_WE_TRIED.md](WHAT_WE_TRIED.md).
- Production flags and harness behaviour: [README.md](README.md).
- Game internals and archived research, indexed in [docs/](docs/README.md):
  [ENEMY_MODEL.md](docs/ENEMY_MODEL.md) (ROM-grounded behaviour of every entity),
  [XENIA_MEMORY.md](docs/XENIA_MEMORY.md) (what the memory bot reads, and the
  dead ends), [DISASM_REFERENCE.md](docs/DISASM_REFERENCE.md) (the annotated
  disassembly and its labels), [SPRITE_DATA.md](docs/SPRITE_DATA.md), and the
  June-July MAME notebook [docs/archive/MAME_EXPERIMENT_LOG.md](docs/archive/MAME_EXPERIMENT_LOG.md).

**External:**
- Scott Tunstall's annotated 6809 disassembly: <https://seanriddle.com/robomame.asm>;
  wave composition table: <https://seanriddle.com/robowaves.html>.

**Not in this repo** (on the development machine only; nothing above depends on
them):
- The unversioned dev tree `C:\Users\strid\code\robotron\`: dev bots, A/B
  harness, `logs/` (A/B logs `ab_*.log`, `uncapped.log`, death rings) and
  `SCRIPTS.md` (usage of the dev scripts).
- MAME logs in `~/mame_logs/` (WSL).
- Claude's project-memory notes (`project_yolo_pipeline_rework.md` and
  siblings): the source of the round-by-round history, now folded into
  WHAT_WE_TRIED.md and sections 5g-5i above.
