"""Offline analysis of a hardware trace folder (decisions.jsonl [+ deaths/]).

    python -m robotron_ai.trace_report <folder> [--json out.json] [--waves N]

Answers, from the console's own per-tick record, the questions the summary
report cannot:

  cadence / blind   how often the loop ran and how often it was blind or
                    holding the last command
  player speed      planner px per real second along a held axis command,
                    against the calibrated 9.5 px per 66.7 ms tick — a
                    slow game, a weak stick, or a wrong arena scale all show
                    up here
  response latency  after a 180-degree move reversal, how many ticks until
                    the observed velocity follows (the emulator: 2 ticks,
                    94% of reversals)
  per-wave economy  HUD deaths and score per wave per game, plus the lives
                    the score could have bought (3 + score/25k) so the HUD's
                    miss rate is visible
  death context     for each HUD death, the collision tick (the last tick
                    the player moved before the death-animation freeze):
                    nearest lethal entity and distance (or UNSEEN if nothing
                    lethal was within reach), wall distance, coasting ghost
                    tracks, blind and held ticks just before, and the
                    commands sent

Also reads the weekend production format (no `hud` in rows, separate
hud_samples.jsonl) so the emulator's games give the reference numbers.
"""
import argparse
import json
import math
import os
import statistics as st
from collections import Counter, defaultdict

from . import coords

DXY_NOMINAL = {1: (0.0, -9.2), 2: (9.5, -9.2), 3: (9.5, 0.0), 4: (9.5, 9.2),
               5: (0.0, 9.2), 6: (-9.5, 9.2), 7: (-9.5, 0.0), 8: (-9.5, -9.2)}
AXIS = {1: (0, -1), 3: (1, 0), 5: (0, 1), 7: (-1, 0)}
OPP = {1: 5, 5: 1, 3: 7, 7: 3, 2: 6, 6: 2, 4: 8, 8: 4}
FAMILY = {'Mikey', 'Mommy', 'Daddy'}
NOMINAL_TICK = 1.0 / 15.0
KILL_R = 45.0        # px: a lethal entity this close at the last sighting is the killer
NEAR_R = 60.0        # px: "threats nearby" radius
WALL_R = 50.0        # px: "near a wall" (the emulator taxonomy's threshold)
FREEZE_TICKS = 8     # ticks: the player (and everything else) stands still this
                     # long right after the collision — the death animation,
                     # during which the detector still reports a "Player"
FREEZE_PX = 3.0      # px: movement below this is "standing still"
WINDOW_S = 4.5       # s: how far before the HUD death event the collision can be
                     # (animation ~1.5-2 s + respawn blank + HUD delay <= 2 s)


# ── loading ───────────────────────────────────────────────────────────────
def load_rows(folder):
    path = os.path.join(folder, 'decisions.jsonl')
    rows = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    hud_path = os.path.join(folder, 'hud_samples.jsonl')
    if rows and rows[0].get('hud') is None and os.path.exists(hud_path):
        _merge_hud_samples(rows, hud_path)
    for r in rows:
        r['entities'] = [tuple(e) for e in r.get('entities') or []]
        r['projectile_tracks'] = [_norm_track(t) for t in r.get('projectile_tracks') or []]
    return rows


def _norm_track(t):
    if isinstance(t, dict):
        return (float(t.get('x', 0)), float(t.get('y', 0)), t.get('name', '?'),
                float(t.get('vx', 0)), float(t.get('vy', 0)), float(t.get('miss', 0)))
    t = list(t) + [0.0] * (6 - len(t))
    return (float(t[0]), float(t[1]), t[2], float(t[3]), float(t[4]), float(t[5]))


