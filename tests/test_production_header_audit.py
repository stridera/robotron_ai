import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import audit_production_headers as audit
from audit_production_decisions import death_events


class HeaderAuditTests(unittest.TestCase):
    def test_cap_keeps_completed_band_and_rejects_live_terminal_as_game_over(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            p=root/'logs/production_games/test_base_1'
            (p/'telemetry').mkdir(parents=True)
            record=dict(outcome='wave_cap', complete=True, cap=6, games=[], arm='test_base',
                        hud=dict(wave=7,score=60000,deaths=0,startup_verified=True))
            (p/'result.json').write_text(json.dumps(record))
            (p/'telemetry/report.json').write_text('{}')
            (p/'hud_samples.jsonl').write_text(json.dumps(dict(game='g'))+'\n')
            rows=[dict(wave=w,score=(w-1)*10000,lives=3+(w-1)*10000//25000) for w in range(1,8)]
            (p/'oracle_headers.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
            log=root/'hud.jsonl'
            log.write_text(''.join(json.dumps(dict(game='g',arm='test_base',wave=w,score=10000,deaths=0))+'\n' for w in range(1,7)))
            with patch.object(audit,'ROOT',root):
                self.assertEqual(len(audit.audit('test',log)['excluded']),1)
                report=audit.audit('test',log,include_wave_cap=True)
                self.assertTrue(report['games'][0]['censored'])
                self.assertEqual([r['wave'] for r in report['games'][0]['waves']],list(range(1,7)))
                self.assertEqual(report['arms']['test_base']['oracle']['waves'],2)
                record['outcome']='game_over'
                record['games']=[dict(game='g',wave=7,score=60000,deaths=0)]
                (p/'result.json').write_text(json.dumps(record))
                self.assertEqual(len(audit.audit('test',log,True)['excluded']),1)

    def test_startup_failure_has_no_death_events(self):
        self.assertEqual(death_events([]), [])

    def test_life_balance_cancels_wave_pulse_and_includes_terminal_death(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            game_dir = root / 'logs/production_games/test_base_1'
            (game_dir / 'telemetry').mkdir(parents=True)
            game = dict(game='g', wave=2, score=30000, deaths=5)
            (game_dir / 'result.json').write_text(json.dumps(dict(outcome='game_over', games=[game], arm='test_base')))
            (game_dir / 'telemetry/report.json').write_text('{}')
            values = [(1, 0, 3), (1, 10000, 2), (2, 10000, 3),
                      (2, 10000, 2), (2, 25000, 3), (2, 30000, 2),
                      (2, 30000, 1), (2, 30000, 0), (2, 30000, 0xffffffff)]
            (game_dir / 'oracle_headers.jsonl').write_text(''.join(json.dumps(dict(wave=w, score=s, lives=lv)) + '\n' for w, s, lv in values))
            log = root / 'hud.jsonl'
            log.write_text(''.join(json.dumps(dict(game='g', arm='test_base', wave=w, score=s, deaths=d)) + '\n' for w, s, d in [(1, 10000, 1), (2, 20000, 4)]))
            with patch.object(audit, 'ROOT', root):
                result = audit.audit('test', log)
            g = result['games'][0]
            self.assertEqual(g['oracle_balance_deaths'], 5)
            self.assertEqual(g['hud_death_error'], 0)
            self.assertEqual([w['oracle']['deaths'] for w in g['waves']], [1, 4])
            self.assertEqual(result['comparisons'], {})
            self.assertIsNone(result['arms']['test_base']['oracle']['net'])


if __name__ == '__main__':
    unittest.main()
