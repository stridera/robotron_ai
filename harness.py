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

from . import coords
from .visualize import VizOverlay, dir_name


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


def _render_vision(viz, perception, mv, fr, blind):
    """Draw the overlay for the hardware path (vision only)."""
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
    tick = 1.0 / hz
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
        t0 = time.time()

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
            time.sleep(tick)
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
                controller.neutral()
                neutral = True
            else:
                cur_mv, cur_fr = brain.decide(obs.player, obs.entities)
                controller.move_shoot(cur_mv, cur_fr)

        # ── Visualize (after acting, so it never delays actuation) ──
        if visualizer is not None and visualizer.enabled:
            _render_memory(visualizer, perception, backdrop, state,
                           cur_mv, cur_fr, deaths, neutral)

        dt = time.time() - t0
        if dt < tick:
            time.sleep(tick - dt)


# ── Hardware game loop (vision only, no memory) ─────────────────────────────
def play_vision_game(brain, perception, controller, *, hz: float = 15.0,
                     start_seq: bool = False, debug: bool = False,
                     visualizer=None):
    """Minimal loop for real hardware. Runs until interrupted (Ctrl+C). Plans and
    acts whenever the player is visible; goes neutral when it isn't. No game-state
    memory is available, so there is no death/wave/score tracking — the game is
    started manually (or with --start) and the bot simply keeps playing."""
    tick = 1.0 / hz
    if start_seq:
        print("[harness] blind start sequence (Start, then A x4)...")
        controller.press_start()
        time.sleep(1.5)
        for _ in range(4):
            controller.press_a()
            time.sleep(1.0)
    print(f"[harness] vision loop running at {hz:.0f} Hz - Ctrl+C to stop")
    blind = 0
    while True:
        t0 = time.time()
        obs = perception.perceive(None)
        cur_mv = cur_fr = 0
        if obs.player is None:
            blind += 1
            controller.neutral()
        else:
            blind = 0
            cur_mv, cur_fr = brain.decide(obs.player, obs.entities)
            controller.move_shoot(cur_mv, cur_fr)
            if debug:
                print(f"[vision] p=({obs.player[0]:.0f},{obs.player[1]:.0f}) "
                      f"n={len(obs.entities)} mv={cur_mv} fr={cur_fr}")
        if visualizer is not None and visualizer.enabled:
            _render_vision(visualizer, perception, cur_mv, cur_fr, blind)
        dt = time.time() - t0
        if dt < tick:
            time.sleep(tick - dt)
