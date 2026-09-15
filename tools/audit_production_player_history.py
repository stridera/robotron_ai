"""Video-only turn-lead forecasts and action replay; no oracle input.

Compare fixed 1.5-tick latest-command lead against 0.5 older + 1.0 latest.
Forecast targets interpolate the next two observed player positions, restricted
to fresh interior samples at approximately nominal cadence. These correlated,
selected continuations are diagnostics, not causal avoided-death evidence.
Replay uses recorded commands, not alternative trajectories.
"""
import argparse
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from robotron_ai.brain import ChampionBrain, DXY


def audit(path):
    rows = [json.loads(s) for s in (path/'decisions.jsonl').read_text().splitlines()]
    forecasts = []
    for i in range(2, len(rows)-2):
        seq = rows[i-2:i+3]
        r = rows[i]
        if any(s['player'] is None or s['player_hold_samples'] or s['control_player'] is None for s in seq):
            continue
        if any(not .8 < (y['sampled_at']-x['sampled_at'])*15 < 1.2 for x,y in zip(seq,seq[1:])):
            continue
        if any(not 25 < s['player'][0] < 640 or not 25 < s['player'][1] < 467 for s in seq):
            continue
        old, last = rows[i-2]['move'], rows[i-1]['move']
        if old not in DXY or last not in DXY or old == last:
            continue
        target = [(rows[i+1]['player'][k]+rows[i+2]['player'][k])/2 for k in (0,1)]
        if math.dist(r['player'], target) > 35:
            continue
        base = [r['player'][k]+1.5*DXY[last][k] for k in (0,1)]
        history = [r['player'][k]+DXY[last][k]+.5*DXY[old][k] for k in (0,1)]
        forecasts.append(dict(t=r['t'], base=math.dist(base,target), history=math.dist(history,target)))
    results = []
    for enabled in (False, True):
        brain = ChampionBrain(.7, 1.5, use_coaster=True, normalize_tracking_time=False)
        brain.player_history_lead = enabled
        outputs = []
        for r in rows:
            if r['control_player'] is None:
                if r['entities']:
                    brain.blind_tick(r['entities'], sampled_at=r['sampled_at'])
            else:
                action = brain.decide(r['control_player'], r['entities'], sampled_at=r['sampled_at'])
                outputs.append(dict(t=r['t'], action=list(action), recorded=[r['move'],r['fire']]))
                brain.last_mv = r['move']
            brain.record_command(r['move'], controlled=r['control_player'] is not None)
        results.append(outputs)
    base, candidate = results
    changes = [dict(t=a['t'], base=a['action'], candidate=b['action'])
               for a,b in zip(base,candidate) if a['action'] != b['action']]
    return dict(path=str(path), decisions=len(base),
        baseline_mismatches=sum(a['action'] != a['recorded'] for a in base),
        forecasts=forecasts, forecast_count=len(forecasts),
        forecast_mean={k:sum(f[k] for f in forecasts)/max(1,len(forecasts)) for k in ('base','history')},
        changed=len(changes), changes=changes)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--game', action='append', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    result = dict(note=__doc__, games=[audit(p) for p in args.game])
    with args.output.open('x') as f:
        json.dump(result, f, indent=2)
    for g in result['games']:
        print(json.dumps({k:v for k,v in g.items() if k not in ('forecasts','changes')}))
