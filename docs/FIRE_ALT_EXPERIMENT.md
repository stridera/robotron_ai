# Fire alternation (FIRE_ALT) — experiment record, started 2026-09-14

## The mechanism (from the ROM)

Robotron's fire-joystick task (`READ_PLAYER_FIRE_JOYSTICK`, robomame.asm
`$31B9`-`$3235`) runs every frame:

- It reads the four fire bits and compares them with the previous frame's.
- **If the direction changed**, it clears the "count up before firing" byte
  (`$3229: CLR $0008,U`) and returns.
- If unchanged, it increments the count. **A laser is fired when the count
  reaches 2**, and afterwards whenever the count is a multiple of 8
  (`ANDB #$07 / BNE`), as long as fewer than 4 player lasers are on screen
  (`$87`).

So holding one direction yields a shot 2 frames after the direction is set and
then one shot every 8 frames (7.5 shots/s). Changing the direction restarts the
count, and the first shot in the new direction comes 2 frames later.

Our decision tick is 4 frames. If the bot alternates between two fire
directions every tick, the ROM sees a change every 4 frames and fires 2 frames
after each: **one shot every 4 frames (15/s), i.e. double the throughput**, with
shots toward each of the two directions still arriving every 8 frames — the
primary target loses nothing. The only cost is the 4-laser cap, which binds
only when lasers fly long without hitting anything (sparse scenes).

The vision bot already changes its fire direction on 45% of ticks (measured
over six emulator games), so it was accidentally getting part of this.

## The knob

`VSEARCH_FIRE_ALT=1` (dev and production clearance planner, default off,
byte-identical when off — verified on 300 random scenes). After the clearance
search picks the move and fire, if this tick's fire direction equals last
tick's and another killable, non-hulk threat within `VSEARCH_FIRE_ALT_R`
(default 160 px) lies in a different compass direction, fire at that one this
tick instead. With one target it holds; with two it alternates.

## Stage 1 — MAME cal_d10 proxy screen (2026-09-14 19:42-19:52)

`mame_run.sh`, 16 workers x 9 games, W26 cap, band W5-25, calibration
`LAB_ACT_FRAMES=4 LAB_LEAD=1.5 LAB_K=1 LAB_LAG=0.3 LAB_DROP=0.10 LAB_PDROP=0.02
LAB_NOISE=2` (the 2026-09-03 cal_d10 set; the weekend's fresh runner uses
LAB_LAG=0.7). Two baseline and four candidate workers hit the known MAME
"instance wedged" reset failure and stopped early.

| arm | games | reached W26 cap | deaths/wave W5-25 | score/wave | rescues/wave | NET |
|---|---:|---:|---:|---:|---:|---:|
| base | 131 | 67 (51%) | 1.127 | 27,873 | 8.11 | −0.012 |
| fire_alt | 132 | 119 (90%) | 0.844 | 28,532 | 8.14 | +0.297 |

**NET delta +0.309, whole-game bootstrap 95% CI [+0.265, +0.352].** Mean
score per game 531k → 645k. Ten times the +0.03 screen threshold; larger than
any proxy effect in the record, so it gets the full confirmation ladder before
anyone believes it.

## Confirmation ladder (queued the same evening)

1. Xenia exact-state late band: `ab_yolo.py run --games 8 --band 25 40`,
   arms `ROBOTRON_ORACLE=1,ROBOTRON_MAX_WAVE=40` with and without
   `VSEARCH_FIRE_ALT=1`, interleaved. Log:
   `robotron/logs/ab_exact_fire_alt_20260914.jsonl`. Tests the mechanism on
   the actual XBLA game code (does the port keep the arcade fire task?) and in
   the repeat band that decides W100.
2. MAME fresh-seed, fresh-process confirmation, 576 games/arm, LAB_LAG=0.7
   calibration: `tools/run_collision_mame_fresh.py --games 576 --candidate-name
   firealt --candidate-env VSEARCH_FIRE_ALT=1 --seed-base 0x2084915
   --prefix firealt_confirm_20260914`.
