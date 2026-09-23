"""The HUD bookkeeper's game-over death figures.

Run from the package's parent directory:
    python -m unittest robotron_ai.tests.test_hud_bookkeeper -v
"""
import unittest

from .. import hud_ocr


def _play(bk, t0=1000.0):
    """Feed a short game, then a long HUD-less stretch that ends it."""
    t = t0
    def feed(score, wave, lives, dt=0.2, visible=True):
        nonlocal t
        t += dt
        bk.feed(dict(score=score, wave=wave, lives=lives, conf=0.95), t=t,
                player_visible=visible)
    for _ in range(6):
        feed(500, 1, 3)
    for i in range(30):
        feed(1000 + i * 100, 2, 3)
    for i in range(60):
        t += 0.2
        bk.feed(dict(score=None, wave=None, lives=None, conf=0.0), t=t,
                player_visible=False)
    return t


class LifeEconomyTest(unittest.TestCase):
    def test_lives_bought_is_three_plus_one_per_25k(self):
        bk = hud_ocr.VisionBookkeeper()
        bk.max_score = 934725                # round-18 game 1
        self.assertEqual(bk.lives_bought(), 40)
        bk.max_score = 24975
        self.assertEqual(bk.lives_bought(), 3)
        bk.max_score = 25000
        self.assertEqual(bk.lives_bought(), 4)

    def test_game_over_reports_both_death_figures(self):
        """Round 18, game 1: the HUD saw 17 of 40 deaths because the icon row
        shows at most ~8 men and the bot had banked more than that from
        wave 9 to wave 28. The economy figure has to travel with the event
        so the console line and the telemetry carry the true total."""
        events = []
        bk = hud_ocr.VisionBookkeeper(on_event=lambda kind, **kw: events.append((kind, kw)))
        _play(bk)
        go = [kw for kind, kw in events if kind == 'game_over']
        self.assertEqual(len(go), 1)
        self.assertIn('lives_bought', go[0])
        self.assertEqual(go[0]['lives_bought'], 3)      # score stayed under 25k
        self.assertEqual(go[0]['score'], bk.max_score)

    def test_telemetry_keeps_the_economy_figure(self):
        from .. import telemetry
        rec = []
        class T:
            games = rec
            game_over = telemetry.HardwareTelemetry.game_over
        T.game_over(T, game='g', wave=37, score=934725, deaths=17, lives_bought=40)
        self.assertEqual(rec[0]['lives_bought'], 40)
        self.assertEqual(rec[0]['deaths'], 17)


if __name__ == "__main__":
    unittest.main()
