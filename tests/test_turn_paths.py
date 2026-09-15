"""Independent scalar replay checks for the opt-in dev turning planner."""
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT.parent / 'robotron/clearance_planner.py'


def load(path, turns=0):
    clean = {k: v for k, v in os.environ.items() if not k.startswith('VSEARCH_')}
    clean['VSEARCH_TURN_STEPS'] = str(turns)
    with patch.dict(os.environ, clean, clear=True):
        spec = importlib.util.spec_from_file_location('turn_test', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


class TurnPathTests(unittest.TestCase):
    def setUp(self):
        if not DEV.exists():
            self.skipTest('dev tree not installed')
        self.cp = load(DEV, 2)

    def test_batched_branches_match_scalar_replays_and_keep_inputs(self):
        c = self.cp
        rng = np.random.default_rng(2084)
        for _ in range(20):
            n = 12
            T = (rng.uniform(10, 655, n), rng.uniform(10, 482, n),
                 rng.uniform(-50, 50, n), rng.uniform(-50, 50, n),
                 rng.uniform(.8, 2.2, n), rng.random(n) < .3,
                 rng.uniform(2, 14, n), rng.integers(0, 2, n))
            before = [a.copy() for a in T]
            px, py = rng.uniform(10, 655), rng.uniform(10, 482)
            for split in (1, 2, 3, 6):
                for d in (1, 3, 6, 8):
                    prefix = c._heading_clearance(px, py, T, d, split, True)
                    ex, ey, T2 = c._end_state(px, py, T, d, split)
                    choices = []
                    for e in range(1, 9):
                        tail = c._heading_clearance(ex, ey, T2, e, 6 - split, True)
                        choices.append(prefix if prefix[0] <= tail[0] else tail)
                    best = max(range(8), key=lambda i: (choices[i][0], -c._angdist(i+1, d)))
                    actual = c._turn_clearance(px, py, T, d, 6, split, True)
                    self.assertAlmostEqual(actual[0], choices[best][0], places=10)
                    self.assertEqual(actual[1], choices[best][1])
                    self.assertGreaterEqual(actual[0] + 1e-10,
                                            c._heading_clearance(px, py, T, d, 6))
            for a, b in zip(T, before):
                np.testing.assert_array_equal(a, b)

    def test_turn_avoids_obstacle_on_straight_route(self):
        c = self.cp
        T = tuple(np.array([v]) for v in (157., 100., 0., 0., 1., False, 0., 0))
        self.assertAlmostEqual(c._heading_clearance(100, 100, T, 3, 6), 0)
        self.assertGreater(c._turn_clearance(100, 100, T, 3, 6, 2), 30)

    def test_disabled_matches_frozen_pre_turn_dev(self):
        frozen = ROOT / 'logs/collision_fresh_20260908_1428/source/clearance_planner.py'
        if not frozen.exists():
            self.skipTest('pre-turn experiment snapshot not installed')
        old, new = load(frozen), load(DEV)
        rng = np.random.default_rng(60)
        for _ in range(30):
            sprites = [(rng.uniform(10, 655), rng.uniform(10, 482), 'Player', 0, 0)]
            names = ('Grunt', 'TankShell', 'Hulk', 'EnforcerBullet', 'Brain', 'Mommy')
            sprites += [(rng.uniform(0, 665), rng.uniform(0, 492), names[i % 6],
                         rng.uniform(-30, 30), rng.uniform(-30, 30)) for i in range(20)]
            for d in range(1, 9):
                self.assertEqual(new.clearance_search(sprites, d, 3),
                                 old.clearance_search(sprites, d, 3))


if __name__ == '__main__':
    unittest.main()
