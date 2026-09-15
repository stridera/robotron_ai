# Daytime research — 2026-09-09

User authorized the machine for testing for the rest of the day. No system or
Python upgrades/restarts are being performed. Production defaults are unchanged.

## Measurement repair

ROM disassembly shows score additions write the low BCD pair before propagating
the carry. A frame callback can read between these writes: e.g. 366875 → 366800
→ 366900. The old guard rejected the entire otherwise valid episode. A bounded
measurement filter now holds the last good total for at most three samples,
logs every anomaly/recovery, rejects persistent corruption, and never joins an
episode across an emulator restart. It does not affect gameplay inputs.

Pilot: all 42 games valid; all 14 previously accepted controls reproduce exactly
(wave, score, deaths, decision count). Artifacts: `logs/score_pilot_20260909`.
Full repair: `logs/score_repair_20260909`; valid original episodes are preserved,
rejected original seeds replayed with frozen policies, and only remaining true
failures replaced with new seeds. This completes the planned 144 games per arm.

Completed repair, 12:30 p.m. PDT: all 2,016 planned valid episodes available.
Three replayed episodes still suffered an emulator recovery and were replaced;
none was silently accepted. Full comparisons, NET lives/wave delta:

| Variant | Delta | Game-bootstrap 95% interval |
|---|---:|---:|
| turn1 | -0.3343 | [-0.3804, -0.2894] |
| turnguard | -0.1661 | [-0.2071, -0.1234] |
| turncommit | -0.2647 | [-0.3020, -0.2254] |
| shot2 | -0.0209 | [-0.0643, +0.0214] |
| shot4 | -0.0059 | [-0.0506, +0.0409] |
| fan12 | -0.0172 | [-0.0585, +0.0279] |
| fan24 | -0.1225 | [-0.1642, -0.0806] |

No variant passes the predeclared independent-confirmation entry threshold.
These are W5–25 MAME results, not evidence about late-game Xenia behavior.

## Learning experiment

The archive already contains failed residual PPO and learned-value experiments.
Those used an older FSM without today's clearance champion, privileged slot
observations, and heavily shaped rewards. Some value search also used lossy
MAME save/restore branching. This experiment does not repeat those conditions:

- Current champion and exactly the calibrated delayed/noisy MAME lab loop.
- Only keep / adjacent left / adjacent right movement; champion chooses fire.
- Features from the same processed sprites the champion receives, with no
  score, wave, lives, entity addresses, or true positions.
- Reward = score/25000 minus deaths, scaled 25; no survival/aim/wave bonuses.
- Initial policy keeps champion with 98% probability (100% when evaluated
  greedily), small updates, frozen checkpoints, held-out seed comparisons.
- Fresh emulator per episode; no counterfactual save/restore branching.

Execution parity and reward bookkeeping must pass before training. No model
will be promoted from training reward alone or a selected best game.

Verification passed: eight full accepted-seed replays were identical through
the generator and no-op actor. The Gym wrapper exactly reproduced W17,
404500 points, 18 deaths, 5379 decisions and summed reward -45.5 = NET*25.
An initial unrelated seed stalled at W26 in both execution paths; preserved in
`logs/residual_env_parity_20260909`. The accepted-seed verification is in the
`_v2` directory. Invalid training transitions truncate at the last valid state
with no invented reward; whole invalid episodes remain excluded from evaluation.

Inference preflight caught BLAS thread oversubscription for the tiny actor.
Single-thread inference measured about 11 microseconds per decision under the
training load. Evaluation children pin numeric threads to one; the portable
actor uses direct NumPy reductions for per-frame vectors, avoiding BLAS thread
wakeup. Both scalar and batch exports are checked against the Torch policy.

Session resumed in the evening. Training actually started around 7:34 p.m. PDT,
in `logs/residual_net_20260909_v2` (3M decisions, 12 workers, 2.5-hour limit,
200k checkpoints). The earlier `residual_net_20260909` attempt failed during
manifest construction before launching games; its error log is preserved.

## Production parity audit

Found a unit mismatch: `TickClock` rescales planner motion for slower cadence,
but `ChampionBrain` called both velocity trackers with an assumed one-tick
interval. The production eye also republishes an observation without telling
the tracker it is a duplicate. Dev vision tracks at the eye's measured cadence.

Optional `ROBOTRON_TRACK_TIME=1` now uses observation read timestamps, divides
velocity by elapsed nominal ticks, passes that interval to projectile coasting,
and reuses tracking results for repeated samples. Long gaps reset velocity
history. Off by default. This fixes a testable unit error; gameplay benefit is
not yet established. HDMI observations retain their pump timestamp across
repeated reads of the same captured frame. Window read time approximates capture
time; neither method identifies repeated images supplied internally by a card.

Another parity difference remains: dev `brain_yolo.py` resets its vision tracker
and suppresses control briefly at memory-detected wave/death transitions. The
production hardware loop logs HUD deaths but resets the brain/perception only
at game-over navigation. Its decisions must be tested directly; a dev-harness
score alone cannot establish the console result. This behavior is not bundled
into the timestamp experiment.

## Automatic evening stages

September 10 00:44 PDT: recovered training from checkpoint 2,400,048 after the old processes disappeared. New run residual_net_20260910_resume, cumulative 3M target, new training seeds, initial actor bit-identical. Held-out evaluation unchanged. Bounded queue resume_queue_20260910; operational details in RESUME.md.

## Automatic evening stages

- Training: complete; artifacts `logs/residual_net_20260910_resume`. 3002160 decisions; 586 seconds.
- Greedy actor: proved identical to champion; artifacts `logs/residual_net_20260910_resume/behavior_audit.json`. Both alternative logits are globally below keep; no gameplay needed.
- residual_sampled_screen_20260909: stopped with error; artifacts `logs/resume_queue_20260910`. MAME stage exited .

