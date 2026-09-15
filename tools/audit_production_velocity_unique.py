"""Video-only replay of unique nonprojectile velocity associations.

Counts legacy reused identities and action sensitivity on identical recorded
histories. Neither an alternative trajectory nor avoided-death evidence.
"""
import argparse
from collections import Counter
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
    duplicates = Counter()
    duplicate_events = []
    for unique in (False, True):
        brain = ChampionBrain(.7, 1.5, use_coaster=True, normalize_tracking_time=False)
        brain.vt.unique_matches = unique
        previous = brain.vt.velocities
        current = None
        def velocities(cur, dt=1.):
            if not unique:
                seen = set()
                for x,y,name in cur:
                    choices = [((x-p[1])**2+(y-p[2])**2,j) for j,p in enumerate(brain.vt.prev) if p[0]==name]
                    if choices:
                        d,j = min(choices)
                        if d <= (brain.vt.VMAX*dt)**2:
                            if j in seen:
                                duplicates[name] += 1
                                duplicate_events.append(dict(t=current['t'],name=name,position=[x,y],previous=list(brain.vt.prev[j])))
                            seen.add(j)
            return previous(cur,dt)
        brain.vt.velocities = velocities
        outputs = []
        start = time.perf_counter()
        for current in trace:
            if current['control_player'] is None:
                if current['entities']:
                    brain.blind_tick(current['entities'], sampled_at=current['sampled_at'])
            else:
                out = brain.decide(current['control_player'],current['entities'],sampled_at=current['sampled_at'])
                outputs.append(dict(t=current['t'], action=list(out), recorded=[current['move'],current['fire']]))
                brain.last_mv = current['move']
        results.append(dict(seconds=time.perf_counter()-start, outputs=outputs))
    base,cand = results
    changes = [dict(t=a['t'],base=a['action'],candidate=b['action'])
               for a,b in zip(base['outputs'],cand['outputs']) if a['action']!=b['action']]
    return dict(path=str(path), decisions=len(base['outputs']),
                baseline_mismatches=sum(a['action']!=a['recorded'] for a in base['outputs']),
                reused_previous_identities=dict(duplicates), changed=len(changes), changes=changes,
                duplicate_events=duplicate_events,
                base_seconds=base['seconds'], candidate_seconds=cand['seconds'])


if __name__ == '__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--game',action='append',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    result=dict(note=__doc__, games=[audit(p) for p in args.game])
    with args.output.open('x') as f: json.dump(result,f,indent=2)
    print(json.dumps([{k:v for k,v in g.items() if k not in ('changes','duplicate_events')} for g in result['games']],indent=2))
