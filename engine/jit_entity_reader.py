"""
Reads entity data from the JIT hook's frame-synchronized shared buffer.

The Xenia JIT hook (at PPC address 0x8207C928) runs every game frame (~60fps):
  1. Snapshots the slot pool from guest memory
  2. Computes per-slot static_frames (consecutive unchanged frames)

Buffer layout (little-endian, in Xenia's host process memory):
  +0x00: u32 magic = 0x454E5421 ('ENT!')
  +0x04: u32 frame_counter       (incremented per-entity by 0x8207C928)
  +0x08: u32 outer_loop_count    (incremented per TRUE 60Hz frame by 0x82060398)
  +0x0C: u32 wave (from 0x82388E20)
  +0x10: u32 score (from 0x82388E24)
  +0x14: u32 lives (from 0x82388E48)
  +0x18: u32 raw_slot_count (non-zero slots in slot pool)
  +0x1C: u32 sprite_render_count (times sub_82086CA8 fired last frame)
  +0x20: u16 static_frames[102] (101 slots + 1 padding = 204 bytes)
  +0xEC: raw slot pool (101 slots x 24 bytes = 2424 bytes)
Total: 0xEC + 2424 = 2660 bytes

Pointer file: %TEMP%/robotron_jit_entity_ptr.bin (32 bytes)
  u64 buf_addr, u64 buf_size, u32 slot_count, u32 slot_stride,
  u32 static_frames_offset, u32 slot_data_offset
"""

from __future__ import annotations

import os
import struct
import time
from pathlib import Path

MAGIC = 0x454E5421  # 'ENT!'
HEADER_SIZE = 0x20  # 32 bytes
STATIC_FRAMES_OFFSET = 0x20
STATIC_FRAMES_COUNT = 102  # 101 slots + 1 padding
STATIC_FRAMES_SIZE = STATIC_FRAMES_COUNT * 2  # 204 bytes
SLOT_DATA_OFFSET = STATIC_FRAMES_OFFSET + STATIC_FRAMES_SIZE  # 0xEC
DEFAULT_SLOT_COUNT = 101
DEFAULT_SLOT_STRIDE = 24
SLOT_POOL_SIZE = DEFAULT_SLOT_COUNT * DEFAULT_SLOT_STRIDE
BUFFER_SIZE = SLOT_DATA_OFFSET + SLOT_POOL_SIZE  # 2660 bytes = 0xA64

# Track B write mask: 4 × u32 (128 bits) appended after the slot pool.
# Bit slot_idx = 1 means slot was written during the last render frame (= alive).
WRITE_MASK_OFFSET = BUFFER_SIZE  # 0xA64
WRITE_MASK_SIZE = 16             # 4 × u32
TOTAL_BUFFER_SIZE = BUFFER_SIZE + WRITE_MASK_SIZE  # 0xA74

# Per-frame authoritative entity list (populated by the active entity hook,
# currently SpriteRenderHook at 0x82086CA8, and published by OuterLoopHook).
# Header: u16 entity_count (LE) + u16 b3c80_call_count (LE) = 4 bytes.
# b3c80_call_count is a legacy field name kept for compatibility; it now carries
# the accepted active-hook entity count for the last completed outer-loop frame.
# Followed by N × 6 bytes (sw BE u16, pos_a, pos_b, slot_idx, flags).
ENTITY_LIST_OFFSET = TOTAL_BUFFER_SIZE  # 0xA74
ENTITY_LIST_HEADER_SIZE = 4             # u16 count + u16 b3c80_call_count
ENTITY_LIST_ENTRY_SIZE = 6              # sw(u16 BE) + pos_a + pos_b + slot + flags
ENTITY_LIST_MAX = 512
ENTITY_LIST_REGION_SIZE = ENTITY_LIST_HEADER_SIZE + ENTITY_LIST_MAX * ENTITY_LIST_ENTRY_SIZE
TOTAL_BUFFER_SIZE_V2 = ENTITY_LIST_OFFSET + ENTITY_LIST_REGION_SIZE