## Morning audit — September 10, 10:46 PDT

The supervisor error above occurred AFTER MAME successfully completed. Confirmed
144 valid games per arm, all valid subprocess exit codes zero; six rejected
attempts were replaced. Summary: NET delta +0.01086 lives/wave, 95% game-bootstrap
CI [-0.03099, +0.05506]. Mean maximum wave 22.02 baseline versus 22.88 sampled.
The gain is inconclusive and below the predeclared +0.03 confirmation threshold.
This is W5–25 MAME evidence only. Training is complete and the final model saved.
The empty exit-status handling stopped the queue at 01:14, so Xenia never ran.
Nothing is running. Do not rerun the completed MAME screen because of this
supervisor failure; the production timestamp comparison remains outstanding.

September 10 17:14 PDT: reproduced exit-code loss with redirected Windows and
WSL subprocesses (both success 0 and failure 7 became null); retaining the
native process handle preserves both. Fixed both supervisors and passed focus
tests. The production timestamp A/B is now running in
`logs/production_timing_20260910`, 8 games per arm, cap W40, 2.5-hour bound.
An initial preflight under the old dated name failed on inherited PowerShell
module lookup before game launch; logs preserved. Child-local module search
order fixed, no host configuration changes. Gameplay outcome remains pending.

September 11 13:47 PDT audit: the Xenia batch hit its 2.5-hour deadline, with
only 3/16 completed games: baseline W25/S571125 and W23/S509300, timed
W18/S420575. Oracle logs confirm these terminal waves/scores. Attempts 2 and 4
remained at the prior game-over state for 3600 seconds each; attempt 6 remained
there for 265 seconds until the deadline. No changing wave/score and lives
4294967295 throughout those failed restarts. This is a between-game restart
failure, not a valid gameplay outcome for either arm. No reliable timing effect
can be inferred. Nothing is running. Repair and verify consecutive production
game starts before another full batch; preserve this incomplete run.

September 12 weekend setup: user authorized the weekend and a cron/loop to keep
progress moving. Fresh Xenia per production game and startup-only 180s progress
guard implemented; restart regression tests (2) and focus guard checks passed.
Added explicit result.json per game and weekend completion/audit gates (4 tests).
Installed RobotronWeekend20260912 Task Scheduler task: persistent 30s monitor,
five-minute relaunch and logon recovery, expiry Sunday 23:55 Pacific. Serializes
all gameplay and bounded Codex reviews. Initial verification batch started
00:42 PDT; then 8/arm timing screen if verified. Reviews can diagnose/prepare
and queue next experiments without the user restarting this chat. Rate-limit
cooldown and review/day/observed-token bounds are explicit in WEEKEND_REVIEW.md
and RESUME.md. Status is WEEKEND_STATUS.md.

The headless review mechanism follows official Codex non-interactive guidance:
https://learn.chatgpt.com/docs/non-interactive-mode . CLI authentication and a
read-only review were verified; no API key or new paid API service was configured.

September 12 01:10 PDT: user extended testing through Monday September 14 at
09:00 Pacific and explicitly requested further experiments beyond the initial
queue. Updated both scheduler triggers/runtime, monitor source, and review
instructions. An idle-boundary helper reloads the monitor without stopping the
current batch. Restart validation passed; full timing screen is running.
WEEKEND_TEST_PLAN.md supplies evidence-driven follow-up priorities and allows
small independent screen batches to use machine time within the review budget.

September 12 02:57 review: restart validation completed two W13 games with
matching terminal scores. Timing screen remains incomplete (7 baseline / 8
timed completed, one startup HUD W71 false cap while oracle stayed W0).
Repaired production wrapper startup filtering and cap crossing, including the
related phantom game-over path, and added raw HUD sample logs. Seven production
offline regressions plus four supervisor checks passed. Gameplay source and
weights retain the failed batch's hashes except the test wrapper; dev
brain_yolo.py was preserved. Queued `weekend_timing_capfix_20260912`: independent
8/arm production timing retry, cap W40, four-hour bound, supervisor launch only.
All 15 completed timing games agree on terminal wave/score, but HUD deaths
undercount oracle life balance by 60. Exploratory W5–25 oracle NET difference
+0.08801, whole-game bootstrap CI [-0.04748, +0.25792]; no established gain or
promotion. Detailed assumptions, discrepancies, checks and next-review gates:
`logs/weekend_20260912/review_025754_science.md`; audited data in
`timing_audit_0305_v2.json` and `restart_audit_0305_v2.json` alongside that report.

September 12 05:42 review: the repaired timing screen completed all 16 games
with matching terminal HUD/oracle waves and scores. Audited W5–25 NET delta
-0.10954, whole-game bootstrap 95% CI [-0.24322, +0.02196]; no confirmation or
promotion. HUD deaths undercount life balance by 80. All 356 emitted HUD death
events align within 2s of approximate oracle event times, median delay 0.620s;
wave recognition median delay 1.587s. Added independent opt-in HUD death/wave
tracking resets, plus common evaluation transition logging, with no control
pause or memory input. Eleven production and four supervisor offline tests
passed. Queued `weekend_hud_deathreset_screen_20260912` and
`weekend_hud_wavereset_screen_20260912`, each 8/arm production Xenia W40, max 4h,
review after the second unless a failure forces review. Defaults and dev
brain_yolo.py preserved. Detailed evidence, limitations and next-review gates:
`logs/weekend_20260912/review_054232_science.md`.

## Twelve-hour status audit — September 12, 13:30 PDT

