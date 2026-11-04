# MAME lab: paired A/B on the console stand-in (minastirith)

Verified 2026-11-03 on minastirith (16 cores, no GPU, MAME 0.285). The tooling lives in `tools/mamelab/`; run it with
`~/Code/robotron-rl/.venv-collision/bin/python` (below: `$PY`). Server layout: [MINASTIRITH.md](MINASTIRITH.md).

```bash
cd ~/Code/robotron_ai          # or any checkout/worktree of this repo
PY=~/Code/robotron-rl/.venv-collision/bin/python
$PY tools/mamelab/run_ab.py --help
```

## What there is

| file | role |
|---|---|
| `tools/mamelab/run_ab.py` | runner: N games per arm, 16 workers, one fresh MAME process per game, arm A / arm B envs, shared seeds |
| `tools/mamelab/mame_lab_pkg.py` | lab game loop that calls `robotron_ai.brain.ChampionBrain` (console code), with the console defect model |
| `tools/mamelab/ab_stats.py` | mean wave, d/w, NET, paired B-A difference with 95% bootstrap CI (stdlib only) |
| `tools/mamelab/labpaths.py` | the configurable paths (table below) |
| `tools/mamelab/pin_checkout.sh` | `git archive` a rev into the pinning dir and print the path for `--checkout` |
| `tools/analyze_collision_mame.py` | validity filter + W5-25 band; shared with `run_collision_mame_fresh.py`, imported by run_ab and ab_stats |
| `~/Code/robotron/mame_lab.py` | the OLD ("legacy") lab loop, driven by `tools/run_collision_mame_fresh.py` |

### Paths and external dependencies

The lab is not self-contained. It needs the MAME gym, the ROM and `/usr/games/mame` (see MINASTIRITH.md) and, for the
dev tree, `mame_score.py` (pkg lab) or the whole set of frozen sources (legacy lab). The dev tree has no git remote and is
**not vendored** here. Each default can be overridden by an environment variable (run_ab also has `--out-root`).

| what | default | override |
|---|---|---|
| MAME gym, ROM, `.venv-collision` | `~/Code/robotron-rl` | `MAMELAB_RL` |
| dev tree (`mame_score.py`; legacy lab sources) | `~/Code/robotron` | `MAMELAB_DEV` |
| results root | `~/Code/robotron_data/mamelab/results` | `MAMELAB_RESULTS` or `--out-root` |
| pinned checkouts | `~/Code/robotron_data/mamelab/ck` | `MAMELAB_CK` or `pin_checkout.sh REV DEST` |
| `--checkout` default | the repo that holds `run_ab.py` | `--checkout PATH` |

Two labs, they are NOT the same decision code:

* `--lab legacy` (= what `tools/run_collision_mame_fresh.py` does): `~/Code/robotron/mame_lab.py` with the dev-tree
  copies of `clearance_planner.py` / `robotron_fsm.py`. It does not import `robotron_ai` at all. Its own `Tracker`
  (identity-stable by memory address, keeps velocity through a dropout), no ProjectileCoaster, no VelocityTracker,
  planner margins 18/10 (not the vision 21/12), FIRE_ALT radius 160 unless set, FIREPLAN forced on. Every vision-path
  default must be passed by hand. Source is frozen into the run dir at start.
* `--lab pkg` (new, default): same MAME gym, same defect model, same LAB_* knobs, but the decision is
  `ChampionBrain(use_coaster=True).decide()` from whatever `robotron_ai` checkout you point at: VelocityTracker,
  ProjectileCoaster, engine/robotron_fsm.py, engine/clearance_planner.py, vision-path pinning (margins 21/12, FIREPLAN
  on, FIRE_ALT on at R=400). Detections are fed as (x, y, name) with 2 px noise and 10% miss rate; no velocities, no ids.
  The first line of every `.out` file prints the brain path and the effective planner settings; check it.

## 0. Pin the code under test (do this, the worktree may be edited while a batch runs)

```bash
CK=$(tools/mamelab/pin_checkout.sh main)        # -> ~/Code/robotron_data/mamelab/ck/main-<sha>/robotron_ai
# which is: git archive --prefix=robotron_ai/ main | tar -x -C <ck>/main-<sha>
```
(a branch, tag or SHA. For a worktree with uncommitted changes pass its path directly; the manifest records
HEAD and a hash of `git diff HEAD`.)

## 1. Knob A/B (same code, arm B has X=Y)