PTR_FILE = Path(os.environ.get("TEMP", "/tmp")) / "robotron_jit_entity_ptr.bin"

# Entity state_word (bytes 4-5 big-endian in slot) -> label mapping
STATE_WORD_LABELS = {
    # ── Confirmed enemies ──────────────────────────────────────────────────────
    0x3A76: 'G',    # Grunt
    0x3AA9: 'E',    # Electrode (W1-7 state_word)
    0x3B85: 'E',    # Electrode (W8+ state variant)
    0x3B8A: 'E',    # Electrode (W8+ state variant)
    0x3B8F: 'E',    # Electrode (W8+ state variant)
    0x3B94: 'E',    # Electrode (W8+ state variant - speculative)
    0x3B99: 'E',    # Electrode (W8+ state variant - speculative)
    0x3BA4: 'E',    # Electrode (W8+ state variant - speculative)
    0x00B6: 'H',    # Hulk
    0x1DD6: 'B',    # Brain
    0x1483: 'F',    # Enforcer
    0x14DC: 'FB',   # Enforcer Bullet (unconfirmed — never seen in crops; kept speculatively)
    0x12C8: 'S',    # Sphereoid (spawner)
    # ── CORRECTED 2026-07-02 from the MAME-side annotated-ASM ground truth ────
    # (robotron-rl/mame_gym/ENEMY_MODEL.md §2 — ROM is byte-identical to XBLA, so
    #  the 6809 state words are identical. Validated on MAME via the independent
    #  anim-frame-pointer oracle; the old table here had the SAME mislabels that
    #  poisoned the MAME side for weeks.)
    #   0x4800 was a PHANTOM (nothing in the ROM loads #$4800) — removed.
    #   0x4DF2 is the TANK collision handler (asm:7388,7427), not a shell.
    #   0x4FD5 is the TANK SHELL handler (asm:7863) — fast, aimed, wall-bouncing;
    #          this is the entity previously misread as "teleporting quarks".
    #   0x1F1F is the PROG (brain-mutated civilian, human-range sprites).
    #   0x2119 is the CRUISE MISSILE handler (asm:3175, anim $206B).
    0x4DF2: 'T',    # Tank (spawned when a Quark converts)
    0x4FD5: 'TS',   # Tank Shell (projectile; caps at 20/wave — see ENEMY_MODEL §9 $F1 bug)
    0x1F1F: 'P',    # Prog (brain-mutated civilian — shootable hunter)
    0x2119: 'MS',   # Cruise Missile (Brain-fired homing projectile; re-aims <=8 ticks)
    0x4BC9: 'Q',    # Quark (pre-Tank blob; the ONLY quark state word; slow wanderer,
                    #   no homing, <=~2px/frame — it cannot teleport. Kill early!)
    # ── Civilians (CC=Child/Mikey, CW=Woman/Mom, CM=Man/Dad) ──────────────────
    # NOTE: Prog detection: civilian state_word stays CC/CW/CM after Brain mutates it,
    #   but the sprite_id (slot bytes 16-17) changes to non-civilian frames.
    #   game_state.py reclassifies as 'P' when sprite_id is out of civilian range.
    #   IMPORTANT: After mutation the slot gx/gy FREEZE (static). As the Prog walks,
    #   its Pool1 position diverges from the frozen slot position, so distance-based
    #   matching is widened for the non-civilian-sprite fallback path.
    0x0330: 'CC',   # Civilian Child (Mikey)
    0x0335: 'CW',   # Civilian Woman (Mom)
    0x033A: 'CM',   # Civilian Man (Dad)
    # ── Non-entity state words — suppressed in game_state.py ──────────────────
    0x0437: '_SKIP',  # Civilian death skull animation
    0x0485: '_SKIP',  # Player entity (slot=255, 6809 list)
    0x0489: '_SKIP',  # Score bonus popup / player anim state
    0x0491: '_SKIP',  # 4000 score sprite
    0x0495: '_SKIP',  # 5000 score sprite
    0x048D: '_SKIP',  # Score popup (200/300 etc.) — previously mislabeled as FB
    0x2171: '_SKIP',  # UI border line
    0x2481: '_SKIP',  # UI/wave-transition animation
    0x2561: '_SKIP',  # UI/wave-transition animation
    0xB3EF: '_SKIP',  # Explosion animation frame
    0xB4F1: '_SKIP',  # Explosion animation frame
    0xB470: '_SKIP',  # Explosion animation frame
    0x40F5: '_SKIP',  # UI/border artifact — thin blue line
    0x55FE: '_SKIP',  # UI/border artifact — thin orange line
    0x551E: '_SKIP',  # UI/border artifact — thin orange line (W7, confirmed by crop)
    0x566E: '_SKIP',  # UI/border artifact — thin orange line (W7, confirmed by crop; 10+ appearances)
    0x558E: '_SKIP',  # Score display UI (shows score digits + player icon, W7)
    0x0067: '_SKIP',  # Transient animation — pink/white bars at W7 (once; likely score popup or explosion frame)
    0x21E1: '_SKIP',  # UI/border artifact — thin blue line
    0x2411: '_SKIP',  # UI/border artifact — thin blue line
    0x2251: '_SKIP',  # UI/border artifact — thin blue line
    0x22C1: '_SKIP',  # UI/border artifact — thin blue line
    0x2331: '_SKIP',  # UI/border artifact — thin blue line
    0x23A1: '_SKIP',  # UI/border artifact — thin blue line
    # ── Resolved 2026-07-02 (was "still unidentified") ────────────────────────
    # Tank shells = 0x4FD5 (above). Enforcer spark = 0x14DC ('FB' above — CONFIRMED
    # on MAME, +25 pts, laser-killable, ballistic-at-launch + fixed curvature).
    # Full per-type movement/AI ground truth: robotron-rl/mame_gym/ENEMY_MODEL.md.
}

