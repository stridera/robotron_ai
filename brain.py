"""ChampionBrain — the shared decision core for every input/output combination.

It consumes an observation (player + entities in planner pixel space, engine
entity names) and returns a (move, fire) pair of directions 1..8. Internally it
is the exact pipeline that reached wave 138 on the memory path:

    velocity tracking  ->  latency extrapolation  ->  player forward-prediction
    ->  evolved FSM (chooseOutputs)  ->  clearance planner (minimal-deviation
    multi-step dodge search)

The brain is perception- and controller-agnostic; the harness feeds it and
routes its output to whichever controller is active.
"""
import json
import math
import os
import time

# Whether the USER pinned the planner margins / fireplan (before our
# setdefaults make the vars exist unconditionally) — a pinned value always
# wins over the per-path defaults applied in ChampionBrain.__init__.
_USER_PINNED_MARGINS = ("VSEARCH_CLEAR_DANGER" in os.environ
                        or "VSEARCH_CLEAR_MARGIN" in os.environ)
_USER_PINNED_FIREPLAN = "VSEARCH_FIREPLAN" in os.environ
_USER_PINNED_FIRE_ALT = "VSEARCH_FIRE_ALT" in os.environ
# These two are independent of each other (pinning one leaves the other's
# vision default on), unlike the margins pair.
_USER_PINNED_SKIP_RECEDING = "FSM_FIRE_SKIP_RECEDING" in os.environ
_USER_PINNED_FALLBACK_REACH = "FSM_FIRE_FALLBACK_REACH" in os.environ

# The planner reads these at import time, so seed the champion defaults BEFORE
# importing the engine modules. setdefault => real env vars still win (for A/B).
os.environ.setdefault("VSEARCH_ASMDYN", "1")
os.environ.setdefault("VSEARCH_H", "6")
os.environ.setdefault("VSEARCH_CLEAR_DANGER", "18")
os.environ.setdefault("VSEARCH_CLEAR_MARGIN", "10")
os.environ.setdefault("FSM_RESCUE_SEEK", "1")

from .engine import robotron_fsm as fsm                       # noqa: E402
from .engine import clearance_planner as cp                    # noqa: E402
from .engine.clearance_planner import (clearance_search, DXY,  # noqa: E402
                                       set_margins, set_fireplan, set_fire_alt,
                                       set_fire_exclude, _dir_toward)
# Vision-path planner margins (2026-07-08 dose-response A/B): ~1.15x the
# memory-optimal 18/10 absorbs vision tracking noise (mean 14.4 vs 13.6,
# worst-game floor W10 vs W7); 1.3x regressed. Memory path keeps 18/10.
VISION_MARGINS = (21.0, 12.0)
VISION_FIRE_ALT_R = 400.0   # fire-alternation second-target radius (proxy plateau)
# 2026-11 MAME lab (package brain, paired): both knobs together ACT 8 900 games
# NET +0.023 [+0.009,+0.037], waves +0.87; ACT 4 600 games NET +0.018, waves +0.90.
# Vision defaults unless pinned (explicit =0 turns one off); memory path keeps 0.
VISION_FIRE_FALLBACK_REACH = 250.0
VISION_SKIP_RECEDING = True
from . import coords                                          # noqa: E402

