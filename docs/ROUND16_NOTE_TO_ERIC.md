# Round 16 — note to Eric (2026-09-16)

Eric,

Round 15 did exactly what it was built to do. Ten games, 56,705 decisions and
60 death windows came back, and for the first time we can say what is
different about your console. Thank you for the long session.

## What round 15 showed

**Results.** Waves 20, 16, 9, 21, 13, 17, 20, 18, 19, 22: a mean of 17.5
against 12 in round 14, so the fire-alternation change helped, but far less
than on the emulator, where the same build now runs to waves 100-200.

**The cause, measured.** Every time the bot reverses direction, the trace
counts how many decisions pass before the player on screen actually turns.
On the emulator that is 2 ticks, 92% of the time. On your console it is 3
ticks in 61% of reversals and 4 in another 26%. That is one to two extra
ticks (70-130 ms) of delay somewhere between our command and the picture we
get back. Everything else checks out: the player moves at exactly the
expected speed (so the controller box and the picture scaling are right),
the capture never stalls, and the scoreboard reader is fine.

The extra delay explains the rest of the numbers. The bot's rules were tuned
for a two-tick loop, so on your console it predicts its own position about
a tick short and it flips its heading every decision while the previous
command is still in flight. One of the electrode deaths you saw is a clean
example: for the last six decisions before the collision the heading went
east, south-west, east, south-west, south-west, south-east, and the net drift
walked it into the electrode. Also, 32% of deaths on your console had no
visible killer at the moment of collision (18% on the emulator), and in most
of those the bot was coasting a projectile track it had lost sight of: with
the extra delay the sparks it does see are already farther along than it
thinks.

## What is different in this build

1. **Self-calibrating lead.** The old delay estimator counted any change of
   direction and treated a 45-degree turn as an instant response, so it read
   1.0 tick on your rig and set the bot's forward prediction to 1.5 ticks. The
   new estimator uses only true reversals, the same measurement as the
   analysis, and sets the prediction from it. On the emulator that stays at 1.5; on your console it gives 2.5, which round 16
   pins explicitly (see the command below), and the measurement is saved in
   the report folder for later runs.
2. **The script now exits.** After `--games N` it stops the vision thread and
   the capture card explicitly and exits; round 15's hang was a background
   thread stuck in the GPU at shutdown.
3. **More death windows.** Round 15 hit the cap of 60 windows at game 4; the
   cap is now 120. The folder will be around 450 MB after ten games.

## What to run

Same command as round 15, from the new zip (it unpacks to
`C:\robotronai16\robotron_ai`):

```
.venv\Scripts\python -m robotron_ai --mode hardware --device 0 --port COM3 --loop --games 10 --visualize --capture-backend dshow --capture-fourcc MJPG --capture-res 1920x1080 --player-lead 2.5
```

The `--player-lead 2.5` is the corrected prediction pinned explicitly, so
round 16 tests it from the first game rather than after the calibration has
collected enough reversals (that takes most of a session on your rig).

If you have time for a second session, this one tests whether the capture
format is part of the delay: identical, except `--capture-fourcc YUY2`. The
MJPG setting was chosen for delivering the most unique frames, not for
delay; MJPG means the card compresses every frame and we decompress it. If
the picture is black or the console output says the card delivers far fewer
than 50 frames a second, stop and go back to MJPG. The trace's reversal count
will tell us directly whether the delay changed.

Two questions that would help pin down the rest of the delay: what is the
controller box (the board, and whether it drives the pad's sticks or
buttons), and roughly how often its firmware loop updates the pad? At 9600
baud our command takes about a millisecond to arrive, so the box itself is
the unknown.

## Your notes from round 15

- **Hulks:** you are right that a hit barely moves one on the console, and the
  bot fires at a hulk only when it is the thing about to hit it: the planner
  fires at whatever is closing fastest, and a hulk only qualifies within 90
  pixels. The one exception is the older rule that shoots a hulk within 50
  pixels regardless; removing that was tested on the arcade version and lost,
  but the arcade push and the console push may differ, so it is worth a test
  once the delay is sorted.
- **Electrode deaths:** three of the 153 deaths had an electrode as the
  nearest thing at the collision (2%, same share as the emulator). The one
  whose frames we have is the heading-flip case above.
- **The hang at exit:** fixed, as above.

## What's next

Round 16 tells us two things: whether the corrected lead closes part of the
gap on its own, and (if you run the second session) whether the capture
format is part of the delay. After that the fix is either in the capture
chain, the controller box, or, if neither moves the reversal count, a
console-specific tuning of the bot around the delay it actually has.

Strider
