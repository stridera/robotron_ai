"""
Sprite lookup table: maps sprite_id → entity type, frame index, pixel dimensions.

Built from the sprite data at 0x826EE000. Each sprite_id (slot bytes 16-17)
is a byte offset into the sprite ROM where a 4-byte animation table entry lives:
  [width_bytes, height, bmp_offset_hi, bmp_offset_lo]

This module reads the sprite ROM once and builds a fast lookup dict so that
any sprite_id can be resolved to its entity type, animation frame, and exact
pixel dimensions — no guesswork, no approximate bounding boxes.

Usage:
    from sprite_lookup import SpriteLookup
    lut = SpriteLookup(mem)       # mem = XeniaMemory instance
    info = lut.lookup(0x4063)     # -> {'type': 'Grunt', 'frame': 0, ...}
"""

import struct
from collections import OrderedDict

SPRITE_DATA_BASE = 0x826EE000
SPRITE_DATA_SIZE = 0x6000

# All known entity sprite IDs — one entry per animation frame
# Ordered by sprite_id offset in ROM
ENTITY_SPRITE_IDS = OrderedDict([
    ('Civ_Mom',    [0x052F, 0x0533, 0x0537, 0x053B, 0x053F, 0x0543,
                    0x0547, 0x054B, 0x054F, 0x0553, 0x0557, 0x055B]),
    ('Civ_Dad',    [0x07FF, 0x0803, 0x0807, 0x080B, 0x080F, 0x0813,
                    0x0817, 0x081B, 0x081F, 0x0823, 0x0827, 0x082B]),
    ('Civ_Child',  [0x0B3B, 0x0B3F, 0x0B43, 0x0B47, 0x0B4B, 0x0B4F,
                    0x0B53, 0x0B57, 0x0B5B, 0x0B5F, 0x0B63, 0x0B67]),
    ('Hulk',       [0x0CF9, 0x0CFD, 0x0D01, 0x0D05, 0x0D09, 0x0D0D,
                    0x0D11, 0x0D15, 0x0D19]),
    ('Sphereoid',  [0x14F2, 0x14F6, 0x14FA, 0x14FE, 0x1502, 0x1506,
                    0x150A, 0x150E]),
    ('Enforcer',   [0x18D2, 0x18D6, 0x18DA, 0x18DE, 0x18E2, 0x18E6]),
    ('EnfBullet',  [0x1A34, 0x1A38, 0x1A3C, 0x1A40]),
    ('Brain2',     [0x206B]),
    ('Brain',      [0x2141, 0x2145, 0x2149, 0x214D, 0x2151, 0x2155,
                    0x2159, 0x215D, 0x2161, 0x2165, 0x2169, 0x216D]),
    ('Electrode',  [0x3B15, 0x3B25, 0x3B2A, 0x3B2F, 0x3B35, 0x3B3A,
                    0x3B3F, 0x3B45, 0x3B4A, 0x3B4F, 0x3B55, 0x3B5A, 0x3B5F]),
    ('Grunt',      [0x4063, 0x4067, 0x406B, 0x406F]),
    ('Quark3',     [0x4FEE]),
    ('Quark2',     [0x500E, 0x5014, 0x501A, 0x5020, 0x5026, 0x502A,
                    0x502E, 0x5032]),
    ('Quark1',     [0x50C2, 0x50C6, 0x50CA, 0x50CE, 0x50D2, 0x50D6,
                    0x50DA, 0x50DE, 0x50E2]),
])

# Map entity names to single-letter labels used by jit_entity_reader
ENTITY_LABEL = {
    'Civ_Mom': 'C', 'Civ_Dad': 'C', 'Civ_Child': 'C',
    'Grunt': 'G', 'Electrode': 'E', 'Hulk': 'H',
    'Brain': 'B', 'Brain2': 'B',
    'Enforcer': 'F', 'EnfBullet': 'FB',
    'Sphereoid': 'S',
    'Quark1': 'Q', 'Quark2': 'Q', 'Quark3': 'Q',
}


