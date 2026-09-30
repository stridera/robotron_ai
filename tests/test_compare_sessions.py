"""tools/compare_sessions.py on synthetic session folders, and the session
folder naming in telemetry.

Run from the package's parent directory:
    python -m unittest robotron_ai.tests.test_compare_sessions -v
"""
import json
import os
import tempfile
import unittest

from .. import telemetry
from ..tools import compare_sessions as cs


def _write(root, name, tag, waves, scores, knobs, tick_hz=17.5):
    d = os.path.join(root, name)
    os.makedirs(d)
    games = [dict(game=f"g{i}", wave=w, score=s, deaths=0, lives_bought=3 + s // 25000)
             for i, (w, s) in enumerate(zip(waves, scores))]
    rep = dict(tag=tag, games=games, knobs=knobs, config=dict(hz=15, lag_ticks=0.7),
               tick=dict(hz=tick_hz))
    with open(os.path.join(d, "report.json"), "w") as f:
        json.dump(rep, f)
    return d


class CompareTest(unittest.TestCase):
    def test_round18_numbers_reproduce(self):
        waves = [37, 29, 38, 32, 39, 36, 29, 11, 29, 18]
        scores = [934725, 795750, 945650, 790150, 983950, 865425, 770225, 246875, 692450, 430725]
        with tempfile.TemporaryDirectory() as root:
            _write(root, "a", "r18", waves, scores, {"VSEARCH_CLEAR_DANGER": "18"})
            arms = cs.collect([os.path.join(root, "a")])
            rep = cs.compare(arms)
        s = rep["arms"][0]
        self.assertEqual(s["games"], 10)
        self.assertEqual(s["mean_wave"], 29.8)
        self.assertEqual(s["record"], 39)
        self.assertAlmostEqual(s["deaths_per_wave"], 1.081, places=3)
        self.assertEqual(s["score_per_wave"], 25020)
        self.assertLess(s["net_per_wave"], 0)
        self.assertEqual(rep["comparisons"], [])

    def test_two_arms_pooled_by_tag_and_compared(self):
        with tempfile.TemporaryDirectory() as root:
            a1 = _write(root, "s1_base", "base", [10, 12, 11, 9, 13], [200000] * 5, {"K": "1"})
            a2 = _write(root, "s2_base", "base", [11, 10, 12, 10, 12], [200000] * 5, {"K": "1"})
            b = _write(root, "s3_cand", "cand", [30, 28, 33, 31, 29, 30, 32, 27, 30, 31],
                       [700000] * 10, {"K": "2"})
            arms = cs.collect([a1, a2, b])
            rep = cs.compare(arms)
        self.assertEqual([s["arm"] for s in rep["arms"]], ["base", "cand"])
        self.assertEqual(rep["arms"][0]["games"], 10)      # two sessions pooled
        c = rep["comparisons"][0]
        self.assertEqual(c["knobs_changed"], {"K": ("1", "2")})
        diff, lo, hi = c["mean_wave"]
        self.assertGreater(lo, 0)                          # interval excludes zero
        self.assertLess(c["mean_wave_p"], 0.001)
        text = cs.render(rep)
        self.assertIn("verdict on depth: real", text)
        self.assertIn("K 1->2", text)

    def test_glob_and_unresolved_verdict(self):
        with tempfile.TemporaryDirectory() as root:
            _write(root, "x_a", "a", [20, 25, 18, 22], [500000] * 4, {})
            _write(root, "x_b", "b", [21, 24, 19, 23], [500000] * 4, {})
            arms = cs.collect([os.path.join(root, "x_*")])
            rep = cs.compare(arms)
        self.assertEqual(len(rep["arms"]), 2)
        self.assertIn("not resolved", cs.render(rep))

    def test_welch_p_sane(self):
        self.assertGreater(cs.welch_p([1, 2, 3, 4], [1, 2, 3, 4]), 0.9)
        self.assertLess(cs.welch_p([1, 2, 1, 2, 1, 2], [9, 10, 9, 10, 9, 10]), 0.001)


class SessionDirTest(unittest.TestCase):
    def test_folder_is_stamped_and_tagged_safely(self):
        d = telemetry.session_dir("margins 24/14", when=0, root="R")
        base = os.path.basename(d)
        self.assertTrue(base.endswith("_margins_24_14"), base)
        self.assertEqual(len(base.split("_")[0]), 8)     # YYYYmmdd
        self.assertEqual(os.path.basename(telemetry.session_dir(None, when=0, root="R")).count("_"), 1)

    def test_report_carries_tag_config_and_knobs(self):
        from ..engine.clearance_planner import DXY
        with tempfile.TemporaryDirectory() as d:
            tel = telemetry.HardwareTelemetry(DXY, out_dir=d, tag="t1",
                                              config={"hz": 15}, knobs={"K": "1"})
            rep = tel.report()
        self.assertEqual(rep["tag"], "t1")
        self.assertEqual(rep["config"], {"hz": 15})
        self.assertEqual(rep["knobs"], {"K": "1"})


if __name__ == "__main__":
    unittest.main()
