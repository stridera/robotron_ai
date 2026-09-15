from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'robotron'))
import ab_yolo


class ProductionRestartTests(unittest.TestCase):
    def run_batch(self, production):
        args = SimpleNamespace(arm=['base=', 'timed=ROBOTRON_TRACK_TIME=1'],
                               games=1, production=production, conf=.3,
                               weights='weights.pt', timeout=3600)
        events = []
        def execute(cmd, **kwargs):
            events.append('stop' if cmd[0] == 'taskkill' else 'play')
            return SimpleNamespace(returncode=0)
        with patch.object(ab_yolo, 'ensure_xenia', side_effect=lambda: events.append('start') or True), \
             patch.object(ab_yolo, 'ensure_player', return_value=True), \
             patch.object(ab_yolo, 'xenia_alive', return_value=False), \
             patch.object(ab_yolo, '_max_wave_logged', return_value=18), \
             patch.object(ab_yolo.subprocess, 'run', side_effect=execute), \
             patch.object(ab_yolo, 'run_production_process', side_effect=execute), \
             patch.object(ab_yolo.time, 'sleep'), \
             patch.dict(ab_yolo.os.environ, {'ROBOTRON_MAX_WAVE': '40'}):
            ab_yolo.run(args)
        return events

    def test_normal_production_game_over_restarts_before_next_game(self):
        self.assertEqual(self.run_batch(True), ['start', 'play', 'stop', 'start', 'play', 'stop'])

    def test_development_lifecycle_unchanged_below_cap(self):
        self.assertEqual(self.run_batch(False), ['start', 'play', 'start', 'play'])


if __name__ == '__main__':
    unittest.main()
