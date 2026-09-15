# Continuing research through Monday September 14, 09:00 Pacific

User explicitly asks to keep finding additional useful tests after the initial
queue finishes. Use available machine time; do not stop at a single failed
variant or a single promising run. The queue may evolve from evidence. Preserve
clear baselines, bounded jobs, complete-game checks, and the review/usage limits.

## First, finish the production comparison

The two consecutive-game validation passed September 12 around 00:53 PDT.
The 8/arm timestamp screen is running. Audit its terminal and per-wave readings
before using NET estimates. If favorable, confirm independently with more games
and a longer wave cap; do not promote from a small sample. If a W100 run occurs,
test repeatability and life economy rather than declaring research finished.

## Choose subsequent tests using failure evidence

1. Production/dev parity at death and wave transitions. The dev vision path
   resets tracking using memory events; production hardware lacks those reset
   signals. Inspect recorded death windows for stale coasting/velocity history.
   Test a video/HUD-derived reset only if evidence supports it, behind an opt-in
   flag. Separate death resets from wave resets and from neutral-input delays.
   Never inject memory events into a video-only candidate.
2. Observation age and actual control cadence. Compare measured telemetry to
   the calibrated lab: duplicates, drop streaks, tracking units, latency, and
   the amount of lead applied. Fix demonstrated mismatches one at a time.
   Use MAME for early-wave screens when the mechanism transfers; use Xenia for
   capture timing and late waves. Do not repeat the old generic noise/fan grid.
3. Local causes of repeated deaths. Group recorded failures by enemy type,
   post-respawn interval, wall/corner position, and rescue pursuit. Pick the
   largest preventable cluster; formulate one concrete movement or firing
   change and its expected tradeoff before testing. Compare deaths and score,
   not just the maximum wave from a lucky game.
4. Life income versus survival. Where evidence shows avoidable lost rescue
   income or risky pursuit, test one targeted rescue/escape decision rule.
   Preserve scoring opportunities when measuring survival improvements. Avoid
   tuning global aggression solely from a small maximum-wave sample.
5. After a credible gain, test its interaction with other independently
   supported changes using fresh controls, then longer Xenia runs. If a change
   regresses, preserve that result and move to a different mechanism rather
   than running the same setting repeatedly hoping for a better outcome.

These are hypotheses, not claims of known defects or a license to implement all
at once. First inspect the closed-experiment history in STATE_OF_PLAY.md and
DAY_REPORT.md to avoid repeating tests already run. The old two-step turning,
collision substeps, shot-delay and velocity-fan screens did not establish gains.
The 3M residual policy screen was inconclusive and below its confirmation gate.
Do not reuse lossy MAME save/restore counterfactual branches.

## Keep the queue productive

Prepare 2–4 independent inexpensive screens in one review when justified, with
opt-in flags, new seeds/run IDs, and explicit expected behavior. Review all at
the end of that batch. Run confirmation only after seeing qualifying evidence.
Prioritize a different mechanism over a dense parameter sweep. Use the local
monitor for waiting, and Codex review time for analysis, implementation, and
choosing the next tests. Save negative and incomplete results as carefully as
positive ones. No default changes, hardware claims, or external deployment.