Three full comparisons completed, 8/arm each (48 games), besides the two-game
restart validation and 15 valid games in the discarded incomplete timing batch.
The monitor recovered, fixed the startup false-cap problem, and independently
queued/completed the death-reset and wave-reset screens. No production promotion.

Audited W5–25 NET deltas (candidate minus baseline, higher better), whole-game
bootstrap 95% intervals:

| Candidate | Mean terminal wave, baseline → candidate | NET delta | 95% interval |
|---|---:|---:|---:|
| Timestamp normalization | 25.38 → 23.12 | -0.10954 | [-0.24322, +0.02196] |
| HUD death tracking reset | 22.50 → 23.50 | +0.05958 | [-0.11247, +0.21339] |
| HUD wave tracking reset | 21.12 → 25.25 | +0.06895 | [-0.07519, +0.21528] |

All intervals include zero; neither reset meets the predeclared confirmation
gate requiring positive lower bound. New reset audits exclude no games and
confirm all 16 terminal outcomes in each screen. Their files are
`logs/weekend_20260912/deathreset_audit_1330.json` and
`logs/weekend_20260912/wavereset_audit_1330.json`. These are score/lives-balance
evaluations, not raw HUD death counts: HUD missed 84 and 90 deaths across the
two respective batches. Death-reset's positive NET estimate came from higher
score (+2147/wave), with slightly more deaths (+0.026/wave); wave-reset had
slightly fewer deaths (-0.036/wave) and higher score (+826/wave). Neither is
established as a primary-metric gain. Highest wave in these full screens: W38.

The supervisor is alive with Monday 09:00 deadline loaded, but gameplay is
idle after the last batch completed around 10:50. Its two automated reviews
used 183165 observed uncached-input/output tokens, exceeding the precautionary
150k rolling-day review gate. This is our configured automation budget, not a
reported account quota error. Budget eligibility returns about Sunday 02:58
PDT when the first review rolls out; completed experiments and audit evidence
are preserved for the next review. User's instruction remains to keep finding
useful tests until Monday 09:00 within the review/usage safeguards.

September 12 14:08 capacity correction: user reports 80% remaining capacity
with 4.5 hours left in the cycle. Removed the arbitrary 150k-token and six-review
rolling-day gates, which did not represent account quota. Serial 15-minute
reviews and existing error/actual-limit cooldown remain; usage stays logged.
Four supervisor regressions passed, including acceptance despite large recorded
token totals while still enforcing cooldown and non-overlap. Reloaded the idle
monitor without any gameplay interruption so the pending review can proceed.
The previously reported Sunday 02:58 wait is superseded.


## September 12, 14:09 review — fresh-player control screen

Reused the saved 13:30 audits: death reset NET +0.05958 (95% CI
[-0.11247,+0.21339]); wave reset +0.06895 ([-0.07519,+0.21528]). Both
16-game screens have full terminal HUD/oracle agreement and neither qualifies
for confirmation. Logged switches behaved correctly: controls reset zero
times; candidates reset 165 times on deaths and 194 times on wave advances.

Added opt-in ROBOTRON_FRESH_PLAYER_ACTION=1: a held player coordinate now
enters the existing hold-action path for control only, preserving HUD and
navigation behavior. Defaults remain unchanged. This tests replanning from
stale coordinates during player-detection misses; benefit is unproven.
The production wrapper records bounded consumed-observation/action traces in
both arms for death-window analysis. Memory remains evaluation-only.

Queued weekend_freshplayer_screen_20260912: production Xenia 8/arm, W40,
max 4h, review afterward. 14 production, 5 tracking/default-parity and 4
supervisor offline checks passed; launcher parses. Trace overhead measured
0.061 ms/tick offline for 100 entities plus 20 tracks, 10,000 ticks. No gameplay
was launched by this review. Dev brain_yolo.py and preexisting edits preserved.
Details, limitations and next-review gates:
logs/weekend_20260912/review_140923_science.md; saved diagnostic counts and
frozen source hashes: review_140923_checks.json. Keep testing through the
Monday deadline; the user removed the arbitrary telemetry-token review gate.

## September 12, 16:36 review — neutral movement prediction screen

Freshplayer completed all 16 games with terminal HUD/oracle agreement and no
exclusions. W5–25 oracle NET delta +0.06837, whole-game bootstrap 95% CI
[-0.09812,+0.21604]; deaths +0.06188/wave and score +3256.03/wave. No confirmation
or promotion. Highest wave W36. HUD missed 62 of 392 life-balance deaths.

All 116,015 decision records are complete, with zero reconstructed blind-command
mismatches. Logging costs about 0.10 ms/decision, with zero overruns. Death-window
proximity labels mostly identify projectiles, but are not killer attribution.
There are 308 baseline reacquisitions after at least 300 ms neutral, while the
brain retains its obsolete movement direction for player prediction. New opt-in
ROBOTRON_NEUTRAL_LEAD_RESET=1 clears only that direction on reacquisition after
sustained neutral; no enemy/FSM reset, navigation change or watchdog.

Queued weekend_neutrallead_screen_20260912: independent production Xenia 8/arm,
W40, max 4h, review afterward. 15 production, five tracking/default-parity and
four supervisor tests passed. Gameplay remains supervisor-owned; defaults,
dev brain_yolo and preexisting edits preserved. Details and next gates:
logs/weekend_20260912/review_163600_science.md. Metric/diagnostic artifacts:
freshplayer_audit_1636.json and freshplayer_decisions_1636_v2.json in that folder.
Continue useful authorized tests through Monday 09:00; this null screen does
not complete the weekend.

## September 12, 19:09 review — below-cap startup contamination

