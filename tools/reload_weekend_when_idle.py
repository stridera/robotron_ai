"""Reload only the monitor, in the quiet interval between its owned jobs."""
import json
from pathlib import Path
import subprocess
import time

import psutil
from weekend_supervisor import cleanup_finished_children, live, read_json

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'logs/weekend_20260912'
state = json.loads((OUT / 'state.json').read_text(encoding='utf-8'))
monitor = psutil.Process(state['supervisor_pid'])
created = monitor.create_time()
if not any('weekend_supervisor.py' in x for x in monitor.cmdline()):
    raise RuntimeError('Refusing to act on a non-supervisor process')


def report(status):
    (OUT / 'deadline_extension.json').write_text(json.dumps(dict(
        deadline='2026-09-14T09:00:00-07:00', status=status,
        old_supervisor_pid=monitor.pid, helper_pid=psutil.Process().pid,
        updated=time.time()), indent=2), encoding='utf-8')


report('pending: waiting for active batch/review to exit')
last_job = state.get('job')
while not (OUT / 'STOP').exists():
    try:
        if monitor.create_time() != created or not monitor.is_running():
            break
        current = read_json(OUT / 'state.json')
        if current.get('job'):
            last_job = current['job']
        elif last_job and not live(last_job):
            # Bridge the old monitor's orphan-cleanup gap while waiting to
            # load its fix. Identity checks never touch a live batch or a
            # reused PID belonging to another process.
            cleanup_finished_children(last_job)
            last_job = None
        # All work is a child of the monitor. Never stop it while a test or
        # review remains, including a process created just before state writes.
        if not monitor.children(recursive=True):
            # Suspend closes the launch race, then recheck before termination.
            monitor.suspend()
            try:
                if monitor.children(recursive=True):
                    monitor.resume()
                else:
                    monitor.terminate()
                    monitor.wait(timeout=10)
                    break
            except BaseException:
                if monitor.is_running():
                    monitor.resume()
                raise
    except psutil.NoSuchProcess:
        break
    time.sleep(1)
if (OUT / 'STOP').exists():
    report('cancelled by STOP; no restart')
else:
    # Scheduler state can lag the exit slightly. Its periodic trigger is also
    # a fallback if this immediate request finds the old action still closing.
    time.sleep(3)
    completed = subprocess.run(['powershell.exe', '-NoProfile', '-Command',
        'Start-ScheduledTask -TaskName RobotronWeekend20260912'],
        capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    report('monitor exited safely; restart requested' if completed.returncode == 0
           else 'monitor exited safely; awaiting five-minute scheduled restart')
