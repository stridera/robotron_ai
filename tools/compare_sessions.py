"""Compare console sessions: is arm B better than arm A, and by how much?

    python -m robotron_ai.tools.compare_sessions logs/sessions/*_base logs/sessions/*_margins24
    python -m robotron_ai.tools.compare_sessions A_folder B_folder [C_folder ...] [--trace]

Each argument is a session folder (or a glob of them) holding report.json;
folders with the same tag are pooled into one arm, in the order first seen.
The first arm is the baseline; every other arm is compared against it.

What it reports per arm, from report.json alone (fast):
  games, mean and median max wave, deaths per wave BY THE LIFE ECONOMY
  (3 + score/25000 per game, exact at game over; the HUD tally is a lower
  bound), score per wave, NET lives per wave (bought minus lost), and the
  knobs that differed from the baseline.

Per comparison: the difference in mean max wave and in NET with a
bootstrap 95% interval and a Welch p-value. Ten games an arm resolve a
change of roughly five waves in the mean; below that, run another ten
before believing it either way.

With --trace it also loads decisions.jsonl (large, ~10 s a session) for the
reversal latency in milliseconds, which is the number that says whether a
change moved the loop rather than the play.
"""
import argparse
import glob
import json
import math
import os
import random
import statistics as st
import sys
from collections import OrderedDict

EXTRA_MAN_EVERY = 25000
START_LIVES = 3


