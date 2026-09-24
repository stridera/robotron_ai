# Round 20 — note to Eric (2026-09-23)

Eric,

Round 19 is the console's best round by a distance. Waves 35, 44, 52, 40,
35, 41, 19, 22, 51, 42: mean **38.1** against 29.8 in round 18, and **wave 52**
is the record by thirteen waves, with a second game at 51. Score per wave
stayed at 25.7k (25.0k last round), so the extra depth came from dying less,
not earning more, which is exactly what shaving latency should buy.

## What the bench said, and why the card question is closed

Your three loopback runs came back with the new CARD-ONLY line, which is the
card's own clock from the first line of a frame arriving to our program
holding the whole frame. Low-latency mode: **16.9 ms**, every one of the forty
trials between 16.9 and 17.0. Normal mode: 28.1. A 60 Hz frame takes 16.7 ms
to scan out, so 16.9 is the floor for any card that delivers complete
frames. There is no lower-latency card to buy; the Magewell in this mode is
at the physical limit.

The 36 ms we had been quoting was never the console's number. On the bench
the source is a Windows monitor output, and Windows holds each flip until the
next refresh before the picture even starts down the cable. That is 8 to
25 ms the Xbox does not pay. The console's real capture cost is the 17 ms
above plus a millisecond or two of handling.

Trial 1 of every earlier run was invalid: calibration left the window white
and the first flip was to white, so it measured nothing. Fixed in this build,
which is why the first trial now looks like the others.

## The reversal figure that did not move

The trace prints "seen by 167 ms, not yet at 110" against 171 / 111 last
round, which looks like nothing changed. It is the ruler, not the loop. Those
two numbers are the times of the frames on either side of the response, and
frames land on the 57 ms tick grid, so a change smaller than a tick cannot
move them. The finer signal is which tick the response shows up in: last
round it was two ticks in 5% of clean reversals, this round **39%**. That is
about 15 ms of real improvement, the card's 11 plus the MJPG decode that no
longer runs.

The same problem applies to the emulator's "117 ms", which sits on a 67 ms
grid. The honest statement is that the console-to-emulator gap has never
been measured to better than about 50 ms. The next build of the report will
print a phase-corrected estimate, and we will re-run it over the emulator
traces.

One thing to check if you still have the round 18 hardware report folder:
run the current report on it. Round 19 shows 30 of 66 clean reversals as
"unresolved" (the player never got moving in the new direction). They are
spread evenly over all eight directions, so it is not the pad; a third sit
next to a logged death and the HUD misses about half of deaths in deep games,
and the rest are players already standing still when the command went out.
Round 18's write-up did not record that count, so we cannot say whether it is
new. Running the report on the old folder answers it in one command.

## Where that leaves the budget

Card 17, pad 11, and the rest is inside the Xbox. The 360 port runs vsynced,
which means each finished frame waits one to two refreshes before it goes
out, and the pad is read once per frame. That is 25 to 45 ms nobody outside
the console can touch. Nothing on the hardware side is left to buy.

## Round 20

Same build, same flags as round 19:

```
--capture-backend magewell --magewell-mode lowlatency --capture-res 1280x720
```

Ten games for a second sample at this latency. The question round 20 answers
is whether 38 is the new level or round 19 was a good draw; the spread was
19 to 52, so one more sample matters. The trace with the `capture` block in
`trace_summary.json` is what we want back, as before.

After that the work moves off the hardware: the income gap (25.7k a wave
against the emulator's 27 to 28k, which is one extra man every ten waves)
and making the bot play with the latency it has rather than against it.
