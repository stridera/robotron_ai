"""run_ab.py - paired A/B on the MAME console stand-in (fresh MAME per game).

Run with ~/Code/robotron-rl/.venv-collision/bin/python. See docs/MAME_LAB.md.
Generalises tools/run_collision_mame_fresh.py: arm A / arm B each get their own
env, --lab pkg drives the robotron_ai package brain (console code) from any
checkout, game seeds (and optionally defect seeds) are shared per trial.
Results: <out-root>/<prefix>/ (episodes.jsonl, manifest.json, per-game logs).
"""
import argparse, hashlib, json, os, re, shutil, signal, subprocess, sys, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))                 # tools/analyze_collision_mame.py (shared with the fresh runner)
import labpaths                                      # noqa: E402
from analyze_collision_mame import completed_games, load, summarize   # noqa: E402

RL = labpaths.RL
DEV = labpaths.DEV
CAL = dict(LAB_ACT_FRAMES="8", LAB_LEAD="1.5", LAB_K="1", LAB_LAG="0.7",
           LAB_DROP="0.10", LAB_PDROP="0.02", LAB_NOISE="2", MAME_RL_RESEED="1")
STOP = threading.Event()


def one_game(cfg, out, arm_idx, trial):
    arm = cfg["names"][arm_idx]
    full = f"{cfg['prefix']}_{arm}"
    port = cfg["port_base"] + (0 if arm_idx == 0 else 2000) + trial
    stem = out / f"{full}_{port}"
    if STOP.is_set():
        return dict(arm=arm, trial=trial, port=port, valid=False, exit_code=-2, elapsed_s=0, episode=None)
    sd = out / f"states_{port}"
    sd.mkdir()
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("LAB_", "VSEARCH_", "ROBOTRON_", "FSM_", "MAME_", "PYTHONPATH"))}
    env.update(CAL); env.update(cfg["cal"])
    env.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    env.update(cfg["common_env"]); env.update(cfg["arm_env"][arm_idx])
    dseed = (cfg["seed_base"] * 2654435761 + trial * 104729
             + (0 if cfg["paired_defects"] else arm_idx * 65537)) % 4294967296
    env.update(MAME_STATE_DIR=str(sd), LAB_RNG_SEED=str(dseed),
               MAME_LOG=str(stem.with_suffix(".mame.log")),
               MAME_RL_SEED_BASE=str((cfg["seed_base"] + trial * 7919) % 2147483648))
    if cfg["lab"] == "pkg":
        env["PYTHONPATH"] = str(out / ("pkgroot_a" if arm_idx == 0 else "pkgroot_b"))
        script = str(HERE / "mame_lab_pkg.py")
    else:
        script = str(out / "source/mame_lab.py")
    cmd = [sys.executable, "-u", script, "--games", "1", "--arm", full, "--port", str(port),
           "--stepcap", "20000", "--cap-wave", str(cfg["cap_wave"]), "--out", str(stem.with_suffix(".jsonl"))]
    began = time.monotonic()
    with stem.with_suffix(".out").open("w") as log:
        p = subprocess.Popen(cmd, cwd=RL, env=env, stdout=log, stderr=subprocess.STDOUT,
                             start_new_session=True)
        try:
            while True:
                if (out / "STOP").exists():
                    STOP.set()
                if STOP.is_set() or time.monotonic() - began > 900:
                    code = -1; break
                try:
                    code = p.wait(timeout=1); break
                except subprocess.TimeoutExpired:
                    pass
        finally:
            for sig in (signal.SIGTERM, signal.SIGKILL):      # own process group only
                try:
                    os.killpg(p.pid, sig)
                except ProcessLookupError:
                    pass
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
    valid, rej = completed_games(stem.with_suffix(".out").read_text(errors="replace"), full, str(port))
    ok = code == 0 and len(valid) == 1 and not rej
    shutil.rmtree(sd, ignore_errors=True)
    return dict(arm=arm, trial=trial, port=port, valid=ok, exit_code=code,
                elapsed_s=round(time.monotonic() - began, 1),
                episode=next(iter(valid.values()), None), rejected=rej)


def kv(ap, items):
    r = {}
    for it in items or []:
        k, s, v = it.partition("=")
        if not s or not k.startswith(("LAB_", "VSEARCH_", "FSM_", "ROBOTRON_")):
            ap.error(f"bad KEY=VALUE '{it}' (LAB_/VSEARCH_/FSM_/ROBOTRON_ only)")
        r[k] = v
    return r


