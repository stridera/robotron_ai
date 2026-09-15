from pathlib import Path
import subprocess
import sys
import types
import threading
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from robotron_ai.brain import ChampionBrain, VelocityTracker


class TrackingTimeTests(unittest.TestCase):
    def test_velocity_units_at_variable_sample_intervals(self):
        tracker = VelocityTracker(alpha=1)
        tracker.velocities([(100, 100, 'Enforcer')])
        self.assertEqual(tracker.velocities([(120, 90, 'Enforcer')], dt=2), [(10, -5)])
        self.assertEqual(tracker.velocities([(125, 87.5, 'Enforcer')], dt=.5), [(10, -5)])

    def test_duplicate_sample_does_not_zero_projectile_velocity(self):
        brain = ChampionBrain(0, use_coaster=True, normalize_tracking_time=True)
        brain.coaster.ALPHA = 1
        brain._track([(100, 100, 'EnforcerBullet')], (300, 200), 1.0)
        track = brain._track([(120, 100, 'EnforcerBullet')], (300, 200), 1 + 2/15)
        self.assertAlmostEqual(track[2][0][3], 10)
        duplicate = brain._track([(120, 100, 'EnforcerBullet')], (300, 200), 1 + 2/15)
        self.assertIs(duplicate, track)
        self.assertAlmostEqual(duplicate[2][0][3], 10)
        brain._track([(130, 100, 'EnforcerBullet')], (300, 200), 1 + 3/15)
        self.assertAlmostEqual(brain.coaster.tracks[0]['vx'], 10)

    def test_long_gap_restarts_velocity_history(self):
        brain = ChampionBrain(0, normalize_tracking_time=True)
        brain.vt.alpha = 1
        brain._track([(100, 100, 'Enforcer')], None, 1)
        self.assertEqual(brain._track([(120, 100, 'Enforcer')], None, 2)[1], [(0, 0)])

    def test_repeated_hdmi_reads_keep_the_capture_timestamp(self):
        from robotron_ai.perception import HdmiSource
        source = object.__new__(HdmiSource)
        source._lock = threading.Lock()
        source._latest = np.zeros((720, 1280, 3), np.uint8)
        source._latest_at = 123.5
        source.w, source.h = 1280, 720
        source.read()
        self.assertEqual(source.last_read_at, 123.5)
        source.read()
        self.assertEqual(source.last_read_at, 123.5)
        source._latest_at = 123.6
        source.read()
        self.assertEqual(source.last_read_at, 123.6)

    def test_default_actions_match_prechange_brain_with_tracking(self):
        old = types.ModuleType('robotron_ai.old_brain_test')
        old.__file__ = str(ROOT / 'brain.py')
        old.__package__ = 'robotron_ai'
        code = subprocess.check_output(['git', 'show', '0e73118:brain.py'], cwd=ROOT, text=True)
        exec(compile(code, old.__file__, 'exec'), old.__dict__)
        rng = np.random.default_rng(91026)
        for coast in (False, True):
            a = old.ChampionBrain(.7, player_lead_ticks=1.5, use_coaster=coast)
            b = ChampionBrain(.7, player_lead_ticks=1.5, use_coaster=coast,
                              normalize_tracking_time=False)
            for tick in range(200):
                entities = [(float(rng.uniform(0, 665)), float(rng.uniform(0, 492)), name)
                            for name in ['Grunt', 'Hulk', 'EnforcerBullet', 'TankShell', 'Mommy'] * 3]
                if tick % 7 == 0:
                    a.blind_tick(entities)
                    b.blind_tick(entities, sampled_at=tick / 10)
                else:
                    self.assertEqual(a.decide((300, 200), entities),
                                     b.decide((300, 200), entities, sampled_at=tick / 10))


if __name__ == '__main__':
    unittest.main()
