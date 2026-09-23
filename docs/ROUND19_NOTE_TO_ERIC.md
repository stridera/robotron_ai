# Round 19 — note to Eric (2026-09-22)

Eric,

Round 18 is the biggest single step the console has taken. Waves 37, 29, 38,
32, 39, 36, 29, 11, 29, 18: mean **29.8** against 16-17.5 for the last three
rounds, and **wave 39** is the console record by eleven waves. Seven of the ten
games beat the old record of 28. The pad measurement you ran the same evening
is exactly what the bench said it would be: 11.4 ms median, every one of the
forty trials between 10.6 and 11.7 ms, none of the 19.5/39.5 staircase the
adapters gave. So the whole ~36 ms went in as planned.

## Two things in your console output, both explained

**"We drove the A line but the pad reported X."** That is a label error in
the measurement tool, not your wiring. The bot's byte puts the fire buttons in
the order Y, A, B, X; the tool's table had them as Y, X, B, A, so what it
called "A" was in fact the X line, and your pad reported X because X is what
was pressed. The tool's table is corrected in the next build. The timing is
right either way, and the games prove the fire directions are right too.

**Deaths missing from the log.** You were right, and it is worse than it
looks: the HUD tally saw 225 of the 322 deaths across the session, and in game
1 it saw 17 of 40. The reason is the lives display. Robotron gives an extra
man every 25,000 points, and the bot was scoring 25,000 a wave, so from about
wave 9 it had banked more men than the HUD can draw (the row shows about
eight). A death with more men banked than that removes nothing visible, and
the bot only counts a death when an icon disappears. That is exactly where
your missing deaths sit: game 1 logged nothing from wave 9 to wave 28, then
fifteen deaths in waves 29-37 as the bank ran down below the row's limit.

The true total is easy, because a game only ends when every man is lost:
deaths = 3 + score / 25,000. Game 7 (score 770,225: 33 men, the HUD counted
32) shows the rule holds on the console. From this build the GAME OVER line
prints both figures, `D=17 on the HUD, 40 by the life economy`, the report
flags each game's shortfall, and the per-wave death counts in deep games are
to be read as lower bounds.

## Where the console now stands

By the life economy: one man bought per wave, 1.08 lost per wave. The bot
bleeds about 0.08 men a wave, so its three starting men last about 37 waves,
which is the 29-39 cluster you saw. Wave 100 needs that bleed under 0.03. The
emulator, at its 2-tick loop, loses about 0.8 a wave in the same waves.

## What the trace says (folder received the same evening)

The reversal test now reads +3 ticks in 92% of cases, where rounds 15-16 read
+3 in about 60% and +4 in up to 29%. But the loop ran faster this time
(57 ms ticks instead of ~63), so the fair unit is milliseconds, and the
report now prints it that way: a reversal is **seen by 171 ms** after the
command and **not yet seen at 111 ms**. The emulator on the same measure is
117 and 50. Rounds 15-16 were about 210. So round 18 took ~40 ms out of the
loop and ~55 ms remain, and we know where they are: the capture card's ~36 ms
(your loopback) and the pad's 11 ms USB interval (your pad test). Nothing
else is left; the console's own pipeline is the emulator's.

Everything else in the trace is either at the emulator's level or better
than before: player speed ratio 1.03, blind 23%, the card delivered 93%
fresh frames with no stalls, and in waves 5-22 the console now dies at the
emulator's rate (0.58 / 0.61 / 0.76 per wave by band against the emulator's
0.64 / 0.79 / 0.88; rounds 15-16 were 1.0-1.7). What separates the two now
is deeper: income (25.0k a wave against the emulator's 27-28k, so one man
bought per wave against 1.1) and the wave 29+ death rate.

## Round 19

Same command, same build plus the two fixes above, ten more games. Nothing
about play changes; this is a second sample of the new configuration, so the
next change can be measured against twenty games rather than ten.

```
.venv\Scripts\python -m robotron_ai --mode hardware --device 0 --port COM4 --loop --games 10 --visualize --capture-backend dshow --capture-fourcc MJPG --capture-res 1280x720
```

Fresh download as usual (GitHub page, green **Code** button, **Download
ZIP**, extract, rename the folder to `robotron_ai`, venv per the README) into
`C:\robotronai19`. Send the `hardware_report` folder and the console text.

Strider
