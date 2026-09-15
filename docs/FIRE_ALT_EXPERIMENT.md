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
