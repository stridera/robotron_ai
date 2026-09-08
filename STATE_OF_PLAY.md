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

## 4. Current shipping configuration (origin/main 4e42ab2 runtime, 2026-09-07; docs through 17893c3)

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
simultaneously on field per wave, logged to `robotron/logs/yolo_waves.jsonl`).

**The 17 unrescued civilians on a rich wave are NOT headroom.** The exact-state
bot, with perfect information, also rescues 8 of 25. They are converted to progs
by brains before any bot could reach them. Attempts to capture them:

| variant | mechanism | exact-state late band |
|---|---|---|
| FSM_RESCUE_BRAIN | brain gets fire priority over grunts while civilians present | d/w 1.07 to 1.17, rescues 8.1 to 7.8, score -5%: WORSE |
| (earlier) FSM_SPAWNER_FIRE / BRAIN_RESCUE_MULT | radius / priority tweaks | flat (proxy) |

The rescue economy is at its cap and easily disturbed. The exact-state bot rides
W100 on the current economy (late-band NET about +0.02, censored 16.6M). Adding
economy is not the lever.

## 5d. The perception diagnostic (2026-09-08) - detection is not the gap

Vision detections vs memory truth, 74k late-band (W25-39) snapshot ticks from
the death rings (`robotron/logs/deaths_yolo/*.json`, fields `mem` and `vis`):

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

The dev tree exposes about 110 environment knobs (`grep environ.get robotron/*.py`).
Status as of 2026-09-08, so a reviewer does not re-propose closed items:

**Shipped ON in production (defaults):** eye-sync 55 ms, hold-action 4,
entity lead 0.7 (`--lag-ticks`), player lead 1.5, velocity EMA 0.5,
VSEARCH_FIREPLAN, VSEARCH_ACT_LAG, VSEARCH_ASMDYN, VSEARCH_LEAST_BAD,
FSM_BUFFER_SCALE 1.15, CLEAR_MARGIN 1.15, FSM_RESCUE_SEEK, the coaster
(LOWCONF 0 / conf 0.30), FSM_ADJACENT_QUARK (evolved), HUNT (via the
evolved `_hunt` json).

**Tested and closed (see ledger section 5 for numbers):** 30 Hz loop; VSEARCH_H
raised (never on vision); WALL_W; MAXCLR; CLEAR_DANGER 14; THREAT_FIELD;
EDGE_DEFLECT; SPAWNER_FIRE / SPAWNER_ALL / SPAWNER_FIRE_R; BRAIN_RESCUE_MULT;
RESCUE_BRAIN; KITE modes 1-3 and all KITE_* geometry; ALWAYS_FIRE;
VSEARCH_STAY / LAB_STAY; VSEARCH_AGE_ADVANCE; VSEARCH_EXIT_W/MIN/STEPS;
VSEARCH_SPARK_SLIDE; ROBOTRON_LAUNCH_LANE/R/SPD; ROBOTRON_YOLO_LAG_PROJ /
LAB_LAG_PROJ; VSEARCH_W_SPARK, W_ENF, PROJ_W, STICKY (actuation-aware dodge
family); ROBOTRON_TRACK_ALL (phantom timidity); ROBOTRON_PHANTOM_SOURCES
(static blob, timid); ROBOTRON_FOVEA (catastrophic without crop-trained
weights); ROBOTRON_ARENA_CROP (null despite +6 pt recall); TensorRT / WGC
capture (age is upstream); evolved-constant ES at 48 and 288 games/candidate.

**Exist, built with forensic rationale, A/B status NOT in this ledger - verify in
git log / memory before proposing:** FSM_HULK_DEFLECT, FSM_HULK_PUSH,
FSM_HULK_NOFIRE (hulk-pin was 30% of deaths in the July taxonomy),
FSM_NO_SHOOT_SHELLS (tank shell budget), FSM_HUNT_STANDOFF value,
ROBOTRON_COAST_FIT (line-fit velocity for straight projectiles),
ROBOTRON_COAST_MS_TURN, ROBOTRON_TRACK_NOCOAST (the code's own open question:
all-class tracking without coasting), ROBOTRON_AUTOCAL_APPLY.

## 5h. Genuinely untried directions (honest list, with priors)

Nothing below has been measured. Priors are my judgement from the record.

1. **ROBOTRON_TRACK_NOCOAST** - all-class tracking that keeps the recall gain
   of TRACK_ALL without coasting ghosts (the coasting caused the timidity).
   Cheap to run on vision. Prior: low-moderate; recall is already 95%.
2. **ROBOTRON_COAST_FIT** - line-fit velocities for sparks/shells to cut
   differencing noise. Attacks the velocity-noise part of the residual. Prior:
   low; the lead bracket's 0.5-0.9 plateau says the planner is insensitive to
   extrapolation error of this size.
3. **Per-detection age** - extrapolate each entity by the measured age of its
   own frame instead of a global 0.7. Same plateau argument; prior low.
4. **30 Hz decisions WITH eye-sync and the 9 ms TensorRT engine** - 30 Hz was
   "dead" before eye-sync existed; untested in the current stack. Prior: low
   (age, not cadence, is the cost), but cheap.
5. **Re-evolve the FSM constants on VISION input at 576+ games/candidate** -
   the evolver only ever ran on the proxy at 48/288 (random walk). Cost: days of
   Xenia time per generation. Prior: moderate in principle, prohibitive in cost.
6. **Hulk handling** (the three HULK_* knobs above) - hulk-pin was 30% of deaths
   in July; status unclear. Prior: moderate if untested; verify first.
7. **Tank-shell budget** (FSM_NO_SHOOT_SHELLS) - dodging shells forever
   exhausts the wave's shell budget; shooting frees an aimed shot. Prior: low.
8. **A learned policy** (RL or imitation on exact-state trajectories, which the
   harness can generate at will) - the only architecture change left. Prior:
   the one thing that could beat the exact-state bot's late band; weeks of work.
9. **Hardware age** - on the console the capture card and display path set the
   age (one rig: 40% duplicate frames). A lower-latency capture path is the
   only lever that attacks the residual directly. Not testable from here.

Closed-by-measurement list for reference: section 6 and the ledger section 5.
Do not spend time on those without a new mechanism.

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
snapshots: recall 95%+ for every class, flat from 10 to 30+ threats on
field, false positives 4-6%, player error median 0.6 px. The vision bot
sees what the oracle sees.

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
exact state, loss early);
evolved-constant search at 48 or 288 games/candidate; TensorRT and WGC
capture (age is upstream); wave-start scripts; W24 memory poke.

## 6b. Known quirk (found by fresh-context review, 2026-09-06) - RESOLVED, null

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
