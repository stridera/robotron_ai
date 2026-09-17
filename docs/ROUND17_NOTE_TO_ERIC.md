# Round 17 — note to Eric (2026-09-16)

Eric,

Both round-16 sessions came through cleanly (twenty games, two full traces,
240 death windows), and together they narrow the problem to the control
hardware.

## What round 16 showed

**Results.** MJPG session: waves 11, 14, 28, 12, 13, 9, 9, 19, 22, 23 (mean
16.0, a new console record at 28). YUY2 session: 19, 20, 13, 19, 17, 22, 9,
13, 13, 17 (mean 16.2). Round 15 was 17.5. Deaths per wave in every band are
the same as round 15 within noise.

**Two questions answered.**

1. *Does the corrected forward prediction help?* No. Pinning it at 2.5 changed
   nothing in any band. That agrees with an older emulator-lab result: a
   prediction can put the bot's own position right, but it cannot give back
   the reaction time the delay takes. Round 17 goes back to the validated
   setting; the delay measurement stays in the report as a diagnostic.
2. *Is the capture format part of the delay?* Not measurably. With YUY2 the
   reversal count was still 3 ticks in 64% of cases and 4 in 9% (MJPG: 57% and
   29%), the card delivered the same 54 unique frames a second, and play was
   the same. One caveat: the capture library reports the same converted
   output format in both logs, so I cannot prove from the logs that the card
   actually switched; the identical numbers make it unlikely the format
   matters either way.

So the extra one to two ticks of delay are between the Arduino's pins and
the picture: the two X-Arcade adapters, or the console's own output path.
Nothing in the bot's software can remove it, and round 16 shows it cannot be
compensated either.

## A test that needs no soldering: time the controller chain by itself

The reversal count is end to end (command to pixels), so it cannot say how
much is the controller side and how much is the console's output and the
capture. This build has a tool that measures the controller side alone:

1. Unplug the X-Arcade Xbox 360 adapter from the console and plug its USB
   output into the PC instead (the adapter kit supports PC; Windows should
   show it under "Set up USB game controllers").
2. Leave the Arduino box connected as usual, and run:

```
.venv\Scripts\python -m robotron_ai.tools.measure_control_latency --port COM3
```

It presses A through your box forty times, watches the controller state as
fast as Windows reports it, and prints the press and release delays in
milliseconds. A direct wired pad would read under 10 ms. If this reads 60 ms
or more, the adapters are the delay and the pad wiring below is the fix. If it
reads 10-20 ms, the delay is in the console's video output or the capture
card, and no controller change will help. Either way it settles the question
in five minutes, before anyone picks up a soldering iron.

### Result (Eric ran it the same evening)

Press and release both land at either ~19.5 ms or ~39.5 ms, nothing in
between, median 39 ms over 39 trials. That is an adapter chain polling at
50 Hz: a press is picked up at the next 20 ms poll or the one after. So the
controller side costs about 30 ms more than a direct pad would (a wired 360
pad reports every 4-8 ms). Real, but only about half a tick of the extra one
to two ticks. **The larger part of the delay is on the video side**: the
console's own input-to-output pipeline plus the capture card's frame latency,
which the emulator's window capture does not pay. (One curiosity for later:
on the PC the adapter reported our "A" line as the X button; on the console
the bot's fire directions clearly work, so the adapter's console mapping
differs from its PC mapping. Not a problem, just noted.)

## What I think the next step is

Given that, the direct-pad wiring would recover about 30 ms and is now the
second thing to try, not the first. The first is free: **set the Xbox 360's
display output to 720p** (System settings, Console settings, Display, HDTV
settings, 720p) and run with `--capture-res 1280x720`. The game renders at
720p; at 1080p the console's hardware scaler is in the path and typically
adds a frame, and the capture card then has 2.25x the pixels to move and we
downscale them back. If the reversal count drops, that was it. It is also
worth a look in the Magewell control panel for a low-latency or
"frame vs field" setting; the default DirectShow path can buffer a frame.


After that, taking the two adapters out of the loop (the same optoisolators
wired directly across a wired Xbox 360 pad's D-pad and A/B/X/Y contacts)
buys the remaining ~30 ms. Your call on the soldering; the reversal count on
every run will show whether each change moved the delay.

## What is different in this build

- The forward prediction is back on its validated setting; do not pass
  `--player-lead` this time.
- The death that ends each game is now counted, so the GAME OVER line and
  the reports match the lives actually lost (your round-16 observation was
  right: the last life has no icon to drop, so it was never counted).
- Everything else is the round-16 build.

## What to run

Same as always: GitHub page, green **Code** button, **Download ZIP**
(`main`, also tagged `round-17`), extract into a fresh `C:\robotronai17`,
rename the folder to `robotron_ai`, venv per the README, then:

```
.venv\Scripts\python -m robotron_ai --mode hardware --device 0 --port COM3 --loop --games 10 --visualize --capture-backend dshow --capture-fourcc MJPG --capture-res 1920x1080
```

If you build the direct-pad path, run exactly this and send the folder; the
first line of the analysis will say whether the delay moved.

## Your notes

- **Wave 13 electrode in game 2:** the trace has it (death 11 of that game):
  the electrode was 23 px away and the last six headings were E, SE, N, SW,
  N, N. Same shape as the round-15 one: the heading changing every decision
  while the previous command is still in flight. That is the delay again,
  not a rule the bot lacks.
- **Final death not counted:** fixed, see above.
- **Script exits cleanly:** confirmed, thanks.

Strider
