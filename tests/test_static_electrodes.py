"""Stationary obstacle semantics and opt-in/default isolation."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from robotron_ai.brain import VelocityTracker


class StaticElectrodeTests(unittest.TestCase):
    def test_opt_in_only(self):
        with patch.dict(os.environ, {'ROBOTRON_STATIC_ELECTRODES':'0'}):
            self.assertFalse(VelocityTracker().static_electrodes)
        with patch.dict(os.environ, {'ROBOTRON_STATIC_ELECTRODES':'1'}):
            self.assertTrue(VelocityTracker().static_electrodes)

    def test_jitter_and_identity_jump_do_not_move_obstacles(self):
        t = VelocityTracker(alpha=1)
        t.static_electrodes = True
        t.velocities([(100,100,'Electrode'), (100,100,'Enforcer')])
        self.assertEqual(t.velocities([(103,98,'Electrode'), (103,98,'Enforcer')], .5),
                         [(0,0), (6,-4)])
        self.assertEqual(t.velocities([(200,100,'Electrode')]), [(0,0)])
        self.assertEqual(t.prev[0][3:], (0,0))
        t.reset()
        self.assertEqual(t.velocities([(201,100,'Electrode')]), [(0,0)])

    def test_disabled_preserves_electrode_velocity(self):
        t = VelocityTracker(alpha=1)
        t.static_electrodes = False
        t.velocities([(100,100,'Electrode')])
        self.assertEqual(t.velocities([(103,98,'Electrode')]), [(3,-2)])


if __name__ == '__main__':
    unittest.main()
