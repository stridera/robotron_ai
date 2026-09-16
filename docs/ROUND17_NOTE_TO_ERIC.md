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

## What I think the next step is

The way to find out, and most likely the fix, is to take the two adapters out
of the loop: the same optoisolators, wired directly across a wired Xbox 360
pad's D-pad and A/B/X/Y contacts. A wired pad reports at 4-8 ms. If the
reversal count in the next trace drops from 3 to 2, that was the delay, and
the console should start playing like the emulator, which reached waves 117
and 198 this week. If it stays at 3, the delay is in the console's own video
output and we tune the bot around it instead.

I know that is a soldering job and your call. If you would rather test before
building, the reversal count is measured on every run, so a single game on any
alternative control path (even a different adapter) would answer it.

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