# ── Behaviour knobs (2026-11; FIRE_FALLBACK_REACH and SKIP_RECEDING are vision defaults, see ChampionBrain.__init__) ─────────────
# FSM_FIRE_FALLBACK_REACH (px, 0 = off): when the FSM has nothing to shoot
# (fire STAY) the old code fires along the MOVE direction, which is how the bot
# ends up shooting the civilians it is walking toward. With a reach, fire at the
# nearest killable (not family / hulk / electrode) within that many px whose
# bearing, led by its velocity over the laser's flight time, lies within
# FALLBACK_LINE_DEG of one of the 8 fire directions; none lined up = old fallback.
FIRE_FALLBACK_REACH = float(os.environ.get("FSM_FIRE_FALLBACK_REACH", "0"))
FALLBACK_LINE_DEG = 12.0
LASER_PX_PER_TICK = 56.0    # 6 ROM px/frame * 4 frames * ~2.35 planner px per ROM px
_NO_FALLBACK_AIM = frozenset(("Player", "Mikey", "Mommy", "Daddy", "Hulk", "Electrode"))
# FSM_SAVE_GRUNT (N, 0 = off): endgame score-farming. Rescues escalate to 5000 and
# the wave only ends when the last killable dies, so with civilians still out and
# only grunts left, keep the last N grunts alive and collect the family first:
#   protect (killables <= N+3, so only the N farthest grunts are spared): fire at
#     everything else but never at a protected grunt;
#   hold (the only killables left are <= N grunts): fire stick released
#     completely (FSM shot, move-direction fallback, FIRE_ALT, FIREPLAN, reach
#     fallback all off); the FSM keeps rescuing (RESCUE_SEEK) and the planner dodging.
# Off (normal killing resumes) while: no civilian is visible, a Brain or Prog is
# on screen (they convert humans), any grunt is within SAVE_EXIT_R (60 to
# re-enter) of the player, a hulk is within SAVE_HULK_R of the nearest civilian,
# or save mode has used SAVE_MAX_S of wall time this wave (then locked out until
# the next reset(), so the wave always ends).
SAVE_GRUNT = int(os.environ.get("FSM_SAVE_GRUNT", "0"))
SAVE_EXTRA_KILLABLES = 3
SAVE_EXIT_R, SAVE_REENTER_R, SAVE_HULK_R, SAVE_MAX_S = 45.0, 60.0, 80.0, 12.0
_FAMILY = frozenset(("Mikey", "Mommy", "Daddy"))
_SAVE_OTHER_KILLABLE = frozenset(("Sphereoid", "Quark", "Enforcer", "Tank"))

_ENGINE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine")

# Default latency compensation (decision ticks) per input path. The memory path
# reads fresh via the 6809 list-walk (~0.25 ticks stale after frame-sync). The
# vision figure was hand-set to 1.0 until 2026-07-28; the onboard latency
# calibrator measures the pipeline at 0.21-0.30 ticks live, and the hand-set
# value over-extrapolated every threat by ~0.7 ticks (~9 px on a spark) — the
# wrong-info-worse-than-none failure mode. Corrected to the measurement.
DEFAULT_LAG_MEMORY = 0.25
DEFAULT_LAG_VISION = 0.7   # 2026-09-06: was 0.3; A/B 0.2/0.7/1.2 on Xenia -> 0.7 NET +0.155 vs +0.012, maxW 38.1 vs 25.4 (p=0.001). The oracle diagnostic showed the planner acted on entities ~1/3 tick BEHIND truth; 0.7 puts it slightly ahead, where exact-state play lives.
# Player forward-prediction: the sent move takes ~2 ticks (measured from
# vision response) to actuate; lead the player position along the last
# command so we dodge from where the player WILL be.
#   memory: 1.8 frames / 4 frames-per-tick = 0.45 ticks (the W158 config).
#   vision: the calibrator's act=2.0 already INCLUDES the vision pipeline
#           age, so the correct lead is act − 0.5 (whole-tick quantization
#           midpoint) = 1.5. Validated live 2026-07-29: max wave 14.6 → 18.0
#           (p=0.003) vs the old shared 0.45 — the single biggest gameplay
#           win of the vision campaign.
DEFAULT_LEAD_MEMORY = 0.45
DEFAULT_LEAD_VISION = 1.5
DEFAULT_PLAYER_LEAD = DEFAULT_LEAD_MEMORY   # back-compat alias

