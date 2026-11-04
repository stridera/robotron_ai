"""Tests for the five 2026-11 behaviour knobs (OFF by default, except FSM_FIRE_SKIP_RECEDING
and FSM_FIRE_FALLBACK_REACH which are vision-path defaults, see VisionDefaultsTest):
FSM_HULK_CLOSING, FSM_FIRE_FALLBACK_REACH, FSM_FIRE_SKIP_RECEDING,
VSEARCH_CLEAR_EXTENTS, FSM_SAVE_GRUNT.

Run from the package's parent directory:
    python -m unittest robotron_ai.tests.test_behaviour_knobs -v

Scenes are in planner pixels (y down); the player is at (300, 250). Sprites are
(x, y, name, vx, vy) fed straight to ChampionBrain._champion_action so the
velocities are exact. Directions: 1=N 2=NE 3=E 4=SE 5=S 6=SW 7=W 8=NW.
"""
import hashlib
import random
import unittest

import numpy as np

from .. import brain as brain_mod
from .. import knobs
from ..engine import clearance_planner as cp
from ..engine import robotron_fsm as fsm

P = (300.0, 250.0, "Player", 0.0, 0.0)

# sha256 of the (move, fire) sequence _golden_run() produced on main @ 53e36f3,
# i.e. BEFORE the knobs existed. The knobs off must reproduce it exactly.
GOLDEN = {True: "a87d2453e1c92a3a72c8713b1737b7e5151613d0e6aab5b097811b650bdb7989",
          False: "c5f44c826e6bd20ef88590b27cf7d865066d5202a6fb33c8ee5bac75f0eebac1"}


def _all_off():
    fsm.HULK_CLOSING = fsm.SKIP_RECEDING = False
    fsm.CTX = None
    cp.set_fire_gates(False, False)
    cp.set_fire_exclude(())
    cp.set_clear_extents(0.0)
    brain_mod.FIRE_FALLBACK_REACH = 0.0
    brain_mod.SAVE_GRUNT = 0
    cp.set_fire_alt(False)
    cp.set_fireplan(False)
    cp.set_margins(18, 10)
    cp.set_tick_scale(1.0)


def _golden_frames(n=120, seed=11):
    rng = random.Random(seed)
    names = ["Grunt", "Grunt", "Hulk", "Electrode", "EnforcerBullet", "TankShell", "CruiseMissile",
             "Enforcer", "Brain", "Quark", "Mommy", "Daddy", "Prog", "Tank"]
    return [((rng.uniform(30, 630), rng.uniform(30, 460)),
             [(rng.uniform(0, 665), rng.uniform(0, 492), rng.choice(names))
              for _ in range(rng.randint(2, 22))]) for _ in range(n)]


def _golden_run(vision):
    """The vision path now defaults SKIP_RECEDING and FALLBACK_REACH on, so the
    golden pins both to 0 (as `--knob NAME=0` does) to reproduce the pre-knob run."""
    _all_off()
    saved = (brain_mod._USER_PINNED_SKIP_RECEDING, brain_mod._USER_PINNED_FALLBACK_REACH)
    brain_mod._USER_PINNED_SKIP_RECEDING = brain_mod._USER_PINNED_FALLBACK_REACH = True
    try:
        b = brain_mod.ChampionBrain(lag_ticks=0.7, use_coaster=vision, fire_alt=vision)
        out = [b.decide(p, e) for p, e in _golden_frames()]
    finally:
        brain_mod._USER_PINNED_SKIP_RECEDING, brain_mod._USER_PINNED_FALLBACK_REACH = saved
    return hashlib.sha256(repr(out).encode()).hexdigest()


class Base(unittest.TestCase):
    def setUp(self):
        _all_off()
        self.b = brain_mod.ChampionBrain(lag_ticks=0.0, player_lead_ticks=0.0)

    def tearDown(self):
        _all_off()

    def act(self, sprites, **knob):
        """One decision on a fresh brain state with the given knobs set."""
        fsm.HULK_CLOSING = knob.get("hulk", False)
        fsm.SKIP_RECEDING = knob.get("skip", False)
        cp.set_fire_gates(knob.get("hulk", False), knob.get("skip", False))
        brain_mod.FIRE_FALLBACK_REACH = knob.get("reach", 0.0)
        self.b.reset()
        return self.b._champion_action([P] + list(sprites))


