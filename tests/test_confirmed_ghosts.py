"""Unconfirmed ghost visibility must not alter association or expiry."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from robotron_ai.brain import ProjectileCoaster


class ConfirmedGhostTests(unittest.TestCase):
    def tracker(self, enabled=True):
        t = ProjectileCoaster()
        t.confirmed_ghosts = enabled
        t.ALPHA = 1
        return t

    def test_default_off(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(ProjectileCoaster().confirmed_ghosts)
        with patch.dict(os.environ, {'ROBOTRON_COAST_CONFIRMED_ONLY': '1'}):
            self.assertTrue(ProjectileCoaster().confirmed_ghosts)

    def test_fresh_visible_singleton_hidden_but_retained(self):
        for name in ProjectileCoaster.NAMES:
            t = self.tracker()
            self.assertEqual(t.update([(100, 100, name)]), [(100, 100, name, 0., 0.)])
            self.assertEqual(t.update([]), [])
            self.assertEqual(len(t.tracks), 1)
            self.assertEqual(t.tracks[0]['miss'], 1)
            for _ in range(3):
                self.assertEqual(t.update([]), [])
            self.assertEqual(t.tracks, [])

    def test_reassociation_after_gap_measures_velocity_and_coasts(self):
        t = self.tracker()
        t.update([(100, 100, 'TankShell')])
        t.update([])
        self.assertEqual(t.update([(120, 100, 'TankShell')]), [(120, 100, 'TankShell', 10., 0.)])
        self.assertEqual(len(t.tracks), 1)
        self.assertEqual(t.update([]), [(130, 100, 'TankShell', 10., 0.)])
        t.reset()
        self.assertEqual(t.tracks, [])

    def test_only_output_changes_and_second_stationary_hit_confirms(self):
        base, candidate = self.tracker(False), self.tracker()
        seq = [[(100,100,'Prog')], [], [(100,100,'Prog')], [], [], [], []]
        for i, dets in enumerate(seq):
            a, b = base.update(dets), candidate.update(dets)
            self.assertEqual(base.tracks, candidate.tracks)
            if i == 1:
                self.assertEqual(len(a), 1)
                self.assertEqual(b, [])
            else:
                self.assertEqual(a, b)


if __name__ == '__main__':
    unittest.main()
