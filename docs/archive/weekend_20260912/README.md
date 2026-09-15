# Weekend of 2026-09-12 to 09-14: unattended GPT Astra research (archive)

The main checkout was handed to GPT Astra (Codex) for the weekend with a
Task-Scheduler supervisor and bounded review loop. It screened twelve isolated
opt-in changes on production Xenia (8-12 games/arm, W25 cap, oracle-audited
NET) and several MAME proxy variants. **None produced a confirmed gain**, and
none is in the shipping code. The reports here are the complete record, kept
verbatim; the ledger row-by-row is in `WHAT_WE_TRIED.md` under "Weekend of
September 12-14 (GPT Astra)".

| file | what it is |
|---|---|
| `WEEKEND_RESULTS.md` | the final synthesis (start here) |
| `DAY_REPORT.md` | the running log of every review, screen and audit, Sept 9-14 |
| `NIGHT_REPORT.md`, `OVERNIGHT_EXPERIMENTS.md`, `TURN_PATH_EXPERIMENT.md` | the MAME overnight queue (turning paths, joint shot, velocity fan) |
| `COLLISION_EXPERIMENT.md` | collision sub-step sampling screen |
| `RESIDUAL_EXPERIMENT.md` | residual-policy training on the champion (3M decisions; greedy actor identical to the champion) |
| `RESUME.md`, `WEEKEND_STATUS.md`, `WEEKEND_REVIEW.md`, `WEEKEND_TEST_PLAN.md` | operational handoff, supervisor status, the review prompt and the research backlog |
| `CLEANUP_NOTES.md` | an earlier note on retiring the dev tree (predates the weekend) |

## What was kept in main

- `tools/run_collision_mame_fresh.py` and `tools/analyze_collision_mame.py`:
  the fresh-emulator-per-game MAME runner with bounded retries, frozen source
  hashes and a whole-game bootstrap. Proven on 2026-09-14/15 (the 576-game
  fire-alternation confirmation and the radius sweeps ran on it).
- `tests/test_mame_screen_analysis.py` for the analysis.

## What was not kept (all preserved on branch `weekend-20260912-raw`)

- The twelve opt-in knobs in `brain.py`, `engine/clearance_planner.py`,
  `harness.py`, `perception.py` (`ROBOTRON_TRACK_TIME`, `_HUD_DEATH_RESET`,
  `_HUD_WAVE_RESET`, `_FRESH_PLAYER_ACTION`, `_NEUTRAL_LEAD_RESET`,
  `_VELOCITY_UNIQUE`, `_STATIC_ELECTRODES`, `_COAST_CLOSEST_PAIRS`,
  `_SPARK_BIRTH_VELOCITY`, `_PLAYER_HISTORY_LEAD`, `_COAST_CONFIRMED_ONLY`,
  `VSEARCH_PLAYER_FULL_BOUNDS`, `VSEARCH_COLLISION_SUBSTEPS`) and their unit
  tests: every one measured null or negative, and the production package
  stays lean.
- The production batch runner (`run_production_game.py`,
  `production_process.py`, `production_decision_trace.py`,
  `production_visual_trace.py`) and its tests: it needed a `decision_observer`
  hook and timestamps threaded through the harness and `Observation`. The
  shipped hardware trace (`trace.py`) records the same per-tick data without
  those hooks, and dev-tree `ab_yolo.py` covers Xenia A/Bs.
- The weekend supervisor, Task Scheduler installer, idle-reload helper, the
  evening/overnight queue runners and their PowerShell wrappers: tied to the
  Codex review loop and that weekend's plan.
- The one-off audit scripts (`audit_production_*.py`, `replay_production_hud.py`)
  whose outputs are in `logs/weekend_20260912/` in the main checkout.
- The residual-policy training tools (`train_champion_residual.py`,
  `champion_residual_env.py`, `verify_residual_*.py`, `inspect_residual_models.py`):
  the experiment is closed (RESIDUAL_EXPERIMENT.md).

The dev-tree planner (`C:\Users\strid\code\robotron\clearance_planner.py`,
unversioned) still carries the MAME-side variants of these knobs
(`VSEARCH_TURN_STEPS`, `VSEARCH_JOINT_SHOT`, `VSEARCH_VELOCITY_FAN`,
`VSEARCH_COLLISION_SUBSTEPS`), all no-ops by default.
