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

## What I need from round 18 before anything else

**The `hardware_report` folder.** Only the console text came through, and the
one number that says how much latency actually came back, the reversal count,
lives in that folder. It is still on your machine at
`C:\robotronai18\robotron_ai\logs\hardware_report`; please zip and send it as
it is. Note the trace stopped saving death windows at 120 (the cap), which is
fine, the decisions file is what matters.

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