class SpriteInfo:
    """Info about a single sprite frame."""
    __slots__ = ('entity_type', 'label', 'frame_index', 'sprite_id',
                 'width_px', 'height_px', 'width_bytes',
                 'bitmap_offset', 'bitmap_size')

    def __init__(self, entity_type, label, frame_index, sprite_id,
                 width_bytes, height_px, bitmap_offset):
        self.entity_type = entity_type
        self.label = label
        self.frame_index = frame_index
        self.sprite_id = sprite_id
        self.width_bytes = width_bytes
        self.width_px = width_bytes * 2
        self.height_px = height_px
        self.bitmap_offset = bitmap_offset
        self.bitmap_size = width_bytes * height_px

    def __repr__(self):
        return (f"SpriteInfo({self.entity_type} f{self.frame_index} "
                f"{self.width_px}x{self.height_px} @0x{self.sprite_id:04X})")


class SpriteLookup:
    """Fast sprite_id → SpriteInfo lookup table.

    Reads the sprite ROM from Xenia memory once, parses all known animation
    table entries, and builds a dict for O(1) lookups.
    """

    def __init__(self, mem=None, sprite_data=None):
        """Initialize from either a memory reader or raw sprite data bytes.

        Args:
            mem: XeniaMemory instance (reads sprite ROM from guest memory)
            sprite_data: raw bytes of sprite ROM (if already read)
        """
        if sprite_data is None:
            if mem is None:
                raise ValueError("Need either mem or sprite_data")
            sprite_data = mem.read_guest(SPRITE_DATA_BASE, SPRITE_DATA_SIZE)

        self._data = sprite_data
        self._lut = {}  # sprite_id -> SpriteInfo
        self._build_lut()

    def _build_lut(self):
        data = self._data
        for entity_type, ids in ENTITY_SPRITE_IDS.items():
            label = ENTITY_LABEL[entity_type]
            for frame_idx, sid in enumerate(ids):
                if sid + 4 > len(data):
                    continue
                w_bytes = data[sid]
                h_rows = data[sid + 1]
                bmp_off = (data[sid + 2] << 8) | data[sid + 3]
                if w_bytes == 0 or h_rows == 0:
                    continue
                self._lut[sid] = SpriteInfo(
                    entity_type, label, frame_idx, sid,
                    w_bytes, h_rows, bmp_off
                )

    def lookup(self, sprite_id):
        """Look up a sprite_id. Returns SpriteInfo or None."""
        return self._lut.get(sprite_id)

    def get_bbox_pixels(self, sprite_id):
        """Get (width_px, height_px) for a sprite_id, or None."""
        info = self._lut.get(sprite_id)
        if info:
            return (info.width_px, info.height_px)
        return None

    @property
    def known_ids(self):
        return set(self._lut.keys())

    def decode_bitmap(self, sprite_id):
        """Decode the nibble-packed bitmap for a sprite_id.

        Returns numpy array of palette indices (uint8), shape (h, w), or None.
        """
        import numpy as np
        info = self._lut.get(sprite_id)
        if info is None:
            return None

        w_bytes = info.width_bytes
        h = info.height_px
        bmp_off = info.bitmap_offset
        w_px = info.width_px

        if bmp_off + w_bytes * h > len(self._data):
            return None

        pixels = np.zeros((h, w_px), dtype=np.uint8)
        for y in range(h):
            row_off = bmp_off + y * w_bytes
            for xb in range(w_bytes):
                byte_val = self._data[row_off + xb]
                pixels[y, xb * 2] = (byte_val >> 4) & 0xF
                pixels[y, xb * 2 + 1] = byte_val & 0xF
        return pixels

    def stats(self):
        """Return summary stats."""
        from collections import Counter
        types = Counter(info.entity_type for info in self._lut.values())
        return {
            'total_sprites': len(self._lut),
            'entity_types': dict(types),
        }


if __name__ == '__main__':
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from xenia_memory import XeniaMemory

    mem = XeniaMemory('xenia_canary.exe')
    lut = SpriteLookup(mem)

    stats = lut.stats()
    print(f"Loaded {stats['total_sprites']} sprite frames:")
    for t, count in sorted(stats['entity_types'].items()):
        print(f"  {t}: {count} frames")

    # Test a few lookups
    test_ids = [0x4063, 0x052F, 0x3B15, 0x2141, 0x0CF9]
    print("\nTest lookups:")
    for sid in test_ids:
        info = lut.lookup(sid)
        print(f"  0x{sid:04X} -> {info}")
