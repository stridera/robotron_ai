# Robotron 2084 — Sprite Data Format

> [!NOTE]
> Copied on 2026-09-10 from the development tree (`robotron/SPRITE_DATA.md`,
> March 2026). The format description is still accurate, but **three of the
> names below are wrong**. They were corrected in July 2026 against the game's
> disassembly (see [ENEMY_MODEL.md](ENEMY_MODEL.md) §2):
>
> | Name below | Sprite IDs | Actually |
> |---|---|---|
> | Brain2 | `0x206B` | **Cruise missile** |
> | Quark3 | `0x4FEE` | **Tank shell** |
> | Quark2 | `0x500E`–`0x5032` | **Tank** |
> | Quark1 | `0x50C2`–`0x50E2` | Quark (correct) |
>
> The memory reader doesn't use these names: it classifies entities by state word
> and by the corrected animation-pointer ranges in
> `GameStateReader._cmd_to_label`. `engine/sprite_lookup.py` still carries the old
> names. The scripts under "Tools" live in the development tree, not in this repo.

## Sprite Data Base Address

All entity sprite data lives at **guest address `0x826EE000`**.

This was discovered by following the game's renderer globals:
- `0x823C5BE0` (draw_fn_table) contains a pointer to `0x826EE000`
- The PPC renderer (`sub_82086D10`) uses this as the base for all sprite lookups

The sprite data region is ~24KB (0x6000 bytes), covering all known sprite IDs up to ~0x5500.

## How sprite_id Works

Entity slot bytes 16-17 contain the **sprite_id**, which is a **direct byte offset** from `0x826EE000` to that sprite's animation table.

```
sprite_data_address = 0x826EE000 + sprite_id
```

For example, Grunt's first sprite_id is `0x4063`, so its animation table is at `0x826EE000 + 0x4063 = 0x82732063`.

## Animation Table Format

At each sprite_id offset, there's an animation table with **4 bytes per frame**:

```
Byte 0:    width_bytes   (pixel width = width_bytes × 2, since nibble-packed)
Byte 1:    height_rows   (pixel height)
Bytes 2-3: u16 big-endian offset from 0x826EE000 to bitmap data
```

Consecutive animation frames for the same entity are at sprite_id offsets spaced 4 apart (e.g., Grunt frames: 0x4063, 0x4067, 0x406B, 0x406F).

**Example** — Grunt frame 0 at offset 0x4063:
```
05 0D 41 CB
 │  │  └──┘── bitmap offset 0x41CB (from 0x826EE000)
 │  └──────── 13 rows tall
 └─────────── 5 bytes wide = 10 pixels wide
```

## Bitmap Format

Bitmaps are **4-bit nibble-packed palette indices**:
- Each byte encodes 2 pixels
- High nibble (bits 7-4) = left pixel
- Low nibble (bits 3-0) = right pixel
- Palette index `0` = transparent/background
- Rows are stored sequentially, `width_bytes` per row

```
Total bitmap size = width_bytes × height_rows
```

### Palette

The game uses a programmable palette. These are the approximate default colors:

| Index | Color         | RGB           |
|-------|---------------|---------------|
| 0x0   | Transparent   | (0, 0, 0)    |
| 0x1   | Red           | (255, 0, 0)  |
| 0x2   | Green         | (0, 200, 0)  |
| 0x3   | Yellow        | (255, 255, 0)|
| 0x4   | Blue          | (0, 0, 255)  |
| 0x5   | Magenta       | (255, 0, 255)|
| 0x6   | Cyan          | (0, 255, 255)|
| 0x7   | White         | (255, 255, 255)|
| 0x8   | Gray          | (128, 128, 128)|
| 0x9   | Orange        | (255, 128, 0)|
| 0xA   | Light Green   | (0, 255, 128)|
| 0xB   | Light Blue    | (128, 128, 255)|
| 0xC   | Pink          | (255, 128, 128)|
| 0xD   | Light Cyan    | (128, 255, 255)|
| 0xE   | Light Yellow  | (255, 255, 128)|
| 0xF   | Light Magenta | (255, 128, 255)|

The live palette may be readable from memory near `0x823D5D90` (render counter area).

## Entity Sprite Dimensions

| Entity      | Pixels (W×H) | Bytes/Row | Bytes/Frame | Frames | First sprite_id |
|-------------|---------------|-----------|-------------|--------|-----------------|
| Civ_Mom     | 8 × 14        | 4         | 56          | 12     | 0x052F          |
| Civ_Dad     | 10 × 13       | 5         | 65          | 12     | 0x07FF          |
| Civ_Child   | 6 × 11        | 3         | 33          | 12     | 0x0B3B          |
| Hulk        | 14 × 16       | 7         | 112         | 9      | 0x0CF9          |
| Sphereoid   | 16 × 15       | 8         | 120         | 8      | 0x14F2          |
| Enforcer    | 10 × 11       | 5         | 55          | 6      | 0x18D2          |
| EnfBullet   | 8 × 7         | 4         | 28          | 4      | 0x1A34          |
| Brain2      | 6 × 4         | 3         | 12          | 1      | 0x206B          |
| Brain       | 14 × 16       | 7         | 112         | 12     | 0x2141          |
| Electrode   | 6–10 × 9*     | 3–5       | varies      | 13     | 0x3B15          |
| Grunt       | 10 × 13       | 5         | 65          | 4      | 0x4063          |
| Quark3      | 8 × 7         | 4         | 28          | 1      | 0x4FEE          |
| Quark2      | varies        | varies    | varies      | 8      | 0x500E          |
| Quark1      | 16 × 15       | 8         | 120         | 9      | 0x50C2          |