class OffIsIdenticalTest(unittest.TestCase):
    def tearDown(self):
        _all_off()

    def test_vision_pipeline_matches_the_pre_knob_golden(self):
        self.assertEqual(_golden_run(True), GOLDEN[True])

    def test_memory_pipeline_matches_the_pre_knob_golden(self):
        self.assertEqual(_golden_run(False), GOLDEN[False])

    def test_defaults_are_off(self):
        self.assertFalse(fsm.HULK_CLOSING)
        self.assertFalse(fsm.SKIP_RECEDING)
        self.assertIsNone(fsm.CTX)
        self.assertFalse(cp.HULK_CLOSING or cp.SKIP_RECEDING)
        self.assertEqual(cp.CLEAR_EXTENTS, 0.0)
        self.assertEqual(brain_mod.FIRE_FALLBACK_REACH, 0.0)
        self.assertEqual(brain_mod.SAVE_GRUNT, 0)

    def test_registered_and_listed(self):
        text = knobs.describe({}, vision=True)
        for k in ("FSM_HULK_CLOSING", "FSM_FIRE_FALLBACK_REACH", "FSM_FIRE_SKIP_RECEDING",
                  "VSEARCH_CLEAR_EXTENTS", "FSM_SAVE_GRUNT"):
            self.assertIn(k, knobs.REGISTRY)
            self.assertEqual(knobs.REGISTRY[k][0], "0")
            self.assertIn(k, text)


def _brain(vision, skip_pinned=False, reach_pinned=False, skip_env=False, reach_px=0.0):
    """Construct a brain as brain.py would after import with the given pins.
    A pinned knob keeps the import-time value (skip_env / reach_px), as --knob does."""
    _all_off()
    fsm.SKIP_RECEDING, brain_mod.FIRE_FALLBACK_REACH = skip_env, reach_px
    cp.set_fire_gates(skip_receding=skip_env)
    saved = (brain_mod._USER_PINNED_SKIP_RECEDING, brain_mod._USER_PINNED_FALLBACK_REACH)
    brain_mod._USER_PINNED_SKIP_RECEDING, brain_mod._USER_PINNED_FALLBACK_REACH = skip_pinned, reach_pinned
    try:
        return brain_mod.ChampionBrain(lag_ticks=0.7, use_coaster=vision)
    finally:
        brain_mod._USER_PINNED_SKIP_RECEDING, brain_mod._USER_PINNED_FALLBACK_REACH = saved


