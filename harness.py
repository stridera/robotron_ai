"""Harness — the run loops that tie perception -> brain -> controller together
and manage game lifecycle.

    play_memory_game   Xenia. Rich bookkeeping from guest memory: frame-sync,
                       wave-start blind window, death detection, game-over
                       detection. Works with EITHER memory or vision perception
                       (perception supplies the decision; memory the bookkeeping).
    play_vision_game   Real hardware. Minimal vision-only loop: plan+act when the
                       player is visible, neutral otherwise. No memory access.
    wait_for_game_start  Navigate the Xenia XBLA menus to gameplay.
"""
import time
from collections import deque

from . import coords
from .engine import clearance_planner as _cp
from .visualize import VizOverlay, dir_name


class TickClock:
    """Deadline-scheduled decision clock with measured-rate feedback
    (ported from the dev tree, 2026-07-28 — measured 15.0 Hz with 0 overruns
    in 3600 ticks vs the old open-loop tail sleep's silent drift).

    Two jobs:
      1. GUARANTEE the cadence: schedule against an absolute deadline, so a
         slow tick is followed by a short sleep instead of permanent debt.
         On an overrun, RESYNC rather than pay back — every kinematic
         constant assumes THIS step covers one tick of game time; a 107 ms
         tick followed by a 27 ms catch-up averages right and is wrong twice.
      2. ADAPT when the cadence can't be held (real-hardware path: HDMI
         capture + serial cost more than the emulator): feed the measured
         period into clearance_planner.set_tick_scale(), which rescales the
         per-step kinematics. A settled rolling MEDIAN drives this — an EMA
         chases the GPU-warmup transient and oscillates.
    """
    SPIN = 0.001            # burn the last ms in a spin (sleep granularity)
    ADAPT_DEADBAND = 0.08
    ADAPT_WINDOW = 90
    ADAPT_WARMUP = 60
    ADAPT_EVERY = 45
    WARN_EVERY = 10.0

    def __init__(self, hz: float = 15.0, adapt: bool = True):
        self.period = 1.0 / hz
        self.nominal = 1.0 / 15.0     # the planner's calibration cadence
        self.adapt = adapt
        self.next = None
        self.last = None
        self.n = 0
        self.n_over = 0
        self.periods = deque(maxlen=900)
        self._warned = 0.0
        self._applied = 1.0
        self._last_adapt = 0
        if adapt:
            _cp.set_tick_scale(1.0)   # fresh clock -> start from nominal

    def wait(self):
        """Call at the END of each tick body: sleeps to the deadline."""
        now = time.perf_counter()
        if self.next is None:
            self.last = now
            self.next = now + self.period
            return
        if now < self.next:
            rem = self.next - now
            if rem > self.SPIN:
                time.sleep(rem - self.SPIN)
            while time.perf_counter() < self.next:
                pass
            self.next += self.period
        else:
            self.n_over += 1
            behind = now - self.next                 # BEFORE resync (the old
            self.next = now + self.period            # order always printed -0)
            if time.time() - self._warned > self.WARN_EVERY:
                self._warned = time.time()
                print(f"[tick] OVERRUN {behind * 1e3:.0f} ms "
                      f"({self.n_over}/{self.n + 1} ticks over)", flush=True)
            # Standing advisory: if EVERY tick overruns, the requested rate is
            # simply not achievable on this machine (usually CPU inference).
            # The planner auto-rescales so play stays correct, but a matched
            # --hz removes the churn.
            if self.n_over == self.n + 1 and self.n_over == 150:
                ach = 1.0 / (sum(self.periods) / len(self.periods))
                print(f"[tick] NOTE: every tick overruns — this machine "
                      f"achieves ~{ach:.0f} Hz, not the requested "
                      f"{1.0 / self.period:.0f}. Play is auto-rescaled and "
                      f"correct; pass --hz {ach:.0f} to stop this churn, or "
                      f"speed up inference (GPU/torch-CUDA, --imgsz 640).",
                      flush=True)
        t = time.perf_counter()
        self.periods.append(t - self.last)
        self.last = t
        self.n += 1
        if (self.adapt and self.n >= self.ADAPT_WARMUP
                and self.n - self._last_adapt >= self.ADAPT_EVERY):
            self._last_adapt = self.n
            recent = sorted(list(self.periods)[-self.ADAPT_WINDOW:])
            k = recent[len(recent) // 2] / self.nominal
            if abs(k - self._applied) > self.ADAPT_DEADBAND:
                self._applied = _cp.set_tick_scale(k)
                print(f"[tick] sustained cadence {1.0 / (k * self.nominal):.1f} Hz "
                      f"— rescaling planner kinematics x{self._applied:.2f}",
                      flush=True)

    def stats(self):
        """Achieved cadence for the telemetry report."""
        if not self.periods:
            return {}
        s = sorted(self.periods)
        import statistics
        return {'hz': round(1.0 / statistics.mean(s), 2),
                'p90_ms': round(s[int(len(s) * 0.9)] * 1e3, 1),
                'overruns': self.n_over, 'ticks': self.n,
                'k_applied': round(self._applied, 3)}


# ── Overlay builders (screen-pixel space) ───────────────────────────────────
def _render_memory(viz, perception, backdrop, state, mv, fr, deaths, neutral):
    """Draw the overlay for the Xenia path. Uses the YOLO frame+boxes when the
    input is vision, otherwise a Xenia-window backdrop with boxes from RAM."""
    if getattr(perception, "collect_viz", False):
        frame = perception.last_frame
        boxes = perception.last_boxes or []
        ppx = perception.last_player_px
    else:
        frame = backdrop.read() if backdrop is not None else None
        boxes = [(*coords.game_to_pixel(e.gx, e.gy), e.w, e.h, e.label)
                 for e in state.entities]
        ppx = (None if (state.player_gx == 0 and state.player_gy == 0)
               else coords.game_to_pixel(state.player_gx, state.player_gy))
    lives = state.lives if state.lives < 100 else '-'
    action = "NEUTRAL" if neutral else f"mv {dir_name(mv)}  fire {dir_name(fr)}"
    hud = [f"W{state.wave}   S{state.score}   L{lives}",
           f"deaths {deaths}    {action}"]
    viz.render(frame, VizOverlay(entities=boxes, player=ppx,
                                 move_dir=mv, fire_dir=fr, hud=hud))


def _render_vision(viz, perception, mv, fr, blind, plain=False):
    """Draw the overlay for the hardware path (vision only). plain=True
    shows the raw feed without boxes/arrows (--visualize-plain)."""
    if plain:
        viz.render(perception.last_frame, VizOverlay(entities=[], player=None,
                                                     move_dir=0, fire_dir=0,
                                                     hud=[]))
        return
    boxes = perception.last_boxes or []
    hud = [f"mv {dir_name(mv)}   fire {dir_name(fr)}",
           f"entities {len(boxes)}",
           (f"BLIND {blind}" if blind else "tracking")]
    viz.render(perception.last_frame,
               VizOverlay(entities=boxes, player=perception.last_player_px,
                          move_dir=mv, fire_dir=fr, hud=hud))


# ── Xenia menu navigation ───────────────────────────────────────────────────
def _focus_xenia_window() -> None:
    """Best-effort: bring the Xenia window to the foreground so it receives
    XInput. No-op if win32gui isn't available."""
    try:
        import win32gui
        hwnd = win32gui.FindWindow(None, None)  # placeholder; enumerate instead

        def _cb(h, acc):
            if win32gui.IsWindowVisible(h) and "xenia" in win32gui.GetWindowText(h).lower():
                acc.append(h)
        found = []
        win32gui.EnumWindows(_cb, found)
        if found:
            win32gui.SetForegroundWindow(found[0])
    except Exception:
        pass


def _olc_advancing(gsr, wait: float = 0.15) -> bool:
    """True if the 60Hz outer-loop counter is advancing (game actually running)."""
    try:
        s1 = gsr.read(wait_new_frame=False)
        if s1 is None or s1.wave == 0:
            return False
        olc1 = s1.outer_loop_count
        time.sleep(wait)
        s2 = gsr.read(wait_new_frame=False)
        return s2 is not None and s2.outer_loop_count > olc1
    except Exception:
        return False


def wait_for_game_start(controller, gsr, attempts: int = 20) -> None:
    """Exit the attract/game-over screen and press A until gameplay is confirmed
    (wave > 0 and the outer-loop counter advancing)."""
    print("[harness] navigating menus...")
    _focus_xenia_window()
    time.sleep(0.5)
    controller.press_start()          # exit attract / game-over
    time.sleep(1.5)
    for _ in range(attempts):
        s = gsr.read(wait_new_frame=False)
        if s is not None and s.wave > 0 and _olc_advancing(gsr):
            print(f"[harness] gameplay confirmed (wave {s.wave})")
            return
        controller.press_a()
        time.sleep(1.0)
    print("[harness] WARNING: could not confirm gameplay - proceeding anyway")


# ── Xenia game loop (memory bookkeeping) ────────────────────────────────────
def play_memory_game(brain, perception, controller, gsr, *,
                     frame_sync: bool = True, hz: float = 15.0,
                     visualizer=None, backdrop=None):
    """Play one game with full memory-based bookkeeping. Returns
    (max_wave, max_score, deaths). `perception` supplies the decision input;
    it may read the same GameState (memory) or capture the screen (vision)."""
    clock = TickClock(hz=hz)
    prev_wave = 0
    prev_lives = 0xFFFFFFFF
    prev_player_pos = (0, 0)
    prev_player_on_field = False
    was_ever_in_game = False
    deaths = 0
    frozen_frames = 0
    ffff_ticks = 0
    suppress_death_frames = 0
    wave_blind_until = 0.0
    last_wave_change = 0.0
    wave_reposition_guard_until = 0.0
    wave_entities_seen = False
    last_valid_entities = []
    max_wave = 0
    max_score = 0

    while True:
        if frame_sync:
            # Phase-lock to the 60Hz frame counter: spin until it ticks over, then
            # read immediately (clean post-update window, deterministic ~1-frame
            # staleness). Bounded spin (~72ms) falls back to a plain read if the
            # counter stalls (paused/menu).
            base = gsr.peek_frame_counter()
            spins = 0
            while base is not None and spins < 120:
                c = gsr.peek_frame_counter()
                if c is None or c != base:
                    break
                spins += 1
                time.sleep(0.0006)
            state = gsr.read(wait_new_frame=False)
        else:
            state = gsr.read(wait_new_frame=False)

        if state is None:
            clock.wait()
            continue

        max_wave = max(max_wave, state.wave)
        max_score = max(max_score, state.score)
        if state.wave > 0:
            was_ever_in_game = True

        # ── Wave-start blind window (JIT accumulator warmup) ──
        # Patches state.entities only; vision perception ignores it harmlessly.
        if time.time() < wave_blind_until:
            if last_valid_entities:
                state.entities = last_valid_entities
        elif not wave_entities_seen:
            if len(state.entities) >= 8:
                wave_entities_seen = True
                last_valid_entities = state.entities
            elif last_valid_entities:
                state.entities = last_valid_entities
        elif len(state.entities) >= 4:
            last_valid_entities = state.entities

        # ── Game-over: lives -> 0xFFFFFFFF persisting ~3 s ──
        # lives == 0 means LAST LIFE, and the counter reads -1 transiently during
        # death freezes, so only quit when the -1 read PERSISTS.
        if (was_ever_in_game and state.lives == 0xFFFFFFFF and prev_lives < 100):
            ffff_ticks += 1
            if ffff_ticks > 45:                      # 3 s at 15 Hz
                print(f"\n[harness] GAME OVER (lives)  W{prev_wave} S{max_score} D={deaths}")
                controller.neutral()
                return max_wave, max_score, deaths
        else:
            ffff_ticks = 0

        # ── Game-over: frozen 7 s outside transitions ──
        cur_pos = (state.player_gx, state.player_gy)
        if (cur_pos == prev_player_pos and cur_pos != (0, 0)
                and suppress_death_frames == 0
                and time.time() >= last_wave_change + 6.0):
            frozen_frames += 1
            if frozen_frames > 105:                  # 7 s at 15 Hz
                print(f"\n[harness] GAME OVER (frozen)  W{prev_wave} S{max_score} D={deaths}")
                controller.neutral()
                return max_wave, max_score, deaths
        else:
            frozen_frames = 0

        # ── Wave change ──
        if state.wave != prev_wave:
            suppress_death_frames = 10
            wave_blind_until = time.time() + 0.35
            last_wave_change = time.time()
            wave_reposition_guard_until = time.time() + 1.4
            last_valid_entities = []
            wave_entities_seen = False
            frozen_frames = 0
            brain.reset()
            perception.reset()
            print(f"[harness] === WAVE {state.wave} ===  S{state.score}")
            prev_wave = state.wave

        # ── Death detection ──
        player_on_field = cur_pos != (0, 0)
        died = False
        if suppress_death_frames > 0:
            suppress_death_frames -= 1
        else:
            if not player_on_field and prev_player_on_field:
                died = True                          # pos -> (0,0): real death
            elif (was_ever_in_game and prev_player_pos != (0, 0) and player_on_field
                  and time.time() >= wave_reposition_guard_until):
                dx = state.player_gx - prev_player_pos[0]
                dy = state.player_gy - prev_player_pos[1]
                if dx * dx + dy * dy > 400:          # teleport = respawn/reposition
                    died = True
        if died:
            deaths += 1
            suppress_death_frames = 5
            brain.reset()
            perception.reset()
            print(f"[harness]  ** DIED #{deaths} **  W{state.wave} S{state.score}")
        prev_player_pos = cur_pos
        prev_player_on_field = player_on_field
        if suppress_death_frames == 0 and state.lives < 100:
            prev_lives = state.lives

        # ── Decide & act ──
        cur_mv = cur_fr = 0
        neutral = suppress_death_frames > 0 or not player_on_field
        if neutral:
            controller.neutral()
        else:
            obs = perception.perceive(state)
            if obs.player is None:                   # blind this tick
                # Keep tracking alive on the enemies we DID see, or every
                # track resumes a tick stale with a halved velocity.
                if obs.entities:
                    brain.blind_tick(obs.entities)
                controller.neutral()
                neutral = True
            else:
                cur_mv, cur_fr = brain.decide(obs.player, obs.entities)
                controller.move_shoot(cur_mv, cur_fr)

        # ── Visualize (after acting, so it never delays actuation) ──
        if visualizer is not None and visualizer.enabled:
            _render_memory(visualizer, perception, backdrop, state,
                           cur_mv, cur_fr, deaths, neutral)

        clock.wait()


# ── Hardware menu navigation (vision-guarded) ───────────────────────────────
def _sense_in_game(perception, hud_reader, seconds=3.0, hz=5.0):
    """True if the game is demonstrably on: HUD readable OR the DETECTOR sees
    the player. The HUD flashes (a single blank frame means nothing) and on
    some rigs its reads are patchy, but the player detector runs at 0.88-0.92
    visibility in-game — the OR of the two signals is what makes "don't touch
    a live game" trustworthy on real hardware."""
    t_end = time.time() + seconds
    while time.time() < t_end:
        obs = perception.perceive(None)
        if obs is not None and obs.player is not None:
            return True
        frame = getattr(perception, "last_frame", None)
        if frame is not None:
            r = hud_reader.read(frame)
            if r['score'] is not None or r['wave'] is not None:
                return True
        time.sleep(1.0 / hz)
    return False


def ensure_game_running(perception, hud_reader, controller,
                        attempts: int = 8, use_start: bool = False) -> bool:
    """Get a game running by pressing A — no blocking pre-sense.

    Why blind-A is CORRECT here (two live lessons, one per direction):
      * Hardware round 1: pressing START on the real console's shell backs
        out of menus / lands in settings — so Start and B/Back are never
        sent (`use_start` re-enables Start for rigs that need it).
      * A "don't press while a game is visible" guard is UNSATISFIABLE and
        unnecessary: Robotron's attract mode plays a real gameplay demo with
        a real HUD and player sprite, indistinguishable per-frame from our
        own game — the guard locked onto the attract screen forever (seen
        live). And with an A-only policy there is nothing to guard: A does
        NOTHING during gameplay (fire is the right stick), resumes from
        pause, advances attract, and is 'One Player Start' on the chooser.
        There is no screen on the A-path where pressing A hurts.

    Sensing (HUD readable / player detected) is used only to STOP pressing
    and report; a false confirmation from the attract demo self-corrects,
    because the demo ends, the bookkeeper times out, and --loop calls this
    again — retry-until-real converges where refuse-to-press stuck."""
    if use_start:
        controller.press_start()
        time.sleep(2.0)
    print("[harness] pressing A until a game is on (A is a no-op in-game)")
    for i in range(attempts):
        controller.press_a()
        time.sleep(1.0)
        if _sense_in_game(perception, hud_reader, seconds=2.0):
            print("[harness] gameplay (or attract demo) visible — playing; "
                  "if this was the demo, the game-over cycle retries")
            return True
    print("[harness] WARNING: nothing game-like visible after "
          f"{attempts} A presses — check the TV/capture; will keep playing "
          "if a game appears")
    return False


# ── Hardware game loop (vision only, no memory) ─────────────────────────────
def play_vision_game(brain, perception, controller, *, hz: float = 15.0,
                     start_seq: bool = False, debug: bool = False,
                     visualizer=None, bookkeeper=None, hud_reader=None,
                     loop_games: bool = False, telemetry=None,
                     menu_start: bool = False, visualize_plain: bool = False):
    """Minimal loop for real hardware. Runs until interrupted (Ctrl+C). Plans and
    acts whenever the player is visible; goes neutral when it isn't.

    Game state comes from HUD OCR when a font is available (hud_reader +
    bookkeeper): score/wave/lives are read off the video feed each tick, giving
    wave lines in the console, death detection via the lives icons, and a wave
    log robotron/ab_yolo.py can analyse — the same bookkeeping the emulator
    gets from guest RAM, minus nothing the tuning loop needs."""
    clock = TickClock(hz=hz)
    if hud_reader is not None:
        # Vision-guarded navigation: senses before pressing anything. Runs
        # even without --start — it's a no-op when a game is already on.
        ensure_game_running(perception, hud_reader, controller,
                            use_start=menu_start)
    elif start_seq:
        # No HUD font -> the old blind sequence, only on explicit request.
        print("[harness] BLIND start sequence (no HUD font to sense with) — "
              "Start, then A x4. Don't use this while a game is running: "
              "Start pauses and A presses navigate the pause menu.")
        controller.press_start()
        time.sleep(1.5)
        for _ in range(4):
            controller.press_a()
            time.sleep(1.0)
    print(f"[harness] vision loop running at {hz:.0f} Hz - Ctrl+C to stop")
    blind = 0
    hud_every = max(1, int(hz / 5))     # OCR ~5x/s is plenty for bookkeeping
    n = 0
    try:
        while True:
            n += 1
            obs = perception.perceive(None)
            frame = getattr(perception, "last_frame", None)
            if telemetry is not None:
                telemetry.frame(frame)
            if (hud_reader is not None and bookkeeper is not None
                    and n % hud_every == 0 and frame is not None):
                r = hud_reader.read(frame)
                bookkeeper.feed(r, player_visible=(obs.player is not None))
                if telemetry is not None:
                    telemetry.hud(r, frame)
                # Deaths need no input (the game respawns automatically; the
                # bookkeeper counts them from the lives icons). GAME OVER is
                # the only state needing action: restart via the same vision-
                # guarded navigator, which presses nothing until the HUD has
                # been gone for a full sensing window.
                if bookkeeper.game_over_fired and loop_games:
                    controller.neutral()
                    brain.reset()
                    perception.reset()
                    ensure_game_running(perception, hud_reader, controller,
                                        use_start=menu_start)
            cur_mv = cur_fr = 0
            if obs.player is None:
                blind += 1
                if obs.entities:
                    brain.blind_tick(obs.entities)   # keep tracks ageing
                controller.neutral()
            else:
                blind = 0
                cur_mv, cur_fr = brain.decide(obs.player, obs.entities)
                controller.move_shoot(cur_mv, cur_fr)
                if debug:
                    print(f"[vision] p=({obs.player[0]:.0f},{obs.player[1]:.0f}) "
                          f"n={len(obs.entities)} mv={cur_mv} fr={cur_fr}")
            if telemetry is not None:
                telemetry.tick(cur_mv, obs.player,
                               getattr(perception, "last_boxes", None), frame)
            if visualizer is not None and visualizer.enabled:
                _render_vision(visualizer, perception, cur_mv, cur_fr, blind,
                               plain=visualize_plain)
            clock.wait()
    finally:
        # Ctrl+C included: the friend's report must survive any exit.
        if telemetry is not None:
            telemetry.finalize(tick_stats=clock.stats())