```bash
$PY tools/mamelab/run_ab.py --lab pkg \
  --checkout "$CK" \
  --games 300 --workers 16 --act-frames 8 \
  --prefix myknob_$(date +%m%d) --a-name base --b-name knob \
  --b-env VSEARCH_SOMETHING=1          # arm A = package defaults
```
* `--act-frames 8` = LAB_ACT_FRAMES=8, the console stand-in (default in run_ab.py). 4 = the old standard calibration.
* `--env K=V` applies to both arms, `--a-env` / `--b-env` to one. Allowed prefixes: `LAB_ VSEARCH_ FSM_ ROBOTRON_`
  (`FSM_OVERRIDE_<CONST>=v` overrides an FSM constant). Knob names are in `robotron_ai/knobs.py`.
* Env pinning rules (brain.py): setting `VSEARCH_CLEAR_DANGER/MARGIN`, `VSEARCH_FIREPLAN`, or `VSEARCH_FIRE_ALT` pins
  it and disables the vision default; e.g. "fire_alt off" = `--a-env VSEARCH_FIRE_ALT=0`. Setting only one of
  DANGER/MARGIN leaves the other at the 18/10 import default and drops BOTH 21/12 pins, so set both.
* Since 2026-11 the package brain's vision defaults also include `FSM_FIRE_SKIP_RECEDING=1` and
  `FSM_FIRE_FALLBACK_REACH=250` (each pinned independently; `=0` turns it off). A default-config arm A therefore
  includes them: old "knob off" baselines now need `--a-env FSM_FIRE_SKIP_RECEDING=0 --a-env FSM_FIRE_FALLBACK_REACH=0`.
* Other `LAB_*` for both arms: `--calibration LAB_DROP=0.05` etc. Defaults: K=1 LEAD=1.5 LAG=0.7 DROP=.10 PDROP=.02 NOISE=2.
* Same trial index = same MAME game seed (`MAME_RL_SEED_BASE`) AND same defect RNG seed in both arms
  (`--independent-defects` to decouple). Arm ports 23000+trial / 25000+trial; do not start two batches at once
  (CPU is the limit; if you must overlap, `--port-base` values must differ by >= 4000: arm B uses base+2000). Replaced invalid games take new trial numbers,
  so ab_stats pairs only on trials valid in both arms.
* Results: `$MAMELAB_RESULTS/<prefix>/` (default `~/Code/robotron_data/mamelab/results/<prefix>/`) : `manifest.json`, `episodes.jsonl` (one line per game: arm, trial, wave,
  score, deaths, steps, seconds), `<prefix>_<arm>_<port>.{out,jsonl,mame.log}`, `summary.json` (project analyzer).
  Stop a batch cleanly: `touch results/<prefix>/STOP` (or SIGTERM the run_ab.py PID); each game's process group is
  killed on exit, so no stray MAME.

## 2. Code A/B (two checkouts, e.g. a branch vs main)

Pin both revs, then the same command with `--checkout A_path --checkout-b B_path` (both `.../robotron_ai` dirs), no `--b-env`:

```bash
A=$(tools/mamelab/pin_checkout.sh main); B=$(tools/mamelab/pin_checkout.sh my-branch)
$PY tools/mamelab/run_ab.py --lab pkg --checkout "$A" --checkout-b "$B" --games 300 --prefix code_$(date +%m%d)
```

## 3. Numbers

```bash
$PY tools/mamelab/ab_stats.py ~/Code/robotron_data/mamelab/results/<prefix> [--json out.json]
```
(plain python3 also works; stdlib only.) Prints per arm: games, mean/median max wave, deaths/wave (W5-25 band), score/wave,
NET = score/25000 - d/w (wave-weighted, same definition as analyze_collision_mame / native_stats), then B-A for
wave, d/w, NET with a paired (resample trials) 95% bootstrap CI and the unpaired CI, plus per-trial win/tie/loss.
Observed: pairing buys almost nothing (A-B per-game wave correlation ~0 +/- 0.1, paired and unpaired CIs coincide),
so the CI width is set by N. The project's own CI (`summary.json comparisons_to_baseline`) is the unpaired one.
Game cap: `--cap-wave 26`, i.e. mean max wave saturates near 26; use it for W5-25 questions, not late waves.

## 4. Legacy lab (reproduces the old numbers)

