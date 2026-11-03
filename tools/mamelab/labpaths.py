"""labpaths.py - where the MAME lab finds things. Every default is overridable
by an environment variable (and, in run_ab.py, by a flag).

  MAMELAB_RL       ~/Code/robotron-rl                    MAME gym, ROM, .venv-collision
  MAMELAB_DEV      ~/Code/robotron                       dev tree (mame_score; legacy lab sources)
  MAMELAB_RESULTS  ~/Code/robotron_data/mamelab/results  run_ab.py --out-root default
  MAMELAB_CK       ~/Code/robotron_data/mamelab/ck       pin_checkout.sh destination
"""
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]          # the robotron_ai package checkout this file lives in


def _p(var, default):
    return Path(os.environ.get(var) or default).expanduser()


RL = _p("MAMELAB_RL", "~/Code/robotron-rl")
DEV = _p("MAMELAB_DEV", "~/Code/robotron")
RESULTS = _p("MAMELAB_RESULTS", "~/Code/robotron_data/mamelab/results")
CK = _p("MAMELAB_CK", "~/Code/robotron_data/mamelab/ck")
