"""Video-only replay of suppressing ghosts until their second detection.

Reports baseline action parity, singleton ghost exposure and candidate action
sensitivity. Tracks retain their normal association and expiry. Recorded
commands are fed back, so this is not a rollout or avoided-death estimate.
No oracle input; detection identities and ghost false positives are unverified.
"""
import argparse
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from robotron_ai.brain import ChampionBrain


def audit(path):
    trace = [json.loads(s) for s in (path/'decisions.jsonl').read_text().splitlines()]
    outputs = []
    exposures = []
    for enabled in (False, True):
        brain = ChampionBrain(.7, 1.5, use_coaster=True, normalize_tracking_time=False)
        brain.coaster.confirmed_ghosts = enabled
        actions = []
        for r in trace:
            if r['control_player'] is None:
                if r['entities']:
                    brain.blind_tick(r['entities'], sampled_at=r['sampled_at'])
            else:
                action = brain.decide(r['control_player'], r['entities'], sampled_at=r['sampled_at'])
                actions.append(dict(t=r['t'], action=list(action), recorded=[r['move'], r['fire']]))
                brain.last_mv = r['move']
                if not enabled:
                    singles = [t for t in brain.coaster.tracks if not t['hit'] and not t['confirmed']]
                    if singles:
                        exposures.append(dict(t=r['t'], count=len(singles), nearest=min(
                            math.dist(r['control_player'], [t['x'],t['y']]) for t in singles)))
            brain.record_command(r['move'], controlled=r['control_player'] is not None)
        outputs.append(actions)
    base, candidate = outputs
    changes = [dict(t=a['t'], base=a['action'], candidate=b['action'])
               for a,b in zip(base,candidate) if a['action'] != b['action']]
    return dict(path=str(path), decisions=len(base),
                baseline_mismatches=sum(a['action'] != a['recorded'] for a in base),
                changed=len(changes), changes=changes, exposures=exposures,
                ghost_ticks=len(exposures), near120=sum(e['nearest'] < 120 for e in exposures))


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--game', action='append', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    result = dict(note=__doc__, games=[audit(p) for p in args.game])
    with args.output.open('x') as f:
        json.dump(result, f, indent=2)
    print(json.dumps([{k:v for k,v in g.items() if k not in ('changes','exposures')}
                      for g in result['games']], indent=2))
