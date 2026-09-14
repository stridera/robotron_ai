"""Per-tick decision trace and death-window frame ring for the hardware path.

Why this exists (2026-09-14). Fourteen hardware rounds sent back a summary
`report.json` and a handful of screenshots. That was enough to fix the
scoreboard reader and the capture flags, but not to explain why the console
plays W9-12 while the emulator plays W30 with the same code: at equal waves
the console loses lives ~1.5-1.8x as fast with identical score income, and
none of the summary numbers (cadence, freshness, act latency, geometry)
differ. Every question that would settle it — where the player was when it
died, what was next to it, whether the detector saw the killer, how many
ticks a command takes to show on screen — needs per-tick data and the
frames around each death. The emulator has had exactly this (the dev tree's
death rings and the weekend's decisions.jsonl); the console never has.

Two recorders, both bounded, both non-fatal (an error stops recording and is
reported in the summary; the game loop never sees an exception):

    DecisionTrace   one JSON line per decision tick: timestamps, the player
                    and every entity in planner pixels, the projectile
                    tracks the brain coasted, the command sent, whether the
                    tick was blind/held, and the bookkeeper's view of the
                    game (score, wave, lives, deaths, game id).
    DeathRing       keeps the last few seconds of raw frames in memory and,
                    when the bookkeeper reports a death (or game over),
                    writes that window plus a short tail as JPEGs with a
                    per-frame index. The HUD reports a death ~2-3 s after
                    the collision (the scene freezes for the death animation,
                    blanks, re-forms, then the lives icons update), so the
                    window defaults to 4.5 s before the report.

Offline analysis: `python -m robotron_ai.trace_report <dir>` (trace_report.py).
"""
import json
import os
import queue
import shutil
import threading
import time
from collections import deque


def _compact_tracks(tracks):
    out = []
    for t in tracks or ():
        try:
            out.append([round(t['x'], 1), round(t['y'], 1), t['name'],
                        round(t['vx'], 2), round(t['vy'], 2), round(t['miss'], 2)])
        except (KeyError, TypeError):
            continue
    return out


class DecisionTrace:
    """Bounded JSONL recorder of every decision tick (see module doc)."""
    SCHEMA = "robotron_ai.decision_trace.v1"
    FILENAME = "decisions.jsonl"

    def __init__(self, out_dir, max_bytes=256 * 1024 * 1024):
        self.out_dir = out_dir
        self.path = os.path.join(out_dir, self.FILENAME)
        self.max_bytes = int(max_bytes)
        self.summary = dict(schema=self.SCHEMA, ticks=0, written=0, bytes=0,
                            blind_ticks=0, held_ticks=0, truncated=False,
                            error=None, seconds=0.0)
        self._f = None
        try:
            os.makedirs(out_dir, exist_ok=True)
            self._f = open(self.path, "w", encoding="utf-8")
        except OSError as e:
            self.summary['error'] = repr(e)

    def tick(self, *, obs, move, fire, blind, held, hud=None, game=None,
             sampled_at=None, seq=None, tracks=None, lead_player=None):
        """Record one decision tick. `obs` has .player / .entities in planner
        space; `blind` is the current blind-streak length (0 = player seen);
        `held` is True when hold-action repeated the last command; `hud` is
        the bookkeeper's dict (score, wave, lives, deaths) or None."""
        t0 = time.perf_counter()
        s = self.summary
        s['ticks'] += 1
        if blind:
            s['blind_ticks'] += 1
        if held:
            s['held_ticks'] += 1
        if self._f is None or s['truncated'] or s['error']:
            return
        try:
            row = {
                't': round(time.time(), 4),
                'monotonic': round(t0, 4),
                'sampled_at': None if sampled_at is None else round(sampled_at, 4),
                'seq': seq,
                'player': None if obs.player is None else
                          [round(obs.player[0], 2), round(obs.player[1], 2)],
                'lead_player': None if lead_player is None else
                               [round(lead_player[0], 2), round(lead_player[1], 2)],
                'entities': [[round(x, 1), round(y, 1), n] for (x, y, n) in obs.entities],
                'projectile_tracks': _compact_tracks(tracks),
                'move': int(move), 'fire': int(fire),
                'blind': int(blind), 'held': bool(held),
                'hud': hud, 'game': game,
            }
            line = json.dumps(row, separators=(',', ':')) + '\n'
            size = len(line.encode('utf-8'))
            if s['bytes'] + size > self.max_bytes:
                s['truncated'] = True
                return
            self._f.write(line)
            s['bytes'] += size
            s['written'] += 1
        except (OSError, TypeError, ValueError) as e:
            s['error'] = repr(e)
        finally:
            s['seconds'] += time.perf_counter() - t0

    def flush(self):
        try:
            if self._f is not None:
                self._f.flush()
        except OSError as e:
            self.summary['error'] = repr(e)

    def close(self):
        try:
            if self._f is not None:
                self._f.close()
        except OSError as e:
            self.summary['error'] = repr(e)
        self._f = None
        return self.summary


