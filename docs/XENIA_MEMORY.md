# Robotron 2084 on Xenia — memory reference

What the memory-input bot (`--input memory`) reads from the Xbox game running in
the Xenia emulator, checked against `engine/game_state.py` and
`engine/jit_entity_reader.py` on 2026-09-10. The video bot (the one that runs on
a real console) reads none of this; it's here for the emulator path, the
exact-state harness, and anyone debugging either.

Related: [ENEMY_MODEL.md](ENEMY_MODEL.md) (what each entity *does*, from the
game's code) · [DISASM_REFERENCE.md](DISASM_REFERENCE.md) (the annotated 6809
disassembly and its labels) · [SPRITE_DATA.md](SPRITE_DATA.md) (sprite format).

## The key fact

The XBLA game runs the **original 6809 arcade code**. Its 6809 RAM sits at a fixed
place in Xenia's guest memory:

```
PPC guest address = 0x826DE000 + 6809 address
```

So every arcade label applies directly: `$9821` (a list head) is at
`0x826E7821`, `$BDED` (wave) is at `0x826EBDED`, and so on. All multi-byte values
are **big-endian**. Guest addresses are offsets into Xenia's guest map
(host base `0x100000000`); the game image is at `0x82000000`.

## Game state

| What | Address | Notes |
|---|---|---|
| Wave | `0x82388E20` (u32) | Read it, don't write it: it's a display copy. Writing 24 changed the screen but not the game (Sept 2026). |
| Score | `0x82388E24` (u32) | Updates before the HUD refreshes |
| Lives | `0x82388E48` (u32) | `0` means **last life**, one more chance remains. Reads `0xFFFFFFFF` briefly during death freezes; only a persistent (~3 s) `0xFFFFFFFF` is game over. |
| Player position | `0x826E7864` | 16-bit fixed point: gx at `+0`, gy at `+2` (not `+1`) |
| Timer | `0x826DDCE0` (u32) | |

Player-reachable bounds (measured July 2026): **gx 7–140, gy 24–223** game units.
`coords.py` maps game units into the planner's 665×492 pixel space.

## Entities: walk the four 6809 lists

This is the reader in use since July 3, 2026 (`GameStateReader._walk_all_lists_alive`).

| Head (6809) | Guest address | Contents |
|---|---|---|
| `$9821` | `0x826E7821` | grunts, hulks, brains, progs, cruise missiles, tanks |
| `$9817` | `0x826E7817` | spheroids, enforcers, sparks, quarks, tank shells |
| `$981F` | `0x826E781F` | family (Mikey, Mom, Dad) |
| `$9823` | `0x826E7823` | electrodes |

- Each head holds a **u16 big-endian offset** (from `0x826DE000`) to the first node;
  `0` means empty.
- Each node is the game's 24-byte object record: `+0` next pointer, `+4/+5`
  on-screen position, `+8` **state word** (the type), `+0x0A/+0x0C` logical X/Y
  (8.8 fixed point). Full layout in [ENEMY_MODEL.md](ENEMY_MODEL.md) §1.
- **Reachable = alive.** Freed records keep their stale bytes and there's no in-use
  flag, so never scan the pool directly; walk the lists.
- Our reader races the running game, so by default it walks each list twice and
  keeps only nodes seen both times (torn-read guard). `ROBOTRON_SINGLE_READ=1`
  skips the second walk for freshness.

Switching to this reader from the old slot-pool scan cut about 250 ms of
staleness and took the memory bot's ceiling from W18 to W39 in one game.

### State word → type

From `STATE_WORD_LABELS` in `engine/jit_entity_reader.py`, corrected on
2026-07-02 against the disassembly:

| State word | Label | Entity |
|---|---|---|
| `0x3A76` | G | Grunt |
| `0x3AA9` | E | Electrode (plus wave-8+ variants `0x3B85/8A/8F`; `0x3B94/99/A4` speculative) |
| `0x00B6` | H | Hulk |
| `0x1DD6` | B | Brain |
| `0x1483` | F | Enforcer |
| `0x14DC` | FB | Enforcer spark |
| `0x12C8` | S | Spheroid |
| `0x4BC9` | Q | Quark (the *only* quark state word) |
| `0x4DF2` | T | Tank |
| `0x4FD5` | TS | Tank shell |
| `0x1F1F` | P | Prog |
| `0x2119` | MS | Cruise missile |
| `0x0330` / `0x0335` / `0x033A` | CC / CW / CM | Mikey / Mom / Dad |

