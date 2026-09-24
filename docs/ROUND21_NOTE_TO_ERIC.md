# Round 21 — note to Eric (2026-09-24)

Eric,

Round 20 confirms it. Waves 22, 51, 49, 40, 33, 49, 64, 31, 32, 34: mean
**40.5**, and **wave 64** is the console record by twelve. Against round 19's
38.1 the two rounds are statistically the same run (t = 0.46), so 38 to 40 is
the console's level on this build, not a lucky draw. Put the twenty games
together and the low-latency capture mode moved the console from 29.8 to
39.3, about ten waves. The series since the adapters came out reads 16.6,
29.8, 39.3.

Thanks for the note on the builds. Understood that nothing from a prior
build survives; we will not ask for re-runs on old folders again, and any
check we need will come as a script with instructions for the next build.

## The reversal figure, one more time

Round 20 shows the response at two ticks in 25% of clean reversals (round 19
39%, round 18 5%). Pooled over the two low-latency rounds that is about 30%
against 5%, so the 15 ms is real and it held. The "seen by 167 ms" line will
keep printing 167 until something shifts by a whole tick; from the next build
the report also prints a phase-corrected estimate on its own line, so a
sub-tick change shows without reading the split. On your two traces it reads
121 ms for round 20 and 119 for round 19, and round 18's split works out to
about 138, so the backend took about 18 ms off the loop.

The "unresolved" count (33 of 90 this round, 30 of 66 last) is the game, not
the rig: those are reversals where the player never got moving because a
death freeze or a wave start was in the way, or the player was already
standing still. Two rounds on the same build agree, so it is a fixed
property of how the report filters events, not a regression.

## What the life economy says

This is the part that decides what we do next. By the economy, the console
dies 1.07 times a wave and buys 1.02 lives a wave (score divided by 25,000).
Round 18 was 1.08 and 0.98, round 19 was 1.10 and 1.03. The console is at
break-even: each wave it earns one man and loses one, and the game ends when
the three starting men have leaked out at the difference. That difference is
0.05 to 0.10 a wave, which is 30 to 60 waves, which is exactly where every
game of the last three rounds has ended (11 to 64).

The latency cut did not change the death rate. It moved the margin by a few
hundredths, and at break-even a few hundredths is ten waves. The emulator
earns 1.1 men a wave and loses 0.8, a margin of plus 0.3, which is why it
banks men and runs to wave 100 and beyond. To get the console there we need
the margin to flip: either 2,500 more points a wave, or a tenth of a death
fewer per wave. Nothing left in the hardware budget converts into either.
Card 17 ms, pad 11 ms, and the 360's own frame pipeline is the rest.

Where the deaths are: enforcer bullets are now the top killer (59), grunts
47, tank shells 35, cruise missiles 25. Deaths within 50 px of a wall rose to
46% from 37%. Unseen killers held at 27%.

## Round 21

No round needed until the next build. Twenty games at this latency is a
solid baseline, and another ten on the same build would only tighten a
number we already trust. The next build changes how the bot plays, not what
it sees, and it will come with a note on what to watch for.

If you want to keep the rig busy in the meantime, the same flags as rounds
19 and 20 still apply and any games add to the baseline:

```
--capture-backend magewell --magewell-mode lowlatency --capture-res 1280x720
```