class VisionDefaultsTest(unittest.TestCase):
    """FSM_FIRE_SKIP_RECEDING=1 and FSM_FIRE_FALLBACK_REACH=250 are vision defaults;
    each is pinned independently; the memory path keeps both at 0."""

    def tearDown(self):
        _all_off()

    def state(self):
        return (fsm.SKIP_RECEDING, cp.SKIP_RECEDING, brain_mod.FIRE_FALLBACK_REACH)

    def test_vision_default_on(self):
        _brain(True)
        self.assertEqual(self.state(), (True, True, 250.0))

    def test_memory_path_stays_off(self):
        _brain(False)
        self.assertEqual(self.state(), (False, False, 0.0))

    def test_explicit_zero_pin_turns_each_off(self):
        _brain(True, skip_pinned=True, reach_pinned=True)
        self.assertEqual(self.state(), (False, False, 0.0))

    def test_pinning_skip_leaves_reach_on(self):
        _brain(True, skip_pinned=True)
        self.assertEqual(self.state(), (False, False, 250.0))

    def test_pinning_reach_leaves_skip_on(self):
        _brain(True, reach_pinned=True)
        self.assertEqual(self.state(), (True, True, 0.0))

    def test_a_pinned_nonzero_value_is_kept(self):
        _brain(True, reach_pinned=True, reach_px=120.0)
        self.assertEqual(brain_mod.FIRE_FALLBACK_REACH, 120.0)

    def test_knobs_report_the_vision_effective_values(self):
        v = knobs.effective_values({}, vision=True, applied={})
        self.assertEqual((v["FSM_FIRE_SKIP_RECEDING"], v["FSM_FIRE_FALLBACK_REACH"]), ("1", "250"))
        m = knobs.effective_values({}, vision=False, applied={})
        self.assertEqual((m["FSM_FIRE_SKIP_RECEDING"], m["FSM_FIRE_FALLBACK_REACH"]), ("0", "0"))
        text = knobs.describe({}, vision=True)
        for k, val in (("FSM_FIRE_SKIP_RECEDING", "1"), ("FSM_FIRE_FALLBACK_REACH", "250")):
            line = next(l for l in text.splitlines() if l.startswith(k))
            self.assertIn(f" {val} ", line)

    def test_knobs_zero_pin_and_independence(self):
        v = knobs.effective_values({"FSM_FIRE_SKIP_RECEDING": "0"}, vision=True, applied={})
        self.assertEqual((v["FSM_FIRE_SKIP_RECEDING"], v["FSM_FIRE_FALLBACK_REACH"]), ("0", "250"))
        v = knobs.effective_values({"FSM_FIRE_FALLBACK_REACH": "0"}, vision=True, applied={})
        self.assertEqual((v["FSM_FIRE_SKIP_RECEDING"], v["FSM_FIRE_FALLBACK_REACH"]), ("1", "0"))

    def test_pinning_one_does_not_drop_other_vision_defaults(self):
        v = knobs.effective_values({"FSM_FIRE_SKIP_RECEDING": "0"}, vision=True, applied={})
        self.assertEqual((v["VSEARCH_FIREPLAN"], v["VSEARCH_CLEAR_MARGIN"]), ("1", "12"))


class HulkClosingTest(Base):
    GRUNT = (300.0, 190.0, "Grunt", 0.0, 0.0)          # 60 px north: the next target

    def test_off_shoots_the_adjacent_hulk_whichever_way_it_walks(self):
        for vx in (3.0, -3.0):
            self.assertEqual(self.act([(335.0, 250.0, "Hulk", vx, 0.0), self.GRUNT])[1], 3)

    def test_hulk_walking_away_is_skipped_for_the_next_target(self):
        away = (335.0, 250.0, "Hulk", 3.0, 0.0)
        self.assertEqual(self.act([away, self.GRUNT], hulk=True)[1], 1)

    def test_hulk_closing_is_still_shot(self):
        closing = (335.0, 250.0, "Hulk", -3.0, 0.0)
        self.assertEqual(self.act([closing, self.GRUNT], hulk=True)[1], 3)

    def test_hulk_within_25px_is_shot_regardless(self):
        self.assertEqual(self.act([(320.0, 250.0, "Hulk", 3.0, 0.0), self.GRUNT], hulk=True)[1], 3)

    def test_player_walking_away_from_a_still_hulk_counts_as_not_closing(self):
        # relative velocity = hulk minus player: still hulk, player moving west
        self.b.last_mv = 7
        self.b.player_lead_ticks = 0.0
        fsm.HULK_CLOSING = True
        ctx = self.b._fire_context([(335.0, 250.0, "Hulk", 0.0, 0.0, )], 300.0, 250.0)
        self.assertEqual(ctx["closing"], set())
        self.b.last_mv = 3                      # player walking at it: closing
        ctx = self.b._fire_context([(335.0, 250.0, "Hulk", 0.0, 0.0)], 300.0, 250.0)
        self.assertEqual(ctx["closing"], {(335.0, 250.0, "Hulk")})

    def test_nothing_else_to_shoot_means_fire_stay_then_the_move_fallback(self):
        away = (335.0, 250.0, "Hulk", 3.0, 0.0)
        fsm.HULK_CLOSING = True
        fsm.CTX = {"closing": set(), "skip": set()}
        mv, fr = fsm.chooseOutputs([(300.0, 250.0, "Player"), (335.0, 250.0, "Hulk")])
        self.assertEqual(fr, fsm.STAY)

    def test_fireplan_aim_is_gated_too(self):
        cp.set_fireplan(True)
        hulk_away = (330.0, 250.0, "Hulk", 4.0, 0.0)
        sp = [P, hulk_away]
        _, fr_off = cp.clearance_search(sp, 3, 7)
        self.assertEqual(fr_off, 3)                       # FIREPLAN aims at the binding hulk
        cp.set_fire_gates(hulk_closing=True)
        self.assertEqual(cp.clearance_search(sp, 3, 7)[1], 7)   # walking away: FSM's fire kept
        closing = [P, (330.0, 250.0, "Hulk", -4.0, 0.0)]
        self.assertEqual(cp.clearance_search(closing, 3, 7)[1], 3)


