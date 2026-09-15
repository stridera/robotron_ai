"""Bounded video-only decision records for offline death-window analysis.

The production test wrapper supplies this write-only observer to both arms.
No oracle state is accepted here; join independent oracle headers OFFLINE.
"""
import json
import time
from pathlib import Path


class DecisionTrace:
    def __init__(self, directory, max_bytes=64 * 1024 * 1024):
        self.directory = Path(directory)
        self.stream = (self.directory / 'decisions.jsonl').open('x', encoding='utf-8')
        self.max_bytes = max_bytes
        self.summary = dict(ticks=0, written=0, bytes=0, held_ticks=0,
                            blind_ticks=0, truncated=False, error=None,
                            observer_seconds=0.0)

    def record(self, obs, move, fire, brain, control_player):
        started = time.perf_counter()
        s = self.summary
        s['ticks'] += 1
        held = getattr(obs, 'player_hold_samples', 0)
        s['held_ticks'] += held > 0
        s['blind_ticks'] += obs.player is None
        if s['truncated'] or s['error']:
            return
        try:
            coaster = getattr(brain, 'coaster', None)
            row = dict(t=time.time(), monotonic=started, sampled_at=obs.sampled_at,
                       player=obs.player, player_hold_samples=held,
                       control_player=control_player,
                       entities=obs.entities, move=move, fire=fire,
                       projectile_tracks=getattr(coaster, 'tracks', []))
            line = json.dumps(row, separators=(',', ':')) + '\n'
            size = len(line.encode('utf-8'))
            if s['bytes'] + size > self.max_bytes:
                s['truncated'] = True
            else:
                self.stream.write(line)
                s['bytes'] += size
                s['written'] += 1
        except (OSError, TypeError, ValueError) as error:
            s['error'] = repr(error)
            print(f'[decision_trace] recording stopped: {error}', flush=True)
        finally:
            s['observer_seconds'] += time.perf_counter() - started

    def close(self):
        try:
            self.stream.close()
        except OSError as error:
            self.summary['error'] = repr(error)
        (self.directory / 'decision_trace_summary.json').write_text(
            json.dumps(self.summary, indent=2), encoding='utf-8')