def load_report(folder):
    path = folder if folder.endswith(".json") else os.path.join(folder, "report.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f), os.path.dirname(path) or "."


def game_rows(rep):
    """(max_wave, score, deaths_by_economy) per finished game."""
    out = []
    for g in rep.get("games") or []:
        w, s = g.get("wave") or 0, g.get("score") or 0
        if w <= 0:
            continue
        bought = g.get("lives_bought")
        if bought is None:
            bought = START_LIVES + s // EXTRA_MAN_EVERY
        out.append(dict(wave=int(w), score=int(s), deaths=int(bought)))
    return out


def arm_summary(name, games, knobs, config, reports):
    waves = [g["wave"] for g in games]
    tot_w = sum(waves) or 1
    tot_s = sum(g["score"] for g in games)
    tot_d = sum(g["deaths"] for g in games)
    per_game_net = [(g["score"] / EXTRA_MAN_EVERY - g["deaths"]) / max(g["wave"], 1)
                    for g in games]
    return dict(
        arm=name, games=len(games), waves=waves,
        mean_wave=round(st.mean(waves), 1) if waves else None,
        median_wave=st.median(waves) if waves else None,
        record=max(waves) if waves else None,
        deaths_per_wave=round(tot_d / tot_w, 3),
        score_per_wave=round(tot_s / tot_w),
        net_per_wave=round((tot_s / EXTRA_MAN_EVERY - tot_d) / tot_w, 3),
        net_per_game=per_game_net,
        knobs=knobs or {}, config=config or {}, sessions=len(reports),
        tick_ms=_tick_ms(reports),
    )


def _tick_ms(reports):
    hz = [r.get("tick", {}).get("hz") for r in reports if r.get("tick", {}).get("hz")]
    return round(1000.0 / st.mean(hz), 1) if hz else None


def bootstrap_diff(a, b, n=4000, seed=2084):
    """95% interval on mean(b) - mean(a)."""
    if not a or not b:
        return None
    rnd = random.Random(seed)
    diffs = []
    for _ in range(n):
        sa = [rnd.choice(a) for _ in a]
        sb = [rnd.choice(b) for _ in b]
        diffs.append(st.mean(sb) - st.mean(sa))
    diffs.sort()
    return (round(st.mean(b) - st.mean(a), 2),
            round(diffs[int(0.025 * n)], 2), round(diffs[int(0.975 * n)], 2))


def welch_p(a, b):
    """Two-sided Welch t-test p-value (normal approximation of the t
    distribution for the small samples we have; good to a few percent)."""
    if len(a) < 2 or len(b) < 2:
        return None
    va, vb = st.variance(a), st.variance(b)
    se = math.sqrt(va / len(a) + vb / len(b))
    if se == 0:
        return 1.0 if st.mean(a) == st.mean(b) else 0.0
    t = (st.mean(b) - st.mean(a)) / se
    df = (va / len(a) + vb / len(b)) ** 2 / (
        (va / len(a)) ** 2 / (len(a) - 1) + (vb / len(b)) ** 2 / (len(b) - 1))
    # Student t survival via the incomplete beta is overkill here; use the
    # normal tail with a small-df correction that is within ~0.01 for df>=8.
    z = abs(t) * (1 - 1 / (4 * df)) / math.sqrt(1 + t * t / (2 * df))
    p = math.erfc(z / math.sqrt(2))
    return round(min(1.0, p), 3)


def knob_diff(base, other):
    out = {}
    for k in sorted(set(base) | set(other)):
        if base.get(k) != other.get(k):
            out[k] = (base.get(k), other.get(k))
    return out


def collect(paths):
    """Expand globs, load reports, pool by tag (folder name when untagged)."""
    arms = OrderedDict()
    for pat in paths:
        hits = sorted(glob.glob(pat)) or [pat]
        for p in hits:
            if not (os.path.isdir(p) or p.endswith(".json")):
                continue
            try:
                rep, folder = load_report(p)
            except (OSError, ValueError) as e:
                print(f"skipping {p}: {e}", file=sys.stderr)
                continue
            name = rep.get("tag") or os.path.basename(os.path.normpath(folder))
            arm = arms.setdefault(name, dict(games=[], reports=[], knobs=None, config=None))
            arm["games"] += game_rows(rep)
            arm["reports"].append(rep)
            if arm["knobs"] is None:
                arm["knobs"] = rep.get("knobs") or {}
                arm["config"] = rep.get("config") or {}
            arm.setdefault("folders", []).append(folder)
    return arms


def reversal_ms(folder):
    from ..trace_report import reversal_latency
    path = os.path.join(folder, "decisions.jsonl")
    if not os.path.exists(path):
        return None
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    rl = reversal_latency(rows)
    return dict(seen_by_ms=rl.get("seen_by_ms"), not_yet_ms=rl.get("not_yet_ms"),
                estimate_ms=rl.get("estimate_ms"), estimate_err_ms=rl.get("estimate_err_ms"),
                ticks=rl.get("median"), n=rl.get("reversals"))


def compare(arms, trace=False):
    summaries = [arm_summary(n, a["games"], a["knobs"], a["config"], a["reports"])
                 for n, a in arms.items()]
    if trace:
        for s, (n, a) in zip(summaries, arms.items()):
            rs = [reversal_ms(f) for f in a.get("folders", [])]
            rs = [r for r in rs if r and r["seen_by_ms"] is not None]
            est = [r["estimate_ms"] for r in rs if r.get("estimate_ms") is not None]
            s["reversal"] = (dict(seen_by_ms=round(st.mean(r["seen_by_ms"] for r in rs)),
                                  not_yet_ms=round(st.mean(r["not_yet_ms"] for r in rs)),
                                  estimate_ms=round(st.mean(est)) if est else None)
                             if rs else None)
    base = summaries[0] if summaries else None
    comps = []
    for s in summaries[1:]:
        comps.append(dict(
            arm=s["arm"], versus=base["arm"],
            mean_wave=bootstrap_diff(base["waves"], s["waves"]),
            mean_wave_p=welch_p(base["waves"], s["waves"]),
            net_per_wave=bootstrap_diff(base["net_per_game"], s["net_per_game"]),
            net_p=welch_p(base["net_per_game"], s["net_per_game"]),
            knobs_changed=knob_diff(base["knobs"], s["knobs"]),
            config_changed=knob_diff(base["config"], s["config"]),
        ))
    return dict(arms=summaries, comparisons=comps)


def render(rep):
    L = []
    L.append(f"{'arm':<22}{'games':>6}{'mean W':>8}{'med W':>7}{'best':>6}"
             f"{'d/wave':>8}{'pts/wave':>10}{'NET/wave':>10}{'tick ms':>9}")
    for s in rep["arms"]:
        L.append(f"{s['arm'][:22]:<22}{s['games']:>6}{s['mean_wave'] or 0:>8.1f}"
                 f"{s['median_wave'] or 0:>7.1f}{s['record'] or 0:>6}"
                 f"{s['deaths_per_wave']:>8.3f}{s['score_per_wave']:>10}"
                 f"{s['net_per_wave']:>+10.3f}{(s['tick_ms'] or 0):>9.1f}")
        if s.get("reversal"):
            r = s["reversal"]
            L.append(f"{'':<22}  loop latency ~{r['estimate_ms']} ms (phase-corrected; "
                     f"response seen by {r['seen_by_ms']}, not yet at {r['not_yet_ms']})"
                     if r.get("estimate_ms") is not None else
                     f"{'':<22}  reversal response seen by {r['seen_by_ms']} ms, "
                     f"not yet at {r['not_yet_ms']} ms")
    L.append("  d/wave and NET use lives bought (3 + score/25000): exact at game over.")
    L.append("  A bleed (NET) of -0.08 lasts ~37 waves from 3 lives; wave 100 needs NET > -0.03.")
    for c in rep["comparisons"]:
        L.append("")
        L.append(f"{c['arm']} vs {c['versus']}:")
        mw = c["mean_wave"]
        if mw:
            L.append(f"  mean max wave {mw[0]:+.1f}  (95% {mw[1]:+.1f} .. {mw[2]:+.1f}, "
                     f"p={c['mean_wave_p']})")
        nw = c["net_per_wave"]
        if nw:
            L.append(f"  NET lives/wave {nw[0]:+.3f}  (95% {nw[1]:+.3f} .. {nw[2]:+.3f}, "
                     f"p={c['net_p']})")
        if c["knobs_changed"]:
            L.append("  knobs changed: " + ", ".join(
                f"{k} {a}->{b}" for k, (a, b) in c["knobs_changed"].items()))
        if c["config_changed"]:
            L.append("  settings changed: " + ", ".join(
                f"{k} {a}->{b}" for k, (a, b) in c["config_changed"].items()))
        if not c["knobs_changed"] and not c["config_changed"]:
            L.append("  (no recorded knob or setting differs: a repeat of the same arm)")
        verdict = ("real" if (mw and (mw[1] > 0 or mw[2] < 0)) else
                   "not resolved at this sample size")
        L.append(f"  verdict on depth: {verdict}")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("sessions", nargs="+", help="session folders, globs, or report.json files")
    ap.add_argument("--trace", action="store_true",
                    help="also read decisions.jsonl for the reversal latency in ms (slow)")
    ap.add_argument("--json", default=None, help="write the comparison here as JSON")
    a = ap.parse_args(argv)
    arms = collect(a.sessions)
    if not arms:
        sys.exit("no report.json found in the given sessions")
    rep = compare(arms, trace=a.trace)
    print(render(rep))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=1)
    return rep


if __name__ == "__main__":
    main()
