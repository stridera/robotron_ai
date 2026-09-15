"""Bound process shutdown separately from gameplay, using a private completion marker."""
import json
from pathlib import Path
import subprocess
import time
import uuid

import psutil


class ShutdownTimeout(RuntimeError):
    pass


def run_completed_process(cmd, *, env, cwd, timeout, marker, shutdown_timeout=45):
    marker = Path(marker)
    if marker.exists():
        raise ValueError('Completion marker must be new')
    child_env = dict(env, ROBOTRON_COMPLETION_MARKER=str(marker))
    process = subprocess.Popen(cmd, env=child_env, cwd=cwd)
    owned = psutil.Process(process.pid)
    began = time.monotonic()
    completed_at = None
    try:
        while process.poll() is None:
            now = time.monotonic()
            if completed_at is None and marker.exists():
                completed_at = now
            if completed_at is not None and now - completed_at >= shutdown_timeout:
                detail = dict(status='shutdown_timeout', pid=process.pid,
                              marker=str(marker), grace_seconds=shutdown_timeout)
                marker.with_suffix('.shutdown_error.json').write_text(
                    json.dumps(detail, indent=2), encoding='utf-8')
                raise ShutdownTimeout(f'Game result saved, but process did not exit within {shutdown_timeout}s: {marker}')
            if now - began >= timeout:
                raise subprocess.TimeoutExpired(cmd, timeout)
            time.sleep(.25)
        return subprocess.CompletedProcess(cmd, process.returncode)
    finally:
        if process.poll() is None:
            # The Windows venv launcher can have a separate interpreter child.
            # Kill only this process tree, never unrelated Python processes.
            try:
                children = owned.children(recursive=True)
            except psutil.NoSuchProcess:
                children = []
            for child in reversed(children):
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass
            process.kill()
            process.wait(timeout=10)


def run_production_process(cmd, *, env, cwd, timeout):
    directory = Path(__file__).resolve().parents[1] / 'logs/production_processes'
    directory.mkdir(parents=True, exist_ok=True)
    return run_completed_process(cmd, env=env, cwd=cwd, timeout=timeout,
                                 marker=directory / (uuid.uuid4().hex + '.json'))
