"""HUD OCR — read score, wave and lives from the game picture alone.

Why this exists (2026-08-05): on real hardware there is no memory access, so
without it the bot has no idea what wave it is on, when it died, or when the
game ended — and, critically, the A/B harness has no metric, which the whole
July campaign showed means no trustworthy tuning. This module turns the video
feed into the same per-wave bookkeeping the emulator gets from guest RAM.

Method: template matching against the game's own fixed bitmap font. The
digit templates are AUTO-HARVESTED on the emulator, where guest memory
provides labels (robotron/harvest_hud.py), and shipped in
weights/hud_font.npz. Matching is scale-normalized per glyph, so the modest
blur/rescale of an HDMI capture chain degrades match confidence gracefully
instead of breaking segmentation.

Layout (1280x720 planner feed, measured 2026-08-05):
    score   white glyphs, y ~68-100, from x ~230; lives icons (coloured
            player sprites) follow on the same strip
    wave    blue glyphs "N WAVE", y ~605-660 (the copyright line sits below)

`HudReader` is stateless per frame; `VisionBookkeeper` adds the temporal
state machine (hysteresis, monotonic-score sanity, death/game-over events)
and writes wave rows in the same JSONL shape the emulator harness logs, so
robotron/ab_yolo.py can analyse hardware runs unchanged (`--log`).
"""
import json
import os
import time

import numpy as np

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_FONT = os.path.join(_PKG_DIR, "weights", "hud_font.npz")

# Glyph normalization grid (w, h). The native digits are ~13x19 at 720p;
# normalizing makes the match tolerant of the hardware chain's rescale.
GRID_W, GRID_H = 12, 16

# HUD strips at 720p (y0, y1, x0, x1) — measured 2026-08-05; geometry
# confirmed IDENTICAL on real-Xbox capture (2026-08-16 hardware reports).
# The wave strip must start BELOW the arena border (full-width bright rows at
# y626-631): above it is playfield, and under a color-agnostic mask the
# sprites read as glyphs. Wave text lives at y634-645; copyright from y666.
# Score strip ends at 94: the arena begins at ~y95, and death-explosion
# particles in rows 95-105 were adding phantom glyphs (seen on hardware).
SCORE_STRIP = (60, 94, 200, 900)
WAVE_STRIP = (632, 660, 200, 1080)
# Lives icons live within ~8 icons of the last digit; farther bright content
# in the score row is spill (particles, sprites at the arena top edge).
LIVES_WINDOW_PX = 200


# THE COLOR SCHEME CYCLES EVERY WAVE — HUD text included (white, cream, pale
# cyan, yellow, ...). Color-specific masks therefore pass some waves fully,
# some partially (eroded strokes = confident misreads) and some not at all —
# this single fact produced chimera templates (54% label accuracy) and the
# wave line's chronic ~10% coverage while it was masked as 'blue'. The
# invariant is BRIGHT ON BLACK, so the masks are color-agnostic brightness
# masks; full-width separator rows (the arena border crossing a strip) are
# suppressed because text rows never approach full-width ink.
def _ink_mask(strip, thresh=None, row_kill=0.6):
    """Brightness mask with an ADAPTIVE threshold. Real-hardware capture
    chains deliver limited-range video (white ≈ 235, and dim wave-color
    schemes land lower still), so a fixed 160 gate can zero out entire waves
    that the emulator read fine. Scale the gate to the strip's actual signal
    level; the floor keeps noise out on truly-empty strips (blacks ≈ 16)."""
    mx = strip.max(axis=2)
    if thresh is None:
        peak = int(mx.max())
        if peak < 110:
            return np.zeros(mx.shape, bool)      # nothing bright — no text
        thresh = max(100, int(peak * 0.55))
    m = mx > thresh
    full = m.mean(axis=1) > row_kill
    if full.any():
        m[full] = False
    return m


def _score_mask(strip):
    return _ink_mask(strip)


