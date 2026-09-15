"""Offline stable-command player boundary forecasts against video detections.

Requires saved phase audits to exclude death animations. This checks coordinate
geometry, not the outcome of an alternative policy; memory is never policy input.
"""
import argparse
import bisect
import json
import math
from pathlib import Path
import statistics

DXY = {1:(0,-9.2),2:(9.5,-9.2),3:(9.5,0),4:(9.5,9.2),
       5:(0,9.2),6:(-9.5,9.2),7:(-9.5,0),8:(-9.5,-9.2)}
def rows(p):
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
def audit(game):
    p=Path(game['path']); trace=rows(p/'decisions.jsonl')
    events=game['events']; samples=[]; windows=[]
    oracle=rows(p/'oracle_headers.jsonl'); ot=[r['t'] for r in oracle]
    for i in range(3,len(trace)-1):
        r=trace[i]; nxt=trace[i+1]; seq=trace[i-3:i+2]
        if oracle[max(0,bisect.bisect_right(ot,r['t'])-1)]['wave']<=10: continue
        if any(s['player'] is None or s['player_hold_samples'] or s['move']!=r['move'] for s in seq): continue
        if r['move'] not in DXY: continue
        if any(e['t']-3<r['t']<e['t']+2 for e in events): continue
        dt=(nxt['sampled_at']-r['sampled_at'])*15
        if not .7<dt<1.3: continue
        x,y=r['player']; dx,dy=DXY[r['move']]
        if not ((x<12 and dx<0) or (x>653 and dx>0) or (y<12 and dy<0) or (y>480 and dy>0)): continue
        nx,ny=nxt['player']
        inner=(min(655,max(10,x+dx*dt)),min(482,max(10,y+dy*dt)))
        full=(min(665,max(0,x+dx*dt)),min(492,max(0,y+dy*dt)))
        samples.append(dict(t=r['t'],player=r['player'],next_player=nxt['player'],move=r['move'],
            inner_error=math.hypot(inner[0]-nx,inner[1]-ny),full_error=math.hypot(full[0]-nx,full[1]-ny)))
    for e in events:
        if not e['phase_valid']: continue
        pre=[r for r in trace if e['freeze_onset']-.8<=r['t']<=e['freeze_onset']-.2 and r['player'] is not None and not r['player_hold_samples']]
        hits=[]
        for r in pre:
            x,y=r['player']; dx,dy=DXY.get(r['move'],(0,0))
            if (x<10 and dx<=0) or (x>655 and dx>=0) or (y<10 and dy<=0) or (y>482 and dy>=0): hits.append(r['t'])
        if hits: windows.append(dict(t=e['t'],onset=e['freeze_onset'],wave=e['wave'],ticks=hits))
    return dict(path=str(p),samples=len(samples),mean_inner_error=statistics.mean(s['inner_error'] for s in samples) if samples else None,
        mean_full_error=statistics.mean(s['full_error'] for s in samples) if samples else None,
        affected_deaths=len(windows),total_deaths=sum(e['phase_valid'] for e in events),windows=windows,records=samples)
if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('--phase-audit',action='append',type=Path,required=True); ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args(); result=dict(note=__doc__,games=[audit(g) for f in args.phase_audit for g in json.loads(f.read_text())['games']])
    with args.output.open('x') as f: json.dump(result,f,indent=2)
    print(json.dumps([{k:v for k,v in g.items() if k not in ('records','windows')} for g in result['games']],indent=2))
