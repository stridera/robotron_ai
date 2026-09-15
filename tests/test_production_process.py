"""Exercise real process exit, post-result hangs, and the gameplay timeout."""
import os
from pathlib import Path
import sys
import tempfile
import subprocess
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from robotron_ai.tools.production_process import run_completed_process, ShutdownTimeout


class ProductionProcessTests(unittest.TestCase):
    def run_child(self, source, timeout=5, grace=.5):
        marker = Path(self.temp.name) / 'completed.json'
        return run_completed_process([sys.executable, '-c', source],
            env=os.environ, cwd=self.temp.name, timeout=timeout,
            marker=marker, shutdown_timeout=grace)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_normal_exit(self):
        self.assertEqual(self.run_child('pass').returncode, 0)

    def test_nonzero_exit_preserved(self):
        self.assertEqual(self.run_child('raise SystemExit(7)').returncode, 7)

    def test_saved_result_hang_is_not_success(self):
        with self.assertRaises(ShutdownTimeout):
            self.run_child("import os,pathlib,time; pathlib.Path(os.environ['ROBOTRON_COMPLETION_MARKER']).write_text('{}'); time.sleep(30)")
        self.assertTrue((Path(self.temp.name) / 'completed.shutdown_error.json').exists())

    def test_no_completion_marker_uses_game_timeout(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            self.run_child('import time; time.sleep(30)', timeout=.75)
        self.assertFalse((Path(self.temp.name) / 'completed.shutdown_error.json').exists())


if __name__ == '__main__':
    unittest.main()
