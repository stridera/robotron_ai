# Robotron 2084 — the annotated disassembly, and how we use it

**Source:** Scott Tunstall's complete annotated 6809 disassembly of Williams
arcade Robotron 2084 (~21,183 lines), hosted by Sean Riddle:
**<https://seanriddle.com/robomame.asm>**. We don't copy it here; download it
from there. Wave-by-wave enemy counts are on the same site:
<https://seanriddle.com/robowaves.html>.

```bash
curl -sL https://seanriddle.com/robomame.asm -o robomame.asm
```

It's plain text. Every routine has a symbolic name, and every RAM address in use
has an `EQU` declaration at the top with a comment explaining it.

## Why it matters

The Xbox 360 (XBLA) Robotron runs **the same 6809 ROM bytes at the same
addresses** as the arcade game, so the labels transfer 1:1. We verified this in
May–June 2026: same memory map, same wave-1 layout, player speed within 2%. The
6809 RAM sits at a fixed offset inside Xenia's guest memory (see
[XENIA_MEMORY.md](XENIA_MEMORY.md)).

Our own reverse-engineering was built from partial analysis and
experimentation. **When his labels disagree with our notes, trust his.** Two
examples: our entity decoder once labeled tank shells as quarks and dropped tanks
entirely, which produced a months-long false belief that "quarks teleport". A
check against these labels found both errors (see [ENEMY_MODEL.md](ENEMY_MODEL.md) §7).

[ENEMY_MODEL.md](ENEMY_MODEL.md) is our digest of it for bot work: object pool,
state-word → type table, spawn/death, movement AI per type, and the deep-dive
mechanics, each with `robomame.asm:<line>` citations.

## How to use it

1. To find what a RAM address means, **grep the EQU declarations first**:
   ```bash
   grep -n "^[a-z_].*EQU.*\$98[0-9A-F]\{2\}" robomame.asm
   grep -n "EQU.*\$BDE" robomame.asm
   ```
2. To find what a ROM address does, jump to the line `^XXXX:` (4 hex digits):
   ```bash
   grep -n "^30B3:" robomame.asm
   ```
   You'll usually land in a labeled section such as
   `PLAYER_COLLISION_DETECTION:` or `GRUNT_COLLISION_HANDLER:`.
3. Routine names are SHOUTING_SNAKE_CASE: `grep -n "^[A-Z_]*:"` lists every
   named entry point.

## High-value definitions

The labels that mattered most for reading live game state. 6809 addresses; add
`0x826DE000` for the Xenia guest address.

### Player state
- `$BDE4` — `p1_score` (4-byte BCD, high byte first; the 4th byte matters past 1,000,000)
- `$BDEC` — `p1_men` (lives counter, the **real** one; see Gotchas)
- `$BDED` — `p1_wave` (current wave)
- `$BDEE` — `p1_grunt_delay` (per-wave grunt-speed control)
- `$BE20-$BE3F` — the same fields for player 2
- `$9864` / `$9866` — `player_x` / `player_y`
- `$985A` — `player_object_start` (the player as a regular entity record)
- `$985E` — `player_blitter_destination` (packed X,Y; updated by render)
- `$9848` — `player_collision_detection` flag (1 = player asking about collisions,
  0 = enemy bullets/electrodes asking)

### Linked-list heads (`$98xx`)
- `$9811` — `object_metadata_list_pointer` (task/callback queue)
- `$9813` — `object_metadata_list_2_pointer` (player bullets etc.)
- `$9815` — `task_list_pointer`
- `$9817` — spheroids, enforcers, quarks, sparks, tank shells
- `$981B` — `free_object_list_pointer`
- `$981D` — `third_object_metadata_list_pointer`
- `$981F` — family (Mom/Dad/Mikey)
- `$9821` — grunts, hulks, brains, progs, cruise missiles, tanks
- `$9823` — electrodes

The bot walks `$9817`, `$981F`, `$9821` and `$9823`; reachable = alive.

### Live wave counts
- `$BE68` — `cur_grunts`, `$BE69` — `cur_electrodes`, `$BE6F` — `cur_sphereoids`
  (more at `$BE6x`; grep for `cur_`)

### Entity record layout
For an entity at linked-list node address `X` (full table in
[ENEMY_MODEL.md](ENEMY_MODEL.md) §1):
- `X+0` next pointer · `X+2` animation frame pointer · `X+4/X+5` on-screen
  position (what collision uses) · `X+8` **state word** (the type id) ·
  `X+10/X+12` logical X/Y (what the AI updates) · `X+14/X+16` velocity deltas ·
  `X+19` per-entity timer

### Key routine entry points
- `$30B3` — `PLAYER_COLLISION_DETECTION` (walks `$9821/$9823/$9817/$981F` against
  the player rectangle); `$30EF` — its kill-player branch
- `$3A76` — `GRUNT_COLLISION_HANDLER` (the grunt's state word *is* this address)
- `$2FC2` — player movement (reads the move stick)
- `$31B9` — fire-input dispatcher; `$3279/$3293/$32AD/$32C7` — move laser R/L/U/D
- `$D7C9` — `COLLISION_DETECTION_FUNCTION` (box, then per-pixel)
- `$DDCE` — `ERASE_THEN_REDRAW_OBJECT`; `$DC56` — main IRQ vector
- `$DB9C` — add a BCD number to a player's score

## Gotchas: XBLA vs arcade

1. **Lives:** `$BDEC` is the real lives field. `$98EF` is easy to mistake for
   lives; it's the number of life icons drawn on the HUD.
2. **Input polarity:** the arcade is active-low; the XBLA recompilation is
   positive-logic for movement. Fire bits are in their original positions.
3. **Decoder ROM overlay:** `$0000-$93FF` is either VRAM or decoder ROM (switched
   by a PIA line). Sprite metadata lives in decoder ROM at `$4000-$93FF`; read with
   decode mode on or you'll see VRAM zeros.
4. **Per-pixel collision** (`$D7EE-$D850`): implementing its indexed opcodes
   "correctly" broke gameplay in our custom 6809 emulator experiments. If you
   write an emulator, validate this path carefully.

## When in doubt

If a note anywhere in this project labels a 6809 address with "???", "appears
to", "looks like" or "probably", grep for it in `robomame.asm` first. One line of
his annotation usually settles it.