3. Real-vision Xenia W5-25 A/B on the shipping configuration, then uncapped
   depth runs, then round-15 console.

Results are appended below as they arrive.

### Stage 1 companions (same queue, same calibration, 20:22)

| arm | games | deaths/wave | score/wave | NET delta vs base (95% CI) |
|---|---:|---:|---:|---|
| disc10 (VSEARCH_H=10, VSEARCH_DISCOUNT=0.15) | 144 | 1.202 | 26,343 | −0.137 [−0.180, −0.098] |
| mpc (VSEARCH_ACT_LAG=1 + VSEARCH_AGE_ADVANCE=1.0) | 135 | 1.208 | 27,183 | −0.109 [−0.150, −0.068] |
| maxclr (VSEARCH_MAXCLR=1, re-screen with RESCUE_SEEK on) | 137 | 1.076 | 22,750 | −0.154 [−0.189, −0.119] |
| wallw03 (VSEARCH_WALL_W=0.3, re-screen with RESCUE_SEEK on) | 130 | 1.088 | 21,707 | −0.208 [−0.246, −0.170] |

All four closed. The two re-screens settle the STATE_OF_PLAY caveat that
WALL_W / MAXCLR had only been measured on the proxy build without rescue
seeking: they lose on the corrected build too.

### Stage 1 by wave band (same games)

| band | base deaths/wave | fire_alt deaths/wave | base score/wave | fire_alt score/wave | rescues/wave (base / fire_alt) |
|---|---:|---:|---:|---:|---|
| W1-4 | 0.109 | 0.088 | 11,752 | 11,896 | 3.75 / 3.72 |
| W5-9 | 0.842 | 0.567 | 27,870 | 27,871 | 7.74 / 7.54 |
| W10-14 | 1.000 | 0.761 | 26,880 | 26,753 | 7.80 / 7.75 |
| W15-19 | 1.347 | 0.984 | 26,820 | 27,758 | 7.77 / 7.83 |
| W20-25 | 1.426 | 1.045 | 30,367 | 31,361 | 9.42 / 9.28 |

The reduction is present in every band and largest in absolute terms in the
densest one; rescues per wave are unchanged, so this is faster killing, not a
change in the rescue economy — the shape one would expect from doubled laser
throughput.

### Stage 2 status (20:26)

Xenia stage A launched at 20:24 and aborted at once: the desktop session is
locked (foreground window = Windows lock screen), so the focus guard refused to
send menu inputs. Xenia stages wait for an unlocked interactive session
(`robotron/xenia_night_20260914.ps1` runs A then B once MAME is idle). The
576-game fresh-process proxy confirmation was started instead at 20:26
(`robotron_ai/logs/firealt_confirm_20260914`), with a FIRE_ALT_R 100/250 sweep
queued behind it.

### Stage 2 interim (20:56, 121 valid games/arm of 576, fresh seeds, fresh process per game, LAB_LAG=0.7)

NET delta **+0.316, whole-game bootstrap 95% CI [+0.267, +0.365]**; candidate
deaths/wave 0.834, score/wave 28,717, mean max wave 26.0 (W26 cap). Reproduces
stage 1 on independent seeds and the newer calibration. Final numbers below
when the batch completes.

### Radius sweep (fresh-process runner, 144 games/arm each with its own base, LAB_LAG=0.7; 20:27-21:40)

| FIRE_ALT_R | base deaths/wave | candidate deaths/wave | candidate score/wave | NET delta (95% CI) |
|---:|---:|---:|---:|---|
| 100 px | 1.081 | 0.911 | 28,596 | +0.204 [+0.157, +0.249] |
| 160 px (default; stage-2 interim) | — | 0.834 | 28,717 | +0.316 [+0.267, +0.365] |
| 250 px | 1.091 | 0.787 | 28,285 | +0.342 [+0.293, +0.390] |

Monotone in the radius: the second shot is free, so a farther second target
still pays. 400 px and unlimited (2000 px) queued next. (These two batches ran
concurrently with the 576-game confirmation because a stale completion line
satisfied the waiter; all 288 games in each were valid.)

