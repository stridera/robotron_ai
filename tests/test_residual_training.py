from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT.parent / 'robotron'))
try:
    import gymnasium as gym
    import torch
    from stable_baselines3 import PPO
    AVAILABLE = True
except ImportError:
    AVAILABLE = False


@unittest.skipUnless(AVAILABLE, 'requires isolated WSL ML runtime')
class ResidualTrainingTests(unittest.TestCase):
    def test_numpy_actor_matches_training_policy(self):
        import residual_policy as rp
        from train_champion_residual import export_actor
        class Dummy(gym.Env):
            observation_space = gym.spaces.Box(-2, 2, (rp.FEATURE_DIM,), np.float32)
            action_space = gym.spaces.Discrete(3)
        torch.set_num_threads(1)
        model = PPO('MlpPolicy', Dummy(), device='cpu', n_steps=8, batch_size=8,
                    policy_kwargs=dict(net_arch=dict(pi=[128, 128], vf=[128, 128])))
        obs = np.random.default_rng(5).uniform(-1, 1, (30, rp.FEATURE_DIM)).astype(np.float32)
        with torch.no_grad():
            latent = model.policy.mlp_extractor.forward_actor(torch.as_tensor(obs))
            expected = model.policy.action_net(latent).numpy()
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'actor.npz'
            export_actor(model, path)
            actual = rp.ResidualPolicy(path).logits(obs)
            np.testing.assert_allclose(actual, expected, atol=1e-6)
            scalar = np.stack([rp.ResidualPolicy(path).logits(row) for row in obs])
            np.testing.assert_allclose(scalar, expected, atol=1e-6)

    def test_invalid_transition_has_no_invented_reward_or_observation(self):
        from champion_residual_env import ChampionResidualEnv
        import residual_policy as rp
        def broken():
            yield
            raise RuntimeError('RECOVERED_EPISODE: test')
        env = object.__new__(ChampionResidualEnv)
        env.rp, env.env = rp, None
        env.context = dict(sprites=None, action=(0, 0), previous_move=1,
                           score=25000, deaths=1, wave=5, steps=50)
        env.game = broken()
        next(env.game)
        env.overrides = env.decisions = 0
        env.score0, env.episode = 0, 1
        with tempfile.TemporaryDirectory() as d:
            env.output = Path(d)
            obs, reward, term, trunc, info = env.step(0)
        self.assertEqual(reward, 0)
        self.assertFalse(term)
        self.assertTrue(trunc)
        self.assertEqual(info['valid'], 0)
        np.testing.assert_array_equal(obs, rp.features(env.context))


if __name__ == '__main__':
    unittest.main()