Neutrallead has 16 actual terminal outcomes matching oracle, but one baseline
attempt also logged a phantom W11/S0 game from intro art. Strict audit accepts
7/8 games: W5–25 NET +0.132825, whole-game 95% CI [-0.068907,+0.311991]. A
separately labeled sensitivity including the continuous oracle trajectory of
the contaminated attempt gives +0.135885 [-0.060769,+0.300699]. Neither meets
the confirmation gate; no promotion. Highest W33; HUD missed 84/410 deaths.

The cold-start production wrapper now requires stable W1/small-score acquisition
before other waves and rejects multiple telemetry games as incomplete. The
180-second startup-only guard and production gameplay defaults are unchanged.
Offline raw-HUD replay passes all 80 streams from five completed screens with
one terminal event and matching wave/score. Eighteen production, five tracking
and four supervisor checks pass. Original artifacts/dev brain_yolo preserved.

Queued weekend_startupverify_20260912: default-gameplay A/A infrastructure
verification, Xenia 2/arm W40, max 1.25h, review afterward. No direct gameplay
launch. Continue useful tests after verification, not another efficacy retry
of the inconclusive neutrallead knob. Detailed evidence, saved diagnostics,
replay caveats and next gates: logs/weekend_20260912/review_190937_science.md.

## September 12, 20:17 review — startup passes; visual death-window collection

The repaired startup wrapper passed all four live verification games: W38,
W24, W37 and W17, one terminal game each, W1/S0/three-life oracle starts,
verified HUD progress and matching terminal HUD/oracle wave/score. No exclusions.
HUD missed 25 of 127 life-balance deaths. This was default-gameplay A/A, not a
policy gain; do not pool it into neutrallead or promote anything.

Added opt-in ROBOTRON_VISUAL_DIAGNOSTICS=1 in the production test wrapper.
It archives the image that produced each vision observation, before another
capture, and returns the same observation. A four-frame queue moves JPEG/hash
work off the inference thread; saturation drops diagnostics. Each enabled game
is bounded at 2 GiB / 48,000 images. Images join decisions by sampled_at; oracle
death-window joins remain offline and never feed the policy. Added an offline
window-extraction CLI and documented it in ../robotron/SCRIPTS.md. Gameplay,
dev brain_yolo.py, supervisor controls and managed files were preserved.

22 production, five tracking/default-parity and four supervisor checks passed;
launcher parses. Final offline 30Hz check saved all 150 1280x720 images, zero
drops/errors; median submission 0.152ms, p95 0.213ms. This does not establish
live recording overhead. Startup traces contain 39,413 complete decisions;
76/123 approximate death events have nearest-projectile labels, 59/123 occur
near walls. Neither label identifies the killer; continuous visuals are needed.

Queued weekend_visualtrace_verify_20260912: Xenia 2/arm W40, 1.5h bound,
default gameplay both arms, recorder enabled only in visualtrace. This is an
A/A recording/overhead check and death-window collection, not efficacy testing.
Review strict complete games, archive coverage, cadence and chronological
death sequences before choosing a new preventable-cluster policy hypothesis.
Keep testing through Monday 09:00. No direct gameplay launch or production
promotion. Details: logs/weekend_20260912/review_201740_science.md;
startupverify_audit_2017.json, startupverify_decisions_2017.json and
review_201740_checks_v2.json are the saved audit/check artifacts.


## September 12, 21:26 review — death-window timing correction

Visualtrace completed four strictly verified games: base W19/S407300 and
W29/S740025; recorder W36/S934925 and W14/S291550. All terminal HUD/oracle
waves/scores agree; HUD missed 29/109 life-balance deaths. This was default
A/A, not efficacy: W5–25 NET +0.124756, whole-game 95% CI
[-0.445781,+0.577962]. No promotion. All 35,853 images saved with zero drops,
errors or truncation; all 17,596 consumed candidate timestamps have images.
Recorder submission averages <0.1 ms, with no control-loop overruns.

Critical diagnostic correction: all first 20 inspected post-W10 counter-relative
windows were already in the death animation. Life counters update about 1.7s
AFTER the visible motion-to-freeze transition. Prior nearest-threat/held-player
counts are not causal pre-impact evidence; whole-game NET remains valid.
Added an offline image phase audit and optional phase-aligned decision audit.
One visibly late onset is explicitly rejected, with original proposals preserved.
After rejection, 40 proposed pre-freeze windows have zero held-player samples,
23 nearest-projectile and 20 wall-proximity labels, versus 6 and 4 respectively
in 30 selected within-wave nondeath controls. These are descriptive observations
from two games; 19 onsets manually checked, 21 remain algorithmic proposals.
No preventable mechanism or policy gain is established.

Queued weekend_deathphase_holdout_20260912: Xenia 4/arm W40, 2.5h,
default gameplay, diagnostic recorder only in candidate, review afterward.
Validate frozen phase alignment and exposure across independent games before
choosing one targeted change. Do not turn this into repeated generic A/A
collection. Five relevant regressions passed; offline modules compile; default
audit aggregates and all 15 gameplay/recorder manifest hashes are unchanged.
Updated ../robotron/SCRIPTS.md. No direct gameplay, managed-state edits or
supervisor changes. Detailed artifacts and next-review gates:
logs/weekend_20260912/review_212613_science.md.

## September 13, 00:38 review — attract startup recovery and holdout audit

Deathphase holdout failed on attempt five: all 3,034 oracle headers stayed
W0/S0, while intro art read W11/W71. The HUD filter and 180-second startup
guard worked; initial A navigation had stopped on false gameplay detection.
Preserved the failure. Four completed games pass strict HUD/oracle checks:
W17/W28 controls, W22/W29 recorded; HUD missed 23/106 life-balance deaths.
Partial A/A NET +0.047730, whole-game 95% CI [-0.155246,+0.321659], deaths
+0.017345/wave, score +1626.89/wave. No efficacy evidence or promotion.

