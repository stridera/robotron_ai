"""
Game state reader: complete Robotron game state from JIT buffer + sprite lookup.

Provides a single GameState snapshot per frame with:
  - Wave, score, lives, frame counter
  - Player position (from slot 1 or PLAYER_POS address)
  - Every alive entity with: type, position, exact sprite dimensions, animation frame
  - Counter caps (remaining alive per type)

This is the foundation for bot brains — no ML needed, just direct memory reads.

Usage:
    from game_state import GameStateReader
    gsr = GameStateReader()
    while True:
        state = gsr.read()
        if state is None:
            continue
        for ent in state.entities:
            print(f"{ent.type} at ({ent.gx},{ent.gy}) {ent.w}x{ent.h}px frame {ent.anim_frame}")
"""

import math
import struct
import time
import os
import sys

from .xenia_memory import XeniaMemory
from .jit_entity_reader import (
    JitEntityReader, STATE_WORD_LABELS,
    DEFAULT_SLOT_COUNT, DEFAULT_SLOT_STRIDE,
)
from .sprite_lookup import SpriteLookup, ENTITY_LABEL

# Player position address in guest memory
PLAYER_POS_ADDR = 0x826E7864

# Civilian sprite_id ranges (from SPRITE_DATA.md — 12 animation frames × stride 4).
# If a CC/CW/CM slot has a sprite_id OUTSIDE its range, the civilian has been
# mutated into a Prog by a Brain; reclassify the entity as 'P'.
# Ranges are inclusive: [lo, hi].
_CIVILIAN_SPRITE_RANGES: dict[str, tuple[int, int]] = {
    'CC': (0x0B3B, 0x0B67),   # Civ_Child (Mikey): 12 frames
    'CW': (0x052F, 0x055B),   # Civ_Mom:           12 frames
    'CM': (0x07FF, 0x082B),   # Civ_Dad:           12 frames
}


# Quark sprite_id set — CORRECTED 2026-07-02 from the MAME-side anim-cluster
# validation (robotron-rl/mame_gym/ENEMY_MODEL.md §2, validate_entity_labels.py):
#   $50Cx cluster = Quark (state word 0x4BC9)      — the ONLY quark sprites
#   $502x cluster = Tank (state word 0x4DF2)       — removed 2026-03-31 (correct)
#   0x4FEE        = TANK SHELL anim block (0x4FD5) — was mislabeled "Quark3";
#                   this single entry manufactured the "teleporting quark" phantom
#                   (shells fly ~4-11 u/step and wall-bounce). REMOVED.
# The real 0x4800 "shared state word" never existed (phantom — nothing in the ROM
# loads #$4800); tank = 0x4DF2, shell = 0x4FD5.
_QUARK_SPRITE_IDS: frozenset = frozenset([
    0x50C2, 0x50C6, 0x50CA, 0x50CE, 0x50D2, 0x50D6, 0x50DA, 0x50DE, 0x50E2,  # Quark (9 frames)
])
# Tank-shell anim block start (see above). Exposed for the cmd classifier.
_SHELL_SPRITE_ID = 0x4FEE

# Approximate sprite pixel dimensions at 1280×720 for each entity label.
# Used in the entity_list path (which has no sprite_id from Pool 1) so that
# reviewer bounding boxes and YOLO labels use correct sizes per entity class.
# Values are (width_px, height_px) at the reference 1280×720 resolution.
# Measured empirically from gameplay screenshots 2026-03-25.
_ENTITY_DIMS: dict[str, tuple[int, int]] = {
    'G':  (20, 28),   # Grunt — taller than wide; head and feet need extra room
    'H':  (30, 36),   # Hulk  — wider and noticeably taller than other entities
    'E':  (18, 18),   # Electrode
    'B':  (22, 24),   # Brain
    'F':  (20, 22),   # Enforcer
    'FB': (10, 10),   # Enforcer Bullet — small fast projectile
    'C':  (16, 22),   # Civilian
    # Entities carry the sub-type label (CC/CW/CM), not 'C', so give each the
    # same dims — otherwise civilians silently fall back to the 20x20 default.
    'CC': (16, 22),   # Civilian Child (Mikey)
    'CW': (16, 22),   # Civilian Woman (Mom)
    'CM': (16, 22),   # Civilian Man (Dad)
    'S':  (28, 28),   # Spheroid
    'Q':  (20, 20),   # Quark (pre-Tank blob)
    'P':  (18, 20),   # Prog
    'T':  (26, 26),   # Tank (fully-formed)
    'TS': (10, 10),   # Tank Shell (projectile; small, fast, wall-bouncing)
    'MS': (12, 14),   # Cruise Missile (Brain-fired homing projectile)
}

# Authoritative label → type name.  Used in the entity_list path so that the
# display type is always consistent with the state_word classification.  The slot
# pool sprite_id can be stale between decoder calls (~15 Hz per entity) and may
# belong to a previously-occupying entity type; we use it only for dimensions.
_LABEL_TYPE = {
    'G': 'Grunt', 'H': 'Hulk', 'E': 'Electrode',
    'B': 'Brain', 'F': 'Enforcer', 'FB': 'Enforcer Bullet',
    'S': 'Sphereoid', 'Q': 'Quark', 'P': 'Prog', 'T': 'Tank', 'TS': 'Tank Shell',
    'MS': 'Cruise Missile',
    'CC': 'Civ_Child', 'CW': 'Civ_Mom', 'CM': 'Civ_Dad',
}


