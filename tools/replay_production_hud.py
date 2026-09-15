"""Replay saved raw HUD samples through the production wrapper, offline only.

Uses recorded timestamps, no emulator or controller. The report preserves event
counts and exceptions; it does not rewrite or certify the original outcomes.
"""
import argparse
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from robotron_ai.hud_ocr import VisionBookkeeper
from robotron_ai.tools.run_production_game import capped_bookkeeper


def replay(path):
    path = Path(path).resolve()
    result = json.loads((path / 'result.json').read_text())
    samples = [json.loads(line) for line in (path / 'hud_samples.jsonl').read_text().splitlines()]
    events, last = [], {}
    current = samples[0]['t']
    book = capped_bookkeeper(VisionBookkeeper, result['cap'], last)(
        on_event=lambda kind, **kw: events.append(dict(observed_at=current, kind=kind, **kw)))
    error, acquired_at, verified_at = None, None, None
    output = io.StringIO()
    with redirect_stdout(output):
        for sample in samples:
            current = sample['t']
            try:
                with patch('robotron_ai.tools.run_production_game.time.monotonic',
                           return_value=current-samples[0]['t']):
                    book.feed(sample['reading'], t=current,
                              player_visible=sample.get('player_visible'))
                if book.startup_acquired and acquired_at is None:
                    acquired_at = current
                if book.startup_verified and verified_at is None:
                    verified_at = current
            except Exception as exc:
                error = repr(exc)
                break
    over = [e for e in events if e['kind'] == 'game_over']
    expected = result['games'][-1] if result.get('games') else {}
    return dict(path=str(path.relative_to(ROOT)), samples=len(samples), error=error,
                acquired_seconds=None if acquired_at is None else acquired_at-samples[0]['t'],
                verified_seconds=None if verified_at is None else verified_at-samples[0]['t'],
                game_over_events=over, new_game_events=[e for e in events if e['kind']=='new_game'],
                original_telemetry_games=len(result.get('games', [])),
                terminal_agrees=len(over)==1 and all(over[0].get(k)==expected.get(k) for k in ('wave','score')),
                last_hud=last, messages=output.getvalue().splitlines())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    games = [replay(p) for p in sorted((ROOT/'logs/production_games').glob(args.prefix+'_*'))]
    report = dict(prefix=args.prefix, games=games, all_terminal_agree=bool(games) and
                  all(g['terminal_agrees'] and g['error'] is None for g in games))
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
    print(json.dumps({k:v for k,v in report.items() if k != 'games'}))
    print(json.dumps([dict(path=g['path'], error=g['error'], terminal_agrees=g['terminal_agrees'],
                           verified_seconds=g['verified_seconds'], game_overs=len(g['game_over_events']))
                      for g in games], indent=2))