# The FSM's obs-limited slot selection (same category budgets as MAME play): the
# planner only sees the nearest N of each threat family, mirroring the arcade
# hardware's per-frame object limit the champion was evolved against.
SLOT_CATEGORIES = [
    (6, {'EnforcerBullet', 'TankShell', 'CruiseMissile', 'Prog'}),
    (6, {'Enforcer', 'Tank'}),
    (6, {'Sphereoid', 'Quark'}),
    (10, {'Grunt', 'Brain'}),
    (5, {'Hulk'}),
    (4, {'Electrode'}),
    (4, {'Mikey', 'Mommy', 'Daddy'}),
]
CATCHALL_SLOTS = 4


class VelocityTracker:
    """Per-entity pixel-space velocity across decision ticks, with EMA smoothing.

    Identity = nearest same-name entity within a sane per-tick radius. The raw
    2-frame difference is noisy (async read jitter doubles under differencing)
    and that noise is multiplied by the lag into the extrapolation the planner
    dodges on, so an EMA de-noises the fast projectiles (spark/missile/shell =
    most real deaths) at almost no lag cost.
    """
    VMAX = 130.0

    def __init__(self, alpha: float = 0.5):
        self.alpha = alpha
        self.prev = []   # [(name, px, py, svx, svy)] — smoothed velocity carried

    def reset(self):
        self.prev = []

    def velocities(self, cur):
        """cur = [(px, py, name)]. Returns [(svx, svy)] aligned with cur."""
        out, new_prev = [], []
        a = self.alpha
        for (px, py, name) in cur:
            best, bd = None, 1e18
            for pe in self.prev:
                if pe[0] != name:
                    continue
                d = (px - pe[1]) ** 2 + (py - pe[2]) ** 2
                if d < bd:
                    bd, best = d, pe
            if best is not None and bd <= self.VMAX ** 2:
                rvx, rvy = px - best[1], py - best[2]
                svx = a * rvx + (1 - a) * best[3]
                svy = a * rvy + (1 - a) * best[4]
            else:
                svx = svy = 0.0
            out.append((svx, svy))
            new_prev.append((name, px, py, svx, svy))
        self.prev = new_prev
        return out


COASTER_TTL = 3.0   # decision ticks a missed projectile track is coasted (loop rescales it)