class SkipRecedingTest(Base):
    RECEDING = (380.0, 250.0, "EnforcerBullet", 6.0, 0.0)      # 80 px east, flying away
    APPROACH = (300.0, 170.0, "EnforcerBullet", 0.0, 5.0)      # 80 px north, coming in

    def test_off_shoots_the_nearest_projectile(self):
        self.assertEqual(self.act([self.RECEDING, self.APPROACH])[1], 3)

    def test_receding_spark_skipped_approaching_one_shot(self):
        self.assertEqual(self.act([self.RECEDING, self.APPROACH], skip=True)[1], 1)

    def test_only_a_receding_spark_falls_through_to_the_next_tier(self):
        grunt = (300.0, 330.0, "Grunt", 0.0, 0.0)
        self.assertEqual(self.act([self.RECEDING, grunt])[1], 3)
        self.assertEqual(self.act([self.RECEDING, grunt], skip=True)[1], 5)

    def test_cruise_missile_is_never_skipped(self):
        self.assertFalse(cp.projectile_receding("CruiseMissile", 300, 250, 0, 0, 380, 250, 8, 0))
        missile = (380.0, 250.0, "CruiseMissile", 6.0, 0.0)
        self.assertEqual(self.act([missile, self.APPROACH], skip=True)[1], 3)

    def test_unknown_velocity_is_never_skipped(self):
        self.assertFalse(cp.projectile_receding("EnforcerBullet", 300, 250, 0, 0, 380, 250, 0, 0))

    def test_player_walking_toward_it_keeps_it_a_target(self):
        # shell flies away at 4 px/tick but the player closes at 9.5: not receding
        self.assertTrue(cp.projectile_receding("EnforcerBullet", 300, 250, 0, 0, 380, 250, 4, 0))
        self.assertFalse(cp.projectile_receding("EnforcerBullet", 300, 250, 9.5, 0, 380, 250, 4, 0))
        # flying away faster than the player walks: range still grows but he is walking at it
        self.assertFalse(cp.projectile_receding("EnforcerBullet", 300, 250, 9.5, 0, 380, 250, 12, 0))

    def test_shell_about_to_bounce_back_is_kept(self):
        # far from the wall: gone for good
        self.assertTrue(cp.projectile_receding("TankShell", 300, 250, 0, 0, 340, 250, 25, 0))
        # player and shell both near the east wall: it reflects and comes straight back
        self.assertFalse(cp.projectile_receding("TankShell", 560, 250, 0, 0, 600, 250, 20, 0))
        # the same geometry as a spark does not bounce
        self.assertTrue(cp.projectile_receding("EnforcerBullet", 560, 250, 0, 0, 600, 250, 20, 0))

    def test_fire_alt_does_not_alternate_onto_a_receding_spark(self):
        sp = [P, (360.0, 250.0, "Grunt", 0.0, 0.0), (300.0, 190.0, "EnforcerBullet", 0.0, -8.0)]
        cp.set_fire_alt(True)      # FSM moves west: the player is not walking at the spark
        self.assertEqual([cp.clearance_search(sp, 7, 3)[1] for _ in range(4)], [3, 1, 3, 1])
        cp.set_fire_alt(True)
        cp.set_fire_gates(skip_receding=True)
        self.assertEqual([cp.clearance_search(sp, 7, 3)[1] for _ in range(4)], [3, 3, 3, 3])

    def test_fireplan_does_not_aim_at_a_receding_spark(self):
        cp.set_fireplan(True)
        sp = [P, (330.0, 250.0, "EnforcerBullet", 8.0, 0.0)]
        # the spark is receding but 30 px away: the planner would bind on it only
        # if the player walks into it; the gate keeps the FSM's own fire
        cp.set_fire_gates(skip_receding=True)
        self.assertEqual(cp.clearance_search(sp, 3, 7)[1], 7)


