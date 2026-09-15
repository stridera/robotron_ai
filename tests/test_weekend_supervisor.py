import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import weekend_supervisor as w


class WeekendTests(unittest.TestCase):
    def fixture(self, root, *, missing=False, mismatch=False):
        job = dict(id='test_job', kind='xenia', games=1, max_wave=40,
                   candidate='timed', settings='ROBOTRON_TRACK_TIME=1', max_hours=1)
        run = root / 'logs/test_job'
        run.mkdir(parents=True)
        (run / 'status.txt').write_text('harness finished; check counts', encoding='utf-8')
        for arm in ['base'] if missing else ['base', 'timed']:
            p = root / ('logs/production_games/test_job_' + arm + '_123')
            p.mkdir(parents=True)
            w.save_json(p / 'result.json', dict(complete=True, arm='test_job_' + arm,
                outcome='game_over', games=[dict(wave=18, score=400000)]))
            (p / 'oracle_headers.jsonl').write_text(json.dumps(dict(wave=18,
                score=400025 if mismatch else 400000)) + '\n', encoding='utf-8')
        return job

    def test_complete_requires_both_arms_and_audit(self):
        for missing, mismatch, expected in [(False, False, True), (True, False, False), (False, True, False)]:
            with self.subTest(missing=missing, mismatch=mismatch), tempfile.TemporaryDirectory() as d:
                root = Path(d)
                job = self.fixture(root, missing=missing, mismatch=mismatch)
                with patch.object(w, 'ROOT', root):
                    self.assertEqual(w.summarize_xenia(job)['complete'], expected)

    def test_review_cooldown_without_inferred_account_quota(self):
        now = 100000
        state = dict(reviews=[], next_review=now + 1)
        self.assertFalse(w.reviews_allowed(state, now))
        state['next_review'] = 0
        self.assertTrue(w.reviews_allowed(state, now))
        state['reviews'] = [dict(started=now - 1)] * 6
        self.assertTrue(w.reviews_allowed(state, now))
        state['reviews'] = [dict(started=now - 1, uncached_and_output_tokens=150000)]
        self.assertTrue(w.reviews_allowed(state, now))
        self.assertTrue(w.reviews_allowed(state, now + 86401))

    def test_invalid_job_paths_are_rejected(self):
        with self.assertRaises(ValueError):
            w.validate_job(dict(id='../outside'))

    def test_finished_batch_reaps_only_identified_owned_children(self):
        job = dict(pid=1, created=1, owned=[dict(pid=2, created=2), dict(pid=3, created=3)])
        orphan = Mock()
        def lookup(identity):
            return orphan if identity['pid'] == 2 else None
        with patch.object(w, 'live', side_effect=lookup), patch.object(w.psutil, 'wait_procs') as wait:
            w.cleanup_finished_children(job)
        orphan.kill.assert_called_once()
        wait.assert_called_once_with([orphan], timeout=2)

    def test_running_batch_children_are_never_reaped(self):
        active = Mock()
        with patch.object(w, 'live', return_value=active), patch.object(w.psutil, 'wait_procs') as wait:
            w.cleanup_finished_children(dict(pid=1, created=1, owned=[dict(pid=2, created=2)]))
        active.kill.assert_not_called()
        wait.assert_not_called()

    def test_existing_review_does_not_launch_another_job(self):
        state = dict(job=dict(id='review_test', pid=1, created=1, kind='review',
                             deadline=w.DEADLINE, owned=[]), results=[], reviews=[])
        class Fake:
            def children(self, recursive): return []
        with patch.object(w, 'live', return_value=Fake()), patch.object(w, 'save'), \
             patch.object(w, 'launch') as launch, patch.object(w.time, 'time', return_value=w.DEADLINE - 100):
            self.assertTrue(w.tick(state))
            launch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
