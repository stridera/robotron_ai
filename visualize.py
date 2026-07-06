"""Live debug/demo overlay — a window showing the game feed with the bot's
perception drawn on top: entity boxes + labels, the player, threat vectors, the
chosen move/fire directions, and a HUD (wave/score/lives/action).

It renders whatever primitives the harness hands it (all in SCREEN pixel space),
so it works identically for the memory path (boxes from guest RAM over a Xenia
window grab) and the vision path (YOLO boxes over the captured frame).

Toggled with --visualize. Closing the window or pressing 'q' turns it off; the
bot keeps playing.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# Per-label box colour (BGR). Threat families warm, civilians green, hazards yellow.
_LABEL_COLORS = {
    'G': (0, 165, 255), 'H': (0, 0, 255), 'E': (0, 255, 255), 'B': (255, 0, 255),
    'F': (0, 100, 255), 'FB': (40, 40, 220), 'S': (255, 0, 128), 'Q': (200, 0, 200),
    'T': (140, 0, 255), 'TS': (40, 40, 200), 'MS': (0, 60, 255), 'P': (255, 140, 0),
    'C': (0, 255, 0), 'CC': (0, 255, 0), 'CW': (0, 255, 0), 'CM': (0, 255, 0),
}
_DEFAULT_COLOR = (200, 200, 200)
_PLAYER_COLOR = (255, 255, 0)     # cyan
_MOVE_COLOR = (0, 255, 0)         # green
_FIRE_COLOR = (0, 160, 255)       # orange
_THREAT_COLOR = (60, 60, 255)     # red
_CIVILIANS = {'C', 'CC', 'CW', 'CM'}

# direction 1..8 -> unit vector in SCREEN space (y-down): N,NE,E,SE,S,SW,W,NW.
_R = 0.70710678
_DIR_SCREEN = {
    0: (0.0, 0.0),
    1: (0.0, -1.0), 2: (_R, -_R), 3: (1.0, 0.0), 4: (_R, _R),
    5: (0.0, 1.0), 6: (-_R, _R), 7: (-1.0, 0.0), 8: (-_R, -_R),
}
_DIR_NAME = {0: '-', 1: 'N', 2: 'NE', 3: 'E', 4: 'SE', 5: 'S', 6: 'SW', 7: 'W', 8: 'NW'}


def dir_name(d: int) -> str:
    return _DIR_NAME.get(d, '?')


@dataclass
class VizOverlay:
    """Everything to draw for one frame, in SCREEN pixel coordinates."""
    entities: List[Tuple[float, float, float, float, str]] = field(default_factory=list)
    #          (cx, cy, w, h, label)
    player: Optional[Tuple[float, float]] = None      # (cx, cy)
    move_dir: int = 0
    fire_dir: int = 0
    hud: List[str] = field(default_factory=list)
    show_threats: bool = True
    n_threats: int = 3


class Visualizer:
    """OpenCV window that draws a VizOverlay on a frame. Cheap enough to call
    every decision tick; call it AFTER acting so it never delays actuation."""

    def __init__(self, enabled: bool = False, window: str = "robotron_ai",
                 width: int = 1280, height: int = 720):
        self.enabled = enabled
        self.window = window
        self.width, self.height = width, height
        self._cv2 = None
        self._np = None
        if enabled:
            try:
                import cv2
                import numpy as np
                self._cv2, self._np = cv2, np
                cv2.namedWindow(window, cv2.WINDOW_NORMAL)
                cv2.resizeWindow(window, width, height)
                print(f"[viz] overlay window '{window}' open (q or close to hide)")
            except Exception as e:
                print(f"[viz] unavailable ({e}) - overlay disabled")
                self.enabled = False

    def render(self, frame, overlay: VizOverlay) -> None:
        """Draw the overlay and pump the window. Disables itself if the user
        closes the window or presses 'q'."""
        if not self.enabled:
            return
        cv2 = self._cv2
        frame = self.draw(frame, overlay)
        cv2.imshow(self.window, frame)
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q') or cv2.getWindowProperty(self.window, cv2.WND_PROP_VISIBLE) < 1:
            self._hide()

    def draw(self, frame, overlay: VizOverlay):
        """Pure drawing: annotate (a copy of) `frame` and return it. No window
        I/O, so it is unit-testable and reusable for saving frames to disk."""
        if self._cv2 is None:                    # allow offscreen use w/o a window
            import cv2
            import numpy as np
            self._cv2, self._np = cv2, np
        cv2, np = self._cv2, self._np
        if frame is None:
            frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        else:
            frame = frame.copy()

        px = overlay.player
        # Threat vectors: lines from the player to the nearest N non-civilians.
        if px is not None and overlay.show_threats:
            threats = [(cx, cy) for (cx, cy, _w, _h, lbl) in overlay.entities
                       if lbl not in _CIVILIANS]
            threats.sort(key=lambda c: (c[0] - px[0]) ** 2 + (c[1] - px[1]) ** 2)
            for (cx, cy) in threats[:overlay.n_threats]:
                cv2.line(frame, (int(px[0]), int(px[1])), (int(cx), int(cy)),
                         _THREAT_COLOR, 1, cv2.LINE_AA)

        # Entity boxes + labels.
        for (cx, cy, w, h, lbl) in overlay.entities:
            color = _LABEL_COLORS.get(lbl, _DEFAULT_COLOR)
            w = max(w, 8); h = max(h, 8)
            x1, y1 = int(cx - w / 2), int(cy - h / 2)
            x2, y2 = int(cx + w / 2), int(cy + h / 2)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 1)
            cv2.putText(frame, lbl, (x1, max(y1 - 3, 8)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)

        # Player marker + move/fire arrows.
        if px is not None:
            p = (int(px[0]), int(px[1]))
            cv2.circle(frame, p, 9, _PLAYER_COLOR, 2)
            self._arrow(frame, p, overlay.move_dir, 46, _MOVE_COLOR)
            self._arrow(frame, p, overlay.fire_dir, 34, _FIRE_COLOR)

        self._draw_hud(frame, overlay.hud)
        return frame

    def _arrow(self, frame, origin, d, length, color):
        if d == 0:
            return
        dx, dy = _DIR_SCREEN[d]
        tip = (int(origin[0] + dx * length), int(origin[1] + dy * length))
        self._cv2.arrowedLine(frame, origin, tip, color, 2,
                              self._cv2.LINE_AA, tipLength=0.3)

    def _draw_hud(self, frame, lines):
        if not lines:
            return
        cv2 = self._cv2
        y = 22
        for line in lines:
            cv2.putText(frame, line, (11, y + 1), cv2.FONT_HERSHEY_SIMPLEX,
                        0.6, (0, 0, 0), 3, cv2.LINE_AA)          # shadow
            cv2.putText(frame, line, (11, y), cv2.FONT_HERSHEY_SIMPLEX,
                        0.6, (255, 255, 255), 1, cv2.LINE_AA)
            y += 26

    def _hide(self):
        try:
            self._cv2.destroyWindow(self.window)
        except Exception:
            pass
        self.enabled = False
        print("[viz] overlay closed")

    def close(self):
        if self._cv2 is not None:
            try:
                self._cv2.destroyWindow(self.window)
            except Exception:
                pass
        self.enabled = False