```bash
$PY tools/mamelab/run_ab.py --lab legacy \
  --games 144 --prefix legacy_x --a-name base --b-name firealt --b-env VSEARCH_FIRE_ALT=1
```
(equivalent to the Sept 16 `actlag8_20260916` run: `tools/run_collision_mame_fresh.py --games 144 --workers 12
--candidate-name firealt --candidate-env VSEARCH_FIRE_ALT=1 --calibration LAB_ACT_FRAMES=8 --seed-base 34097429`.)
That script writes to `<repo>/logs/<prefix>` (inside the checkout it is run from) and reads the dev tree, not the package.

## Settings that matter

* **ACT 8 vs ACT 4** (`--act-frames`, = `LAB_ACT_FRAMES`, frames of actuation delay; 4 frames = one 15 Hz tick). The default
  is 8, the "console stand-in" calibration inherited from the legacy lab. For the package lab, ACT 8 is harsher than the
  console (fire_alt off 8.2 W vs the console's ~12 W) and ACT 4 matches the console's wave numbers (10.7 W without,
  16.8 W with fire_alt vs the console's ~12 and 16-17.5). Use `--act-frames 4` when you want absolute levels near the
  console's; paired knob effects agree at both. Details under "Facts established" below.
* **Port spacing**: arm A uses ports `port-base + trial`, arm B `port-base + 2000 + trial` (default base 23000). Two
  batches running at once need `--port-base` values at least 4000 apart (e.g. 23000 and 27000), or the ports collide.
  Prefer not to overlap at all: CPU is the limit.
* **`LAB_FRAMESKIP=4`**: frames per decision (4 = 15 Hz). `mame_lab_pkg.py` asserts it: the package brain is tuned in 15 Hz
  ticks, so do not set another value for `--lab pkg`. (The legacy lab accepts 2 = 30 Hz and scales its tick.)
* **Wave-26 cap** (`--cap-wave 26`): a game ends at wave 26, so the mean max wave saturates near 26. The analysis band is
  W5-25. Use this lab for W5-25 questions, not late waves.
* **Throughput**: about 1,400 games/hour on 16 workers (~24-28 s per game). 300 games/arm = 600 games takes about 30-40 min
  including the ~5% invalid-game replacements and the tail. Run nothing else CPU-heavy meanwhile.

## Wall time

Measured: 96 games (48/arm) at 16 workers = 2.5-4 min wall (~24-28 s per game, tail-bound), ~1,400-1,500 games/h.
300 games/arm = 600 games: about 25-30 min (pkg lab ~25, legacy ~30). Allow 30-40 min with the 5% invalid replacements
and the tail. Do not run anything else CPU-heavy meanwhile.

## Statistical power (from the above)

N=48/arm gives NET CI half-width ~0.08, wave CI half-width ~1.5-3. N=300/arm: NET about +/-0.03, wave about +/-1.

## Facts established 2026-11-03

* Determinism: same code + same seed-base + same env gives bit-identical games (A=B null test: 6/6 identical episodes;
  re-running arm A in two batches gave 13.06 waves / 1.181 d/w both times). So all A/B difference comes from the knob; use a
  new `--seed-base` for a fresh sample, and keep it fixed to replicate.
* Calibration (all 48/arm, seed-base 34097429):
  legacy lab ACT 8: base 12.50 W / 1.285 d/w, fire_alt(R160) 19.44 W / 1.131, NET delta +0.150
  (old actlag8 run, 144/arm: 13.02 / 1.281, 19.42 / 1.152, +0.146).
  pkg lab ACT 8: fire_alt off 8.21 W / 1.387, package default 13.06 W / 1.181, NET delta +0.176 [+0.10, +0.26].
  pkg lab ACT 4: fire_alt off 10.69 W / 1.315, package default 16.75 W / 1.157, NET delta +0.181 [+0.12, +0.24].
  Console (rounds 14-16): ~12 W without, 16-17.5 W with fire_alt, d/w 1.04-1.33. So the package-brain lab at ACT 4 sits on
  the console's wave numbers, the legacy lab needs ACT 8 for the same; the package lab at ACT 8 is harsher than the console.
  Which ACT is "the console" for the pkg lab is therefore undecided; the legacy lab's ACT 8 calibration was fitted to a
  different tracker. Re-fit before trusting absolute levels; paired knob effects (sign, rough size) agree across all of them.
* Planner margins sanity on pkg lab ACT 8: 21/12 (vision pin) vs 18/10 gives 13.06 vs 11.75 W, NET -0.068 [-0.12, -0.02] for 18/10.
