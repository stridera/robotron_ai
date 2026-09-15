"""Offline HUD/oracle audit of completed production games; never policy input.

Writes per-wave discrepancies and exploratory whole-game bootstrap metrics.
Oracle deaths use life balance, not raw downward ticks: wave transitions briefly
increment lives. Assumes the configured 25,000-point extra life interval; reports
initial/final life counters and transition anomalies for review. Boundaries are
the last oracle sample in each wave, so HUD timing can move income across waves.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import random
import statistics

ROOT = Path(__file__).resolve().parents[1]


def read_rows(path):
    with path.open(encoding='utf-8-sig') as stream:
        return [json.loads(line) for line in stream if line.strip()]


def signed_lives(value):
    return -1 if value == 0xffffffff else value


def metrics(games, source):
    rows = [r[source] for g in games for r in g['waves'] if 5 <= r['wave'] <= 25 and r[source] is not None]
    n = len(rows)
    if not n:
        return dict(waves=0, deaths_per_wave=None, score_per_wave=None, net=None)
    d, s = sum(r['deaths'] for r in rows) / n, sum(r['score'] for r in rows) / n
    return dict(waves=n, deaths_per_wave=d, score_per_wave=s, net=s / 25000 - d)


def audit(prefix, wave_log, include_wave_cap=False):
    hud = defaultdict(list)
    for r in read_rows(wave_log):
        if r.get('arm', '').startswith(prefix + '_'):
            hud[r['game']].append(r)
    games, excluded = [], []
    for path in sorted((ROOT / 'logs/production_games').glob(prefix + '_*')):
        result_path = path / 'result.json'
        record = json.loads(result_path.read_text()) if result_path.exists() else {}
        capped = include_wave_cap and record.get('outcome') == 'wave_cap'
        if capped:
            samples = read_rows(path / 'hud_samples.jsonl')
            ids = {r['game'] for r in samples if r.get('game')}
            h = record.get('hud', {})
            if (not record.get('complete') or record.get('games') or len(ids) != 1
                    or not h.get('startup_verified') or h.get('wave') != record['cap'] + 1):
                excluded.append(dict(path=str(path.relative_to(ROOT)), reason='invalid cap completion'))
                continue
            game = dict(game=ids.pop(), wave=h['wave'], score=h['score'], deaths=h['deaths'])
        elif record.get('outcome') != 'game_over' or len(record.get('games', [])) != 1:
            excluded.append(dict(path=str(path.relative_to(ROOT)), reason='not one completed game_over'))
            continue
        else:
            game = record['games'][0]
        rows = [r for r in read_rows(path / 'oracle_headers.jsonl') if r['wave'] > 0]
        if not rows:
            excluded.append(dict(path=str(path.relative_to(ROOT)), reason='no oracle gameplay'))
            continue
        first, last = rows[0], rows[-1]
        if (first['wave'] != 1 or first['score'] != 0 or not 0 <= first['lives'] < 100
                or (not capped and last['lives'] != 0xffffffff)
                or (capped and not 0 <= last['lives'] < 100)
                or last['wave'] != game['wave']
                or last['score'] != game['score']):
            excluded.append(dict(path=str(path.relative_to(ROOT)), reason='initial/terminal oracle validation failed'))
            continue
        end_by_wave = {r['wave']: r for r in rows}
        if capped:
            if not all(w in end_by_wave for w in range(1, record['cap'] + 1)):
                excluded.append(dict(path=str(path.relative_to(ROOT)), reason='missing pre-cap oracle waves'))
                continue
            end_by_wave = {w:r for w,r in end_by_wave.items() if w <= record['cap']}
        hud_by_wave = {r['wave']: r for r in hud[game['game']]}
        initial = signed_lives(first['lives'])
        previous_score = first['score']
        previous_deaths = 0
        waves = []
        for wave, r in sorted(end_by_wave.items()):
            deaths = initial + r['score'] // 25000 - first['score'] // 25000 - signed_lives(r['lives'])
            oracle = dict(score=r['score'] - previous_score, deaths=deaths - previous_deaths,
                          end_score=r['score'], end_lives=signed_lives(r['lives']))
            h = hud_by_wave.get(wave)
            waves.append(dict(wave=wave, oracle=oracle, hud=h,
                              score_delta=None if h is None else h['score'] - oracle['score'],
                              deaths_delta=None if h is None else h['deaths'] - oracle['deaths']))
            previous_score, previous_deaths = r['score'], deaths
        telemetry = json.loads((path / 'telemetry/report.json').read_text())
        games.append(dict(path=str(path.relative_to(ROOT)), arm=record['arm'], game=game['game'],
                          censored=capped, outcome=record['outcome'],
                          terminal_hud=game, terminal_oracle=last,
                          terminal_agrees=last['wave'] == game['wave'] and last['score'] == game['score'],
                          initial_lives=initial, initial_wave=first['wave'], initial_score=first['score'],
                          oracle_balance_deaths=previous_deaths,
                          hud_death_error=game['deaths'] - previous_deaths,
                          waves=waves, frames=telemetry.get('frames'), tick=telemetry.get('tick')))
    grouped = defaultdict(list)
    for g in games:
        grouped[g['arm']].append(g)
    arms = {arm: dict(games=len(gs), mean_wave=statistics.mean(g['terminal_hud']['wave'] for g in gs),
                     hud=metrics(gs, 'hud'), oracle=metrics(gs, 'oracle'),
                     censored_games=sum(g['censored'] for g in gs),
                     hud_death_error=sum(g['hud_death_error'] for g in gs)) for arm, gs in grouped.items()}
    comparisons = {}
    eligible = {arm: [g for g in gs if any(5 <= r['wave'] <= 25 and r['hud'] is not None
                                          for r in g['waves'])] for arm, gs in grouped.items()}
    base = eligible.get(prefix + '_base', [])
    rng = random.Random(9120301)
    for arm, gs in eligible.items():
        if arm.endswith('_base') or len(base) < 2 or len(gs) < 2:
            continue
        for source in ('hud', 'oracle'):
            delta = {key: [] for key in ('net', 'deaths_per_wave', 'score_per_wave')}
            for _ in range(4000):
                a = metrics(rng.choices(gs, k=len(gs)), source)
                b = metrics(rng.choices(base, k=len(base)), source)
                for key in delta:
                    delta[key].append(a[key] - b[key])
            a, b = metrics(gs, source), metrics(base, source)
            comparisons[arm + '/' + source] = {key: dict(delta=a[key] - b[key],
                ci95=[sorted(values)[100], sorted(values)[3900]]) for key, values in delta.items()}
    return dict(prefix=prefix, band=[5, 25], status='exploratory; incomplete batches and HUD discrepancies are not promotion evidence',
                assumptions='25k extra lives; signed game-over counter -1; last sample per wave; whole-game resampling',
                arms=arms, comparisons=comparisons, excluded=excluded, games=games)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--prefix', required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--include-wave-cap', action='store_true',
                    help='Include verified capped games through their last completed wave; label censoring')
    ap.add_argument('--wave-log', type=Path, default=ROOT.parent / 'robotron/logs/yolo_waves.jsonl')
    args = ap.parse_args()
    result = audit(args.prefix, args.wave_log, args.include_wave_cap)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps({k: v for k, v in result.items() if k != 'games'}, indent=2))


if __name__ == '__main__':
    main()