Production wrapper now retries A every five seconds before HUD acquisition,
maximum 30, and permanently disables retries on acquisition. Guard remains
180 seconds; no mid-game watchdog or Start/B escalation. Navigation actions
are saved separately. Raw-HUD mocked-pad replay adds zero presses to the four
normal games, 30 to the failed attract stream, and preserves its guard error.
Live recovery is unproven. Offline death auditing now handles empty gameplay
headers and labels incomplete attempts. 25 production, five tracking/parity,
four supervisor checks pass. Other 14 manifest hashes, including dev brain,
are unchanged. Managed state/status and supervisor controls untouched.

All 35,400 images and 17,362 consumed timestamps have full archive coverage.
Frozen phase method proposes 43 onsets, zero flags in 28 nondeath controls;
first five onsets per game visually accepted (ten total), 33 still algorithmic.
Counter delays 1.489–1.760s. Death windows show wall exposure 14/43 and nearest
projectile 18/43 versus 1/28 and 5/28 controls, zero held-player windows. This
replicates descriptive exposure but not a preventable policy error or killer.

Queued weekend_startuparetry_verify_20260913: Xenia 3/arm W40, max 2.5h,
default gameplay, candidate recorder enabled, review afterward. Six consecutive
games test the intermittent startup defect; inspect every startup action and
strict terminal outcome. Do not queue another blind retry or generic A/A
collection after it. Continue mechanism analysis from existing footage and
useful authorized tests through Monday 09:00. Detailed evidence and next gates:
logs/weekend_20260912/review_003842_science.md.

## September 13 01:15 PDT — root shutdown recovery

User caught another stall. `weekend_startuparetry_verify_20260913` saved one
strict terminal-agreeing game (baseline W28 / 710025, HUD deaths 27) at 01:02:29,
but its Python process remained live at 01:05:53 without more output. Root
requested its STOP; the local supervisor ingested it as incomplete. The monitor
itself was alive, waiting for its next scheduled review at 01:50. Earlier tests
finished; the six-game startup-verification batch did not. Preserve its data.

The virtual-pad strong-reference hypothesis did NOT reproduce: both retained
and explicitly released native pads exited normally in short subprocess tests.
Code inspection found the production CLI leaves its daemon inference thread
running after gameplay. Test wrapper now stops/joins that eye (5-second bound)
before closing visual diagnostics, explicitly releases pad and restores patched
classes. This repairs a real cleanup omission but does not prove the original
hang's cause. Delayed faulthandler traces now record post-result hangs.

New production_process helper, used by dev ab_yolo only for production tests,
adds a unique parent/child completion marker and a 45-second shutdown grace.
It preserves the result, logs shutdown failure, kills only its own child tree,
and aborts the batch for review on a hang. It does not change active gameplay.
Existing full-game timeout and cold-Xenia restart behavior remain. 29 production
unit/integration tests passed, including real normal/nonzero child exit,
post-result hang, and no-marker gameplay timeout. Helper included in source hashes.

Root queues `weekend_shutdownverify_20260913`: two games/arm, cap40, 1.5h,
default policy vs same policy with visual recording, review afterward. Four
full games verify normal game-over teardown and continued cold-start navigation;
do not claim repair until consecutive child exits are seen. No settings promoted.
Next review must inspect startup_actions, shutdown_trace and process error files,
then return to the phase-aligned mechanism work from review_003842_science.md.
Do not repeat generic diagnostic A/A batches once lifecycle verification passes.
Fresh-player NET +.0684 CI[-.0981,+.2160] was inconclusive. Neutral-lead screen
had a positive point estimate with CI crossing zero and an invalid startup
attempt; it is not a proven gain. Overall W100 remains unachieved.

## September 13 01:28 PDT — active stall watch

Root is watching shutdown verification through the first game transition.
Decision and oracle streams remain fresh through W35. Found a separate recovery
bug by tracing failure code: a nonzero A/B exit could leave its Xenia descendant
alive; finish() cleared ownership and foreign_gameplay() then blocked review.
Supervisor now reaps recorded descendants only after the owning batch exits,
validating PID plus creation time. Running batches and reused PIDs are untouched.
Six supervisor checks passed, including these two cleanup cases.

The idle-reload helper now bridges that same orphan gap using its last observed
job identity while waiting for the old monitor to become idle. It will load the
updated monitor only between batches/reviews. No gameplay files or settings
changed during this game. A hidden helper is being started for this handoff;
check deadline_extension.json for its status. Existing Monday 09:00 deadline,
review limits, and shutdown timeout remain unchanged.

September 13 01:30 PDT live follow-up: shutdown-verification game 1 ended
normally at W39 / 966950. Terminal oracle agrees; original interpreter PID47840
exited, shutdown trace is empty, A/B cold-restarted Xenia and game 2 reached W3
with fresh headers and decisions. This verifies ONE normal shutdown/restart,
not the full four-game batch or the cause of the earlier hang. The local
30-second monitor and new 45-second post-result limit are active. Idle reload
helper actual PID39332 waits for batch/review completion to load orphan cleanup.

## September 13, 05:59 review — player-boundary parity screen

Shutdown verification passes all four complete games (W39/W16 controls,
W18/W29 recorded), with strict initial/terminal HUD-oracle agreement, four
completion markers, empty shutdown traces and no shutdown errors. One game
used one startup A retry before acquisition and then completed normally.
HUD missed 24/113 life-balance deaths. Diagnostic A/A NET -0.051673, whole-game
95% CI [-0.385500,+0.392976]; no efficacy conclusion or promotion.

