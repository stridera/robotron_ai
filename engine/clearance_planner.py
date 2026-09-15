"""Minimal-deviation multi-step analytic clearance planner (the champion's brain).

Extracted from search_value.py (2026-07-01) so the eval harness, eval_protocol
promotions, and future live deploys share ONE implementation. Behavior-identical
to the N=100-validated champion: VSEARCH_CLEAR H=6 DANGER=18 MARGIN=10, ASM-true
dynamics (VSEARCH_ASMDYN=1 default).

Config via the same env vars search_value.py used, read at import:
  VSEARCH_H, VSEARCH_CLEAR_DANGER, VSEARCH_CLEAR_MARGIN, VSEARCH_ASMDYN,
  VSEARCH_FIREPLAN, VSEARCH_FIREPLAN_HULK_R
"""
from __future__ import annotations

import math
import os

import numpy as np

CLEAR_H = int(os.environ.get("VSEARCH_H", "6"))
CLEAR_DANGER = float(os.environ.get("VSEARCH_CLEAR_DANGER", "18"))
CLEAR_MARGIN = float(os.environ.get("VSEARCH_CLEAR_MARGIN", "10"))
# Experimental collision sampling; 1 preserves the validated endpoint-only
# planner. 4 checks at nominal game-frame intervals without changing the
# coarse-step chase model, search horizon, decision cadence or safety margins.
COLLISION_SUBSTEPS = int(os.environ.get("VSEARCH_COLLISION_SUBSTEPS", "1"))
if not 1 <= COLLISION_SUBSTEPS <= 16:
    raise ValueError("VSEARCH_COLLISION_SUBSTEPS must be in [1, 16]")
_COLLISION_FRACTIONS = (np.arange(1, COLLISION_SUBSTEPS, dtype=float)
                        / COLLISION_SUBSTEPS)[:, None]


def set_margins(danger: float, margin: float) -> None:
    """Rebind the safety margins after import (constants are read at call
    time, so this takes effect immediately). Used by ChampionBrain to apply
    the vision-path margins (2026-07-08 dose-response A/B: 18/10 is optimal
    on exact memory input; 21/12 (~1.15x) is optimal on vision, absorbing
    tracking noise — mean 14.4 vs 13.6, floor W10 vs W7; 1.3x regressed)."""
    global CLEAR_DANGER, CLEAR_MARGIN
    CLEAR_DANGER = float(danger)
    CLEAR_MARGIN = float(margin)


def set_fireplan(on: bool) -> None:
    """Enable/disable fire-at-the-binding-threat after import. ChampionBrain
    turns this ON for the vision path (2026-07-30, replicated 2026-07-31):
    with ~2 ticks of actuation latency a close-fired spark arrives before any
    dodge can act, so the only defence is killing the launcher — d/w 1.20 vs
    1.38 (p=.027), max wave 21.9 vs 17.5 (p=.007), and the first positive net
    life economy measured on vision. Memory input keeps its own default."""
    global FIREPLAN
    FIREPLAN = bool(on)
# Least-bad surround escape (2026-07-05): when NO heading clears the safety margin
# (fully boxed in), the old code falls back to the FSM move — which in a dense
# swarm is STAY (stand still = the classic deep-wave death). Instead pick the
# argmax-clearance heading — the least-bad direction always beats standing still.
LEAST_BAD = os.environ.get("VSEARCH_LEAST_BAD", "0") == "1"
ASMDYN = os.environ.get("VSEARCH_ASMDYN", "1") == "1"
FIREPLAN = os.environ.get("VSEARCH_FIREPLAN", "0") == "1"
FIREPLAN_HULK_R = float(os.environ.get("VSEARCH_FIREPLAN_HULK_R", "90"))
# Per-class clearance weights for the two spark-band A/B knobs (2026-07-30).
# Both measured FLAT at 1.15-2.4x on vision — kept as env knobs, not defaults.
SPARK_W = float(os.environ.get("VSEARCH_W_SPARK", "1.8"))
ENF_W = float(os.environ.get("VSEARCH_W_ENF", "1.3"))

# Per-env-step player displacement (obs px) by server move dir 1..8, measured
# 2026-06-28 at frameskip 4; scales linearly with frameskip (1px/frame per axis).
_FS_SCALE = int(os.environ.get("VSEARCH_FRAMESKIP", "4")) / 4.0
DXY = {1: (0.0, -9.2), 2: (9.5, -9.2), 3: (9.5, 0.0), 4: (9.5, 9.2),
       5: (0.0, 9.2), 6: (-9.5, 9.2), 7: (-9.5, 0.0), 8: (-9.5, -9.2)}
