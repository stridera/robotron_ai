import importlib.util
from pathlib import Path
import tempfile
import unittest

import numpy as np

path = Path(__file__).resolve().parents[2] / 'robotron/residual_policy.py'
spec = importlib.util.spec_from_file_location('residual', path)
rp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rp)


class ResidualTests(unittest.TestCase):
    def context(self):
        return dict(sprites=[(300, 200, 'Player', 0, 0),
                             (315, 208, 'EnforcerBullet', -10, 5)],
                    action=(1, 7), previous_move=8, score=100, deaths=1, wave=20)

    def test_metadata_cannot_leak_into_policy(self):
        c = self.context()
        a = rp.features(c)
        c.update(score=999999, deaths=55, wave=100, steps=30000)
        np.testing.assert_array_equal(a, rp.features(c))
        self.assertEqual(a.shape, (rp.FEATURE_DIM,))
        self.assertTrue(np.isfinite(a).all())

    def test_only_adjacent_movement_changes_and_fire_stays(self):
        c = self.context()
        self.assertIsNone(rp.corrected_action(c, 0))
        self.assertEqual(rp.corrected_action(c, 1), (8, 7))
        self.assertEqual(rp.corrected_action(c, 2), (2, 7))
        c['action'] = (8, 3)
        self.assertEqual(rp.corrected_action(c, 2), (1, 3))
        c['sprites'] = None
        self.assertIsNone(rp.corrected_action(c, 1))
        self.assertTrue((rp.features(c) == 0).all())

    def test_initial_actor_exactly_preserves_champion(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'actor.npz'
            np.savez(p, feature_dim=rp.FEATURE_DIM, layers=0,
                     wa=np.zeros((3, rp.FEATURE_DIM)), ba=np.log([.98, .01, .01]))
            actor = rp.ResidualPolicy(p)
            self.assertIsNone(actor(self.context()))

    def test_sampled_actor_is_reproducible_and_does_not_mutate_input(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'actor.npz'
            np.savez(p, feature_dim=rp.FEATURE_DIM, layers=0,
                     wa=np.zeros((3, rp.FEATURE_DIM)), ba=np.log([.5, .25, .25]))
            a = rp.ResidualPolicy(p, sample=True, seed=2084)
            b = rp.ResidualPolicy(p, sample=True, seed=2084)
            context = self.context()
            before = rp.features(context).copy()
            choices = [a(context) for _ in range(100)]
            self.assertEqual(choices, [b(context) for _ in range(100)])
            self.assertGreater(a.overrides, 20)
            self.assertLess(a.overrides, 80)
            np.testing.assert_array_equal(before, rp.features(context))


if __name__ == '__main__':
    unittest.main()
