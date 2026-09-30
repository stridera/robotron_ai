# Working on minastirith (the analysis and MAME-lab server)

As of 2026-09-30 the agentic work on this project runs on `minastirith`
(Ubuntu 26.04, 16 cores, 26 GB, no GPU, `~/Code`). Strider's Windows PC is
no longer the working machine; Eric's Windows rig is the console bench and
runs the bot. This page is what is on the server, where, and what it can
and cannot do.

## Layout

| path | what | source of truth |
|---|---|---|
| `~/Code/robotron_ai/` | this package, clone of `git@github.com:stridera/robotron_ai.git` (`main`) | GitHub |
| `~/Code/robotron_ai/logs/` | emulator and lab artifacts referenced by STATE_OF_PLAY (production_games traces, collision and actlag runs, weekend screens); ~11 GB, not in git | synced from the PC 2026-09-30 |
| `~/Code/robotron_ai/tools/pad_*.py` | untracked bench scripts for the pad rig (kept out of git on purpose) | synced from the PC |
| `~/Code/robotron/` | the dev tree the MAME lab draws its sources from (`mame_lab.py`, `mame_score.py`, `residual_policy.py`, `clearance_planner.py`, `robotron_fsm.py`, `fsm_evolved_planner_v2_hunt.json`) plus its `logs/` (8.6 GB of lab runs); no git remote, the PC copy is the origin | synced from the PC; the previous server copy is `~/Code/robotron.old-20260302` |
| `~/Code/robotron-rl/` | the MAME gym: `mame_gym/` (Lua bridge `robotron_server.lua`, env, ROM in `mame_gym/roms/robotron87.zip`), `mame_states/`, the FSM history; clone of `git@github.com:stridera/robotron-rl.git` with the PC's working tree on top | GitHub + PC (pushed 2026-09-30) |
| `~/Code/robotron-rl/.venv-collision/` | Python 3.12 (uv) with numpy, gymnasium, cloudpickle: the interpreter the lab runs under | built here |
| `~/Code/.venv-robotron/` | Python 3.12 (uv) with numpy, opencv-python-headless, pyserial, pymagewell: runs this package's tests, `trace_report`, `compare_sessions` | built here |
| `~/Code/robotron_data/round18/` | Eric's round-18 trace (`decisions.jsonl`, `report.json`, `trace_summary.json`, `rig_calibration.json`) and the ad-hoc `reversal_ms.py` | copied from the PC |
| `~/mame_robotron/roms/` | spare copies of `robotron.zip` and the two decoder ROMs (the lab does not need them; `robotron87.zip` boots on its own) | copied from WSL |
| `/usr/games/mame` | MAME 0.285 (apt), the same version the WSL lab used | apt |
| `~/.claude/projects/-home-strider-Code-robotron-ai/memory/` | Claude's project memory, merged from the PC's on 2026-09-30 | here |

Left on the PC deliberately: `~/code/robotron/labeler_captures` (268 GB)
and `recordings` (77 GB), the raw capture material for detector training;
the Xenia emulator and everything that needs a GPU.

## What runs here

```bash
cd ~/Code
.venv-robotron/bin/python -m unittest discover -s robotron_ai/tests -t .        # 106 tests
.venv-robotron/bin/python -m robotron_ai.trace_report robotron_data/round18 --waves 40
.venv-robotron/bin/python -m robotron_ai.tools.compare_sessions <session folders>
```

The MAME stand-in (the console proxy at one extra tick of actuation delay):

```bash
cd ~/Code/robotron_ai
../robotron-rl/.venv-collision/bin/python tools/run_collision_mame_fresh.py --help
```

`run_collision_mame_fresh.py` expects `~/Code/robotron-rl` (it is hard-coded
as `WSL_ROOT`, and the path is the same here as it was on the PC's WSL) and
`~/Code/robotron` as the dev tree. MAME boots the ROM headless at ~60x real
time on one core; sixteen cores means sixteen games in parallel. MAME's
`-verifyroms` calls the set "bad" on both machines; it has always run.

## What does not run here

- The bot itself (`python -m robotron_ai --mode hardware`): needs the
  capture card, the serial pad and a GPU for the detector. That is Eric's
  rig. Xenia and `--mode xenia` likewise stay on a Windows GPU machine.
- `tools/measure_capture_latency.py` and `measure_control_latency.py` are
  Windows tools (GDI, DirectShow, XInput); their pure parts are tested here.
- pymagewell's real device (Windows SDK); its mock device works here and the
  tests use it.

## Getting new results in

Eric sends session folders (see `docs/ERIC_HANDOFF.md`). Put them under
`~/Code/robotron_data/<round>/` and run `trace_report` / `compare_sessions`
from `~/Code` with the venv above. Push code to `main` from here with the
server's own SSH key (`git push origin main`); Eric takes the `main` ZIP.
