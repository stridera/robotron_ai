"""Safety and geometry checks for overnight research variants (no emulator)."""
import unittest
import numpy as np
from test_turn_paths import DEV, load


def threats(rows):
    a = np.array(rows, dtype=float).T
    return (*a[:5], a[5].astype(bool), a[6], a[7].astype(int))


class NightPlannerTests(unittest.TestCase):
    def setUp(self):
        if not DEV.exists():
            self.skipTest('dev tree not installed')
        self.cp = load(DEV)

    def test_laser_hits_first_object_instead_of_shooting_through_it(self):
        c = self.cp
        idx, hit = c._laser_hits(np.array([[100.]]), np.array([[100.]]),
                                np.array([[100.]]), np.array([[0.]]),
                                np.array([170., 140.]), np.array([100., 100.]),
                                np.array([170., 140.]), np.array([100., 100.]),
                                np.ones((1, 2), bool))
        self.assertTrue(hit[0])
        self.assertEqual(idx[0], 1)

    def test_crossing_target_hit_uses_relative_motion(self):
        c = self.cp
        idx, hit = c._laser_hits(np.array([[100.]]), np.array([[100.]]),
                                np.array([[100.]]), np.array([[0.]]),
                                np.array([150.]), np.array([150.]),
                                np.array([150.]), np.array([50.]),
                                np.ones((1, 1), bool))
        self.assertTrue(hit[0])
        self.assertEqual(idx[0], 0)

    def test_shot_credit_requires_travel_and_wait_and_never_removes_hulk(self):
        c = self.cp
        t = threats([(157, 100, 0, 0, 1, 0, 0, 0)])
        before = [a.copy() for a in t]
        straight = c._heading_clearance(100, 100, t, 3, 6)
        clr, fire = c._joint_heading(100, 100, t, ['Electrode'], 3, 6, 3)
        self.assertEqual(fire, 3)
        self.assertGreater(clr, straight + 20)
        # No credit before the laser is allowed to leave, or for invincible Hulk.
        c.SHOT_DELAY = 6
        self.assertAlmostEqual(c._joint_heading(100, 100, t, ['Electrode'], 3, 6, 3)[0], straight)
        c.SHOT_DELAY = 2
        self.assertAlmostEqual(c._joint_heading(100, 100, t, ['Hulk'], 3, 6, 3)[0], straight)
        for a, b in zip(t, before):
            np.testing.assert_array_equal(a, b)

    def test_joint_no_credit_for_first_steps_even_when_target_is_hit(self):
        c = self.cp
        t = threats([(129, 100, 0, 0, 1, 0, 0, 0)])
        # Collision during the laser's own hit step stays in the risk score.
        self.assertLess(c._joint_heading(100, 100, t, ['Electrode'], 3, 6, 3)[0], 1)

    def test_velocity_uncertainty_leaves_nonprojectiles_and_input_unchanged(self):
        c = self.cp
        c.VELOCITY_FAN = 24
        t = threats([(157, 100, -5, 7, 1, 0, 0, 0)])
        central = [c._heading_clearance(100, 100, t, d, 6) for d in range(1, 9)]
        self.assertEqual(c._velocity_fan_clearances(100, 100, t, ['Grunt'], central), central)
        before = [a.copy() for a in t]
        altered = c._velocity_fan_clearances(100, 100, t, ['TankShell'], central)
        self.assertFalse(np.allclose(altered, central))
        for a, b in zip(t, before):
            np.testing.assert_array_equal(a, b)

    def test_committed_route_executes_its_turn_instead_of_postponing_it(self):
        c = self.cp
        c.TURN_STEPS = 2
        c.TURN_COMMIT = True
        obstacle = (157., 100., 'Electrode', 0., 0.)
        self.assertEqual(c.clearance_search([(100., 100., 'Player', 0., 0.), obstacle], 3, 3)[0], 3)
        self.assertEqual(len(c.TURN_PENDING), 2)
        turn = c.TURN_PENDING[-1]
        self.assertNotEqual(turn, 3)
        self.assertEqual(c.clearance_search([(109.5, 100., 'Player', 0., 0.), obstacle], 7, 3)[0], 3)
        self.assertEqual(c.clearance_search([(119., 100., 'Player', 0., 0.), obstacle], 3, 3)[0], turn)
        self.assertEqual(c.TURN_PENDING, [])

    def test_committed_route_cancels_for_new_immediate_obstacle(self):
        c = self.cp
        c.TURN_STEPS = 2
        c.TURN_COMMIT = True
        c.TURN_PENDING = [3, 1]
        c.TURN_LAST_PLAYER = (100., 100.)
        mv, _ = c.clearance_search([(109.5, 100., 'Player', 0., 0.),
                                    (119., 100., 'Electrode', 0., 0.)], 7, 3)
        self.assertEqual(mv, 7)
        self.assertEqual(c.TURN_PENDING, [])


if __name__ == '__main__':
    unittest.main()
