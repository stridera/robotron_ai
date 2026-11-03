#!/usr/bin/env python3
"""ab_stats.py - paired statistics for a run_ab.py result directory.

  python3 tools/mamelab/ab_stats.py ~/Code/robotron_data/mamelab/results/<prefix> [--band 5 25] [--boot 10000]

Reports per arm: games, mean/median max wave, deaths/wave (d/w), score/wave,
NET = score/25000 - d/w (wave-weighted over the band, same as the project's
analyze_collision_mame / native_stats), then the PAIRED difference B - A with a
95% bootstrap CI (resampling trials, a trial = the same MAME game seed in both
arms), plus the unpaired CI for comparison. Only trials valid in both arms
count. Stdlib only.
"""
import argparse, json, random, statistics, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))             # tools/analyze_collision_mame.py
from analyze_collision_mame import load   # noqa: E402


def agg(games):
    n = sum(g["n"] for g in games)
    if not n:
        return None
    d = sum(g["d"] for g in games) / n
    s = sum(g["s"] for g in games) / n
    return dict(dw=d, spw=s, net=s / 25000 - d)


def waves(games):
    return statistics.mean(g["wave"] for g in games)


def pct(v, q):
    return v[min(len(v) - 1, max(0, int(q * len(v))))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("directory", type=Path)
    ap.add_argument("--band", type=int, nargs=2, default=(5, 25))
    ap.add_argument("--boot", type=int, default=10000)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    man = json.loads((a.directory / "manifest.json").read_text())
    names, prefix, base = man["names"], man["prefix"], man["port_base"]
    arms, excl = load(a.directory, prefix, band=tuple(a.band))
    by = []
    for i, nm in enumerate(names):
        d = {}
        for g in arms.get(f"{prefix}_{nm}", []):
            port = int(g["game"].rsplit("-", 2)[1])
            d[port - base - (0 if i == 0 else 2000)] = g
        by.append(d)
    common = sorted(by[0].keys() & by[1].keys())
    out = dict(prefix=prefix, names=names, band=a.band, exclusions=dict(excl),
               paired_trials=len(common), arms={})
    for i, nm in enumerate(names):
        gs = list(by[i].values())
        inb = [g for g in gs if g["n"]]
        m = agg(gs)
        out["arms"][nm] = dict(games=len(gs), mean_wave=waves(gs), median_wave=statistics.median(g["wave"] for g in gs),
                               band_games=len(inb), **(m or {}))
    A = [by[0][t] for t in common]
    B = [by[1][t] for t in common]
    rng = random.Random(2084)
    keys = ("wave", "dw", "net")
    pt = dict(wave=waves(B) - waves(A), dw=agg(B)["dw"] - agg(A)["dw"], net=agg(B)["net"] - agg(A)["net"])
    boots = {k: [] for k in keys}
    ub = {k: [] for k in keys}
    for _ in range(a.boot):
        idx = [rng.randrange(len(common)) for _ in common]
        ra, rb = [A[j] for j in idx], [B[j] for j in idx]
        boots["wave"].append(waves(rb) - waves(ra))
        ma, mb = agg(ra), agg(rb)
        if ma and mb:
            boots["dw"].append(mb["dw"] - ma["dw"]); boots["net"].append(mb["net"] - ma["net"])
        ua = [rng.choice(A) for _ in A]; ub_ = [rng.choice(B) for _ in B]
        ub["wave"].append(waves(ub_) - waves(ua))
        xa, xb = agg(ua), agg(ub_)
        if xa and xb:
            ub["dw"].append(xb["dw"] - xa["dw"]); ub["net"].append(xb["net"] - xa["net"])
    out["paired_diff_B_minus_A"] = {}
    for k in keys:
        s = sorted(boots[k]); u = sorted(ub[k])
        out["paired_diff_B_minus_A"][k] = dict(
            diff=pt[k], ci95=[pct(s, .025), pct(s, .975)], unpaired_ci95=[pct(u, .025), pct(u, .975)])
    wl = [(b["wave"] > x["wave"]) - (b["wave"] < x["wave"]) for x, b in zip(A, B)]
    out["per_trial_wave"] = dict(B_wins=wl.count(1), ties=wl.count(0), A_wins=wl.count(-1),
                                 corr=None)
    try:
        out["per_trial_wave"]["corr"] = statistics.correlation([g["wave"] for g in A], [g["wave"] for g in B])
    except Exception:
        pass
    print(f"{prefix}  arms A={names[0]} B={names[1]}  band W{a.band[0]}-{a.band[1]}  paired trials={len(common)}")
    for nm, v in out["arms"].items():
        print(f"  {nm:>10}: n={v['games']:4d} meanW={v['mean_wave']:6.2f} medW={v['median_wave']:5.1f} "
              f"d/w={v.get('dw', float('nan')):.3f} score/w={v.get('spw', float('nan')):8.0f} NET={v.get('net', float('nan')):+.3f}")
    for k, v in out["paired_diff_B_minus_A"].items():
        print(f"  B-A {k:>4}: {v['diff']:+.3f}  paired 95% [{v['ci95'][0]:+.3f}, {v['ci95'][1]:+.3f}]"
              f"   unpaired [{v['unpaired_ci95'][0]:+.3f}, {v['unpaired_ci95'][1]:+.3f}]")
    p = out["per_trial_wave"]
    print(f"  per-trial wave: B wins {p['B_wins']}, ties {p['ties']}, A wins {p['A_wins']}; "
          f"A-B wave correlation {p['corr']}")
    if excl:
        print("  excluded:", dict(excl))
    if a.json:
        a.json.write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