class FallbackReachTest(Base):
    MOMMY = (350.0, 300.0, "Mommy", 0.0, 0.0)          # SE of the player: the move heads there

    def test_off_fires_along_the_move_direction_at_the_civilian(self):
        grunt = (540.0, 250.0, "Grunt", 0.0, 0.0)      # due east, 240 px: beyond the FSM's fire radius
        mv, fr = self.act([self.MOMMY, grunt])
        self.assertEqual((mv, fr), (4, 4))

    def test_lined_up_grunt_is_aimed_at_instead(self):
        grunt = (540.0, 250.0, "Grunt", 0.0, 0.0)
        mv, fr = self.act([self.MOMMY, grunt], reach=250.0)
        self.assertEqual((mv, fr), (4, 3))

    def test_grunt_out_of_reach_or_not_lined_up_keeps_the_old_fallback(self):
        far = (580.0, 250.0, "Grunt", 0.0, 0.0)                          # 280 px
        off_axis = (540.0, 337.0, "Grunt", 0.0, 0.0)                     # ~20 deg off east
        self.assertEqual(self.act([self.MOMMY, far], reach=250.0), (4, 4))
        self.assertEqual(self.act([self.MOMMY, off_axis], reach=250.0), (4, 4))

    def test_shot_is_led_by_the_target_velocity(self):
        # 18 deg off east now, but walking north it crosses the east line in time
        grunt = (540.0, 330.0, "Grunt", 0.0, -15.0)
        self.assertEqual(self.act([self.MOMMY, grunt], reach=300.0)[1], 3)
        still = (540.0, 330.0, "Grunt", 0.0, 0.0)
        self.assertEqual(self.act([self.MOMMY, still], reach=300.0)[1], 4)

    def test_never_aims_at_family_hulks_or_electrodes(self):
        for name in ("Hulk", "Electrode", "Daddy"):
            thing = (540.0, 250.0, name, 0.0, 0.0)
            self.assertEqual(self.act([self.MOMMY, thing], reach=250.0)[1], 4, name)

    def test_nearest_lined_up_target_wins(self):
        near = (460.0, 250.0, "Grunt", 0.0, 0.0)
        far = (300.0, 20.0, "Grunt", 0.0, 0.0)            # due north, 230 px
        brain_mod.FIRE_FALLBACK_REACH = 250.0
        self.assertEqual(self.b._lined_up_fire(300.0, 250.0, [far, near]), 3)