DXY = {d: (x * _FS_SCALE, y * _FS_SCALE) for d, (x, y) in DXY.items()}
_DXY_NOMINAL = {d: v for d, v in DXY.items()}
PX_MIN, PX_MAX, PY_MIN, PY_MAX = 10.0, 655.0, 10.0, 482.0
# Opt-in production coordinate-parity screen: video player wall positions map
# to 0..665 / 0..492 (coords.py). The inherited inset can move a wall-pinned
# player ten pixels inward even when the commanded heading points outward.
# Enemy bounds/dynamics and clearance margins deliberately remain independent.
PLAYER_FULL_BOUNDS = os.environ.get("VSEARCH_PLAYER_FULL_BOUNDS", "0") == "1"
PLAYER_X_MIN, PLAYER_X_MAX, PLAYER_Y_MIN, PLAYER_Y_MAX = (
    (0.0, 665.0, 0.0, 492.0) if PLAYER_FULL_BOUNDS
    else (PX_MIN, PX_MAX, PY_MIN, PY_MAX))

# ── decision-tick rescaling (2026-07-28) ──────────────────────────────────
# Every per-step constant here (DXY player displacement, the chase-speed
# bands, the CLEAR_H horizon) is calibrated for ONE decision step = 66.7 ms
# (15 Hz). If the live loop can't hold that — a slower host, or the real-
# hardware path where HDMI capture + serial actuation cost more — the game
# advances further per decision and every constant is silently wrong (an
# 83 ms tick makes them 25% short). set_tick_scale(k) rescales for a step
# k x the nominal duration: DXY x k, chase-speed bands x k, horizon
# CLEAR_H / k (same look-ahead TIME). Driven by the harness TickClock from
# the measured cadence; k == 1.0 (the deadline-held 15 Hz) is a no-op.
TICK_SCALE = 1.0
CLEAR_H_EFF = CLEAR_H


def set_tick_scale(k: float) -> float:
    """Rescale per-step kinematics for a decision tick k x the nominal 66.7 ms.
    Returns the clamped k actually applied. DXY is mutated IN PLACE so modules
    that did `from clearance_planner import DXY` see the update."""
    global TICK_SCALE, CLEAR_H_EFF
    k = min(max(float(k), 0.25), 4.0)
    if abs(k - TICK_SCALE) < 1e-3:
        return TICK_SCALE
    TICK_SCALE = k
    for d, (x, y) in _DXY_NOMINAL.items():
        DXY[d] = (x * k, y * k)
    CLEAR_H_EFF = int(min(max(round(CLEAR_H / k), 3), 12))
    return k


def _spd(spd, lo, hi):
    """Clamp a measured per-step speed into a class's [lo, hi] band, with the
    band scaled to the real tick duration."""
    return max(lo * TICK_SCALE, min(spd, hi * TICK_SCALE))


_FIRE_DIRS = (3, 4, 5, 6, 7, 8, 1, 2)   # compass by 45deg from East, screen y-down


def _angdist(a, b):
    d = abs(a - b)
    return min(d, 8 - d)   # compass steps 0..4


def _dir_toward(px, py, tx, ty):
    """Quantize the bearing player->target to the 1..8 compass (1=N .. 3=E .. 5=S)."""
    ang = math.degrees(math.atan2(ty - py, tx - px))   # 0=E, +90=S (screen y-down)
    return _FIRE_DIRS[int(round(ang / 45.0)) % 8]


