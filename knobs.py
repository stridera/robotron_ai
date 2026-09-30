"""Engine knobs: the planner and FSM settings an operator can change without
touching code, how they get set, and how a session records them.

The engine modules read these from the environment WHEN THEY ARE IMPORTED,
so a knob has to be in os.environ before `robotron_ai.cli` is imported.
`__main__.py` calls preload(argv) first for exactly that reason; a knob set
any later way is silently ignored. Three equivalent ways to set one:

    python -m robotron_ai ... --knob VSEARCH_CLEAR_DANGER=24 --knob VSEARCH_CLEAR_MARGIN=14
    python -m robotron_ai ... --config eric.json      # {"knobs": {"VSEARCH_CLEAR_DANGER": "24"}}
    set VSEARCH_CLEAR_DANGER=24                        # plain environment, before python

--knob wins over the config file, which wins over the shell environment.
`--list-knobs` prints the table below with current values. Every hardware
session writes the values in force into report.json ("knobs"), so a session
folder always says what produced it and tools/compare_sessions.py can show
what differed between two arms.

This module must import nothing from the engine.
"""
import json
import os
import sys
from collections import OrderedDict

# name -> (default as the engine reads it, one-line meaning)
# Defaults are the engine's own; where the vision path (the console) applies a
# different value unless the knob is pinned, the meaning says so.
REGISTRY = OrderedDict([
    # ── clearance planner (engine/clearance_planner.py) ──
    ("VSEARCH_CLEAR_DANGER", ("18", "planner danger radius, px: how close a threat may come before "
                                    "a move is ruled out. Vision path uses 21 unless pinned")),
    ("VSEARCH_CLEAR_MARGIN", ("10", "planner clearance margin, px, added around every threat when "
                                    "scoring moves. Vision path uses 12 unless pinned. Pin both "
                                    "margins together")),
    ("VSEARCH_H", ("6", "planner horizon in ticks (raising it never helped on vision)")),
    ("VSEARCH_FIRE_ALT", ("0", "1 = alternate the fire direction between the two best targets "
                               "(doubles laser throughput). Vision path: ON unless pinned; "
                               "--fire-alt / --no-fire-alt is the usual switch")),
    ("VSEARCH_FIRE_ALT_R", ("160", "px radius for the second fire target. Vision path uses 400 unless "
                                   "VSEARCH_FIRE_ALT is pinned; to change only the radius pin "
                                   "VSEARCH_FIRE_ALT=1 and this together")),
    ("VSEARCH_FIREPLAN", ("0", "1 = fire at the threat that binds the clearance (kill the launcher). "
                               "Vision path: ON unless pinned")),
    ("VSEARCH_FIREPLAN_HULK_R", ("90", "px: fire at a hulk only inside this (hulks are indestructible)")),
    ("VSEARCH_W_SPARK", ("1.8", "danger weight of sparks (enforcer shots) relative to a grunt")),
    ("VSEARCH_W_ENF", ("1.3", "danger weight of enforcers relative to a grunt")),
    ("VSEARCH_DISCOUNT", ("0", "per-tick discount on future danger in the planner (0 = none)")),
    ("VSEARCH_ASMDYN", ("1", "1 = ROM-exact enemy motion in the planner's lookahead (keep on)")),
    ("VSEARCH_LEAST_BAD", ("0", "1 = when every move is unsafe pick the least bad (null on tests)")),
    ("VSEARCH_FRAMESKIP", ("4", "frames per decision the planner assumes (4 = 15 Hz); the loop "
                                "rescales this itself from the measured cadence, leave it")),
    # ── FSM (engine/robotron_fsm.py) ──
    ("FSM_RESCUE_SEEK", ("0", "1 = seek civilians when safe (shipped ON: brain.py sets it)")),
    ("FSM_BRAIN_RESCUE_MULT", ("1.0", "multiplier on the civilian-rescue pull")),
    ("FSM_HULK_DEFLECT", ("1", "1 = step around hulks instead of through them (validated +1.3 waves)")),
    ("FSM_HULK_DEFLECT_R", ("60", "px: hulk deflection radius")),
    ("FSM_HULK_NOFIRE", ("0", "1 = never fire at hulks (lost on MAME)")),
    ("FSM_HULK_PUSH", ("0", "1 = push hulks away with fire when cornered (lost on MAME)")),
    ("FSM_HULK_PUSH_R", ("40", "px: hulk push radius")),
    ("FSM_ADJACENT_QUARK", ("75", "px: treat a quark this close as adjacent (spawns tanks)")),
    ("FSM_HUNT", ("0", "hunt killable enemies when this many or fewer remain (0 = evolved default)")),
    ("FSM_HUNT_STANDOFF", ("90", "px: standoff distance while hunting")),
    ("FSM_NO_SHOOT_SHELLS", ("0", "1 = do not waste shots on tank shells (lost on MAME, flat on vision)")),
    ("FSM_SPAWNER_FIRE", ("0", "1 = prioritise firing at spawners (quarks/spheroids) within range")),
    ("FSM_SPAWNER_FIRE_R", ("150", "px: spawner fire range")),
    ("FSM_THREAT_FIELD", ("0", "1 = repulsive threat field steering (closed: broad and pincer-gated both lost)")),
    ("FSM_FIELD_RADIUS", ("140", "px: threat field radius")),
    ("FSM_FIELD_MAX_THREATS", ("3", "threat field pincer gate")),
    ("FSM_EDGE_DEFLECT", ("0", "1 = steer off the arena edge early (closed, lost)")),
    ("FSM_EDGE_DEFLECT_M", ("55", "px: edge deflection margin")),
    ("FSM_BUFFER_SCALE", ("1.0", "scales the FSM's collision buffers (1.15 and 1.30 both lost)")),
    ("FSM_KITE", ("0", "kiting mode 0-3 (all lost on MAME)")),
    ("FSM_ALWAYS_FIRE", ("0", "1 = hold fire every tick (parked)")),
])

