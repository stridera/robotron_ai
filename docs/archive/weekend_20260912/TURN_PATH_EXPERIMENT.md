# Turning-path MAME screen — 2026-09-09

Status: completed proxy loss, dev-only, opt-in `VSEARCH_TURN_STEPS=2`.
Production unchanged. Follow-up mechanisms are in `OVERNIGHT_EXPERIMENTS.md`.

Validated result, 144 games/arm: deaths/wave 1.096 baseline versus 1.303 candidate;
NET +0.0202 versus -0.1831, difference **-0.2033**, game-bootstrap 95% interval
**[-0.2416, -0.1623]**. Mean capped max wave 22.51 versus 15.49.
One corrupt-score episode was rejected and replaced. The original unvalidated
summary falsely inflated income; `summary.json` now holds the corrected result.
See `OVERNIGHT_EXPERIMENTS.md` for the data-quality fix and follow-up tests.

The existing search holds one heading throughout its six-step prediction.
The candidate holds the first heading for two steps, then evaluates all eight
second headings for the remaining four. Straight continuation remains available.
It selects the best minimum clearance for each first heading, then applies the
existing minimal-deviation selection and firing rules. FIREPLAN uses the binding
threat from the selected route. Search runs only when the FSM's straight route is
unsafe (or it requests STAY); the next decision replans rather than committing to
the whole route. Horizon, margins, threat dynamics, and collision sampling match
baseline. This differs from the previously closed end-of-horizon exit penalty.

Potential failure: the extra options can make the planner optimistic about a
future turn that delayed control or repeated replanning fails to execute.
Gameplay evidence, not improved geometric clearance, determines usefulness.

Three new tests pass: vectorized continuations match independent scalar replays
with chasing and reflecting threats, a turn escapes an obstacle on a straight
route, and the disabled feature matches frozen pre-change dev actions. The full
Python suite passes 13 tests. On 100 synthetic dense scenes (30 threats), median /
p95 planner time was 1.31 / 1.38 ms baseline and 3.77 / 3.91 ms candidate, with
five differing actions. These are execution checks, not gameplay evidence.

Two smoke games per arm completed with no invalid episodes in
`logs/turn2_smoke_20260909/`. Not pooled with the screen or interpreted as an
effect estimate.

Full screen: `logs/turn2_screen_20260909/`, 144 games per arm, 12 workers,
seed root 40910001. Each game starts a fresh MAME process; source files and exact
settings are frozen in the run folder. The existing delayed/noisy proxy settings
are unchanged: perception age one decision, actuation four frames, entity lead
0.7, player lead 1.5, 10% entity drop, 2% player drop, 2 px noise. Arms differ
only by `VSEARCH_TURN_STEPS=0` versus `2`.

Primary measure: W5–25 net lives/wave = score/25000 − deaths, wave-weighted,
with game-bootstrap uncertainty. Also report score, deaths and capped max wave.
A small apparent gain requires an independent larger confirmation before Xenia;
the earlier +0.03 proxy gains vanished at 576 games. No conclusions about late
Xenia or hardware follow directly from this MAME screen. No Xenia runs alongside
MAME. New runner options support other candidate flags and calibrated delay
conditions without writing another experiment-specific launcher.