### Stage 2 final (22:10, 576 valid games/arm, fresh seeds, fresh process per game, LAB_LAG=0.7; 3 invalid episodes replaced)

| arm | mean max wave (W26 cap) | deaths/wave W5-25 | score/wave | NET lives/wave |
|---|---:|---:|---:|---:|
| base | 22.60 | 1.097 | 27,430 | +0.000 |
| fire_alt (R=160) | 26.30 | 0.828 | 28,493 | +0.311 |

**NET delta +0.311, whole-game bootstrap 95% CI [+0.289, +0.333].** Report:
`robotron_ai/logs/firealt_confirm_20260914/report.json`. Confirmed on the
W5-25 proxy at the project's highest power. Not yet a late-game or
real-vision claim: Xenia stages A and B are still pending the unlocked desktop.

### Radius sweep, part 2 (22:26-23:17, same runner, 144 games/arm each)

| FIRE_ALT_R | base deaths/wave | candidate deaths/wave | candidate score/wave | NET delta (95% CI) |
|---:|---:|---:|---:|---|
| 400 px | 1.106 | 0.775 | 28,348 | +0.379 [+0.339, +0.419] |
| 2000 px (unlimited) | 1.094 | 0.765 | 28,360 | +0.370 [+0.324, +0.415] |

Plateau from ~400 px: 100 → +0.204, 160 → +0.311, 250 → +0.342, 400 → +0.379,
unlimited → +0.370 (the last three overlap). The second shot is free at any
range, so the production default should be 400 px when the knob is promoted.

### Stage A interim — Xenia exact state, W25-40 (2026-09-15 01:30, 4 games/arm of 8, interleaved, W40 cap)

| arm | deaths/wave W25-40 | game-bootstrap 95% CI | score/wave | rescues/wave | games reaching W40 |
|---|---:|---|---:|---:|---|
| base | 1.200 | [1.146, 1.250] | 28,531 | 8.23 | 3 / 4 (one game over at W33) |
| fire_alt (R=160) | 0.766 | [0.656, 0.891] | 28,914 | 8.23 | 4 / 4 |

Per game, late-band deaths/wave: base 1.11, 1.19, 1.25, 1.25; fire_alt 0.75,
0.62, 0.94, 0.75. Delta +0.43 deaths/wave (p < 0.001 on the harness's game
bootstrap); income and rescues unchanged. The XBLA port runs the arcade fire
task unchanged, and the effect in the repeat band is twice the −0.15 to −0.20
the 2026-09-08 Monte Carlo said makes W100 likely. (A first attempt at 23:19
was discarded: a custom wave-log path hid the W40 cap from the harness's
emulator-restart check, so games 2-6 attached to a finished game and quit.)

### Stage A final — Xenia exact state (2026-09-15 03:28, 8 games/arm, interleaved, W40 cap)

| band | base deaths/wave (95% CI) | fire_alt deaths/wave (95% CI) | delta | score/wave base / fire_alt |
|---|---|---|---|---|
| W25-40 | 1.217 [1.139, 1.289] | 0.758 [0.672, 0.852] | +0.46, p < 0.001 | 29,074 / 29,497 |
| W5-25 | 0.780 [0.685, 0.863] | 0.429 [0.369, 0.494] | +0.35, p < 0.001 | 29,811 / 30,234 |

Per game: base max wave [33, 40 x7], deaths [28, 33, 30, 36, 33, 37, 34, 36];
fire_alt max wave [40 x8], deaths [22, 20, 25, 20, 18, 23, 22, 15]. Rescues
per wave 8.27 vs 8.18. The perfect-information planner's late band goes from
~1.2 to ~0.76 deaths/wave with the same income: the mechanism transfers to the
Xbox game code, and the late-band effect is roughly twice what the Monte Carlo
says makes W100 likely. Stage B (real vision, 12/arm, W40 cap) started 03:28;
stage C (uncapped vision depth, R=400) is chained behind it.

