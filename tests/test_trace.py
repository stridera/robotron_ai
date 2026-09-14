"""Tests for the hardware trace recorders and the offline analyser.

Run from the package's parent directory:
    python -m unittest robotron_ai.tests.test_trace -v
"""
import json
import os
import shutil
import tempfile
import time
import unittest

import numpy as np

from .. import harness, trace, trace_report
from ..perception import Observation


class FakeBookkeeper:
    def __init__(self):
        self.game_id = 'g1'
        self.score, self.wave, self.lives, self.deaths = 0, 1, 3, 0
        self.max_wave, self.max_score = 1, 0
        self.game_over_fired = False

    def feed(self, reading, player_visible=None):
        return dict(score=self.score, wave=self.wave, lives=self.lives,
                    deaths=self.deaths)


def _jsonl(path):
    with open(path, encoding='utf-8') as f:
        return [json.loads(l) for l in f if l.strip()]


def _json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def _frame(v=0):
    f = np.zeros((36, 64, 3), dtype=np.uint8)
    f[:, :, 1] = v % 256
    return f


class DecisionTraceTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_rows_and_summary(self):
        tr = trace.DecisionTrace(self.d)
        obs = Observation((100.0, 200.0), [(10.0, 20.0, 'Grunt')])
        tr.tick(obs=obs, move=3, fire=1, blind=0, held=False,
                hud=dict(score=100, wave=1, lives=3, deaths=0), game='g',
                sampled_at=1.5, seq=7, tracks=[dict(x=1, y=2, name='TankShell',
                                                    vx=3, vy=4, miss=0.5)])
        tr.tick(obs=Observation(None, []), move=3, fire=1, blind=1, held=True)
        s = tr.close()
        self.assertEqual(s['written'], 2)
        self.assertEqual(s['blind_ticks'], 1)
        self.assertEqual(s['held_ticks'], 1)
        rows = _jsonl(tr.path)
        self.assertEqual(rows[0]['player'], [100.0, 200.0])
        self.assertEqual(rows[0]['entities'], [[10.0, 20.0, 'Grunt']])
        self.assertEqual(rows[0]['projectile_tracks'], [[1, 2, 'TankShell', 3, 4, 0.5]])
        self.assertEqual(rows[0]['hud']['score'], 100)
        self.assertIsNone(rows[1]['player'])
        self.assertTrue(rows[1]['held'])

    def test_bounded(self):
        tr = trace.DecisionTrace(self.d, max_bytes=300)
        obs = Observation((1.0, 1.0), [(float(i), 0.0, 'Grunt') for i in range(20)])
        for _ in range(10):
            tr.tick(obs=obs, move=1, fire=1, blind=0, held=False)
        s = tr.close()
        self.assertTrue(s['truncated'])
        self.assertLessEqual(s['bytes'], 300)
        self.assertEqual(s['ticks'], 10)


class DeathRingTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_window_before_and_after(self):
        ring = trace.DeathRing(self.d, hz=10, before_s=0.5, after_s=0.2,
                               max_events=5)
        for i in range(20):
            ring.push(_frame(i), dict(tick=i))
        ring.mark('d1', dict(kind='death'))
        for i in range(20, 25):
            ring.push(_frame(i), dict(tick=i))
        s = ring.close()
        self.assertEqual(s['events'], 1)
        self.assertIsNone(s['error'])
        ev_dir = os.path.join(self.d, 'deaths', 'd1')
        idx = _jsonl(os.path.join(ev_dir, 'index.jsonl'))
        self.assertEqual([r['tick'] for r in idx], list(range(15, 22)))   # 5 before + 2 after
        self.assertEqual(sum(r['before_mark'] for r in idx), 5)
        self.assertTrue(all(os.path.exists(os.path.join(ev_dir, r['file'])) for r in idx))
        ev = _json(os.path.join(ev_dir, 'event.json'))
        self.assertEqual(ev['info']['kind'], 'death')
        self.assertEqual(ev['n_frames'], 7)

    def test_copy_isolation_and_limits(self):
        ring = trace.DeathRing(self.d, hz=10, before_s=0.3, after_s=0.0, max_events=1)
        f = _frame(5)
        ring.push(f, {})
        f[:] = 0                          # mutate the source after push
        ring.mark('a')
        ring.mark('b')                    # over max_events
        s = ring.close()
        self.assertEqual(s['events'], 1)
        self.assertEqual(s['dropped_events'], 1)
        import cv2
        img = cv2.imread(os.path.join(self.d, 'deaths', 'a', 'frame_000.jpg'))
        self.assertGreater(int(img[:, :, 1].mean()), 2)   # the pushed copy, not the zeroed source

    def test_second_mark_during_tail_is_merged(self):
        ring = trace.DeathRing(self.d, hz=10, before_s=0.2, after_s=0.5)
        ring.push(_frame(), {})
        ring.mark('first')
        ring.push(_frame(), {})
        ring.mark('second')
        for _ in range(6):
            ring.push(_frame(), {})
        s = ring.close()
        self.assertEqual(s['events'], 1)
        self.assertEqual(s['merged_marks'], 1)
        ev = _json(os.path.join(self.d, 'deaths', 'first', 'event.json'))
        self.assertEqual(ev['info']['merged'][0]['label'], 'second')

    def test_close_flushes_partial_tail(self):
        ring = trace.DeathRing(self.d, hz=10, before_s=0.2, after_s=2.0)
        ring.push(_frame(), {})
        ring.mark('cut')
        s = ring.close()
        self.assertEqual(s['events'], 1)


class HardwareTraceTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_marks_on_death_and_game_over(self):
        ht = trace.HardwareTrace(self.d, hz=10, death_before_s=0.3, death_after_s=0.0)
        bk = FakeBookkeeper()
        obs = Observation((5.0, 5.0), [])
        for i in range(4):
            ht.tick(frame=_frame(i), obs=obs, move=1, fire=1, blind=0, held=False,
                    bookkeeper=bk)
        bk.deaths = 1
        bk.wave = 3
        ht.tick(frame=_frame(), obs=obs, move=1, fire=1, blind=0, held=False, bookkeeper=bk)
        bk.game_over_fired = True
        bk.max_wave = 3
        ht.tick(frame=_frame(), obs=obs, move=1, fire=1, blind=0, held=False, bookkeeper=bk)
        s = ht.close()
        self.assertEqual(s['marks'], 2)
        self.assertEqual(s['deaths']['events'], 2)
        names = sorted(os.listdir(os.path.join(self.d, 'deaths')))
        self.assertEqual(names, ['g1_d01_w3', 'g1_gameover_w3'])
        self.assertTrue(os.path.exists(os.path.join(self.d, trace.HardwareTrace.SUMMARY)))
        rows = _jsonl(os.path.join(self.d, 'decisions.jsonl'))
        self.assertEqual(rows[-1]['hud']['deaths'], 1)
        self.assertEqual(rows[-1]['game'], 'g1')

    def test_new_game_resets_death_baseline(self):
        ht = trace.HardwareTrace(self.d, hz=10, death_before_s=0.2, death_after_s=0.0)
        bk = FakeBookkeeper()
        bk.deaths = 5
        ht.tick(frame=_frame(), obs=Observation(None, []), move=0, fire=0, blind=1,
                held=False, bookkeeper=bk)
        bk.game_id, bk.deaths = 'g2', 0
        ht.tick(frame=_frame(), obs=Observation(None, []), move=0, fire=0, blind=1,
                held=False, bookkeeper=bk)
        s = ht.close()
        self.assertEqual(s['marks'], 0)


class FakePerception:
    """Scripted eye: a list of (player, entities, frame)."""
    def __init__(self, script):
        self.script = list(script)
        self.i = 0
        self.last_frame = None
        self.last_boxes = None
        self.latest_t = None
        self.seq = 0

    def perceive(self, state):
        p, ents, frame = self.script[min(self.i, len(self.script) - 1)]
        self.i += 1
        self.last_frame = frame
        self.latest_t = time.perf_counter()
        self.seq += 1
        return Observation(p, ents)

    def reset(self):
        pass