Suppressed as non-entities (`_SKIP`): score popups (`0x0485`, `0x0489`,
`0x048D`, `0x0491`, `0x0495`), the civilian death skull (`0x0437`), explosion
frames (`0xB3EF`, `0xB470`, `0xB4F1`), and a set of UI/border/wave-transition
artifacts (`0x2171`, `0x2481`, `0x2561`, `0x40F5`, `0x55FE`, `0x551E`, `0x566E`,
`0x558E`, `0x0067`, `0x21E1`, `0x2251`, `0x22C1`, `0x2331`, `0x23A1`, `0x2411`).

**Traps that cost us weeks:** `0x2119` is a cruise missile, not a brain; `0x4DF2`
and `0x4FD5` are the tank and tank shell, not quarks; `0x4800` is a phantom
nothing in the ROM uses; `0x0390` is a score sprite, not a prog.

## The JIT hook buffer (custom Xenia build only)

Wave, score, lives and a true 60 Hz frame counter come from a shared buffer
written by hooks compiled into our custom `xenia-canary` build
(`x64_sequences.cc`): a frame hook at PPC `0x8207C928` and an outer-loop hook at
`0x82060398`. The buffer's address is published in
`%TEMP%/robotron_jit_entity_ptr.bin`. Header (little-endian):

| Offset | Field |
|---|---|
| `+0x00` | magic `0x454E5421` (`'ENT!'`) |
| `+0x04` | frame counter |
| `+0x08` | `outer_loop_count`: increments once per true 60 Hz frame (used for frame-sync) |
| `+0x0C` / `+0x10` / `+0x14` | wave / score / lives |
| `+0x18` onward | legacy slot-pool snapshot, static-frame counts and write mask (old reader) |

A stock Xenia build has none of this; the memory path needs the custom build.

## Legacy structures (still in the code, not used for entities)

- **`_6809_LIST_HEADS`** in `game_state.py` (`$9811`, `$9703`, `$A00A`, `$A05F`,
  plus `$9823`): the March 2026 heads. The enemy and tank heads are **wrong**
  (they walk garbage); only electrodes and civilians were ever right. Kept for
  logging and the old path.
- **The slot pool at `0x826E78D4`** (101 × 24 bytes): turned out to live inside
  the renderer's decode buffer, not the game's authoritative state. Stale records
  persist after death, which is where the "ghost" problems came from.
- **Live counter blocks** at `0x826E9DFA`, `0x826E9E36`, `0x826E9E68`: three
  rotating 9-byte tuples of remaining initial-wave entities. They don't track
  spawned enemies, and the byte-to-type mapping was never fully verified.
- **Sprite data** at `0x826EE000`: see [SPRITE_DATA.md](SPRITE_DATA.md).

## Waves

- After wave 40 the game **repeats waves 21–40** forever, so W40+ is every pattern
  seen, and "wave 100" is an endurance test through repeats.
- Brain waves are every 5th wave; quark (tank) waves are 7, 12, 17, 22, 27 and so
  on. Per-wave enemy counts: <https://seanriddle.com/robowaves.html>.

## Dead ends (don't re-investigate)

From the March 2026 Xenia investigation and later work:

- **The entity manager** (`0x82389688 → 0x4005CDC0`): its counters (`+7368`,
  `+7372`, `+5764/+5776`, `+6268`) are stale or unrelated, its list heads are null
  at runtime, and its pools point at zeroed memory. Not the enemy list.
- **`sub_8207C928`** traverses a render/layout structure, not gameplay entities.
- **PPC breakpoints don't fire on JIT-compiled code**, and Xenia's data breakpoints
  aren't implemented. Hooks at `0x82329AB0` (suspected death handler) and
  `0x823D5D8C` (counter decrement, reached by indirect dispatch) never fire. PPC
  code-cave patches crash the JIT.
- **Write-mask and accumulator tricks** (write mask at `0x820A2C38`, single-frame
  diffs, rolling windows over 500 ms): too sparse or too stale. Superseded by the
  list walk.
- **Starting a game at a later wave** by writing `0x82388E20` (a display copy), or
  the slot-1 "wave" word (a frame counter).
- **Cheap screen capture** (BitBlt, PrintWindow without full-content rendering):
  returns black frames from Xenia's D3D12 window. Running two window-capture
  processes at once crashes Xenia.
