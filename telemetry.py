"""Hardware telemetry — one sendable folder that answers the port questions.

The rig owner (a friend with the Xbox) is not the person tuning the bot, so
every empirical unknown of the emulator->hardware port must be answered by a
file they can just send back. This module runs automatically in hardware mode
(negligible cost) and writes logs/hardware_report/:

    report.json   every measurement below, machine-readable
    *.png         a few sample frames (first good frame, a HUD-unreadable
                  frame, a player-blind frame) for eyeballing capture quality
                  and re-deriving geometry offsets

What it measures, and which port question each answers:
  act_ticks          command-change -> vision-observed response latency
                     (median, n). THE number PLAYER_LEAD_TICKS=1.5 depends
                     on; measured exactly like the emulator calibrator, pure
                     vision so it transfers unchanged.
  tick               achieved decision cadence, busy times, overruns, and
                     the kinematic scale k actually applied — is 15 Hz held?
  frames             delivered rate + duplicate-frame fraction (capture
                     cards re-serve frames; duplicates halve the velocity
                     sample rate) + delivered resolution.
  detection          per-class box counts/minute + mean confidence, player-
                     visible fraction, blind-streak histogram — recall
                     proxies without ground truth; compare against the
                     emulator baseline printed in the same schema.
  player_bounds      min/max of player positions in planner space — if the
                     player never reaches the expected arena bounds, the
                     capture geometry (OFFSET/SCALE) is shifted.
  hud                OCR coverage, per-field accuracy proxies (match
                     confidence distribution), glyph x/y extents vs the
                     expected layout — is the HUD where we think it is, and
                     is the capture sharp enough to read it?
  games              per-game summaries from the bookkeeper (wave, score,
                     deaths) — the actual outcomes.
"""
import json
import os
import time
from collections import Counter, deque

import numpy as np

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DIR = os.path.join(_PKG_DIR, "logs", "hardware_report")


