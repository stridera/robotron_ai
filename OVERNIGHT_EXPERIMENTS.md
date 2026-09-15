# Overnight research queue — 2026-09-09

User authorized unattended MAME/Xenia experiments through the night. Runtime
budget: 6.5 hours. The default production bot is unchanged. No automatic promotion.
Live results: [NIGHT_REPORT.md](NIGHT_REPORT.md); detailed state under
`logs/night_20260909/`. A `STOP` file there cancels the current stage and queue.

## Mechanisms

| Candidate | Question | Implementation |
|---|---|---|
| turn1 | Does allowing a turn after one decision help? | Same total horizon; best of eight continuations. |
| turnguard | Does a predicted future escape wrongly suppress defensive firing now? | Two-step turning search, retaining the original straight-route firing danger check. |
| turncommit | Does repeated replanning keep postponing the escape turn? | Execute the selected route through its first turn, with an immediate-danger check each decision and cancellation on respawn/jump. |
| shot2 | Does predicting a shot opening an escape improve joint move/fire choices? | Eight fire directions per movement; one delayed laser, travel time and first blocker, Hulks remain lethal. |
| shot4 | Is any shot-model gain robust to later shot availability? | Same model, four-step rather than two-step shot delay. |
| fan12 | Does uncertainty in projectile velocity improve decisions on aged observations? | Mean route clearance over observed velocity and ±12° alternatives for sparks/shells. |
| fan24 | Does a wider uncertainty estimate help or become overly cautious? | Same directional model, ±24°. |

These are research prototypes, not known solutions. The shot model assumes a
shot slot becomes available after its delay: friendly lasers are absent from the
planner's observations, so it cannot know the true four-shot inventory. A shot
removes at most its first intercepted killable target, only after its hit step;
it never deletes a Hulk. The velocity ensemble cannot recover unseen launches;
it tests uncertain trajectories, not lower capture latency. Turning can still be
optimistic about future control. Individual negative results do not close whole
architectural families.

Existing source confirmed Hulk deflection is already on by default and the old
no-Hulk-fire variant regressed. Those are not new overnight experiments.

Validation before launch: all 23 Python checks passed on Windows and WSL; the
PowerShell focus scenarios passed, and the generalized Xenia launcher completed
its prepare-only check. Dense synthetic 30-threat timing (100 scenes) measured
p95 1.47 ms baseline, 4.19 ms committed turns, 4.62 ms joint shooting, and 4.31 ms
velocity uncertainty. These timings are not real gameplay cadence guarantees.

## Evaluation and selection

Each variant first runs two smoke games/arm, then 144 valid games/arm with the
unchanged delayed/noisy MAME calibration, cap W26, primary W5–25. Games are the
bootstrap unit; NET = score/25000 − deaths per wave. Scores, deaths, max wave,
exclusions and full source/settings hashes are retained in each run directory.
Fresh MAME instance and private state path per game; twelve full-screen workers.

At most two screens with NET improvement > +0.03 receive independent 576-game
confirmation. ROM seed roots **and observation-defect random seeds** differ across
stages. Confirmation requires NET > +0.03 and its 95% interval above zero.
Exploratory screens and confirmations are not pooled. This limits selection
bias; a screen alone is never a promoted result.

If a candidate confirms and at least 2.3 hours remain, the best gets one
real-vision Xenia follow-up, four games/arm, W40 cap. This is still preliminary
for late-wave effects. The focus guard logs actual foreground process/window
changes and stops on external focus loss after acquisition. MAME and Xenia run
sequentially. No console or production deployment is performed.

## Data quality correction found during the first screen

The initial two-step turn screen contained one impossible final score:
41,242,365 at W21, including a 40,670,340-point partial wave. This is consistent
with the known environment hazard of reading reused score RAM around game over;
the precise bad frame was not recorded, so the source is not proved. Every
Robotron award is a multiple of 25, making this score invalid independently of
the candidate's performance.

The analyzer now rejects non-multiple-of-25 final scores and invalid per-wave
scores. The live lab rejects a whole episode immediately on impossible score
increments instead of accepting corrupted RAM as income. Rejected episodes are
replaced with fresh seeds, with a bounded invalid budget (12 or 3% of scheduled
games, whichever is larger). All invalid attempts remain logged.

After excluding that episode and completing one replacement, the original
two-step turn screen had NET change **−0.2033**, 95% interval
**[−0.2416, −0.1623]**, 144 valid games/arm. Deaths/wave rose 1.096 → 1.303;
mean capped max wave fell 22.51 → 15.49. This prototype is a clear proxy loss.
The original unvalidated summary is preserved; `summary.json` is corrected.
Revalidating the earlier collision screen changed none of its results.

The new commit and firing variants target distinct possible causes of that loss.
The overnight supervisor writes both `state.json` and `NIGHT_REPORT.md` after
every stage; failed or incomplete stages cannot pass the confirmation gate.