def _merge_hud_samples(rows, hud_path):
    """Weekend production format: hud_samples.jsonl carries the bookkeeper's
    accepted state at ~5 Hz. Attach the latest sample at or before each row."""
    samples = []
    with open(hud_path, encoding='utf-8') as f:
        for line in f:
            try:
                s = json.loads(line)
            except ValueError:
                continue
            acc = s.get('accepted') or {}
            samples.append((s['t'], dict(score=acc.get('score'), wave=acc.get('wave'),
                                         lives=acc.get('lives'), deaths=acc.get('deaths', 0)),
                            s.get('game')))
    samples.sort(key=lambda x: x[0])
    j = 0
    cur = None
    for r in rows:
        while j < len(samples) and samples[j][0] <= r['t']:
            cur = samples[j]
            j += 1
        if cur is not None:
            r['hud'] = cur[1]
            r['game'] = r.get('game') or cur[2]


# ── basic loop statistics ─────────────────────────────────────────────────
def loop_stats(rows):
    dts = [b['monotonic'] - a['monotonic'] for a, b in zip(rows, rows[1:])
           if 0 < b['monotonic'] - a['monotonic'] < 0.5]
    blind = sum(1 for r in rows if r.get('player') is None)
    held = sum(1 for r in rows if r.get('held'))
    streaks = Counter()
    run = 0
    for r in rows:
        if r.get('player') is None:
            run += 1
        elif run:
            streaks[min(run, 20)] += 1
            run = 0
    return dict(ticks=len(rows),
                seconds=round(rows[-1]['t'] - rows[0]['t'], 1) if len(rows) > 1 else 0.0,
                tick_ms_median=round(st.median(dts) * 1e3, 1) if dts else None,
                hz=round(1.0 / st.median(dts), 2) if dts else None,
                blind_frac=round(blind / max(len(rows), 1), 4),
                held_frac=round(held / max(len(rows), 1), 4),
                blind_streaks=dict(sorted(streaks.items())))


def player_speed(rows, min_run=6):
    """px/s along a held axis command, measured over ticks 3..N of each run
    (the first ticks carry the actuation lag)."""
    rates = {'x': [], 'y': []}
    run = []
    for r in rows:
        mv, p = r.get('move'), r.get('player')
        if p is None or mv not in AXIS:
            run = []
            continue
        if run and run[-1][0] != mv:
            run = []
        run.append((mv, p, r['monotonic']))
        if len(run) >= min_run:
            (_, p0, t0), (_, p1, t1) = run[-4], run[-1]
            dt = t1 - t0
            if dt <= 0:
                continue
            ux, uy = AXIS[mv]
            # skip runs pressing into the wall ahead (the FSM's STAY is
            # emitted as UP, so "up at the top wall" is a standstill, not a
            # speed sample)
            ahead = {1: p0[1], 5: coords.PIX_H - p0[1],
                     7: p0[0], 3: coords.PIX_W - p0[0]}[mv]
            if ahead < 4 * 9.5 + 5:
                continue
            disp = (p1[0] - p0[0]) * ux + (p1[1] - p0[1]) * uy
            rates['x' if ux else 'y'].append(disp / dt)
    out = {}
    for k, v in rates.items():
        v = sorted(v)
        exp = (9.5 if k == 'x' else 9.2) / NOMINAL_TICK
        out[k] = dict(n=len(v),
                      median=round(st.median(v), 1) if v else None,
                      p90=round(v[int(0.9 * len(v))], 1) if v else None,
                      expected=round(exp, 1),
                      ratio=round(st.median(v) / exp, 3) if v else None)
    return out


