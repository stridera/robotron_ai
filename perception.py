"""Perception — the input layer. Each source produces an Observation: the player
position and the entity list, both in planner pixel space with engine entity
names, ready for ChampionBrain.decide().

    MemoryPerception   reads the guest entity buffer (Xenia only, gold standard).
    VisionPerception   runs YOLO on a captured frame (Xenia window OR HDMI card);
                       the only option on real hardware.

Frame sources feed VisionPerception:
    XeniaWindowSource  PrintWindow capture of the Xenia window.
    HdmiSource         a cv2 capture device (the friend's HDMI capture card).
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from . import coords


@dataclass
class Observation:
    """One tick of perception, in planner pixel space."""
    player: Optional[Tuple[float, float]]          # None => player not visible
    entities: List[Tuple[float, float, str]] = field(default_factory=list)


class Perception(ABC):
    # Visualization hooks. When collect_viz is True, perceive() should populate
    # last_frame / last_boxes / last_player_px in SCREEN pixel space for the
    # overlay. Memory perception has no frame, so it leaves them None (the
    # harness draws a Xenia-window backdrop instead).
    collect_viz = False
    last_frame = None                    # BGR numpy frame, or None
    last_boxes = None                    # [(cx, cy, w, h, label)] screen px, or None
    last_player_px = None                # (cx, cy) screen px, or None

    @abstractmethod
    def perceive(self, state) -> Observation:
        """Return the current Observation. `state` is the harness's GameState
        (used by MemoryPerception, ignored by VisionPerception)."""

    def reset(self) -> None:
        """Clear any cross-tick state (called on death / wave change)."""


# ── Memory perception (Xenia) ───────────────────────────────────────────────
# game_state entity label -> engine (FSM/planner) entity name.
LABEL_TO_NAME = {
    'G': 'Grunt', 'H': 'Hulk', 'E': 'Electrode', 'B': 'Brain',
    'F': 'Enforcer', 'FB': 'EnforcerBullet', 'S': 'Sphereoid', 'Q': 'Quark',
    'P': 'Prog', 'T': 'Tank', 'TS': 'TankShell', 'MS': 'CruiseMissile',
    'CC': 'Mikey', 'CW': 'Mommy', 'CM': 'Daddy',
}


class MemoryPerception(Perception):
    """Turns a GameState (from GameStateReader) into an Observation."""

    def perceive(self, state) -> Observation:
        if state is None:
            return Observation(None, [])
        px, py = state.player_gx, state.player_gy
        if px == 0 and py == 0:                    # player off-field / dead
            return Observation(None, [])
        player = coords.to_pixels(px, py)
        ents = []
        for e in state.entities:
            name = LABEL_TO_NAME.get(e.label)
            if name is None:
                continue
            ents.append(coords.to_pixels(e.gx, e.gy) + (name,))
        return Observation(player, ents)


# ── Frame sources ───────────────────────────────────────────────────────────
class FrameSource(ABC):
    @abstractmethod
    def read(self):
        """Return a BGR numpy frame (1280x720) or None."""

    def release(self) -> None:
        pass


class XeniaWindowSource(FrameSource):
    """Capture the Xenia window content (works even when occluded)."""

    def __init__(self, window_title: str = "Xenia-canary",
                 width: int = 1280, height: int = 720):
        from .engine.screen_capture import ScreenCapture
        self.cap = ScreenCapture(window_title=window_title, width=width, height=height)

    def read(self):
        ok, frame = self.cap.read()
        return frame if ok else None

    def release(self) -> None:
        self.cap.release()


class HdmiSource(FrameSource):
    """Capture from an HDMI capture card exposed as a cv2 video device.

    The Xbox outputs 1080p60; the card may deliver 1080p frames which we
    downscale to the model's native 1280x720 (an exact 1.5x, same aspect —
    the coordinate transform is unchanged). Two latency/quality pitfalls
    handled here (2026-07-08):

      * cv2.VideoCapture BUFFERS frames. Reading at the ~12Hz decision rate
        from a 60fps stream serves frames 4-5 deep in the queue = 60-80ms of
        hidden lag (a full decision tick — the exact latency class that caused
        the original W9-27 cap). We request BUFFERSIZE=1 and, since not all
        backends honor it, drain the queue with grab()s before each retrieve.
      * Downscaling uses INTER_AREA (the correct filter for shrinking) so the
        ~10px projectile sprites stay as crisp as the training data.
    """

    def __init__(self, device=0, width: int = 1280, height: int = 720):
        import cv2
        import threading
        self.cv2 = cv2
        self.cap = cv2.VideoCapture(device)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.w, self.h = width, height
        if not self.cap.isOpened():
            print(f"[hdmi] WARNING: capture device {device!r} did not open")
        # BACKGROUND CAPTURE THREAD (hardware round 2). The old path drained
        # the backend queue with 3 blocking grab()s per read; on a real card
        # those block on frame boundaries and cost ~85 ms/tick — with GPU
        # inference at ~15 ms, capture was the whole 10 Hz ceiling
        # (delivered_hz == tick hz, duplicate_frac ~0.45 in the reports).
        # A thread grabs continuously at the card's own rate and read() just
        # takes the newest frame: the loop never blocks on the card, and the
        # frame age is bounded by one card-frame instead of a queue.
        self._lock = threading.Lock()
        self._latest = None
        self._running = True
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def _pump(self):
        while self._running:
            ok = self.cap.grab()
            if not ok:
                import time
                time.sleep(0.02)
                continue
            ok, frame = self.cap.retrieve()
            if ok and frame is not None:
                with self._lock:
                    self._latest = frame

    def read(self):
        with self._lock:
            frame = self._latest       # newest frame, re-served if the card
                                       # is slower than the loop (a duplicate
                                       # tick beats a blind tick)
        if frame is None:
            return None
        if frame.shape[1] != self.w or frame.shape[0] != self.h:
            frame = self.cv2.resize(frame, (self.w, self.h),
                                    interpolation=self.cv2.INTER_AREA)
        return frame

    def release(self) -> None:
        self._running = False
        if self.cap:
            self.cap.release()


# ── Vision perception (YOLO) ────────────────────────────────────────────────
# YOLO class name -> engine entity name.
CLS_TO_NAME = {
    'G': 'Grunt', 'H': 'Hulk', 'E': 'Electrode', 'B': 'Brain',
    'F': 'Enforcer', 'FB': 'EnforcerBullet', 'S': 'Sphereoid', 'Q': 'Quark',
    'P': 'Prog', 'T': 'Tank', 'TS': 'TankShell', 'MS': 'CruiseMissile',
    'C': 'Mommy',   # any family name — the FSM treats all civilians as rescues
}

# Per-class confidence gates. Missing a lethal threat is far worse than a
# spurious box the planner routes around, so deadly/hard-to-detect classes get
# LOW thresholds (max recall); the player gets a higher one to suppress phantom
# double-Player detections that corrupt avoidance geometry. --conf raises the
# floor for every class (never lowers recall unexpectedly).
PER_CLASS_CONF = {
    'Player': 0.35,
    'E': 0.15, 'FB': 0.10, 'TS': 0.10, 'MS': 0.10,
    'F': 0.10, 'H': 0.10, 'P': 0.12, 'T': 0.15,
    'B': 0.20, 'S': 0.18, 'Q': 0.20, 'G': 0.25, 'C': 0.30,
}


class VisionPerception(Perception):
    """Screen/HDMI frame -> YOLO detections -> Observation in planner space."""

    def __init__(self, source: FrameSource, weights: str, conf: float = 0.4,
                 track: bool = False, max_player_hold: int = 6,
                 imgsz: int = None):
        from ultralytics import YOLO
        self.source = source
        self.model = YOLO(weights)
        # Inference size. The model trains/serves at 1280 for small-sprite
        # recall; on a CPU-only rig that costs ~150 ms/frame and caps the
        # loop near 7 Hz. 640 is ~3-4x faster at some recall cost on the
        # smallest sprites — the right trade when there is no CUDA GPU.
        self.imgsz = imgsz
        self.names = self.model.names
        self.track = track
        self.cls_conf = {k: max(v, conf) for k, v in PER_CLASS_CONF.items()}
        self.base_conf = min(min(PER_CLASS_CONF.values()), conf)
        self.max_player_hold = max_player_hold
        self._player_hold = 0
        self.last_player = None
        # CENTER-OFFSET SELF-CALIBRATION (hardware round 3). The model's box
        # centers are unbiased on emulator pixels (<=1.2px) but measured
        # ~4.3px low / 1.4px left on a real capture chain (resampling phase
        # shift) — every planner coordinate inherits that, which shows up as
        # e.g. the player stopping short of the bottom wall. Isolated
        # detections let us measure it live: sprite ink centroid vs box
        # center, running median, applied once settled.
        from collections import deque
        self._off_dx = deque(maxlen=500)
        self._off_dy = deque(maxlen=500)
        self.center_off = (0.0, 0.0)     # applied (manual --center-off only)
        self.center_measured = (0.0, 0.0)  # diagnostic, reported in telemetry
        self._off_announced = False
        # Warm up (first inference compiles kernels / inits the tracker).
        frame = self.source.read()
        if frame is not None:
            self._infer(frame)

    def reset(self) -> None:
        self.last_player = None
        self._player_hold = 0

    def _infer(self, frame):
        kw = {}
        if self.imgsz:
            kw['imgsz'] = self.imgsz
        if self.track:
            return self.model.track(frame, conf=self.base_conf, persist=True,
                                    tracker="bytetrack.yaml", verbose=False,
                                    **kw)[0]
        return self.model.predict(frame, conf=self.base_conf, verbose=False,
                                  **kw)[0]

    def _rows(self, boxes):
        """(class_name, conf, cx, cy, w, h) per box. Indexing an ultralytics
        Boxes per-box forces a GPU->CPU sync for EVERY field of every box —
        measured at 6.7 ms/tick on the dev tree (a tenth of the tick budget
        spent marshalling numbers). Pull the three tensors across once and
        iterate in numpy. Falls back to per-box attribute access so tests can
        feed plain fake boxes."""
        cls_t = getattr(boxes, "cls", None)
        if cls_t is not None and hasattr(cls_t, "cpu"):
            cls_a = cls_t.cpu().numpy().astype(int)
            conf_a = boxes.conf.cpu().numpy()
            xy_a = boxes.xywh.cpu().numpy()
            return [(self.names[int(c)], float(f), float(b[0]), float(b[1]),
                     float(b[2]), float(b[3]))
                    for c, f, b in zip(cls_a, conf_a, xy_a)]
        return [(self.names[int(b.cls[0])], float(b.conf[0]),
                 float(b.xywh[0][0]), float(b.xywh[0][1]),
                 float(b.xywh[0][2]), float(b.xywh[0][3])) for b in boxes]

    def _parse_boxes(self, boxes):
        """boxes -> (player_xy|None, entities, viz_boxes, player_px). The first
        two are in planner space (the brain's frame); viz_boxes/player_px are in
        SCREEN pixels for the overlay. Applies the calibrated center offset."""
        player, best_pconf, ents = None, 0.0, []
        viz_boxes, player_px = [], None
        odx, ody = self.center_off
        for cls, conf, rcx, rcy, bw, bh in self._rows(boxes):
            if conf < self.cls_conf.get(cls, 1.0):     # per-class gate
                continue
            cx, cy = rcx + odx, rcy + ody
            gx, gy = coords.px_to_game(cx, cy)
            if cls == 'Player':
                if conf > best_pconf:                  # keep only the best player
                    best_pconf = conf
                    player = coords.to_pixels(gx, gy)
                    player_px = (cx, cy)
                continue
            name = CLS_TO_NAME.get(cls)
            if name is None:
                continue
            ents.append(coords.to_pixels(gx, gy) + (name,))
            viz_boxes.append((cx, cy, bw, bh, cls))
        return player, ents, viz_boxes, player_px

    def _calibrate_center(self, frame, viz_boxes):
        """Sample sprite-centroid-vs-box-center offsets from ISOLATED boxes
        (neighbours corrupt the centroid) and apply the running median once
        enough samples agree. Costs ~nothing; a no-op on unbiased captures."""
        import numpy as np
        # Sample ONLY during actual gameplay (full-width arena border row
        # present). Menu screens produce fake "E" detections (achievement
        # icons at 0.4+), and sampling those walked the correction ~0.5px
        # per update through every menu visit.
        band = frame[615:645, 200:1080]
        if band.size == 0 or (band.max(axis=2) > 140).mean(axis=1).max() < 0.6:
            return
        # Two hard-won rules (the first version DIVERGED, -2.5 -> -7.7 px in
        # a steady ramp, caught in rehearsal):
        #  * The sampling window must be anchored to the RAW box center. A
        #    window centered on the corrected box shifts off the sprite as
        #    the correction grows, clips its ink asymmetrically, and drags
        #    the centroid further in the correction's direction — a positive
        #    feedback loop.
        #  * Only ELECTRODES are sampled: their ink is compact and symmetric,
        #    so centroid == visual center. Shaped sprites (civilians, hulks)
        #    have genuinely asymmetric ink and bias the estimate per class.
        odx, ody = self.center_off
        for i, (cx, cy, w, h, cls) in enumerate(viz_boxes[:10]):
            if cls != 'E' or w < 8 or h < 8 or w > 60 or h > 60:
                continue
            if any(j != i and abs(b[0] - cx) < 45 and abs(b[1] - cy) < 45
                   for j, b in enumerate(viz_boxes)):
                continue                       # not isolated
            rcx, rcy = cx - odx, cy - ody
            x0, y0 = int(rcx - w / 2) - 8, int(rcy - h / 2) - 8
            x1, y1 = int(rcx + w / 2) + 8, int(rcy + h / 2) + 8
            if x0 < 0 or y0 < 0 or y1 > frame.shape[0] or x1 > frame.shape[1]:
                continue
            sub = frame[y0:y1, x0:x1].max(axis=2) > 90
            if sub.sum() < 15:
                continue
            ys, xs = np.where(sub)
            self._off_dx.append(x0 + float(xs.mean()) - rcx)
            self._off_dy.append(y0 + float(ys.mean()) - rcy)
        if len(self._off_dx) >= 120:
            # MEASURED, NOT APPLIED. Live application was tried twice and
            # walked both times: the ink centroid moves with the wave
            # palette and the electrode flash phase, so centroid-vs-box is
            # not a valid estimator of detection bias (on the emulator,
            # where true bias is <=1.2px, it reads -4 to -8). The medians go
            # to telemetry as a diagnostic; --center-off applies a manual
            # correction if offline analysis ever justifies one.
            self.center_measured = (float(np.median(self._off_dx)),
                                    float(np.median(self._off_dy)))
            if not self._off_announced:
                self._off_announced = True
                print(f"[vision] box-center diagnostic (not applied): "
                      f"centroid-vs-box ({self.center_measured[0]:+.1f}, "
                      f"{self.center_measured[1]:+.1f}) px, "
                      f"n={len(self._off_dx)}")

    def _resolve_player(self, player):
        """Bounded last-player hold: reuse the last position for up to
        max_player_hold blind frames, then report blind (None)."""
        if player is None:
            if self.last_player is not None and self._player_hold < self.max_player_hold:
                self._player_hold += 1
                return self.last_player
            return None
        self._player_hold = 0
        self.last_player = player
        return player

    def perceive(self, state) -> Observation:
        frame = self.source.read()
        # last_frame is kept unconditionally (a reference, not a copy): the
        # HUD bookkeeper reads score/wave from it on the hardware path.
        self.last_frame = frame
        if frame is None:
            if self.collect_viz:
                self.last_boxes, self.last_player_px = [], None
            return Observation(None, [])
        res = self._infer(frame)
        player, ents, viz_boxes, player_px = self._parse_boxes(res.boxes)
        self._calibrate_center(frame, viz_boxes)
        # Boxes/player are kept unconditionally too — telemetry consumes them
        # on the hardware path; the overlay just reads the same fields.
        self.last_boxes = viz_boxes
        self.last_player_px = player_px
        player = self._resolve_player(player)
        return Observation(player, ents)
