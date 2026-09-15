# Round 15 — note to Eric (2026-09-14)

Eric,

Thanks for the round-14 games and the notes. Here is where we stand, what
round 15 is for, and answers to your questions.

## Where we stand

Your five games reached waves 9, 9, 22, 9 and 11. That is the same band as
rounds 12 and 13. Meanwhile the same code on the emulator now averages about
wave 30, with records at 58 and 60. Comparing your games to 135 emulator games
wave by wave: the score per wave is identical, but on your console the bot
loses lives about one and a half times as fast, and the extra deaths start in
waves 2 to 5, where the emulator almost never dies.

Everything the current report can measure looks the same on both machines:
picture geometry, frame rate, capture freshness, the scoreboard reader, and
what the detector sees in your screenshots. Over the weekend an automated
run also tried twelve different gameplay tweaks on the emulator and none of
them held up. So the gap is on the console side, and nothing we have ever
received from the console can say what is killing the bot there. In fourteen
rounds we have never seen where the player was, what was next to it, or how
long a command took to show up on screen when it died.

## What round 15 gathers

The new build records two things while it plays, into the same
`logs\hardware_report` folder you already send back:

- A log of every decision, fifteen times a second: where it saw the player,
  every enemy and bullet it saw, the command it sent, and the score, wave and
  lives it read off the screen.
- For every death, the previous four and a half seconds of video frames plus
  one second after, as still images.

Nothing about how it plays has changed. It is the round-14 bot with a
recorder attached, and the recording happens after each command is sent, so
it does not slow the bot down. The folder will be a few hundred megabytes
after five games instead of a few kilobytes.

## How it helps

From that folder we can compute, for your console, the same three numbers we
already have for the emulator:

1. **Was the killer visible?** For each death, what lethal thing the
   detector saw within a few pixels of the player at the moment of the
   collision, or nothing at all. On the emulator, 18% of deaths have no
   visible killer. If your console is well above that, the detector is
   missing things in your video feed, and the fix is retraining it on your
   frames, which these death images give us.
2. **How long does a command take to show on screen?** Every time the bot
   reverses direction, we count frames until the player actually turns. On
   the emulator it is two ticks, 92% of the time. If yours is slower or
   erratic, the delay is in the controller box or the capture card, and the
   fix is timing constants or hardware, not gameplay rules.
3. **Does the player move at the expected speed?** If not, the controller or
   the screen scaling is off.

One of those three will almost certainly stand out, and it decides where the
next month of work goes. That is why I would rather do this than try more
gameplay tweaks now: a tweak tuned on the emulator has not transferred to
your console yet, and we need to know why before tuning anything else.

## What to do

1. Unzip `robotronai15.zip` next to the round-14 folder (it becomes
   `C:\robotronai15\robotron_ai`) and reuse the same venv or run the install
   step from the README.
2. Run exactly the round-14 command from the new folder:

```
.venv\Scripts\python -m robotron_ai --mode hardware --device 0 --port COM3 --loop --games 5 --visualize --capture-backend dshow --capture-fourcc MJPG --capture-res 1920x1080
```

   More games are better if you have the time; `--games 8` is ideal.
3. When it stops, zip `robotron_ai\logs\hardware_report` and send it. It
   will be large this time, so a file-share link is fine. If disk or memory
   is a problem, add `--death-seconds 2` to halve it.
4. Your written observations are still valuable, especially anything you
   notice in the `--visualize` window at the moment of a death.

## Your questions from round 14

- **Saving a grunt and collecting civilians before ending the wave:** not
  tried in that form, so it is a genuinely new idea. The pieces around it
  have been measured: killing spawners first lost six times, pursuing
  civilians harder lost three times, and the late-wave rescue income is
  already at what a bot with perfect information collects. So the upside is
  real but bounded, and it is queued behind finding out why the console
  dies in waves 2 to 8.
- **Shooting toward the civilian it is walking to:** you are right about
  what it does. When nothing is in range the rules say "do not fire", and
  the bot turns that into "fire the way I am walking". The alternative of
  firing at the nearest killable enemy was tested: slightly fewer deaths,
  slightly less score, too small to ship on the emulator. Worth re-testing
  on the console once we have its own numbers.
- **Boxes and collisions:** the planner only uses the centre of each box,
  with a per-type safety weight and a fixed danger radius. Box height and
  width errors do not affect it as long as the centre is right, which it is
  on the emulator to about one pixel. The wide electrodes on waves 10 and 20
  are a real gap in a centre-only model; electrodes cause 1.5% of emulator
  deaths, and round 15 will tell us their share on the console.
- **Hulks:** shooting a hulk pushes it back, which is why never firing at
  hulks lost when it was tested. The bot only fires at a hulk when it is
  close and blocking the escape. Hulks cause 6% of emulator deaths.
- **A lower-latency capture card or a different language:** your Magewell
  is already a low-latency card. The format we chose for it (MJPG over
  DirectShow) was picked for delivering unique frames, not for delay, and a
  raw format might be faster. Round 15 measures the whole delay directly,
  so we will know whether delay is the problem before anyone buys anything.
  A different language would not help; the bot's own work per decision is
  about ten milliseconds, and the delay lives in the console output, the
  card, and the detector.

## What's next

Round 15 comes back, we run the analysis, and one of three paths opens:
retrain the detector on your frames, fix the timing chain, or fix the
controller. After that, gameplay changes get tested with your console's own
numbers as the target instead of the emulator's.

Strider