class ProjectileCoaster:
    """Track-and-coast layer for fast projectiles on the VISION path (ported
    from robotron/brain_yolo.py, 2026-07-08 — the change that took the vision
    bot from a W10.7 mean to W13.6+ / record W23).

    The detector misses fast projectiles frame-to-frame, and VelocityTracker
    needs two CONSECUTIVE sightings for a velocity — so most sparks were
    extrapolated as stationary and dodges targeted the wrong spot. Robotron
    projectiles fly straight at constant speed, so a track that goes
    undetected can be coasted along its velocity for a few ticks with near-
    zero error, and re-detection after k blind ticks recovers velocity as
    displacement/(k+1).

    TTL=3 per the 2026-07-08 A/B (drifted ghosts' position error grows faster
    than the coverage benefit: p90 error 29px @TTL5 -> 19.7px @TTL3).
    turn>0 curves blind CruiseMissile ghosts toward the player (they home);
    the proven live config runs with turn=0.
    """
    NAMES = frozenset(('EnforcerBullet', 'TankShell', 'CruiseMissile', 'Prog'))
    HOMING = {'CruiseMissile'}
    GATE = 130.0   # px association gate (admits the fastest sparks), x2 when blind
    VMAX = 130.0   # px/tick velocity clamp (mirrors VelocityTracker.VMAX)
    ALPHA = 0.5    # velocity EMA

    def __init__(self, ttl: float = COASTER_TTL, turn: float = 0.0):
        self.ttl = ttl
        self.turn = turn
        self.tracks = []   # dicts: x,y coasted pos; lx,ly last-seen; vx,vy; name; miss

    def reset(self):
        self.tracks = []

    @staticmethod
    def _steer(vx, vy, tx, ty, max_turn):
        import math
        speed = math.hypot(vx, vy)
        if speed < 1e-6 or (tx == 0.0 and ty == 0.0):
            return vx, vy
        cur = math.atan2(vy, vx)
        want = math.atan2(ty, tx)
        diff = (want - cur + math.pi) % (2 * math.pi) - math.pi
        ang = cur + max(-max_turn, min(max_turn, diff))
        return speed * math.cos(ang), speed * math.sin(ang)

    def update(self, dets, player=None, dt=1.0):
        """dets: [(x, y, name)] seen THIS sample (planner space). dt in decision
        ticks. Returns [(x, y, name, vx, vy)] for every live track — fresh
        detections plus unseen tracks coasted along their velocity."""
        for t in self.tracks:
            t['x'] += t['vx'] * dt
            t['y'] += t['vy'] * dt
            t['hit'] = False
        for (x, y, name) in dets:
            best, bd = None, 1e18
            for t in self.tracks:
                if t['name'] != name or t['hit']:
                    continue
                gate = self.GATE * max(dt, 0.3) * min(1 + t['miss'], 2)
                d = (x - t['x']) ** 2 + (y - t['y']) ** 2
                if d <= gate ** 2 and d < bd:
                    bd, best = d, t
            if best is None:
                self.tracks.append(dict(x=x, y=y, lx=x, ly=y, vx=0.0, vy=0.0,
                                        name=name, miss=0.0, hit=True))
                continue
            n = best['miss'] + dt
            rvx, rvy = (x - best['lx']) / n, (y - best['ly']) / n
            if rvx * rvx + rvy * rvy <= self.VMAX ** 2:
                a = min(1.0, self.ALPHA * dt) if dt < 1.0 else self.ALPHA
                best['vx'] = a * rvx + (1 - a) * best['vx']
                best['vy'] = a * rvy + (1 - a) * best['vy']
            best['x'], best['y'] = best['lx'], best['ly'] = x, y
            best['miss'] = 0.0
            best['hit'] = True
        out, keep = [], []
        for t in self.tracks:
            if not t['hit']:
                t['miss'] += dt
                if t['miss'] > self.ttl:
                    continue
                if not (-30.0 <= t['x'] <= coords.PIX_W + 30.0
                        and -30.0 <= t['y'] <= coords.PIX_H + 30.0):
                    continue                          # left the arena for real
                if player is not None and self.turn > 0 and t['name'] in self.HOMING:
                    t['vx'], t['vy'] = self._steer(
                        t['vx'], t['vy'],
                        player[0] - t['x'], player[1] - t['y'], self.turn * dt)
            keep.append(t)
            out.append((t['x'], t['y'], t['name'], t['vx'], t['vy']))
        self.tracks = keep
        return out


