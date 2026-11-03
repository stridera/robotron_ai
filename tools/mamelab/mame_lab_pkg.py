"""mame_lab_pkg.py - MAME proxy lab that drives the robotron_ai PACKAGE brain.

Same MAME gym, same vision-defect model and the same LAB_* knobs as
~/Code/robotron/mame_lab.py (ACT_FRAMES, K, LEAD, LAG, DROP, PDROP, NOISE),
but the decision is made by robotron_ai.brain.ChampionBrain.decide() with
use_coaster=True - i.e. the console's code: VelocityTracker, ProjectileCoaster,
engine/robotron_fsm.py, engine/clearance_planner.py, brain.py's vision-path
pinning (margins 21/12, FIREPLAN on, FIRE_ALT on R=400 unless env-pinned).

The package to test is whatever `robotron_ai` resolves to on PYTHONPATH
(run_ab.py --checkout PATH sets that up through a symlink).
Output format is identical to mame_lab.py so analyze_collision_mame.py works.
"""
import argparse
import json
import os
import random
import sys
import time
from collections import deque

os.environ.setdefault("MAME_RL_RESEED", "1")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import labpaths                                                       # noqa: E402
# External dependencies (see docs/MAME_LAB.md): the MAME gym in robotron-rl, and
# mame_score.py from the dev tree (~/Code/robotron, no git remote; NOT vendored).
for p in (labpaths.RL / "mame_gym", labpaths.RL, labpaths.DEV):
    sys.path.insert(0, str(p))

import numpy as np                                                   # noqa: E402
import robotron_ai.brain as brain_mod                                # noqa: E402
from robotron_ai.engine import robotron_fsm as fsm                   # noqa: E402
from mame_obs import (_gxgy_to_pixel, _LIST1_SW, _LIST2_SW, _LIST3_SW,  # noqa: E402
                      iter_entities, parse_header)
from mame_robotron_env import MameRobotronEnv                        # noqa: E402
from mame_score import ScoreMeasurement                              # noqa: E402

W, H = 665.0, 492.0
FRAMESKIP = int(os.environ.get("LAB_FRAMESKIP", "4"))
K = int(os.environ.get("LAB_K", "0"))
COMP = os.environ.get("LAB_COMP", "1") == "1"
ACT_FRAMES = int(os.environ.get("LAB_ACT_FRAMES", "0"))
DROP = float(os.environ.get("LAB_DROP", "0"))
PDROP = float(os.environ.get("LAB_PDROP", "0"))
NOISE = float(os.environ.get("LAB_NOISE", "0"))
LEAD = float(os.environ.get("LAB_LEAD", str(ACT_FRAMES / 4.0)))
LAG = float(os.environ.get("LAB_LAG", "0"))
VEL_ALPHA = float(os.environ.get("ROBOTRON_VEL_EMA_ALPHA", "0.5"))
TICK_SCALE = FRAMESKIP / 4.0
ACT_STEPS = int(round(ACT_FRAMES / FRAMESKIP))
NEUTRAL = -1
assert FRAMESKIP == 4, "package brain is tuned in 15 Hz ticks; keep LAB_FRAMESKIP=4"


def packet_entities(packet):
    out = []
    for addr, list_id, sw, x, y in iter_entities(packet):
        if list_id == 4:
            name = "Electrode"
        elif list_id == 2:
            name = _LIST2_SW.get(sw)
        elif list_id == 1:
            name = _LIST1_SW.get(sw, "TankShell")
        else:
            name = _LIST3_SW.get(sw)
        if name:
            out.append((addr, name, x, y))
    return out


def detections(ents, rng):
    """Memory read -> YOLO-like detections [(x, y, name)] in planner pixels:
    gaussian position noise and per-entity miss rate (no velocities, no ids:
    the brain's own VelocityTracker / ProjectileCoaster supply those)."""
    out = []
    for _addr, name, gx, gy in ents:
        x, y = _gxgy_to_pixel(gx, gy)
        if NOISE > 0:
            x += rng.gauss(0, NOISE)
            y += rng.gauss(0, NOISE)
        if DROP > 0 and rng.random() < DROP:
            continue
        out.append((x, y, name))
    return out


