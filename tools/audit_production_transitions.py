"""Offline HUD transition timing diagnostic; never imported by gameplay.

Event times are approximate: a cumulative oracle life balance must persist for
0.3 seconds. A high-water mark suppresses wave-transition counter pulses. This
is a diagnostic of HUD event coverage, not a replacement for whole-game NET.
"""
import argparse
import json
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def audit(prefix):
    games = []
    for path in sorted((ROOT / 'logs/production_games').glob(prefix + '_*')):
        oracle = [r for r in rows(path / 'oracle_headers.jsonl') if r['wave'] > 0]
        hud = rows(path / 'hud_samples.jsonl')
        if not oracle:
            continue
        first = oracle[0]
        high, pending, since = 0, None, 0
        deaths = []
        for r in oracle:
            lives = -1 if r['lives'] == 0xffffffff else r['lives']
            balance = first['lives'] + r['score'] // 25000 - first['score'] // 25000 - lives
            if balance != pending:
                pending, since = balance, r['t']
            if balance > high and r['t'] - since >= .3:
                deaths.append(dict(t=since, count=balance-high, wave=r['wave'], balance=balance))
                high = balance
        hud_deaths, hud_waves, uncounted = [], [], []
        for before, after in zip(hud, hud[1:]):
            b, a = before['accepted'], after['accepted']
            if before['game'] != after['game']:
                continue
            if a['deaths'] > b['deaths']:
                hud_deaths.append(after)
            if b['wave'] is not None and a['wave'] is not None and a['wave'] > b['wave']:
                hud_waves.append(after)
            if (a['lives'] is not None and b['lives'] is not None
                    and a['lives'] < b['lives'] and a['deaths'] == b['deaths']):
                uncounted.append(after)
        starts = {}
        for r in oracle:
            starts.setdefault(r['wave'], r['t'])
        matches = []
        for h in hud_deaths:
            if deaths:
                d = min(deaths, key=lambda d: abs(d['t']-h['t']))
                matches.append(dict(t=h['t'], oracle_t=d['t'], delay=h['t']-d['t'],
                                    wave=h['accepted']['wave']))
        unmatched = [dict(**d, hud_window=[h for h in hud if d['t']-1 <= h['t'] <= d['t']+2])
                     for d in deaths if not any(abs(h['t']-d['t']) <= 2 for h in hud_deaths)]
        games.append(dict(path=str(path.relative_to(ROOT)), confirmed_balance=high,
            oracle_events=deaths, hud_events=len(hud_deaths), matches=matches,
            unmatched_oracle_events=unmatched, accepted_drops_not_counted=uncounted,
            wave_delays=[h['t']-starts[h['accepted']['wave']] for h in hud_waves
                         if h['accepted']['wave'] in starts]))
    delays = [m['delay'] for g in games for m in g['matches']]
    waves = [d for g in games for d in g['wave_delays']]
    return dict(assumptions=__doc__, games=games, summary=dict(
        games=len(games), confirmed_balance=sum(g['confirmed_balance'] for g in games),
        hud_events=sum(g['hud_events'] for g in games),
        matched_within_2s=sum(abs(d) <= 2 for d in delays),
        median_death_delay=statistics.median(delays) if delays else None,
        wave_events=len(waves), median_wave_delay=statistics.median(waves) if waves else None,
        max_wave_delay=max(waves) if waves else None,
        accepted_drops_not_counted=sum(len(g['accepted_drops_not_counted']) for g in games)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.prefix)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps(result['summary'], indent=2))