class ChampionBrain:
    """Wraps the evolved FSM + clearance planner. One instance per process
    (the FSM keeps tuning constants as module globals)."""

    def __init__(self, lag_ticks: float, player_lead_ticks: float = DEFAULT_PLAYER_LEAD,
                 vel_ema_alpha: float = 0.5, use_coaster: bool = False,
                 debug: bool = False, fire_alt=None):
        self.lag_ticks = lag_ticks
        self.player_lead_ticks = player_lead_ticks
        self.vt = VelocityTracker(alpha=vel_ema_alpha)
        # Vision path only: projectile track-and-coast (memory input is exact
        # every tick, so coasting there would only add ghosts) + widened
        # planner margins (env-pinned values always win).
        self.coaster = ProjectileCoaster() if use_coaster else None
        if use_coaster and not _USER_PINNED_MARGINS:
            set_margins(*VISION_MARGINS)
        # Vision path fires at the clearance-binding threat (kill the launcher
        # — see set_fireplan's docstring for the measured win). Env-pinned
        # VSEARCH_FIREPLAN always wins, for A/B.
        if use_coaster and not _USER_PINNED_FIREPLAN:
            set_fireplan(True)
        # Fire-direction alternation (docs/FIRE_ALT_EXPERIMENT.md). Default ON
        # for the vision path since 2026-09-15: proxy 576/arm NET +0.311;
        # Xenia exact state W25-40 deaths/wave 1.22 -> 0.76; real vision
        # 12/arm W5-25 1.06 -> 0.81 and W25-40 1.33 -> 1.10; first uncapped
        # vision games W117 and W90 (previous record W60). Radius 400 px is
        # the proxy plateau (100 +0.20, 160 +0.31, 250 +0.34, 400 +0.38,
        # unlimited +0.37). Explicit argument wins, then an env-pinned
        # VSEARCH_FIRE_ALT (A/B purity), else on for vision / off for memory.
        if not _USER_PINNED_FIRE_ALT:
            on = use_coaster if fire_alt is None else bool(fire_alt)
            set_fire_alt(on, VISION_FIRE_ALT_R if on else None)
        # FSM_FIRE_SKIP_RECEDING / FSM_FIRE_FALLBACK_REACH: on for vision unless
        # pinned (each independently); the pinned/memory value is the import-time
        # env read. The FSM and planner keep their own copies of SKIP_RECEDING.
        global FIRE_FALLBACK_REACH
        if not _USER_PINNED_SKIP_RECEDING:
            fsm.SKIP_RECEDING = bool(use_coaster and VISION_SKIP_RECEDING)
            cp.set_fire_gates(skip_receding=fsm.SKIP_RECEDING)
        if not _USER_PINNED_FALLBACK_REACH:
            FIRE_FALLBACK_REACH = VISION_FIRE_FALLBACK_REACH if use_coaster else 0.0
        self.last_mv = 0
        self.clock = time.monotonic       # save-grunt timer (tests inject a fake)
        self._save_reset()
        self._setup_fsm(debug)

    def _setup_fsm(self, debug: bool):
        W, H = int(coords.PIX_W), int(coords.PIX_H)
        fsm.DEBUG_LEVEL = 0
        fsm.MAX_RIGHT, fsm.MAX_TOP = W, H
        fsm.MAX_BOTTOM, fsm.MAX_LEFT = 0, 0
        fsm.Y_AXIS_INVERSION = H
        # Prefer the hunt variant (gen-6 constants + endgame killable-hunt); it
        # lifted wave-100+ completion from 4% to ~80% on the MAME books replica.
        # Delete the _hunt json to fall back to the plain gen-6 champion.
        p = os.path.join(_ENGINE_DIR, "fsm_evolved_planner_v2_hunt.json")
        if not os.path.exists(p):
            p = os.path.join(_ENGINE_DIR, "fsm_evolved_planner_v2_final.json")
        with open(p) as f:
            for name, val in json.load(f)["best_params"].items():
                setattr(fsm, name, val)
        B = float(getattr(fsm, "BORDER_ADJUST", 20))
        fsm.ADJ_TOP, fsm.ADJ_BOTTOM = H - 2, 0 + B + 9
        fsm.ADJ_LEFT, fsm.ADJ_RIGHT = 0 + 2, W - B
        if debug:
            print(f"[brain] evolved params loaded from {os.path.basename(p)}")

    def reset(self):
        """Clear cross-tick state (call on death / wave change)."""
        self.vt.reset()
        if self.coaster is not None:
            self.coaster.reset()
        self.last_mv = 0
        self._save_reset()

    def _save_reset(self):
        self.save_active = False     # save mode engaged on the last tick
        self.save_used = 0.0         # seconds of save mode spent this wave
        self.save_locked = False
        self._save_t = 0.0

    def _player_vel(self):
        """Player velocity, px per NOMINAL tick, from the last command."""
        vx, vy = DXY.get(self.last_mv, (0.0, 0.0))
        return vx / cp.TICK_SCALE, vy / cp.TICK_SCALE

    def _save_grunt(self, px, py, others):
        """FSM_SAVE_GRUNT state machine. Returns (0 off | 1 protect | 2 hold,
        keys of the protected grunts). See the knob comment."""
        n = SAVE_GRUNT
        grunts = [s for s in others if s[2] == "Grunt"]
        civs = [s for s in others if s[2] in _FAMILY]
        other_k = [s for s in others if s[2] in _SAVE_OTHER_KILLABLE]
        mode, prot = 0, ()
        if (n > 0 and not self.save_locked and civs and grunts
                and len(grunts) + len(other_k) <= n + SAVE_EXTRA_KILLABLES
                and not any(s[2] in ("Brain", "Prog") for s in others)):
            near = min(math.hypot(s[0] - px, s[1] - py) for s in grunts)
            civ = min(civs, key=lambda s: (s[0] - px) ** 2 + (s[1] - py) ** 2)
            hulk_near = any(s[2] == "Hulk" and math.hypot(s[0] - civ[0], s[1] - civ[1]) <= SAVE_HULK_R
                            for s in others)
            if near > (SAVE_EXIT_R if self.save_active else SAVE_REENTER_R) and not hulk_near:
                keep = sorted(grunts, key=lambda s: -((s[0] - px) ** 2 + (s[1] - py) ** 2))[:n]
                prot = tuple((s[0], s[1], s[2]) for s in keep)
                mode = 2 if (not other_k and len(grunts) <= n) else 1
        now = self.clock()
        if mode:
            if self.save_active:
                self.save_used += min(max(now - self._save_t, 0.0), 0.5)
            if self.save_used > SAVE_MAX_S:
                self.save_locked, mode, prot = True, 0, ()
        self.save_active, self._save_t = bool(mode), now
        return mode, prot

    def _fire_context(self, sel, px, py):
        """FSM_HULK_CLOSING / FSM_FIRE_SKIP_RECEDING: the per-tick sets the FSM
        (which sees no velocities) needs, keyed by its (x, y, name) input tuples."""
        pvx, pvy = self._player_vel()
        closing, skip = set(), set()
        for s in sel:
            if fsm.HULK_CLOSING and s[2] == "Hulk" \
                    and cp.hulk_closing(px, py, pvx, pvy, s[0], s[1], s[3], s[4]):
                closing.add((s[0], s[1], s[2]))
            elif fsm.SKIP_RECEDING and cp.projectile_receding(
                    s[2], px, py, pvx, pvy, s[0], s[1], s[3], s[4]):
                skip.add((s[0], s[1], s[2]))
        return {'closing': closing, 'skip': skip}

    def _lined_up_fire(self, px, py, others, protected=()):
        """FIRE_FALLBACK_REACH: direction of the nearest killable within reach
        that is lined up with one of the 8 fire directions, else 0."""
        pvx, pvy = self._player_vel()
        best = None
        for s in others:
            if s[2] in _NO_FALLBACK_AIM or (s[0], s[1], s[2]) in protected:
                continue
            d = math.hypot(s[0] - px, s[1] - py)
            if d > FIRE_FALLBACK_REACH or d < 1.0:
                continue
            if fsm.SKIP_RECEDING and cp.projectile_receding(
                    s[2], px, py, pvx, pvy, s[0], s[1], s[3], s[4]):
                continue
            lx, ly = s[0] + s[3] * d / LASER_PX_PER_TICK, s[1] + s[4] * d / LASER_PX_PER_TICK
            ang = math.degrees(math.atan2(ly - py, lx - px))
            if abs((ang + 22.5) % 45.0 - 22.5) <= FALLBACK_LINE_DEG and (best is None or d < best[0]):
                best = (d, _dir_toward(px, py, lx, ly))
        return best[1] if best else 0

    def _champion_action(self, sprites):
        """sprites = [(px, py, name, vx, vy), ...] incl. ('Player'). -> (mv, fr) 1..8."""
        player = next((s for s in sprites if s[2] == "Player"), None)
        if player is None:
            return 1, 1
        px, py = player[0], player[1]
        others = [s for s in sprites if s[2] != "Player"]
        d2 = lambda s: (s[0] - px) ** 2 + (s[1] - py) ** 2  # noqa: E731
        used, sel = set(), []
        for cnt, types in SLOT_CATEGORIES:
            for s in sorted([s for s in others if s[2] in types and id(s) not in used],
                            key=d2)[:cnt]:
                used.add(id(s)); sel.append(s)
        sel += sorted([s for s in others if id(s) not in used], key=d2)[:CATCHALL_SLOTS]
        save, protected = 0, ()
        if SAVE_GRUNT > 0:
            save, protected = self._save_grunt(px, py, others)
            set_fire_exclude(protected)
            if save == 1:       # the FSM must not see the grunts it is meant to spare
                sel = [s for s in sel if (s[0], s[1], s[2]) not in protected]
        fsm.CTX = self._fire_context(sel, px, py) if (fsm.HULK_CLOSING or fsm.SKIP_RECEDING) else None
        data = [(px, py, "Player")] + [(s[0], s[1], s[2]) for s in sel]
        try:
            mv, fr = fsm.chooseOutputs(data)
        except Exception:
            mv, fr = 1, 1
        mv = mv if mv >= 1 else 1
        if save == 2:
            fr = 0              # hold fire completely
        else:
            if fr < 1 and FIRE_FALLBACK_REACH > 0:
                fr = self._lined_up_fire(px, py, others, protected)
            fr = fr if fr >= 1 else mv
        mv, fr = clearance_search(sprites, mv, fr)
        return (mv, 0) if save == 2 else (mv, fr)

    def blind_tick(self, entities):
        """Feed a tick where the PLAYER box was missed but enemies were seen.
        Without this, tracking freezes on player-blind ticks and resumes a
        tick stale with halved velocities (2026-07-28 fix): the coaster must
        keep associating and ageing, and the velocity tracker must keep its
        identity chain, even when no decision is made."""
        cur = list(entities)
        if self.coaster is not None:
            proj = [e for e in cur if e[2] in ProjectileCoaster.NAMES]
            cur = [e for e in cur if e[2] not in ProjectileCoaster.NAMES]
            self.coaster.update(proj, None)
        self.vt.velocities(cur)

    def decide(self, player_xy, entities):
        """player_xy = (px, py) planner; entities = [(px, py, name)] planner.
        Returns (move, fire) directions 1..8."""
        cur = list(entities)
        # Projectile classes go through the track-and-coast layer (it owns
        # their identity AND velocity); everything else keeps the
        # consecutive-frame VelocityTracker.
        if self.coaster is not None:
            proj = [e for e in cur if e[2] in ProjectileCoaster.NAMES]
            cur = [e for e in cur if e[2] not in ProjectileCoaster.NAMES]
            tracked = self.coaster.update(proj, player_xy)
        else:
            tracked = []
        vels = self.vt.velocities(cur)

        # Player forward-prediction: lead along the last commanded direction.
        plx, ply = player_xy
        if self.player_lead_ticks > 0 and self.last_mv in DXY:
            ldx, ldy = DXY[self.last_mv]
            plx = min(max(plx + ldx * self.player_lead_ticks, 0.0), coords.PIX_W)
            ply = min(max(ply + ldy * self.player_lead_ticks, 0.0), coords.PIX_H)

        # Latency extrapolation: advance each entity along its tracked velocity so
        # the planner dodges where threats WILL be, not where they were.
        lag = self.lag_ticks
        clamp = lambda x, y, n, vx, vy: (  # noqa: E731
            min(max(x + vx * lag, 0.0), coords.PIX_W),
            min(max(y + vy * lag, 0.0), coords.PIX_H), n, vx, vy)
        sprites = [(plx, ply, "Player", 0.0, 0.0)] \
            + [clamp(x, y, n, vx, vy) for (x, y, n), (vx, vy) in zip(cur, vels)] \
            + [clamp(x, y, n, vx, vy) for (x, y, n, vx, vy) in tracked]
        mv, fr = self._champion_action(sprites)
        self.last_mv = mv
        return mv, fr
