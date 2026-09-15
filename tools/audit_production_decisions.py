"""Offline trace exposure and approximate death windows; never gameplay input.

Nearest detected threat is a descriptive label, not an attributed killer.
Default times use persistent life balance as in audit_production_transitions.
Those counter updates occur AFTER the collision freeze (about 1.7s in the
September 12 visual sample); default windows describe death-animation state,
not causal pre-impact exposure. --phase-audit uses independently saved visual
freeze-onset estimates and excludes events without an accepted phase estimate.
"""
import argparse
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]
NONTHREATS = {'Mommy', 'Daddy', 'Mikey', 'Player'}


def rows(path):
    with path.open(encoding='utf-8-sig') as stream:
        return [json.loads(line) for line in stream if line.strip()]


def death_events(oracle):
    if not oracle:
        return []
    first = oracle[0]
    high, pending, since = 0, None, 0
    events = []
    for r in oracle:
        lives = -1 if r['lives'] == 0xffffffff else r['lives']
        balance = first['lives'] + r['score']//25000 - first['score']//25000 - lives
        if balance != pending:
            pending, since = balance, r['t']
        if balance > high and r['t']-since >= .3:
            events.append(dict(t=since, count=balance-high, wave=r['wave']))
            high = balance
    return events


def audit(prefix, phase_audit=None):
    games = []
    phases = {}
    if phase_audit is not None:
        for g in json.loads(Path(phase_audit).read_text())['games']:
            for e in g['events']:
                phases[Path(g['path']).name, e['t']] = e
    for path in sorted((ROOT/'logs/production_games').glob(prefix+'_*')):
        result = json.loads((path/'result.json').read_text())
        trace = rows(path/'decisions.jsonl')
        oracle = [r for r in rows(path/'oracle_headers.jsonl') if r['wave'] > 0]
        summary = json.loads((path/'decision_trace_summary.json').read_text())
        events = death_events(oracle)
        excluded_phases = 0
        if phase_audit is not None:
            aligned = []
            for event in events:
                phase = phases.get((path.name, event['t']))
                if phase is None or not phase['phase_valid']:
                    excluded_phases += 1
                    continue
                aligned.append(dict(event, counter_t=event['t'], t=phase['freeze_onset']))
            events = aligned
        times = [r['t'] for r in trace]
        counts, nearest, windows = Counter(), Counter(), []
        ages, neutral_recoveries = [], []
        previous, neutral_since = None, None
        for r in trace:
            counts['ticks'] += 1
            counts['held'] += r['player_hold_samples'] > 0
            counts['blind'] += r['player'] is None
            counts['neutral'] += (r['move'], r['fire']) == (0, 0)
            counts['held_control_null'] += r['player_hold_samples'] > 0 and r['control_player'] is None
            ages.append(r['monotonic']-r['sampled_at'])
            neutral = r['control_player'] is None and r['move'] == 0
            if neutral:
                if neutral_since is None:
                    neutral_since = r['t']
            else:
                if neutral_since is not None and r['control_player'] is not None:
                    neutral_recoveries.append(dict(t=r['t'], seconds=r['t']-neutral_since,
                        player=r['player']))
                neutral_since = None
            if previous and r['sampled_at'] == previous['sampled_at']:
                counts['same_sample'] += 1
            previous = r
        for i, event in enumerate(events):
            # A counter anchor is post-impact; only a verified phase anchor
            # makes this an approximate pre-impact window.
            lo, hi = bisect_left(times, event['t']-.8), bisect_right(times, event['t']-.2)
            pre = trace[lo:hi]
            fresh = [r for r in pre if r['player'] is not None and not r['player_hold_samples']]
            detail = dict(**event, decisions=len(pre), fresh=len(fresh),
                held=sum(r['player_hold_samples'] > 0 for r in pre),
                blind=sum(r['player'] is None for r in pre),
                since_previous=None if i == 0 else event['t']-events[i-1]['t'])
            if fresh:
                r = fresh[-1]
                x, y = r['player']
                detail['wall_distance'] = min(x, 665-x, y, 492-y)
                threats = [(math.hypot(x-ex, y-ey), name) for ex, ey, name in r['entities']
                           if name not in NONTHREATS]
                if threats:
                    distance, name = min(threats)
                    detail.update(nearest=name, nearest_distance=distance)
                    nearest[name] += 1
            windows.append(detail)
        games.append(dict(path=str(path.relative_to(ROOT)), arm=result['arm'],
            outcome=result.get('outcome'), complete=result.get('complete', False),
            anchor_kind='visual_freeze' if phase_audit is not None else 'life_counter_update',
            excluded_phases=excluded_phases,
            trace_summary=summary, counts=dict(counts),
            trace_rows_match=len(trace) == summary['written'] == summary['ticks'],
            observation_age_median=statistics.median(ages),
            observation_age_p90=sorted(ages)[int(.9*len(ages))],
            neutral_recoveries=neutral_recoveries, death_windows=windows,
            nearest_threat=dict(nearest)))
    arms = defaultdict(list)
    for g in games:
        arms[g['arm']].append(g)
    totals = {}
    for arm, gs in arms.items():
        counts, nearest = Counter(), Counter()
        for g in gs:
            counts.update(g['counts'])
            nearest.update(g['nearest_threat'])
        windows = [w for g in gs for w in g['death_windows']]
        recoveries = [r for g in gs for r in g['neutral_recoveries']]
        totals[arm] = dict(games=len(gs), counts=dict(counts), nearest_threat=dict(nearest),
            trace_complete=all(g['trace_rows_match'] and not g['trace_summary']['truncated']
                               and g['trace_summary']['error'] is None for g in gs),
            observer_ms_per_tick=1000*sum(g['trace_summary']['observer_seconds'] for g in gs)/counts['ticks'],
            neutral_recoveries=len(recoveries),
            neutral_over_300ms=sum(r['seconds'] >= .3 for r in recoveries),
            approximate_death_events=len(windows),
            death_windows_with_held=sum(w['held'] > 0 for w in windows),
            death_windows_with_fresh=sum(w['fresh'] > 0 for w in windows),
            death_windows_wall_30px=sum(w.get('wall_distance', 999) < 30 for w in windows),
            deaths_within_5s_of_previous=sum(w['since_previous'] is not None and w['since_previous'] < 5 for w in windows))
    return dict(prefix=prefix, assumptions=__doc__, arms=totals, games=games)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--phase-audit', type=Path)
    args = parser.parse_args()
    report = audit(args.prefix, args.phase_audit)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
    print(json.dumps(report['arms'], indent=2))