# Knobs the brain overrides on the vision path unless the operator pins them.
VISION_EFFECTIVE = {"VSEARCH_CLEAR_DANGER": "21", "VSEARCH_CLEAR_MARGIN": "12",
                    "VSEARCH_FIRE_ALT": "1", "VSEARCH_FIRE_ALT_R": "400",
                    "VSEARCH_FIREPLAN": "1", "FSM_RESCUE_SEEK": "1"}

PREFIXES = ("VSEARCH_", "FSM_", "ROBOTRON_")
APPLIED = OrderedDict()      # what preload() put into the environment, in order


def parse_pair(text):
    if "=" not in text:
        raise ValueError(f"--knob wants NAME=VALUE, got {text!r}")
    k, v = text.split("=", 1)
    k = k.strip().upper()
    if not k.startswith(PREFIXES):
        raise ValueError(f"{k!r} is not an engine knob (they start with {', '.join(PREFIXES)})")
    return k, v.strip()


def _config_path(argv):
    for i, a in enumerate(argv):
        if a == "--config" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--config="):
            return a.split("=", 1)[1]
    return None


def _knob_args(argv):
    out = []
    for i, a in enumerate(argv):
        if a == "--knob" and i + 1 < len(argv):
            out.append(argv[i + 1])
        elif a.startswith("--knob="):
            out.append(a.split("=", 1)[1])
    return out


def preload(argv, environ=None):
    """Put the config file's "knobs" and every --knob into the environment.
    Called by __main__ before the CLI is imported. Returns what it set."""
    env = os.environ if environ is None else environ
    applied = OrderedDict()
    path = _config_path(argv)
    if path:
        try:
            with open(path, encoding="utf-8") as f:
                cfg = json.load(f)
        except (OSError, ValueError) as e:
            sys.exit(f"error: --config {path}: {e}")
        for k, v in (cfg.get("knobs") or {}).items():
            k2, v2 = parse_pair(f"{k}={v}")
            applied[k2] = v2
    for text in _knob_args(argv):
        try:
            k, v = parse_pair(text)
        except ValueError as e:
            sys.exit(f"error: {e}")
        applied[k] = v
    for k, v in applied.items():
        env[k] = v
        APPLIED[k] = v
    return applied


