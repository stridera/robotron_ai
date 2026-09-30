import sys

# Planner and FSM knobs are read from the environment when engine modules are
# imported, so any --knob / config "knobs" must land in os.environ BEFORE the
# CLI (and through it the engine) is imported. knobs.py imports nothing from
# the engine.
from .knobs import preload

preload(sys.argv[1:])

from .cli import main  # noqa: E402

if __name__ == "__main__":
    main()