def _wave_mask(strip):
    return _ink_mask(strip)


def _color_mask(strip):
    """Lives-icon ink. The icons are the only bright content RIGHT of the
    score digits, so the same brightness mask works and stays color-proof
    (a saturation test would confuse yellow-scheme text with the icons)."""
    return _ink_mask(strip, thresh=110)


def segment_glyphs(mask, min_w=2, min_h=6, max_gap=1):
    """Column-projection segmentation: contiguous x-runs of ink (allowing
    max_gap empty columns inside a glyph), each trimmed to its y-extent.
    Returns [(x0, y0, x1, y1)] sorted left-to-right."""
    cols = mask.any(axis=0)
    boxes, x0, gap = [], None, 0
    for x in range(len(cols) + 1):
        on = x < len(cols) and cols[x]
        if on:
            if x0 is None:
                x0 = x
            gap = 0
        elif x0 is not None:
            gap += 1
            if gap > max_gap or x == len(cols):
                x1 = x - gap
                sub = mask[:, x0:x1 + 1]
                ys = np.where(sub.any(axis=1))[0]
                if len(ys) and (x1 - x0 + 1) >= min_w and (ys[-1] - ys[0] + 1) >= min_h:
                    boxes.append((x0, int(ys[0]), x1, int(ys[-1])))
                x0, gap = None, 0
    return boxes


def normalize_glyph(mask, box):
    """Binary glyph crop -> GRID float array in [0,1] via AREA-AVERAGE
    pooling (each cell = ink fraction of its source block).

    This must NOT be nearest-neighbour: the same digit lands on the pixel
    grid with sub-pixel shifts frame to frame, and NN sampling aliases those
    shifts into wildly different normalized patterns — instances of one
    digit then scatter, mean templates blur into confusability, and
    self-consistency cleaning discarded 71% of a harvest before this was
    found. Area pooling is shift-stable."""
    x0, y0, x1, y1 = box
    crop = mask[y0:y1 + 1, x0:x1 + 1].astype(np.float32)
    h, w = crop.shape
    integ = np.zeros((h + 1, w + 1), np.float32)
    integ[1:, 1:] = crop.cumsum(0).cumsum(1)
    yb = np.linspace(0, h, GRID_H + 1).round().astype(int)
    xb = np.linspace(0, w, GRID_W + 1).round().astype(int)
    yb = np.maximum.accumulate(np.maximum(yb, np.arange(GRID_H + 1) *
                                          (yb[-1] >= GRID_H)))
    out = np.empty((GRID_H, GRID_W), np.float32)
    for i in range(GRID_H):
        yy0, yy1 = yb[i], max(yb[i + 1], yb[i] + 1)
        yy1 = min(yy1, h)
        yy0 = min(yy0, yy1 - 1) if yy1 > 0 else 0
        for j in range(GRID_W):
            xx0, xx1 = xb[j], max(xb[j + 1], xb[j] + 1)
            xx1 = min(xx1, w)
            xx0 = min(xx0, xx1 - 1) if xx1 > 0 else 0
            area = (yy1 - yy0) * (xx1 - xx0)
            out[i, j] = (integ[yy1, xx1] - integ[yy0, xx1]
                         - integ[yy1, xx0] + integ[yy0, xx0]) / max(area, 1)
    return out