def main():
    signal.signal(signal.SIGTERM, lambda *_: STOP.set())
    signal.signal(signal.SIGINT, lambda *_: STOP.set())
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lab", choices=("pkg", "legacy"), default="pkg",
                    help="pkg: robotron_ai.brain.ChampionBrain (console code); legacy: ~/Code/robotron mame_lab.py")
    ap.add_argument("--checkout", default=str(labpaths.REPO),
                    help="robotron_ai package checkout to test (pkg lab); default = the checkout this script is in. "
                         "Pin a rev first with tools/mamelab/pin_checkout.sh")
    ap.add_argument("--checkout-b", default=None, help="different checkout for arm B (code A/B)")
    ap.add_argument("--games", type=int, default=48, help="valid games PER ARM")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--prefix", default="ab_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    ap.add_argument("--out-root", default=str(labpaths.RESULTS),
                    help="results root (env MAMELAB_RESULTS); default %(default)s")
    ap.add_argument("--seed-base", type=int, default=34097429)
    ap.add_argument("--port-base", type=int, default=23000,
                    help="arm A ports base, arm B = +2000; concurrent batches need bases >= 4000 apart")
    ap.add_argument("--act-frames", default="8", help="LAB_ACT_FRAMES; 8 = console stand-in")
    ap.add_argument("--cap-wave", type=int, default=26)
    ap.add_argument("--env", action="append", help="KEY=VALUE for BOTH arms")
    ap.add_argument("--a-env", action="append", help="KEY=VALUE arm A only")
    ap.add_argument("--b-env", action="append", help="KEY=VALUE arm B only")
    ap.add_argument("--calibration", action="append", help="override LAB_* defect/latency setting, both arms")
    ap.add_argument("--a-name", default="a"); ap.add_argument("--b-name", default="b")
    ap.add_argument("--independent-defects", action="store_true",
                    help="arm B uses a different defect RNG seed (default: same per trial)")
    args = ap.parse_args()
    names = (args.a_name, args.b_name)
    if names[0] == names[1] or not all(re.fullmatch(r"[a-z][a-z0-9]*", n) for n in names):
        ap.error("arm names must differ and be lowercase alphanumeric")
    cal = dict(LAB_ACT_FRAMES=args.act_frames, **kv(ap, args.calibration))
    cfg = dict(lab=args.lab, names=names, prefix=args.prefix, seed_base=args.seed_base,
               port_base=args.port_base, cap_wave=args.cap_wave, cal=cal,
               common_env=kv(ap, args.env), arm_env=(kv(ap, args.a_env), kv(ap, args.b_env)),
               paired_defects=not args.independent_defects)
    out = Path(args.out_root) / args.prefix
    out.mkdir(parents=True, exist_ok=False)
    man = dict(cfg, games_per_arm=args.games, started=time.time(), act_frames=args.act_frames)
    if args.lab == "pkg":
        co = [Path(args.checkout).resolve(), Path(args.checkout_b or args.checkout).resolve()]
        for tag, c in zip("ab", co):
            (out / f"pkgroot_{tag}").mkdir()
            (out / f"pkgroot_{tag}/robotron_ai").symlink_to(c)
        def git(c, *a):
            return subprocess.run(["git", "-C", str(c), *a], capture_output=True, text=True).stdout.strip()
        man["checkouts"] = [dict(path=str(c), head=git(c, "rev-parse", "HEAD"),
                                 branch=git(c, "rev-parse", "--abbrev-ref", "HEAD"),
                                 dirty_hash=hashlib.sha256(git(c, "diff", "HEAD").encode()).hexdigest()[:12])
                            for c in co]
    else:
        (out / "source").mkdir()
        for n in ("mame_lab.py", "mame_score.py", "residual_policy.py", "clearance_planner.py",
                  "robotron_fsm.py", "fsm_evolved_planner_v2_hunt.json"):
            shutil.copy2(DEV / n, out / "source" / n)
    (out / "manifest.json").write_text(json.dumps(man, indent=2))
    print(f"[ab] {out}: {args.lab} lab, {args.games}/arm, {args.workers} workers, act={args.act_frames}", flush=True)
    counts, attempts = [0, 0], [0, 0]
    budget = max(12, int(args.games * 2 * .05))
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        while min(counts) < args.games and not STOP.is_set():
            futs = []
            rem = [args.games - c for c in counts]
            for off in range(max(rem)):
                for ai in (0, 1):
                    if off < rem[ai]:
                        futs.append(pool.submit(one_game, cfg, out, ai, attempts[ai]))
                        attempts[ai] += 1
            for f in as_completed(futs):
                r = f.result()
                ai = names.index(r["arm"])
                if r["valid"]:
                    counts[ai] += 1
                with (out / "episodes.jsonl").open("a") as lg:
                    lg.write(json.dumps(r) + "\n")
                print(f"[ab] {names[0]}={counts[0]}/{args.games} {names[1]}={counts[1]}/{args.games} "
                      f"last={r['arm']}#{r['trial']} valid={r['valid']} {r['elapsed_s']}s", flush=True)
            if sum(attempts) - sum(counts) > budget:
                raise SystemExit(f"more than {budget} invalid games; look at {out}/*.out and *.mame.log")
    arms, excl = load(out, args.prefix)
    rep = summarize(arms, f"{args.prefix}_{names[0]}", args.games)
    rep.update(exclusions=dict(excl), complete=counts == [args.games] * 2, scope="W5-25 band; MAME proxy")
    (out / "summary.json").write_text(json.dumps(rep, indent=2))
    print(json.dumps(rep["comparisons_to_baseline"], indent=2), flush=True)


if __name__ == "__main__":
    main()
