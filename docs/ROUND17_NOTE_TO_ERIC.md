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
second thing to try, not the first. The first is another five-minute
measurement, this time of the video side, and it needs only a spare HDMI
cable. (Strider confirms the console already outputs 720p, so the console's
scaler is not in the path; the card is asked for 1080p and upscales, and we
scale back down. Whether that costs anything is exactly what this measures.)

### Time the capture chain by itself

1. Run an HDMI cable from the PC's video card straight into the capture
   card, in place of the console. Windows will show the card as a second
   monitor (extend, do not duplicate).
2. Find its number, then run the test with the usual capture flags:

```
.venv\Scripts\python -m robotron_ai.tools.measure_capture_latency --list
.venv\Scripts\python -m robotron_ai.tools.measure_capture_latency --monitor 2 --device 0 --capture-backend dshow --capture-fourcc MJPG --capture-res 1920x1080
```

It opens a full-screen window on that monitor, flips it black and white
forty times, and reports how long each flip took to arrive two ways at once:
through the card, with the bot's own capture settings, and through a direct
read of the screen, which is what the emulator's window capture amounts to.
The difference between the two is what the console picture pays on the
video side over the emulator: scan-out, the card, the decode, and any driver
buffering. Then run it two or three more times with different flags, since
this is now a five-minute comparison instead of a ten-game session:

```
... --capture-fourcc MJPG --capture-res 1280x720
... --capture-fourcc YUY2 --capture-res 1280x720
```

With the controller number from tonight (~30 ms) and this one, the console's
extra 70-130 ms is fully accounted for: whatever is left over is the
console's own input-to-picture pipeline, which nothing on our side can
change. And if one capture setting is a frame faster than another, that is a
free win we take immediately.

### Result (Eric, same evening, MJPG 1920x1080)

Screen read 4 ms median; card 41 ms median (p10 36, p90 52); difference
**37.5 ms**, about two and a quarter 60 Hz frames: one frame of scan-out,
one frame in the card or its driver, a few ms of MJPG decode. The card
delivered a steady 60 frames a second. So the video side costs ~38 ms and
the controller side ~30 ms, ~68 ms together, just over one decision tick,
which is exactly what the reversal count shows (3 ticks in most cases, 4 in
a quarter). The console's own pipeline is therefore no slower than the
emulator's; the whole gap is the two paths we can touch. The MAME proxy
agrees: run with one extra tick of actuation delay it reproduces the console
almost exactly (baseline 13.0 waves against your round-14 12; fire
alternation 19.4 against your rounds 15-16 at 16-17.5; deaths per wave 1.15
against your 1.15). That gives us a console stand-in on the desk.

To get the loop back to the emulator's 2 ticks we need to shave ~40 ms.
The direct pad wiring is ~30 of it; the other capture settings (1280x720,
YUY2) may be worth a frame, which is the remaining 10-17. Please run those
two when you can; they decide whether the pad mod alone is enough.

### The other two settings (Eric, same evening)

| setting | hdmi − screen, median | p10 | p90 |
|---|---:|---:|---:|
| MJPG 1920x1080 (what every round so far used) | 37.5 ms | 30.4 | 47.8 |
| MJPG 1280x720 | 33.1 ms | 27.0 | 41.1 |
| **YUY2 1280x720** | **30.3 ms** | 23.4 | 36.7 |

**Withdrawn the same night.** Latency is only half of frame age; the other
half is how often a *new* frame arrives, and a flashing white square cannot
measure that (it looks identical whether the card sends a fresh frame or
repeats one). The capture probe measured exactly that months ago, and its
table rules 720p out:

| setting | unique frames/s | delivered/s |
|---|---:|---:|
| **dshow MJPG 1920x1080** | **50.0** | 59.6 |
| dshow default 1920x1080 | 45.3 | 59.6 |
| dshow default 1280x720 | 22.2 | 59.8 |
| dshow YUY2 1920x1080 | 15.3 | 59.6 |
| dshow YUY2 1280x720, 30 fps | 9.3 | 29.9 |

