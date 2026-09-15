"""Video-only replay of stationary-electrode velocity suppression.

Replays recorded commands, never alternative trajectories or oracle input.
Reports jitter exposure and changed actions, not prevented deaths.
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
    trace = [json.loads(s) for s in (path / 'decisions.jsonl').read_text().splitlines()]
    results = []
    exposures = []
    for static in (False, True):
        brain = ChampionBrain(.7, 1.5, use_coaster=True, normalize_tracking_time=False)
        brain.vt.static_electrodes = static
        previous = brain.vt.velocities
        current = None
        def velocities(cur, dt=1.):
            output = previous(cur, dt)
            if not static:
                moving = [(e, v) for e, v in zip(cur, output)
                          if e[2] == 'Electrode' and v[0]**2 + v[1]**2 > 1]
                if moving:
                    exposures.append(dict(t=current['t'], electrodes=moving))
            return output
        brain.vt.velocities = velocities
        outputs = []
        start = time.perf_counter()
        for current in trace:
            if current['control_player'] is None:
                if current['entities']:
                    brain.blind_tick(current['entities'], sampled_at=current['sampled_at'])
            else:
                action = brain.decide(current['control_player'], current['entities'],
                                      sampled_at=current['sampled_at'])
                outputs.append(dict(t=current['t'], action=list(action),
                                    recorded=[current['move'], current['fire']]))
                brain.last_mv = current['move']
        results.append(dict(seconds=time.perf_counter()-start, outputs=outputs))
    base, candidate = results
    changes = [dict(t=a['t'], base=a['action'], candidate=b['action'])
               for a, b in zip(base['outputs'], candidate['outputs'])
               if a['action'] != b['action']]
    return dict(path=str(path), decisions=len(base['outputs']),
                baseline_mismatches=sum(a['action'] != a['recorded'] for a in base['outputs']),
                moving_electrode_ticks=len(exposures), exposures=exposures,
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
    print(json.dumps([{k:v for k,v in g.items() if k not in ('changes','exposures')}
                      for g in result['games']], indent=2))