class Entity:
    """A single entity in the current frame."""
    __slots__ = ('slot', 'type', 'label', 'gx', 'gy',
                 'state_word', 'sprite_id', 'anim_frame',
                 'w', 'h', 'static_frames', 'alive')

    def __init__(self):
        self.slot = 0
        self.type = ''      # e.g. 'Grunt', 'Civ_Mom'
        self.label = ''     # e.g. 'G', 'C'
        self.gx = 0
        self.gy = 0
        self.state_word = 0
        self.sprite_id = 0
        self.anim_frame = -1  # -1 = unknown
        self.w = 0          # sprite width in pixels
        self.h = 0          # sprite height in pixels
        self.static_frames = 0
        self.alive = True

    def __repr__(self):
        return (f"Entity({self.type} slot={self.slot} "
                f"({self.gx},{self.gy}) {self.w}x{self.h} "
                f"sf={self.static_frames})")


class GameState:
    """Snapshot of the complete game state for one frame."""
    __slots__ = ('frame', 'outer_loop_count', 'wave', 'score', 'lives',
                 'player_gx', 'player_gy',
                 'entities', 'counter_caps',
                 'raw_slot_count', 'write_mask', 'timestamp',
                 'entity_source', 'b3c80_call_count', 'slot_entity_count',
                 'lists_6809', 'raw_slots', 'active_hook_entities')

    def __init__(self):
        self.frame = 0
        self.outer_loop_count = 0   # true 60Hz frame counter from RobotronOuterLoopHook
        self.wave = 0
        self.score = 0
        self.lives = 0
        self.player_gx = 0
        self.player_gy = 0
        self.entities = []
        self.counter_caps = {}
        self.raw_slot_count = 0
        self.write_mask = 0         # 101-bit mask: bit i=1 → slot i alive this frame
        self.timestamp = 0.0
        self.entity_source = 'entity_list'
        self.b3c80_call_count = 0   # total B3C6C hook fires last frame (incl. rejected)
        self.slot_entity_count = 0  # slots with recognized state_words in raw slot pool
        self.lists_6809 = {}        # authoritative alive lists from 6809 RAM linked lists
        self.raw_slots  = None      # raw slot pool bytes (bytearray) — saved in captures
        self.active_hook_entities = []  # raw per-frame active-hook entries (incl. _SKIP / unknown)

    @property
    def in_game(self):
        """True if we appear to be in active gameplay.

        Lives can be a normal value (1-99) or 0xFFFFFFFF in XBLA mode.
        We verify by checking for entities with recognized state_words
        and a non-zero player position.
        """
        if self.wave == 0:
            return False
        # Must have at least some recognized entities
        if len(self.entities) == 0 and self.raw_slot_count == 0:
            return False
        # Player must be on the playfield
        if self.player_gx == 0 and self.player_gy == 0:
            return False
        return True

    def entities_by_type(self, label):
        """Get all entities matching a label (e.g. 'G' for Grunt)."""
        return [e for e in self.entities if e.label == label]

    def nearest_threat(self, threat_labels=('G', 'H', 'B', 'F', 'FB', 'E', 'S', 'Q', 'P',
                                            'T', 'TS', 'MS')):
        """Find the nearest threat entity to the player. Returns (entity, distance) or (None, inf)."""
        best = None
        best_dist = float('inf')
        for e in self.entities:
            if e.label not in threat_labels:
                continue
            dx = e.gx - self.player_gx
            dy = e.gy - self.player_gy
            dist = (dx * dx + dy * dy) ** 0.5
            if dist < best_dist:
                best_dist = dist
                best = e
        return best, best_dist

    def nearest_civilian(self):
        """Find the nearest civilian. Returns (entity, distance) or (None, inf)."""
        best = None
        best_dist = float('inf')
        for e in self.entities:
            if e.label not in ('CC', 'CW', 'CM'):
                continue
            dx = e.gx - self.player_gx
            dy = e.gy - self.player_gy
            dist = (dx * dx + dy * dy) ** 0.5
            if dist < best_dist:
                best_dist = dist
                best = e
        return best, best_dist

    def summary(self):
        from collections import Counter
        types = Counter(e.label for e in self.entities)
        parts = [f"{k}={v}" for k, v in sorted(types.items())]
        return (f"F{self.frame} W{self.wave} S{self.score} L{self.lives} "
                f"P({self.player_gx},{self.player_gy}) "
                f"{len(self.entities)} ents: {' '.join(parts)}")