class ClearExtentsTest(unittest.TestCase):
    def tearDown(self):
        _all_off()

    @staticmethod
    def _T(name_xy, extents=None):
        tx = np.array([p[0] for p in name_xy]); ty = np.array([p[1] for p in name_xy])
        z = np.zeros(len(name_xy))
        T = (tx, ty, z, z, np.ones(len(name_xy)), np.zeros(len(name_xy), dtype=bool), z,
             np.zeros(len(name_xy), dtype=bool))
        return T + extents if extents else T

    def _clr(self, hulk_at, k, d=5):
        _all_off()
        cp.set_clear_extents(k)
        hx, hy = cp._half_extent(cp._ROM_SIZE["Hulk"])
        ext = (np.array([hx]), np.array([hy])) if k > 0 else None
        return cp._heading_clearance(300.0, 250.0, self._T([hulk_at], ext), d, 1)

    def test_zero_is_centre_to_centre(self):
        self.assertAlmostEqual(self._clr((400.0, 259.2), 0.0), np.hypot(100.0, 0.0), places=6)

    def test_extents_reduce_clearance_in_proportion_to_k(self):
        base = self._clr((400.0, 259.2), 0.0)
        half = self._clr((400.0, 259.2), 0.5)
        full = self._clr((400.0, 259.2), 1.0)
        self.assertLess(half, base)
        self.assertLess(full, half)
        self.assertAlmostEqual(base - full, 2 * (base - half), places=6)

    def test_extent_is_anisotropic_hulk_plus_player_along_the_line(self):
        # player steps south to y=259.2; hulk due east: x half-sizes apply
        hx, _ = cp._half_extent(cp._ROM_SIZE["Hulk"])
        px_, _ = cp._half_extent(cp._ROM_PLAYER)
        d = np.hypot(100.0, 259.2 - 259.2)
        self.assertAlmostEqual(self._clr((400.0, 259.2), 1.0), d - (hx + px_), places=6)
        # hulk due south of the stepped player: y half-sizes (taller than wide in planner px)
        _, hy = cp._half_extent(cp._ROM_SIZE["Hulk"])
        _, py_ = cp._half_extent(cp._ROM_PLAYER)
        self.assertAlmostEqual(self._clr((300.0, 359.2), 1.0), 100.0 - (hy + py_), places=6)

    def test_overlapping_boxes_clamp_at_zero(self):
        self.assertEqual(self._clr((310.0, 259.2), 1.0), 0.0)

    def test_electrode_uses_the_widest_frame(self):
        self.assertEqual(cp._ROM_SIZE["Electrode"], (10, 9))

    def test_extents_change_planner_decisions_only_when_on(self):
        rng = random.Random(5)
        scenes = []
        for _ in range(300):
            sp = [(rng.uniform(100, 560), rng.uniform(100, 400), "Player", 0.0, 0.0)]
            for _ in range(rng.randint(2, 8)):
                sp.append((sp[0][0] + rng.uniform(-90, 90), sp[0][1] + rng.uniform(-90, 90),
                           rng.choice(["Hulk", "Grunt", "Electrode", "EnforcerBullet"]),
                           rng.uniform(-8, 8), rng.uniform(-8, 8)))
            scenes.append((sp, rng.randint(1, 8), rng.randint(1, 8)))
        _all_off()
        base = [cp.clearance_search(*sc) for sc in scenes]
        self.assertEqual(base, [cp._clearance_search_impl(*sc) for sc in scenes])
        cp.set_clear_extents(1.0)
        on = [cp.clearance_search(*sc) for sc in scenes]
        self.assertGreater(sum(a != b for a, b in zip(base, on)), 10)
        cp.set_clear_extents(0.0)
        self.assertEqual(base, [cp.clearance_search(*sc) for sc in scenes])