The 01:54 review hit an actual usage limit after leaving a player-boundary
experiment unfinished. Reused its diagnostics and finished validation. The
production planner's inherited inset predicts a wall-pinned player ten pixels
inward. Independent latest-game video gives 21 selected stable-command samples:
mean inset forecast error 10.103 px versus calibrated-boundary 0.584 px. An
offline video-only replay reproduces 4,799/4,799 baseline decisions; changing
only the player rectangle changes 131, including decisions in 7/11 proposed
death windows. These are geometry/sensitivity findings, not avoided deaths.

Queued weekend_playerbounds_screen_20260913: production Xenia 8/arm, W40,
max 4h, VSEARCH_PLAYER_FULL_BOUNDS=1, review afterward. Default remains off;
enemy dynamics and gameplay defaults unchanged. No generic A/A rerun, shell
reflection experiment or direct gameplay launch. All 16 prior manifest hashes
match, including dev brain_yolo; launcher now also hashes production planner,
coordinate transform and FSM. Four player-geometry, seven collision, five
tracking, 29 production and six supervisor checks pass; launcher parses.
Scripts documented in ../robotron/SCRIPTS.md. Detailed evidence and next gates:
logs/weekend_20260912/review_055938_science.md. Continue useful testing through
Monday 09:00; W100 remains unachieved and no production change is promoted.


## September 13, 09:07 review — player bounds null; unique velocity associations

Player-boundary screen has 16 verified outcomes: 15 game-overs plus one baseline
capped alive at W41 after completing W40. All initial/final HUD-oracle checks and
16 child completion markers pass; no shutdown errors or startup retries. HUD
missed 140/510 observed life-balance deaths. Added opt-in capped-game accounting
to the offline auditor; no completed game data excluded from the primary band.
W5-25 NET delta -0.064069, whole-game 95% CI [-0.270792,+0.125941], deaths
-0.002716/wave, score -1669.62/wave. No qualifying gain or playerbounds retry.

Implemented opt-in ROBOTRON_VELOCITY_UNIQUE=1 for the ordinary (nonprojectile)
velocity tracker. Legacy matching can copy one old identity into several
current tracks; the candidate greedily assigns closest pairs one-to-one within
the existing gate. Projectile coasting/defaults unchanged. Video-only replay
reproduces all 24,753 baseline actions across three games, with 826 changed
candidate actions. Seven of 38 frozen proposed pre-freeze windows contain changes;
this is sensitivity, not true identity validation or avoided-death evidence.

Queued weekend_velocityunique_screen_20260913: production Xenia 8/arm W40,
max 4h, only the unique-association switch, review afterward. Five unique-match,
five tracking, 30 production and six supervisor checks pass; launcher parses.
Dev brain_yolo and other 19 manifest files preserved, production brain gets only
the new opt-in patch on existing edits. Detailed metrics, censoring, limitations,
artifacts and next gates: logs/weekend_20260912/review_090746_science.md.
Continue useful tests through Monday 09:00; no W100 claim or promotion.


## September 13, 12:03 review — velocity uniqueness null; static electrodes

Velocityunique has 16 strictly verified outcomes (15 game-overs, one control
capped alive at W41). All startup/terminal HUD-oracle checks, completion markers
and 141,518 saved decisions pass; no shutdown errors or startup retries. All
20 source hashes matched. HUD missed 106/468 life-balance deaths. W5-25 NET
+0.081262, whole-game 95% CI [-0.111719,+0.288073]; deaths -0.042970/wave,
score +957.28/wave. No confirmation or promotion. Descriptive observed W1-40
NET is essentially flat (+0.000342); late exposure is sparse and conditional.

Two diagnostics did not justify tests: clipping spark coasting to player bounds
worsened selected detection consistency; exact repeated consumed observations
were rare during active play. Historical memory also confirms FIT harmful and
noshells/hunt60 flat; do not repeat those stale backlog entries.

New default-off ROBOTRON_STATIC_ELECTRODES=1 suppresses fictitious velocity of
stationary electrodes, preserving positions and every other class. Video-only
replay exactly reproduces 22,385 baseline decisions and changes 47 candidate
actions (39 in W5-25). None of 38 frozen proposed pre-freeze windows has an
altered action: this is a small modeling correction with low/uncertain expected
gain, not evidence of prevented deaths. No memory enters the policy.

Queued weekend_staticelectrodes_screen_20260913: production Xenia 12/arm, W25,
max 4h, review afterward. Require all 24 outcomes, cap-aware oracle audit and
independent confirmation gate; no direct gameplay launched. Three static-class,
five tracking, five unique-match and 30 production tests pass; launcher parses.
Dev brain_yolo/preexisting edits and supervisor controls preserved. Scripts
listed in ../robotron/SCRIPTS.md. Detailed evidence and next gates:
logs/weekend_20260912/review_120356_science.md. Keep useful tests moving through
Monday 09:00 PDT; W100 remains unachieved.


## September 13, 15:35 review — static electrodes null; projectile ordering

Static-electrode screen has 24 strictly verified outcomes: 11 game-overs and
13 W25 completions capped alive at W26 (five controls, eight candidates).
All startup/terminal HUD-oracle checks, child completion markers, 170,664 saved
decisions and 20 frozen source hashes pass. No shutdown errors or startup retries.
HUD missed 105/516 life-balance deaths. W5-25 NET +0.075773, whole-game 95% CI
[-0.103845,+0.269226], deaths -0.077689/wave, score -47.92/wave. Confirmation
gate fails; no static-electrode retry or promotion. First control reports
15.96 Hz; remaining games 14.95-15.00 Hz, with no overruns. All games retained.

