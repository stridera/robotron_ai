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
import os

# Whether the USER pinned the planner margins / fireplan (before our
# setdefaults make the vars exist unconditionally) — a pinned value always
# wins over the per-path defaults applied in ChampionBrain.__init__.
_USER_PINNED_MARGINS = ("VSEARCH_CLEAR_DANGER" in os.environ
                        or "VSEARCH_CLEAR_MARGIN" in os.environ)
_USER_PINNED_FIREPLAN = "VSEARCH_FIREPLAN" in os.environ

# The planner reads these at import time, so seed the champion defaults BEFORE
# importing the engine modules. setdefault => real env vars still win (for A/B).
os.environ.setdefault("VSEARCH_ASMDYN", "1")
os.environ.setdefault("VSEARCH_H", "6")
os.environ.setdefault("VSEARCH_CLEAR_DANGER", "18")
os.environ.setdefault("VSEARCH_CLEAR_MARGIN", "10")
os.environ.setdefault("FSM_RESCUE_SEEK", "1")

from .engine import robotron_fsm as fsm                       # noqa: E402
from .engine.clearance_planner import (clearance_search, DXY,  # noqa: E402
                                       set_margins, set_fireplan)
# Vision-path planner margins (2026-07-08 dose-response A/B): ~1.15x the
# memory-optimal 18/10 absorbs vision tracking noise (mean 14.4 vs 13.6,
# worst-game floor W10 vs W7); 1.3x regressed. Memory path keeps 18/10.
VISION_MARGINS = (21.0, 12.0)
from . import coords                                          # noqa: E402

_ENGINE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine")

# Default latency compensation (decision ticks) per input path. The memory path
# reads fresh via the 6809 list-walk (~0.25 ticks stale after frame-sync). The
# vision figure was hand-set to 1.0 until 2026-07-28; the onboard latency
# calibrator measures the pipeline at 0.21-0.30 ticks live, and the hand-set
# value over-extrapolated every threat by ~0.7 ticks (~9 px on a spark) — the
# wrong-info-worse-than-none failure mode. Corrected to the measurement.
DEFAULT_LAG_MEMORY = 0.25
DEFAULT_LAG_VISION = 0.3
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

    def __init__(self, ttl: float = 3.0, turn: float = 0.0):
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
                 debug: bool = False):
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
        self.last_mv = 0
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
        data = [(px, py, "Player")] + [(s[0], s[1], s[2]) for s in sel]
        try:
            mv, fr = fsm.chooseOutputs(data)
        except Exception:
            mv, fr = 1, 1
        mv = mv if mv >= 1 else 1
        fr = fr if fr >= 1 else mv
        return clearance_search(sprites, mv, fr)

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
