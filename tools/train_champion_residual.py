"""PPO steering corrections using current champion + calibrated defects + NET.

Use the repaired Python with the old ML site-packages on PYTHONPATH. Freezes
source, checkpoints frequently, uses CPU for a small MLP. No automatic promotion.
"""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

REPO = Path(__file__).resolve().parents[1]
DEV = REPO.parent / 'robotron'


def export_actor(model, path):
    import numpy as np
    import torch
    from residual_policy import FEATURE_DIM
    layers = [m for m in model.policy.mlp_extractor.policy_net if isinstance(m, torch.nn.Linear)]
    data = dict(feature_dim=np.array(FEATURE_DIM), layers=np.array(len(layers)))
    for i, layer in enumerate(layers):
        data[f'w{i}'] = layer.weight.detach().cpu().numpy()
        data[f'b{i}'] = layer.bias.detach().cpu().numpy()
    data['wa'] = model.policy.action_net.weight.detach().cpu().numpy()
    data['ba'] = model.policy.action_net.bias.detach().cpu().numpy()
    np.savez(path, **data)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--name', default='residual_' + datetime.now().strftime('%Y%m%d_%H%M%S'))
    ap.add_argument('--steps', type=int, default=3000000)
    ap.add_argument('--workers', type=int, default=12)
    ap.add_argument('--seed', type=int, default=91026000)
    ap.add_argument('--checkpoint', type=int, default=200000)
    ap.add_argument('--max-hours', type=float, default=4)
    ap.add_argument('--resume', type=Path, help='PPO checkpoint; --steps remains the cumulative target')
    args = ap.parse_args()
    out = REPO / 'logs' / args.name
    out.mkdir(exist_ok=False)
    source = out / 'source'
    source.mkdir()
    for name in ('mame_lab.py', 'mame_score.py', 'residual_policy.py', 'clearance_planner.py',
                 'robotron_fsm.py', 'fsm_evolved_planner_v2_hunt.json'):
        origin = args.resume.resolve().parent / 'source' if args.resume else DEV
        shutil.copy2(origin / name, source / name)
    shutil.copy2(__file__, source / Path(__file__).name)
    shutil.copy2(Path(__file__).with_name('champion_residual_env.py'), source / 'champion_residual_env.py')
    for key in list(os.environ):
        if key.startswith(('LAB_', 'VSEARCH_', 'ROBOTRON_', 'FSM_', 'MAME_')):
            del os.environ[key]
    from run_collision_mame_fresh import CAL
    os.environ.update(CAL, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
    sys.path.insert(0, str(source))
    import numpy as np
    import torch
    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env import SubprocVecEnv
    from stable_baselines3.common.monitor import Monitor
    from stable_baselines3.common.callbacks import BaseCallback
    from champion_residual_env import ChampionResidualEnv
    torch.set_num_threads(1)
    manifest = dict(vars(args), calibration=CAL, reward='delta_score/1000 - 25*delta_deaths',
                    actions=['keep', 'left45', 'right45'], initial_probabilities=[.98, .01, .01],
                    started=time.time(), source_hashes={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                                        for p in source.iterdir() if p.is_file()})
    if args.resume:
        manifest['resume'] = str(args.resume.resolve())
        manifest['resume_sha256'] = hashlib.sha256(args.resume.read_bytes()).hexdigest()
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    def make_env(rank):
        return lambda: Monitor(ChampionResidualEnv(source, out, rank, args.seed),
                               info_keywords=('score', 'wave', 'deaths', 'net', 'override_fraction', 'valid'))
    envs = SubprocVecEnv([make_env(i) for i in range(args.workers)], start_method='spawn')
    if args.resume:
        model = PPO.load(args.resume, env=envs, device='cpu')
        model.set_random_seed(args.seed)
        if model.num_timesteps >= args.steps:
            envs.close()
            raise ValueError('Resume checkpoint already meets the cumulative target')
    else:
        model = PPO('MlpPolicy', envs, device='cpu', verbose=1, seed=args.seed,
                n_steps=1024, batch_size=512, n_epochs=4, gamma=.999, gae_lambda=.97,
                ent_coef=.001, learning_rate=5e-5, clip_range=.1, target_kl=.01,
                policy_kwargs=dict(net_arch=dict(pi=[128, 128], vf=[128, 128])))
        with torch.no_grad():
            model.policy.action_net.weight.zero_()
            model.policy.action_net.bias.copy_(torch.tensor(np.log([.98, .01, .01]), dtype=torch.float32))
    initial_steps = model.num_timesteps
    export_actor(model, out / f'actor_{initial_steps}.npz')
    began = time.monotonic()
    (out / 'status.json').write_text(json.dumps(dict(steps=initial_steps,
        resumed=bool(args.resume), running=True, elapsed_s=0), indent=2))
    class Checkpoints(BaseCallback):
        last = initial_steps
        def _on_step(self):
            if self.num_timesteps - self.last >= args.checkpoint:
                self.last = self.num_timesteps
                model.save(out / f'model_{self.num_timesteps}')
                export_actor(model, out / f'actor_{self.num_timesteps}.npz')
                (out / 'status.json').write_text(json.dumps(dict(steps=self.num_timesteps,
                    elapsed_s=time.monotonic()-began, running=True), indent=2))
            return not (out / 'STOP').exists() and time.monotonic() - began < args.max_hours * 3600
    try:
        model.learn(total_timesteps=args.steps-initial_steps, callback=Checkpoints(),
                    reset_num_timesteps=not bool(args.resume))
        model.save(out / 'final_model')
        export_actor(model, out / 'actor_final.npz')
        (out / 'status.json').write_text(json.dumps(dict(steps=model.num_timesteps,
            elapsed_s=time.monotonic()-began, running=False, complete=model.num_timesteps >= args.steps), indent=2))
    finally:
        envs.close()


if __name__ == '__main__':
    main()