# Counter block addresses (three 9-byte tuples, one is "live")
COUNTER_BLOCK_ADDRS = [0x826E9DFA, 0x826E9E36, 0x826E9E68]
# Order of types in each 9-byte counter block.
# The game tracks all three civilian sub-types (CC/CW/CM) as a single 'C' count.
# game_state.py maps the 'C' counter slot to all three labels.
COUNTER_TYPE_ORDER = ['G', 'E', 'H', 'B', 'F', 'C', 'S', 'Q', 'P']
CIVILIAN_LABELS = frozenset({'CC', 'CW', 'CM'})  # All three map to 'C' counter slot

# Keep old name for backwards compat
ENTITY_TYPE_LABELS = STATE_WORD_LABELS


class JitEntityReader:
    """Reads entity data from the JIT hook's shared buffer."""

    def __init__(self, mem):
        self.mem = mem
        self._host_ptr: int | None = None
        self._buf_size: int = TOTAL_BUFFER_SIZE_V2
        self._slot_count: int = DEFAULT_SLOT_COUNT
        self._slot_stride: int = DEFAULT_SLOT_STRIDE
        self._slot_data_offset: int = SLOT_DATA_OFFSET
        self._last_frame: int = 0
        self._discover_time: float = 0.0

    def _discover_pointer(self) -> int | None:
        """Read the host pointer from the temp file written by the JIT hook."""
        try:
            data = PTR_FILE.read_bytes()
            if len(data) < 16:
                return None
            buf_addr = struct.unpack_from("<Q", data, 0)[0]
            buf_size = struct.unpack_from("<Q", data, 8)[0]
            if buf_addr == 0:
                return None
            if len(data) >= 24:
                self._slot_count = struct.unpack_from("<I", data, 16)[0]
                self._slot_stride = struct.unpack_from("<I", data, 20)[0]
            if len(data) >= 32:
                # +24 is static_frames_offset (fixed at 0x20)
                self._slot_data_offset = struct.unpack_from("<I", data, 28)[0]
            if buf_size > 0:
                self._buf_size = max(buf_size, TOTAL_BUFFER_SIZE_V2)

            # Validate by reading the magic word
            header = self.mem.read(buf_addr, 4)
            magic = struct.unpack_from("<I", header, 0)[0]
            if magic == MAGIC:
                return buf_addr
        except (OSError, struct.error):
            pass
        return None

    @property
    def available(self) -> bool:
        """True if the JIT buffer has been discovered and is readable."""
        if self._host_ptr is not None:
            return True
        now = time.time()
        if now - self._discover_time < 1.0:
            return False
        self._discover_time = now
        self._host_ptr = self._discover_pointer()
        return self._host_ptr is not None

    def read_buffer(self):
        """Read the entire JIT buffer.

        Returns:
            (header_dict, static_frames, raw_slot_data)
            header_dict: frame, raw_slot_count, wave, score, lives
            static_frames: tuple of 101 u16 values (consecutive unchanged frames per slot)
            raw_slot_data: raw slot pool bytes (101 x 24 bytes)
            Returns ({}, (), None) if buffer not available.
        """
        if not self.available:
            return {}, (), None

        try:
            data = self.mem.read(self._host_ptr, self._buf_size)
        except OSError:
            self._host_ptr = None
            return {}, (), None

        if len(data) < self._slot_data_offset:
            return {}, (), None

        magic = struct.unpack_from("<I", data, 0)[0]
        if magic != MAGIC:
            self._host_ptr = None
            return {}, (), None

        frame, outer_loop_count, wave, score, lives, raw_slot_count, sprite_render_count = \
            struct.unpack_from("<IIIIIII", data, 4)

        # Parse static_frames (101 u16 values)
        sf_end = STATIC_FRAMES_OFFSET + DEFAULT_SLOT_COUNT * 2
        static_frames = struct.unpack_from(f"<{DEFAULT_SLOT_COUNT}H", data, STATIC_FRAMES_OFFSET)

        # Track B write mask: 4 × u32 at WRITE_MASK_OFFSET.
        # Each bit = one slot; bit i set → slot i was written last frame (alive).
        write_mask = 0
        if len(data) >= WRITE_MASK_OFFSET + WRITE_MASK_SIZE:
            w0, w1, w2, w3 = struct.unpack_from("<IIII", data, WRITE_MASK_OFFSET)
            write_mask = w0 | (w1 << 32) | (w2 << 64) | (w3 << 96)

        # Parse per-frame authoritative entity list from B3C80 hook.
        # Published by OuterLoopHook at kRobotronEntityListOffset (0xA74).
        # Header: u16 entity_count + u16 b3c80_call_count (total fires incl. rejected).
        entity_list = []
        b3c80_call_count = 0
        if len(data) >= ENTITY_LIST_OFFSET + ENTITY_LIST_HEADER_SIZE:
            count, b3c80_call_count = struct.unpack_from('<HH', data, ENTITY_LIST_OFFSET)
            count = min(count, ENTITY_LIST_MAX)
            base = ENTITY_LIST_OFFSET + ENTITY_LIST_HEADER_SIZE
            for i in range(count):
                off = base + i * ENTITY_LIST_ENTRY_SIZE
                if off + ENTITY_LIST_ENTRY_SIZE > len(data):
                    break
                # state_word is stored big-endian by xe::store_and_swap<uint16_t>
                sw = (data[off] << 8) | data[off + 1]
                pos_a = data[off + 2]   # r3 bits [15:8] from sub_82066DE0 return
                pos_b = data[off + 3]   # r3 bits [7:0]
                slot = data[off + 4]    # 0xFF if no slot pool entry
                flags = data[off + 5]   # bit0=1: has slot pool entry
                # Python table takes precedence over C++ unknown flag.
                # If the state_word is in our table, use that label.
                # Only fall back to ?XXXX for state_words unknown to both.
                label = STATE_WORD_LABELS.get(sw)
                if label is None:
                    label = f'?{sw:04X}' if (flags & 0x02) else None
                if label:
                    entity_list.append({
                        'state_word': sw,
                        'label': label,
                        'pos_a': pos_a,
                        'pos_b': pos_b,
                        'slot_idx': slot,
                        'has_slot': bool(flags & 1),
                    })

        header = {
            'frame': frame,
            # outer_loop_count: incremented once per TRUE 60 Hz video frame by
            # RobotronOuterLoopHook (PPC 0x82060398).  When this value advances,
            # write_mask holds the COMPLETE entity set for that frame — no
            # accumulation needed.  If still 0, the new hook has not fired yet
            # (game not running / Xenia not rebuilt with new hook).
            'outer_loop_count': outer_loop_count,
            'raw_slot_count': raw_slot_count,
            'wave': wave,
            'score': score,
            'lives': lives,
            # Number of times sub_82086CA8 (sprite render setup) fired last frame.
            'sprite_render_count': sprite_render_count,
            # Track B: 101-bit mask of slots written during the last COMPLETE frame.
            # Published atomically by RobotronOuterLoopHook at the start of each
            # new frame (= all entities rendered in the previous frame).
            # Bit i = 1 → slot i was written by the renderer → entity is alive.
            'write_mask': write_mask,
            # Per-frame authoritative entity list from the active entity hook.
            # Each entry: {state_word, label, pos_a, pos_b, slot_idx, has_slot}.
            # In the current SpriteRenderHook path, pos_a = gx and pos_b = gy
            # from the command table bytes [1:2].
            'entity_list': entity_list,
            # Diagnostic: accepted active-hook entity count for the last completed
            # outer-loop frame. The key name is legacy.
            'b3c80_call_count': b3c80_call_count,
        }

        slot_start = self._slot_data_offset
        raw_slots = data[slot_start:] if slot_start < len(data) else None

        self._last_frame = frame
        return header, static_frames, raw_slots

    def get_alive_slots_from_mask(self, write_mask: int, raw_slots) -> list:
        """Return parsed slots whose index has a set bit in write_mask.

        This is the Track B authoritative alive list: if the renderer wrote
        to a slot during the last complete frame, the entity is alive.

        The write mask is published by RobotronOuterLoopHook (PPC 0x82060398)
        at the START of each true 60 Hz video frame — meaning it contains the
        complete entity set from the PREVIOUS frame in one atomic snapshot.
        No accumulation is needed: read header['write_mask'] and pass it here.

        Poll for header['outer_loop_count'] advancing to detect new frames::

            last_olc = 0
            while True:
                header, sf, raw = reader.read_buffer()
                olc = header.get('outer_loop_count', 0)
                if olc != last_olc:
                    last_olc = olc
                    alive = reader.get_alive_slots_from_mask(header['write_mask'], raw)
                    # alive is now a clean single-frame entity list

        Args:
            write_mask: 128-bit integer — bit i = slot i written last frame
            raw_slots:  raw slot pool bytes from read_buffer()

        Returns:
            List of slot dicts (same format as parse_slots) for alive slots only.
        """
        if not write_mask or raw_slots is None:
            return []
        all_slots = self.parse_slots(raw_slots)
        return [s for s in all_slots if (write_mask >> s['index']) & 1]

    def parse_slots(self, raw_slots):
        """Parse raw slot data into list of slot dicts.

        Returns list of dicts with: index, gx, gy, state_word, label, raw (24 bytes)
        Only returns non-zero slots with recognized state_words.
        """
        if raw_slots is None:
            return []
        slots = []
        for i in range(self._slot_count):
            off = i * self._slot_stride
            if off + self._slot_stride > len(raw_slots):
                break
            chunk = raw_slots[off:off + self._slot_stride]
            # Slot layout: gx(u8), gy(u8), ?, ?, state_word(u16 BE at +4), ...
            gx = chunk[0]
            gy = chunk[1]
            state_word = (chunk[4] << 8) | chunk[5]
            if state_word == 0:
                continue
            label = STATE_WORD_LABELS.get(state_word)
            if label is None:
                continue  # Unknown entity type, skip
            # Electrodes (0x3AA9) and Sphereoids (0x12C8): slot byte[1] is always 0
            # (the game stores their gy in the command table, not the slot pool).
            # Leave gy=0 here; game_state.py overrides it from the static_pos_cache.
            # Bytes 16-17: sprite_id (big-endian offset into sprite ROM at 0x826EE000)
            sprite_id = (chunk[16] << 8) | chunk[17]
            slots.append({
                'index': i,
                'gx': gx,
                'gy': gy,
                'state_word': state_word,
                'label': label,
                'sprite_id': sprite_id,
                'raw': chunk,
            })
        return slots

    def get_alive_entities(self, static_frames, raw_slots, counter_caps=None):
        """Determine alive entities using freshness ranking + counter caps.

        For each entity type, sorts slots by static_frames (ascending = freshest
        first) and keeps the top N where N = counter block count for that type.
        No hard threshold — ranking alone separates alive (sf=0-5) from ghosts
        (sf=200+) during active gameplay.

        Args:
            static_frames: tuple of u16 static_frames per slot
            raw_slots: raw slot pool bytes
            counter_caps: dict of label -> max alive count (from counter blocks)

        Returns:
            List of slot dicts for slots deemed alive.
        """
        all_slots = self.parse_slots(raw_slots)
        if not all_slots:
            return all_slots

        # Attach static_frames to each slot
        for s in all_slots:
            sf = static_frames[s['index']] if s['index'] < len(static_frames) else 0xFFFF
            s['static_frames'] = sf

        if counter_caps is None:
            return all_slots

        from collections import defaultdict
        by_label = defaultdict(list)
        for s in all_slots:
            by_label[s['label']].append(s)

        alive = []
        for label, group in by_label.items():
            cap = counter_caps.get(label, len(group))
            group.sort(key=lambda s: s['static_frames'])
            alive.extend(group[:cap])

        return alive

    def read_counter_blocks(self):
        """Read the three counter blocks from guest memory.

        Returns the block with the lowest total as a dict of label -> count.
        Returns None if reading fails.
        """
        best_total = 999
        best_caps = None
        for addr in COUNTER_BLOCK_ADDRS:
            try:
                # Read 9 bytes: each byte is remaining count for one entity type
                guest_data = self.mem.read_guest(addr, 9)
                caps = {}
                total = 0
                for j, label in enumerate(COUNTER_TYPE_ORDER):
                    c = guest_data[j]
                    caps[label] = c
                    total += c
                if total < best_total:
                    best_total = total
                    best_caps = caps
            except (OSError, Exception):
                continue
        return best_caps

    # Class-level cache: 'ab' means pos_a=gx / pos_b=gy;
    #                    'ba' means pos_a=gy / pos_b=gx.
    _pos_byte_order: str | None = None

    def resolve_entity_positions(self, entity_list: list, raw_slots) -> list:
        """Resolve gx/gy for each entity in entity_list.

        For entities with has_slot=True and slot_idx < 101, reads gx/gy
        directly from the slot pool (bytes 0 and 1 of the 24-byte slot,
        which are known authoritative positions).

        For entities without a slot pool entry (has_slot=False or slot_idx
        >= 101), uses pos_a/pos_b from sub_82066DE0's return value in r3.
        The byte order (which byte is gx vs gy) is unknown until calibrated.

        Calibration: on the first frame where at least one entity has both
        a valid slot pool position AND pos_a/pos_b, compare them.  If pos_a
        matches slot byte 0, then pos_a=gx.  Cache the result in
        JitEntityReader._pos_byte_order so all subsequent frames use it.

        Returns a new list of dicts with 'gx' and 'gy' added.  Entries
        whose position cannot be resolved have gx=0, gy=0 and
        'pos_calibrated'=False.
        """
        cls = type(self)
        resolved = []

        for ent in entity_list:
            out = dict(ent)
            out['pos_calibrated'] = False

            slot_idx = ent['slot_idx']
            has_slot = ent['has_slot']

            if has_slot and slot_idx < 101 and raw_slots is not None:
                slot_off = slot_idx * DEFAULT_SLOT_STRIDE
                if slot_off + DEFAULT_SLOT_STRIDE <= len(raw_slots):
                    slot_gx = raw_slots[slot_off]
                    slot_gy = raw_slots[slot_off + 1]

                    label_check = ent.get('label', '')

                    out['gx'] = slot_gx
                    out['gy'] = slot_gy
                    out['pos_calibrated'] = True

                    # Attempt calibration if not yet done
                    if cls._pos_byte_order is None:
                        pos_a = ent['pos_a']
                        pos_b = ent['pos_b']
                        if pos_a == slot_gx and pos_b == slot_gy:
                            cls._pos_byte_order = 'ab'
                        elif pos_a == slot_gy and pos_b == slot_gx:
                            cls._pos_byte_order = 'ba'
                        if cls._pos_byte_order is not None:
                            import sys
                            print(
                                f"[jit_entity_reader] pos byte order calibrated: "
                                f"pos_a={'gx' if cls._pos_byte_order == 'ab' else 'gy'}, "
                                f"pos_b={'gy' if cls._pos_byte_order == 'ab' else 'gx'} "
                                f"(slot={slot_idx} slot_gx={slot_gx} slot_gy={slot_gy} "
                                f"pos_a={pos_a} pos_b={pos_b})",
                                file=sys.stderr,
                            )
                else:
                    out['gx'] = 0
                    out['gy'] = 0
            else:
                # No slot pool entry — use r3 byte order
                pos_a = ent['pos_a']
                pos_b = ent['pos_b']
                if cls._pos_byte_order == 'ab':
                    out['gx'] = pos_a
                    out['gy'] = pos_b
                    out['pos_calibrated'] = True
                elif cls._pos_byte_order == 'ba':
                    out['gx'] = pos_b
                    out['gy'] = pos_a
                    out['pos_calibrated'] = True
                else:
                    # Order unknown yet — store tentatively as-is
                    out['gx'] = pos_a
                    out['gy'] = pos_b

            resolved.append(out)

        return resolved