class ActEstimator:
    """Actuation latency from command history + vision, ported from the
    emulator's LatencyCalibrator (measured a rock-stable 2.0 ticks there):
    when the commanded move direction changes, count decision ticks until the
    observed player velocity aligns with the new command."""
    ALIGN = 0.7
    SPEED = 1.5

    def __init__(self, dxy):
        self.dxy = dxy
        self.prev_p = None
        self.samples = deque(maxlen=600)
        self._evt = None
        self._last_mv = None

    def tick(self, mv, player_xy):
        import math
        vv = None
        if player_xy is not None and self.prev_p is not None:
            vv = (player_xy[0] - self.prev_p[0], player_xy[1] - self.prev_p[1])
        if self._evt is not None:
            n, ux, uy, cmd = self._evt
            if mv != cmd or n > 8:
                self._evt = None
            elif vv is not None:
                sp = math.hypot(*vv)
                if sp > self.SPEED and (vv[0] * ux + vv[1] * uy) / sp > self.ALIGN:
                    self.samples.append(float(n))
                    self._evt = None
                else:
                    self._evt = (n + 1, ux, uy, cmd)
            else:
                self._evt = (n + 1, ux, uy, cmd)
        if self._evt is None and mv != self._last_mv and mv in self.dxy:
            import math
            d = self.dxy[mv]
            if d[0] or d[1]:
                mag = math.hypot(d[0], d[1])
                self._evt = (1, d[0] / mag, d[1] / mag, mv)
        self._last_mv = mv
        self.prev_p = player_xy

    def stats(self):
        if not self.samples:
            return dict(median=None, n=0)
        s = sorted(self.samples)
        return dict(median=s[len(s) // 2], n=len(s),
                    p90=s[int(len(s) * 0.9)])


class HardwareTelemetry:
    """Collects everything; call the hooks from the vision loop, then
    finalize() (also safe on Ctrl+C via the harness's finally)."""

    SAMPLE_FRAMES = {"first_good": None, "hud_unreadable": None,
                     "player_blind": None}

    def __init__(self, dxy, out_dir=None):
        self.out = out_dir or DEFAULT_DIR
        os.makedirs(self.out, exist_ok=True)
        self.t0 = time.time()
        self.act = ActEstimator(dxy)
        self.cls_counts = Counter()
        self.cls_conf = Counter()
        self.ticks = 0
        self.player_seen = 0
        self.blind_streak = 0
        self.blind_hist = Counter()
        self.px_min = [1e9, 1e9]
        self.px_max = [-1e9, -1e9]
        self.frames = 0
        self.dup_frames = 0
        self._last_frame_sig = None
        self.hud_reads = 0
        self.hud_valid = 0
        self.hud_conf = []
        self.games = []
        self._frames_saved = dict.fromkeys(self.SAMPLE_FRAMES, False)
        self._finalized = False
        self._last_save = time.time()

    # ── hooks ──────────────────────────────────────────────────────────
    def frame(self, frame):
        """Every captured frame (cheap: 8x8 downsample signature)."""
        if frame is None:
            return
        self.frames += 1
        sig = frame[::90, ::160].astype(np.int32).sum(axis=2)
        if self._last_frame_sig is not None and \
                np.array_equal(sig, self._last_frame_sig):
            self.dup_frames += 1
        self._last_frame_sig = sig

    def tick(self, mv, player_xy, viz_boxes, frame):
        self.ticks += 1
        self.act.tick(mv, player_xy)
        if player_xy is not None:
            self.player_seen += 1
            if self.blind_streak:
                self.blind_hist[min(self.blind_streak, 20)] += 1
                self.blind_streak = 0
            self.px_min = [min(self.px_min[0], player_xy[0]),
                           min(self.px_min[1], player_xy[1])]
            self.px_max = [max(self.px_max[0], player_xy[0]),
                           max(self.px_max[1], player_xy[1])]
            self._save_frame("first_good", frame)
        else:
            self.blind_streak += 1
            if self.blind_streak == 3:
                self._save_frame("player_blind", frame)
        for b in viz_boxes or []:
            self.cls_counts[b[4]] += 1
        # Autosave: a hard kill or power loss on the rig must not lose the
        # report (finalize() only runs on a clean exit).
        if time.time() - self._last_save > 60:
            self._last_save = time.time()
            try:
                with open(os.path.join(self.out, "report.json"), "w") as f:
                    json.dump(self.report(), f, indent=1)
            except OSError:
                pass

    def hud(self, reading, frame):
        self.hud_reads += 1
        if reading['score'] is not None or reading['wave'] is not None:
            self.hud_valid += 1
            if reading['conf']:
                self.hud_conf.append(round(float(reading['conf']), 3))
        elif self.hud_reads > 50:
            self._save_frame("hud_unreadable", frame)

    def game_over(self, **kw):
        self.games.append({k: kw.get(k) for k in
                           ("game", "wave", "score", "deaths")})

    # ── output ─────────────────────────────────────────────────────────
    def _save_frame(self, key, frame):
        if frame is None or self._frames_saved.get(key):
            return
        self._frames_saved[key] = True
        try:
            import cv2
            cv2.imwrite(os.path.join(self.out, f"{key}.png"), frame)
        except Exception:
            pass

    def report(self):
        el = max(time.time() - self.t0, 1e-6)
        hc = sorted(self.hud_conf)
        return {
            "schema": "robotron_ai.hardware_report.v1",
            "started_utc": time.strftime("%Y-%m-%d %H:%M:%S",
                                         time.gmtime(self.t0)),
            "elapsed_s": round(el, 1),
            "act_ticks": self.act.stats(),
            "frames": {
                "delivered_hz": round(self.frames / el, 2),
                "duplicate_frac": round(self.dup_frames / max(self.frames, 1), 4),
            },
            "detection": {
                "player_visible_frac": round(self.player_seen / max(self.ticks, 1), 4),
                "blind_streaks": dict(sorted(self.blind_hist.items())),
                "boxes_per_min": {k: round(v / (el / 60), 1)
                                  for k, v in sorted(self.cls_counts.items())},
            },
            "player_bounds_planner_px": {
                "min": [round(v, 1) for v in self.px_min],
                "max": [round(v, 1) for v in self.px_max],
                "expected": [[0, 0], [665, 492]],
            },
            "hud": {
                "coverage": round(self.hud_valid / max(self.hud_reads, 1), 4),
                "conf_p10": hc[int(len(hc) * 0.1)] if hc else None,
                "conf_p50": hc[len(hc) // 2] if hc else None,
            },
            "games": self.games,
            "ticks": self.ticks,
        }

    def finalize(self, tick_stats=None, center_off=None):
        if self._finalized:
            return
        self._finalized = True
        rep = self.report()
        if tick_stats:
            rep["tick"] = tick_stats
        if center_off is not None:
            rep["box_center_offset_px"] = [round(v, 2) for v in center_off]
        path = os.path.join(self.out, "report.json")
        try:
            with open(path, "w") as f:
                json.dump(rep, f, indent=1)
            print(f"\n[telemetry] report written to {self.out}")
            print("[telemetry] >>> send that whole folder back for analysis <<<")
        except OSError as e:
            print(f"[telemetry] could not write report: {e}")
