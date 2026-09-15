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
        self.unique_matches = os.environ.get('ROBOTRON_VELOCITY_UNIQUE', '0') == '1'
        self.static_electrodes = os.environ.get('ROBOTRON_STATIC_ELECTRODES', '0') == '1'
        self.prev = []   # [(name, px, py, svx, svy)] — smoothed velocity carried

    def reset(self):
        self.prev = []

    def velocities(self, cur, dt=1.0):
        """cur = [(px, py, name)]. Returns [(svx, svy)] aligned with cur."""
        out, new_prev = [], []
        a = self.alpha
        # Opt-in identity constraint for non-coasted entities. The legacy
        # nearest-neighbour loop can assign one old entity to several new
        # detections, copying its velocity history into multiple tracks.
        # Assign shortest same-class pairs first; unmatched detections start
        # at zero velocity, just as legacy unmatched detections do.
        matches = {}
        if self.unique_matches:
            pairs = sorted(((px-pe[1])**2 + (py-pe[2])**2, i, j)
                           for i, (px, py, name) in enumerate(cur)
                           for j, pe in enumerate(self.prev)
                           if pe[0] == name and (px-pe[1])**2 + (py-pe[2])**2 <= (self.VMAX*dt)**2)
            used = set()
            for _, i, j in pairs:
                if i not in matches and j not in used:
                    matches[i] = self.prev[j]
                    used.add(j)
        for i, (px, py, name) in enumerate(cur):
            best, bd = None, 1e18
            for pe in (() if self.unique_matches else self.prev):
                if pe[0] != name:
                    continue
                d = (px - pe[1]) ** 2 + (py - pe[2]) ** 2
                if d < bd:
                    bd, best = d, pe
            if self.unique_matches and i in matches:
                best, bd = matches[i], 0.0
            if best is not None and bd <= (self.VMAX * dt) ** 2:
                rvx, rvy = (px - best[1]) / dt, (py - best[2]) / dt
                svx = a * rvx + (1 - a) * best[3]
                svy = a * rvy + (1 - a) * best[4]
            else:
                svx = svy = 0.0
            # Electrodes are stationary obstacles. Detection jitter and nearby
            # identity swaps otherwise become fictitious obstacle motion in
            # both latency extrapolation and the clearance horizon.
            if self.static_electrodes and name == 'Electrode':
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
        self.closest_pairs = os.environ.get('ROBOTRON_COAST_CLOSEST_PAIRS', '0') == '1'
        self.spark_birth = os.environ.get('ROBOTRON_SPARK_BIRTH_VELOCITY', '0') == '1'
        self.confirmed_ghosts = os.environ.get('ROBOTRON_COAST_CONFIRMED_ONLY', '0') == '1'
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

    @staticmethod
    def _birth_velocity(x, y, name, launchers):
        # Only a detected spark with one nearby visible Enforcer is eligible.
        # This estimates its initial motion; it never creates a projectile.
        if name != 'EnforcerBullet':
            return 0.0, 0.0
        nearby = [(lx, ly) for lx, ly, n in launchers if n == 'Enforcer'
                  and (lx-x)**2 + (ly-y)**2 <= 60.0**2]
        if len(nearby) != 1:
            return 0.0, 0.0
        lx, ly = nearby[0]
        distance = ((x-lx)**2 + (y-ly)**2)**.5
        if distance < 8.0:
            return 0.0, 0.0
        return 12.0*(x-lx)/distance, 12.0*(y-ly)/distance

    def update(self, dets, player=None, dt=1.0, launchers=()):
        """dets: [(x, y, name)] seen THIS sample (planner space). dt in decision
        ticks. Returns [(x, y, name, vx, vy)] for every live track — fresh
        detections plus unseen tracks coasted along their velocity."""
        for t in self.tracks:
            t['x'] += t['vx'] * dt
            t['y'] += t['vy'] * dt
            t['hit'] = False
        # Opt-in: reserve the closest prediction/detection pairs before weaker
        # matches can consume them in detector output order. The same gates,
        # velocity update, TTL and one-to-one identity constraint still apply.
        matches = {}
        if self.closest_pairs:
            pairs = []
            for i, (x, y, name) in enumerate(dets):
                for j, t in enumerate(self.tracks):
                    if t['name'] != name:
                        continue
                    gate = self.GATE * max(dt, 0.3) * min(1 + t['miss'], 2)
                    d = (x - t['x']) ** 2 + (y - t['y']) ** 2
                    if d <= gate ** 2:
                        pairs.append((d, x, y, t['x'], t['y'], i, j))
            used = set()
            for *_, i, j in sorted(pairs):
                if i not in matches and j not in used:
                    matches[i] = self.tracks[j]
                    used.add(j)
        for i, (x, y, name) in enumerate(dets):
            best, bd = None, 1e18
            for t in (() if self.closest_pairs else self.tracks):
                if t['name'] != name or t['hit']:
                    continue
                gate = self.GATE * max(dt, 0.3) * min(1 + t['miss'], 2)
                d = (x - t['x']) ** 2 + (y - t['y']) ** 2
                if d <= gate ** 2 and d < bd:
                    bd, best = d, t
            if self.closest_pairs:
                best = matches.get(i)
            if best is None:
                vx, vy = self._birth_velocity(x, y, name, launchers) if self.spark_birth else (0.0, 0.0)
                self.tracks.append(dict(x=x, y=y, lx=x, ly=y, vx=vx, vy=vy,
                                        name=name, miss=0.0, hit=True, confirmed=False))
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
            best['confirmed'] = True
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
            # A single sighting has no measured velocity. Opt-in: retain its
            # association history/expiry, but do not present it as a stationary
            # unseen threat until a second detection confirms the track.
            # Fresh detections and every confirmed ghost remain visible.
            if self.confirmed_ghosts and not t['hit'] and not t['confirmed']:
                continue
            out.append((t['x'], t['y'], t['name'], t['vx'], t['vy']))
        self.tracks = keep
        return out


