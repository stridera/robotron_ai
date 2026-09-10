# What we already tried: the Robotron bot idea ledger

**For:** anyone with an idea for making the bot play deeper.
**Covers:** March to September 2026. **Current as of:** 2026-09-10.
**Engineering version:** [STATE_OF_PLAY.md](STATE_OF_PLAY.md).

This is every change we've tried on the bot since March 2026, what happened when
we measured it, and why we kept or dropped it. It exists so good ideas get tried
and already-answered ones don't get re-argued.

> [!TIP]
> Start with [§1](#1-before-you-suggest-something). It lists the ideas people
> suggest most often, with the answer for each. In the full ledger
> ([§4](#4-the-full-ledger)), **click any row to expand it** for the numbers and
> the reasoning. If your idea isn't in here, it's new and we want to hear it.
> [§6](#6-whats-still-open) lists where new ideas have the most room.

## Contents

1. [Before you suggest something](#1-before-you-suggest-something)
2. [How we got here](#2-how-we-got-here) (the history in one table)
3. [How we decide whether an idea worked](#3-how-we-decide-whether-an-idea-worked)
4. [The full ledger](#4-the-full-ledger) (every attempt, click to expand)
5. [Four things we measured that constrain every new idea](#5-four-things-we-measured-that-constrain-every-new-idea)
6. [What's still open](#6-whats-still-open)
7. [How to propose an idea so we can test it fast](#7-how-to-propose-an-idea-so-we-can-test-it-fast)

---

## 1. Before you suggest something

These are the suggestions that come up most often. We've built, run and
measured every one of them, most of them more than once.

| The idea | What happened | |
|---|---|---|
| "Circle the field / keep moving in a loop" | ❌ Tried **5 separate times** since March. All worse or no effect. | [details](#circle-the-field-kiting) |
| "Shoot the spawners first" | ❌ Tried **6 times**. It always cost score and never cut deaths. | [details](#shoot-spawners-first) |
| "Just shoot constantly" | 🅿️ Slightly fewer deaths, slightly less score. A wash. | [details](#always-be-shooting) |
| "Stay away from the walls" | ❌ Worse. Walls are where the bot dies, not why. | [details](#stay-away-from-the-walls) |
| "Run toward the most open space" | ❌ One of the clearest losses we've measured. | [details](#head-for-the-most-open-space) |
| "Dodge earlier / give it more room" | ❌ A little extra room (15%) helps and ships. Anything more loses. | [details](#bigger-safety-margins) |
| "Don't let it get cornered" | ❌ Tried 3 ways. Worse early, no effect late. | [details](#keep-an-escape-route-open) |
| "Handle hulks better" | ✅ One fix ships (steer around them, +1.26 waves). Two others lost. | [details](#hulk-handling) |
| "Rescue more civilians for more points" | ❌ Not possible. A bot with *perfect* information rescues the same number. | [details](#rescue-more-civilians) |
| "The vision must be missing things" | ⚪ Checked against the game's memory. It isn't. | [details](#is-the-vision-missing-things) |
| "Make it think faster" | ❌ 30 decisions/second was a disaster. *Fresher* frames were a big win. | [details](#think-faster-30-decisions-per-second) |
| "Make it plan further ahead" | ❌ Every longer look-ahead we tried lost. | [details](#look-further-ahead) |
| "Use AI / machine learning instead" | ❌ About 20 variants in June. None beat the hand-written rules. | [details](#learned-policies-rl-and-imitation) |
| "Let evolution tune it" | ✅ Built the W100 champion on perfect input. ❌ On video, noise swamps it. | [details](#evolve-the-constants) |
| "Practice the late waves by starting at wave 24" | ❌ Not possible. The memory address is only a display copy. | [details](#start-deep-to-practice-late-waves) |

---

## 2. How we got here

The bot has been rebuilt several times. Most "new" ideas were first tried in an
earlier version, so it helps to know the eras.

| When | What we were building | Best result | How it ended |
|---|---|---|---|
| Mar 2026 | Hand-written bots on the Xbox emulator | wave 7 | Replaced by the MAME-developed rule bot |
| Jun 2026 | Learned policies (reinforcement / imitation learning) on MAME | mean ≈ 9.4 | Never beat the hand-written rules. Dropped. |
| Jun 2026 | Rule-based bot + evolved constants + a look-ahead dodge planner, on MAME | mean 12.6 → 15.2 | Became the core of today's bot |
| Jul 1–3 | Same bot on MAME: fixed a label bug, added rescue-seeking, re-evolved, added endgame hunting | **mean 174; 76% of games reach W100** | Proved the planner can reach W100 *with perfect, instant information* |
| Jul 2026 | Same bot on the Xbox game, reading the game's memory | **W158** | Showed delay was the gap. Memory reading isn't possible on a real console. |
| Jul 2026 | Same bot on **video only** (the version Eric runs) | mean ≈ 13.5, best W26 | Detection solved. Stuck at a plateau. |
| Late Jul–Aug | Video bot rework + hardware rounds 1–12 with Eric | first life-positive video bot; scoreboard reading correct on Eric's rig | |
| Sep 2026 | Delay work: fresher frames and aiming ahead | **mean ≈ 31, records W58 / W60** | The ceiling for this design at this delay ([§5](#5-four-things-we-measured-that-constrain-every-new-idea)) |

**There are three versions of the same bot, and the difference matters:**

- **The video bot** is the one Eric runs. It sees only the screen, like a person.
- **The memory-reading bot** has the same brain, but reads every position straight
  out of the emulator's memory: perfect, instant information. That's impossible on
  a real console, so we use it as a reference. When this doc says "perfect
  information" or "exact-state", this is the bot it means.
- **The MAME bot** has the same brain again, running on the original arcade game
  in an emulator, where we can run hundreds of games an hour.

---

## 3. How we decide whether an idea worked

**The number we track is `NET`: lives earned minus lives lost, per wave.**
You get a free life every 25,000 points, so:

```
NET  =  (score per wave / 25,000)  −  (deaths per wave)
```

Positive NET means the bot banks lives faster than it loses them and keeps going
deeper. Negative means it's counting down to game over. The shipped video bot is
about **+0.05 in waves 5–25** and about **−0.13 from wave 20 on**, which is why
most games end between waves 30 and 40.

This catches two things "it felt better" doesn't:

- **An idea that cuts deaths but also cuts score usually breaks even or loses.**
  Many "safer" ideas below did exactly that: the bot survives by playing
  cautiously, and cautious play doesn't earn the lives it needs.
- **Robotron is extremely swingy.** A change can look like a clear +10% over 20
  games and turn out to be worth nothing.

> [!IMPORTANT]
> **A small improvement over 144 games is not a result.** Confirm it at 576
> before believing it. We learned this in September when a circling variant
> measured **+0.036** at 144 games and **−0.011** at 576. An earlier version of the
> same lesson: in June, an idea looked like **+1.05 waves at 40 games** and was
> **+0.13 (a dead heat) at 100**.

**Where we run tests**

| Test bed | What it is | Speed | Good for |
|---|---|---|---|
| **Xenia** | The real Xbox game on a PC emulator, played through the same camera-and-detector pipeline as the console | ~1 game / 10 min | The truth. The only place where late waves behave like the real game. |
| **MAME farm** | 16 copies of arcade Robotron at 250× speed, with a deliberate handicap that makes it match the video bot's numbers | 144 games / 16 min | Cheap screening in waves 5–25. **Its late waves don't match the Xbox's.** |
| **Exact-state harness** | The video bot on Xenia, fed the game's memory instead of the camera | Xenia speed | Testing a *decision* idea with all camera error removed. If an idea can't win here, it won't win on video. |

---

## 4. The full ledger

**Verdict key:**
✅ **Shipped** (running today) ·
❌ **Rejected** (measurably worse) ·
⚪ **No effect** (measured, indistinguishable from nothing) ·
🅿️ **Parked** (real but too small to be worth it)

**Click any row to expand it.** Inside each one, a *"likely why"* is our reading
of a result, and a plain *"why"* is something we measured directly.

### The overall approach

<details>
<summary><a id="hand-written-bots"></a>❌ <b>Hand-written bots (force fields, goal planners)</b>: best wave 7, March 2026</summary>

Three bots on the Xbox emulator, all reading the game's memory:

- **brain2, force fields:** every enemy pushes the bot away, civilians pull it
  in, walls push it off, and it's pulled toward the center. It also had a
  circling mode. Result: average wave 4.7, best wave 7, over 30 games.
  Documented failures: opposing forces cancel so the bot jitters in place, and
  it got stuck bouncing between a wall and a civilian.
- **brain3, goal-directed:** locks one target at a time, with **spawners ranked
  first**, and blends a **circling orbit into every move** ("orbit, don't
  flee"). Best wave 7.
- **brain4, grid blend:** best wave 5.

**Why they were replaced:** the rule-based bot developed on MAME reached wave 19
to 22 on the same game on its first day.

**Worth knowing:** two of the most common suggestions today, circling and killing
spawners first, were brain3's founding design rules.

</details>

<details>
<summary><a id="early-expert-fsm"></a>❌ <b>Early "expert" rule bot on our first simulator</b>: superseded when we moved to MAME</summary>

Before June 2026 the bot was developed on a custom simulator. Version 1 used
human-expert tactics: circle the edges, spawners first, dodge projectiles,
collect family when safe, kite. It reached about level 1. Six rounds of
death-analysis fixes followed (spawner priority boost, shooter priority, wall
avoidance when bullets are near, an "escape corridor" mode that flees before the
bot is boxed in). It reached level 18 once, averaging 6.7.

In June 2026 we moved to MAME, which runs the real arcade code, because the
simulator didn't match the real game closely enough. Its numbers don't carry
over. Each of its ideas was re-tested later on MAME or video. See the entries on
[circling](#circle-the-field-kiting), [spawners](#shoot-spawners-first),
[walls](#stay-away-from-the-walls) and
[escape routes](#keep-an-escape-route-open).

</details>

<details>
<summary><a id="learned-policies-rl-and-imitation"></a>❌ <b>Learned policies (reinforcement and imitation learning)</b>: ~20 variants, best ≈ 9.4 vs the rule bot's 12.6</summary>

In June 2026 we spent weeks trying to *learn* a player on MAME instead of writing
rules. Mean or median wave reached, each started from wave 1:

| Approach | Result |
|---|---|
| Reinforcement learning (RL) from scratch | median 3 |
| RL + reward shaping (aim, evasion, hulk-aim bonuses) | median 3, mean 3.2 |
| Image-grid inputs (24×36 and 48×72) | median 3 |
| Curriculum (start training in deep waves) | median 3 |
| Memory (LSTM) network | median 3 |
| Copy the rule bot (behavior cloning) | median 2 |
| Copy with corrections (DAgger), scaled up | median 3 → 8 |
| Attention network | median 1–2 |
| Copy the rule bot, then RL on top ("anchored RL") | **mean 9.41** (best, 100 games) |
| RL that may override the rule bot ("residual"), 3 versions | 5.3 / 7.3 / 9.35 |
| Copy the later W100 champion | 6.1–6.5 |
| **The rule bot itself** (same time, same game) | **12.6** |

**Why it failed (measured):** a network copies the rule bot's choices only about
80% of the time. In Robotron the other 20% are fatal. Better teachers made no
difference: a 12.7-wave teacher and a 14.3-wave teacher both produced about a
9.4-wave student. Copying the W100 champion did *worse*, because its behavior is
harder to imitate.

**We'd reopen it for** a fundamentally different setup, not another variant of
these. See [§6](#6-whats-still-open).

</details>

<details>
<summary><a id="evolved-rule-bot"></a>✅ <b>Rule-based bot with evolved constants</b>: the core of today's bot</summary>

A hand-written rule set (how far to run from each enemy type, what to shoot
first, when to go for a rescue) with about 20–25 numeric constants. The constants
were found by evolution: try many variations, keep the best. See
[evolve the constants](#evolve-the-constants) for how that went.

On MAME this bot reached a mean of 12.6 in June, and with the planner and fixes
below, a mean of 174 by July 3. It's the brain in every version today.

</details>

<details>
<summary><a id="search-with-save-states"></a>❌ <b>Look-ahead by replaying the emulator (save / try / restore)</b>: not possible on MAME</summary>

**The idea.** Before each move, save the game, try each of the 8 directions a few
steps ahead, restore, and pick the best.

**What happened.** Play collapsed from wave 13 to wave 4, **even with the choice
switched off**. So the damage came from the saving and restoring itself.

**Why (measured).** MAME's save-states aren't exact for this game. Restore and
replay the same inputs, and the game drifts apart within 4 steps. Every trial run
corrupted the real game. An earlier short look-ahead version also played at wave
3–4, because over a one-second horizon every move looks equally survivable, so it
just chased points.

</details>

<details>
<summary><a id="learned-danger-model"></a>⚪ <b>Learned danger model + one-step prediction</b>: tied with the rule bot</summary>

We trained a network to predict "how soon will I die from here" (correlation
0.956 with the truth). Then we simulated each of the 8 moves one step ahead in
Python, with no emulator replay, and took the safest when the rule bot's choice
looked dangerous.

**Result, 100 paired games:** 12.32 vs 12.19 for the rule bot, 44 wins vs 42
losses. A tie. It had looked like **+1.05 waves at 40 games**; that was luck in
which games were sampled.

It led directly to the next entry, which did win.

</details>

<details>
<summary><a id="clearance-planner"></a>✅ <b>Minimal-deviation dodge planner ("clearance search")</b>: +2.57 waves, the planner we ship</summary>

**What it does.** Every decision, it projects 6 steps ahead in each of 8
directions, with chasing enemies re-aiming at where the player will be. If the
rule bot's chosen direction ends up too close to something, it **switches to the
safe direction closest to what the rule bot wanted**. Otherwise it leaves the rule
bot alone.

**Result (June 30, MAME, 100 games):** 15.21 vs 12.64, winning 66% of paired
games. It was the first method to beat the hand-written rules. The danger
threshold turned out not to matter much (14, 18 and 24 all won by 2.6–3.1).

**The key detail:** an aggressive version that always picks the *most open*
direction **lost 2.71 waves**. The planner wins because it changes as little as
possible. It keeps the rule bot's kills and rescues and only steps in to avoid a
predicted death. This is also the measured answer to
["run toward open space"](#head-for-the-most-open-space).

</details>

<details>
<summary><a id="look-further-ahead"></a>❌ <b>Look further ahead (longer planning horizon)</b>: every length tried was worse than 6 steps</summary>

| Test | Result |
|---|---|
| MAME, June: 8 steps / 10 steps vs 6 steps | +1.27 / +1.67 over the rule bot, vs +2.57 for 6 steps |
| MAME, July (with exact enemy physics): 10 / 14 steps | **−4.7 / −5.7 waves** |
| Video, July: 8 steps | harmful: score −1,280/wave, worst early-wave life drain measured |
| Farm, Sept: 4 / 8 steps | flat |

**Likely why.** On MAME, longer horizons make the planner step in more often, and
every extra intervention costs kills and rescues. On video, speed estimates are
slightly noisy, and projecting them 8 steps ahead produces wrong predictions that
the planner then dodges. **Rule since July: never raise the horizon on video.**

</details>

<details>
<summary><a id="exact-enemy-physics"></a>⚪ <b>Exact enemy physics (from the game's disassembly) in the planner</b>: no gain, kept because it's correct</summary>

We rebuilt the planner's model of each enemy from the game's own code: tank
shells bounce, cruise missiles home, brains chase humans rather than the player,
and so on.

**Result:** +0.16 waves (range −1.9 to +2.3) over 97 paired games. A tie. It stays
on because it's the true behavior and costs nothing.

**Found alongside it:** a bug in how enemy types were labeled. Fixing it raised
the same bot from a mean of **15.2 to 22.7 waves**, one of the largest single
jumps in the project.

</details>

### Movement, dodging and positioning

<details>
<summary><a id="circle-the-field-kiting"></a>❌ <b>Circle the field (kiting)</b>: 5 separate attempts since March, all worse or no effect</summary>

**The idea.** Good human players keep moving in a loop, pulling enemies into a
line behind them.

| When | Version | Result |
|---|---|---|
| Mar | brain2 circling mode; brain3 blended an orbit into every move | best wave 7; replaced ([details](#hand-written-bots)) |
| Early sim | "Edge circling" in the first expert bot | level ≈ 1 ([details](#early-expert-fsm)) |
| Jul 4, MAME | Tangential orbit around mobs, with a keep-out spiral and wall flip, tested at three delay levels | **−0.9 / −1.9 / −5.1 waves**; in deep waves, deaths/wave 1.06 vs 1.00 and games surviving to the cap 40% vs 61% |
| Sep 5, farm | Kite 1: circle the arena when idle | NET **−0.035**: same deaths, less score |
| Sep 5, farm | Kite 2: circle by default, planner dodges | 144 games: **+0.036** → 576 games: **−0.011** (range −0.031 to +0.010). Noise. |
| Sep 5, video | Kite 2 on Xenia (default, then tuned) | default version aborted (worse); tuned: deaths 1.112 vs 1.142 (p=0.60), NET +0.014 vs −0.002. No effect. |
| Sep 5, farm | Kite 3: orbit the middle of the enemy pack | NET **−0.074** |

**Why we rejected it.** Circling costs *score*: kite 1 died just as often and
simply earned less. In deep waves on MAME, orbiting *raised* the death rate. The
bot's existing flee + [hulk steering](#hulk-handling) + planner already handles
mobs better than circling does.

**Note:** the video record of W55 came from a kite-arm game. One game proves
nothing; the full test showed no effect.

**We'd reopen it for** a variant that doesn't cost score, e.g. circling *through*
civilians instead of around the edge.

</details>

<details>
<summary><a id="stay-away-from-the-walls"></a>❌ <b>Stay away from the walls</b>: worse; walls are where the bot dies, not why</summary>

**The idea.** A very convincing one: **56% of video deaths happen within 50 px of
a wall**, and 35% happen with 2 or fewer open directions.

**What we tried:**
- Wall repulsion in the March force-field bot (replaced).
- Wall avoidance when bullets are near, on the early simulator (mixed).
- **Edge deflection** (turn along the wall instead of into it): MAME June, −0.40
  waves over 100 paired games; farm September, −0.015 (no effect). See
  [edge deflection](#edge-deflection).
- **Wall repulsion in the planner** (September): strongly negative. **Caveat:**
  that screen ran on a farm build later found to have rescue-seeking accidentally
  switched off, and it was never re-run after the fix. This one is cheap to
  repeat (see [§6](#6-whats-still-open)).
- Indirect evidence: two September changes that happened to push the bot off the
  walls ([launch-lane](#dodge-the-shot-before-its-fired) and
  [spark slide](#sparks-sliding-along-walls)) made it worse on the exact-state
  harness. The analysis: it "pushes the bot off the walls into the pack."

**Why the statistic misleads.** Moving away from the walls moves the bot toward
the middle, where the enemies are. The June analysis of edge deaths put it this
way: "the spark-edge clustering was correlation, not causation."

**Also measured:** late-wave deaths look the *same* as early ones (same wall
distance, same share boxed in, same killers). There's no special late-game
failure. The bot makes the same mistakes, just more often.

</details>

<details>
<summary><a id="head-for-the-most-open-space"></a>❌ <b>Head for the most open space</b>: −2.71 waves on MAME</summary>

**The idea.** Instead of any safe move, always run to the biggest open area.

**What happened.** When the planner was first built (June 30), the version that
always chose the *most open* direction **lost 2.71 waves**, while the version that
changes course as little as possible won 2.57 ([details](#clearance-planner)). A
September farm screen of the same idea was also negative (with the same rescue
caveat as [wall repulsion](#stay-away-from-the-walls)).

**Likely why.** The most open part of the arena usually has nothing worth going
to. The bot spends the wave in empty space, kills and rescues less, and runs short
of lives. Safety works best as a limit on the bot's choices, not its goal.

</details>

<details>
<summary><a id="bigger-safety-margins"></a>❌ <b>Dodge earlier / give it more room</b>: 15% more room helps on video and ships; anything more loses</summary>

| Test | Result |
|---|---|
| Video, July: planner margins 1.15× | mean 14.4 vs 13.6, fewer early busts → **shipped** (margins 21/12 on video) |
| Video, July: planner margins 1.3× | mean 12.75: worse |
| Video, July–Aug: rule-bot buffer 1.15× | weakly positive at first (13.71 vs 13.31); didn't reproduce in August. Not in production. |
| Video, July–Aug: rule-bot buffer 1.3× | mean 12.60, and max wave −3.4 in a second test: worse |
| Video, July: dodge projectiles 17% earlier | mean 10.6 vs 13.5; **deaths unchanged**. Pure timidity. |
| Video, July: dodge projectiles 25% *later* | fewer deaths, less score, no net gain |
| Farm, Sept: planner margin 14 | NET **−0.099** (range −0.139 to −0.060) |
| MAME, June: flee quarks twice as far | tie (fewer early deaths, shallower deep games) |

**Likely why.** Robotron gets crowded. A margin that's comfortable in an empty
arena can't be met in wave 25, so the planner rejects most directions. More room
also keeps the bot from closing on grunts and civilians, so it earns less.
"Dodge earlier" failed in a telling way: deaths didn't drop at all, because the
fatal shots are fired from point-blank range, where no amount of early dodging
helps.

**Across 6 July–August sweeps, every blanket-caution change lost, in both
directions.** The wins came from removing errors and adding abilities.

</details>

<details>
<summary><a id="threat-field-steering"></a>❌ <b>Threat-field steering (add up a push from every enemy)</b>: lost 3 times</summary>

Classic "potential field" navigation: each enemy pushes the bot away, and it moves
along the combined push.

| Test | Result |
|---|---|
| March: force-field bot (brain2) | best wave 7; replaced |
| MAME, June: applied to every flee | **−1.20 waves** (40% win rate) |
| MAME, June: only when 2–3 threats form a pincer | **−2.65 waves** (26% win rate) |
| Farm, Sept | NET **−0.043**, statistically significant |

**Why (measured in June):** in a crowd the pushes cancel out around the player, so
the resulting flee is weak and erratic. Running from the single nearest threat is
decisive, and it's better. The fix that *did* work was more surgical:
[steer around hulks](#hulk-handling).

</details>

<details>
<summary><a id="edge-deflection"></a>❌ <b>Edge deflection (turn along the wall instead of into it)</b>: −0.40 waves on MAME, no effect on the farm</summary>

**The idea.** On MAME, 73% of spark deaths were at edges or corners. So when the
bot flees toward a nearby edge, turn 45° to run along it.

**Results:** MAME June, −0.40 waves over 100 paired games (41% win rate). Farm
September, −0.015 (range −0.056 to +0.028).

**Why (from the June analysis):** the edge clustering was correlation, not cause.
Forcing the flee off the edge breaks the decisive flee from the nearest threat,
the same failure as the [threat field](#threat-field-steering).

</details>

<details>
<summary><a id="hulk-handling"></a>✅ <b>Handle hulks better</b>: steering around them ships (+1.26 waves); not shooting them and shoving them both lost</summary>

Hulks can't be killed and they push toward the player, so they get their own
rules.

| Change | Result |
|---|---|
| **Steer around hulks:** when the flee points at a nearby hulk, turn 45° to the nearest clear direction | ✅ **+1.26 waves**, 100 paired games, 60% win rate. On by default. Evolution later widened its range from 60 to 90 px. |
| **Don't waste shots on hulks:** shoot the nearest killable enemy instead | ❌ −0.69 waves over 61 paired games, getting worse as games were added |
| **Shove hulks with shots when pinned** (shots push hulks back) | ❌ lost on MAME. The log records it as failed; the exact numbers weren't carried forward. |

**How the hulk problem has shrunk:** hulks caused about 30% of deaths on MAME in
early July, 20% for the memory-reading bot on July 4, and **about 5–6% for today's
video bot** (September: 4.9% of 600 deaths, 6% in late waves).

**The June lesson** was that *movement* fixes for hulks and quarks worked and the
*shooting* fix didn't.

</details>

<details>
<summary><a id="quark-kiting"></a>✅ <b>Back away from quarks while shooting them</b>: +0.72 waves</summary>

**The problem (June, MAME).** Quarks caused 32% of deaths. The bot walked *toward*
them to get a shot and died on contact.

**The fix.** A close quark is now a top-priority threat: flee it from 75 px while
firing at it.

**Result:** +0.72 waves over 100 paired games (58% win rate), with quark deaths
down from 32% to 27%. The range was tuned: 50, 60 and 90 px were all worse than
75. Evolution later pushed it to 84.

**Correction:** the June explanation ("quarks teleport") turned out to be a
label-decoding error. Quarks drift slowly. The measured gain stands.

</details>

<details>
<summary><a id="keep-an-escape-route-open"></a>❌ <b>Keep an escape route open / don't get cornered</b>: tried 3 ways, worse early, no effect late</summary>

| Version | Result |
|---|---|
| June, MAME (learned policy): penalty for being surrounded on 3+ sides | mean 3.2 → 2.9; it learned to freeze and flee. Reverted. |
| Early simulator: "escape corridor" mode | built on the old simulator; its numbers don't transfer |
| Sept: planner penalty for moves that leave few exits, strength 6 and 2 | farm, waves 5–25: **−0.031** / +0.003 |
| Sept: same, on the exact-state harness | late waves 1.147 vs 1.143 deaths/wave (no effect); early waves 0.87 vs 0.77 (**worse**); games reaching the wave-60 cap 4/8 vs 7/8 |

**Why we closed it.** It was the most promising planner idea we had left. It did
nothing where it should have helped and hurt where it shouldn't have mattered.
"Don't get cornered" *sounds* impossible to argue with, and that's why it's worth
listing.

</details>

<details>
<summary><a id="smarter-dodging-math"></a>⚪ <b>Smarter dodging math</b>: about 10 variants, all flat</summary>

Refinements to how the planner searches, each tested on the farm or on video:

- Account for the controller's delay while dodging (3 versions)
- Weight projectiles more heavily; widen the spark danger zone
- Keep more distance from enforcers
- Prefer to keep the current heading ("sticky")
- 4 vs 6 vs 8 search steps
- Better handling of "every option is bad" (tested on both the farm and video)
- Different speed smoothing (0.3 and 0.8 vs 0.5) and projection lengths

**All flat.** The mechanism was found in July: with about 2 ticks of controller
delay, a spark fired from point-blank range arrives before *any* dodge can land.
So the spark problem is really a problem with whoever fired it. That insight
became [shoot the launcher](#shoot-the-launcher-boxing-you-in), which worked.

</details>

<details>
<summary><a id="actually-stand-still-when-told-to-hold"></a>⚪ <b>Actually stand still when told to hold</b>: fixed a real bug that turned out not to matter</summary>

A review in September found that every bot turned the rule bot's `STAY` ("hold
position") into **UP**. The bot never stood still: every "hold" walked it toward
the top wall. With 56% of deaths near walls, it looked like the smoking gun.

**Fixed and tested over 288 games: +0.004.** No effect.

**Likely why:** the planner overrides the rule bot whenever the bot is in danger,
so a `STAY` rarely reached the controller in the moments that kill it.

</details>

<details>
<summary><a id="dodge-the-shot-before-its-fired"></a>❌ <b>Dodge the shot before it's fired</b>: flat on the farm, worse on exact-state</summary>

**The idea.** Enforcer sparks are the top killer and they're fast. Treat the lane
each nearby enforcer is about to fire down as already dangerous.

**Result:** flat on the farm. On exact-state late waves, **worse**: 1.15 vs 1.02
deaths/wave (p≈0.08).

**Why (measured):** it predicted too much danger near walls and pushed the bot off
the walls into the pack. This was the last untested idea on our list in
September. Closing it is what settled [the ceiling](#5-four-things-we-measured-that-constrain-every-new-idea).

**Related:** a July version that placed fixed danger zones on spawners and tanks
("phantom sources") also lost. It made the bot timid.

</details>

<details>
<summary><a id="sparks-sliding-along-walls"></a>❌ <b>Model sparks sliding along walls at full speed</b>: worse; the old model was already right</summary>

From an observation of real play: sparks that hit a wall slide along it, and
that's where a player backed against the wall gets hit.

**Result:** exact-state late waves, 1.11 vs 1.02 deaths/wave (worse). The farm
showed no effect at 576 games.

**Why:** the planner already slid sparks along walls, at the part of their speed
that runs along the wall. That turned out to be the correct model. Full speed
overestimates wall danger and pushes the bot into the pack.

</details>

<details>
<summary><a id="endgame-hunt"></a>✅ <b>Chase the last enemies instead of hiding</b>: took MAME games reaching W100 from 4% to 76%</summary>

**Spotted by watching play (July 3):** with one enemy left, the bot ran to a wall
and waited for it to come, wasting time while the remaining grunts sped up.

**The fix:** when nothing is threatening, advance on the nearest killable enemy
and fire from a 90 px standoff. Fleeing threats still takes priority.

**Result (MAME, 90 games):** mean **174 vs 49** waves, and games reaching W100
went from **4% to 76%**. On the memory-reading Xbox bot at the time, no
measurable change, because its games were limited by deaths rather than by
wasted time. It ships in production. A more aggressive 60 px standoff was tested
on video in August: no effect.

</details>

<details>
<summary><a id="scripted-wave-openings"></a>❌ <b>Scripted opening moves at wave start</b>: nothing to fix</summary>

**Measured:** **0% of video deaths** happen within 3 seconds of a wave starting.
Deaths cluster 8–20 seconds in (median 16 s). The memory-reading bot's July
analysis agrees: 1 of 41 real deaths was a spawn-in. A "wave-start blind window"
theory was ruled out at the same time.

</details>

### Shooting and target choice

<details>
<summary><a id="shoot-spawners-first"></a>❌ <b>Shoot spawners first</b>: 6 attempts; it always costs score and never cuts deaths</summary>

**The idea.** Spheroids, quarks and brains produce the enemies that kill you.
Kill the source.

| When | Version | Result |
|---|---|---|
| Mar | brain3: spawners are target tier 1, with extra aggression after a death | best wave 7; replaced |
| Early sim | Spawner priority +1000 | old simulator; numbers don't transfer |
| Jul 4, MAME | Snipe spawners at any range / at up to 250 px below enforcer priority, at two delay levels | **−3.0 to −4.5 waves**; score/wave 18.2k → ~13k for any-range sniping |
| Jul 31, video | Brains first (`FSM_SPAWNER_FIRE`) | score **−3,615/wave (p=0.019)**, no fewer deaths |
| Sep 4, farm | Brains first, 150 and 250 px | +0.023 (range −0.04 to +0.09) and −0.008: flat |
| Sep 6, farm | Spheroids and quarks first, up to 300 px | NET **−0.021**, score **−2.6%** |

Evolution came to the same conclusion by itself: it **shrank** the fire range
for spawner-type enemies (175 → 130 px) and **grew** it for grunts
(75 → 219 px).

**Why (from the July MAME analysis):** cross-board shots at moving spheroids miss,
because there are only 8 fire directions and the target moves while the shot
travels. Meanwhile the enforcers and grunts in the danger zone go unshot. Fewer
kills means fewer points, fewer extra lives, and shorter games.

**One nuance.** The W158 record on the memory-reading bot used a configuration
that included brains-first. That setting's own contribution was never isolated
there, and every isolated test, on three test beds, came out flat or negative.

</details>

<details>
<summary><a id="always-be-shooting"></a>🅿️ <b>Shoot whenever the gun is idle</b>: slightly fewer deaths, slightly less score</summary>

When nothing else wants the gun, shoot the nearest killable enemy.

**Result (864 games per arm):** deaths **−0.026/wave** (real, consistent in both
runs), score **−1.4%**, NET **+0.011** (range −0.006 to +0.029).

**Why it's parked:** the range includes zero, and the score cost caps the upside at
about a rounding error. It's built and harmless, but it won't move the results.

</details>

<details>
<summary><a id="shoot-the-launcher-boxing-you-in"></a>✅ <b>Shoot the enemy that's boxing you in</b>: the first life-positive video bot</summary>

**The idea (July 30).** Sparks fired from point-blank range can't be dodged (see
[smarter dodging](#smarter-dodging-math)). So when the planner has to step in,
aim the gun at the enemy that's limiting its escape. Kill the launcher.

**Result on video:** deaths 1.20 vs 1.38 (p=0.027), max wave 21.9 vs 17.5
(p=0.007), NET +0.079 vs −0.039. **The first positive NET ever measured on
video.** Replicated at 40 games per arm: max wave 23.1 vs 20.0, NET +0.115 vs
+0.013.

**Worth knowing:** on perfect-information MAME it was a tie (July), and slightly
positive in September. It helps most when input is imperfect. It ships on the
video path.

</details>

<details>
<summary><a id="dont-shoot-tank-shells"></a>❌ <b>Don't shoot tank shells (the shell-budget trick)</b>: −3.04 waves on MAME, no effect on video</summary>

**The idea.** From the game's code: tanks have a shell budget per wave, and shells
that expire on their own are never counted back. If you dodge instead of
shooting them, the tanks eventually go silent for the rest of the wave.

**Results:** MAME July, **−3.04 waves** (range −5.2 to −0.9, 94 games). Video
August, no effect (p>0.48).

**Why (from the MAME analysis):** shooting shells was protecting the bot. The
tank-silencing payoff comes too late to make up for it.

</details>

<details>
<summary><a id="per-class-aim-lead"></a>⚪ <b>Different aim-ahead per projectile type</b>: no effect</summary>

A longer lead for projectiles (1.0 or 1.3 ticks) than for other enemies (0.7).
No effect on Xenia (8 games per arm) or on the farm.

**Why:** the best lead is a flat plateau from 0.5 to 0.9 ticks (see
[the lead fix](#aim-where-things-will-be-the-biggest-win)), so differences this
small don't change play.

</details>

### Rescue and scoring

<details>
<summary><a id="rescue-seeking"></a>✅ <b>Go get civilians whenever it's safe</b>: +35% score</summary>

**The problem (July 1, MAME).** The bot only rescued civilians that happened to be
close by (~92 px). When idle, it preferred chasing spheroids to rescuing. Yet
rescues escalate from 1,000 to 5,000 points each, and a free life comes every
25,000.

**The fix:** when no threat demands attention, head for the nearest civilian at
any distance.

**Result:** score **+35%** (621k vs 459k per game), waves +1.27 (range −0.8 to
+3.4), and income crossed the self-sustaining line (25.6k points/wave). Records
at the time: wave 48, 1.15M points. It ships in production.

</details>

<details>
<summary><a id="rescue-more-civilians"></a>❌ <b>Rescue more of the civilians on rich waves</b>: not possible, and we checked directly</summary>

**The idea.** In late waves about 90% of score is rescue bonus. A "rich" brain
wave has 25–26 civilians and the bot rescues 8, leaving 17. That looks like a
huge pile of free points.

**How we checked.** We counted the peak number of civilians each wave, then ran
the **exact-state bot**, with perfect knowledge of every civilian and brain.

| Wave type | Share of late waves | Civilians (peak) | Rescued | Left |
|---|---|---|---|---|
| Ordinary | ~80% | ~9 | ~8 | ~1 |
| Rich brain wave | ~20% | 25–26 | 8–15 | 10–18 |

**The perfect-information bot also rescues about 8 of 25.** Brains turn the rest
into progs before *anything* could reach them. That's how those waves work, not
a gap in the bot's play. The perfect-information bot reaches W100 with the rescue
rate we already have. **Earning more is not the lever.**

</details>

<details>
<summary><a id="rescue-boosts"></a>⚪ <b>Boost rescue priority</b>: no effect or worse in every form</summary>

| Version | Result |
|---|---|
| Memory-reading bot, July 5: go after civilians harder (3 versions) | all lost: NET −0.009 / +0.003 / −0.022 vs +0.067 for no change |
| MAME, July: wider civilian range while brains are on screen | no effect at all: identical games, because rescue-seeking already goes after civilians at any distance |
| Video July 31 and farm Sept: same, at 1.5× | flat |

**Likely why:** once the bot goes for civilians whenever it's safe, pushing harder
just trades safety for rescues it would have made anyway.

</details>

<details>
<summary><a id="shoot-the-brains-during-rescue-waves"></a>❌ <b>Target brains first while civilians are on the field</b>: everything got worse at once</summary>

The obvious next step from the entry above: if brains are converting the
civilians, shoot the brains first.

| Exact-state late waves | before | after |
|---|---|---|
| Deaths/wave | 1.07 | **1.17** |
| Rescues/wave | 8.1 | **7.8** |
| Score | | **−5%** |

More deaths, *fewer* rescues, and less score. Chasing brains pulls the bot away
from both the civilians and safety.

</details>

### Reaction time and delay

<details>
<summary><a id="aim-where-things-will-be-the-biggest-win"></a>✅ <b>Aim where enemies will be (0.7-tick lead)</b>: the biggest single win on video</summary>

**How we found it (Sept 6).** On the exact-state harness we gave the bot perfect
information and then deliberately delayed parts of it:

| Input | Result |
|---|---|
| Exact state, no delay | plays past W100 (stopped at 16.6M points) |
| Exact state, delayed one tick | plays like the video bot (1.15 vs 1.14 deaths/wave) |
| Delay **only the player** | no effect |
| Delay **only the enemies** | all of the damage |

That pinned down a plain bug. The planner projected enemies forward by only
**0.2 ticks** when the measured delay was **0.55**, so it was dodging where things
had been a third of a tick earlier.

**The fix, tested on real video** (8 games per setting):

| Enemy lead | Deaths/wave | Score/wave | NET | Mean best wave |
|---|---|---|---|---|
| 0.2 (old) | 1.106 | 27.9k | +0.01 | 25.4 |
| **0.7 (new)** | **1.024** | **29.5k** | **+0.155** | **38.1** (p=0.001) |
| 1.2 | 1.077 | 28.8k | +0.08 | 31.1 |

Every game at 0.7 reached wave 28 or later. Record: W58, then W60. A follow-up
test found results about equally good **from 0.5 to 0.9**, so the setting holds
up on a rig whose delay differs from the emulator's.

</details>

<details>
<summary><a id="predict-where-the-player-will-be"></a>✅ <b>Predict where the player will be when the move lands</b>: the memory-reading bot's breakthrough to W138</summary>

Controller input takes a moment to take effect, so plan from where the player
*will be*, not where it is.

- **Memory-reading bot (July):** a 0.45-tick player lead took it from a wall around
  wave 40–58 to **W138**, and later W158.
- **Video bot (July 29):** player lead 1.5 plus enemy lead 0.3 raised the mean best
  wave from 14.6 to **18.0** (p=0.003).
- **The rule (September):** the best player lead is about "measured controller
  delay + 0.5 ticks". Testing it exposed a bug on Eric's rig: auto-lead had been
  using *delay − 0.5*, which set his lead to 0.5 every session since round 2 and
  threw away about 0.15 lives/wave. It's fixed (lead 1.5 on his rig).

</details>

<details>
<summary><a id="act-on-the-freshest-frame-eye-sync"></a>✅ <b>Act the moment a new frame arrives (eye-sync)</b>: deaths 1.20 → 1.10</summary>

The bot used to decide on a fixed 15-per-second clock, so it might act on a frame
anywhere from brand new to a full tick old. Now it waits for the newest frame's
detections and acts right away. The average input age dropped from **55 to 34
ms**.

**The 2×2 test** (Xenia, 20 games per setup, waves 5–25):

| Setup | Deaths/wave | Score/wave | NET | Reached wave 26 |
|---|---|---|---|---|
| Baseline | 1.198 | 27.8k | −0.086 | 6/20 |
| Hold-action only | 1.179 | 28.2k | −0.051 | 9/20 |
| Eye-sync only | 1.096 | 27.5k | +0.006 | 10/20 |
| **Both** | **1.085** | **29.3k** | **+0.086** | **14/20** |

Eye-sync's effect: p=0.005 (p=0.001 together with hold-action), replicated in a
second test.

</details>

<details>
<summary><a id="keep-moving-on-a-blind-tick-hold-action"></a>✅ <b>Repeat the last move when no new frame arrives (hold-action)</b>: pays off together with eye-sync</summary>

When a decision comes with no new detections, repeat the last stick command for
up to 4 ticks instead of centering the stick. Flat on its own, best result
combined with eye-sync (table above), so they ship as a pair.

</details>

<details>
<summary><a id="background-vision-thread"></a>✅ <b>Run the vision on its own thread</b>: failed in early July, shipped in August</summary>

- **July 7:** vision on a separate thread at ~31 frames/s → mean 10.75 vs ~14.5.
  A regression, blamed on speed estimates getting noisier. Reverted.
- **August 1 retry:** flat on the main numbers (deaths p=0.97) over about 47 games
  per arm. Every late-wave number leaned positive, and it matches how the
  hardware version has to work anyway, so it shipped. Eye-sync (above) builds on
  it.

</details>

<details>
<summary><a id="fresher-memory-reads"></a>✅ <b>Fresher data for the memory-reading bot</b>: W18 → W39 in one change</summary>

This only applies to the memory-reading bot on the emulator, but it shows how
much stale data costs.

- **Reading the enemy lists the way the game does** (July 3) cut about 250 ms of
  staleness. The very next game went from a W18 ceiling to **W39 and 1.02M
  points**.
- **Syncing reads to the game's frame, smoothing speeds (0.5), and fixing a
  false-death counter** (July 4): real deaths/wave 1.22 → 1.05.
- **July lab test:** delaying the MAME bot's input by 1 / 2 / 4 ticks alone
  reproduced the Xbox gap exactly. Projecting enemies forward recovered 90% of
  the loss at a 1-tick delay.

</details>

<details>
<summary><a id="think-faster-30-decisions-per-second"></a>❌ <b>Think faster (30 decisions per second)</b>: the worst result in the ledger</summary>

| Test | Result |
|---|---|
| Video, Sept: 30 decisions/s | mean best wave **20.4 → 8.5** (p<0.001) |
| Farm, Sept: same | NET **−0.40** |
| MAME, July: act every 2 frames instead of 4 | **−2.88 waves** (range −5.7 to −0.05) |
| Early sim, June: same | no better |

**Why (from the July analysis):** halving the time between decisions also halves
how far each decision moves the player, so dodges take longer to execute. The
rule bot's constants also assume 15 decisions per second. Retuning for 30 would
mean re-evolving everything with no guaranteed gain.

**The lesson: fresher input beats more frequent decisions.** That's why
[eye-sync](#act-on-the-freshest-frame-eye-sync) worked.

**Caveat:** 30 Hz has never been tested together with eye-sync and the faster
detector. That's cheap and on the [open list](#6-whats-still-open), though we
expect it to lose again.

</details>

<details>
<summary><a id="faster-detector-tensorrt"></a>⚪ <b>Faster detector (TensorRT, 21.5 → 9.2 ms)</b>: no measurable effect</summary>

More than twice as fast. Deaths per wave didn't change in either test, including
a late-wave test (1.28 vs 1.39, not significant).

**Why:** a frame is already about 34 ms old when it reaches the detector, because
of the display and capture path. Speeding up our own processing doesn't change
that. It's optional, and we don't recommend it for Eric's rig.

</details>

<details>
<summary><a id="faster-screen-capture"></a>⚪ <b>Faster screen capture</b>: the delay happens before our capture</summary>

- **Windows Graphics Capture** (September): measured delay unchanged.
- **Cheaper capture methods** (BitBlt, a faster PrintWindow mode): 2–4× faster, but
  they return **black frames** from the emulator's window.
- Two other libraries (dxcam, bettercam) crashed.

**Where this still leaves room:** on the real console, the delay comes from the
capture card and display path. One rig showed 40% duplicate frames. That's the one
place a hardware change could reduce the delay directly, and only Eric can test
it. See [§6](#6-whats-still-open).

</details>

<details>
<summary><a id="auto-calibrate-the-delay"></a>❌ <b>Measure the delay live and adjust automatically</b>: worse</summary>

- **Per-game delay auto-calibration** (July 30): score −1,546/wave (p=0.08).
  Rejected. It stays measure-only.
- **Auto-correcting the detector's box positions** on Eric's rig (hardware
  round 3): drifted twice, because menu icons and color changes fooled the
  estimate. Demoted to measure-only.

**Rule since then:** automatic adjustment loops don't ship until they've been
checked against the truth.

</details>

<details>
<summary><a id="predict-enemy-movement-with-a-model"></a>❌ <b>Predict enemies with a movement model instead of straight lines</b>: no gain</summary>

Advance every threat 0.75 ticks using its real behavior (chasers chase, shells
bounce) before the search, instead of projecting straight lines.

**Result (farm, 288 games):** −0.026 (range −0.057 to +0.003). The simple straight
projection is as good or better.

</details>

### Vision and detection

<details>
<summary><a id="better-training-labels"></a>✅ <b>Fix the detector's training labels</b>: detector accuracy (mAP) 0.38 → 0.85</summary>

**July 3:** the detector's training boxes were being generated from the wrong
memory reader, so many were drawn over empty screen (82% of electrode boxes). We
fixed the reader and two screen-offset errors (−15 px vertical, +3.5 px
horizontal).

**Result:** detector accuracy (mAP50) **0.38 → 0.85**, with electrode recall
0.04 → 0.95. The video bot's range moved from W7–10 to W9–15. Label quality was
the whole story; model size wasn't the problem.

</details>

<details>
<summary><a id="more-missile-and-shell-training-data"></a>✅ <b>Recover the missing missile and shell training data</b>: "never-seen" deaths 16–22% → 2%</summary>

**July 8:** we'd thought missiles were rare in the data (431 examples). In fact
the archive held over a million. A filter was throwing away 91% of missile frames,
because fast objects move between the memory read and the screen grab. We
re-centered those boxes on the visible sprite instead.

**Result:** accuracy 0.906, missile recall 0.34 → 0.60, and deaths from threats
the bot **never saw** dropped from **16–22% to 2%**. New records at the time:
W21–W23.

</details>

<details>
<summary><a id="small-object-detector-head"></a>✅ <b>A detector variant tuned for small objects</b>: kept for fewer deep-wave deaths</summary>

A detector with an extra small-object layer (yolov8s-p2): accuracy 0.921,
missile recall up at every threshold. The mean was a tie (13.92 vs 13.71), but
deaths per wave were the best ever at the time (0.898), and there were 3 games
past W20 in 50 vs 4 in 1,146 before. It ships (weights "yolo6", confidence
threshold 0.30).

</details>

<details>
<summary><a id="more-retraining"></a>⚪ <b>More retraining</b>: the detector is at its ceiling</summary>

- **Hard-example fine-tune** (July 7): oversampling frames the detector missed.
  Flat. Duplicates add no information.
- **Retrain cycle 2** (July 15): 32k new frames from the bot's own deep-wave play.
  Tied with the previous model at every threshold.

**Conclusion (July 15):** for this model size and resolution, more data isn't the
constraint.

</details>

<details>
<summary><a id="detection-thresholds"></a>❌ <b>Lower detection thresholds</b>: more detections = more phantoms = worse play</summary>

| Change | Result |
|---|---|
| Thresholds 0.05 for projectiles | a flood of false detections. The bot dodged phantoms into real enemies. Reverted. |
| Per-class threshold table active (July 30) | score −2,454/wave (p=0.055). Rejected. |
| Flat 0.30 | ✅ ships |

**Two bugs found along the way:** progs were missing from the threshold table, so
the bot **never saw a prog** (fixing it: median wave 15 → 16, max 16 → 18). And a
`--conf` default of 0.4 silently overrode every per-class threshold for weeks,
which makes several early threshold results suspect.

**The pattern:** *false positives cost more than misses.* The bot reacts to
everything it sees.

</details>

<details>
<summary><a id="coast-projectiles-when-unseen"></a>✅ <b>Keep tracking projectiles for a moment when a detection drops out</b>: mean 10.7 → ~14.5</summary>

**July 7 ("the coaster"):** sparks, shells and missiles fly straight, so when the
detector misses one for a frame, carry it forward along its path. Per-frame recall
of about 70% becomes about 95% effective coverage.

**Result:** mean wave 10.7 → ~14.5, and the video record went to W19 at the time.
Shortening how long a missed projectile is carried from 5 ticks to 3 cut position
error by a third (p90 29 → 20 px), and the mean went from 12.9 to 13.6. Kept.

</details>

<details>
<summary><a id="remember-what-you-saw-object-tracking"></a>❌ <b>Remember every object between frames</b>: better recall, worse play, 5 versions</summary>

| Version | Result |
|---|---|
| Track and carry **every** enemy type (July 28) | best recall (0.979) and fewest deaths, **but** score 22.9k vs 27.7k (p<0.001), fewer rescues, **max wave 10.0 vs 14.6** (p<0.001) |
| "Lean" tracker: track but don't carry electrodes and civilians (and grunts/hulks) | deaths 1.20 vs 1.22, score 27.1k / 28.0k vs 28.6k, max wave 16.3 vs 17.0: no gain |
| Infer spawn points as fixed objects | W6 / W10: a regression |
| Continue tracks from low-confidence detections (3 versions) | one tie, then mildly harmful, then 2.4 standard errors worse. Retired. |
| Frame-to-frame box persistence (ByteTrack) | no change |

**Why (measured):** about one extra phantom per tick made the bot evasive. It died
less but rescued less, and rescues are what earn lives. **Better perception doesn't
automatically mean better play.**

</details>

<details>
<summary><a id="smarter-projectile-tracking"></a>❌ <b>Smarter projectile tracking (homing missiles, line fitting)</b>: both harmful</summary>

- **Curve missed missiles toward the player** (they home): mean 10.6 vs 14.4.
  Harmful. The curved ghosts over-warned the planner, and it fled into real
  threats.
- **Fit a straight line to the last 4 positions** instead of using the last 2: mean
  10.6 vs 14.4. Harmful. Sparks bounce off walls, and a 4-point fit lags every
  bounce.

Both were stopped early (5 games each), which is enough to see results this large.
The simple 2-point estimate with smoothing is close to right for this game.

</details>

<details>
<summary><a id="crop-and-zoom-the-detector"></a>⚪ <b>Crop or zoom the detector</b>: cropping had no effect, zooming was disastrous</summary>

- **Arena crop** (drop the HUD, retrain on the play area): missile recall
  **+6 points**, **zero** effect on play (mean 13.04 vs 13.49). That's useful on its
  own: the tracker already covered almost every missile by the time it mattered.
- **Zoom on the busy area ("fovea"):** games ended at W1–3. The detector was never
  trained on zoomed images. It would need retraining before it could even be
  judged.

</details>

<details>
<summary><a id="is-the-vision-missing-things"></a>⚪ <b>Is the vision missing things?</b> Checked three times: no</summary>

**September:** 74,000 late-wave snapshots, comparing detections with the game's
memory.

| Enemies on screen | Share detected |
|---|---|
| 5–9 | 89% |
| 10–14 | 92% |
| 15–19 | 91% |
| 20–24 | 91% |
| 25–29 | 91% |
| 30+ | 90% |

**Flat:** the detector doesn't get worse on busy screens. By type: Tank 97, Prog
97, Spheroid ~97, Electrode 96, Hulk 96, Grunt 95, Quark 92, Enforcer 91, Brain
90. False detections are 4–6%, and the player's position is typically off by
0.6 px. Missiles (78%), sparks (87%) and shells (93%) score lower only because they
move farther than the 22 px matching distance during the 34 ms delay. That's the
delay showing up in the numbers, not a detector failure.

**July, two earlier checks:** 98–99% of deaths were from threats the bot *had*
seen, and the arena-crop retrain gained recall without gaining waves.

</details>

### Tuning the constants

<details>
<summary><a id="evolve-the-constants"></a>✅ <b>Evolve the constants</b>: built the W100 champion on MAME; can't see through video noise</summary>

**On MAME with perfect information, evolution was the engine of progress:**

| Round | Result (mean wave) |
|---|---|
| June: honest fitness | 10.4 → 11.18 → **12.72** |
| June 30: also evolve the quark and hulk distances | **+2.84 waves** over 100 paired games |
| July 2: evolve with the planner running | **+10.25 waves**; first W100+ game (W113); official mean 49, max 142 |
| Second rounds (June and July) | both lost to the version before (−0.85; mean 156 vs 174) |

**On video it hasn't worked:**
- **Xenia, 24 constants, 12 generations** (August–September): the evolved mean
  replayed at NET −0.067, about the same as the defaults. Stopped at 7.5 hours per
  generation, with differences inside the ±0.07 noise. (Generations 1–11 also
  carried an evaluation bug.)
- **Farm, 14 generations at 24–48 games per candidate:** a random walk. A run at
  288 games per candidate was started twice and died both times before producing
  a result.

**Likely why:** game-to-game luck on video is bigger than the difference between a
good and an average set of constants. Fixing that needs 576+ games per candidate,
which means days per generation. See [§6](#6-whats-still-open).

</details>

<details>
<summary><a id="tune-one-constant-at-a-time"></a>⚪ <b>Tune constants by hand, one or a few at a time</b>: the evolved values hold</summary>

All on video, July–August:

| Change | Result |
|---|---|
| Dodge projectiles 17% earlier / 25% later | both lost ([details](#bigger-safety-margins)) |
| Fire range for projectiles 150; move range 80 | flat |
| Whole fire bundle (5 fire ranges + consider 3 targets instead of 1) | flat |
| Hunt standoff 60 (more aggressive) | flat |
| Planner danger 14 ("braver") | flat |

**Conclusion (August):** the rule bot's constants are at a local optimum even on
video. The gap isn't in any one of them.

</details>

### Test-bed dead ends

<details>
<summary><a id="start-deep-to-practice-late-waves"></a>❌ <b>Start games at wave 24 to practice late waves</b>: not possible</summary>

The wave address we found (`0x82388E20`) only holds a copy of the number shown on
screen. Writing to it changes the display and nothing else. A second candidate
turned out to be a frame counter.

**What we do instead:** the exact-state harness ends each game at a set wave, so
every game spends as much time as possible in the late waves.

</details>

<details>
<summary><a id="use-the-fast-farm-for-late-wave-questions"></a>❌ <b>Use the MAME farm for late-wave questions</b>: invalid</summary>

The farm is tuned to match the video bot **in waves 5–25**, and it does. Past wave
25, deaths fall on the farm while they rise on the Xbox, and it only gets about
200 late-wave samples per 144 games. Late-wave questions are answered on Xenia or
the exact-state harness.

</details>

<details>
<summary><a id="other-test-bed-dead-ends"></a>❌ <b>Other test-bed dead ends</b></summary>

- **A faster custom 6809 emulator** (Sept 3): freezes at wave 5 in one mode and wave
  1 in the other. More than 5 patches failed. Parked.
- **Two screen-capture processes on the emulator at once:** the emulator crashes.
  Pair diagnostics only with the memory-reading bot.
- **Evaluation pairing on MAME:** two games with the same random seed diverge
  within a wave or two for planner bots (correlation 0.18), so "paired" tests
  barely reduce noise. Only large-sample means count.

</details>

### Scoreboard and harness

<details>
<summary><a id="reading-the-scoreboard-off-the-screen"></a>✅ <b>Read score, wave and lives off the screen</b>: confirmed working on Eric's rig</summary>

Not a gameplay change, but every measurement depends on it. Over hardware rounds
1–12 (August–September) we shipped:
- score and wave reading that works with any HUD color
- wave-digit templates built from Eric's own frames (his '8' was reading as '0')
- deaths counted only when the lives icons drop
- fixes for 6-digit scores past 100k and a phantom first-game death
- menu handling that only ever presses A
- a capture test tool (it found `dshow MJPG 1080p` for his Magewell card)
- a stale-frame measure

**On the real console: "all waves correct, no false deaths."** Two follow-ups: the
attract-mode demo is recognized by its spotlight effect and skipped instead of
played, and each game's end is reported only once.

</details>

---

## 5. Four things we measured that constrain every new idea

**1. The bot can't earn more points.** After wave 20, about 90% of score is rescue
bonus. The perfect-information bot rescues the same ~8 of 25 civilians on rich
waves. Every attempt to earn more made things worse
([details](#rescue-more-civilians)).

**2. The bot isn't blind.** About 90% of enemies detected, flat from 5 to 30+ on
screen. Player position typically within 0.6 px
([details](#is-the-vision-missing-things)).

**3. What's left is delay, and it happens before the frame reaches our code.**
Every frame is about 34 ms old when we act on it. That delay comes from the
emulator's (or the console's and capture card's) display path. A faster detector
and faster capture didn't reduce it. Aiming ahead makes up for the *predictable*
part. It can't account for things that *happen* within those 34 ms, like a shot
being fired or an enemy turning. The video bot dies about as often as the
perfect-information bot given one tick of delay (1.26 vs 1.33 deaths/wave), and
far more often than it does with no delay (1.07).

**4. Hand-written rules plus a light-touch planner beat everything else we've
built.** About 20 learned policies never matched the rules. Every planner change
that steps in more often, whether planning further ahead, preferring open space,
or wider margins, lost. The wins removed errors (labels, delay, stale data) or
added an ability (dodge planner, hunting, rescuing, shooting the launcher).

> [!IMPORTANT]
> **So the shipped video bot is at the ceiling for this design at this delay:**
> mean wave 31, median 30, half of games past wave 30, records W58 and W60.
> Reaching W100 reliably needs either a decision-maker that beats the
> perfect-information bot in late waves, or less delay in the capture hardware.

---

## 6. What's still open

None of these has been tested. This is where new ideas have room. Each has a
rough estimate of its chances, so nobody spends a week on a long shot by
accident.

| Direction | Why it might work | Chances |
|---|---|---|
| **Lower-delay capture on the console** | Goes straight at the remaining problem. One rig showed 40% duplicate frames. Only Eric can test this. | **Moderate, and cheap to try** |
| **Re-run the wall-repulsion and open-space tests on the fixed farm** | The only direct September tests ran on a farm build with rescue-seeking off. About an hour of farm time. | Low (every related test lost), but cheap |
| **An exact game model + look-ahead over whole move sequences** | Planned on MAME in July; the data plumbing was built, the model never was. It's the one planner idea aimed at beating the perfect-information bot's late waves. | Low to moderate; weeks of work |
| **"Clear a route, then take it"** (plan moves and shots together) | [Shoot the launcher](#shoot-the-launcher-boxing-you-in) is a narrow version and it won on video. The general version is untested. | Low to moderate |
| 30 Hz decisions *with* eye-sync and the faster detector | 30 Hz was only tested before eye-sync existed | Low, but cheap |
| Aim-ahead per detection's own delay instead of one global value | More precise leads | Low (the lead has a wide flat optimum) |
| Shove hulks on video | Lost on MAME; hulks cause only ~5% of video deaths now | Low |
| Re-evolve on video at 576+ games per candidate | Earlier video runs used far too few games | Moderate in principle, too expensive in practice |
| A *different kind* of learned policy (e.g. learn the planner's scoring, not raw moves) | About 20 standard variants failed; a new setup would have to avoid copying moves directly | Low |

---

## 7. How to propose an idea so we can test it fast

1. **Check §1 and §4 first.** If your idea is already here, explain what's
   different now. That's a valid reason to reopen something: "you tested it before
   X existed" is exactly why 30 Hz is back on the open list.
2. **Describe the change, not the result you want.** "Target brains first while
   civilians are on the field" can be tested in an afternoon. "Play the rescue
   waves better" can't.
3. **Explain how it earns or saves lives.** A change that cuts deaths but costs
   score has a high bar. See [kiting](#circle-the-field-kiting) and
   [spawners first](#shoot-spawners-first) for how that usually ends.
4. **Check it against [§5](#5-four-things-we-measured-that-constrain-every-new-idea).**
   If it depends on earning more points, seeing better, or the planner stepping in
   more often, we've already measured those.

> [!WARNING]
> **Several ideas here were obviously right and still lost:** don't get cornered,
> stay off the walls, kill the spawners, save more civilians, dodge earlier,
> don't waste shots on hulks. Robotron punishes them in ways you can't see from
> the outside. That's not a reason to stop suggesting things. It's why we measure
> every idea instead of arguing about it.

---

*Every number here comes from a logged run. For file names, settings and exact
commands, see [STATE_OF_PLAY.md](STATE_OF_PLAY.md). How each enemy actually
behaves, from the game's own code, is in [docs/ENEMY_MODEL.md](docs/ENEMY_MODEL.md).
The raw June–July MAME lab notebook is archived at
[docs/archive/MAME_EXPERIMENT_LOG.md](docs/archive/MAME_EXPERIMENT_LOG.md).*
