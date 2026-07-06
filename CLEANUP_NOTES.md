# Cleanup status & pending archive plan

## Done
- **`robotron_ai/` is the clean, self-contained tool.** It has its own copy of
  the proven engine libraries under `robotron_ai/engine/` and imports **nothing**
  from the old `robotron/` tree. A friend can download the `robotron_ai/` folder
  alone and run it.
- Archived 33 stale build/experiment scratch logs to
  `robotron/archive/scratch_logs/` (nothing imports or writes them).

## Deferred — DO THIS AFTER STOPPING THE 24/7 LOOP
A live loop was running during the refactor (`brain_champion.py --loop`,
`player.py`, `record_loop.py`, two `auto_labeler.py`). Those scripts import from
`robotron/` and respawn subprocesses, so moving them mid-run would break it.

When you're ready (`robotron/kill_all.bat` first), the old `robotron/` tree can be
retired down to what `robotron_ai/` replaces. Suggested split:

**Superseded by `robotron_ai/` (safe to archive):**
`brain0.py`, `brain3.py`, `brain4.py`, `brain_champion.py`, `brain_yolo.py`,
`player.py`, `real_game_player.py`, `game_loop.py`, plus the now-duplicated engine
originals (`game_state.py`, `xenia_memory.py`, `jit_entity_reader.py`,
`sprite_lookup.py`, `robotron_fsm.py`, `clearance_planner.py`, `screen_capture.py`)
— the live copies now live in `robotron_ai/engine/`.

**Keep if you still run the training / research pipeline** (your standing goal to
retrain YOLO on deep-wave data): `auto_labeler.py`, `train_yolo.py`,
`audit_yolo_labels.py`, `capture_training.py`, `record_loop.py`, and the
diagnostics you still use (`analyze_deaths.py`, `validate_detection.py`,
`watcher.py`, `overlay.py`).

**Pure experiments (archive):** `gen_test.py`, `improve_test.py`, `sweep_lag.py`,
`measure_actuation.py`, `probe_wave_addr.py`, `xenia_dynamics_probe.py`,
`record_now.py`, `record_run.py`, `_make_video.py`, `_verify_*.py`, `tune_loop.py`,
`annotate.py`.

The engine copies in `robotron_ai/engine/` are the ones to sync going forward if
you keep tuning the FSM/planner in robotron-rl.
