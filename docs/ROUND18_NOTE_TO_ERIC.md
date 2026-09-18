# Round 18 — note to Eric (2026-09-18)

Eric,

Three clean loopback runs, and they settle the capture question. Thank you for
running all three.

## What the runs say

Every one of them was valid, which the new environment block makes checkable
from here: the window covered the monitor exactly, the desktop was unlocked,
the animation painted 59.0 frames a second against a 59 Hz link, the screen
probe sampled at 164.9/s (2.8x margin, enough to resolve every frame), and the
source measured 59.1 unique frames a second. So the numbers below are real.

| setting | video-side delay | card unique/s | share of the 59/s offered |
|---|---:|---:|---:|
| MJPG 1920x1080 (what every round has used) | 41.9 ms | 54.1 | 92% |
| **MJPG 1280x720** | **35.9 ms** | **54.9** | **93%** |
| YUY2 1280x720 | 35.2 ms | 54.5 | 92% |

**720p is about 6 ms faster and exactly as fresh.** That is the whole finding.
The freshness column is what I was worried about two days ago, when I told you
720p was off the table: the old capture probe ranked 720p far below 1080p on
unique frames, and I took that at face value. It was wrong, and the reason is
embarrassing. That probe decides whether a frame changed by sampling a fixed
grid of individual pixels, which works out to 144 sample points at 1080p but
only 64 at 720p. On Robotron's mostly black arena a frame only registers as
changed if a sprite happens to land on one of those points, so fewer points
means fewer detected changes. The ratio of sample points is 2.25 and the ratio
of the scores it gave was 2.252. It was measuring its own grid, not your card.
The new test reduces both paths to the same fixed-size patch, so resolutions
compare fairly, and 720p turns out to be free.

On the console the gain should be a little larger than 6 ms. In your loopback
the PC fed the card 1080p, so its 720p row included a downscale. The Xbox
outputs 720p natively, so capturing at 720p is a straight pass-through and
also removes a round trip the bot pays today: the card upscales your 720p
picture to 1080p and then the bot scales it back down to 720p for the
detector. That round trip can only lose detail, so 720p should be marginally
better for detection as well.

**MJPG against YUY2 is a non-question.** The two 720p rows are within noise of
each other, and the card reports the same converted RGB24 buffer whichever we
ask for, so we still cannot confirm a format request ever takes effect. MJPG
is the one we have years of runs on, so we keep it.

**One small thing for the record.** The card passes about 92% of the frames
offered to it, dropping roughly four or five a second at every setting. That
costs under a millisecond of average age and is the same across settings, so
it changes nothing, but it is worth knowing it is not perfect.

## Round 18: two changes, both already measured

Normally I would change one thing at a time. Here both changes have been
measured on the bench in isolation, so the reversal count in the trace can be
attributed afterwards without a separate session, and your time is the thing
worth saving.

1. **The direct-wired pad**, replacing the two X-Arcade adapters: 9 ms
   press-to-report against 39 ms through the adapters, so about 30 ms back.
2. **`--capture-res 1280x720`**, worth about 6 ms and free.

Together that is roughly 36 ms of the ~72 ms the console loses over the
emulator. That should be enough to move the reversal count from 3 ticks, and
sometimes 4, down toward the emulator's 2. The emulator at 2 ticks reaches
waves 90 to 198; the MAME lab run at one extra tick reproduces your console
almost exactly, so this is the whole of what stands between the two.

```
.venv\Scripts\python -m robotron_ai --mode hardware --device 0 --port COM3 --loop --games 10 --visualize --capture-backend dshow --capture-fourcc MJPG --capture-res 1280x720
```

Send the `hardware_report` folder as usual. The first line of the analysis is
the reversal count, and that is the number that says whether this worked.

Strider