def _classify_threat(name, vx, vy):
    """(weight, is_chaser, chase_speed, reflects). weight<=0 => ignore (family).
    ASM-grounded dynamics (ENEMY_MODEL.md §4/§9 + robomame.asm); ASMDYN=0 restores
    the pre-2026-07 model (A/B control)."""
    spd = math.hypot(vx, vy)
    if not ASMDYN:                                   # pre-2026-07 baseline (A/B control)
        if name in ("Mikey", "Mommy", "Daddy"):
            return 0.0, False, 0.0, False
        if name == "Hulk":
            return 2.5, True, _spd(spd, 2.5, 6.0), False
        if name == "Quark":
            return 2.0, False, 0.0, False
        if name in ("EnforcerBullet", "Spark", "CruiseMissile", "TankShell"):
            return 1.8, False, spd, False
        if name == "Grunt":
            return 1.0, True, _spd(spd, 5.0, 13.0), False
        if name in ("Brain", "Prog"):
            return 1.2, True, _spd(spd, 4.0, 12.0), False
        if name == "Electrode":
            return 0.8, False, 0.0, False
        return 1.0, False, spd, False
    if name in ("Mikey", "Mommy", "Daddy"):
        return 0.0, False, 0.0, False                # family — not lethal
    if name == "Hulk":
        # invincible pinning obstacle (30% of deaths) — wide berth, slow 4-dir mover
        return 2.2, True, _spd(spd, 2.0, 5.0), False
    if name == "Quark":
        # slow random wanderer, NO homing, <=~9.5px/step (asm:7201-7248)
        return 1.0, False, spd, False
    if name == "TankShell":
        # straight & fast, REFLECTS off all 4 walls (asm:7807-7857); ~half are
        # deliberate wall-bank shots (asm:7694-7757)
        return 1.8, False, spd, True
    if name == "CruiseMissile":
        # homes on the player, re-aims every <=8 ticks (asm:3082-3118)
        return 1.6, True, _spd(spd, 6.0, 14.0), False
    if name == "EnforcerBullet":
        # spark: ballistic + fixed curvature, never re-homes (asm:2082-2087)
        return SPARK_W, False, spd, False
    if name == "Enforcer":
        # dives at the player, velocity ∝ distance (asm:1933-1964)
        return ENF_W, True, _spd(spd, 3.0, 22.0), False
    if name == "Grunt":
        return 1.0, True, _spd(spd, 5.0, 13.0), False   # 4px axis beeline
    if name == "Prog":
        return 1.1, True, _spd(spd, 4.0, 12.0), False
    if name == "Brain":
        # chases the nearest HUMAN, not the player (asm:2466-2475)
        return 1.1, False, spd, False
    if name == "Electrode":
        return 0.8, False, 0.0, False
    return 1.0, False, spd, False                    # Tank/Spheroid/other


def _intermediate_clearance(px, py, dx, dy, tx0, ty0, tx1, ty1, w, refl):
    """Per-threat minimum at intermediate fractions of ONE coarse step.

    tx1/ty1 are the pre-wall endpoints from the existing dynamics. Interpolate
    before reflecting/clamping, so a bank shot visits the wall instead of
    taking a false straight chord between its start and reflected endpoint.
    Likewise, a player that reaches a wall stops there at the correct fraction.
    Sampling excludes t=0: it adds future checks, not an identical initial
    clearance ceiling on every escape. This is sampled, not swept, collision
    checking; impacts between the extra samples can still be missed.
    """
    f = _COLLISION_FRACTIONS
    pxs = np.clip(px + dx * f, PLAYER_X_MIN, PLAYER_X_MAX)
    pys = np.clip(py + dy * f, PLAYER_Y_MIN, PLAYER_Y_MAX)
    xs = tx0 + (tx1 - tx0) * f
    ys = ty0 + (ty1 - ty0) * f
    if ASMDYN:
        reflect = refl == 1
        if reflect.any():
            xs = np.where(reflect & (xs < PX_MIN), 2 * PX_MIN - xs,
                          np.where(reflect & (xs > PX_MAX), 2 * PX_MAX - xs, xs))
            ys = np.where(reflect & (ys < PY_MIN), 2 * PY_MIN - ys,
                          np.where(reflect & (ys > PY_MAX), 2 * PY_MAX - ys, ys))
        xs = np.clip(xs, PX_MIN, PX_MAX)
        ys = np.clip(ys, PY_MIN, PY_MAX)
    return np.sqrt((pxs - xs) ** 2 + (pys - ys) ** 2).min(axis=0) / w


