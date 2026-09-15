# Collision sampling experiment — 2026-09-08

Status (2026-09-09): experimental, default OFF. The completed MAME screen did not
show an improvement; the Xenia comparison stopped on focus loss after three games
per arm, with worse preliminary late-wave survival. No wave-100 result or
measured gameplay improvement yet. Existing production behavior is preserved with
`VSEARCH_COLLISION_SUBSTEPS=1` (the default).

## Hypothesis

Both clearance planners update predicted positions once per nominal 66.7 ms
and check distance only at the resulting endpoints. A fast threat can cross a
player's path between checks. This is a sampling limitation distinct from the
closed margin, wall-weight, lead, launch-lane, and horizon experiments.

`VSEARCH_COLLISION_SUBSTEPS=4` also checks at 1/4, 1/2, and 3/4 of each existing
prediction step. It preserves the coarse chase dynamics, endpoint states,
horizon, weights, margins, and decision cadence. Intermediate positions are
computed before wall reflection/clamping; bank shots visit the wall and the
player stops when it reaches a wall. The selected binding threat can change,
so the experiment can affect both movement and FIREPLAN targeting.

This is sampled collision checking, not exact continuous collision detection.
It does not predict unseen projectiles or fix perception latency. More danger
detection can make the bot timid or disturb rescues, so geometric correctness
alone is not evidence of improved play. The dev-only, closed full-speed
`VSEARCH_SPARK_SLIDE` experiment cannot be combined with this option.

## Evidence so far

- Seven offline tests pass: crossing, bank-shot, player wall contact, binding
  threat, nonmutation/clearance monotonicity, dev/production geometry parity,
  and default action parity against production commit `0e73118`.
- On 600 raw snapshots from the 100 most recent historical W25–39 death rings,
  18 of 212 endpoint-safe headings became dangerous with extra samples
  (4,800 headings examined). These are mixed historical, death-selected
  snapshots with no player/entity lead or action replay. This is a geometric
  diagnostic, not a death-prevention estimate or normal-play frequency.
  Details: `logs/collision_audit.json`.
- A 30-threat synthetic timing check, 300 calls per setting, measured median
  planner time 1.31 ms at one sample and 2.85 ms at four; p95 1.98/3.44 ms.
- Two real-vision Xenia smoke games, one per arm, completed the W6 cap:
  baseline W7 / 128,100 / 1 death; candidate W7 / 114,625 / 2 deaths.
  Candidate cadence was about 15 Hz with 3–5 ms busy time. These two games
  validate execution only. Logs: `logs/collision_smoke{,.err}.log`.

## Evaluation sequence

Completed MAME result (`collision_fresh_20260908_1428`):

| W5–25, 144 valid games/arm | Baseline | Four samples |
|---|---:|---:|
| Deaths/wave | 1.0739 | 1.0980 |
| Score/wave | 27,632 | 27,501 |
| Net lives/wave, wave-weighted | +0.0314 | +0.0020 |
| Equal-game mean net | -0.0150 | -0.0316 |
| Games reaching the analysis band | 142 | 143 |

Candidate-minus-baseline NET = -0.0294; game-bootstrap 95% interval
[-0.0729, +0.0131]. One zero-score/short episode was excluded and replaced.
This is **not a win**; the point estimate is worse, with uncertainty including
zero. Per the predeclared gate (no clear early economy regression), proceed to
the Xenia late-band comparison, where the motivating question can be tested.
No setting is promoted. Machine-readable result: the run folder's `summary.json`.

The Xenia exact-state batch in `logs/collision_20260908_145424/` stopped after
about 93 minutes when the guard reported focus loss for three seconds. It stopped the
controller and batch. Six games completed (three per arm of the planned eight),
all through W40; the seventh was interrupted during startup. No test processes
remain running as of the 2026-09-09 status check.

