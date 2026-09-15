"""Video-only replay of closest-pair projectile association.

Conditions on recorded commands. Action changes and prediction competition are
not true identity labels, alternative trajectories, or prevented deaths.
"""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from robotron_ai.brain import ChampionBrain


def audit(path):
    trace = [json.loads(s) for s in (path/'decisions.jsonl').read_text().splitlines()]
    results = []
    for enabled in (False, True):
        brain = ChampionBrain(.7, 1.5, use_coaster=True, normalize_tracking_time=False)
        brain.coaster.closest_pairs = enabled
        outputs = []
        start = time.perf_counter()
        for r in trace:
            if r['control_player'] is None:
                if r['entities']:
                    brain.blind_tick(r['entities'], sampled_at=r['sampled_at'])
            else:
                action = brain.decide(r['control_player'], r['entities'], sampled_at=r['sampled_at'])
                outputs.append(dict(t=r['t'], action=list(action), recorded=[r['move'],r['fire']]))
                brain.last_mv = r['move']
        results.append(dict(seconds=time.perf_counter()-start, outputs=outputs))
    base, candidate = results
    changes = [dict(t=a['t'], base=a['action'], candidate=b['action'])
               for a,b in zip(base['outputs'],candidate['outputs']) if a['action']!=b['action']]
    return dict(path=str(path), decisions=len(base['outputs']),
                baseline_mismatches=sum(a['action']!=a['recorded'] for a in base['outputs']),
                changed=len(changes), changes=changes,
                base_seconds=base['seconds'], candidate_seconds=candidate['seconds'])


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--game', action='append', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    result = dict(note=__doc__, games=[audit(p) for p in args.game])
    with args.output.open('x') as f:
        json.dump(result, f, indent=2)
    print(json.dumps([{k:v for k,v in g.items() if k!='changes'} for g in result['games']],indent=2))
