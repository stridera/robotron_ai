# Documentation

Game internals and archived research for the Robotron bot.

- **What's been tried, and why it was kept or dropped:** [WHAT_WE_TRIED.md](../WHAT_WE_TRIED.md)
- **The engineering state (shipping config, ledgers, knobs):** [STATE_OF_PLAY.md](../STATE_OF_PLAY.md)
- **Running the bot:** [README.md](../README.md)

| Doc | What it's for |
|---|---|
| [ENEMY_MODEL.md](ENEMY_MODEL.md) | How every enemy spawns, moves, shoots and dies, from the game's own code. Read this before proposing a behaviour change. |
| [XENIA_MEMORY.md](XENIA_MEMORY.md) | What the memory-input bot reads on the Xenia emulator: addresses, the entity lists, the type table, and the dead ends. |
| [DISASM_REFERENCE.md](DISASM_REFERENCE.md) | Where to get the annotated arcade disassembly (hosted at seanriddle.com) and how to use it. |
| [SPRITE_DATA.md](SPRITE_DATA.md) | Sprite format in Xenia's memory (March 2026; its banner corrects three names). |
| [archive/MAME_EXPERIMENT_LOG.md](archive/MAME_EXPERIMENT_LOG.md) | The raw June–July 2026 MAME lab notebook, kept for provenance. |

**Not copied from the development machine, and why:**

- The March 2026 memory maps (`MEMORY_MAP.md`, `XENIA_MEMORY_MAP.md`): superseded
  by [XENIA_MEMORY.md](XENIA_MEMORY.md). They predate the list-walk reader and
  carry the old, wrong state-word table. Their useful dead-end lists are folded in.
- The July 2026 latency checklist: carried out. Its results are in
  [STATE_OF_PLAY.md](../STATE_OF_PLAY.md) §5i.
- Dev-tree plans, handoffs and script references (`Plan.md`, `SCRIPTS.md`,
  `BOT_ALGORITHMS.md`, `YOLO_STATUS.md`, `XENIA_CHAMPION_HANDOFF.md`): they
  describe scripts that aren't in this repo. Their history is in
  [WHAT_WE_TRIED.md](../WHAT_WE_TRIED.md).
- The disassembly itself: third-party work. We link to it instead.