| W25–40, 3 games/arm, 48 waves/arm | Baseline | Four samples |
|---|---:|---:|
| Deaths/wave | 0.917 | 1.292 |
| Score/wave | 29,133 | 30,104 |
| Net lives/wave | +0.249 | -0.088 |

The candidate had approximately 41% more deaths/wave; extra income did not
compensate (NET difference approximately -0.336 lives/wave). Both arms ran at
15 Hz with no reported overruns. This is an interrupted, small sample, not a
completed confirmatory comparison. The secondary W5–25 deaths/wave were
0.794 baseline and 0.730 candidate. The primary late-band direction and the
completed MAME screen provide no basis for promotion. No new wave record was
attempted in this W40-capped exact-state test. See `stats_late.txt`,
`stats_early.txt`, and `status.txt` in the run directory.

Focus-stop investigation (2026-09-09): the user confirms nobody used the PC.
The last log entries show verified Xenia focus followed by four menu A presses
for game 7. The old guard logged no foreground identity, so the historical cause
cannot be determined. Its comparison against `Process.MainWindowHandle` could
misclassify another window owned by Xenia. The supervisor now checks foreground
process ownership, resets its timer across process generations even without an
empty poll, and records foreground PID/process/title/handle transitions in
`focus.jsonl`. The three-second stop remains for actual external ownership after
acquisition. `tests/test_collision_focus.ps1` passes mocked polling scenarios for
secondary windows, restart, acquisition, recovery, sustained loss, and diagnostic
contents. This fixes identified weaknesses; it does not establish the cause of
the earlier stop. No live emulator run was launched for this investigation.

An earlier launch
(`collision_20260908_144708`) produced no gameplay and was stopped after the
menu-input loop failed to acquire focus. `brain3._focus_xenia_window` now
verifies foreground ownership, temporarily attaches input queues while
requesting focus, and refuses menu input if focus was denied. `ab_yolo` now
aborts on a nonzero brain exit rather than silently continuing an invalid
batch. These are shared startup fixes, not treatment changes; their hashes
are included in the new Xenia manifest.

1. MAME screen: 144 games/arm, six workers/arm, W5–25 analysis. Use the
   existing calibrated proxy configuration from `lane_screen.sh`: actuation
   4 frames, player lead 1.5, `LAB_K=1`, entity lead 0.7, drop .10, player drop
   .02, noise 2. `LAB_K=1` is one **decision step**, not the one-frame age
   described in the state-of-play summary. Record the actual flags.
2. If there is no clear early economy regression, run Xenia exact-state
   (`ROBOTRON_ORACLE=1`), eight interleaved games/arm, cap W40, primary band
   W25–40, secondary W5–25. Additional samples are the only arm difference.
3. A promising late-band result needs more games and confirmation through
   real vision, then the production hardware-sim, then Eric's console.

Do not promote from a small proxy improvement: the earlier +.03 results failed
at 576 games. The practical target is roughly .15–.20 fewer late-band deaths
per wave without sacrificing income; report game-level uncertainty, incomplete
games, cadence, and score. MAME's late band cannot establish this result.

MAME and Xenia must run sequentially. The current full screen is
`logs/collision_fresh_20260908_1428/`, started with
`tools/run_collision_mame_fresh.py --games 144 --workers 12`. It starts a new
emulator per game, uses private state paths and distinct seed roots, freezes
the planner/FSM/parameters, logs MAME diagnostics, and replaces invalid games
with new trials (bounded retry budget). Twelve workers share interleaved arm
submissions. Two games/arm completed its smoke with no invalid episodes;
those smoke games are not pooled with the full screen.

The first screen (`collision_20260908`, eight workers/arm) was interrupted
when the user completed a WSL upgrade/restart. Its logs are preserved in
`logs/mame_collision_20260908_interrupted/` and are not pooled with the rerun.
Python 3.12 vanished from `/usr/bin` during the upgrade. A separate
`.venv-collision` environment in the WSL project now uses uv-managed Python
3.12.12, NumPy 1.26.4 and Gymnasium 1.2.1 (the existing package versions).
The original `.venv` was not modified. MAME reports version 0.285.

