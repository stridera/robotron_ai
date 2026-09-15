"""Validate completed MAME episodes before calculating a screen result.

Example (Windows Python, copied logs or a WSL UNC path):
  python tools/analyze_collision_mame.py LOG_DIR PREFIX --expected 144

Unlike the old summary, reject recovered episodes and the following seed-
restarted segment, reject uncompleted episodes, and use the actual max wave
from the episode log. A one-game smoke never gets a bootstrap significance.
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import random
import re
import statistics

GAME = re.compile(r"\[lab\] game (\d+)/(\d+): maxW\s+(\d+)\s+score\s+(\d+)"
                  r"\s+deaths\s+(\d+)\s+steps\s+(\d+)")


def completed_games(text, arm, port):
    valid, rejected = {}, {}
    recovered = False
    for line in text.splitlines():
        if "instance wedged" in line:
            recovered = True
        m = GAME.search(line)
        if m:
            g, _, wave, score, deaths, steps = map(int, m.groups())
            key = f"{arm}-{port}-{g - 1}"
            if recovered:
                rejected[key] = "recovery or subsequent restarted seed sequence"
            elif score == 0 or steps < 100:
                rejected[key] = "zero score or fewer than 100 decisions"
            elif score % 25:
                rejected[key] = "invalid score: not a multiple of 25"
            else:
                valid[key] = dict(wave=wave, score=score, deaths=deaths, steps=steps)
    if "Traceback (most recent call last)" in text:
        rejected.update({key: "worker traceback" for key in valid})
        valid.clear()
    return valid, rejected


def load(directory, prefix, band=(5, 25)):
    arms, exclusions = defaultdict(list), Counter()
    files = sorted(Path(directory).glob(prefix + "_*.jsonl"))
    if not files:
        raise ValueError("No matching per-wave logs")
    for path in files:
        arm, port = path.stem.rsplit("_", 1)
        output = path.with_suffix(".out")
        if not output.exists():
            raise ValueError(f"Missing episode log: {output}")
        valid, rejected = completed_games(output.read_text(encoding="utf-8", errors="replace"), arm, port)
        exclusions.update(rejected.values())
        rows = defaultdict(list)
        for line in path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            rows[r["game"]].append(r)
        for gid in rows.keys() - valid.keys() - rejected.keys():
            exclusions["no completed-episode record"] += 1
        for gid, info in valid.items():
            if gid not in rows:
                exclusions["completed episode missing wave records"] += 1
                continue
            if any(r['score'] < 0 or r['score'] % 25 or r['score'] > 1000000 for r in rows[gid]):
                exclusions['invalid per-wave score'] += 1
                continue
            selected = [r for r in rows[gid] if band[0] <= r["wave"] <= band[1]]
            arms[arm].append(dict(info, game=gid, n=len(selected),
                d=sum(r["deaths"] for r in selected),
                s=sum(r["score"] for r in selected)))
    return arms, exclusions


def metrics(games):
    n = sum(g["n"] for g in games)
    if not n:
        return None
    d = sum(g["d"] for g in games) / n
    s = sum(g["s"] for g in games) / n
    return dict(waves=n, deaths_per_wave=d, score_per_wave=s,
                net_lives_per_wave=s / 25000 - d)


def summarize(arms, baseline, expected, boot=2000):
    result = {}
    for arm, games in sorted(arms.items()):
        band_games = [g for g in games if g["n"]]
        result[arm] = dict(completed_valid_games=len(games), expected_games=expected,
            games_reaching_band=len(band_games),
            mean_max_wave=statistics.mean(g["wave"] for g in games),
            median_max_wave=statistics.median(g["wave"] for g in games),
            aggregate=metrics(games),
            equal_game_mean_net=(statistics.mean((g["s"] / 25000 - g["d"]) / g["n"]
                                  for g in band_games) if band_games else None))
    comparisons = {}
    ctrl = [g for g in arms.get(baseline, []) if g["n"]]
    if len(ctrl) >= 10:
        rng = random.Random(2084)
        for arm, games in sorted(arms.items()):
            candidate = [g for g in games if g["n"]]
            if arm == baseline or len(candidate) < 10:
                continue
            delta = []
            for _ in range(boot):
                a = metrics(rng.choices(candidate, k=len(candidate)))
                b = metrics(rng.choices(ctrl, k=len(ctrl)))
                delta.append(a["net_lives_per_wave"] - b["net_lives_per_wave"])
            delta.sort()
            comparisons[arm] = dict(
                net_delta=metrics(candidate)["net_lives_per_wave"] - metrics(ctrl)["net_lives_per_wave"],
                bootstrap_95=[delta[int(.025 * boot)], delta[int(.975 * boot)]],
                resampling_unit="game; wave-weighted aggregate, matching native_stats")
    return dict(arms=result, comparisons_to_baseline=comparisons)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("directory", type=Path)
    ap.add_argument("prefix")
    ap.add_argument("--expected", type=int, default=144)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    arms, exclusions = load(args.directory, args.prefix)
    report = summarize(arms, args.prefix + "_base", args.expected)
    report["exclusions"] = dict(exclusions)
    report["scope"] = "W5-25 proxy screen only; no late-Xenia or hardware inference"
    report["complete"] = (len(arms) == 2 and all(len(g) == args.expected for g in arms.values()))
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
