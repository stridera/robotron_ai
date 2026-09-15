"""Replay four accepted control seeds through generator and no-op actor.

No learning here: full episode totals must match the pre-refactor lab exactly.
Run only after the score repair batch has finished (shared test ports).
"""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil

import numpy as np

from run_collision_mame_fresh import REPO, DEV, one_game


def main():
    original = REPO / 'logs/night_20260909_screen_shot4'
    manifest = json.loads((original / 'manifest.json').read_text())
    episodes = [json.loads(s) for s in (original / 'episodes.jsonl').read_text().splitlines()]
    controls = [e for e in episodes if e['valid'] and e['variant'] == 1][:4]
    root = REPO / 'logs/residual_parity_20260909'
    root.mkdir(exist_ok=False)
    import sys
    sys.path.insert(0, str(DEV))
    from residual_policy import FEATURE_DIM
    actor = root / 'noop.npz'
    np.savez(actor, feature_dim=FEATURE_DIM, layers=0,
             wa=np.zeros((3, FEATURE_DIM)), ba=np.log([.98, .01, .01]))
    reports = []
    for mode in ('generator', 'actor'):
        out = root / mode
        source = out / 'source'
        source.mkdir(parents=True)
        for name in ('clearance_planner.py', 'robotron_fsm.py', 'fsm_evolved_planner_v2_hunt.json'):
            shutil.copy2(original / 'source' / name, source / name)
        for name in ('mame_lab.py', 'mame_score.py', 'residual_policy.py'):
            shutil.copy2(DEV / name, source / name)
        calibration = dict(manifest['calibration'])
        if mode == 'actor':
            calibration['LAB_RESIDUAL_MODEL'] = str(actor)
        def run(e):
            result = one_game(out, manifest['prefix'], 1, e['trial'],
                              calibration=calibration, seed_base=manifest['seed_base'])
            result['identical'] = result['valid'] and result['episode'] == e['episode']
            result['mode'] = mode
            return result
        with ThreadPoolExecutor(max_workers=4) as pool:
            for result in pool.map(run, controls):
                print(json.dumps(result), flush=True)
                reports.append(result)
    (root / 'results.json').write_text(json.dumps(reports, indent=2))
    if not all(r['identical'] for r in reports):
        raise RuntimeError('No-op execution changed a control episode')


if __name__ == '__main__':
    main()