class ChampionBrain:
    """Wraps the evolved FSM + clearance planner. One instance per process
    (the FSM keeps tuning constants as module globals)."""

    def __init__(self, lag_ticks: float, player_lead_ticks: float = DEFAULT_PLAYER_LEAD,
                 vel_ema_alpha: float = 0.5, use_coaster: bool = False,
                 debug: bool = False, normalize_tracking_time=None):
        self.lag_ticks = lag_ticks
        self.player_lead_ticks = player_lead_ticks
        self.vt = VelocityTracker(alpha=vel_ema_alpha)
        self.normalize_tracking_time = (os.environ.get('ROBOTRON_TRACK_TIME', '0') == '1'
                                        if normalize_tracking_time is None else normalize_tracking_time)
        self._sample_time = None
        self._tracked_sample = None
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
        self.player_history_lead = os.environ.get('ROBOTRON_PLAYER_HISTORY_LEAD', '0') == '1'
        self._sent_moves = []
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
        self._sent_moves = []
        self._sample_time = None
        self._tracked_sample = None
        self.vt.reset()
        if self.coaster is not None:
            self.coaster.reset()
        self.last_mv = 0

    def record_command(self, move, controlled=True):
        """Remember actual vision-loop commands, including held/neutral ticks.

        Used only by the opt-in turn lead; no observation or oracle input.
        """
        if self.player_history_lead:
            self._sent_moves = (self._sent_moves + [(move, controlled)])[-2:]

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

    def _track(self, entities, player, sampled_at):
        dt = 1.0
        if self.normalize_tracking_time:
            if sampled_at is None:
                import time
                sampled_at = time.perf_counter()
            if self._sample_time is not None:
                elapsed = sampled_at - self._sample_time
                if elapsed <= 0 and self._tracked_sample is not None:
                    return self._tracked_sample
                if elapsed > .5:
                    self.vt.reset()
                    if self.coaster is not None:
                        self.coaster.reset()
                else:
                    dt = max(.05, elapsed * 15.0)
            self._sample_time = sampled_at
        cur = list(entities)
        tracked = []
        if self.coaster is not None:
            proj = [e for e in cur if e[2] in ProjectileCoaster.NAMES]
            cur = [e for e in cur if e[2] not in ProjectileCoaster.NAMES]
            tracked = self.coaster.update(proj, player, dt=dt, launchers=cur)
        result = cur, self.vt.velocities(cur, dt=dt), tracked
        self._tracked_sample = result
        return result

    def blind_tick(self, entities, sampled_at=None):
        """Feed a tick where the PLAYER box was missed but enemies were seen.
        Without this, tracking freezes on player-blind ticks and resumes a
        tick stale with halved velocities (2026-07-28 fix): the coaster must
        keep associating and ageing, and the velocity tracker must keep its
        identity chain, even when no decision is made."""
        self._track(entities, None, sampled_at)

    def decide(self, player_xy, entities, sampled_at=None):
        """player_xy = (px, py) planner; entities = [(px, py, name)] planner.
        Returns (move, fire) directions 1..8."""
        # Projectile classes go through the track-and-coast layer (it owns
        # their identity AND velocity); everything else keeps the
        # consecutive-frame VelocityTracker.
        cur, vels, tracked = self._track(entities, player_xy, sampled_at)

        # Player forward-prediction: lead along the last commanded direction.
        plx, ply = player_xy
        if self.player_lead_ticks > 0 and self.last_mv in DXY:
            ldx, ldy = DXY[self.last_mv]
            dx, dy = ldx * self.player_lead_ticks, ldy * self.player_lead_ticks
            if (self.player_history_lead and len(self._sent_moves) == 2
                    and all(controlled and move in DXY for move, controlled in self._sent_moves)
                    and self._sent_moves[-1][0] == self.last_mv):
                # At a turn, some in-flight movement still belongs to the
                # preceding command. Keep total lead fixed; replace half a
                # tick with that command. Blind/reacquisition behavior remains
                # legacy until two consecutive controlled sends are available.
                older = DXY[self._sent_moves[0][0]]
                weight = min(.5, self.player_lead_ticks)
                dx += weight * (older[0] - ldx)
                dy += weight * (older[1] - ldy)
            plx = min(max(plx + dx, 0.0), coords.PIX_W)
            ply = min(max(ply + dy, 0.0), coords.PIX_H)

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
