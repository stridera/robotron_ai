# Running the experiments yourself (handoff, 2026-09-30)

Eric,

From here the console work runs on your machine. You run sessions, change
settings, and judge the results with the tools in this build; I stay on for
analysis of anything you send and for code changes you ask for. This page is
everything you need to do that without me: what the bot is, how to run a fair
experiment, where the knobs are, and which changes are worth your time.

## 1. Where things stand

Rounds 19 and 20 on the low-latency capture backend: twenty games, mean
**39.3**, record **W64**, and the two rounds are statistically the same run.
The series since the adapters came out reads 16.6, 29.8, 39.3.

The hardware budget is spent. The card's own cost is 16.9 ms, which is one
60 Hz scan-out and the floor for any card; the pad is 11 ms; the rest is the
Xbox 360's own frame pipeline, which nobody outside the console can touch.

What decides the game now is the life economy. By it the console buys
1.02 men a wave (score divided by 25,000) and loses 1.07: break-even, so the
three starting men leak out at 0.05-0.10 a wave, which is 30-60 waves, which
is exactly where every game of the last three rounds ended (11 to 64). The
emulator, same code, buys 1.1 and loses 0.8, banks men, and runs to 100 and
beyond. **Wave 100 on the console needs the margin at -0.03 or better:
either 2,500 more points a wave, or a tenth of a death fewer per wave.** At
break-even a few hundredths is ten waves, so small effects matter here,
which is why the protocol below insists on sample sizes.

Where the deaths are (round 20): enforcer bullets 59, grunts 47, tank shells
35, cruise missiles 25; 46% within 50 px of a wall (up from 37%); 27% with
no visible killer.

## 2. What the bot is, in one paragraph

Every decision tick (57 ms on your rig) the bot takes the newest frame from
the card, runs the YOLO detector on it, extrapolates every enemy by the
frame's age, and asks the clearance planner for the safest move over a short
horizon while the FSM chooses what to shoot at. The move and fire directions
go out as one serial byte to the Arduino, which presses the pad. The HUD
reader keeps score, wave and lives from the picture, and the trace writes
every decision plus a few seconds of frames before each death. All of that
is `python -m robotron_ai --mode hardware ...`; the README lists every flag.

## 3. How to run an experiment that means something

1. **Put sessions outside the build folder.** You delete each build before
   taking the next, so add `--sessions-dir C:\robotron_sessions` (any folder
   you keep) to every run. Each session then lands in its own folder there,
   `<date>_<tag>`, and nothing is lost when a build goes.
2. **Tag every session.** `--tag base`, `--tag lag10`, whatever names the
   arm. The tag is in the folder name, in `report.json`, and in the wave
   log. Rounds 19 and 20 are your first `base`.
3. **Ten games an arm, minimum.** Game-to-game spread on the console is
   about twelve waves at this level, so ten games resolve a change of
   roughly eight waves in the mean; twenty resolve five. For the economy the
   tool also reports NET men per wave, which is less noisy than max wave
   and is the number that has to move.
4. **Alternate arms across sessions**: base, candidate, base, candidate.
   The console drifts, and alternating cancels it. Never compare tonight's
   candidate with last week's base alone.
5. **Change one thing.** The comparison tool prints what differed between
   two arms; if it lists two changes, the result belongs to neither.
6. **Judge it with the tool**, not by eye:

   ```
   .venv\Scripts\python -m robotron_ai.tools.compare_sessions C:\robotron_sessions\*_base C:\robotron_sessions\*_lag10
   ```

   Sessions with the same tag pool into one arm; the first arm named is the
   baseline. It prints per arm: games, mean and median max wave, deaths per
   wave by the life economy, points per wave, NET men per wave; and per
   comparison the difference in mean wave and in NET, each with a 95%
   interval and a p-value, plus the knobs and settings that differed.
   **Believe an interval that excludes zero; treat anything else as "not
   yet".** Add `--trace` for the loop latency in milliseconds (slow; reads
   every decision).
7. **Keep the base arm current.** When a change is adopted it becomes the
   new base and the next candidate runs against it.

When you want my read on something, zip the session folders in question
(`report.json`, `decisions.jsonl`, `trace_summary.json` and
`rig_calibration.json` are what I use; the `deaths/` frames are 500 MB and
only matter when the question is about specific deaths) and send them with
the console text.

The base command, as of this build:

```
.venv\Scripts\python -m robotron_ai --mode hardware --device 0 --port COM4 --loop --games 10 --visualize --capture-backend magewell --magewell-mode lowlatency --capture-res 1280x720 --sessions-dir C:\robotron_sessions --tag base
```

## 4. Where the knobs are

Three kinds of setting, all recorded in `report.json`:

- **Command-line flags** (README table). The ones that matter for play:
  `--lag-ticks` (how far ahead enemies are extrapolated, in ticks),
  `--player-lead` (the bot's own forward-prediction; measured null on the
  console in round 16, leave it), `--hz` and `--eye-sync` (decision
  cadence), `--fire-alt` / `--no-fire-alt`, `--conf` (detector confidence
  floor), and the capture flags.