class SaveGruntTest(Base):
    MOMMY = (150.0, 350.0, "Mommy", 0.0, 0.0)
    FAR_GRUNT = (550.0, 100.0, "Grunt", 0.0, 0.0)

    def setUp(self):
        super().setUp()
        brain_mod.SAVE_GRUNT = 1
        self.t = [1000.0]
        self.b.clock = lambda: self.t[0]

    def tick(self, sprites, dt=0.07):
        self.t[0] += dt
        return self.b._champion_action([P] + list(sprites))

    def test_off_the_bot_shoots_the_last_grunt(self):
        brain_mod.SAVE_GRUNT = 0
        self.assertGreaterEqual(self.tick([self.MOMMY, self.FAR_GRUNT])[1], 1)

    def test_one_grunt_and_a_civilian_holds_fire_and_rescues(self):
        mv, fr = self.tick([self.MOMMY, self.FAR_GRUNT])
        self.assertEqual(fr, 0)
        self.assertIn(mv, (5, 6, 7))                      # toward the civilian (SW of the player)
        self.assertTrue(self.b.save_active)

    def test_nothing_fires_even_with_fire_alt_and_fireplan_on(self):
        cp.set_fire_alt(True)
        cp.set_fireplan(True)
        for _ in range(4):
            self.assertEqual(self.tick([self.MOMMY, self.FAR_GRUNT, (330.0, 250.0, "Electrode", 0, 0)])[1], 0)

    def test_grunt_within_45px_ends_save_mode_and_is_shot(self):
        self.tick([self.MOMMY, self.FAR_GRUNT])
        mv, fr = self.tick([self.MOMMY, (335.0, 250.0, "Grunt", 0.0, 0.0)])     # 35 px east
        self.assertEqual(fr, 3)
        self.assertFalse(self.b.save_active)

    def test_reentry_needs_the_grunt_beyond_60px(self):
        self.tick([self.MOMMY, self.FAR_GRUNT])
        self.tick([self.MOMMY, (335.0, 250.0, "Grunt", 0.0, 0.0)])               # exit
        self.assertEqual(self.tick([self.MOMMY, (355.0, 250.0, "Grunt", 0.0, 0.0)])[1], 3)   # 55 px: still shooting
        self.assertEqual(self.tick([self.MOMMY, (370.0, 250.0, "Grunt", 0.0, 0.0)])[1], 0)   # 70 px: save again

    def test_no_civilian_means_normal_killing(self):
        self.assertGreaterEqual(self.tick([self.FAR_GRUNT])[1], 1)
        self.assertFalse(self.b.save_active)

    def test_brains_and_progs_disable_it(self):
        for name in ("Brain", "Prog"):
            fr = self.tick([self.MOMMY, self.FAR_GRUNT, (500.0, 400.0, name, 0.0, 0.0)])[1]
            self.assertGreaterEqual(fr, 1, name)

    def test_hulk_near_the_civilian_ends_it(self):
        fr = self.tick([self.MOMMY, self.FAR_GRUNT, (200.0, 380.0, "Hulk", 0.0, 0.0)])[1]   # ~58 px from Mommy
        self.assertGreaterEqual(fr, 1)
        fr = self.tick([self.MOMMY, self.FAR_GRUNT, (500.0, 450.0, "Hulk", 0.0, 0.0)])[1]   # far from her
        self.assertEqual(fr, 0)

    def test_times_out_after_12_seconds_and_stays_out_until_reset(self):
        fires = [self.tick([self.MOMMY, self.FAR_GRUNT], dt=0.4)[1] for _ in range(40)]
        self.assertEqual(fires[0], 0)
        self.assertEqual(fires[29], 0)                    # 29 x 0.4 s = 11.6 s
        self.assertGreaterEqual(fires[32], 1)             # past 12 s: killing resumes
        self.assertTrue(self.b.save_locked)
        self.assertGreaterEqual(fires[-1], 1)
        self.b.reset()                                    # next wave
        self.assertEqual(self.tick([self.MOMMY, self.FAR_GRUNT])[1], 0)

    def test_long_gap_between_ticks_does_not_eat_the_budget(self):
        self.tick([self.MOMMY, self.FAR_GRUNT])
        self.tick([self.MOMMY, self.FAR_GRUNT], dt=60.0)  # paused game
        self.assertFalse(self.b.save_locked)

    def test_protect_stage_spares_the_farthest_grunt_but_shoots_the_rest(self):
        near, far = (420.0, 250.0, "Grunt", 0.0, 0.0), (300.0, 40.0, "Grunt", 0.0, 0.0)
        mv, fr = self.tick([self.MOMMY, near, far])
        self.assertEqual(fr, 3)                           # the near one is shot
        self.assertEqual(cp.FIRE_EXCLUDE, {(300.0, 40.0, "Grunt")})
        self.assertTrue(self.b.save_active)
        # the near one dies: only the spared grunt is left -> hold
        self.assertEqual(self.tick([self.MOMMY, far])[1], 0)

    def test_too_many_killables_means_no_protection(self):
        grunts = [(400.0 + 10 * i, 250.0, "Grunt", 0.0, 0.0) for i in range(5)]    # 5 > N+3
        fr = self.tick([self.MOMMY] + grunts)[1]
        self.assertGreaterEqual(fr, 1)
        self.assertEqual(cp.FIRE_EXCLUDE, frozenset())

    def test_protected_grunt_is_not_a_fire_alt_or_fireplan_or_fallback_target(self):
        key = (300.0, 190.0, "Grunt")
        cp.set_fire_exclude([key])
        sp = [P, (360.0, 250.0, "Grunt", 0.0, 0.0), (300.0, 190.0, "Grunt", 0.0, 0.0)]
        cp.set_fire_alt(True)
        self.assertEqual([cp.clearance_search(sp, 1, 3)[1] for _ in range(4)], [3, 3, 3, 3])
        brain_mod.FIRE_FALLBACK_REACH = 250.0
        self.assertEqual(self.b._lined_up_fire(300.0, 250.0, sp[2:], protected={key}), 0)
        self.assertEqual(self.b._lined_up_fire(300.0, 250.0, sp[2:]), 1)


if __name__ == "__main__":
    unittest.main()
