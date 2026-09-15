"""Projectile association competition, lifecycle and default isolation."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from robotron_ai.brain import ProjectileCoaster


class CoastPairsTests(unittest.TestCase):
    def tracker(self, enabled=True):
        t = ProjectileCoaster()
        t.closest_pairs = enabled
        t.ALPHA = 1
        return t

    def test_flag_default_off(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(ProjectileCoaster().closest_pairs)
        with patch.dict(os.environ, {'ROBOTRON_COAST_CLOSEST_PAIRS':'1'}):
            self.assertTrue(ProjectileCoaster().closest_pairs)

    def test_exact_continuation_reserved_before_weak_box(self):
        t = self.tracker()
        t.update([(100,100,'TankShell')])
        t.update([(120,100,'TankShell'),(100,100,'TankShell')])
        self.assertEqual((t.tracks[0]['x'],t.tracks[0]['vx']), (100,0))
        self.assertEqual(len(t.tracks),2)
        self.assertEqual(t.tracks[1]['vx'],0)

    def test_detection_order_independent_with_distinct_matches(self):
        outputs=[]
        for dets in ([(111,100,'TankShell'),(131,100,'TankShell')],
                     [(131,100,'TankShell'),(111,100,'TankShell')]):
            t=self.tracker()
            t.update([(100,100,'TankShell'),(130,100,'TankShell')])
            outputs.append(sorted(t.update(dets)))
        self.assertEqual(*outputs)
        self.assertEqual([r[3] for r in outputs[0]], [11,1])

    def test_legacy_keeps_order_behavior(self):
        t=self.tracker(False)
        t.update([(100,100,'TankShell')])
        t.update([(120,100,'TankShell'),(100,100,'TankShell')])
        self.assertEqual((t.tracks[0]['x'],t.tracks[0]['vx']), (120,20))

    def test_class_gate_expiry_and_reset(self):
        t=self.tracker()
        t.update([(100,100,'TankShell')])
        out=t.update([(100,100,'EnforcerBullet'),(400,100,'TankShell')])
        self.assertEqual(len(out),3)
        self.assertTrue(all(r[3:]==(0.,0.) for r in out))
        for _ in range(4): out=t.update([])
        self.assertEqual(out,[])
        t.update([(100,100,'TankShell')]); t.reset()
        self.assertEqual(t.tracks,[])


if __name__ == '__main__':
    unittest.main()
