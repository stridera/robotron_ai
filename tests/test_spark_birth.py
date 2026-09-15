"""Observed-spark velocity seed: ambiguity, lifecycle and default isolation."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from robotron_ai.brain import ProjectileCoaster


class SparkBirthTests(unittest.TestCase):
    def test_default_and_opt_in(self):
        with patch.dict(os.environ, {}, clear=True):
            t = ProjectileCoaster()
            self.assertFalse(t.spark_birth)
            self.assertEqual(t.update([(120,100,'EnforcerBullet')], launchers=[(100,100,'Enforcer')])[0][3:], (0.,0.))
        with patch.dict(os.environ, {'ROBOTRON_SPARK_BIRTH_VELOCITY':'1'}):
            self.assertTrue(ProjectileCoaster().spark_birth)

    def test_only_unambiguous_observed_spark(self):
        seed = ProjectileCoaster._birth_velocity
        self.assertEqual(seed(120,100,'EnforcerBullet',[(100,100,'Enforcer')]), (12.,0.))
        for name, sources in [('TankShell',[(100,100,'Enforcer')]),
                              ('EnforcerBullet',[(100,100,'Tank')]),
                              ('EnforcerBullet',[(100,100,'Enforcer'),(125,100,'Enforcer')]),
                              ('EnforcerBullet',[(119,100,'Enforcer')]),
                              ('EnforcerBullet',[(0,100,'Enforcer')])]:
            self.assertEqual(seed(120,100,name,sources), (0.,0.))
        t=ProjectileCoaster(); t.spark_birth=True
        self.assertEqual(t.update([], launchers=[(100,100,'Enforcer')]), [])

    def test_velocity_evidence_replaces_prior_and_ghost_expires(self):
        t=ProjectileCoaster(); t.spark_birth=True; t.ALPHA=1
        t.update([(120,100,'EnforcerBullet')], launchers=[(100,100,'Enforcer')])
        t.update([(130,100,'EnforcerBullet')], launchers=[(140,100,'Enforcer')])
        self.assertEqual(t.tracks[0]['vx'], 10.)
        self.assertEqual(len(t.tracks),1)
        self.assertEqual(t.update([])[0][:2], (140.,100.))
        for _ in range(3): out=t.update([])
        self.assertEqual(out,[])
        t.reset(); self.assertEqual(t.tracks,[])


if __name__ == '__main__':
    unittest.main()
