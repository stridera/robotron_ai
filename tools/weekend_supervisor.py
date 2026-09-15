"""Persistent weekend queue with bounded, non-overlapping Codex reviews."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import psutil

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'logs/weekend_20260912'
DEADLINE = datetime.fromisoformat('2026-09-14T09:00:00-07:00').timestamp()
CODEX = Path.home() / 'AppData/Local/Programs/OpenAI/Codex/bin/codex.exe'
PYTHON = ROOT.parent / '.venv/Scripts/python.exe'
LINUX_PYTHON = '/home/strider/Code/robotron-rl/.venv-collision/bin/python'
LINUX_ROOT = '/mnt/c/Users/strid/code/robotron_ai'


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        return default


def save_json(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2), encoding='utf-8')
    temp.replace(path)


def live(identity):
    try:
        p = psutil.Process(identity['pid'])
        return p if abs(p.create_time() - identity['created']) < .1 and p.is_running() else None
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def validate_job(job):
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,95}', job['id']):
        raise ValueError('Invalid job id')
    if job['kind'] not in ('xenia', 'mame'):
        raise ValueError('Invalid job kind')
    if not re.fullmatch(r'[a-z][a-z0-9]*', job['candidate']) or job['candidate'] == 'base':
        raise ValueError('Invalid candidate name')
    if not 1 <= job['games'] <= (100 if job['kind'] == 'xenia' else 576):
        raise ValueError('Invalid game count')
    if not .1 <= job['max_hours'] <= 4:
        raise ValueError('Invalid job time limit')
    if job['kind'] == 'xenia':
        if not 6 <= job['max_wave'] <= 100:
            raise ValueError('Invalid wave cap')
        for setting in job['settings'].split(','):
            if not re.fullmatch(r'(ROBOTRON|VSEARCH|FSM)_[A-Z0-9_]+=[A-Za-z0-9_.|+-]+', setting):
                raise ValueError('Invalid Xenia setting')
    else:
        if not isinstance(job['seed'], int) or job['seed'] < 0:
            raise ValueError('Invalid seed')
        for setting in job['settings']:
            if not re.fullmatch(r'(LAB|ROBOTRON|VSEARCH|FSM)_[A-Z0-9_]+=[^\r\n]+', setting):
                raise ValueError('Invalid MAME setting')


def job_command(job):
    validate_job(job)
    if job['kind'] == 'xenia':
        return ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                str(ROOT / 'tools/run_collision_ab.ps1'), '-Production', '-Games', str(job['games']),
                '-MaxWave', str(job['max_wave']), '-CandidateName', job['candidate'],
                '-CandidateSettings', job['settings'], '-RunName', job['id'],
                '-MaxHours', str(job['max_hours'])]
    command = ['wsl.exe', '-d', 'Ubuntu', '--exec', LINUX_PYTHON, '-u',
               LINUX_ROOT + '/tools/run_collision_mame_fresh.py', '--prefix', job['id'],
               '--games', str(job['games']), '--workers', '12', '--candidate-name', job['candidate'],
               '--seed-base', str(job['seed'])]
    for setting in job['settings']:
        command += ['--candidate-env', setting]
    return command


def summarize_xenia(job):
    run = ROOT / 'logs' / job['id']
    status = (run / 'status.txt').read_text(encoding='utf-8-sig').strip() if (run / 'status.txt').exists() else 'missing status'
    arms = {job['id'] + '_base': [], job['id'] + '_' + job['candidate']: []}
    issues = []
    for directory in sorted((ROOT / 'logs/production_games').glob(job['id'] + '_*')):
        record = read_json(directory / 'result.json', {})
        if not record.get('complete'):
            issues.append(directory.name + ': incomplete game')
            continue
        arm = record.get('arm')
        if arm not in arms:
            issues.append(directory.name + ': unknown arm')
            continue
        oracle = directory / 'oracle_headers.jsonl'
        wave = score = 0
        if oracle.exists():
            with oracle.open(encoding='utf-8') as log:
                for line in log:
                    try:
                        row = json.loads(line)
                        wave, score = max(wave, row['wave']), max(score, row['score'])
                    except (ValueError, KeyError):
                        pass
        if record['outcome'] == 'game_over':
            game = record['games'][-1]
            if wave != game['wave'] or score != game['score']:
                issues.append(directory.name + ': HUD/oracle terminal disagreement')
        elif wave < job['max_wave']:
            issues.append(directory.name + ': oracle did not reach cap')
        arms[arm].append(dict(path=str(directory.relative_to(ROOT)), wave=wave, score=score,
                              outcome=record['outcome'], hud=record.get('games', [])))
    complete = (status.startswith('harness finished') and not issues
                and all(len(games) == job['games'] for games in arms.values()))
    return dict(complete=complete, status=status, arms=arms, issues=issues,
                note='Terminal agreement checked; per-wave death/score audit still required for performance claims.')


def reviews_allowed(state, now):
    # Recorded tokens/review counts are not the user's account quota. The user
    # reported 80% capacity remaining and asked us to use the available time.
    # Keep bounded, serial reviews and error cooldowns; do not infer a quota
    # exhaustion from an arbitrary rolling token or review-count threshold.
    return now >= state.get('next_review', 0)


def save(state):
    state['updated'] = time.time()
    state['supervisor_pid'] = os.getpid()
    save_json(OUT / 'state.json', state)
    save_json(ROOT / 'logs/day_active.json', dict(running=state['status'] != 'ended',
        stage=state['status'], state_file='logs/weekend_20260912/state.json', report='WEEKEND_STATUS.md',
        observed=datetime.now().astimezone().isoformat()))
    lines = ['# Robotron weekend status', '', 'Updated: ' + datetime.now().astimezone().isoformat(),
             '', '**' + state['status'] + '**', '',
             'Deadline: Monday September 14, 09:00 Pacific. Local monitor: 30 seconds;',
             'Task Scheduler recovery: 5 minutes. One bounded agent review at a time; error cooldowns retained.', '',
             'No production promotion or W100 claim. Detailed state: logs/weekend_20260912/state.json.', '']
    if state.get('job'):
        lines += ['Active: `' + state['job']['id'] + '`; PID ' + str(state['job']['pid']), '']
    for result in state['results']:
        lines += ['- `' + result['id'] + '`: ' + ('complete' if result['complete'] else 'incomplete/error')]
    for review in state['reviews'][-3:]:
        lines += ['- Review: `' + review['id'] + '` — ' + review.get('status', 'running')]
    (ROOT / 'WEEKEND_STATUS.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def launch(state, ident, command, kind, hours, spec=None, stdin=None):
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    with (OUT / (ident + '.out')).open('wb') as stdout, (OUT / (ident + '.err')).open('wb') as stderr:
        source = open(stdin, 'rb') if stdin else subprocess.DEVNULL
        try:
            p = subprocess.Popen(command, cwd=ROOT, env=env, stdin=source, stdout=stdout, stderr=stderr,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        finally:
            if stdin:
                source.close()
    state['job'] = dict(id=ident, kind=kind, pid=p.pid, created=psutil.Process(p.pid).create_time(),
                        started=time.time(), deadline=min(DEADLINE, time.time() + hours * 3600),
                        spec=spec, owned=[])
    state['status'] = 'running ' + kind
    save(state)


def stop_job(job):
    if job['kind'] != 'review':
        directory = ROOT / 'logs' / job['id']
        directory.mkdir(exist_ok=True)
        (directory / 'STOP').write_text('weekend supervisor stop', encoding='utf-8')
    p = live(job)
    if p:
        try:
            p.wait(timeout=15)
        except psutil.TimeoutExpired:
            for child in reversed(p.children(recursive=True)):
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass
            p.kill()
    for identity in job.get('owned', []):
        child = live(identity)
        if child:
            child.kill()


def cleanup_finished_children(job):
    """Reap recorded descendants only after their owning batch has exited."""
    if live(job):
        return
    stopped = []
    for identity in reversed(job.get('owned', [])):
        child = live(identity)
        if child:
            try:
                child.kill()
                stopped.append(child)
            except psutil.NoSuchProcess:
                pass
    if stopped:
        psutil.wait_procs(stopped, timeout=2)


def finish(state, job):
    # A failed A/B process may exit before cleaning up Xenia. Otherwise the
    # foreign-gameplay guard mistakes our orphan for another user's session
    # and prevents the failure review from ever starting.
    cleanup_finished_children(job)
    if job['kind'] == 'review':
        events = []
        for line in (OUT / (job['id'] + '.out')).read_text(encoding='utf-8', errors='replace').splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                pass
        completed = next((e for e in reversed(events) if e.get('type') == 'turn.completed'), None)
        usage = completed.get('usage', {}) if completed else {}
        row = next(r for r in state['reviews'] if r['id'] == job['id'])
        row.update(status='complete' if completed else 'failed; 4-hour cooldown',
                   uncached_and_output_tokens=max(0, usage.get('input_tokens', 0) - usage.get('cached_input_tokens', 0)) + usage.get('output_tokens', 0))
        state['next_review'] = time.time() + (3600 if completed else 14400)
        state['needs_review'] = not bool(completed)
    else:
        spec = job['spec']
        if job['kind'] == 'xenia':
            result = summarize_xenia(spec)
        else:
            result = read_json(ROOT / 'logs' / job['id'] / 'summary.json', {'complete': False, 'status': 'missing summary'})
        result['id'] = job['id']
        save_json(OUT / (job['id'] + '.summary.json'), result)
        state['results'].append(dict(id=job['id'], complete=bool(result.get('complete')), ended=time.time()))
        state['needs_review'] = not result.get('complete') or spec.get('review_after', True)
    state['job'] = None
    state['status'] = 'checking next stage'


def foreign_gameplay():
    for p in psutil.process_iter(['name', 'cmdline']):
        try:
            name = (p.info['name'] or '').lower()
            command = ' '.join(p.info['cmdline'] or [])
            if name == 'xenia_canary.exe' or (name in ('python.exe', 'wsl.exe', 'powershell.exe') and
                any(s in command for s in ('ab_yolo.py', 'run_production_game.py', 'run_collision_mame_fresh.py', 'train_champion_residual.py', 'run_collision_ab.ps1'))):
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False


def tick(state):
    now = time.time()
    if (OUT / 'STOP').exists() or now >= DEADLINE:
        if state.get('job'):
            stop_job(state['job'])
            finish(state, state['job'])
        state['status'] = 'ended'
        save(state)
        return False
    job = state.get('job')
    if job:
        p = live(job)
        if p:
            children = p.children(recursive=True)
            job['owned'] = [dict(pid=c.pid, created=c.create_time()) for c in children if c.is_running()]
            if now > job['deadline']:
                stop_job(job)
                finish(state, job)
            else:
                state['status'] = 'running ' + job['kind']
            save(state)
            return True
        finish(state, job)
    if foreign_gameplay():
        state['status'] = 'waiting: another gameplay process owns the rig'
        save(state)
        return True
    ready = None
    if not state.get('needs_review'):
        plan = read_json(OUT / 'plan.json')
        attempted = {r['id'] for r in state['results']}
        passed = {r['id'] for r in state['results'] if r['complete']}
        ids = [s['id'] for s in plan['jobs']]
        if len(set(ids)) != len(ids):
            raise ValueError('Duplicate job ids')
        for spec in plan['jobs']:
            validate_job(spec)
        ready = next((s for s in plan['jobs'] if s['id'] not in attempted and
                      (not s.get('depends_on') or s['depends_on'] in passed)), None)
    if state.get('needs_review') or ready is None:
        if reviews_allowed(state, now):
            ident = 'review_' + datetime.now().strftime('%Y%m%d_%H%M%S')
            state['reviews'].append(dict(id=ident, started=now))
            launch(state, ident, [str(CODEX), 'exec', '--json', '--model', 'gpt-6-astra',
                '--sandbox', 'danger-full-access', '-c', 'approval_policy="never"', '-C', str(ROOT),
                '-o', str(OUT / (ident + '.md')), '-'], 'review', .25, stdin=ROOT / 'WEEKEND_REVIEW.md')
        else:
            state['status'] = 'waiting for scheduled review / usage cooldown'
            save(state)
        return True
    if (ROOT / 'logs' / ready['id']).exists():
        state['results'].append(dict(id=ready['id'], complete=False, ended=now,
                                     error='Existing artifacts: requires explicit review, never overwrite'))
        state['needs_review'] = True
        save(state)
        return True
    launch(state, ready['id'], job_command(ready), ready['kind'], ready['max_hours'] + .02, ready)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--once', action='store_true')
    ap.add_argument('--check-plan', action='store_true')
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.check_plan:
        for job in read_json(OUT / 'plan.json')['jobs']:
            print(job_command(job))
        return
    import msvcrt
    lock = (OUT / 'supervisor.lock').open('a+b')
    lock.seek(0)
    if lock.read(1) == b'':
        lock.write(b'0'); lock.flush()
    lock.seek(0)
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        return
    state = read_json(OUT / 'state.json', dict(status='starting', results=[], reviews=[], job=None, needs_review=False))
    while True:
        try:
            if not tick(state) or args.once:
                break
        except Exception as error:
            state['status'] = 'monitor error: ' + repr(error)
            state['needs_review'] = True
            save(state)
            with (OUT / 'monitor_errors.log').open('a', encoding='utf-8') as log:
                log.write(datetime.now().isoformat() + ' ' + repr(error) + '\n')
            if args.once:
                raise
        time.sleep(30)


if __name__ == '__main__':
    main()
