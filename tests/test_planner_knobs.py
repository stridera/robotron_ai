"""Tests for the 2026-09-14 opt-in planner knobs: FIRE_ALT and DISCOUNT.

Run from the package's parent directory:
    python -m unittest robotron_ai.tests.test_planner_knobs -v
"""
import importlib
import os
import random
import unittest

from ..engine import clearance_planner as cp


def _scenes(n=200, seed=3):
    rng = random.Random(seed)
    names = ["Grunt", "Grunt", "Hulk", "Electrode", "EnforcerBullet", "TankShell",
             "CruiseMissile", "Enforcer", "Brain", "Quark", "Mommy"]
    out = []
    for _ in range(n):
        px, py = rng.uniform(30, 630), rng.uniform(30, 460)
        sp = [(px, py, "Player", 0.0, 0.0)]
        for _ in range(rng.randint(3, 25)):
            sp.append((rng.uniform(0, 665), rng.uniform(0, 492), rng.choice(names),
                       rng.uniform(-12, 12), rng.uniform(-12, 12)))
        out.append((sp, rng.randint(1, 8), rng.randint(1, 8)))
    return out


class FireAltTest(unittest.TestCase):
    def setUp(self):
        cp.set_fire_alt(False)

    def tearDown(self):
        cp.set_fire_alt(False)

    def test_off_is_identity(self):
        """With the knob off the wrapper returns exactly the core result."""
        for sp, mv, fr in _scenes(100):
            self.assertEqual(cp.clearance_search(sp, mv, fr),
                             cp._clearance_search_impl(sp, mv, fr))

    def test_alternates_between_two_targets(self):
        cp.set_fire_alt(True)
        sp = [(300, 250, "Player", 0, 0), (360, 250, "Grunt", 0, 0), (300, 190, "Grunt", 0, 0)]
        seq = [cp.clearance_search(sp, 1, 3)[1] for _ in range(6)]
        self.assertEqual(seq, [3, 1, 3, 1, 3, 1])   # FSM asks E (3); the N target alternates in

    def test_holds_with_one_target(self):
        cp.set_fire_alt(True)
        sp = [(300, 250, "Player", 0, 0), (360, 250, "Grunt", 0, 0)]
        self.assertEqual([cp.clearance_search(sp, 1, 3)[1] for _ in range(4)], [3, 3, 3, 3])

    def test_ignores_hulks_family_and_far_targets(self):
        cp.set_fire_alt(True, radius=160)
        sp = [(300, 250, "Player", 0, 0), (360, 250, "Grunt", 0, 0),
              (300, 190, "Hulk", 0, 0), (300, 310, "Mommy", 0, 0), (300, 470, "Grunt", 0, 0)]
        self.assertEqual([cp.clearance_search(sp, 1, 3)[1] for _ in range(4)], [3, 3, 3, 3])

    def test_no_fire_passes_through(self):
        cp.set_fire_alt(True)
        sp = [(300, 250, "Player", 0, 0), (360, 250, "Grunt", 0, 0), (300, 190, "Grunt", 0, 0)]
        self.assertEqual(cp.clearance_search(sp, 1, 0)[1], 0)
        self.assertEqual(cp.clearance_search(sp, 1, 0)[1], 0)


class DiscountTest(unittest.TestCase):
    def test_zero_discount_is_identity(self):
        old = cp.DISCOUNT
        try:
            cp.DISCOUNT = 0.0
            a = [cp.clearance_search(sp, mv, fr) for sp, mv, fr in _scenes(60, seed=5)]
            self.assertEqual(a, [cp.clearance_search(sp, mv, fr) for sp, mv, fr in _scenes(60, seed=5)])
        finally:
            cp.DISCOUNT = old

    def test_discount_never_lowers_clearance(self):
        """clr*(1+g*t) >= clr, so a discounted heading is never judged worse."""
        old = cp.DISCOUNT
        try:
            T = None
            for sp, mv, fr in _scenes(40, seed=7):
                player = sp[0]
                xs = [s for s in sp[1:] if s[2] not in ("Mommy", "Mikey", "Daddy")]
                import numpy as np
                tx = np.array([s[0] for s in xs], dtype=float)
                ty = np.array([s[1] for s in xs], dtype=float)
                vx = np.array([s[3] for s in xs], dtype=float)
                vy = np.array([s[4] for s in xs], dtype=float)
                w = np.ones(len(xs))
                chase = np.zeros(len(xs), dtype=bool)
                spd = np.zeros(len(xs))
                refl = np.zeros(len(xs), dtype=bool)
                T = (tx, ty, vx, vy, w, chase, spd, refl)
                for d in range(1, 9):
                    cp.DISCOUNT = 0.0
                    base = cp._heading_clearance(player[0], player[1], T, d, 6)
                    cp.DISCOUNT = 0.2
                    disc = cp._heading_clearance(player[0], player[1], T, d, 6)
                    self.assertGreaterEqual(disc + 1e-9, base)
        finally:
            cp.DISCOUNT = old


if __name__ == "__main__":
    unittest.main()
