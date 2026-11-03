"""tools/mamelab without MAME: ab_stats on a synthetic results dir, run_ab's
KEY=VALUE routing and labpaths overrides.

Run from the package's parent directory:
    python -m unittest robotron_ai.tests.test_mamelab -v
"""
import contextlib
import importlib
import io
import json
import os
import signal
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1] / "tools"
MAMELAB = TOOLS / "mamelab"


def _import(name):
    for p in (str(MAMELAB), str(TOOLS)):
        if p not in sys.path:
            sys.path.insert(0, p)
    return importlib.import_module(name)


def _episode(arm, port, wave, d=1, score=60000):
    return dict(game=f"{arm}-{port}-1", wave=wave, n=20, d=d * 20, s=score * 20)


class AbStatsTest(unittest.TestCase):
    def test_synthetic_results_dir(self):
        ab = _import("ab_stats")
        ana = _import("analyze_collision_mame")
        base = 23000
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "t1"
            out.mkdir()
            man = dict(names=["a", "b"], prefix="t1", port_base=base)
            (out / "manifest.json").write_text(json.dumps(man))
            arms = {
                "t1_a": [_episode("t1_a", base + t, 10 + t % 3) for t in range(8)],
                "t1_b": [_episode("t1_b", base + 2000 + t, 14 + t % 3, d=1) for t in range(8)],
            }
            fake_load = mock.Mock(return_value=(arms, {}))
            with mock.patch.object(ab, "load", fake_load):
                js = out / "o.json"
                buf = io.StringIO()
                with mock.patch.object(sys, "argv", ["ab_stats", str(out), "--boot", "200", "--json", str(js)]), \
                        contextlib.redirect_stdout(buf):
                    ab.main()
            rep = json.loads(js.read_text())
            self.assertEqual(rep["paired_trials"], 8)
            self.assertAlmostEqual(rep["paired_diff_B_minus_A"]["wave"]["diff"], 4.0)
            self.assertAlmostEqual(rep["arms"]["a"]["mean_wave"], sum(10 + t % 3 for t in range(8)) / 8)
            self.assertEqual(rep["per_trial_wave"]["B_wins"], 8)
            self.assertIn("B-A", buf.getvalue())
            self.assertTrue(callable(ana.load))


class RunAbTest(unittest.TestCase):
    def test_kv_routing(self):
        ra = _import("run_ab")
        import argparse
        ap = argparse.ArgumentParser()
        self.assertEqual(ra.kv(ap, ["VSEARCH_FIRE_ALT=0", "LAB_DROP=0.05"]),
                         {"VSEARCH_FIRE_ALT": "0", "LAB_DROP": "0.05"})
        self.assertEqual(ra.kv(ap, None), {})
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            ra.kv(ap, ["PATH=/x"])

    def test_help_and_defaults(self):
        ra = _import("run_ab")
        buf = io.StringIO()
        saved = signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)   # main() replaces them
        self.addCleanup(lambda: (signal.signal(signal.SIGTERM, saved[0]), signal.signal(signal.SIGINT, saved[1])))
        with mock.patch.object(sys, "argv", ["run_ab", "--help"]), contextlib.redirect_stdout(buf), \
                self.assertRaises(SystemExit) as cm:
            ra.main()
        self.assertEqual(cm.exception.code, 0)
        self.assertIn("--checkout-b", buf.getvalue())
        self.assertIn("--port-base", buf.getvalue())


class LabPathsTest(unittest.TestCase):
    def test_env_overrides(self):
        lp = _import("labpaths")
        try:
            with mock.patch.dict(os.environ, {"MAMELAB_RL": "/x/rl", "MAMELAB_RESULTS": "/x/res"}):
                lp = importlib.reload(lp)
                self.assertEqual(lp.RL, Path("/x/rl"))
                self.assertEqual(lp.RESULTS, Path("/x/res"))
                self.assertEqual(lp.DEV, Path("~/Code/robotron").expanduser())
        finally:
            importlib.reload(lp)
        self.assertEqual(lp.RESULTS, Path("~/Code/robotron_data/mamelab/results").expanduser())
        self.assertTrue((lp.REPO / "brain.py").exists())


if __name__ == "__main__":
    unittest.main()