class DeathRing:
    """Rolling raw-frame ring; on mark() the window (plus a short tail) is
    handed to a writer thread that stores JPEGs under `<out_dir>/deaths/<label>/`.

    Memory: before_s * hz frames of raw BGR (1280x720x3 = 2.8 MB each), so
    4.5 s at 15 Hz is ~190 MB. Copies are made on push() because the eye's
    frame buffer is reused. Disk: ~40-80 KB per JPEG on the mostly-black
    arena, ~3-4 MB per death, bounded by max_events."""
    SUBDIR = "deaths"

    def __init__(self, out_dir, hz=15.0, before_s=4.5, after_s=1.0,
                 max_events=60, quality=85):
        self.dir = os.path.join(out_dir, self.SUBDIR)
        self.n_before = max(1, int(round(before_s * hz)))
        self.n_after = max(0, int(round(after_s * hz)))
        self.max_events = int(max_events)
        self.quality = int(quality)
        self.ring = deque(maxlen=self.n_before)
        self._pending = None            # dict(label, frames, remaining, info)
        self.summary = dict(events=0, written_frames=0, bytes=0, dropped_events=0,
                            merged_marks=0, error=None, writer_alive=None)
        self._q = queue.Queue(maxsize=8)
        self._stop = threading.Event()
        self._worker = threading.Thread(target=self._write_loop, daemon=True)
        try:
            if os.path.isdir(self.dir):
                shutil.rmtree(self.dir)        # this run's own folder only
            os.makedirs(self.dir, exist_ok=True)
        except OSError as e:
            self.summary['error'] = repr(e)
        self._worker.start()

    # ── hooks (decision thread) ────────────────────────────────────────
    def push(self, frame, meta=None):
        """Every tick, after the command was sent. `meta` is a small dict
        (tick, player, move, fire, hud...) stored beside the frame."""
        if frame is None or self.summary['error']:
            return
        try:
            item = (time.time(), frame.copy(), meta or {})
        except Exception as e:      # noqa: BLE001 — never fail the loop
            self.summary['error'] = repr(e)
            return
        self.ring.append(item)
        p = self._pending
        if p is not None:
            p['frames'].append(item)
            p['remaining'] -= 1
            if p['remaining'] <= 0:
                self._enqueue(p)
                self._pending = None

    def mark(self, label, info=None):
        """A death (or game over) was just reported: capture the ring now and
        keep collecting the tail. A second mark while a tail is still being
        collected is folded into the pending event."""
        if self.summary['error']:
            return
        if self._pending is not None:
            self.summary['merged_marks'] += 1
            self._pending.setdefault('info', {}).setdefault('merged', []).append(
                {'label': label, 'info': info or {}, 't': time.time()})
            return
        if self.summary['events'] + self._q.qsize() >= self.max_events:
            self.summary['dropped_events'] += 1
            return
        ev = dict(label=str(label), t=time.time(), info=info or {},
                  frames=list(self.ring), remaining=self.n_after,
                  n_before=len(self.ring))
        if self.n_after <= 0:
            self._enqueue(ev)
        else:
            self._pending = ev

    def _enqueue(self, ev):
        try:
            self._q.put_nowait(ev)
        except queue.Full:
            self.summary['dropped_events'] += 1

    # ── writer thread ──────────────────────────────────────────────────
    def _write_loop(self):
        try:
            import cv2
        except Exception as e:      # noqa: BLE001
            self.summary['error'] = repr(e)
            return
        while not (self._stop.is_set() and self._q.empty()):
            try:
                ev = self._q.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                self._write_event(cv2, ev)
                self.summary['events'] += 1
            except Exception as e:  # noqa: BLE001
                self.summary['error'] = repr(e)

    def _write_event(self, cv2, ev):
        d = os.path.join(self.dir, ev['label'])
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "index.jsonl"), "w", encoding="utf-8") as idx:
            for i, (t, frame, meta) in enumerate(ev['frames']):
                name = f"frame_{i:03d}.jpg"
                ok, enc = cv2.imencode('.jpg', frame,
                                       [cv2.IMWRITE_JPEG_QUALITY, self.quality])
                if not ok:
                    raise RuntimeError("JPEG encode failed")
                with open(os.path.join(d, name), "wb") as f:
                    f.write(enc.tobytes())
                self.summary['bytes'] += len(enc)
                self.summary['written_frames'] += 1
                row = dict(i=i, file=name, t=round(t, 4),
                           before_mark=i < ev['n_before'], **meta)
                idx.write(json.dumps(row, separators=(',', ':')) + '\n')
        with open(os.path.join(d, "event.json"), "w", encoding="utf-8") as f:
            json.dump(dict(label=ev['label'], t=ev['t'], n_before=ev['n_before'],
                           n_frames=len(ev['frames']), info=ev['info']), f, indent=1)

    def close(self, timeout=15.0):
        if self._pending is not None:     # game ended mid-tail: keep what we have
            self._enqueue(self._pending)
            self._pending = None
        self._stop.set()
        self._worker.join(timeout=timeout)
        self.summary['writer_alive'] = self._worker.is_alive()
        self.ring.clear()
        return self.summary