def play_game(env, brain, arm, game_id, out_path, stepcap, rng, cap_wave):
    env.reset()
    brain.reset()
    hist = deque(maxlen=K + 1)
    act_q = deque([(1, 1)] * ACT_STEPS)
    held = (1, 1)
    last_mv = 0
    h = parse_header(env._last_packet)
    prev_lives, prev_wave, prev_gs = h["lives"], h["wave"], h["game_state"]
    wave_deaths, wave_score0, wave_rescues = 0, h["score"], 0
    deaths, max_wave, rows, steps = 0, prev_wave, [], 0
    prev_score = h["score"]

    def score_event(event):
        with open(out_path + '.score.log', 'a') as f:
            f.write(json.dumps(dict(game=game_id, **event)) + '\n')
    sm = ScoreMeasurement(prev_score, emit=score_event)
    RESCUE_VALUES = (1000, 2000, 3000, 4000, 5000)

    def log_wave(w, score_now):
        if w > 0:
            rows.append({'t': round(time.time(), 2), 'game': game_id, 'arm': arm, 'wave': w,
                         'deaths': wave_deaths, 'rescues': wave_rescues,
                         'score': score_now - wave_score0, 'src': 'mame_lab_pkg'})

    while steps < stepcap:
        packet = env._last_packet
        h = parse_header(packet)
        hist.append(detections(packet_entities(packet), rng))
        px, py = _gxgy_to_pixel(h["player_x"], h["player_y"])
        if PDROP > 0 and rng.random() < PDROP:
            brain.blind_tick(hist[0])                 # production: keep tracks ageing
            action = (0, 0)
        else:
            age_ticks = ((len(hist) - 1) * TICK_SCALE) if K else 0.0
            brain.lag_ticks = (age_ticks if COMP else 0.0) + LAG
            brain.last_mv = last_mv
            mv, fr = brain.decide((px, py), hist[0])
            last_mv = mv
            action = (mv, fr)
        act_q.append(action)
        mv_now, fr_now = act_q.popleft()
        if mv_now == 0:
            mv_now, fr_now = held
        held = (mv_now, fr_now)
        _, _, term, trunc, info = env.step(np.array([mv_now - 1, fr_now - 1]))
        steps += 1
        lives = info.get("lives", prev_lives)
        wave = info.get("wave", prev_wave)
        score = sm.observe(info.get('score', 0), terminal=bool(term),
                           recovered=bool(info.get('recovered')), wave=wave, step=steps,
                           header=bytes(env._last_packet[:11]).hex())
        if score - prev_score in RESCUE_VALUES:
            wave_rescues += 1
        prev_score = score
        gs = parse_header(env._last_packet)["game_state"]
        if gs == 0x1B and prev_gs != 0x1B:
            deaths += 1
            wave_deaths += 1
            brain.reset()                             # harness resets on death
            hist.clear()
            last_mv = 0
        prev_gs = gs
        prev_lives = lives
        if wave != prev_wave:
            log_wave(prev_wave, score)
            prev_wave = wave
            wave_deaths, wave_score0, wave_rescues = 0, score, 0
            max_wave = max(max_wave, wave)
            brain.reset()                             # harness resets on wave change
            hist.clear()
            last_mv = 0
            if cap_wave and wave > cap_wave:
                break
        if term or trunc:
            break
    log_wave(prev_wave, sm.value)
    with open(out_path, "a") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return max_wave, sm.value, deaths, steps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=3)
    ap.add_argument("--arm", default="base")
    ap.add_argument("--port", type=int, default=9930)
    ap.add_argument("--out", default=None)
    ap.add_argument("--stepcap", type=int, default=15000)
    ap.add_argument("--cap-wave", type=int, default=26)
    args = ap.parse_args()
    # Console wiring (cli.py): lag/lead from config, coaster on for vision.
    brain = brain_mod.ChampionBrain(lag_ticks=LAG, player_lead_ticks=LEAD,
                                    vel_ema_alpha=VEL_ALPHA, use_coaster=True)
    for k, v in os.environ.items():                   # FSM constants, as mame_lab.py
        if k.startswith("FSM_OVERRIDE_"):
            setattr(fsm, k[len("FSM_OVERRIDE_"):], float(v))
    out = args.out or os.path.expanduser(f"~/mame_logs/{args.arm}_{args.port}.jsonl")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    rng = random.Random(int(os.environ.get('LAB_RNG_SEED', args.port * 31 + 7)))
    env = MameRobotronEnv(rank=0, base_port=args.port, frameskip=FRAMESKIP,
                          reset_pool=[0], obs_mode="slot")
    from robotron_ai.engine import clearance_planner as cpl
    print(f"[lab] PKG brain={brain_mod.__file__} arm={args.arm} port={args.port} K={K} comp={COMP} "
          f"act_frames={ACT_FRAMES} drop={DROP} pdrop={PDROP} noise={NOISE} lead={LEAD} lag={LAG} "
          f"| planner danger={cpl.CLEAR_DANGER} margin={cpl.CLEAR_MARGIN} fireplan={cpl.FIREPLAN} "
          f"fire_alt={cpl.FIRE_ALT}@{cpl.FIRE_ALT_R} -> {out}", flush=True)
    waves, t0 = [], time.time()
    for g in range(args.games):
        gid = f"{args.arm}-{args.port}-{g}"
        mw, sc, d, steps = play_game(env, brain, args.arm, gid, out, args.stepcap, rng, args.cap_wave)
        waves.append(mw)
        print(f"[lab] game {g + 1}/{args.games}: maxW {mw:3d}  score {sc:7d}  deaths {d:2d}  "
              f"steps {steps:5d}  ({(time.time() - t0) / (g + 1):.0f}s/game)", flush=True)
    print(f"[lab] {args.arm}: mean maxW {np.mean(waves):.2f}  median {np.median(waves):.0f}  "
          f"games {len(waves)}", flush=True)
    env.close()


if __name__ == "__main__":
    main()
