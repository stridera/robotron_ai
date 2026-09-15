"""One production hardware-sim game, with HUD wave cap and isolated telemetry.

Uses the real production vision/controller loop. No memory feeds the decisions.
The outer A/B supervisor owns focus and process lifetimes.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))


class WaveCapReached(Exception):
    pass


class StartupARecovery:
    """Bounded A-only navigation before HUD acquisition, never after it."""
    def __init__(self, press_a, observe=None):
        self.press_a = press_a
        self.observe = observe
        self.began = self.last_press = None
        self.disabled = False
        self.presses = 0

    def update(self, hud):
        if hud.get('startup_acquired') or hud.get('startup_verified'):
            self.disabled = True
        if self.disabled:
            return
        now = time.monotonic()
        if self.began is None:
            self.began = self.last_press = now
        # Initial navigation already sent A three times. Retry that safe path
        # if intro art falsely satisfied its player/HUD sense. Do not reset
        # the independent 180-second startup deadline or escalate to Start/B.
        if now - self.last_press < 5 or now - self.began >= 180 or self.presses >= 30:
            return
        self.last_press = now
        self.press_a()
        self.presses += 1
        if self.observe is not None:
            self.observe(dict(t=time.time(), elapsed=now-self.began,
                              action='press_a', press=self.presses))


def capped_bookkeeper(original, cap, last_hud, observe=None, startup_recovery=None):
    """Test-rig limits from HUD only; a startup digit is not a cap crossing."""
    class CappedBookkeeper(original):
        startup_began = None
        startup_verified = False
        startup_acquired = False

        def feed(self, *a, **kw):
            previous_wave = self.wave
            reading = a[0] if a else kw.get('reading')
            filtered = reading
            if not self.startup_acquired:
                # Every isolated run starts cold. Intro art can read W11/S0,
                # not only a digit above the cap. Require stable W1 with a
                # small score before admitting other waves or lives.
                if (reading.get('wave') != 1 or
                        (reading.get('score') is not None and
                         not 0 <= reading['score'] < 10000)):
                    filtered = dict(reading, wave=None, score=None, lives=None)
            elif (not self.startup_verified and reading.get('wave') is not None
                    and reading['wave'] > (cap or 100)):
                # Keep intro/menu digits out of the underlying bookkeeper too:
                # otherwise its later W1 reset can emit a phantom game_over.
                filtered = dict(reading, wave=None)
            if filtered is not reading:
                if a:
                    a = (filtered, *a[1:])
                else:
                    kw = dict(kw, reading=filtered)
            result = super().feed(*a, **kw)
            if self.wave == 1 and self.score is not None and 0 <= self.score < 10000:
                self.startup_acquired = True
            if self.startup_began is None:
                self.startup_began = time.monotonic()
            if self.wave is not None and 2 <= self.wave <= (cap or 100) and (self.score or 0) > 0:
                self.startup_verified = True
            last_hud.update(wave=self.wave, score=self.score, deaths=self.deaths,
                            startup_acquired=self.startup_acquired,
                            startup_verified=self.startup_verified)
            if observe is not None:
                observe(dict(t=time.time(), reading=reading,
                             accepted=result, game=self.game_id,
                             player_visible=kw.get('player_visible')))
            # Startup only: never interrupt a progressed game on a watchdog.
            if not self.startup_verified and time.monotonic() - self.startup_began > 180:
                raise RuntimeError('Production startup failed: no HUD-confirmed wave progress in 180 seconds')
            if startup_recovery is not None:
                startup_recovery.update(last_hud)
            if (cap and self.startup_verified and previous_wave is not None
                    and 1 <= previous_wave <= cap and self.wave is not None and self.wave > cap):
                print(f'[production] MAX_WAVE {cap} exceeded: W{self.wave} S{self.score}', flush=True)
                raise WaveCapReached()
            return result
    return CappedBookkeeper


def completed_outcome(outcome, games, last_hud):
    """Ambiguous telemetry must force review, even if its last game looks valid."""
    if outcome == 'game_over' and (len(games) != 1 or not last_hud.get('startup_verified')):
        return 'incomplete'
    return outcome


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--weights', required=True)
    ap.add_argument('--conf', default='0.30')
    args = ap.parse_args()
    from robotron_ai import cli, hud_ocr, telemetry, control, harness, perception
    from robotron_ai.tools.production_decision_trace import DecisionTrace
    arm = os.environ.get('ROBOTRON_ARM', 'production')
    # Common evaluation-only diagnostics for both arms; no policy settings.
    os.environ.setdefault('ROBOTRON_TRANSITION_DIAGNOSTICS', '1')
    out = ROOT / 'logs' / 'production_games' / f'{arm}_{int(time.time())}'
    out.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(ROOT.parent / 'robotron'))
    from brain3 import _focus_xenia_window
    if not _focus_xenia_window():
        raise RuntimeError('Xenia did not acquire verified foreground ownership')
    stop = threading.Event()
    def audit_headers():
        # Independent read-only bookkeeping; no reference to this reader or its
        # snapshots is passed to perception, the brain, or the controller.
        try:
            from robotron_ai.engine.game_state import GameStateReader
            reader = GameStateReader()
            with (out / 'oracle_headers.jsonl').open('w') as log:
                while not stop.is_set():
                    state = reader.read(wait_new_frame=False)
                    if state is not None:
                        log.write(json.dumps(dict(t=time.time(), wave=state.wave, score=state.score,
                                  lives=state.lives, px=state.player_gx, py=state.player_gy)) + '\n')
                        log.flush()
                    stop.wait(.05)
        except Exception as error:
            (out / 'oracle_error.txt').write_text(repr(error))
    auditor = threading.Thread(target=audit_headers, daemon=True)
    auditor.start()
    telemetry.DEFAULT_DIR = str(out / 'telemetry')
    cap = int(os.environ.get('ROBOTRON_MAX_WAVE', '0'))
    original = hud_ocr.VisionBookkeeper
    last_hud = {}
    controllers = []
    startup_log = (out / 'startup_actions.jsonl').open('w', encoding='utf-8')
    recovery = StartupARecovery(lambda: controllers[0].press_a(),
        lambda row: (startup_log.write(json.dumps(row) + '\n'), startup_log.flush()))
    hud_samples = (out / 'hud_samples.jsonl').open('w', encoding='utf-8')
    hud_ocr.VisionBookkeeper = capped_bookkeeper(original, cap, last_hud,
        lambda row: hud_samples.write(json.dumps(row) + '\n'), recovery)
    # A missing pad must fail the test, never silently create a simulated run.
    pad_class = control.VgamepadController
    class RequiredPad(pad_class):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            if self.pad is None:
                raise RuntimeError('Production test needs a working virtual gamepad')
            controllers.append(self)
    control.VgamepadController = RequiredPad
    outcome = 'error'
    trace = DecisionTrace(out)
    visual_trace = None
    original_perceive = perception.VisionPerception.perceive
    if os.environ.get('ROBOTRON_VISUAL_DIAGNOSTICS', '0') == '1':
        from robotron_ai.tools.production_visual_trace import VisualTrace, observed_perceive
        visual_trace = VisualTrace(out / 'visual')
        perception.VisionPerception.perceive = observed_perceive(original_perceive, visual_trace)
    original_play = harness.play_vision_game
    def observed_play(brain, eye, controller, **kwargs):
        try:
            return original_play(brain, eye, controller, decision_observer=trace.record, **kwargs)
        finally:
            # Finish inference before closing its diagnostic sinks or finalizing
            # Python/CUDA. The production CLI otherwise leaves this daemon live.
            if isinstance(eye, perception.ThreadedVisionPerception):
                eye.stop()
                eye._thread.join(timeout=5)
                if eye._thread.is_alive():
                    raise RuntimeError('Inference thread did not stop after gameplay')
    harness.play_vision_game = observed_play
    try:
        cli.main(['--mode', 'hardware', '--source', 'window', '--output', 'vgamepad',
                  '--input', 'yolo', '--loop', '--games', '1', '--eye-sync', '55',
                  '--hold-action', '4', '--weights', args.weights, '--conf', args.conf,
                  '--lag-ticks', os.environ.get('ROBOTRON_YOLO_LAG_TICKS', '.7'),
                  '--player-lead', os.environ.get('ROBOTRON_PLAYER_LEAD_TICKS', '1.5'),
                  '--hud-log', str(ROOT.parent / 'robotron/logs/yolo_waves.jsonl')])
        outcome = 'game_over'
    except WaveCapReached:
        outcome = 'wave_cap'
    finally:
        harness.play_vision_game = original_play
        perception.VisionPerception.perceive = original_perceive
        hud_ocr.VisionBookkeeper = original
        control.VgamepadController = pad_class
        for controller in controllers:
            controller.close()
            controller.pad = None
        controllers.clear()
        if visual_trace is not None:
            visual_trace.close()
        trace.close()
        startup_log.close()
        hud_samples.close()
        stop.set()
        auditor.join(timeout=2)
        report_path = out / 'telemetry/report.json'
        games = json.loads(report_path.read_text(encoding='utf-8')).get('games', []) if report_path.exists() else []
        outcome = completed_outcome(outcome, games, last_hud)
        (out / 'result.json').write_text(json.dumps(dict(arm=arm, outcome=outcome,
            complete=outcome in ('game_over', 'wave_cap'), cap=cap,
            hud=last_hud, games=games, ended=time.time()), indent=2), encoding='utf-8')
        # This marker is private to the parent process, and signals only that
        # gameplay and result writing ended, not that shutdown succeeded.
        marker = os.environ.get('ROBOTRON_COMPLETION_MARKER')
        if marker:
            path = Path(marker)
            temp = path.with_suffix('.tmp')
            temp.write_text(json.dumps(dict(result=str(out / 'result.json'))), encoding='utf-8')
            temp.replace(path)
        import faulthandler
        # Keep the file alive during interpreter finalization for a native hang.
        global _shutdown_trace
        _shutdown_trace = (out / 'shutdown_trace.txt').open('w', encoding='utf-8')
        faulthandler.dump_traceback_later(10, repeat=True, file=_shutdown_trace)


if __name__ == '__main__':
    main()