class HudReader:
    """Per-frame HUD reads via template matching. Load once, call read()."""

    def __init__(self, font_path=DEFAULT_FONT):
        z = np.load(font_path, allow_pickle=False)
        self.templates = z["digits"]          # (10, GRID_H, GRID_W) float
        self.threshold = float(z["threshold"])
        # The wave line uses a SMALLER font with different glyph shapes
        # (digit widths 2-8px vs the score's 13-14) — score templates cannot
        # read it. Separate set, harvested from the wave strip.
        # MULTI-VARIANT (hardware round 7): wave_digits may hold MORE than
        # one template per digit — wave_labels[i] names the digit template i
        # represents. Real capture chains render these tiny glyphs just
        # differently enough that a single emulator-harvested template tops
        # out at ~0.78-0.85 on hardware (right at the threshold, scattering
        # with the per-wave palette); adding glyphs cropped from the
        # operator's own frames lets his rig self-match at ~1.0. Without a
        # labels array the set is the classic one-per-digit layout.
        self.wave_templates = z["wave_digits"] if "wave_digits" in z else None
        if "wave_labels" in z:
            self.wave_labels = z["wave_labels"].astype(int)
        elif self.wave_templates is not None:
            self.wave_labels = np.arange(len(self.wave_templates))
        else:
            self.wave_labels = None
        self.wave_threshold = (float(z["wave_threshold"])
                               if "wave_threshold" in z else self.threshold)
        # Lives icons sit nearly flush, so counting clusters reads 1 no
        # matter what. Model: extent ≈ icon_w + (n-1)*pitch (the intercept
        # matters — a zero-intercept fit skews the pitch badly).
        self.lives_pitch = float(z["lives_pitch"]) if "lives_pitch" in z else 0.0
        self.lives_icon_w = float(z["lives_icon_w"]) if "lives_icon_w" in z else 0.0
        # Optional letter/negative templates raise the effective floor: a
        # glyph must beat every negative to count as a digit.
        self.negatives = z["negatives"] if "negatives" in z else None
        self.n_read = 0
        self.n_reject = 0

    def _match_digit(self, g, templates=None, labels=None, neg_margin=0.0):
        """(best_digit, score in [0,1]) for a normalized glyph.

        `neg_margin`: veto a digit only when the best letter/negative beats
        it by at least this much. 0.0 = classic strict veto (score font).
        The wave font needs a small margin: on real hardware the operator's
        wave '9' matched 0.852 with the best negative at 0.854 — a 0.002
        photo-finish loss that silently dropped every wave-9 transition.
        Genuine letters beat their digit lookalike by 0.05-0.35, so a small
        margin costs nothing there."""
        T = self.templates if templates is None else templates
        d = 1.0 - np.abs(T - g[None]).mean(axis=(1, 2))
        i = int(d.argmax())
        s = float(d[i])
        digit = int(labels[i]) if labels is not None else i
        if self.negatives is not None and len(self.negatives):
            neg = 1.0 - np.abs(self.negatives - g[None]).mean(axis=(1, 2))
            if float(neg.max()) >= s + neg_margin:
                return digit, 0.0             # looks more like a letter
        return digit, s

    def _read_number(self, mask, max_digits, templates=None, threshold=None,
                     labels=None, neg_margin=0.0):
        """Left-to-right digit read of a strip mask. Returns (value|None,
        min_match). Rejects if any glyph is sub-threshold or the count is
        implausible. Trailing non-digit glyphs (letters, icons) are allowed:
        digits are taken from the LEADING run of confident matches."""
        th = self.threshold if threshold is None else threshold
        boxes = segment_glyphs(mask)
        if not boxes:
            return None, 0.0, 0
        digits, worst = [], 1.0
        for b in boxes[:max_digits + 6]:
            d, s = self._match_digit(normalize_glyph(mask, b), templates,
                                     labels=labels, neg_margin=neg_margin)
            if s < th:
                break                         # first non-digit ends the number
            digits.append(d)
            worst = min(worst, s)
        if not digits or len(digits) > max_digits:
            return None, 0.0, 0
        # The glyph COUNT is returned separately from the value: a fresh
        # game shows the score as "00", two glyphs for the number 0. Anyone
        # anchoring on len(str(value)) lands one glyph short.
        return int("".join(map(str, digits))), worst, len(digits)

    def read(self, frame):
        """frame: 1280x720 BGR. Returns dict(score, wave, lives, conf) — any
        field None when unreadable this frame."""
        self.n_read += 1
        sy0, sy1, sx0, sx1 = SCORE_STRIP
        wy0, wy1, wx0, wx1 = WAVE_STRIP
        s_strip = frame[sy0:sy1, sx0:sx1]
        w_strip = frame[wy0:wy1, wx0:wx1]

        s_mask = _score_mask(s_strip)
        score, s_conf, s_glyphs = self._read_number(s_mask, max_digits=8)
        # Every Robotron score event is a multiple of 25, so any read that
        # isn't ≡0 (mod 25) is a misread — a torn prefix ('9597' from
        # 95975) or menu digit-art ('2084'). One line kills both classes
        # that repeatedly defeated the temporal guards.
        if score is not None and score % 25 != 0:
            score, s_conf = None, 0.0

        w_mask = _wave_mask(w_strip)
        if self.wave_templates is not None:
            wave, w_conf, _ = self._read_number(
                w_mask, max_digits=3, templates=self.wave_templates,
                threshold=self.wave_threshold, labels=self.wave_labels,
                neg_margin=0.02)
            if wave == 0:
                # There is no wave 0: this is a two-digit wave whose leading
                # digit dropped out (a flash-dimmed '1' sliver leaves "10"
                # reading as "0" — seen live in round-8 telemetry).
                wave, w_conf = None, 0.0
        else:
            wave, w_conf = None, 0.0    # no wave font harvested — don't guess

        lives = None
        if score is not None and self.lives_pitch > 0:
            # Lives icons: coloured row RIGHT of the last score digit;
            # count = extent / pitch.
            boxes = segment_glyphs(s_mask)
            if boxes:
                # Anchor on the last glyph the score read CONSUMED, not on
                # len(str(score)): a new game displays "00", and anchoring
                # one glyph short swept the second '0' into the icon extent
                # (lives read 4 with 2 icons on screen), so the first real
                # score event "dropped" lives by 2 — the phantom death at
                # the start of every session's first game (round 10).
                last_digit_x = boxes[min(s_glyphs, len(boxes)) - 1][2]
                c_mask = _color_mask(s_strip)
                c_mask[:, :last_digit_x + 4] = False
                c_mask[:, last_digit_x + 4 + LIVES_WINDOW_PX:] = False
                cols = np.where(c_mask.any(axis=0))[0]
                if len(cols):
                    extent = int(cols[-1] - cols[0] + 1)
                    # Affine model fits exactly for n>=2 (icon_w is a fitted
                    # intercept, negative in practice — icons overlap); the
                    # single-icon extent (~11px) sits off the line and gets
                    # its own guard band.
                    if extent < 6:
                        lives = 0
                    elif extent < 13:
                        lives = 1
                    else:
                        lives = 1 + max(0, int(round(
                            (extent - self.lives_icon_w) / self.lives_pitch)))
                        if lives > 9:
                            # The display never shows more than 8 icons — a
                            # bigger value is a junk extent (sprite/explosion
                            # spill), and the bookkeeper's delta filter can't
                            # catch it on FIRST acceptance. Refuse it here.
                            lives = None
                else:
                    lives = 0
        if score is None and wave is None:
            self.n_reject += 1
        return dict(score=score, wave=wave, lives=lives,
                    conf=min(s_conf, w_conf))