Workers previously shared the same `rl_reset.sta` path. The optional
`MAME_LAB_STATE_ROOT` setting now gives each worker a private state directory,
removing concurrent writes to the reset file. `MAME_LAB_PYTHON` selects the
separate interpreter; absent these settings, `robotron/mame_run.sh` retains
its old paths. A two-game recovery smoke completed without errors, but the
subsequent multi-game-per-process screen (`collision_20260908_clean`) still
reproduced reset failures and was stopped. Isolation was not a sufficient
fix; the fresh-process launcher avoids reusing an instance across episodes.
Neither recovery smoke nor interrupted screen is a treatment-effect estimate.

Use `tools/analyze_collision_mame.py LOG_DIR PREFIX --expected 144` for the
validated result. It cross-checks completed-episode logs, excludes recovered
episodes and subsequent restarted-seed segments, reports actual max wave
(the older summary adds one), and resamples games. Fewer than ten games per
arm does not produce a confidence interval. Two additional offline tests
cover these exclusions, worker errors, and the single-game smoke case (ten
tests total). The geometry suite also passed under the repaired WSL runtime.

The prepared Xenia launcher is `tools/run_collision_ab.ps1`. Run from an idle
rig with no existing Xenia or gamepad server:

```powershell
pwsh -NoProfile -File tools/run_collision_ab.ps1
# Real-vision confirmation, after the exact-state result warrants it:
pwsh -NoProfile -File tools/run_collision_ab.ps1 -Vision
```

It records source/weights hashes, exact settings, process IDs, output and error
logs, and band summaries under a timestamped `logs/collision_*` folder. It
stops the batch and its gamepad server if Xenia loses focus for three seconds
after acquiring focus, the server fails, eight hours elapse, or a file named
`STOP` appears in that run folder. A completed harness is not automatically a
valid result: check per-arm completed games and worker errors.

## Separate production-transfer audit

Read-only findings; these are not changed by this experiment:

- Production `ThreadedVisionPerception` performs capture/inference in the
  background but emits position-only observations. `ChampionBrain.decide`
  updates velocity/coasting at decision cadence. Dev `ThreadedVision` tracks
  at eye cadence and normalizes velocity using measured sample duration.
- Production trackers are called with implicit `dt=1`, even when `TickClock`
  rescales the planner for a sustained different cadence. Production's simple
  velocity tracker measures displacement per decision, while the planner
  expects displacement per nominal tick. Audit this before interpreting
  transfer to a slower capture rig.
- In a clean environment, the dev planner uses margins 18/10; production's
  vision brain sets 21/12. The state inventory's `CLEAR_MARGIN 1.15` is not
  the runtime margin value.
  On 300 raw historical late-wave snapshots, default production and dev
  actions differed on 22; with margins matched, they agreed on all 300.
  This bypasses tracking/leads and is a parity check, not a performance
  comparison. Details: `logs/collision_production_parity.json`.
- The source defaults are `LEAST_BAD=0` and `FSM_BUFFER_SCALE=1.0` in both
  trees, and `VSEARCH_ACT_LAG=0` in dev (absent in production), despite the
  state inventory describing those as shipped ON. Dev low-confidence
  continuation defaults ON; production has no equivalent low-confidence feed.
- The evolved parameter JSONs match. FSM source differences currently add
  opt-in spawner/rescue experiments, off by default. The existing uncommitted
  changes in dev `brain_yolo.py` were preserved.

These discrepancies do not invalidate within-harness A/B comparisons, but
production transfer requires its own validation. Neither matching a current
oracle's rescue count nor failing several planner variants proves an absolute
architectural ceiling. The existing planner still only scores constant-heading
trajectories; trajectories with turns and joint move/fire outcomes remain
distinct architectural questions, not measured solutions.
