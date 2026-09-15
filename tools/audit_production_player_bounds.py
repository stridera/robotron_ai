"""Offline one-decision sensitivity to player-wall geometry on saved vision.

Reconstruct baseline tracking and use the recorded previous decision as player
lead. Evaluate both geometries on the SAME sprites. This is not a rollout or a
counterfactual survival estimate; no oracle data is read.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from robotron_ai.brain import ChampionBrain
from robotron_ai.engine import clearance_planner as cp


def audit(path):
    brain = ChampionBrain(.7, 1.5, use_coaster=True, normalize_tracking_time=False)
    action = brain._champion_action
    comparisons = []
    current = None

    def compare(sprites):
        cp.PLAYER_X_MIN, cp.PLAYER_X_MAX, cp.PLAYER_Y_MIN, cp.PLAYER_Y_MAX = 10.,655.,10.,482.
        base = action(sprites)
        try:
            cp.PLAYER_X_MIN, cp.PLAYER_X_MAX, cp.PLAYER_Y_MIN, cp.PLAYER_Y_MAX = 0.,665.,0.,492.
            candidate = action(sprites)
        finally:
            cp.PLAYER_X_MIN, cp.PLAYER_X_MAX, cp.PLAYER_Y_MIN, cp.PLAYER_Y_MAX = 10.,655.,10.,482.
        comparisons.append(dict(t=current['t'], player=current['player'], base=base,
                                candidate=candidate, recorded=[current['move'],current['fire']]))
        return base

    brain._champion_action = compare
    for line in (path/'decisions.jsonl').read_text().splitlines():
        current = json.loads(line)
        if current['control_player'] is None:
            if current['entities']:
                brain.blind_tick(current['entities'], sampled_at=current['sampled_at'])
        else:
            brain.decide(current['control_player'],current['entities'],sampled_at=current['sampled_at'])
            # One-decision comparison always conditions on the actual history.
            brain.last_mv = current['move']
    changed = [r for r in comparisons if r['base'] != r['candidate']]
    return dict(path=str(path), decisions=len(comparisons), changed=len(changed),
        baseline_mismatches=sum(list(r['base']) != r['recorded'] for r in comparisons),
        changes=changed)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--game',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args = ap.parse_args()
    result = audit(args.game)
    with args.output.open('x',encoding='utf-8') as f:
        json.dump(dict(note=__doc__,**result),f,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k!='changes'},indent=2))
