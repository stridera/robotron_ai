"""Player-wall coordinate regression checks; no emulator or oracle policy input."""
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def load(full, substeps=1):
    with patch.dict(os.environ, {'VSEARCH_PLAYER_FULL_BOUNDS': str(full),
                               'VSEARCH_COLLISION_SUBSTEPS': str(substeps)}):
        spec = importlib.util.spec_from_file_location('bounds_test', ROOT/'engine/clearance_planner.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


def threat(x, y, vx=0, vy=0, reflect=False):
    return (np.array([x]), np.array([y]), np.array([vx]), np.array([vy]),
            np.array([1.]), np.array([False]), np.array([0.]), np.array([reflect]))


class PlayerBoundsTests(unittest.TestCase):
    def test_outward_commands_remain_at_each_calibrated_wall(self):
        for substeps in (1, 4):
            full = load(1, substeps)
            for x, y, d, tx, ty in [(0,200,7,100,200), (665,200,3,565,200),
                                    (300,0,1,300,100), (300,492,5,300,392)]:
                with self.subTest(substeps=substeps, direction=d):
                    self.assertAlmostEqual(full._heading_clearance(x,y,threat(tx,ty),d,3),100)
                    self.assertAlmostEqual(load(0,substeps)._heading_clearance(x,y,threat(tx,ty),d,3),90)

    def test_enemy_bank_wall_remains_at_inherited_location(self):
        # Shell 650 -> 670 reflects to 640, while player remains at x=665.
        full = load(1)
        self.assertAlmostEqual(full._heading_clearance(665,200,threat(650,200,20,0,True),3,1),25)

    def test_interior_predictions_unchanged(self):
        base, full = load(0), load(1)
        for d in range(1,9):
            t = threat(380,280,-8,6)
            self.assertEqual(base._heading_clearance(300,230,t,d,6,True),
                             full._heading_clearance(300,230,t,d,6,True))

    def test_scaled_diagonal_stops_at_corner(self):
        full = load(1)
        full.set_tick_scale(1.25)
        self.assertAlmostEqual(full._heading_clearance(664,491,threat(565,392),4,1),
                               100*2**.5)


if __name__ == '__main__':
    unittest.main()
