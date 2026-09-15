"""Offline replay of the startup W71 failure and genuine HUD cap crossing."""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from robotron_ai.hud_ocr import VisionBookkeeper
from robotron_ai.tools.run_production_game import capped_bookkeeper, WaveCapReached, completed_outcome, StartupARecovery


class ProductionCapTests(unittest.TestCase):
    def test_startup_retry_is_bounded_and_latches_off_on_acquisition(self):
        presses = []
        recovery = StartupARecovery(lambda: presses.append(1))
        for t in (0, 4.9, 5, 5.1, 10):
            with patch('robotron_ai.tools.run_production_game.time.monotonic', return_value=t):
                recovery.update({})
        self.assertEqual(len(presses), 2)
        recovery.update({'startup_acquired': True})
        for t in (15, 9999):
            with patch('robotron_ai.tools.run_production_game.time.monotonic', return_value=t):
                recovery.update({})
        self.assertEqual(len(presses), 2)
        self.assertTrue(recovery.disabled)

    def test_startup_retry_does_not_extend_guard_or_press_after_progress(self):
        presses = []
        recovery = StartupARecovery(lambda: presses.append(1))
        book = capped_bookkeeper(VisionBookkeeper, 40, {}, startup_recovery=recovery)()
        for t in range(181):
            with patch('robotron_ai.tools.run_production_game.time.monotonic', return_value=t):
                book.feed(dict(wave=71, score=None, lives=None), t=t)
        self.assertEqual(len(presses), 30)
        with patch('robotron_ai.tools.run_production_game.time.monotonic', return_value=181):
            with self.assertRaisesRegex(RuntimeError, 'startup failed'):
                book.feed(dict(wave=71, score=None, lives=None), t=181)
        self.assertEqual(len(presses), 30)

    def make(self):
        self.last = {}
        return capped_bookkeeper(VisionBookkeeper, 40, self.last)()

    def feed(self, book, wave, score, t=100):
        for i in range(3):
            book.feed(dict(wave=wave, score=score, lives=None), t=t + i)

    def test_startup_71_is_not_completion_and_guard_stays_active(self):
        book = self.make()
        with patch('robotron_ai.tools.run_production_game.time.monotonic', return_value=0):
            self.feed(book, 71, None)
            self.feed(book, 71, 100)
        self.assertFalse(self.last['startup_verified'])
        with patch('robotron_ai.tools.run_production_game.time.monotonic', return_value=181):
            with self.assertRaisesRegex(RuntimeError, 'startup failed'):
                self.feed(book, 71, None)

    def test_real_crossing_logs_cap_wave(self):
        events = []
        book = self.make()
        book.on_event = lambda kind, **kw: events.append((kind, kw))
        self.feed(book, 1, 0)
        self.feed(book, 2, 5000)
        self.feed(book, 20, 25000)
        self.feed(book, 40, 50000)
        with self.assertRaises(WaveCapReached):
            self.feed(book, 41, 75000)
        self.assertTrue(any(k == 'wave_end' and r['wave'] == 40 for k, r in events))

    def test_intro_then_real_start_does_not_emit_phantom_game_over(self):
        events, samples = [], []
        book = capped_bookkeeper(VisionBookkeeper, 40, {}, samples.append)(
            on_event=lambda kind, **kw: events.append(kind))
        self.feed(book, 71, None)
        self.feed(book, 1, 0)
        self.feed(book, 1, 1000)
        self.feed(book, 2, 5000)
        self.assertNotIn('game_over', events)
        self.assertTrue(book.startup_verified)
        self.assertEqual(samples[0]['reading']['wave'], 71)
        self.assertIsNone(samples[0]['accepted']['wave'])

    def test_no_midgame_watchdog(self):
        book = self.make()
        with patch('robotron_ai.tools.run_production_game.time.monotonic', return_value=0):
            self.feed(book, 1, 0)
            self.feed(book, 2, 5000)
        with patch('robotron_ai.tools.run_production_game.time.monotonic', return_value=9999):
            self.feed(book, None, None)
        self.assertTrue(self.last['startup_verified'])

    def test_below_cap_intro_with_zero_score_cannot_mint_game(self):
        events = []
        book = self.make()
        book.on_event = lambda kind, **kw: events.append(kind)
        self.feed(book, 11, 0)
        self.assertIsNone(book.wave)
        self.assertIsNone(book.lives)
        self.feed(book, 1, 400)
        self.feed(book, 2, 4500)
        self.assertTrue(book.startup_verified)
        self.assertNotIn('game_over', events)
        self.assertEqual(book.max_wave, 2)

    def test_intro_positive_score_does_not_disable_startup_guard(self):
        book = self.make()
        with patch('robotron_ai.tools.run_production_game.time.monotonic', return_value=0):
            self.feed(book, 11, 500)
        with patch('robotron_ai.tools.run_production_game.time.monotonic', return_value=181):
            with self.assertRaisesRegex(RuntimeError, 'startup failed'):
                self.feed(book, 11, 500)

    def test_ambiguous_or_unverified_game_forces_incomplete(self):
        for games, hud in [([], {'startup_verified': True}),
                           ([{}, {}], {'startup_verified': True}), ([{}], {})]:
            self.assertEqual(completed_outcome('game_over', games, hud), 'incomplete')
        self.assertEqual(completed_outcome('game_over', [{}], {'startup_verified': True}), 'game_over')


if __name__ == '__main__':
    unittest.main()