# brain.py seeds these into the environment at import (setdefault), so their
# mere presence in os.environ does not mean the operator pinned them.
BRAIN_SEEDED = {"VSEARCH_ASMDYN": "1", "VSEARCH_H": "6", "VSEARCH_CLEAR_DANGER": "18",
                "VSEARCH_CLEAR_MARGIN": "10", "FSM_RESCUE_SEEK": "1"}


def pinned(env, applied=None):
    """Knobs the operator set: via preload (--knob / config) or found in the
    environment with a value the brain would not have seeded."""
    applied = APPLIED if applied is None else applied
    out = set(applied)
    for k in env:
        if k.startswith(PREFIXES) and k != "ROBOTRON_ARM" and k not in out:
            if k not in BRAIN_SEEDED or env[k] != BRAIN_SEEDED[k]:
                out.add(k)
    return out


def effective_values(environ=None, vision=True, applied=None):
    """Every registered knob with the value actually in force, following
    brain.py's rules for the vision path: the vision margins apply only if
    NEITHER margin is pinned, the vision fire-alt radius only if
    VSEARCH_FIRE_ALT is not pinned, fireplan only if not pinned. Plus any
    unregistered knob the operator set. Written into report.json."""
    env = os.environ if environ is None else environ
    pin = pinned(env, applied)
    out = OrderedDict()
    for k, (default, _) in REGISTRY.items():
        out[k] = env.get(k, default)
    if vision:
        if not ({"VSEARCH_CLEAR_DANGER", "VSEARCH_CLEAR_MARGIN"} & pin):
            out["VSEARCH_CLEAR_DANGER"], out["VSEARCH_CLEAR_MARGIN"] = "21", "12"
        if "VSEARCH_FIRE_ALT" not in pin:
            out["VSEARCH_FIRE_ALT"], out["VSEARCH_FIRE_ALT_R"] = "1", "400"
        if "VSEARCH_FIREPLAN" not in pin:
            out["VSEARCH_FIREPLAN"] = "1"
        out["FSM_RESCUE_SEEK"] = env.get("FSM_RESCUE_SEEK", "1")
    for k in sorted(env):
        if k.startswith(PREFIXES) and k not in out and k != "ROBOTRON_ARM":
            out[k] = env[k]
    return out


def current_values(environ=None, vision=True):
    return effective_values(environ, vision)


def config_dict(cfg):
    """The effective CLI settings as plain JSON for report.json (only
    simple values; paths and objects are stringified)."""
    out = OrderedDict()
    for k in sorted(vars(cfg)):
        v = getattr(cfg, k)
        if isinstance(v, (int, float, str, bool, type(None))):
            out[k] = v
        elif isinstance(v, (list, tuple)):
            out[k] = [x if isinstance(x, (int, float, str, bool)) else str(x) for x in v]
        else:
            out[k] = str(v)
    return out


def describe(environ=None, vision=True):
    """The --list-knobs text."""
    env = os.environ if environ is None else environ
    eff = effective_values(env, vision)
    pin = pinned(env)
    L = ["engine knobs (set with --knob NAME=VALUE, a config \"knobs\" block, or the environment)",
         "", f"{'knob':<26}{'default':>8}{'in force':>10}  meaning"]
    for k, (default, meaning) in REGISTRY.items():
        mark = "*" if k in pin else " "
        L.append(f"{k:<26}{default:>8}{eff[k]:>9}{mark}  {meaning}")
    L.append("")
    L.append("  * = pinned for this run. 'in force' is the value the " +
             ("vision path (console)" if vision else "memory path") + " will run with;")
    L.append("    the brain applies its vision defaults only to knobs that are not pinned, so")
    L.append("    pinning one margin leaves the other at the engine default (pin both).")
    L.append("  Closed knobs (measured, lost or null) are listed in STATE_OF_PLAY.md section 5g;")
    L.append("  candidates worth a console A/B are in docs/ERIC_HANDOFF.md.")
    return "\n".join(L)