The probe prints only its top 12 of 36 combinations, and MJPG 1280x720 and
YUY2 1280x720 at the default rate are not among them: both are below 9.3
unique frames a second. The card sends 60 frames a second in every mode, but
at 720p most of them repeat. Average frame age is about half the gap between
new frames, so 50 a second costs 10 ms while 9 a second costs 54 ms. Trading
4-7 ms of pipeline delay for 12-44 ms of staleness is a large loss, and at
9 unique frames a second the bot would not even get a new picture every
decision. **Round 18 keeps MJPG 1920x1080.**

One more caveat on those three runs: the card reported the same pixel-format
string in all three, as it did in round 16, so the YUY2 request probably
never took effect. What actually changed was the resolution, and 30.3 vs
33.1 ms is within the run-to-run spread. Read it as "720p is ~4 ms faster
and much staler", not as a format result.

That leaves the pad wiring as the whole fix, and it is built: the Uno and
optoisolators now go straight onto a wired VOYEE 360 pad, bench-verified at
**9 ms** press-to-report against 39 ms through the two X-Arcade adapters.
That is the ~30 ms, and it is the only change in round 18.

### The capture tool now measures both halves

Rather than take the old probe's word for it, `measure_capture_latency` has
been extended: after the flips it animates moving shapes with a colour-cycling
block at the centre, painted at the monitor's refresh rate, and counts the
frames that actually changed down both paths at once. The screen read shows
what the PC put out and the card's count shows what survived, so it separates
"the card repeated a frame" from "the source never made one". Its change test
now reduces both paths to a fixed-size patch, so 720p is no longer penalised
for having fewer pixels the way the old probe's fixed grid was.

So if we want to revisit 720p, the loopback run answers it in five minutes
rather than a ten-game session, and no YouTube clip is needed: the tool is its
own source and reports the paint rate it achieved. Worth doing at some point,
but it is not on the round-18 path.

Meanwhile on my side: the MAME lab can apply the bot's commands late on
purpose (it already runs at one tick late as its standard calibration, and
the July cost curve showed each extra tick roughly halves the depth: 42 ->
18 -> 8 waves). Running it at the console's two-to-three ticks gives a
console stand-in on the desk at 16 games in parallel, so latency-tolerant
play can be searched there instead of one ten-game round at a time.

## What is different in this build

- The forward prediction is back on its validated setting; do not pass
  `--player-lead` this time.
- The death that ends each game is now counted, so the GAME OVER line and
  the reports match the lives actually lost (your round-16 observation was
  right: the last life has no icon to drop, so it was never counted).
- Everything else is the round-16 build.

## What to run

The capture tool is new, so this is a fresh download: GitHub page, green
**Code** button, **Download ZIP** (`main`), extract into a fresh
`C:\robotronai17`, rename the folder to `robotron_ai`, venv per the README.
The capture tests are done (above) and they change nothing: the capture flags
stay exactly as they have been for every round. Round 18 is ten games with
the direct-wired pad in place of the two adapters, and that is the only
change:

```
.venv\Scripts\python -m robotron_ai --mode hardware --device 0 --port COM3 --loop --games 10 --visualize --capture-backend dshow --capture-fourcc MJPG --capture-res 1920x1080
```

One change at a time, so the reversal count on the first line of the
analysis attributes cleanly to the pad.

Send the hardware_report folder as usual; the first line of the analysis
will say whether the delay moved.

## Your notes

- **Wave 13 electrode in game 2:** the trace has it (death 11 of that game):
  the electrode was 23 px away and the last six headings were E, SE, N, SW,
  N, N. Same shape as the round-15 one: the heading changing every decision
  while the previous command is still in flight. That is the delay again,
  not a rule the bot lacks.
- **Final death not counted:** fixed, see above.
- **Script exits cleanly:** confirmed, thanks.

Strider
