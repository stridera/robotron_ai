"""Coordinate transforms between the three spaces the bot works in.

  game units        integer (gx, gy) the ROM stores; player-reachable field is
                    gx in [7,140], gy in [24,223] on XBLA.
  screen pixels     the 1280x720 captured frame (Xenia window or HDMI). YOLO
                    boxes live here.
  planner pixels    the 665x492 space the evolved FSM + clearance planner were
                    tuned in. EVERYTHING the brain sees is in this space.

Both input paths funnel into planner pixels:
  memory:  game --to_pixels-->            planner
  vision:  screen --px_to_game--> game --to_pixels--> planner
"""
import math

# ── Planner pixel space (FSM / clearance-planner tuning frame) ───────────────
PIX_W, PIX_H = 665.0, 492.0

# game -> planner. Calibrated to Xenia's PLAYER-REACHABLE bounds (measured
# 2026-07-02 by wall probing), NOT the raw MAME field extents: the FSM's wall
# handling only triggers within ~2px of the frame edge, so the player's real
# wall positions must map to the edges.
GX_MIN, GX_RANGE = 7, 133        # left wall gx=7, right wall gx=140
GY_MIN, GY_RANGE = 24, 199       # top wall gy=24, bottom wall gy=223


def to_pixels(gx: float, gy: float) -> tuple:
    """game units -> planner pixel space (y stays down; the FSM flips internally)."""
    return ((gx - GX_MIN) / GX_RANGE * PIX_W,
            (gy - GY_MIN) / GY_RANGE * PIX_H)


# ── Screen pixel space (YOLO detections) <-> game units ─────────────────────
# Affine fit of sprite centre (game units) to captured-frame pixels at 1280x720.
# Calibrated against the clean GameStateReader positions (auto-labeller lineage,
# OFFSET_X fixed +3.5px 2026-07-05, OFFSET_Y fixed -15px 2026-07-03).
SCALE_X = 5.4398
SCALE_Y = 2.4226
OFFSET_X = 244.6211
OFFSET_Y = 67.3573


def game_to_pixel(gx: float, gy: float) -> tuple:
    """game units -> screen pixel (centre of the sprite in a 1280x720 frame)."""
    return int(SCALE_X * gx + OFFSET_X), int(SCALE_Y * gy + OFFSET_Y)


def px_to_game(px: float, py: float) -> tuple:
    """screen pixel -> game units (inverse of game_to_pixel)."""
    return (px - OFFSET_X) / SCALE_X, (py - OFFSET_Y) / SCALE_Y


# ── Decision direction (1..8) <-> analog stick ──────────────────────────────
# Directions are compass N,NE,E,SE,S,SW,W,NW in SCREEN coords (y-down), the
# convention the FSM emits. 0 = neutral.
#
# Analog stick uses x-right+, y-UP+, so the y component is flipped relative to
# the y-down game/planner frame.
_D = math.sqrt(0.5)  # 0.70710678...
DIR_TO_STICK = {
    0: (0.0, 0.0),
    1: (0.0, 1.0), 2: (_D, _D), 3: (1.0, 0.0), 4: (_D, -_D),
    5: (0.0, -1.0), 6: (-_D, -_D), 7: (-1.0, 0.0), 8: (-_D, _D),
}
