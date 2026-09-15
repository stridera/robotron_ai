"""Identity constraints, velocity units and legacy parity without gameplay."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import os
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from robotron_ai.brain import VelocityTracker


class UniqueTests(unittest.TestCase):
    def test_opt_in_environment(self):
        with patch.dict(os.environ, {'ROBOTRON_VELOCITY_UNIQUE':'1'}):
            self.assertTrue(VelocityTracker().unique_matches)
        with patch.dict(os.environ, {'ROBOTRON_VELOCITY_UNIQUE':'0'}):
            self.assertFalse(VelocityTracker().unique_matches)

    def tracker(self, unique):
        t=VelocityTracker(alpha=1)
        t.unique_matches=unique
        return t

    def test_one_old_identity_cannot_seed_two_detections(self):
        t=self.tracker(True)
        t.velocities([(100,100,'Enforcer')])
        self.assertEqual(t.velocities([(110,100,'Enforcer'),(101,100,'Enforcer')]),[(0,0),(1,0)])

    def test_distinct_class_and_unambiguous_dt_parity(self):
        a,b=self.tracker(False),self.tracker(True)
        for cur,dt in [([(100,100,'Enforcer'),(100,100,'Hulk'),(400,100,'Enforcer')],1),
                       ([(110,105,'Enforcer'),(101,100,'Hulk'),(420,90,'Enforcer')],.5)]:
            self.assertEqual(a.velocities(cur,dt),b.velocities(cur,dt))

    def test_gate_reset_and_unmatched_zero(self):
        t=self.tracker(True)
        t.velocities([(100,100,'Grunt')])
        self.assertEqual(t.velocities([(300,100,'Grunt')]),[(0,0)])
        t.reset()
        self.assertEqual(t.velocities([(301,100,'Grunt')]),[(0,0)])

    def test_legacy_reuse_is_preserved_when_disabled(self):
        t=self.tracker(False)
        t.velocities([(100,100,'Enforcer')])
        self.assertEqual(t.velocities([(110,100,'Enforcer'),(101,100,'Enforcer')]),[(10,0),(1,0)])

if __name__=='__main__': unittest.main()