### Stage B interim — Xenia REAL VISION, shipping config (2026-09-15 06:03, 6 games/arm of 12, yolo6, eye-sync, W40 cap)

| band | base deaths/wave (95% CI) | fire_alt deaths/wave (95% CI) | delta | score/wave base / fire_alt |
|---|---|---|---|---|
| W5-25 | 1.075 [1.019, 1.122] | 0.810 [0.643, 0.944] | +0.27, p = 0.004 | 27,749 / 29,523 |
| W25-40 | 1.387 [1.182, 1.667] | 1.042 [0.979, 1.115] | +0.35, p = 0.021 | 28,716 / 28,340 |

Per game: base max wave [40, 35, 20, 18, 33, 23], deaths [44, 36, 18, 16, 34,
20]; fire_alt max wave [40, 40, 40, 40, 34, 40], deaths [33, 28, 35, 34, 30,
30]. Mean max wave 28.2 vs 39.0 (p = 0.005). The first real-vision evidence:
the effect survives the detector, the coaster and the ~2-tick loop latency.

### Stage B final — Xenia REAL VISION (2026-09-15 08:34, 12 games/arm, shipping config, W40 cap)

Recomputed on the exact stage-B window (03:27:50-08:34; the night script's own
stats used a PowerShell 5.1 `%s` timestamp that runs seven hours early and so
also swept in the stage-A games).

| band | base deaths/wave (95% CI) | fire_alt deaths/wave (95% CI) | delta (95% CI) | score/wave base / fire_alt |
|---|---|---|---|---|
| W5-25 | 1.063 [0.979, 1.133] | 0.806 [0.706, 0.901] | +0.257 [+0.132, +0.387] | 27,976 / 29,340 |
| W25-40 | 1.328 [1.219, 1.485] | 1.104 [1.040, 1.172] | +0.225 [+0.094, +0.396] | 27,413 / 28,527 |

Max wave per game: base [18, 18, 18, 20, 23, 24, 31, 33, 33, 35, 39, 40];
fire_alt [34, 37, 40, 40, 40, 40, 40, 40, 40, 40, 40, 40]. The full ladder
holds on real vision: proxy screen, 576-game fresh confirmation, exact-state
late band, real-vision W5-25 and W25-40.

### Stage C — uncapped real vision, FIRE_ALT_R=400 (2026-09-15 08:35-, 3 games/arm, interleaved, no wave cap)

| game | arm | max wave | score | deaths | W41+ deaths/wave |
|---|---|---:|---:|---:|---:|
| 1 | base | 31 | 788,525 | 30 | — |
| 2 | fire_alt | **117** | 3,135,375 | 114 | 1.04 |
| 3 | fire_alt | **90** | 2,473,400 | 91 | 1.24 |
| 4 | base | 16 | 399,025 | 17 | — |
| 5 | base | 31 | 799,975 | 30 | — |
| 6 | fire_alt | **198** | 5,419,750 | 193 | 1.02 |

### Console round 15 (Eric, 2026-09-15, 10 games, R=400, trace on)

Waves 20, 16, 9, 21, 13, 17, 20, 18, 19, 22: mean 17.5 vs 12.0 in round 14
(five games) on the same rig. Fire direction changed on 95.8% of ticks, so
alternation was active. Smaller lift than the emulator's because the console
carries 1-2 extra ticks of loop latency (reversals +3/+4 vs +2); see
STATE_OF_PLAY section 0. Per band vs the emulator's alternation games:
deaths/wave W5-9 1.04 vs 0.64, W10-16 1.16 vs 0.79, W17-22 1.33 vs 0.88.

Final (11:40): fire_alt max waves 117 / 90 / 198, base 31 / 16 / 31. Before
this the vision bot's record was W60 (2026-09-06). Above W40 the fire_alt bot
runs 1.02-1.24 deaths/wave against ~27.3-28.3k points/wave (~1.1 lives bought
per wave): break-even to slightly positive, the regime the memory-input
champion rides to W100-158. The W198 game is the deepest any bot in this
project has reached on any input. Promoted 2026-09-15: default ON for the
vision path, radius 400 px.
