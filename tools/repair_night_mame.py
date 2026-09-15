"""Replay rejected overnight trials with measurement-only BCD carry filtering.

Pilot replays two rejected and one accepted trial per arm. Full repair preserves
accepted games and replays rejected seeds once, replacing only still-invalid
episodes with fresh trials. Policies/parameters come from each original snapshot.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import shutil
import signal

from run_collision_mame_fresh import one_game, REPO, DEV, STOP_EVENT
from analyze_collision_mame import load, summarize


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--pilot', action='store_true')
    ap.add_argument('--name', required=True)
    args = ap.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: STOP_EVENT.set())
    signal.signal(signal.SIGINT, lambda *_: STOP_EVENT.set())
    root = REPO / 'logs' / args.name
    root.mkdir(exist_ok=False)
    measurement = root / 'measurement_source'
    measurement.mkdir()
    for name in ('mame_lab.py', 'mame_score.py'):
        shutil.copy2(DEV / name, measurement / name)
    state = json.loads((REPO / 'logs/night_20260909/state.json').read_text())
    stages = [r for r in state['results'] if r['phase'] == 'screen']
    reports = []
    for stage in stages:
        original = REPO / 'logs' / stage['run']
        manifest = json.loads((original / 'manifest.json').read_text())
        episodes = [json.loads(line) for line in (original / 'episodes.jsonl').read_text().splitlines()]
        out = root / stage['name']
        out.mkdir()
        shutil.copytree(original / 'source', out / 'source')
        for name in ('mame_lab.py', 'mame_score.py'):
            shutil.copy2(measurement / name, out / 'source' / name)
        selected = []
        if args.pilot:
            for variant in (1, 4):
                selected += [e for e in episodes if e['variant'] == variant and not e['valid']][:2]
                selected += [e for e in episodes if e['variant'] == variant and e['valid']][:1]
        else:
            selected = [e for e in episodes if not e['valid']]
            for e in episodes:
                if not e['valid']:
                    continue
                arm = stage['run'] + ('_base' if e['variant'] == 1 else '_' + stage['name'])
                for suffix in ('.out', '.jsonl'):
                    fname = f"{arm}_{e['port']}{suffix}"
                    shutil.copy2(original / fname, out / fname)
        audit = dict(original=str(original), pilot=args.pilot,
                     measurement_hashes={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                         for p in measurement.iterdir()},
                     original_manifest=manifest, replayed_trials=selected)
        (out / 'repair_manifest.json').write_text(json.dumps(audit, indent=2))
        print(f"[repair] {stage['name']}: replay {len(selected)} trials", flush=True)

        def replay(e):
            return one_game(out, stage['run'], e['variant'], e['trial'],
                            stage['name'], manifest['candidate_env'],
                            manifest['calibration'], manifest['seed_base'])

        def collect(jobs):
            results = []
            with ThreadPoolExecutor(max_workers=6 if args.pilot else 12) as pool:
                futures = {pool.submit(replay, e): e for e in jobs}
                for future in as_completed(futures):
                    old = futures[future]
                    result = future.result()
                    result['originally_valid'] = old.get('valid', False)
                    if old.get('valid'):
                        result['same_episode_totals'] = result['episode'] == old['episode']
                    results.append(result)
                    with (out / 'repair_episodes.log').open('a') as f:
                        f.write(json.dumps(result) + '\n')
                    print(f"[repair] {stage['name']} {result['variant']}:{result['trial']} "
                          f"valid={result['valid']} identical={result.get('same_episode_totals')}", flush=True)
            return results

        result = collect(selected)
        if STOP_EVENT.is_set():
            raise RuntimeError('Repair stopped; completed trials preserved')
        if not args.pilot:
            next_trial = {v: max(e['trial'] for e in episodes if e['variant'] == v) + 1 for v in (1, 4)}
            failed = [r for r in result if not r['valid']]
            for _ in range(3):
                if not failed:
                    break
                replacements = []
                for r in failed:
                    v = r['variant']
                    replacements.append(dict(variant=v, trial=next_trial[v], valid=False))
                    next_trial[v] += 1
                failed = [r for r in collect(replacements) if not r['valid']]
        arms, exclusions = load(out, stage['run'])
        expected = 3 if args.pilot else 144
        report = summarize(arms, stage['run'] + '_base', expected)
        report.update(exclusions=dict(exclusions), complete=(len(arms) == 2 and
                      all(len(g) == expected for g in arms.values())), pilot=args.pilot,
                      scope='diagnostic replay only' if args.pilot else 'W5-25 repaired MAME screen')
        (out / 'summary.json').write_text(json.dumps(report, indent=2))
        reports.append(dict(name=stage['name'], report=report))
        (root / 'results.json').write_text(json.dumps(reports, indent=2))
    print('[repair] finished', flush=True)


if __name__ == '__main__':
    main()