class HardwareTrace:
    """The two recorders behind one object, plus the death detection glue
    the harness calls each tick."""
    SUMMARY = "trace_summary.json"

    def __init__(self, out_dir, hz=15.0, death_before_s=4.5, death_after_s=1.0,
                 max_deaths=60, decisions=True, deaths=True):
        self.out_dir = out_dir
        self.decisions = DecisionTrace(out_dir) if decisions else None
        self.ring = (DeathRing(out_dir, hz=hz, before_s=death_before_s,
                               after_s=death_after_s, max_events=max_deaths)
                     if deaths else None)
        self._last_key = None       # (game_id, deaths) seen last tick
        self._last_go = False
        self.n_marks = 0
        self.t0 = time.time()

    def tick(self, *, frame, obs, move, fire, blind, held, bookkeeper=None,
             sampled_at=None, seq=None, brain=None):
        hud = game = None
        if bookkeeper is not None:
            hud = dict(score=bookkeeper.score, wave=bookkeeper.wave,
                       lives=bookkeeper.lives, deaths=bookkeeper.deaths)
            game = bookkeeper.game_id
        tracks = getattr(getattr(brain, 'coaster', None), 'tracks', None)
        if self.decisions is not None:
            self.decisions.tick(obs=obs, move=move, fire=fire, blind=blind,
                                held=held, hud=hud, game=game,
                                sampled_at=sampled_at, seq=seq, tracks=tracks)
        if self.ring is not None:
            tick_no = self.decisions.summary['ticks'] if self.decisions else None
            self.ring.push(frame, dict(tick=tick_no, player=obs.player,
                                       move=move, fire=fire, blind=blind,
                                       hud=hud))
        if bookkeeper is not None:
            self._check_events(bookkeeper, hud)

    def _check_events(self, bk, hud):
        key = (bk.game_id, bk.deaths)
        if self._last_key is not None and key[0] == self._last_key[0] \
                and key[1] > self._last_key[1]:
            self._mark(f"{bk.game_id}_d{bk.deaths:02d}_w{bk.wave or 0}",
                       dict(kind='death', **hud))
        go = bool(bk.game_over_fired)
        if go and not self._last_go:
            self._mark(f"{bk.game_id}_gameover_w{bk.max_wave or 0}",
                       dict(kind='game_over', **hud))
        self._last_go = go
        self._last_key = key

    def _mark(self, label, info):
        self.n_marks += 1
        if self.ring is not None:
            self.ring.mark(label, info)
        if self.decisions is not None:
            self.decisions.flush()

    def close(self):
        summary = dict(schema="robotron_ai.hardware_trace.v1",
                       elapsed_s=round(time.time() - self.t0, 1),
                       marks=self.n_marks,
                       decisions=self.decisions.close() if self.decisions else None,
                       deaths=self.ring.close() if self.ring else None)
        try:
            with open(os.path.join(self.out_dir, self.SUMMARY), "w",
                      encoding="utf-8") as f:
                json.dump(summary, f, indent=1)
        except OSError:
            pass
        return summary