*Electrode frames all have height 9 but width varies (6 or 10 pixels) across animation stages.

## All Known Sprite IDs

### Grunt (4 frames)
`0x4063, 0x4067, 0x406B, 0x406F`

### Electrode (13 frames)
`0x3B15, 0x3B25, 0x3B2A, 0x3B2F, 0x3B35, 0x3B3A, 0x3B3F, 0x3B45, 0x3B4A, 0x3B4F, 0x3B55, 0x3B5A, 0x3B5F`

Note: Electrode IDs have irregular spacing (not all +4), suggesting some frames have different sizes in the animation table.

### Hulk (9 frames)
`0x0CF9, 0x0CFD, 0x0D01, 0x0D05, 0x0D09, 0x0D0D, 0x0D11, 0x0D15, 0x0D19`

### Brain (12 frames + 1 alt)
`0x2141, 0x2145, 0x2149, 0x214D, 0x2151, 0x2155, 0x2159, 0x215D, 0x2161, 0x2165, 0x2169, 0x216D`
Alt (Brain2): `0x206B`

### Enforcer (6 frames)
`0x18D2, 0x18D6, 0x18DA, 0x18DE, 0x18E2, 0x18E6`

### Enforcer Bullet (4 frames)
`0x1A34, 0x1A38, 0x1A3C, 0x1A40`

### Civilian Mom (12 frames)
`0x052F, 0x0533, 0x0537, 0x053B, 0x053F, 0x0543, 0x0547, 0x054B, 0x054F, 0x0553, 0x0557, 0x055B`

### Civilian Dad (12 frames)
`0x07FF, 0x0803, 0x0807, 0x080B, 0x080F, 0x0813, 0x0817, 0x081B, 0x081F, 0x0823, 0x0827, 0x082B`

### Civilian Child (12 frames)
`0x0B3B, 0x0B3F, 0x0B43, 0x0B47, 0x0B4B, 0x0B4F, 0x0B53, 0x0B57, 0x0B5B, 0x0B5F, 0x0B63, 0x0B67`

### Sphereoid (8 frames)
`0x14F2, 0x14F6, 0x14FA, 0x14FE, 0x1502, 0x1506, 0x150A, 0x150E`

### Quark1 (9 frames)
`0x50C2, 0x50C6, 0x50CA, 0x50CE, 0x50D2, 0x50D6, 0x50DA, 0x50DE, 0x50E2`

### Quark2 (8 frames)
`0x500E, 0x5014, 0x501A, 0x5020, 0x5026, 0x502A, 0x502E, 0x5032`

### Quark3 (1 frame)
`0x4FEE`

## Game Renderer Globals (Corrected)

These addresses were derived from the PPC code in `sub_82086D10`. The `lis rX, imm` instruction computes `(imm & 0xFFFF) << 16`:

| Address      | Contents                         | Typical Value  |
|--------------|----------------------------------|----------------|
| 0x823C5BE0   | draw_fn_table ptr                | → 0x826EE000   |
| 0x823C5C60   | sprite_data_base_ptr             | → 0x826EBC56   |
| 0x823C5C6C   | bitstream_ptr                    | → 0x826EAB00   |
| 0x823C5D84   | current_sprite_ptr               | → 0x826EA80C   |
| 0x823D5D8C   | framebuffer ptr                  | → 0x826DE000   |
| 0x823D5D90   | palette / render counter data    |                |

## Resource Pool at 0x400EB910 (HUD Sprites Only)

The resource pool (ptr at `0x823B316C`) contains **HUD/menu/font** sprite descriptors, NOT entity sprites. Found ~79 entries with vtable `0x82002558`:

- Font glyphs: 7×12
- HUD elements: 30×30, 64×64, 200×200
- Splash screens: 512×512, 640×480

Entity sprite IDs (0x052F, 0x4063, etc.) do NOT index into this pool — they index into the raw sprite data at 0x826EE000.

## Tools

- **`sprite_extractor.py`** — Reads all entity sprite bitmaps from memory, renders individual frames and sprite sheets as PNGs, outputs `sprite_atlas.json` metadata.
- **`probe_sprite_data.py`** — Investigation tool that discovered the sprite data base address.
- **`probe_sprite_pool.py`** — Investigation tool for the HUD resource pool.
- **`sprite_command_reader.py`** — Reads sprite descriptors via the resource pool (HUD sprites only).
- **`sprite_descriptor_dump.py`** — Dumps sprite descriptors for live entities.

## PPC Rendering Pipeline (for reference)

1. `sub_82086CA8` — Sprite rendering setup, dispatches via vtable
2. `sub_82086D10` — Bitstream decoder/renderer (1200+ lines of PPC, complex bytecode VM with command dispatch, color palette lookups, mirroring, RLE). This is the **runtime renderer** — it interprets the sprite data and writes to the framebuffer. We don't need to replicate it because we can read the source bitmaps directly.
3. `sub_82086938` — Simple wrapper calling sub_820836A0
4. `sub_820836A0` — Pixel writer: writes palette-index bytes to framebuffer at 1216 bytes/row stride (304×4 bytes). Bounds: x < 1216, y < 1024.