New default-off ROBOTRON_COAST_CLOSEST_PAIRS=1 addresses a distinct projectile
association issue: detector order lets a weaker match consume a prediction
before a later box within five pixels. Two recorded games show 556 exposed
ticks and exposure in 13/38 frozen proposed pre-freeze windows versus 7/26
nondeath controls. These are prediction competitions, not identity truth or
killer attribution. Candidate reserves closest eligible pairs one-to-one;
ordinary tracker, gates, velocity formulas and ghost expiry stay as before.

Video-only replay exactly reproduces 18,431 baseline actions; candidate changes
1,350 decisions, including decisions in 23/38 proposed pre-freeze windows.
Changes are conditioned on recorded commands, not simulated avoided deaths.
Five new association tests, five tracking, five ordinary unique-match, three
static-class and 30 production checks pass. Dev brain_yolo and other 19 manifest
sources preserved. New replay CLI documented in ../robotron/SCRIPTS.md.

Queued weekend_coastpairs_screen_20260913: production Xenia 12/arm W25,
max 4h, only closest-pair switch, review afterward. Require all 24 audited
outcomes and independent confirmation if NET delta > +0.03 with positive
whole-game 95% lower bound. No direct gameplay or supervisor changes. Full
evidence and limitations: logs/weekend_20260912/review_153536_science.md.
Continue useful tests through Monday 09:00 Pacific; no W100 claim or promotion.

## September 13, 19:06 review — coast pairs null; detected-spark motion prior

Coastpairs has 24 strictly verified outcomes: 16 game-overs and eight W25
completions capped alive at W26 (four/arm). All initial/terminal HUD-oracle
checks, child markers, 170,064 decision rows and 20 frozen source hashes pass.
No startup retries or shutdown errors; cadence 14.97-15.00 Hz. HUD missed
118/531 life-balance deaths. W5-25 NET -0.005215, whole-game 95% CI
[-0.215276,+0.207772], deaths -0.002007/wave, score -180.55/wave. Close this
isolated ordering candidate; no qualifying confirmation or promotion.

New default-off ROBOTRON_SPARK_BIRTH_VELOCITY=1 seeds only newly created
detected spark tracks away from one visible Enforcer within 60 pixels, with
minimum eight-pixel separation and 12 px/tick speed prior. No virtual threats
or oracle input. Selected independent next-frame continuations show mean
error 19.87 -> 15.18 px across 101 cases; source identities remain inferred,
and some estimates worsen. Existing EMA/ghost lifecycle can propagate a bad
prior. This is a small, uncertain hypothesis, not a demonstrated policy gain.

Video-only replay exactly reproduces 21,975 baseline actions and changes 167
candidate actions, 137 in W5-25. Changes occur in 7/38 proposed pre-freeze
windows versus 1/26 selected nondeath controls. These are action sensitivity
counts conditioned on recorded commands, not prevented deaths. Three new
seed tests, five tracking/default-parity, five association and 30 production
checks pass. Initial system-Python cv2 import failure resolved using the
existing project virtual environment. Dev brain_yolo and other 19 manifest
sources preserved. Added replay CLI documented in ../robotron/SCRIPTS.md.

Queued weekend_sparkbirth_screen_20260913: Xenia 12/arm W25, max four hours,
only the spark-birth switch, review afterward. Require all outcomes, cap-aware
oracle audit and independent confirmation if NET > +0.03 with positive 95%
lower bound. No direct gameplay or supervisor/state/status changes. Detailed
evidence, limitations and next gates: logs/weekend_20260912/review_190645_science.md.
Continue useful testing through Monday 09:00 Pacific; W100 remains unachieved.

## September 13, 22:35 review — spark birth null; command-history player lead

Sparkbirth has 24 strictly verified outcomes: 14 game-overs and ten W25
completions capped at W26 (six controls, four candidates). All initial/terminal
oracle checks, child completion markers, 168,138 decision rows and 20 frozen
source hashes pass. No startup retries or shutdown errors. First control reports
15.70 Hz; others near 15 Hz, zero overruns. HUD missed 89/526 life-balance deaths.
W5-25 NET -0.063050, whole-game 95% CI [-0.218063,+0.092566], deaths
+0.037879/wave, score -629.27/wave. No confirmation, retry or promotion.

New default-off ROBOTRON_PLAYER_HISTORY_LEAD=1 substitutes half a tick of the
preceding sent command into the existing 1.5-tick player lead after turns.
Only two consecutive controlled sends qualify; blind reacquisition keeps its
existing behavior. Total lead and all enemy tracking stay as before. Selected
video-coordinate forecasts improve in four current controls and two separate
recordings; this is conditional prediction evidence, not avoided deaths.
Video-only replay reproduces all 22,053 baseline actions; 4,810 candidate changes,
including 32/38 proposed pre-freeze and 18/26 selected nondeath windows.

Three new command-history, five tracking/default-parity and 30 production checks
pass; launcher parses. All 18 other manifest sources, including dev brain_yolo,
are preserved. Scripts documented in ../robotron/SCRIPTS.md. Queued
weekend_playerhistory_screen_20260913: Xenia 12/arm W25, max four hours, review
afterward. No direct gameplay or supervisor/state/status changes. Full evidence,
limitations and confirmation gates: logs/weekend_20260912/review_223556_science.md.
Continue useful testing through Monday 09:00 Pacific; W100 remains unachieved.

## September 14, 02:00 review — player history null; confirmed projectile ghosts

Playerhistory has 24 strictly verified outcomes: 15 game-overs and nine W25
completions capped at W26 (six controls, three candidates). All startup/terminal
oracle checks, child completion markers, 164,601 decision rows and 20 frozen
source hashes pass. No startup retries or shutdown errors; cadence 14.95-15.01
Hz, zero overruns. HUD missed 82/530 life-balance deaths. W5-25 NET -0.125330,
whole-game 95% CI [-0.286093,+0.014191], deaths +0.088532/wave, score
-919.94/wave. No confirmation, retry or promotion.

