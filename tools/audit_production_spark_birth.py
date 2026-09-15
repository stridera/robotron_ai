"""Video-only spark birth-velocity forecasts and action replay.

Local single-box continuations are inferred identities, not ground truth.
Replay conditions on recorded commands, never alternative trajectories.
No oracle input. The report is sensitivity evidence, not prevented deaths.
"""
import argparse
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from robotron_ai.brain import ChampionBrain, ProjectileCoaster


def audit(path):
    trace = [json.loads(s) for s in (path/'decisions.jsonl').read_text().splitlines()]
    forecasts = []
    for r, nxt in zip(trace, trace[1:]):
        dt = (nxt['sampled_at']-r['sampled_at'])*15
        if r['control_player'] is None or nxt['control_player'] is None or not .7 < dt < 1.3:
            continue
        for t in r['projectile_tracks']:
            if t['name'] != 'EnforcerBullet' or t['miss'] or t['vx'] or t['vy']:
                continue
            x, y = t['x'], t['y']
            vx, vy = ProjectileCoaster._birth_velocity(x, y, t['name'], r['entities'])
            if vx == vy == 0:
                continue
            near = lambda row: [e for e in row['entities'] if e[2]=='EnforcerBullet'
                                and math.hypot(e[0]-x, e[1]-y)<40]
            after = near(nxt)
            if len(after) != 1 or len(near(r)) != 1:
                continue
            nx, ny, _ = after[0]
            forecasts.append(dict(t=r['t'], x=x, y=y, vx=vx, vy=vy, dt=dt,
                next=after[0], stationary_error=math.hypot(nx-x, ny-y),
                birth_error=math.hypot(nx-x-vx*dt, ny-y-vy*dt)))
    results = []
    for enabled in (False, True):
        brain = ChampionBrain(.7, 1.5, use_coaster=True, normalize_tracking_time=False)
        brain.coaster.spark_birth = enabled
        outputs = []
        start = time.perf_counter()
        for r in trace:
            if r['control_player'] is None:
                if r['entities']:
                    brain.blind_tick(r['entities'], sampled_at=r['sampled_at'])
            else:
                action = brain.decide(r['control_player'], r['entities'], sampled_at=r['sampled_at'])
                outputs.append(dict(t=r['t'], action=list(action), recorded=[r['move'], r['fire']]))
                brain.last_mv = r['move']
        results.append(dict(seconds=time.perf_counter()-start, outputs=outputs))
    base, candidate = results
    changes = [dict(t=a['t'], base=a['action'], candidate=b['action'])
               for a,b in zip(base['outputs'],candidate['outputs']) if a['action']!=b['action']]
    return dict(path=str(path), decisions=len(base['outputs']), forecasts=forecasts,
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
    for g in result['games']:
        fs = g['forecasts']
        print(json.dumps({**{k:v for k,v in g.items() if k not in ('forecasts','changes')},
            'forecast_count':len(fs), 'mean_errors':{k:sum(r[k] for r in fs)/max(1,len(fs))
            for k in ('stationary_error','birth_error')}}))