def _heading_clearance(px, py, T, d, H, return_argmin=False):
    """Min weighted clearance if the player commits to heading d for H env-steps.
    T = (tx,ty,vx,vy,w,chase,spd,refl) numpy arrays. Chasers re-aim toward the
    player each step; reflectors mirror off walls with velocity negation
    (asm:7807-7857); others clamp at the border like the game's integrator
    (asm:17308-17327). With return_argmin, also returns the BINDING threat index."""
    tx, ty, tvx, tvy, w, chase, spd, refl = T
    ppx, ppy = px, py
    dx_, dy_ = DXY[d]
    tx = tx.copy(); ty = ty.copy()
    tvx = tvx.copy(); tvy = tvy.copy()
    worst = 1e18; worst_i = 0
    for _ in range(H):
        if COLLISION_SUBSTEPS > 1:
            px0, py0, tx0, ty0 = ppx, ppy, tx, ty
        ppx = min(PLAYER_X_MAX, max(PLAYER_X_MIN, ppx + dx_))
        ppy = min(PLAYER_Y_MAX, max(PLAYER_Y_MIN, ppy + dy_))
        if chase.any():
            ax = ppx - tx; ay = ppy - ty
            dist = np.sqrt(ax * ax + ay * ay) + 1e-6
            step = spd / dist
            tx = np.where(chase, tx + ax * step, tx + tvx)
            ty = np.where(chase, ty + ay * step, ty + tvy)
        else:
            tx = tx + tvx; ty = ty + tvy
        if COLLISION_SUBSTEPS > 1:
            intermediate = _intermediate_clearance(
                px0, py0, dx_, dy_, tx0, ty0, tx, ty, w, refl)
        if ASMDYN:
            if refl.any():
                lo = refl & (tx < PX_MIN); hi = refl & (tx > PX_MAX)
                tvx = np.where(lo | hi, -tvx, tvx)
                tx = np.where(lo, 2 * PX_MIN - tx, np.where(hi, 2 * PX_MAX - tx, tx))
                lo = refl & (ty < PY_MIN); hi = refl & (ty > PY_MAX)
                tvy = np.where(lo | hi, -tvy, tvy)
                ty = np.where(lo, 2 * PY_MIN - ty, np.where(hi, 2 * PY_MAX - ty, ty))
            tx = np.clip(tx, PX_MIN, PX_MAX); ty = np.clip(ty, PY_MIN, PY_MAX)
        clr = np.sqrt((ppx - tx) ** 2 + (ppy - ty) ** 2) / w
        if COLLISION_SUBSTEPS > 1:
            clr = np.minimum(clr, intermediate)
        i = int(clr.argmin()); m = float(clr[i])
        if m < worst:
            worst = m; worst_i = i
    return (worst, worst_i) if return_argmin else worst


def clearance_search(sprites, fsm_mv, first_fire):
    """Guarded multi-step clearance override over pre-extracted sprites
    [(x, y, name, vx, vy), ...]. Keeps the FSM move unless its heading is in
    danger and a clearly-safer heading exists (minimal deviation)."""
    player = next((s for s in sprites if s[2] == "Player"), None)
    if player is None:
        return fsm_mv, first_fire
    px, py = player[0], player[1]
    xs, ys, vxs, vys, ws, ch, sp, rf, nm = [], [], [], [], [], [], [], [], []
    for s in sprites:
        if s[2] == "Player":
            continue
        # Velocities arrive in px per NOMINAL (66.7 ms) tick. The search
        # steps are TICK_SCALE nominal ticks long (set_tick_scale), and the
        # player already moves DXY*k per step — threats must move v*k per
        # step too, or at a 30 Hz decision rate (k=0.5) every projectile
        # flies twice as fast in the simulation as on screen (2026-09-03).
        svx, svy = s[3] * TICK_SCALE, s[4] * TICK_SCALE
        wt, isch, speed, refl = _classify_threat(s[2], svx, svy)
        if wt <= 0.0:
            continue
        xs.append(s[0]); ys.append(s[1]); vxs.append(svx); vys.append(svy)
        ws.append(wt); ch.append(isch); sp.append(speed); rf.append(refl)
        nm.append(s[2])
    if not xs:
        return fsm_mv, first_fire
    T = (np.array(xs), np.array(ys), np.array(vxs), np.array(vys),
         np.array(ws), np.array(ch, dtype=bool), np.array(sp),
         np.array(rf, dtype=bool))
    clr = [_heading_clearance(px, py, T, d, CLEAR_H_EFF) for d in range(1, 9)]
    v_fsm = clr[fsm_mv - 1]
    if v_fsm >= CLEAR_DANGER:                      # FSM heading is safe enough — trust it
        return fsm_mv, first_fire
    cand = [d for d in range(1, 9) if clr[d - 1] >= v_fsm + CLEAR_MARGIN]
    if cand:
        best_d = min(cand, key=lambda d: (_angdist(d, fsm_mv), -clr[d - 1]))
    elif LEAST_BAD:
        best_d = max(range(1, 9), key=lambda d: clr[d - 1])   # surrounded: least-bad dir
    else:
        best_d = fsm_mv
    if FIREPLAN:
        _, bi = _heading_clearance(px, py, T, best_d, CLEAR_H_EFF, return_argmin=True)
        bx, by = float(T[0][bi]), float(T[1][bi])
        if nm[bi] != "Hulk" or ((bx - px) ** 2 + (by - py) ** 2) <= FIREPLAN_HULK_R ** 2:
            return best_d, _dir_toward(px, py, bx, by)
    return best_d, first_fire
