"""Engine knob plumbing: --knob / config "knobs" reach the environment before
the engine is imported, and a session records what was in force.

Run from the package's parent directory:
    python -m unittest robotron_ai.tests.test_knobs -v
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

from .. import knobs


class PreloadTest(unittest.TestCase):
    def test_knob_flags_and_config_block_land_in_the_environment(self):
        env = {}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.json")
            with open(path, "w") as f:
                json.dump({"hz": 15, "knobs": {"VSEARCH_CLEAR_DANGER": 24,
                                               "FSM_HUNT": "2"}}, f)
            applied = knobs.preload(["--mode", "hardware", "--config", path,
                                     "--knob", "VSEARCH_CLEAR_MARGIN=14",
                                     "--knob=FSM_HUNT=3"], environ=env)
        self.assertEqual(env["VSEARCH_CLEAR_DANGER"], "24")
        self.assertEqual(env["VSEARCH_CLEAR_MARGIN"], "14")
        self.assertEqual(env["FSM_HUNT"], "3")          # --knob beats the config block
        self.assertEqual(list(applied), ["VSEARCH_CLEAR_DANGER", "FSM_HUNT", "VSEARCH_CLEAR_MARGIN"])

    def test_non_knob_names_are_refused(self):
        with self.assertRaises(ValueError):
            knobs.parse_pair("PATH=/tmp")
        with self.assertRaises(ValueError):
            knobs.parse_pair("VSEARCH_H")
        self.assertEqual(knobs.parse_pair("vsearch_h = 7"), ("VSEARCH_H", "7"))

    def test_effective_values_follow_the_brain_rules(self):
        """Pinning one margin switches the vision margins off for BOTH (that is
        what brain.py does), fire-alt radius 400 applies only while
        VSEARCH_FIRE_ALT is unpinned, and unregistered knobs are carried."""
        env = {"VSEARCH_CLEAR_DANGER": "24", "FSM_SOMETHING_NEW": "1", "ROBOTRON_ARM": "x"}
        vals = knobs.current_values(env, vision=True)
        self.assertEqual(vals["VSEARCH_CLEAR_DANGER"], "24")
        self.assertEqual(vals["VSEARCH_CLEAR_MARGIN"], "10")      # engine default, not 12
        self.assertEqual(vals["VSEARCH_FIRE_ALT_R"], "400")
        self.assertEqual(vals["FSM_SOMETHING_NEW"], "1")
        self.assertNotIn("ROBOTRON_ARM", vals)
        clean = knobs.current_values({}, vision=True)
        self.assertEqual((clean["VSEARCH_CLEAR_DANGER"], clean["VSEARCH_CLEAR_MARGIN"]), ("21", "12"))
        self.assertEqual(clean["VSEARCH_FIRE_ALT"], "1")
        alt = knobs.current_values({"VSEARCH_FIRE_ALT": "1"}, vision=True)
        self.assertEqual(alt["VSEARCH_FIRE_ALT_R"], "160")        # the trap the table warns about
        mem = knobs.current_values({}, vision=False)
        self.assertEqual(mem["VSEARCH_CLEAR_DANGER"], "18")

    def test_brain_seeded_values_do_not_count_as_pinned(self):
        env = {"VSEARCH_ASMDYN": "1", "VSEARCH_H": "6", "VSEARCH_CLEAR_DANGER": "18",
               "VSEARCH_CLEAR_MARGIN": "10", "FSM_RESCUE_SEEK": "1", "FSM_HUNT": "2"}
        self.assertEqual(knobs.pinned(env, applied={}), {"FSM_HUNT"})
        env["VSEARCH_H"] = "8"
        self.assertEqual(knobs.pinned(env, applied={}), {"FSM_HUNT", "VSEARCH_H"})

    def test_describe_marks_pinned_and_shows_vision_values(self):
        text = knobs.describe({}, vision=True)
        line = next(l for l in text.splitlines() if l.startswith("VSEARCH_CLEAR_MARGIN"))
        self.assertIn(" 12 ", line)                              # vision default, not pinned
        text = knobs.describe({"VSEARCH_CLEAR_DANGER": "24"}, vision=True)
        line = next(l for l in text.splitlines() if l.startswith("VSEARCH_CLEAR_DANGER"))
        self.assertIn("24*", line)
        line = next(l for l in text.splitlines() if l.startswith("VSEARCH_CLEAR_MARGIN"))
        self.assertIn(" 10 ", line)                              # other margin falls back

    def test_registry_defaults_match_the_engine(self):
        """The table must not drift from what the engine actually reads."""
        import re
        pkg = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        src = ""
        for name in ("engine/clearance_planner.py", "engine/robotron_fsm.py"):
            with open(os.path.join(pkg, name), encoding="utf-8") as f:
                src += f.read()
        found = dict(re.findall(r"environ\.get\(['\"]([A-Z_0-9]+)['\"],\s*['\"]([^'\"]*)['\"]", src))
        for k, (default, _) in knobs.REGISTRY.items():
            self.assertIn(k, found, k)
            self.assertEqual(found[k], default, k)


class EndToEndTest(unittest.TestCase):
    def test_knob_is_visible_to_the_engine_at_import(self):
        """The whole point: a --knob must be in force when the planner module
        reads the environment. Run the real entry point in a subprocess."""
        code = ("import sys; sys.argv=['x','--knob','VSEARCH_CLEAR_DANGER=24'];"
                "from robotron_ai.knobs import preload; preload(sys.argv[1:]);"
                "from robotron_ai.engine import clearance_planner as cp;"
                "print(cp.CLEAR_DANGER)")
        pkgroot = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                             cwd=pkgroot, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr[-800:])
        self.assertEqual(out.stdout.strip().splitlines()[-1], "24.0")


if __name__ == "__main__":
    unittest.main()