class GameStateReader:
    """Reads complete game state from JIT buffer + sprite lookup."""

    def __init__(self, mem=None):
        if mem is None:
            mem = XeniaMemory('xenia_canary.exe')
        self.mem = mem
        self.jit = JitEntityReader(mem)
        self.sprites = SpriteLookup(mem)
        self._last_frame = -1
        self._last_outer_loop_count = -1
        self._last_empty_warn = 0.0
        self._last_filter_warn = 0.0
        # Cache of slot_idx → (gx, gy) for static entities (E, S) sourced from
        # the command table via the entity_list hook. Cleared on wave change.
        self._static_pos_cache: dict = {}
        self._static_cache_wave: int = 0
        # Python-side write_mask accumulator (used only in fallback path).
        self._mask_entries: list = []  # list of (timestamp_float, mask_int)
        # entity_list cache: persists the most recent non-empty entity_list across
        # b3c=0 gaps (where the outer loop resets the count before repopulating).
        # slot_idx → entity_list entry dict.  Cleared on wave change.
        self._elist_cache: dict = {}   # slot_idx → _el dict (most recent)
        self._elist_cache_time: float = 0.0  # timestamp of last non-empty update
        # Wave-start / respawn time — used for ghost-filter grace period.
        # Reset on both wave change AND death (lives decrease) to suppress ghosts
        # during wave transitions and respawns.
        self._wave_start_time: float = 0.0
        self._last_lives: int = -1  # detects death (lives decrease)
        # Electrode position tracking for cross-wave ghost filtering.
        # W(N-1) ghost electrodes appear at W(N-1) positions. After the grace period,
        # electrodes at previous-wave positions that have no write_mask activity are
        # filtered as ghosts. Real W(N) electrodes are at new positions (not in prev set),
        # or if at the same position, they would have briefly had write_mask=1 at wave init.
        self._cur_electrode_positions: set = set()   # (gx, gy) tuples seen this wave
        self._prev_electrode_positions: set = set()  # (gx, gy) from previous wave
        # Stable pseudo-slot assignment for Pool 1 entities (slot_idx=0xFF sentinel).
        # All 6809-sourced entities share slot=0xFF, breaking VelocityTracker (dict
        # key collision) and GoalSelector (all same-type entities match the target slot).
        # Fix: nearest-neighbour matching per label assigns stable IDs across frames.
        self._pool1_prev: dict = {}   # pseudo_slot → (label, gx, gy)
        self._pool1_next_id: int = 200  # IDs 200+ are Pool 1 pseudo-slots

    def peek_frame_counter(self):
        """Cheap read of the 60Hz outer_loop_count WITHOUT the entity walk.
        For frame-sync: spin on this until it ticks over, then call read() so the
        list walk lands right after the game's frame update. Returns None if the
        JIT buffer is unavailable."""
        try:
            if not self.jit.available:
                return None
            header, _static, _slots = self.jit.read_buffer()
            if not header:
                return None
            return header.get('outer_loop_count', 0)
        except Exception:
            return None

    def read(self, wait_new_frame=True):
        """Read current game state. Returns GameState or None.

        Entity data comes exclusively from the per-frame active-hook entity list.
        Returns None if the frame hasn't changed (wait_new_frame=True) or if
        the JIT buffer is unavailable.

        If the entity list is empty (active hook not producing entities), state.entities will be
        empty and a diagnostic warning is printed to stderr.
        """
        if not self.jit.available:
            return None

        header, static_frames, raw_slots = self.jit.read_buffer()
        if not header or raw_slots is None:
            return None

        frame = header['frame']
        outer_loop_count = header.get('outer_loop_count', 0)
        write_mask = header.get('write_mask', 0)

        # Update the Python-side write_mask accumulator.
        _now = time.time()
        if write_mask:
            self._mask_entries.append((_now, write_mask))
        # Accumulator window (~15-frame C++ cycle). Kept at 0.280 for stability;
        # the real fix is to drop this accumulator entirely for direct 6809
        # linked-list walks (MAME parity) — see the list-walk migration.
        _MASK_WINDOW = float(os.environ.get("ROBOTRON_MASK_WINDOW", "0.280"))
        self._mask_entries = [(t, m) for t, m in self._mask_entries
                              if _now - t < _MASK_WINDOW]
        _accum_mask = 0
        for _, m in self._mask_entries:
            _accum_mask |= m

        # Use outer_loop_count (true 60Hz boundary) for new-frame detection.
        if outer_loop_count > 0:
            if wait_new_frame and outer_loop_count == self._last_outer_loop_count:
                return None
            self._last_outer_loop_count = outer_loop_count
        else:
            if wait_new_frame and frame == self._last_frame:
                return None
        self._last_frame = frame

        state = GameState()
        state.frame = frame
        state.outer_loop_count = outer_loop_count
        state.wave = header['wave']
        state.score = header['score']
        state.lives = header['lives']
        state.raw_slot_count = header['raw_slot_count']
        state.write_mask = write_mask
        state.b3c80_call_count = header.get('b3c80_call_count', 0)
        state.timestamp = time.time()
        state.raw_slots  = raw_slots   # kept for offline reanalysis in captures
        state.active_hook_entities = list(header.get('entity_list', []))

        # Count slot pool entries with recognized state_words (ground truth —
        # independent of the active entity hook).  If this is > 0 but entity_list = 0,
        # the hook is the problem (not the game state).
        slot_ent_count = 0
        for _si in range(DEFAULT_SLOT_COUNT):
            _off = _si * DEFAULT_SLOT_STRIDE
            if _off + 6 <= len(raw_slots):
                _sw = (raw_slots[_off + 4] << 8) | raw_slots[_off + 5]
                if _sw in STATE_WORD_LABELS:
                    slot_ent_count += 1
        state.slot_entity_count = slot_ent_count

        # Read player position from guest memory
        try:
            pos_data = self.mem.read_guest(PLAYER_POS_ADDR, 4)
            state.player_gx = pos_data[0]
            state.player_gy = pos_data[2] if len(pos_data) > 2 else 0
        except Exception:
            state.player_gx = 0
            state.player_gy = 0

        # === Entity sourcing: 6809 linked-list walks (MAME parity, 2026-07-03) ===
        # Replaces the C++ write-mask/accumulator + slot-scan + entity_list paths.
        # Reachable-on-list = ALIVE (ghost-free by construction, like MAME); the
        # STATE WORD at node +8 classifies; position from +4/+5. No accumulator
        # staleness, no caps, no static_frames. Verified live: every type on the
        # correct head. See project_6809_listwalk_migration.
        state.entity_source = 'listwalk_6809'
        state.entities = self._walk_all_lists_alive()
        # Safety net: drop out-of-bounds positions (torn reads / spawn artifacts).
        state.entities = [e for e in state.entities
                          if 0 <= e.gx <= 155 and 10 <= e.gy <= 240]
        return state

        # ── LEGACY hook/slot-scan path below (unreachable; kept for reference) ──
        # WAVE_DATA hard constraints — applied as post-filter to both paths
        # (handles stale state_words in slot pool from previous games)
        # Columns: G, E, C, H, B, S, Q, F, FB
        _WAVE_CAPS_LABELS = ('G', 'E', 'C', 'H', 'B', 'S', 'Q', 'F', 'FB')
        _WAVE_DATA = {
            # (G, E, C, H, B, S, Q, F, FB) — based on observed entity counts
            # Q=0 on waves 1-2: Quarks don't appear until wave 3 (MEMORY_MAP.md)
            # F and FB caps are high (16/32) because Spheroids continuously spawn
            # Enforcers; by mid-wave you can have 3-4× the initial Spheroid count.
            1:(15,5,2,1,0,1,0, 8,16),  2:(17,15,3,5,0,2,0, 8,16),
            3:(22,25,6,6,0,3,2,16,32), 4:(34,25,6,7,0,4,2,16,32),
            5:(20,20,16,0,15,1,2,16,32), 6:(32,25,9,7,0,4,2,16,32),
            7:(0,0,12,12,0,0,10,16,32), 8:(35,25,9,8,0,5,2,16,32),
            9:(60,0,9,4,0,5,2,16,32),
        }

        # === Primary entity source: slot pool snapshot (OuterLoopHook) ===
        # The C++ OuterLoopHook walks the slot pool snapshot each frame and
        # publishes all slots with recognized state_words as entity_list.
        # Ghost filter: slots unchanged for >_GHOST_SF_THRESH consecutive frames
        # are treated as dead (stale slot data from a previous entity).
        # Electrodes (0x3AA9) are exempt — they are permanently static by design.
        _elist = header.get('entity_list', [])
        state.entity_source = 'entity_list_slot_pool'

        # Ghost filter (moving entities only):
        #   write_mask bit set by StateStoreHook every rendered frame.
        #   Dead slot → not written → mask_bit=False → skip.
        # Electrodes are skipped here; they are added from the 6809 linked list
        # below (authoritative, ghost-free by construction).
        _ELECTRODE_SW = 0x3AA9

        # Track wave changes (used only for the empty-warn reset).
        if state.wave != self._static_cache_wave:
            self._static_cache_wave = state.wave
            self._wave_start_time = time.time()
            self._pool1_prev.clear()  # new wave → all entity identities reset

        for _el in _elist:
            lbl = _el.get('label', '')
            if not lbl or lbl == '_SKIP':
                continue  # Skip non-entity state words (player, explosions)
            _sw = _el.get('state_word', 0)
            _slot_idx = _el.get('slot_idx', 0xFF)

            if lbl == 'E':
                continue  # Electrodes come from the 6809 Electrodes list below.

            # All other entities: write_mask is authoritative for slot-pool entries.
            # 6809-sourced entries carry slot_idx=0xFF (sentinel) — they are alive
            # by construction (dead nodes are unlinked from the list), so bypass
            # the write-mask check entirely for that sentinel value.
            if _slot_idx == 0xFF:
                _mask_bit = True  # 6809 node reachable ⟹ alive
            else:
                _mask_bit = bool((_accum_mask >> _slot_idx) & 1) if 0 <= _slot_idx < 128 else False
            if not _mask_bit:
                continue
            ent = Entity()
            ent.slot       = _slot_idx
            ent.state_word = _sw
            ent.gx         = _el['pos_a']
            ent.gy         = _el['pos_b']
            ent.alive      = True
            ent.static_frames = static_frames[_slot_idx] if _slot_idx < len(static_frames) else 0

            # --- Prog reclassification ---
            # Brains mutate civilians into Progs; the state_word stays the same
            # (CC/CW/CM) but the sprite_id changes to non-civilian frames.
            # Prog detection on Brain waves (5, 10, 15 …):
            # When a Brain mutates a civilian the slot-pool state_word changes
            # 0x0335/0x033A/0x0330 → 0x1F1F immediately, but the JIT render hook
            # still reports state_word 0x0335 (CW) because it reads a different
            # memory path.  Detection: if a 0x1F1F slot exists at the same game
            # position as a Pool1 civilian → the civilian has been mutated → Prog.
            # Threshold 8 units: Prog slot gx/gy matches Pool1 exactly at mutation;
            # the gap grows slowly as the entity walks (slot pos is STATIC after
            # mutation), so a tight threshold avoids false matches with real MS
            # missiles that also carry state_word 0x1F1F.
            if (lbl in _CIVILIAN_SPRITE_RANGES and raw_slots is not None
                    and state.wave % 5 == 0):   # Progs only appear on Brain waves (5, 10, 15…)
                _is_prog = False
                if _slot_idx == 0xFF:
                    # Pool1 entity — scan for a 0x1F1F slot at a matching position.
                    _PROG_SW   = 0x1F1F
                    _PROG_DIST = 8          # tight: mutation point matches exactly
                    _total_slots = len(raw_slots) // DEFAULT_SLOT_STRIDE
                    for _csi in range(_total_slots):
                        _coff = _csi * DEFAULT_SLOT_STRIDE
                        if _coff + 6 > len(raw_slots):
                            break
                        if (raw_slots[_coff + 4] << 8 | raw_slots[_coff + 5]) != _PROG_SW:
                            continue
                        if (abs(raw_slots[_coff] - ent.gx) +
                                abs(raw_slots[_coff + 1] - ent.gy)) <= _PROG_DIST:
                            _is_prog = True
                            break
                if _is_prog:
                    lbl = 'P'

            # Q/T/TS discrimination: the C++ Pool-1 walker (x64_sequences.cc)
            # still uses the PRE-2026-07-02 mapping (quark sprites → 0x4DF2 'Q',
            # tanks → phantom 0x4800). The Python cmd classifier below is
            # corrected (Q=0x4BC9, T=0x4DF2, TS=0x4FD5 per ENEMY_MODEL.md §2);
            # rebuild the hook with matching kQuarkCmds when possible.

            ent.label = lbl
            ent.type  = _LABEL_TYPE.get(lbl, lbl)
            _dims = _ENTITY_DIMS.get(lbl, (20, 20))
            ent.w = _dims[0]
            ent.h = _dims[1]
            state.entities.append(ent)

        # === Supplementary slot pool scan for G/H/B/F/FB/Q/P/T ===
        # F/FB/Q/P/T have pos=(0,0) in entity_list (command table position offset differs).
        # G/H/B come from Pool 1 in entity_list (slot_idx=0xFF, no write_mask validation).
        # Pool 1 walk lags 1-2 frames after death → ghost FP for G/H/B.
        # Fix: scan slot pool directly for G/H/B (as well as F/FB/Q/P/T).
        # Slot bytes[0]=gx, bytes[1]=gy are correct for all types except Electrodes
        # (handled by 6809 list) and Spheroids (gy=0 in slot, valid in list).
        # write_mask filter applies: slot must have been written recently to be alive.
        _SLOT_SCAN_LABELS = frozenset({'F', 'FB', 'Q', 'P', 'T'})
        # static_frames threshold: slots unchanged for more than this many frames are
        # treated as dead (entity stopped rendering = killed).  Alive entities at 15 Hz
        # update rate write every ~4 frames; threshold of 7 (filter sf≥8) gives a 2×
        # safety margin while catching dead/frozen slots within ~133 ms.
        # Observed: alive Grunts have sf 0–7; game-over/dead entities jump to sf=8+.
        _GHOST_SF_THRESH = 7
        if raw_slots is not None:
            for _si in range(DEFAULT_SLOT_COUNT):
                _off = _si * DEFAULT_SLOT_STRIDE
                if _off + 6 > len(raw_slots):
                    break
                _sw2 = (raw_slots[_off + 4] << 8) | raw_slots[_off + 5]
                _lbl2 = STATE_WORD_LABELS.get(_sw2)
                if _lbl2 not in _SLOT_SCAN_LABELS:
                    continue
                _sf2 = static_frames[_si] if _si < len(static_frames) else 0
                if _sf2 > _GHOST_SF_THRESH:
                    continue  # slot stale → entity dead
                _mask_bit2 = bool((_accum_mask >> _si) & 1) if 0 <= _si < 128 else False
                if not _mask_bit2:
                    continue
                ent2 = Entity()
                ent2.slot       = _si
                ent2.label      = _lbl2
                ent2.type       = _LABEL_TYPE.get(_lbl2, _lbl2)
                ent2.gx         = raw_slots[_off]
                ent2.gy         = raw_slots[_off + 1]
                ent2.state_word = _sw2
                ent2.alive      = True
                ent2.static_frames = static_frames[_si] if _si < len(static_frames) else 0
                _dims2 = _ENTITY_DIMS.get(_lbl2, (20, 20))
                ent2.w, ent2.h  = _dims2
                state.entities.append(ent2)

        # === 6809 linked list sources ===
        def _make_ent_from_6809(lbl, sw, gx, gy):
            e = Entity()
            e.slot       = 0xFF   # pseudo-slot; assigned below
            e.label      = lbl
            e.type       = _LABEL_TYPE.get(lbl, lbl)
            e.gx         = gx
            e.gy         = gy
            e.state_word = sw
            e.alive      = True
            _d = _ENTITY_DIMS.get(lbl, (20, 20))
            e.w, e.h     = _d
            return e

        # Electrodes: 6809 Electrodes list is the authoritative active-electrode source.
        # cmd=0x3B05 maps to 'E' (confirmed from 6809 RAM dump).
        # Ghost-filter: a second read of the same list is done after _read_6809_lists()
        # below and used to cross-validate positions (stale nodes unlinked between reads).
        _elec_first_positions: set = set()   # (gx, gy) from this read
        for _cmd, _gx, _gy in self._walk_6809_list(self._6809_LIST_HEADS['Electrodes']):
            _lbl, _sw = self._cmd_to_label(_cmd)
            if _lbl == 'E' and _gx > 0 and _gy > 0:
                state.entities.append(_make_ent_from_6809(_lbl, _sw, _gx, _gy))
                _elec_first_positions.add((_gx, _gy))
                pass  # debug removed

        # Civilians (supplementary): civilians start in Pool1/slot-scan (first ~25s of wave).
        # After ~25s they migrate to their own pool at 6809 offset ~0x373B, at which point
        # their Pool1 slots are freed and the slot-scan path no longer sees them.
        # Walking this list adds them back after migration. No duplicates: Pool1 slot cleared
        # at migration time, so the slot-scan path will have already dropped them.
        for _cmd, _gx, _gy in self._walk_6809_list(self._6809_LIST_HEADS['Civilians']):
            _lbl, _sw = self._cmd_to_label(_cmd)
            if _lbl in ('CC', 'CW', 'CM'):
                state.entities.append(_make_ent_from_6809(_lbl, _sw, _gx, _gy))

        # === Stable pseudo-slot assignment for Pool 1 entities (slot=0xFF) ===
        # All entities from the 6809 Pool 1 free-list walk share slot_idx=0xFF,
        # which causes VelocityTracker key collisions (multiple entities overwrite
        # the same slot key) and broken GoalSelector target tracking (all entities
        # of the same type match the stored target slot).
        #
        # Fix: nearest-neighbour matching by label+position assigns each Pool 1
        # entity a stable pseudo-slot ID (>= 200) that persists across frames as
        # long as the entity stays within 20 game units of its previous position.
        # On wave change, _pool1_prev is cleared so IDs reset cleanly.
        _pool1_ents = [_e for _e in state.entities if _e.slot == 0xFF]
        if _pool1_ents:
            _prev   = self._pool1_prev     # pseudo_slot → (label, gx, gy)
            _used   = set()                # pseudo-slots assigned this frame
            _next   = {}                   # pseudo_slot → (label, gx, gy) for next frame

            # Build candidate matches: (dist, pseudo_slot, entity) sorted by dist.
            _candidates = []
            for _pe in _pool1_ents:
                for _pid, (_plbl, _pgx, _pgy) in _prev.items():
                    if _plbl != _pe.label:
                        continue
                    _d = math.sqrt((_pe.gx - _pgx) ** 2 + (_pe.gy - _pgy) ** 2)
                    if _d < 20.0:
                        _candidates.append((_d, _pid, _pe))
            _candidates.sort(key=lambda x: x[0])

            # Greedy nearest-first assignment.
            _assigned_ents = set()
            for _d, _pid, _pe in _candidates:
                if _pid in _used or id(_pe) in _assigned_ents:
                    continue
                _pe.slot = _pid
                _used.add(_pid)
                _assigned_ents.add(id(_pe))
                _next[_pid] = (_pe.label, _pe.gx, _pe.gy)

            # Unmatched entities (new this frame) get fresh IDs.
            for _pe in _pool1_ents:
                if id(_pe) not in _assigned_ents:
                    _pid = self._pool1_next_id
                    self._pool1_next_id += 1
                    _pe.slot = _pid
                    _next[_pid] = (_pe.label, _pe.gx, _pe.gy)

            self._pool1_prev = _next

        if not state.entities and state.wave > 0 and state.lives > 0:
            _now = time.time()
            if _now - self._last_empty_warn > 5.0:
                self._last_empty_warn = _now
                print(f"[game_state] W{state.wave}: entity_list empty "
                      f"(slot_ent_count={slot_ent_count})",
                      file=sys.stderr)

        # (Removed 2026-07-02) The old "dedupe TS ghosts near Quarks" post-filter
        # was built on the 0x4DF2-is-a-shell mislabel; with the corrected table
        # (0x4DF2=Tank, 0x4FD5=Shell, ENEMY_MODEL.md §2) shells are genuinely
        # distinct entities and that filter would DELETE real shells passing a
        # quark. If the C++ hook still emits pre-fix duplicates on the
        # entity_list path, fix kQuarkCmds in x64_sequences.cc instead.

        # Post-filter: remove entities with clearly out-of-bounds positions.
        # GY_LO=10 catches Hulks at gy=4 that appear to be off the top of screen.
        _GX_LO, _GX_HI = 0, 155
        _GY_LO, _GY_HI = 10, 240
        if state.entities:
            before_pos = len(state.entities)
            state.entities = [
                _e for _e in state.entities
                if _GX_LO <= _e.gx <= _GX_HI and _GY_LO <= _e.gy <= _GY_HI
            ]
            removed_pos = before_pos - len(state.entities)
            if removed_pos > 0:
                _now = time.time()
                if _now - self._last_filter_warn > 5.0:
                    self._last_filter_warn = _now
                    print(f"[game_state] W{state.wave}: pos-filter removed "
                          f"{removed_pos} out-of-bounds ents", file=sys.stderr)

        # Post-filter: enforce WAVE_DATA constraints.
        if state.wave > 0 and state.entities:
            wd = _WAVE_DATA.get(state.wave)
            if wd:
                wave_caps_pf = dict(zip(_WAVE_CAPS_LABELS, wd))
                before = len(state.entities)
                from collections import defaultdict as _dd
                by_lbl: dict = _dd(list)
                for _e in state.entities:
                    by_lbl[_e.label].append(_e)
                filtered_ents = []
                for _lbl, _ents in by_lbl.items():
                    wmax = wave_caps_pf.get(_lbl)
                    if wmax is not None and wmax == 0:
                        continue
                    elif wmax is not None:
                        # Sort by static_frames ascending (freshest first) before capping.
                        # This prefers recently-updated (alive) entities over stale (dead) ones.
                        _sorted = sorted(_ents, key=lambda _e: _e.static_frames)
                        filtered_ents.extend(_sorted[:wmax])
                    else:
                        filtered_ents.extend(_ents)
                removed_ents = [_e for _e in state.entities if _e not in filtered_ents]
                state.entities = filtered_ents
                removed = before - len(state.entities)
                if removed > 0:
                    _now = time.time()
                    if _now - self._last_filter_warn > 5.0:
                        self._last_filter_warn = _now
                        from collections import Counter as _Ctr2
                        rm_types = dict(_Ctr2(e.label for e in removed_ents))
                        print(f"[game_state] W{state.wave}: wave-cap removed "
                              f"{removed} ents: {rm_types}", file=sys.stderr)

        # No 'T' count cap: the ASM spawns 1 + rand(ctl)/2 tanks per quark with a
        # global SIMULTANEOUS limit of 20 (CMPA #$14 at $4C43), not a per-wave count.
        # The write_mask + static_frames ghost filters already drop dead tanks, so a
        # count cap only risked deleting real live tanks on quark waves (12/17/22
        # already ran uncapped, safely). Removed 2026-07-03.

        # Read 6809 linked lists for authoritative alive entity counts (second read).
        # Also used for electrode ghost-filtering: the second read is slightly later
        # than the first (line ~465) — nodes for just-killed electrodes are often
        # already unlinked by the time of this read, so ghost positions disappear.
        state.lists_6809 = self._read_6809_lists()

        # === Electrode ghost filter (double-read validation) ===
        # Keep only E entities whose position appears in the second (logging) read.
        # Ghost electrodes: still in list at first read (stale node), unlinked by
        # second read → position absent → removed.
        # Real electrodes missing from first read (list updated between reads):
        # added from second read so they're never dropped.
        _elec_second: list = [
            (e['gx'], e['gy'])
            for e in state.lists_6809.get('Electrodes', [])
            if self._cmd_to_label(e['cmd'])[0] == 'E' and e['gx'] > 0 and e['gy'] > 0
        ]
        _elec_second_set: set = set(_elec_second)

        # Remove ghost E entities (position not confirmed by second read).
        _before_e = [(e.gx, e.gy) for e in state.entities if e.label == 'E']
        state.entities = [
            e for e in state.entities
            if e.label != 'E' or (e.gx, e.gy) in _elec_second_set
        ]
        # Add real E entities present in second read but absent from first read.
        _e_positions_in_state: set = {(e.gx, e.gy) for e in state.entities if e.label == 'E'}
        for _gx2, _gy2 in _elec_second:
            if (_gx2, _gy2) not in _e_positions_in_state:
                state.entities.append(_make_ent_from_6809('E', 0x3AA9, _gx2, _gy2))
                pass  # debug removed
        # Log removals (debug removed).

        return state

    # ─── 6809 linked list reader ──────────────────────────────────────────
    # 6809 RAM base in PPC address space.
    _6809_RAM_BASE = 0x826DE000

    # List head addresses (PPC absolute). Each holds a u16 BE offset to the
    # first entity in the linked list (0 = empty).
    #
    # Verified against x64_sequences.cc diagnostic kListHeads table (2026-03-30):
    #   TanksSph    = 0x9703  → PPC 0x826E7703  ✓
    #   RealEnemies = 0x9811  → PPC 0x826E7811  (was mislabeled 'Enforcers')
    #   Electrodes  = 0x9823  → PPC 0x826E7823  (was off-by-1: 0x826E7824)
    #   Civilians   = 0xA00A  → PPC 0x826E800A  ✓
    #   Unknown     = 0xA05F  → PPC 0x826E805F  (was mislabeled 'Enemies'; purpose unknown)
    _6809_LIST_HEADS = {
        'Enemies':    0x826E7811,  # RealEnemies: Grunts, Hulks, Brains, Progs
        'Civilians':  0x826E800A,  # Civilians: CC/CW/CM
        'Enforcers':  0x826E805F,  # Unknown list (possibly Enforcer/Prog) — keep for logging
        'Electrodes': 0x826E7823,  # Electrodes (fixed off-by-1)
        'TanksSph':   0x826E7703,  # Tanks, Spheroids, Quarks
    }

    # Pool1 cmd → (label, state_word) mapping — mirrors x64_sequences.cc Pool1 walker.
    # Used to classify entities from 6809 linked lists by their cmd byte.
    _CMD_RANGES: list = [
        (0x4060, 0x40C0, 'G',  0x3A76),   # Grunt
        (0x3B00, 0x3BC0, 'E',  0x3AA9),   # Electrode (0x3B85 seen in W8+; extend range)
        (0x0520, 0x0560, 'CW', 0x0335),   # Civilian type 1 (Mom)
        (0x07F8, 0x0830, 'CM', 0x033A),   # Civilian type 2 (Dad)
        (0x0CF0, 0x0D20, 'H',  0x00B6),   # Hulk
        (0x0B30, 0x0B70, 'CC', 0x0330),   # Civilian child (Mikey)
        (0x14F0, 0x1510, 'S',  0x12C8),   # Spheroid
        (0x18D0, 0x18F0, 'F',  0x1483),   # Enforcer
        (0x1A30, 0x1A50, 'FB', 0x14DC),   # Enforcer spark (sw 0x14DC per ASM — CREATE_SPARK)
        (0x1F60, 0x2060, 'P',  0x1F1F),   # Prog (human-range anims)
        (0x2060, 0x2080, 'MS', 0x2119),   # Cruise Missile (anim $206B, handler 0x2119 —
                                          #   was swallowed by the Prog range pre-2026-07-02)
        (0x2140, 0x2170, 'B',  0x1DD6),   # Brain
    ]

    @classmethod
    def _cmd_to_label(cls, cmd: int):
        """Map a Pool1/6809 cmd byte to (label, state_word), or (None, 0) if unknown.
        Quark/Tank discrimination (both in [0x4FC0,0x5100)) is handled separately.
        """
        for lo, hi, lbl, sw in cls._CMD_RANGES:
            if lo <= cmd < hi:
                return lbl, sw
        # Quark / Tank / Tank-Shell range — CORRECTED 2026-07-02 per the MAME-side
        # anim-cluster validation (ENEMY_MODEL.md §2): $50Cx=Quark(0x4BC9),
        # $502x=Tank(0x4DF2), 0x4FEE block=Tank Shell(0x4FD5). The old mapping
        # lumped shells+tanks into 'Q' and used the phantom 0x4800 for tanks.
        # NOTE: the C++ hook (x64_sequences.cc kQuarkCmds) still carries the old
        # discrimination for the entity_list path — needs the same fix + rebuild.
        if 0x4FC0 <= cmd < 0x5100:
            if cmd in _QUARK_SPRITE_IDS:
                return 'Q', 0x4BC9
            if 0x4FC0 <= cmd < 0x500E:          # shell anim block (0x4FEE ±)
                return 'TS', 0x4FD5
            return 'T', 0x4DF2                   # $500E-$5032 tank cluster + rest
        return None, 0

    # ─── 6809 linked-list entity sourcing (MAME parity, 2026-07-03) ──────────
    # ROM-verified heads. The older _6809_LIST_HEADS had the enemy/tank heads
    # WRONG (0x9811/0x9703 walk garbage). These match MAME_ENEMY_MODEL §1.
    _LIST_HEADS_V2 = (
        0x826E7821,  # $9821: Grunt/Hulk/Brain/Prog/CruiseMissile/Tank
        0x826E7817,  # $9817: Spheroid/Enforcer/Spark/Quark/TankShell
        0x826E781F,  # $981F: family (Mikey/Mom/Dad)
        0x826E7823,  # $9823: Electrodes
    )

    def _walk_list_raw(self, head_ppc):
        """Walk one list -> {node_offset: (state_word, gx, gy)}.
        Node (24-byte object record): +0 next-ptr(BE), +4/+5 blitter position,
        +8/+9 STATE WORD (type discriminator). Reachable = alive."""
        import struct as _s
        base = self._6809_RAM_BASE
        try:
            off = _s.unpack('>H', self.mem.read_guest(head_ppc, 2))[0]
        except Exception:
            return {}
        out = {}
        visited = set()
        limit = 200
        while off and off not in visited and limit > 0:
            limit -= 1
            visited.add(off)
            try:
                rec = self.mem.read_guest(base + off, 10)
            except Exception:
                break
            nxt = (rec[0] << 8) | rec[1]
            sw = (rec[8] << 8) | rec[9]
            out[off] = (sw, rec[4], rec[5])
            off = nxt
        return out

    # A/B toggle: ROBOTRON_SINGLE_READ=1 skips the double-read cross-validation
    # (fresher, but no torn-read guard). Default 0 (double-read).
    _SINGLE_READ = os.environ.get("ROBOTRON_SINGLE_READ", "0") == "1"
    # Perception-dropout hardening (2026-07-05): 27% of real deaths had an EMPTY
    # entity read on the last-alive frame (a torn read went briefly blind → the
    # planner had nothing to dodge). If a slot present last frame vanishes this
    # frame, carry it forward ONCE at its last position (node offset = stable id).
    # One frame only: a real death ghosts for 1 frame (cheap); a torn read is
    # bridged (the entity reappears next frame). Env-toggle.
    _ENTITY_PERSIST = os.environ.get("ROBOTRON_ENTITY_PERSIST", "0") == "1"

    def _make_entity(self, off, sw, gx, gy, lbl):
        e = Entity()
        e.slot = off                 # node offset = stable per-entity id
        e.label = lbl
        e.type = _LABEL_TYPE.get(lbl, lbl)
        e.gx = gx
        e.gy = gy
        e.state_word = sw
        e.alive = True
        e.static_frames = 0
        e.w, e.h = _ENTITY_DIMS.get(lbl, (20, 20))
        return e

    def _walk_all_lists_alive(self):
        """All alive entities from the 4 linked lists, ghost-free. Double-reads
        each list and keeps only nodes present in BOTH reads (torn-read guard —
        XeniaMemory races the guest, unlike MAME's frame-synchronous lua).
        Single-read mode (env) skips the second walk for freshness."""
        ents = []
        cur = {}                     # slot -> (sw, gx, gy) real entities this frame
        for head in self._LIST_HEADS_V2:
            b = self._walk_list_raw(head)
            keys = b.keys() if self._SINGLE_READ else (self._walk_list_raw(head).keys() & b.keys())
            for off in keys:
                sw, gx, gy = b[off]
                lbl = STATE_WORD_LABELS.get(sw)
                if not lbl or lbl == '_SKIP':
                    continue
                cur[off] = (sw, gx, gy)
                ents.append(self._make_entity(off, sw, gx, gy, lbl))
        if self._ENTITY_PERSIST:
            prev = getattr(self, "_persist_prev", {})
            persisted = getattr(self, "_persisted_slots", set())
            carried = set()
            for off, (sw, gx, gy) in prev.items():
                if off in cur or off in persisted:   # reappeared, or already carried once
                    continue
                lbl = STATE_WORD_LABELS.get(sw)
                if lbl and lbl != '_SKIP':
                    ents.append(self._make_entity(off, sw, gx, gy, lbl))
                    carried.add(off)
            self._persist_prev = cur
            self._persisted_slots = carried
        return ents

    def _walk_6809_list(self, head_addr: int) -> list:
        """Walk one 6809 linked list. Returns list of (cmd, gx, gy) tuples.
        head_addr is the PPC address that holds the u16 BE offset of the first node.
        Nodes: bytes[0:2]=next_offset, bytes[2:4]=cmd, bytes[4]=gx, bytes[5]=gy.
        """
        import struct as _s
        base = self._6809_RAM_BASE
        try:
            head_raw = self.mem.read_guest(head_addr, 2)
            off = _s.unpack_from('>H', head_raw)[0]
        except Exception:
            return []
        result = []
        visited: set = set()
        limit = 200
        while off and off not in visited and limit > 0:
            limit -= 1
            visited.add(off)
            try:
                rec = self.mem.read_guest(base + off, 6)
                off      = (rec[0] << 8) | rec[1]
                cmd      = (rec[2] << 8) | rec[3]
                result.append((cmd, rec[4], rec[5]))
            except Exception:
                break
        return result

    def _read_6809_lists(self) -> dict:
        """Walk all 6809 entity linked lists. Returns dict of list_name → entries.
        Each entry: {'off': int, 'cmd': int, 'gx': int, 'gy': int}
        Returns empty dict on error.
        """
        import struct as _s
        result = {}
        base = self._6809_RAM_BASE
        try:
            for name, head_addr in self._6809_LIST_HEADS.items():
                head_raw = self.mem.read_guest(head_addr, 2)
                first_off = _s.unpack_from('>H', head_raw)[0]
                entries = []
                if first_off:
                    visited: set = set()
                    off = first_off
                    limit = 200
                    while off and off not in visited and limit > 0:
                        limit -= 1
                        visited.add(off)
                        try:
                            e = self.mem.read_guest(base + off, 6)
                            next_off = _s.unpack_from('>H', e, 0)[0]
                            cmd_word  = _s.unpack_from('>H', e, 2)[0]
                            gx = e[4]
                            gy = e[5]
                            entries.append({'off': off, 'cmd': cmd_word,
                                            'gx': gx, 'gy': gy})
                            off = next_off
                        except Exception:
                            break
                result[name] = entries
        except Exception:
            pass
        return result


if __name__ == '__main__':
    print("Connecting to Xenia...")
    gsr = GameStateReader()
    print("Connected. Reading game state (Ctrl+C to stop)...\n")

    try:
        while True:
            state = gsr.read(wait_new_frame=True)
            if state is None:
                time.sleep(0.016)
                continue

            if not state.in_game:
                print(f"  (not in game: W{state.wave} L{state.lives})")
                time.sleep(0.5)
                continue

            print(state.summary())

            # Show nearest threat
            threat, dist = state.nearest_threat()
            if threat:
                print(f"  Nearest threat: {threat.type} at dist={dist:.1f} "
                      f"({threat.gx},{threat.gy}) {threat.w}x{threat.h}px")

            # Show nearest civilian
            civ, cdist = state.nearest_civilian()
            if civ:
                print(f"  Nearest civ: {civ.type} at dist={cdist:.1f}")

            time.sleep(0.25)  # ~4 reads/sec for display

    except KeyboardInterrupt:
        print("\nDone.")
