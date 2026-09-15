"""Offline geometric checks; no game, capture, controller, or detector imports.

Run from robotron_ai: python -m unittest discover -s tests -v
"""
import importlib.util
import os
from pathlib import Path
import subprocess
import types
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def load(path, substeps):
    with patch.dict(os.environ, {"VSEARCH_COLLISION_SUBSTEPS": str(substeps)}):
        spec = importlib.util.spec_from_file_location("planner_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


def threats(rows):
    a = np.asarray(rows, dtype=float).T
    return (*a[:5], a[5].astype(bool), a[6], a[7].astype(bool))


class CollisionSamplingTests(unittest.TestCase):
    def setUp(self):
        self.base = load(ROOT / "engine/clearance_planner.py", 1)
        self.fine = load(ROOT / "engine/clearance_planner.py", 4)

    def test_fast_crossing_between_clear_endpoints(self):
        t = threats([(104.75, 150, 0, -100, 1.8, 0, 0, 0)])
        self.assertGreater(self.base._heading_clearance(100, 100, t, 3, 1), 21)
        self.assertAlmostEqual(self.fine._heading_clearance(100, 100, t, 3, 1), 0)

    def test_bank_shot_visits_wall_before_reflected_endpoint(self):
        # Shell goes 635 -> 655 -> 635; a chord would stay at 635.
        t = threats([(635, 200, 40, 0, 1, 0, 0, 1)])
        self.assertGreater(self.base._heading_clearance(655, 200, t, 3, 1), 19)
        self.assertAlmostEqual(self.fine._heading_clearance(655, 200, t, 3, 1), 0)

    def test_player_stops_at_wall_at_impact_time(self):
        # Player reaches right wall before t=.5; the projectile crosses there.
        t = threats([(655, 250, 0, -100, 1, 0, 0, 0)])
        self.assertAlmostEqual(self.fine._heading_clearance(654, 200, t, 3, 1), 0)

    def test_binding_threat_comes_from_intermediate_collision(self):
        t = threats([(109.5, 130, 0, 0, 1, 0, 0, 0),
                     (104.75, 150, 0, -100, 1, 0, 0, 0)])
        self.assertEqual(self.base._heading_clearance(100, 100, t, 3, 1, True)[1], 0)
        self.assertEqual(self.fine._heading_clearance(100, 100, t, 3, 1, True), (0, 1))

    def test_additional_samples_never_increase_clearance_or_mutate_input(self):
        rng = np.random.default_rng(2084)
        for _ in range(40):
            t = threats([(rng.uniform(10, 655), rng.uniform(10, 482),
                          rng.uniform(-90, 90), rng.uniform(-90, 90),
                          rng.uniform(.8, 2.2), rng.integers(2), 8,
                          rng.integers(2)) for _ in range(12)])
            before = [a.copy() for a in t]
            px, py = rng.uniform(10, 655), rng.uniform(10, 482)
            for d in range(1, 9):
                self.assertLessEqual(self.fine._heading_clearance(px, py, t, d, 6),
                                     self.base._heading_clearance(px, py, t, d, 6) + 1e-10)
            for a, b in zip(t, before):
                np.testing.assert_array_equal(a, b)

    def test_default_matches_pre_experiment_commit(self):
        # Independent reference: frozen shipped source, not another new-code path.
        source = subprocess.check_output(
            ["git", "show", "0e73118:engine/clearance_planner.py"], cwd=ROOT,
            text=True, encoding="utf-8")
        old = types.ModuleType("reference_planner")
        exec(compile(source, "reference_planner", "exec"), old.__dict__)
        rng = np.random.default_rng(100)
        for _ in range(50):
            sprites = [(rng.uniform(10, 655), rng.uniform(10, 482), "Player", 0, 0)]
            names = ["TankShell", "EnforcerBullet", "Grunt", "Hulk", "Brain", "Mommy"]
            sprites += [(rng.uniform(0, 665), rng.uniform(0, 492), names[i % 6],
                         rng.uniform(-70, 70), rng.uniform(-70, 70)) for i in range(20)]
            for d in range(1, 9):
                self.assertEqual(self.base.clearance_search(sprites, d, 3),
                                 old.clearance_search(sprites, d, 3))

    def test_dev_and_production_geometry_match(self):
        path = ROOT.parent / "robotron/clearance_planner.py"
        if not path.exists():
            self.skipTest("dev tree not installed")
        dev = load(path, 4)
        t = threats([(635, 200, 40, 0, 1.8, 0, 0, 1),
                     (104.75, 150, 0, -100, 1.8, 0, 0, 0)])
        for px, py in [(655, 200), (100, 100)]:
            for d in range(1, 9):
                self.assertEqual(dev._heading_clearance(px, py, t, d, 6, True),
                                 self.fine._heading_clearance(px, py, t, d, 6, True))


if __name__ == "__main__":
    unittest.main()