class VisionBookkeeper:
    """Temporal state machine over HudReader frames: stable score/wave/lives,
    death and game-over events, and per-wave JSONL rows compatible with the
    emulator harness's wave log (so robotron/ab_yolo.py analyses hardware
    runs unchanged).

    THE HUD FLASHES. Score/wave/lives blink in and out of the frame as part
    of the game's normal rendering, so a large fraction of frames read None
    on every field. That is the expected steady state, not an error path:
    None reads pass through without resetting a pending value's agreement
    streak, and game-over is only inferred from a LONG sustained absence —
    far longer than any flash cycle or wave-transition blank.

    Robustness rules, each earned by a failure mode:
      * A value changes only after AGREE consecutive identical VALID reads
        (single-frame misreads never propagate; interleaved blank frames
        don't reset the streak).
      * Score is monotonic within a game (Robotron never subtracts); a lower
        stable score is either a misread (rejected) or, together with wave 1,
        a NEW GAME.
      * Deaths come from the lives-icon count dropping; extra men (every
        25k) raise it, which is not a death.
      * Sustained unreadable HUD (GAME_OVER_S with no valid read) after a
        valid game = game over.
    """
    # Per-field agreement requirements. Score changes every few reads, so
    # demanding consecutive agreement would make it permanently stale — its
    # safety comes from monotonicity + MAX_JUMP + self-heal instead. Lives
    # icon reads are the noisiest (death animations flash the row), and a
    # phantom lives-drop mints a phantom death, so lives demands the most.
    AGREE = {'score': 1, 'wave': 3, 'lives': 3}
    # Max plausible score gain between OCR reads (~200ms apart). The old
    # 100000 let a single digit-inserted misread jump the score 10x, which
    # self-heal later walked back — leaving a NEGATIVE wave delta in the log.
    # Nothing legitimate earns more than a few thousand in 200ms.
    MAX_JUMP = 25000
    # Sustained no-valid-read window before declaring game over. Must
    # comfortably exceed the worst legitimate blank stretch: HUD flash cycles
    # plus a death freeze plus a wave-transition splash can stack.
    GAME_OVER_S = 10.0

    def __init__(self, log_path=None, arm=None, on_event=None):
        self.log_path = log_path
        self.arm = arm or os.environ.get("ROBOTRON_ARM", "hardware")
        self.on_event = on_event or (lambda kind, **kw: None)
        self.game_id = f"{int(time.time() * 1000):x}"
        self.score = None
        self.wave = None
        self.lives = None
        self.deaths = 0
        self.wave_deaths = 0
        self.wave_score0 = 0
        self.max_wave = 0
        self.max_score = 0
        self.last_valid_t = None
        self.game_over_fired = False
        self._pend = {}          # field -> (value, count)
        self._down = (None, 0)   # stuck-high score self-heal candidate
        self._up = (None, 0)     # stuck-low score self-heal candidate
        self._last_player_t = 0.0
        self.last_advance_t = 0.0   # stable score last increased
        self._ng = 0             # new-game evidence accumulator
        self._last_no_hud_t = 0.0   # last sustained (>=5s) no-valid-HUD
                                    # episode; 0.0 = none seen yet (permissive)
        self._last_death_t = 0.0
        self._last_wave_t = 0.0
        self._lives_since = 0.0     # when the current lives value was set

    def _stable(self, field, value):
        """Hysteresis: return the newly-accepted value or None."""
        if value is None:
            return None
        cur = getattr(self, field)
        if value == cur:
            self._pend.pop(field, None)
            return None
        v, n = self._pend.get(field, (None, 0))
        n = n + 1 if v == value else 1
        self._pend[field] = (value, n)
        if n >= self.AGREE[field]:
            self._pend.pop(field, None)
            return value
        return None

    def _log_wave(self, wave_no, t):
        rec = {'t': round(t, 2), 'game': self.game_id, 'arm': self.arm,
               'wave': wave_no, 'deaths': self.wave_deaths,
               'lives': self.lives,
               # Clamped: a mid-wave self-heal can leave score < wave_score0
               # and a negative delta would poison downstream score stats.
               'score': max(0, (self.score or 0) - self.wave_score0),
               'src': 'hud_ocr'}
        if self.log_path:
            try:
                os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
                with open(self.log_path, "a") as f:
                    f.write(json.dumps(rec) + "\n")
            except OSError:
                pass
        self.on_event('wave_end', **rec)

    def _progressed(self):
        """Has the CURRENT game demonstrably been played? New-game/game-over
        transitions are only meaningful from a progressed game — without this
        gate, a 100-point backward misread during W1 re-declares 'new game'
        every few seconds."""
        return self.max_wave >= 2 or self.max_score >= 10000

    def _new_game(self, t):
        if self.wave is not None and not self.game_over_fired \
                and self._progressed():
            self.on_event('game_over', game=self.game_id, wave=self.max_wave,
                          score=self.max_score, deaths=self.deaths)
        self.game_id = f"{int(t * 1000):x}"
        self.score, self.wave, self.lives = 0, 1, None
        self.deaths = self.wave_deaths = 0
        self.wave_score0 = 0
        self.max_wave, self.max_score = 1, 0
        self.game_over_fired = False
        self._last_wave_t = t
        self.on_event('new_game', game=self.game_id)

    def feed(self, reading, t=None, player_visible=None):
        """Feed one HudReader.read() result. `player_visible`: whether the
        DETECTOR currently sees the player (game-over veto only).

        Deaths come from the LIVES ICONS DROPPING and nothing else. A
        player-disappearance death path existed through hardware round 6 and
        was removed: the real capture chain delivers ~45% duplicate frames
        and long detector blind streaks (48 streaks of 20+ frames in one
        five-game session), so every civilian pickup and wave transition
        minted phantom deaths, while the deaths it was meant to catch were
        actually the lives reader going blind past 100k (leading-'1'
        threshold miss — fixed in the font, not here).

        No arena-border input either (round 6, operator directive): some
        waves draw no border, and the HUD itself — score/wave reads passing
        the mod-25 and letter-negative gates — is the in-game signal. The
        HUD flashes, so absence only means anything when SUSTAINED."""
        t = t if t is not None else time.time()
        if player_visible:
            self._last_player_t = t
        if reading['score'] is not None or reading['wave'] is not None:
            self.last_valid_t = t
            self.game_over_fired = False
        elif self.last_valid_t is not None \
                and t - self.last_valid_t >= 5.0:
            # Sustained no-valid-HUD episode (game over screens, name entry,
            # menus). Recorded as context for new-game detection: a real new
            # game is always preceded by one of these. 5s comfortably
            # exceeds any legitimate in-game blank (flash cycles + death
            # freeze + wave wipe stack to ~4s worst case).
            self._last_no_hud_t = t

        # ── score (stable + monotonic) ──
        s = self._stable('score', reading['score'])
        if s is not None:
            if self.score is None:
                self.score = s
                self.last_advance_t = t
            elif s > self.score:
                if s - self.score <= self.MAX_JUMP:
                    self.score = s
                    self.last_advance_t = t
                    self._up = (None, 0)
                else:
                    # Persistent much-higher readings mean the BASELINE is a
                    # stuck-low torn read (round 3: score stuck at 343 while
                    # the real score was 34k+ — every honest update exceeded
                    # MAX_JUMP and was rejected, logging '+0' waves). Four
                    # consecutive oversized readings adopt the new level.
                    v, k = self._up
                    self._up = (s, k + 1)
                    if k + 1 >= 4:
                        print(f"[hud] score baseline heal {self.score} -> {s}")
                        self.score = s
                        self._up = (None, 0)
            elif s < self.score:
                # Regression: self-heal a stuck-high score (a rare too-high
                # misread that got accepted): a persistently repeated lower
                # value is the truth. New-game detection is NOT triggered
                # from here — see the evidence accumulator below.
                v, k = self._down
                self._down = (s, k + 1) if v == s else (s, 1)
                if self._down[1] >= 4:
                    self.score = s
                    self._down = (None, 0)
            self.max_score = max(self.max_score, self.score or 0)

        # ── wave (stable, +1 steps or restart) ──
        w = self._stable('wave', reading['wave'])
        if w is not None:
            if self.wave is None:
                self.wave = w
                self.wave_score0 = self.score or 0
            elif self.wave < w <= self.wave + 30:
                # Forward by 1: normal. Any bigger forward jump: we MISSED
                # transitions — resync. Hardware round 1 proved +1-only
                # pathological (stuck on W2 while the game hit W8); round 2
                # proved a +3 cap just recreates it at longer gaps (stuck at
                # W2 during a W11 game). A STABLE repeated forward read (AGREE
                # 3) is trustworthy at any plausible distance — misreads don't
                # repeat three times running.
                self._log_wave(self.wave, t)
                if w > self.wave + 1:
                    print(f"[hud] wave resync {self.wave} -> {w} "
                          f"(missed transitions)")
                self.wave = w
                self.wave_deaths = 0
                self.wave_score0 = self.score or 0
                self._last_wave_t = t
            # NOTE: stable w==1 alone no longer declares a new game — wave
            # "11" systematically reads as its prefix "1" when the second
            # digit dips sub-threshold, and systematic misreads DO repeat
            # (hardware round 2: a W11 game got reset mid-play). New games
            # come only from the evidence accumulator below.
            self.max_wave = max(self.max_wave, self.wave or 0)

        # ── new game: sustained, contradiction-free evidence ──
        # A real fresh game shows wave 1 AND a small score for many seconds.
        # A prefix misread ("11"->"1") co-occurs with score reads in the tens
        # of thousands, which CONTRADICT and reset the count. Requires 5
        # supporting reads with zero contradictions.
        contradiction = ((reading['wave'] is not None and reading['wave'] != 1)
                         or (reading['score'] is not None
                             and reading['score'] >= 10000))
        if contradiction:
            self._ng = 0
        elif reading['wave'] == 1:
            self._ng += 1
        # HUD-gap context: a real new game is always preceded by screens
        # with no valid HUD (game over / name entry / menus). No recent
        # sustained gap => no new game, whatever the digits say — this is
        # what stops the wave-'11'-reads-as-'1' chain mid-game even when
        # torn score reads slip past mod-25 (prefixes ending 00/25/50/75).
        hud_gap_ok = (self._last_no_hud_t == 0.0
                      or t - self._last_no_hud_t < 30.0)
        if (self._ng >= 5 and self.wave is not None and self.wave > 1
                and self._progressed() and hud_gap_ok):
            self._ng = 0
            self._new_game(t)

        # ── lives -> deaths ──
        lv = self._stable('lives', reading['lives'])
        if lv is not None:
            if self.lives is not None and abs(lv - self.lives) > 2:
                pass          # implausible jump — extent misread, ignore
            else:
                if self.lives is not None and lv < self.lives \
                        and t - self._last_death_t > 4.0 \
                        and t - self._lives_since >= 3.0:
                    # Real deaths drop EXACTLY one life; a 2-drop is a noisy
                    # extent settling (this is what produced the skipped
                    # death numbers in the first hardware round). Count one,
                    # at most one per 4s, and only from a value that has
                    # been HELD for 3s: a game-start / intro-junk read that
                    # settles within a couple of seconds is not a death (a
                    # real death sooner than 3s after the previous lives
                    # change was already discarded by the 4s dedupe).
                    self.deaths += 1
                    self.wave_deaths += 1
                    self._last_death_t = t
                    self.on_event('death', deaths=self.deaths, wave=self.wave)
                if lv != self.lives:
                    self._lives_since = t
                self.lives = lv

        # ── game over: HUD gone for a sustained stretch — AND the player is
        # not visibly alive. First hardware round fired GAME OVER mid-play
        # (patchy HUD reads); the detector seeing the player at 0.88-0.92 is
        # a strong veto the OCR gap can't fake.
        if (self.last_valid_t is not None and not self.game_over_fired
                and t - self.last_valid_t > self.GAME_OVER_S
                and t - getattr(self, '_last_player_t', 0) > self.GAME_OVER_S
                and self.wave is not None):
            self.game_over_fired = True
            self._log_wave(self.wave, t)
            self.on_event('game_over', game=self.game_id, wave=self.max_wave,
                          score=self.max_score, deaths=self.deaths)
        return dict(score=self.score, wave=self.wave, lives=self.lives,
                    deaths=self.deaths)