class FakeController:
    def __init__(self):
        self.sent = []

    def move_shoot(self, mv, fr):
        self.sent.append((mv, fr))

    def neutral(self):
        self.sent.append((0, 0))


class FakeBrain:
    player_lead_ticks = 1.5
    coaster = None

    def decide(self, player, entities):
        return 3, 1

    def blind_tick(self, entities):
        pass

    def reset(self):
        pass


class VisionLoopIntegrationTest(unittest.TestCase):
    """play_vision_game feeds the trace after the command is sent and the
    trace sees the bookkeeper's death."""
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_loop_feeds_trace(self):
        script = [((100.0, 100.0), [(150.0, 100.0, 'Grunt')], _frame(i)) for i in range(6)]
        script += [(None, [], _frame(9))] * 2
        perception = FakePerception(script)
        controller = FakeController()
        bk = FakeBookkeeper()
        tr = trace.HardwareTrace(self.d, hz=100, death_before_s=0.05, death_after_s=0.0)

        class HudReader:
            def read(self, frame):
                if perception.i >= 4:
                    bk.deaths = 1          # the bookkeeper reports a death
                return dict(score=0, wave=1, lives=3, conf=1.0)

        orig = harness.ensure_game_running
        harness.ensure_game_running = lambda *a, **k: True
        try:
            # games_limit trick: stop after the scripted frames by raising from
            # the perception when exhausted
            def perceive(state, _p=perception.perceive):
                if perception.i >= len(script):
                    raise KeyboardInterrupt
                return _p(state)
            perception.perceive = perceive
            with self.assertRaises(KeyboardInterrupt):
                # hz 15: the HUD is read every 3rd tick, so the death lands
                # on tick 6 while the player is still visible
                harness.play_vision_game(FakeBrain(), perception, controller,
                                         hz=15.0, bookkeeper=bk, hud_reader=HudReader(),
                                         hold_action=1, trace=tr)
        finally:
            harness.ensure_game_running = orig
        rows = _jsonl(os.path.join(self.d, 'decisions.jsonl'))
        self.assertEqual(len(rows), len(script))
        self.assertEqual(rows[0]['move'], 3)
        self.assertEqual(rows[0]['entities'], [[150.0, 100.0, 'Grunt']])
        self.assertTrue(rows[6]['held'])          # first blind tick held the command
        self.assertEqual(rows[6]['blind'], 1)
        self.assertFalse(rows[7]['held'])          # hold_action=1 exhausted
        self.assertEqual(rows[7]['move'], 0)
        self.assertTrue(any(r['hud']['deaths'] == 1 for r in rows))
        summ = _json(os.path.join(self.d, 'trace_summary.json'))
        self.assertEqual(summ['marks'], 1)
        self.assertEqual(summ['deaths']['events'], 1)
        self.assertEqual(len(os.listdir(os.path.join(self.d, 'deaths'))), 1)