New default-off ROBOTRON_COAST_CONFIRMED_ONLY=1 hides unseen projectile tracks
until a second associated detection. Internal tracks retain normal gates,
velocity update and expiry; all fresh detections and confirmed ghosts remain.
This targets stationary ghosts with no measured velocity, risking lost coverage
of real missed projectiles. Four recordings contain 465 single-sighting tracks
among 3,547 retired tracks; these are not certified false positives.
Video-only replay reproduces all 26,782 baseline actions; 98 candidate changes,
including changes in only 2/38 proposed pre-freeze and 1/26 selected nondeath
windows. Expected effect is small/uncertain, not prevented-death evidence.

Four new lifecycle, five tracking/default-parity, five association and 30
production checks pass. Scripts documented in ../robotron/SCRIPTS.md. Queued
weekend_confirmedghosts_screen_20260914: Xenia 12/arm W25, max four hours,
review afterward. No direct gameplay or supervisor/state/status changes. Full
evidence, limitations and confirmation gates:
logs/weekend_20260912/review_020005_science.md. Continue useful testing through
Monday 09:00 Pacific; no W100 claim or promotion.


## September 14, 05:32 review — confirmed ghosts positive; independent replication

Confirmedghosts has 24 strictly verified outcomes: 16 game-overs and eight
W25 completions capped at W26 (two controls, six candidates). All startup/
terminal oracle checks, child completion markers, 172,515 decision rows and
20 frozen source hashes pass. No startup retries or shutdown errors; cadence
14.96-15.00 Hz, zero overruns. HUD missed 91/532 life-balance deaths.
W5-25 NET +0.185921, whole-game 95% CI [+0.031038,+0.334994]; deaths
-0.146593/wave, score +983.21/wave (score CI includes zero). This passes the
predeclared confirmation gate, but is a selected nominal positive after many
screens. Absolute candidate NET remains negative; no promotion or late claim.

Video-only replay reproduces all 23,703 controlled actions in first/last games
of both arms with their respective frozen flags. No production fixes or source
changes were needed. Added one-off integrity/replay scripts are documented in
../robotron/SCRIPTS.md. Queue validation passes; all prior jobs preserved.

Queued weekend_confirmedghosts_confirm_20260914: production Xenia nine fresh
games/arm W25, max 3.15h, same isolated flag, review afterward. Size is limited
by Monday 09:00; expected runtime about 2h34 from the latest batch. Judge the
replication alone using the same NET > +0.03 and positive 95% lower-bound gate;
require all 18 outcomes and full audits. Do not pool discovery into confirmation.
No direct gameplay or supervisor/state/status edits. Continue useful authorized
work after its review if time remains. Full evidence and limitations:
logs/weekend_20260912/review_053217_science.md. W100 remains unachieved.

## September 14, 08:15 review — ghost gain not confirmed; final late diagnostic

Independent confirmedghosts replication has all 18 verified outcomes: nine
game-overs and nine W25 completions capped at W26 (five controls, four
candidates). All initial/terminal oracle checks, child completion markers,
133,530 decision rows and 20 frozen source hashes pass. No startup retries,
shutdown errors or overruns; cadence 14.96-15.00 Hz. HUD missed 109/417
life-balance deaths, unevenly across arms (72 control, 37 candidate).

Replication-only W5-25 NET -0.025568, whole-game 95% CI
[-0.185006,+0.129503]; deaths -0.047396/wave, score -1824.12/wave
(score CI [-3427.02,-69.00]). The independent confirmation gate fails.
Do not pool discovery into confirmation or repeat this isolated setting.
No promotion; candidate stays default-off. Video-only recorded-action replay
matches all 25,647 controlled actions across first/last games in both arms.

Queued weekend_latephase_baseline_20260914: production Xenia one game/arm,
W40 cap, max 0.5h, only ROBOTRON_VISUAL_DIAGNOSTICS=1 on the diagnostic arm.
Both arms use default gameplay. The existing six-game phase corpus contains
only three W36-40 proposals, all in one game; the final collection tests whether
the wall/projectile exposure pattern persists in fresh W26-40 footage. This is
descriptive baseline evidence, not an efficacy comparison. Require both complete
outcomes and archive/lifecycle checks; use the unchanged phase algorithm and
visually inspect every new late onset. Early deaths contribute zero late
exposure and must not trigger selective replacement. No further identical batch.

No gameplay or supervisor code, managed state or WEEKEND_STATUS edits; no
direct gameplay launch. Scripts documented in ../robotron/SCRIPTS.md. Existing
review scheduling may leave final artifacts pending audit at the hard 09:00
deadline; no extension. Full evidence, limitations and final-job gates:
logs/weekend_20260912/review_081556_science.md. W100 remains unachieved.

## September 14 final root audit — weekend ended

Supervisor stopped at 09:00:28 PDT; root verified no gameplay/monitor processes
at 10:35. No extension or restarted tests. Twelve isolated policy screens and
one independent confirmation produced no confirmed improvement or W100. Ghost
screen +.185921 NET did not replicate: -.025568, CI[-.185006,+.129503]. No promotion.
Final diagnostic W29 and W22 completed and passed source/lifecycle/header checks.
The image-recorded game died at W22, adding zero late-wave visual exposure.
Final synthesis and evidence: WEEKEND_RESULTS.md. Final saved-data audits are
final_latephase_audit_1035.json and final_latephase_checks_1035.json under the
weekend log directory. All gameplay remains stopped.
