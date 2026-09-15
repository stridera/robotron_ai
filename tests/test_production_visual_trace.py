import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from robotron_ai.tools.production_visual_trace import VisualTrace, extract, observed_perceive


class VisualTraceTests(unittest.TestCase):
    def test_exact_inference_image_copied_and_observation_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image = np.full((40, 60, 3), 70, dtype=np.uint8)
            digest = hashlib.sha256(memoryview(image)).hexdigest()
            obs = SimpleNamespace(sampled_at=123., player=(3, 4))
            eye = SimpleNamespace(last_frame=image)
            trace = VisualTrace(root / 'visual')
            wrapped = observed_perceive(lambda e, state: obs, trace)
            self.assertIs(wrapped(eye, None), obs)
            image[:] = 200
            trace.close()
            row = json.loads((root / 'visual/frames.jsonl').read_text())
            self.assertEqual(row['raw_sha256'], digest)
            self.assertEqual(row['sampled_at'], 123.)
            self.assertEqual(extract(root / 'visual', row['t'], .1, .1, root / 'window'), 1)
            saved = cv2.imread(str(next((root / 'window').glob('*.jpg'))))
            self.assertLess(abs(float(saved.mean()) - 70), 1)
            self.assertIsNone(trace.summary['error'])
            self.assertFalse(trace.summary['writer_alive'])
            with self.assertRaises(FileExistsError):
                extract(root / 'visual', row['t'], .1, .1, root / 'window')

    def test_archive_cap_never_writes_partial_jpeg(self):
        with tempfile.TemporaryDirectory() as temp:
            trace = VisualTrace(Path(temp) / 'visual', max_bytes=1)
            trace.record(np.zeros((20, 20, 3), np.uint8), SimpleNamespace(sampled_at=1, player=None))
            trace.close()
            self.assertTrue(trace.summary['truncated'])
            self.assertEqual(trace.summary['written'], 0)
            self.assertEqual((trace.directory / 'frames.mjpg').stat().st_size, 0)

    def test_slow_encoder_drops_instead_of_blocking_inference(self):
        entered, release = threading.Event(), threading.Event()
        encode = cv2.imencode
        def slow(*args):
            entered.set()
            release.wait(2)
            return encode(*args)
        with tempfile.TemporaryDirectory() as temp, patch.object(cv2, 'imencode', side_effect=slow):
            trace = VisualTrace(Path(temp) / 'visual')
            frame = np.zeros((20, 20, 3), np.uint8)
            obs = SimpleNamespace(sampled_at=1, player=None)
            trace.record(frame, obs)
            self.assertTrue(entered.wait(1))
            try:
                for _ in range(10):
                    trace.record(frame, obs)
                self.assertEqual(trace.summary['dropped'], 6)
            finally:
                release.set()
                trace.close()
            self.assertEqual(trace.summary['written'], 5)

    def test_encoder_error_is_diagnostic_and_does_not_escape_to_policy(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(cv2, 'imencode', side_effect=OSError('disk diagnostic')):
            trace = VisualTrace(Path(temp) / 'visual')
            trace.record(np.zeros((20, 20, 3), np.uint8), SimpleNamespace(sampled_at=1, player=None))
            trace.close()
            self.assertIn('disk diagnostic', trace.summary['error'])


if __name__ == '__main__':
    unittest.main()
