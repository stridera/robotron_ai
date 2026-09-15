"""Opt-in, bounded vision-frame archive; no oracle inputs or control outputs.

JPEG bytes live in frames.mjpg; frames.jsonl indexes timestamps and byte ranges.
The offline CLI extracts a wall-clock window into a NEW directory.
"""
import argparse
import hashlib
import json
from pathlib import Path
import queue
import threading
import time


class VisualTrace:
    def __init__(self, directory, max_bytes=2 * 1024 * 1024 * 1024):
        self.directory = Path(directory)
        self.directory.mkdir(exist_ok=False)
        self.max_bytes = max_bytes
        self.pending = queue.Queue(maxsize=4)
        self.stopped = threading.Event()
        self.gate = threading.Lock()
        self.summary = dict(submitted=0, written=0, dropped=0, bytes=0,
                            truncated=False, error=None, copy_seconds=0.0,
                            max_copy_seconds=0.0, encode_seconds=0.0)
        self.worker = threading.Thread(target=self._write, daemon=True)
        self.worker.start()

    def record(self, frame, obs):
        with self.gate:
            self._record(frame, obs)

    def _record(self, frame, obs):
        if frame is None or self.stopped.is_set():
            return
        started = time.perf_counter()
        s = self.summary
        s['submitted'] += 1
        if s['error'] or s['truncated'] or self.pending.full():
            s['dropped'] += 1
            return
        try:
            if frame.nbytes > 32 * 1024 * 1024:
                raise ValueError('frame exceeds 32 MiB input bound')
            # Called on the inference thread before its next source.read().
            # Copy prevents later capture-buffer reuse from changing this image.
            row = dict(t=time.time(), sampled_at=obs.sampled_at,
                       player=obs.player, shape=list(frame.shape))
            self.pending.put_nowait((frame.copy(), row))
        except queue.Full:
            s['dropped'] += 1
        except Exception as error:
            s['error'] = repr(error)
        finally:
            elapsed = time.perf_counter() - started
            s['copy_seconds'] += elapsed
            s['max_copy_seconds'] = max(s['max_copy_seconds'], elapsed)

    def _write(self):
        try:
            import cv2
            with (self.directory / 'frames.mjpg').open('xb') as data, \
                    (self.directory / 'frames.jsonl').open('x', encoding='utf-8') as index:
                while not self.stopped.is_set() or not self.pending.empty():
                    try:
                        frame, row = self.pending.get(timeout=.1)
                    except queue.Empty:
                        continue
                    s = self.summary
                    if s['truncated']:
                        s['dropped'] += 1
                        continue
                    started = time.perf_counter()
                    row['raw_sha256'] = hashlib.sha256(memoryview(frame)).hexdigest()
                    ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
                    if not ok:
                        raise RuntimeError('JPEG encode failed')
                    payload = encoded.tobytes()
                    s['encode_seconds'] += time.perf_counter() - started
                    if s['written'] >= 48000 or s['bytes'] + len(payload) > self.max_bytes:
                        s['truncated'] = True
                        s['dropped'] += 1
                        continue
                    row.update(offset=s['bytes'], size=len(payload))
                    data.write(payload)
                    index.write(json.dumps(row, separators=(',', ':')) + '\n')
                    s['bytes'] += len(payload)
                    s['written'] += 1
        except Exception as error:
            self.summary['error'] = repr(error)

    def close(self):
        with self.gate:
            self.stopped.set()
        self.worker.join(timeout=5)
        self.summary['writer_alive'] = self.worker.is_alive()
        (self.directory / 'summary.json').write_text(
            json.dumps(self.summary, indent=2), encoding='utf-8')


def observed_perceive(original, recorder):
    def perceive(eye, state):
        obs = original(eye, state)
        recorder.record(eye.last_frame, obs)
        return obs
    return perceive


def extract(directory, at, before, after, output):
    rows = [json.loads(line) for line in (directory / 'frames.jsonl').read_text().splitlines()]
    selected = [r for r in rows if at - before <= r['t'] <= at + after]
    output.mkdir(exist_ok=False, parents=True)
    with (directory / 'frames.mjpg').open('rb') as stream:
        for i, row in enumerate(selected):
            stream.seek(row['offset'])
            payload = stream.read(row['size'])
            if len(payload) != row['size']:
                raise ValueError('incomplete archive byte range')
            (output / f'{i:04d}_{row["t"]:.3f}.jpg').write_bytes(payload)
    (output / 'index.json').write_text(json.dumps(selected, indent=2), encoding='utf-8')
    return len(selected)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--at', type=float, required=True)
    parser.add_argument('--before', type=float, default=1.5)
    parser.add_argument('--after', type=float, default=.5)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(extract(args.archive, args.at, args.before, args.after, args.output))