def reversal_latency(rows, hold_before=3, hold_after=4, max_k=6):
    """Ticks from a 180-degree reversal command until the observed player
    velocity aligns (>0.7) with it. Unresolved = never aligned within max_k.

    Also in MILLISECONDS, because the tick length differs between rigs and
    rounds (the console ran 57 ms ticks in round 18 against 67 on the
    emulator, so "+3 ticks" there is 171 ms, not 200): `seen_by_ms` is the
    time from the command to the sample in which the response was seen, and
    `not_yet_ms` the time to the sample before it, in which it was not. The
    true latency lies between the two medians -- but those medians sit on
    the tick grid and cannot move for a sub-tick latency change. `estimate_ms`
    is a phase-corrected point estimate: for each resolved event the true
    latency lies in the bracket (not_yet_ms, seen_by_ms], uniformly (we don't
    know the phase of the command within the tick); its midpoint is an
    unbiased per-event estimate, and the mean of those midpoints (not the
    median -- the median is what's stuck on the grid) moves smoothly with
    the true latency. `estimate_err_ms` is the standard error of that mean:
    each bracket is a uniform(width) random variable around the midpoint,
    which has variance width^2/12, so the mean of n such midpoints has
    standard error mean(width)/sqrt(12*n)."""
    hist = Counter()
    n = unresolved = 0
    seen_by, not_yet, brackets = [], [], []
    for i in range(hold_before, len(rows) - hold_after - max_k):
        a, b = rows[i - 1].get('move'), rows[i].get('move')
        if a not in OPP or OPP[a] != b:
            continue
        if not all(rows[i - k].get('move') == a for k in range(1, hold_before + 1)):
            continue
        if not all(rows[i + k].get('move') == b for k in range(1, hold_after + 1)):
            continue
        ux, uy = DXY_NOMINAL[b]
        um = math.hypot(ux, uy)
        ux, uy = ux / um, uy / um
        found = None
        for k in range(0, max_k + 1):
            p0, p1 = rows[i + k - 1].get('player'), rows[i + k].get('player')
            if p0 is None or p1 is None:
                continue
            vx, vy = p1[0] - p0[0], p1[1] - p0[1]
            sp = math.hypot(vx, vy)
            if sp > 1.5 and (vx * ux + vy * uy) / sp > 0.7:
                found = k
                break
        n += 1
        if found is None:
            unresolved += 1
        else:
            hist[found] += 1
            t_cmd = rows[i].get('monotonic')
            s_hi = rows[i + found].get('sampled_at')
            s_lo = rows[i + found - 1].get('sampled_at')
            if t_cmd is not None and s_hi is not None:
                seen_ms = (s_hi - t_cmd) * 1000.0
                seen_by.append(seen_ms)
                if s_lo is not None:
                    not_yet_ms_v = (s_lo - t_cmd) * 1000.0
                    not_yet.append(not_yet_ms_v)
                    brackets.append((not_yet_ms_v, seen_ms))
    tot = sum(hist.values())
    ks = sorted(k for k in hist for _ in range(hist[k]))
    if brackets:
        mids = [(lo + hi) / 2.0 for lo, hi in brackets]
        widths = [hi - lo for lo, hi in brackets]
        mean_mid = st.mean(mids)
        mean_width = st.mean(widths)
        estimate_ms = mean_mid
        estimate_err_ms = mean_width / math.sqrt(12 * len(brackets))
    else:
        estimate_ms = estimate_err_ms = None
    return dict(reversals=n, unresolved=unresolved,
                median=ks[len(ks) // 2] if ks else None,
                histogram={str(k): dict(n=hist[k], frac=round(hist[k] / tot, 3))
                           for k in sorted(hist)} if tot else {},
                seen_by_ms=round(st.median(seen_by)) if seen_by else None,
                not_yet_ms=round(st.median(not_yet)) if not_yet else None,
                estimate_ms=estimate_ms,
                estimate_err_ms=estimate_err_ms,
                estimate_n=len(brackets))


# ── games, waves, deaths ──────────────────────────────────────────────────
def _game_rows(rows):
    games = defaultdict(list)
    for r in rows:
        if r.get('hud') and r.get('game'):
            games[r['game']].append(r)
    return games


def game_table(rows):
    out = []
    for gid, rs in _game_rows(rows).items():
        hud = [r['hud'] for r in rs if r['hud'].get('wave')]
        if not hud:
            continue
        maxw = max(h['wave'] for h in hud)
        score = max((h['score'] or 0) for h in hud)
        deaths = max((h['deaths'] or 0) for h in hud)
        out.append(dict(game=gid, max_wave=maxw, score=score, hud_deaths=deaths,
                        lives_bought=3 + score // 25000,
                        seconds=round(rs[-1]['t'] - rs[0]['t'], 1)))
    return out


def wave_table(rows, max_wave=12):
    """Per-wave HUD deaths and score deltas, completed waves only, across games."""
    deaths = defaultdict(list)
    scores = defaultdict(list)
    for gid, rs in _game_rows(rows).items():
        first, last = {}, {}
        for r in rs:
            h = r['hud']
            w = h.get('wave')
            if not w:
                continue
            first.setdefault(w, h)
            last[w] = h
        if not first:
            continue
        maxw = max(first)
        for w in sorted(first):
            if w >= maxw or w > max_wave:
                continue          # the terminal wave is incomplete
            d0, d1 = first[w].get('deaths') or 0, last[w].get('deaths') or 0
            s0, s1 = first[w].get('score') or 0, last[w].get('score') or 0
            deaths[w].append(d1 - d0)
            scores[w].append(max(0, s1 - s0))
    table = {}
    for w in sorted(deaths):
        table[w] = dict(n=len(deaths[w]),
                        deaths_per_wave=round(st.mean(deaths[w]), 2),
                        score_per_wave=round(st.mean(scores[w])))
    return table


def _wall_distance(p):
    return round(min(p[0], coords.PIX_W - p[0], p[1], coords.PIX_H - p[1]), 1)


def _nearest(p, items):
    best = None
    for it in items:
        d = math.hypot(it[0] - p[0], it[1] - p[1])
        if best is None or d < best[0]:
            best = (d, it)
    return best


def death_contexts(rows, window_s=WINDOW_S):
    """One record per HUD death (and game over): the collision tick and what
    was around the player then.

    How a death looks in the trace (verified on the emulator's oracle-timed
    games, 2026-09-14): the player collides, then for ~1.5-2 s the whole
    scene FREEZES while the player sprite dissolves — the detector keeps
    reporting a "Player" at the same spot — then the screen blanks (entities
    vanish, player blind), the game re-forms, and the HUD's lives count drops
    ~0.3-2 s after that. So the collision is the last tick the player MOVED
    before a standstill of FREEZE_TICKS or more that is followed by a blank
    or blind stretch, all within WINDOW_S before the HUD event."""
    out = []
    games = _game_rows(rows)
    for gid, rs in games.items():
        prev_deaths = None
        for idx, r in enumerate(rs):
            d = r['hud'].get('deaths') or 0
            if prev_deaths is not None and d > prev_deaths:
                out.append(_context(rs, idx, gid, d, window_s))
            prev_deaths = d
    return out


def _moved(a, b):
    pa, pb = a.get('player'), b.get('player')
    if pa is None or pb is None:
        return None
    return math.hypot(pb[0] - pa[0], pb[1] - pa[1])


def _locate_collision(rs, idx, window_s):
    """Index of the last moving tick before the death freeze, or None."""
    t_ev = rs[idx]['t']
    lo = idx
    while lo > 0 and t_ev - rs[lo]['t'] <= window_s:
        lo -= 1
    k = idx - 1
    while k > lo:
        d = _moved(rs[k - 1], rs[k]) if k > 0 else None
        if d is not None and d >= FREEZE_PX:
            # is the player still (visible, < FREEZE_PX from here) for the
            # next FREEZE_TICKS ticks?
            p0 = rs[k]['player']
            still = 0
            j = k + 1
            while j < len(rs) and rs[j].get('player') is not None                     and math.hypot(rs[j]['player'][0] - p0[0],
                                   rs[j]['player'][1] - p0[1]) < FREEZE_PX:
                still += 1
                j += 1
            if still >= FREEZE_TICKS:
                # ...and followed by the blank/blind stretch (not a live
                # player pinned in a corner)
                n0 = max(1, len(rs[k]['entities']))
                for m in range(j, min(len(rs), j + 45)):
                    if rs[m].get('player') is None or len(rs[m]['entities']) <= 0.4 * n0:
                        return k
        k -= 1
    return None


def _context(rs, idx, gid, deaths_no, window_s):
    t_ev = rs[idx]['t']
    k = _locate_collision(rs, idx, window_s)
    fallback = k is None
    if fallback:
        # no freeze found: the last visible tick before the event
        lo = idx
        while lo > 0 and t_ev - rs[lo]['t'] <= window_s:
            lo -= 1
        k = idx
        while k > lo and rs[k].get('player') is None:
            k -= 1
        if rs[k].get('player') is None:
            return dict(game=gid, death=deaths_no, t=t_ev, located=False)
    r = rs[k]
    p = r['player']
    lethal = [e for e in r['entities'] if e[2] not in FAMILY]
    ghosts = [t for t in r['projectile_tracks'] if t[5] > 0]
    near = _nearest(p, lethal)
    near_ghost = _nearest(p, ghosts)
    # the freeze-start tick (k+1) shows the collision position itself
    nxt = rs[k + 1] if k + 1 < len(rs) and rs[k + 1].get('player') else None
    near_next = _nearest(nxt['player'], [e for e in nxt['entities'] if e[2] not in FAMILY]) if nxt else None
    cand = [c for c in (near, near_next) if c]
    killer = min(cand, key=lambda c: c[0]) if cand else None
    threats60 = sum(1 for e in lethal if math.hypot(e[0] - p[0], e[1] - p[1]) <= NEAR_R)
    before = rs[max(0, k - 15):k]
    return dict(
        game=gid, death=deaths_no, t=t_ev, located=True, fallback=fallback,
        wave=r['hud'].get('wave'),
        seconds_before_hud=round(t_ev - r['t'], 2),
        player=[round(p[0], 1), round(p[1], 1)],
        wall_distance=_wall_distance(p),
        near_wall=_wall_distance(p) < WALL_R,
        killer=(killer[1][2] if killer and killer[0] <= KILL_R else 'UNSEEN'),
        killer_distance=round(killer[0], 1) if killer else None,
        nearest_class=near[1][2] if near else None,
        nearest_distance=round(near[0], 1) if near else None,
        nearest_ghost=(near_ghost[1][2], round(near_ghost[0], 1)) if near_ghost else None,
        threats_within_60=threats60,
        entities_seen=len(lethal),
        blind_ticks_before=sum(1 for c in before if c.get('player') is None),
        held_ticks_before=sum(1 for c in before if c.get('held')),
        moves_before=[b.get('move') for b in rs[max(0, k - 5):k + 1]],
        fires_before=[b.get('fire') for b in rs[max(0, k - 5):k + 1]],
    )


def death_summary(ctxs):
    located = [c for c in ctxs if c.get('located')]
    if not located:
        return dict(deaths=len(ctxs), located=0)
    killers = Counter(c['killer'] for c in located)
    return dict(
        deaths=len(ctxs), located=len(located),
        fallback_located=sum(1 for c in located if c.get('fallback')),
        near_wall_frac=round(sum(c['near_wall'] for c in located) / len(located), 3),
        unseen_frac=round(killers.get('UNSEEN', 0) / len(located), 3),
        killers={k: v for k, v in killers.most_common()},
        median_threats_within_60=st.median(c['threats_within_60'] for c in located),
        blind_before_frac=round(sum(1 for c in located if c['blind_ticks_before'] >= 3)
                                / len(located), 3),
        median_seconds_before_hud=round(st.median(c['seconds_before_hud']
                                                  for c in located), 2),
    )


# ── report ────────────────────────────────────────────────────────────────
def analyse(folder, max_wave=12):
    rows = load_rows(folder)
    if not rows:
        return dict(folder=folder, error='no rows')
    ctxs = death_contexts(rows)
    rep = dict(folder=folder,
               loop=loop_stats(rows),
               player_speed=player_speed(rows),
               reversal_latency=reversal_latency(rows),
               games=game_table(rows),
               waves=wave_table(rows, max_wave=max_wave),
               deaths=death_summary(ctxs),
               death_contexts=ctxs)
    summ = os.path.join(folder, 'trace_summary.json')
    if os.path.exists(summ):
        try:
            with open(summ, encoding='utf-8') as f:
                rep['trace_summary'] = json.load(f)
        except (OSError, ValueError):
            pass
    return rep


def format_report(rep):
    L = []
    if rep.get('error'):
        return f"{rep['folder']}: {rep['error']}"
    lo = rep['loop']
    L.append(f"trace: {rep['folder']}")
    L.append(f"ticks {lo['ticks']}  {lo['seconds']} s  tick {lo['tick_ms_median']} ms "
             f"({lo['hz']} Hz)  blind {lo['blind_frac']:.1%}  held {lo['held_frac']:.1%}")
    ps = rep['player_speed']
    for k in ('x', 'y'):
        v = ps[k]
        if v['n']:
            L.append(f"player speed {k}: median {v['median']} px/s (p90 {v['p90']}) "
                     f"vs expected {v['expected']} -> ratio {v['ratio']}  [n={v['n']}]")
    rl = rep['reversal_latency']
    if rl['reversals']:
        hist = ', '.join(f"+{k}: {v['frac']:.0%}" for k, v in rl['histogram'].items())
        L.append(f"reversal response: median +{rl['median']} ticks  ({hist}; "
                 f"unresolved {rl['unresolved']}/{rl['reversals']})")
        if rl.get('seen_by_ms') is not None:
            L.append(f"  in ms: response seen by {rl['seen_by_ms']} ms, not yet at "
                     f"{rl['not_yet_ms']} ms (true latency between the two; the "
                     f"emulator reads 117 / 50; compare rigs in ms, ticks differ)")
        if rl.get('estimate_ms') is not None:
            L.append(f"  estimate: ~{rl['estimate_ms']:.0f} ms (mean of the per-event "
                     f"frame brackets, ±{rl['estimate_err_ms']:.0f}; n={rl['estimate_n']})")
    if rep['games']:
        L.append("games:")
        for g in rep['games']:
            short = g['lives_bought'] - g['hud_deaths']
            L.append(f"  {g['game']}: W{g['max_wave']}  score {g['score']}  "
                     f"HUD deaths {g['hud_deaths']}  lives bought {g['lives_bought']}"
                     + (f"  (HUD missed {short}: icon row full)" if short > 1 else "")
                     + f"  {g['seconds']} s")
        L.append("  (a game ends with every life lost, so lives bought = 3 + score/25000 "
                 "is the true death total; the HUD tally is a lower bound)")
    if rep['waves']:
        L.append("per wave (completed waves, mean over games):")
        L.append("  wave  n   deaths/wave  score/wave")
        for w, v in rep['waves'].items():
            L.append(f"  {w:>4} {v['n']:>3}   {v['deaths_per_wave']:>10.2f}  {v['score_per_wave']:>10}")
    ds = rep['deaths']
    if ds.get('located'):
        L.append(f"deaths: {ds['deaths']} HUD events, {ds['located']} located "
                 f"({ds['fallback_located']} without a visible death freeze)")
        L.append(f"  near wall (<{WALL_R:.0f} px): {ds['near_wall_frac']:.0%}   "
                 f"killer UNSEEN (nothing lethal within {KILL_R:.0f} px): {ds['unseen_frac']:.0%}   "
                 f"blind >=3 of last 15 ticks: {ds['blind_before_frac']:.0%}")
        L.append(f"  killers: " + ', '.join(f"{k} {v}" for k, v in ds['killers'].items()))
        L.append(f"  median threats within {NEAR_R:.0f} px: {ds['median_threats_within_60']}   "
                 f"median HUD delay: {ds['median_seconds_before_hud']} s")
    ts = rep.get('trace_summary')
    if ts:
        d = ts.get('deaths') or {}
        L.append(f"death windows on disk: {d.get('events', 0)} "
                 f"({d.get('written_frames', 0)} frames, {d.get('bytes', 0) / 1e6:.0f} MB)")
    return '\n'.join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('folder', help='hardware_report folder (has decisions.jsonl)')
    ap.add_argument('--json', default=None, help='also write the full report here')
    ap.add_argument('--waves', type=int, default=12, help='per-wave table depth')
    a = ap.parse_args(argv)
    rep = analyse(a.folder, max_wave=a.waves)
    print(format_report(rep))
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as f:
            json.dump(rep, f, indent=1)
    return rep


if __name__ == '__main__':
    main()
