"""Bounded unattended research queue. Run with the isolated WSL interpreter.

Screens independent mechanisms, confirms at most two positive candidates on
fresh seeds, then optionally runs one real-vision Xenia follow-up. Never promotes
settings. STOP in the night folder cancels the current stage and remaining queue.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT.parent / 'robotron'
RUNNER = ROOT / 'tools/run_collision_mame_fresh.py'
PLAN = [
    ('turn1', {'VSEARCH_TURN_STEPS': '1'}),
    ('turnguard', {'VSEARCH_TURN_STEPS': '2', 'VSEARCH_TURN_FIRE_GUARD': '1'}),
    ('turncommit', {'VSEARCH_TURN_STEPS': '2', 'VSEARCH_TURN_COMMIT': '1',
                    'VSEARCH_TURN_FIRE_GUARD': '1'}),
    ('shot2', {'VSEARCH_JOINT_SHOT': '1', 'VSEARCH_SHOT_DELAY': '2'}),
    ('shot4', {'VSEARCH_JOINT_SHOT': '1', 'VSEARCH_SHOT_DELAY': '4'}),
    ('fan12', {'VSEARCH_VELOCITY_FAN': '12'}),
    ('fan24', {'VSEARCH_VELOCITY_FAN': '24'}),
]


def atomic_json(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, indent=2), encoding='utf-8')
    tmp.replace(path)


def effect(report):
    if not report.get('complete') or len(report.get('arms', {})) != 2:
        return None
    if any(a['completed_valid_games'] != a['expected_games'] for a in report['arms'].values()):
        return None
    comparisons = report.get('comparisons_to_baseline', {})
    return next(iter(comparisons.values()), None)


def eligible(report, confirmation=False):
    result = effect(report)
    return bool(result and result['net_delta'] > .03
                and (not confirmation or result['bootstrap_95'][0] > 0))


def render(state):
    lines = ['# Overnight Robotron experiments — 2026-09-09', '',
             f"Status: **{state['status']}**. Updated {state['updated']}.", '',
             'Production settings remain unchanged. All MAME results below are W5–25',
             'proxy measurements; none establishes a late-Xenia or console improvement.', '',
             '| Stage | Candidate | Games/arm | NET change | Game-bootstrap 95% interval |',
             '|---|---|---:|---:|---|']
    for row in state['results']:
        result = effect(row.get('report', {}))
        if row['phase'] == 'smoke':
            continue
        if result:
            lo, hi = result['bootstrap_95']
            lines.append(f"| {row['phase']} | {row['name']} | {row['games']} | "
                         f"{result['net_delta']:+.4f} | [{lo:+.4f}, {hi:+.4f}] |")
        else:
            lines.append(f"| {row['phase']} | {row['name']} | {row['games']} | incomplete/error | see logs |")
    lines += ['', 'NET = score/25,000 minus deaths, aggregated over waves; games are the',
              'resampling unit. Higher is better. Screen selection requires NET > +0.03;',
              'independent 576-game confirmation also requires its interval above zero.',
              'Screens and confirmations use different ROM and defect seeds and are not pooled.',
              'At most two screen winners get confirmation; no automatic promotion occurs.', '']
    if state.get('xenia'):
        lines += [f"Xenia follow-up: {state['xenia'].get('status', 'running')}",
                  f"Run: `{state['xenia']['run']}`. See its band summaries and focus log.", '']
    if state.get('conclusion'):
        lines += [state['conclusion'], '']
    lines += [f"Detailed results, settings and stage logs: `{state['directory']}`.",
              'Experiment definitions: [OVERNIGHT_EXPERIMENTS.md](OVERNIGHT_EXPERIMENTS.md).', '']
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--name', default='night_20260909')
    ap.add_argument('--hours', type=float, default=6.5)
    ap.add_argument('--wait-for', type=Path)
    ap.add_argument('--xenia', action='store_true')
    args = ap.parse_args()
    import re
    if not re.fullmatch(r'[a-z0-9_]+', args.name) or not 0 < args.hours <= 8:
        ap.error('name must be lowercase alphanumeric/underscore; hours in (0,8]')
    out = ROOT / 'logs' / args.name
    out.mkdir(exist_ok=False)
    began = time.time()
    deadline = began + args.hours * 3600
    paths = [DEV / n for n in ('clearance_planner.py', 'robotron_fsm.py',
                               'mame_lab.py', 'fsm_evolved_planner_v2_hunt.json')]
    paths += [RUNNER, Path(__file__), ROOT / 'tools/analyze_collision_mame.py',
              ROOT / 'tools/run_collision_ab.ps1']
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    state = dict(status='starting', directory=str(out.relative_to(ROOT)),
                 started=began, deadline=deadline, linux_pid=os.getpid(), plan=PLAN,
                 source_hashes=hashes, results=[], xenia=None)
    interrupted = False

    def on_signal(*_):
        nonlocal interrupted
        interrupted = True
    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    def stopping():
        return interrupted or (out / 'STOP').exists() or time.time() >= deadline

    def save(status=None):
        if status:
            state['status'] = status
        state['updated'] = datetime.now(timezone.utc).isoformat()
        atomic_json(out / 'state.json', state)
        atomic_json(ROOT / 'logs/night_active.json',
                    {k: state[k] for k in ('status', 'directory', 'linux_pid', 'deadline', 'updated')})
        text = render(state)
        tmp = ROOT / 'NIGHT_REPORT.tmp'
        tmp.write_text(text, encoding='utf-8')
        tmp.replace(ROOT / 'NIGHT_REPORT.md')
        (out / 'report.md').write_text(text, encoding='utf-8')

    def check_source():
        for p in paths:
            if hashlib.sha256(p.read_bytes()).hexdigest() != hashes[str(p)]:
                raise RuntimeError(f'Source changed during overnight queue: {p}')

    counter = 0

    def stage(name, settings, phase, games):
        nonlocal counter
        if stopping():
            raise TimeoutError('Time budget or STOP request reached')
        check_source()
        counter += 1
        prefix = f'{args.name}_{phase}_{name}'
        stage_dir = ROOT / 'logs' / prefix
        command = [sys.executable, '-u', str(RUNNER), '--games', str(games),
                   '--workers', '4' if phase == 'smoke' else '12', '--prefix', prefix,
                   '--candidate-name', name, '--seed-base', str(50909001 + counter * 10000019)]
        for key, value in settings.items():
            command += ['--candidate-env', f'{key}={value}']
        save(f'{phase}: {name} ({games} games per arm)')
        log_path = out / f'{phase}_{name}.log'
        with log_path.open('w') as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
            while process.poll() is None:
                if stopping():
                    if stage_dir.exists():
                        (stage_dir / 'STOP').touch()
                    process.terminate()  # runner reaps its own game process groups
                time.sleep(2)
        report_path = stage_dir / 'summary.json'
        report = json.loads(report_path.read_text()) if report_path.exists() else {}
        row = dict(name=name, phase=phase, games=games, settings=settings,
                   run=prefix, exit_code=process.returncode, report=report)
        state['results'].append(row)
        save()
        if stopping():
            raise TimeoutError('Time budget or STOP request reached')
        return row

    save()
    try:
        if args.wait_for:
            save('waiting for the existing turning-path screen')
            while not (args.wait_for / 'summary.json').exists():
                if stopping():
                    raise TimeoutError('Stopped while waiting for existing screen')
                time.sleep(5)
            prior = json.loads((args.wait_for / 'summary.json').read_text())
            state['results'].append(dict(name='turn2', phase='prior screen', games=144,
                                         run=args.wait_for.name, settings={'VSEARCH_TURN_STEPS': '2'}, report=prior))
            save()
        screens = []
        ready = []
        for name, settings in PLAN:
            smoke = stage(name, settings, 'smoke', 2)
            if smoke['exit_code'] or not smoke['report'].get('complete'):
                save(f'smoke failed: {name}; skipping its full screen')
                continue
            ready.append((name, settings))
        for name, settings in ready:
            row = stage(name, settings, 'screen', 144)
            if row['exit_code'] == 0 and eligible(row['report']):
                screens.append(row)
        chosen = sorted(screens, key=lambda r: effect(r['report'])['net_delta'], reverse=True)[:2]
        confirmed = []
        for row in chosen:
            result = stage(row['name'], row['settings'], 'confirm', 576)
            if result['exit_code'] == 0 and eligible(result['report'], confirmation=True):
                confirmed.append(result)
        state['conclusion'] = ('No screen met the entry threshold for larger confirmation.' if not chosen
                               else 'No candidate passed the independent confirmation gate.' if not confirmed
                               else 'MAME-confirmed candidates: ' + ', '.join(r['name'] for r in confirmed)
                               + '. These still require real-vision and hardware validation.')
        save('MAME queue complete')
        if confirmed and args.xenia and deadline - time.time() >= 2.3 * 3600:
            check_source()
            winner = max(confirmed, key=lambda r: effect(r['report'])['net_delta'])
            run = f"{args.name}_xenia_{winner['name']}"
            xdir = ROOT / 'logs' / run
            hours = min(3, (deadline - time.time()) / 3600 - .1)
            ps_script = str(ROOT / 'tools/run_collision_ab.ps1').replace('/mnt/c/', 'C:/').replace('/', '\\')
            command = ['/mnt/c/Program Files/PowerShell/7/pwsh.exe', '-NoProfile', '-File', ps_script,
                       '-Games', '4', '-MaxWave', '40', '-Vision', '-RunName', run,
                       '-CandidateName', winner['name'], '-CandidateSettings',
                       ','.join(f'{k}={v}' for k, v in winner['settings'].items()),
                       '-MaxHours', str(round(hours, 3))]
            state['xenia'] = dict(run=run, candidate=winner['name'], status='running; four games per arm planned')
            save('real-vision Xenia follow-up')
            with (out / 'xenia.log').open('w') as log:
                process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
                while process.poll() is None:
                    if stopping() and xdir.exists():
                        (xdir / 'STOP').touch()
                    time.sleep(2)
            status = xdir / 'status.txt'
            state['xenia']['status'] = status.read_text(encoding='utf-8-sig').strip() if status.exists() else 'launcher failed; see xenia.log'
            state['xenia']['exit_code'] = process.returncode
        failed = [r for r in state['results'] if r['phase'] != 'prior screen'
                  and (r.get('exit_code') or not r['report'].get('complete'))]
        if failed:
            state['conclusion'] = (f"{len(failed)} stages were incomplete or failed; "
                                   "failure to evaluate is not evidence of no improvement. "
                                   + state.get('conclusion', ''))
            save('queue ended with incomplete stages; diagnosis required')
        else:
            save('finished; results ready for review')
    except TimeoutError as exc:
        state['conclusion'] = str(exc) + '. Completed stages are preserved; unfinished stages are not wins.'
        save('stopped at time budget or operator request')
    except Exception as exc:
        state['conclusion'] = f'Queue stopped on error: {type(exc).__name__}: {exc}'
        save('stopped on error; inspect stage logs')
        raise


if __name__ == '__main__':
    main()
