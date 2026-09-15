"""Offline image registration of death-animation onset, never a policy input.

Life-balance timestamps mark a later counter update, not collision time. Compare
foreground geometry to an image 0.6s before that update to bracket the preceding
scene freeze. This is a diagnostic estimate requiring visual verification, not
killer attribution. Fixed thresholds must be checked on independent games.
"""
import argparse
import bisect
import json
from pathlib import Path
import numpy as np
import cv2

from audit_production_decisions import death_events, rows


def mask(payload):
    frame = cv2.imdecode(np.frombuffer(payload, np.uint8), cv2.IMREAD_COLOR)
    if frame is None or frame.shape[:2] != (720, 1280):
        raise ValueError('expected complete 1280x720 JPEG')
    # Exclude HUD and border; ignore cycling hue, retain foreground geometry.
    return frame[105:620, 278:1012].max(axis=2)[::2, ::2] > 100


def distance(a, b):
    return float(np.count_nonzero(a != b) / max(1, np.count_nonzero(a | b)))


def audit_game(path):
    index = rows(path/'visual/frames.jsonl')
    times = [r['t'] for r in index]
    oracle = [r for r in rows(path/'oracle_headers.jsonl') if r['wave'] > 0]
    events = death_events(oracle)
    records = []
    oracle_times = [r['t'] for r in oracle]
    controls = []
    wave_starts = {}
    for r in oracle:
        wave_starts.setdefault(r['wave'], r['t'])
    for e in events:
        at = e['t'] - 6.0
        k = max(0, bisect.bisect_right(oracle_times, at)-1)
        if (e['wave'] > 10 and oracle[k]['wave'] == e['wave'] and
                at-wave_starts[e['wave']] > 3 and
                all(abs(at-d['t']) > 4 for d in events)):
            controls.append(dict(t=at, wave=e['wave'], count=0, control=True))
    with (path/'visual/frames.mjpg').open('rb') as stream:
        def read(k):
            r = index[k]
            stream.seek(r['offset'])
            return mask(stream.read(r['size']))
        def nearest(t):
            k = bisect.bisect_left(times, t)
            return min(range(max(0,k-1),min(len(index),k+1)), key=lambda i:abs(times[i]-t))
        for event in events + controls:
            if event['wave'] <= 10:
                continue
            anchor_index = nearest(event['t']-.6)
            anchor = read(anchor_index)
            lo = bisect.bisect_left(times,event['t']-3)
            hi = bisect.bisect_right(times,event['t']-.2)
            comparisons = [(i,distance(read(i),anchor)) for i in range(lo,hi)]
            # Find the last dissimilar frame before the anchor. Require the
            # resulting plateau to persist >=0.7s and include >=15 samples.
            prior = [(i,d) for i,d in comparisons if i <= anchor_index]
            dissimilar = [i for i,d in prior if d > .18]
            first = (dissimilar[-1]+1) if dissimilar else lo
            plateau = [(i,d) for i,d in comparisons if i >= first]
            onset = times[first]
            valid = (bool(dissimilar) and len(plateau)>=15 and
                     times[plateau[-1][0]]-onset >= .7 and
                     sum(d <= .18 for _,d in plateau)/len(plateau) >= .9)
            records.append(dict(**event, phase_valid=valid, freeze_onset=onset if valid else None,
                onset_bracket=[times[first-1],onset] if valid else None,
                counter_delay=event['t']-onset if valid else None,
                distances=[dict(t=times[i],distance=d) for i,d in comparisons]))
    return dict(path=str(path), events=[e for e in records if not e.get('control')],
                controls=[e for e in records if e.get('control')])


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--prefix', required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    root = Path(__file__).resolve().parents[1]
    games = [audit_game(p) for p in sorted((root/'logs/production_games').glob(args.prefix+'_*'))
             if (p/'visual/frames.jsonl').exists()]
    report = dict(method=__doc__, threshold=.18, games=games)
    with args.output.open('x',encoding='utf-8') as f:
        json.dump(report,f,indent=2)
    for game in games:
        accepted=[e['counter_delay'] for e in game['events'] if e['phase_valid']]
        print(Path(game['path']).name, 'valid',len(accepted),'of',len(game['events']),
              'delay range', [min(accepted),max(accepted)] if accepted else [],
              'control flags',sum(e['phase_valid'] for e in game['controls']), 'of',len(game['controls']))
