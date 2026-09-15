"""Compare no-op Gym rewards/totals against the ordinary lab on identical seeds."""
import argparse
import json
import os
from pathlib import Path
import random
import subprocess
import sys

from run_collision_mame_fresh import CAL, DEV, REPO


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--worker', choices=['lab', 'env'])
    args = ap.parse_args()
    root = REPO / 'logs/residual_env_parity_20260909_v2'
    if not args.worker:
        root.mkdir(exist_ok=True)
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(('LAB_', 'VSEARCH_', 'FSM_', 'MAME_', 'ROBOTRON_'))}
        env.update(CAL)
        for mode in ('env', 'lab'):
            subprocess.run([sys.executable, '-u', __file__, '--worker', mode], env=env, check=True)
        a, b = (json.loads((root / f'{mode}.json').read_text()) for mode in ('env', 'lab'))
        assert a['totals'] == b['totals'], (a, b)
        assert abs(a['reward'] - (a['totals'][1] / 1000 - 25 * a['totals'][2])) < 1e-6, a
        print('PASS: no-op Gym episode exactly matches lab; reward telescopes to NET*25', flush=True)
        return
    sys.path.insert(0, str(DEV))
    import mame_lab as lab
    # Accepted original control: ROM and defect seed both reproduce trial 0.
    seed_base = 170909229
    defect_seed = (seed_base * 2654435761 + 65537) % 4294967296
    if args.worker == 'env':
        from champion_residual_env import ChampionResidualEnv
        env = ChampionResidualEnv(DEV, root, seed_base=seed_base)
        obs, _ = env.reset(options=dict(rom_seed=seed_base, defect_seed=defect_seed))
        reward, steps = 0, 0
        try:
            while True:
                obs, r, term, trunc, info = env.step(0)
                assert env.observation_space.contains(obs), (obs.min(), obs.max())
                reward += r
                steps += 1
                if term or trunc:
                    assert info['valid'], info
                    break
            result = dict(totals=[info['wave'], info['score'], info['deaths'], steps], reward=reward)
        finally:
            env.close()
    else:
        state = root / 'lab_states'
        state.mkdir()
        os.environ.update(MAME_RL_SEED_BASE=str(seed_base),
                          MAME_LOG=str(root / 'lab.mame.log'))
        import mame_bridge
        mame_bridge.STATE_DIR = str(state)
        lab.setup_fsm(str(DEV / 'fsm_evolved_planner_v2_hunt.json'))
        env = lab.MameRobotronEnv(base_port=29000, frameskip=4, reset_pool=[0])
        try:
            totals = lab.play_game(env, 'verify', 'verify', str(root / 'lab.jsonl'), 20000,
                                  random.Random(defect_seed), 26)
            result = dict(totals=totals)
        finally:
            env.close()
    (root / f'{args.worker}.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