class WriteMaskAccumulator:
    """Rolling OR accumulator for the Track B write mask.

    The write mask is published once per entity render (not once per true
    60 Hz video frame), so each publication carries only 1-5 bits.  This
    class accumulates all publications within a sliding time window and
    returns their bitwise OR — which represents all slots written in the
    window = all alive entities.

    Typical window: 200 ms covers ~12 true frames × ~22 entities/frame,
    so every alive entity gets at least one mask bit published.  Dead
    entities stop being rendered and their bits fade out after one window.

    Usage::

        accum = WriteMaskAccumulator(window_s=0.200)
        while True:
            header, sf, raw = reader.read_buffer()
            cumul_mask = accum.update(header.get('write_mask', 0))
            alive = reader.get_alive_slots_from_mask(cumul_mask, raw)
    """

    def __init__(self, window_s: float = 0.200):
        import time as _time
        self._time = _time
        self._window_s = window_s
        self._entries: list[tuple[float, int]] = []  # (timestamp, mask)

    def update(self, write_mask: int) -> int:
        """Add a new mask snapshot and return the accumulated OR over the window."""
        now = self._time.time()
        self._entries.append((now, write_mask))
        cutoff = now - self._window_s
        # Drop expired entries
        self._entries = [(t, m) for t, m in self._entries if t >= cutoff]
        # OR everything remaining
        result = 0
        for _, m in self._entries:
            result |= m
        return result

    def reset(self):
        """Clear all accumulated state (call on wave change / game restart)."""
        self._entries.clear()
