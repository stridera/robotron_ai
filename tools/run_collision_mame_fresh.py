"""WSL MAME screen: a fresh emulator process for every game, bounded retries.

Run with the isolated WSL .venv-collision interpreter. Every game has its own
port, reset-state path and MAME diagnostic log. No Xenia may run alongside it.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import signal
import threading

from analyze_collision_mame import completed_games, load, summarize

REPO = Path(__file__).resolve().parents[1]
DEV = REPO.parent / "robotron"
WSL_ROOT = Path("/home/strider/Code/robotron-rl")
CAL = dict(LAB_ACT_FRAMES="4", LAB_LEAD="1.5", LAB_K="1", LAB_LAG="0.7",
           LAB_DROP="0.10", LAB_PDROP="0.02", LAB_NOISE="2", MAME_RL_RESEED="1")
STOP_EVENT = threading.Event()


def one_game(out, prefix, variant, trial, candidate_name="four", candidate_env=None,
             calibration=None, seed_base=0x2084100):
    arm = prefix + ("_base" if variant == 1 else "_" + candidate_name)
    port = (23000 if variant == 1 else 25000) + trial
    if STOP_EVENT.is_set():
        return dict(variant=variant, trial=trial, port=port, valid=False,
                    exit_code=-2, elapsed_s=0, episode=None, rejected={"cancelled": "batch stopped"})
    stem = out / f"{arm}_{port}"
    state_dir = out / f"states_{port}"
    state_dir.mkdir()
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("LAB_", "VSEARCH_", "ROBOTRON_", "FSM_", "MAME_"))}
    env.update(CAL if calibration is None else calibration)
    env.update(OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1')
    env.update(VSEARCH_COLLISION_SUBSTEPS="1", VSEARCH_TURN_STEPS="0")
    if variant != 1:
        env.update(candidate_env if candidate_env is not None else {"VSEARCH_COLLISION_SUBSTEPS": "4"})
    env.update(MAME_STATE_DIR=str(state_dir),
               LAB_RNG_SEED=str((seed_base * 2654435761 + trial * 104729 + variant * 65537) % 4294967296),
               MAME_LOG=str(stem.with_suffix(".mame.log")),
               MAME_RL_SEED_BASE=str((seed_base + trial * 7919) % 2147483648))
    cmd = [sys.executable, "-u", str(out / "source/mame_lab.py"), "--games", "1",
           "--arm", arm, "--port", str(port), "--stepcap", "20000",
           "--cap-wave", "26", "--out", str(stem.with_suffix(".jsonl"))]
    began = time.monotonic()
    with stem.with_suffix(".out").open("w") as log:
        process = subprocess.Popen(cmd, cwd=WSL_ROOT, env=env,
                                   stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        try:
            while True:
                if (out / "STOP").exists():
                    STOP_EVENT.set()
                if STOP_EVENT.is_set() or time.monotonic() - began > 600:
                    code = -1
                    break
                try:
                    code = process.wait(timeout=1)
                    break
                except subprocess.TimeoutExpired:
                    pass
        finally:
            # Own process group includes this game's MAME child, even on a
            # timeout/exception. Never kill unrelated emulator sessions.
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            # Also reap a child emulator that outlived its Python parent.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
    valid, rejected = completed_games(stem.with_suffix(".out").read_text(errors="replace"), arm, str(port))
    ok = code == 0 and len(valid) == 1 and not rejected
    return dict(variant=variant, trial=trial, port=port, valid=ok, exit_code=code,
                elapsed_s=round(time.monotonic() - began, 1),
                episode=next(iter(valid.values()), None), rejected=rejected)


def main():
    signal.signal(signal.SIGTERM, lambda *_: STOP_EVENT.set())
    signal.signal(signal.SIGINT, lambda *_: STOP_EVENT.set())
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--games", type=int, default=144)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--candidate-name", default="four")
    ap.add_argument("--candidate-env", action="append", metavar="KEY=VALUE")
    ap.add_argument("--calibration", action="append", default=[], metavar="KEY=VALUE")
    ap.add_argument("--seed-base", type=int, default=0x2084100)
    ap.add_argument("--prefix", default="collision_fresh_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    args = ap.parse_args()
    if not 1 <= args.games <= 1000 or not 1 <= args.workers <= 16:
        ap.error("games must be 1..1000 and workers 1..16")
    import re
    if not re.fullmatch(r"[a-z][a-z0-9]*", args.candidate_name) or args.candidate_name == "base":
        ap.error("candidate-name must be lowercase alphanumeric and not base")
    def settings(values):
        result = {}
        for value in values:
            key, sep, val = value.partition("=")
            if not sep or not key.startswith(("LAB_", "VSEARCH_", "FSM_", "ROBOTRON_")):
                ap.error("settings require LAB_/VSEARCH_/FSM_/ROBOTRON_ KEY=VALUE")
            result[key] = val
        return result
    candidate_env = settings(args.candidate_env or ["VSEARCH_COLLISION_SUBSTEPS=4"])
    calibration = dict(CAL, **settings(args.calibration))
    invalid_budget = max(12, math.ceil(args.games * 2 * .03))
    out = REPO / "logs" / args.prefix
    out.mkdir(exist_ok=False)
    frozen = out / "source"
    frozen.mkdir()
    sources = [DEV / name for name in ("mame_lab.py", "mame_score.py", "residual_policy.py", "clearance_planner.py",
                                      "robotron_fsm.py", "fsm_evolved_planner_v2_hunt.json")]
    for source in sources:
        shutil.copy2(source, frozen / source.name)
    if candidate_env.get('LAB_RESIDUAL_MODEL'):
        model_source = Path(candidate_env['LAB_RESIDUAL_MODEL']).resolve(strict=True)
        shutil.copy2(model_source, frozen / 'residual_actor.npz')
        candidate_env['LAB_RESIDUAL_MODEL'] = str(frozen / 'residual_actor.npz')
        sources.append(model_source)
    manifest = dict(prefix=args.prefix, games_per_arm=args.games, workers=args.workers,
                    calibration=calibration, candidate_name=args.candidate_name,
                    candidate_env=candidate_env, seed_base=args.seed_base,
                    defect_seed_rule="(seed_base*2654435761 + trial*104729 + variant*65537) % 2**32",
                    invalid_budget=invalid_budget,
                    numeric_threads=1,
                    python=sys.version, started=time.time(),
                    source_hashes={str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in sources + [WSL_ROOT / "mame_gym/robotron_server.lua"]})
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"[fresh] {out}, {args.games} games/arm, {args.workers} workers", flush=True)
    counts = {1: 0, 4: 0}
    attempts = {1: 0, 4: 0}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        while min(counts.values()) < args.games:
            futures = []
            # Interleave submissions. Replacement games use new seeds/ports;
            # they never reuse the invalid episode's state or observations.
            remaining = {v: args.games - counts[v] for v in (1, 4)}
            for offset in range(max(remaining.values())):
                for variant in (1, 4):
                    if offset >= remaining[variant]:
                        continue
                    trial = attempts[variant]
                    attempts[variant] += 1
                    futures.append(pool.submit(one_game, out, args.prefix, variant, trial,
                                               args.candidate_name, candidate_env,
                                               calibration, args.seed_base))
            for future in as_completed(futures):
                result = future.result()
                if result["valid"]:
                    counts[result["variant"]] += 1
                with (out / "episodes.jsonl").open("a") as log:
                    log.write(json.dumps(result) + "\n")
                print(f"[fresh] base={counts[1]}/{args.games} {args.candidate_name}={counts[4]}/{args.games} "
                      f"last={result['variant']} valid={result['valid']} "
                      f"seconds={result['elapsed_s']}", flush=True)
            if STOP_EVENT.is_set():
                raise RuntimeError("Batch cancelled; completed games remain in the episode logs")
            if sum(attempts.values()) - sum(counts.values()) > invalid_budget:
                raise RuntimeError(f"More than {invalid_budget} invalid games; stop and diagnose MAME logs")
    arms, exclusions = load(out, args.prefix)
    report = summarize(arms, args.prefix + "_base", args.games)
    report.update(exclusions=dict(exclusions), complete=all(n == args.games for n in counts.values()),
                  invalid_attempts=sum(attempts.values()) - sum(counts.values()),
                  scope="W5-25 MAME proxy only")
    (out / "summary.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