def _synthetic_rows(n_ticks=400, tick=1 / 15, lag=2, death=True, killer_seen=True):
    """A player that answers each command `lag` ticks late at exactly the
    nominal speed. With death=True a death is staged near the end the way
    the emulator's oracle-timed games show it: the player collides at a wall
    with a Grunt 15 px away, everything freezes for 20 ticks (detector still
    reports the player), the screen blanks (entities gone, player blind) and
    the HUD death lands 1.6 s after the collision."""
    rows = []
    x, y = 300.0, 200.0
    cmd_hist = []
    t0 = 1000.0
    deaths = 0
    plan = [3 if (k // 20) % 2 == 0 else 7 for k in range(n_ticks)]
    for k in range(n_ticks):
        mv = plan[k]
        cmd_hist.append(mv)
        eff = cmd_hist[-1 - lag] if len(cmd_hist) > lag else 0
        dx, dy = trace_report.DXY_NOMINAL.get(eff, (0.0, 0.0))
        x += dx
        y += dy
        player = [x, y]
        ents = [[x + 20.0, y, 'Grunt']]
        blind = 0
        if death and n_ticks > 380:
            if k == 349:                                # collision tick
                player = [20.0, 200.0]
                ents = ([[35.0, 200.0, 'Grunt']] if killer_seen else []) + [[300.0, 300.0, 'Mommy']]
            elif 350 <= k < 370:                        # freeze: scene stands still
                player = [20.5, 200.0]
                ents = ([[35.0, 200.0, 'Grunt']] if killer_seen else []) + [[300.0, 300.0, 'Mommy']]
            elif 370 <= k < 380:                        # blank + respawn: blind
                player = None
                ents = []
                blind = k - 369
            if k == 373:
                deaths = 1
        rows.append(dict(t=t0 + k * tick, monotonic=k * tick, player=player,
                         entities=ents, projectile_tracks=[], move=mv, fire=1,
                         blind=blind, held=False, game='g',
                         hud=dict(score=1000 * (k // 40), wave=1 + k // 100,
                                  lives=3, deaths=deaths)))
    return rows


class TraceReportTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        with open(os.path.join(self.d, 'decisions.jsonl'), 'w', encoding='utf-8') as f:
            for r in _synthetic_rows():
                f.write(json.dumps(r) + '\n')

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_metrics(self):
        rep = trace_report.analyse(self.d)
        self.assertAlmostEqual(rep['loop']['tick_ms_median'], 66.7, delta=0.2)
        self.assertAlmostEqual(rep['player_speed']['x']['ratio'], 1.0, delta=0.02)
        rl = rep['reversal_latency']
        self.assertGreater(rl['reversals'], 10)
        self.assertEqual(rl['median'], 2)
        self.assertEqual(rep['games'][0]['max_wave'], 4)
        self.assertEqual(rep['games'][0]['hud_deaths'], 1)
        self.assertIn(1, rep['waves'])
        ds = rep['deaths']
        self.assertEqual(ds['deaths'], 1)
        self.assertEqual(ds['located'], 1)
        ctx = rep['death_contexts'][0]
        self.assertFalse(ctx['fallback'])
        self.assertEqual(ctx['killer'], 'Grunt')
        self.assertAlmostEqual(ctx['killer_distance'], 14.5, delta=0.6)
        self.assertTrue(ctx['near_wall'])
        self.assertEqual(ctx['wall_distance'], 20.0)
        self.assertEqual(ctx['wave'], 4)
        self.assertAlmostEqual(ctx['seconds_before_hud'], 24 / 15, delta=0.01)
        text = trace_report.format_report(rep)
        self.assertIn('reversal response: median +2', text)
        self.assertIn('killers: Grunt 1', text)

    def test_weekend_format_merges_hud_samples(self):
        # rows without hud + a hud_samples.jsonl in the production format
        rows = _synthetic_rows(60)
        with open(os.path.join(self.d, 'decisions.jsonl'), 'w', encoding='utf-8') as f:
            for r in rows:
                r.pop('hud'); r.pop('game')
                f.write(json.dumps(r) + '\n')
        with open(os.path.join(self.d, 'hud_samples.jsonl'), 'w', encoding='utf-8') as f:
            for k in range(0, 60, 3):
                f.write(json.dumps(dict(t=rows[k]['t'], game='w1', accepted=dict(
                    score=100 * k, wave=1 + k // 30, lives=3, deaths=0))) + '\n')
        rep = trace_report.analyse(self.d)
        self.assertEqual(rep['games'][0]['game'], 'w1')
        self.assertEqual(rep['games'][0]['max_wave'], 2)

    def test_unseen_killer(self):
        rows = _synthetic_rows(killer_seen=False)              # nothing lethal seen
        with open(os.path.join(self.d, 'decisions.jsonl'), 'w', encoding='utf-8') as f:
            for r in rows:
                f.write(json.dumps(r) + '\n')
        rep = trace_report.analyse(self.d)
        self.assertEqual(rep['death_contexts'][0]['killer'], 'UNSEEN')
        self.assertEqual(rep['deaths']['unseen_frac'], 1.0)


if __name__ == '__main__':
    unittest.main()