- **Engine knobs**: planner and FSM constants read from the environment.
  See them all with

  ```
  .venv\Scripts\python -m robotron_ai --mode hardware --list-knobs
  ```

  and set one for a run with `--knob NAME=VALUE` (repeatable), or put a
  `"knobs": {...}` block in a `--config` file. The table shows the engine
  default, the value in force on the console, and a `*` on anything pinned.
  Two traps the table also warns about: pinning one planner margin switches
  the console's default for the *other* off (pin both), and pinning
  `VSEARCH_FIRE_ALT` drops the fire-alt radius from 400 to 160 unless you
  pin `VSEARCH_FIRE_ALT_R` as well.
- **A config file** for the settings you always use, so the command line
  stays short:

  ```json
  {"mode": "hardware", "device": 0, "port": "COM4", "loop": true, "games": 10,
   "visualize": true, "capture_backend": "magewell", "magewell_mode": "lowlatency",
   "capture_res": "1280x720", "sessions_dir": "C:\\robotron_sessions", "knobs": {}}
  ```

  `python -m robotron_ai --config eric.json --tag base`.

Knobs that are already closed (measured, lost or null, with the numbers)
are listed in `STATE_OF_PLAY.md` section 5g. Re-running one of those is
only worth it if you have a reason the console should differ from where it
was measured; the console's longer loop is such a reason for the latency
sensitive ones, which is what the list in section 6 is.

## 5. Reading a session

```
.venv\Scripts\python -m robotron_ai.trace_report C:\robotron_sessions\<folder> --waves 40
```

Lines that matter, top to bottom: the tick length and rate; the player
speed ratio (should be ~1.03; anything else means the controller or the
scale is off); the **reversal response**, where the phase-corrected
`estimate` line is the loop latency in milliseconds (~120 on rounds 19-20;
the two bracket figures sit on the tick grid and only move by whole ticks);
the games table with HUD deaths against lives bought (the HUD misses deaths
while the lives row is full, the economy figure is the true total); the
per-wave table (deaths there are lower bounds in deep games); and the
killers list. The GAME OVER line in the console output prints both death
figures too.

## 6. What is worth trying, in order

Each entry says what the change does, why the console might differ from
where it was last measured, and my honest prior. The number to watch is NET
men per wave; a change of +0.05 there is the difference between wave 40 and
wave 100.

1. **Entity lead for a longer loop**: `--lag-ticks 1.0`, then `1.3`. The
   planner extrapolates every enemy forward by this many ticks to undo the
   picture's age. 0.7 was tuned on the emulator, whose picture is fresher
   than yours; the console's optimum should sit higher. This is different
   from `--player-lead`, which was null. Prior: moderate.
2. **Planner margins for a longer loop**:
   `--knob VSEARCH_CLEAR_DANGER=24 --knob VSEARCH_CLEAR_MARGIN=14` (the
   console runs 21/12). The margins are how much positional uncertainty the
   planner allows for, and uncertainty grows with latency. On the emulator
   1.3x margins lost, but its uncertainty is smaller. Try one step up; if
   it loses, one step down (18/10) so the direction is known. Enforcer
   bullets and near-wall deaths are the growing killers, and both are what
   margins are for. Prior: low-moderate.
3. **Faster decisions**: `--eye-sync 40` (the loop then settles near 24 Hz;
   the planner rescales its own kinematics to the measured cadence, the
   `[tick] sustained cadence` line). A shorter tick reacts to a new picture
   sooner and quantises commands finer. 30 Hz lost on the emulator where
   the picture's age, not the cadence, was the cost. Prior: low, but it
   costs one session and nothing else.
4. **Income**: 25.4k a wave against the emulator's 27-28k is one man every
   ten waves, and would close the gap on its own. The rescue pull is
   `--knob FSM_BRAIN_RESCUE_MULT=1.3` (higher = the bot goes further for
   civilians; it lost on the emulator, where income was not the problem).
   Watch points per wave and deaths per wave together: rescues that cost
   men are a net loss. Prior: low-moderate.
5. **Fire-alt radius**: `--knob VSEARCH_FIRE_ALT=1 --knob VSEARCH_FIRE_ALT_R=250`
   against the current 400. The proxy's plateau was 250-400; on the console
   a nearer second target means less time with the laser pointed away from
   the thing that kills you. Prior: low.
6. **Detector confidence**: `--conf 0.25` and `0.35` against 0.30. Never
   tuned on console frames. Watch the killer-unseen share in the report: if
   it drops with 0.25 without the wall share rising, the detector was
   missing things. Prior: low.

Things I would not spend sessions on: `--player-lead` (null on the console
at 1.5 vs 2.5), `--imgsz 640` (breaks classification, measured), the
closed knobs in 5g, and anything on the capture side (the card is at its
floor). Two things need me rather than a flag: new detector weights (needs
your death frames labelled), and planner or FSM logic changes, which I would
first screen on the MAME stand-in that reproduces your console's latency.

## 7. If you want a faster lab than the console

The emulator path in the README (`--mode xenia --input yolo`) runs the same
vision bot on Xenia at your desk, and the MAME stand-in on my side plays
sixteen games in parallel at the console's measured latency. Neither is
needed for the list above; the console at ten games a session is the true
measure, and every result you get there is worth more than the same result
anywhere else.

Strider
