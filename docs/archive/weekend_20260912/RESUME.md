# Operational handoff — September 10, 2026

User requests continued unattended MAME/Xenia testing, and a graceful pause
before the chat usage limit. Exact remaining account quota is not visible.
No production settings have been promoted; no new W100 result.

## Capacity correction — September 12, 14:08 PDT

User reports 80% remaining capacity with 4.5h until cycle reset. Removed the
supervisor's arbitrary 150k-token and six-review rolling-day gates; they were
not account limits and had caused unnecessary idle time. Reviews remain serial,
15-minute bounded, with existing cooldown after completion/failure. Raw usage
is still recorded. The next pending review is eligible immediately after the
monitor reload. Previous notes about waiting until Sunday 02:58 are superseded.

## Latest audit — September 12, 13:30 PDT

Three complete 8/arm comparisons (48 games) are done. Oracle-audited NET:
timing -0.10954 CI [-0.24322,+0.02196]; death reset +0.05958 CI
[-0.11247,+0.21339]; wave reset +0.06895 CI [-0.07519,+0.21528]. No proven gain.
New offline audit files: logs/weekend_20260912/{deathreset,wavereset}_audit_1330.json.
See DAY_REPORT.md twelve-hour audit for means, component metrics, and HUD errors.
All 32 reset-screen games passed the header audit; no exclusions/capped survivors.

Supervisor is alive, deadline extension loaded, currently waiting on its own
150k rolling-day review-token gate after two reviews used 183165 uncached/output
tokens. No reported account rate-limit error. Gameplay idle since ~10:50;
automatic review eligibility returns ~Sunday 02:58 PDT. Do not report it as
actively playing. Preserve budget and results; no blind reruns of these screens.

## Weekend automation — September 12, 00:42 PDT

Latest user steering (September 12): extend through Monday September 14 at
09:00 Pacific, and keep preparing further useful tests after the initial queue
or an improvement completes. WEEKEND_TEST_PLAN.md records the research backlog;
scheduled reviews may prepare small batches of independent screens to keep the
machine productive within the unchanged review budget. The restart verification
passed and the full timing screen is running.

Both scheduled-task trigger end times and its runtime allowance are extended.
The monitor source is updated; helper PID 24072 waits for the current job to
exit before reloading only the monitor. This avoids interrupting gameplay.
Handover status: logs/weekend_20260912/deadline_extension.json. Until the reload,
the live status page may still display the old Sunday deadline. The updated
source and scheduled task use Monday 09:00. Do not kill the active test to reload.

USER AUTHORIZED THE WHOLE WEEKEND and explicitly requested a cron/loop to
keep work progressing. Windows Task Scheduler task `RobotronWeekend20260912`
is installed and running as the current logged-on user, limited privileges.
It launches `tools/weekend_supervisor.py`, which checks every 30 seconds;
the scheduled task retries every 5 minutes and at user logon if the supervisor
is absent. Deadline extended by user to Monday September 14, 09:00 Pacific. No Windows/WSL restarts,
updates, power settings, authentication, or global model config were changed.

Authoritative status: WEEKEND_STATUS.md and logs/weekend_20260912/state.json.
Initial supervisor PID 6744; validation batch PID 37688 (now complete). Always verify
identities, since PID reuse is possible. Plan contains two consecutive full
games, then an independent 8/arm timing screen ONLY if the validation passes.
Fresh Xenia after every production game is now implemented and tested. The
startup-only HUD guard fails after 180 seconds without progress and is disabled
after W2; no mid-game watchdog. Explicit per-game result.json markers plus
oracle terminal agreement guard stage completion.

After a failure or completed screen, the supervisor runs one bounded Codex
review (15-minute maximum, never alongside gameplay), which diagnoses results,
can repair infrastructure/prepare opt-in hypotheses, and appends new bounded
jobs. Review instructions are WEEKEND_REVIEW.md. No inferred daily quota gate;
observed uncached-input+output tokens remain logged, at least an hour between
successful reviews, four-hour cooldown after failure including usage limits.
No recursive agents, automatic promotion, external messages, or deploys.
Codex CLI connectivity and read-only filesystem access were verified with the
existing ChatGPT login. Global config's old gpt-5.4 was unsupported; ONLY the
scheduled invocation selects gpt-6-astra, matching this chat.

STOP: create logs/weekend_20260912/STOP. The supervisor stops owned work and
subsequent scheduled launches exit without starting jobs. Disable the named
scheduled task as well if you want the five-minute checks removed. Interactive
Xenia needs the Windows user session logged on; the logon trigger resumes checks
after a reboot/login, without unattended login or system changes.
Do not manually launch duplicate tests while this supervisor is active.
Previous dated notes below are historical.

## September 11 audit — incomplete Xenia batch

Nothing is running as of 13:47 PDT. `production_timing_20260910` stopped at its
2.5-hour deadline September 10 around 19:44. Only 3 of 16 games completed:
baseline W25/571125 and W23/509300; timed W18/420575. Too few for a comparison.
The independently logged oracle confirms those terminal waves and scores.
Attempts 2 and 4 each sat at the preceding game's final state for the entire
3600-second timeout; attempt 6 did so until the batch deadline (265 seconds).
All had lives=4294967295 (game-over sentinel), unchanged score/wave. Cold Xenia
launches played successfully; attaching a new production process after game
over failed to restart. This is navigation/controller lifecycle failure, not
evidence that the timed policy stalled during gameplay, nor a focus failure.

Next: fix production batch game restart (fresh Xenia per production game is
the simplest isolated test-rig fix), verify two consecutive fresh games and
shorten startup-only failure handling before scheduling another full batch.
Do not add the previously rejected mid-game watchdog or change gameplay policy.
Audit HUD deaths against oracle lives/score before interpreting partial metrics.
Previous active-stage notes below are historical.

## Active Xenia comparison — September 10, 17:14 PDT

The pending production timing A/B is now running in
`logs/production_timing_20260910`: 8 games/arm, cap W40, 2.5-hour limit (about
19:44 PDT). Supervisor PID 2312; verify before acting. Read its `status.txt`
and `run.log` as authoritative status. Stop file is that directory's `STOP`.
Default versus `ROBOTRON_TRACK_TIME=1`, actual production video/controller loop.
Xenia acquired focus and the virtual pad initialized; first game reached W4
at 17:15 with HUD per-wave records and independent oracle headers both writing.
No gameplay conclusion yet. MAME has no remaining running process.

Exit-code failure reproduced in redirected Windows and WSL children: both 0
and 7 became null without retaining Process.Handle, and both were correct with
it retained. Applied fix to both supervisors; focus tests passed. An initial
launch under the old `production_timing_20260909` name failed before launching
the game because Start-Process inherited PowerShell 7's module search order
into PowerShell 5.1. Child scripts now prioritize their own built-in modules;
no machine settings changed. Failed preflight logs preserved under the old name.
The morning and earlier notes below are historical.

## Morning status — September 10, 10:46 PDT

Nothing is running. The sampled MAME screen DID complete at about 01:14:
144 valid games per arm, 6 rejected attempts replaced. NET delta +0.01086
lives/wave, 95% game-bootstrap CI [-0.03099, +0.05506]. Mean maximum wave
22.02 baseline versus 22.88 sampled. This W5–25 proxy result does not meet the
predeclared +0.03 confirmation entry threshold and establishes no improvement.
The supervisor stopped with `MAME stage exited .` after the result was written
(empty process exit status); all 288 valid game subprocess exit codes were zero.
Xenia was NEVER started. Repair the supervisor's process exit-status handling
before reusing it. Preserve the completed MAME result; do not repeat this screen
merely because the queue failed. The remaining comparison is production Xenia
timestamp tracking. Earlier live-stage notes below are historical.

Latest verified stage at 00:54 PDT: training completed 3,002,160 decisions in
586 seconds of resumed training. Final files `final_model.zip` and
`actor_final.npz` are saved. Final greedy action is globally proven identical
to the champion. The 144/arm sampled-actor held-out comparison has started in
`logs/residual_sampled_screen_20260909`; result still pending. Do not restart
training or duplicate that evaluation. Xenia follows the MAME stages.

At the graceful chat pause (00:55 PDT), 8 baseline and 6 sampled games had
completed, all valid. The first inspected sampled episode applied 37 corrections
in 3,235 decisions, confirming the actor is active. No performance conclusion
from this partial sample. Queue is continuing unattended; inspect its state
and final summaries on the next turn. Evaluation versus training lab source
diff was audited: only optional actor sampling/RNG setup differs; the gameplay
generator is identical. Training/export tests and focus guard tests passed.

At 00:42 PDT no old trainer, supervisor, or gameplay processes remained. Old
`running:true` files were stale. Host boot time was September 9 03:32; cause of
the later process loss is unknown. WSL started on the first inspection command;
no upgrades or restart commands were issued.

Training resumed at 00:44 PDT using `tools/train_champion_residual.py --resume`
from `logs/residual_net_20260909_v2/model_2400048.zip`. New run:
`logs/residual_net_20260910_resume`; cumulative 3M target, 12 workers, new seed
91036000, 45-minute limit, checkpoint every 200k. Initial actor arrays verified
bit-identical to the old checkpoint. Windows launcher PID 36868 (verify current
command before acting; PID reuse is possible). The previous run logged 2.54M
but only 2.40M was checkpointed. Frozen old gameplay source is reused.

Queue: `logs/resume_queue_20260910/state.json` and `logs/day_active.json` are
the live stage pointers. Supervisor Windows PID 30100, started 00:46 PDT,
deadline 03:46 PDT. It waits for training, audits the final
actor, runs the predeclared 144/arm sampled screen (576/arm only if eligible),
then the actual production Xenia timestamp A/B. Maximum queue duration 3 hours.
Artifacts keep the names declared in RESIDUAL_EXPERIMENT.md, including date 20260909.
Always verify live processes as well as state files before launching anything.

Stop gracefully: create `STOP` in the active queue directory. If Xenia has
already started, also create `logs/production_timing_20260909/STOP`. Training
accepts `logs/residual_net_20260910_resume/STOP`; MAME uses its own run's STOP.
Do not run multiple MAME batches (shared ports), nor MAME alongside Xenia.

Read DAY_REPORT.md for the repaired seven screens: all 2016 games valid,
no candidate passed. RESIDUAL_EXPERIMENT.md defines the held-out test gates.
Optional production `ROBOTRON_TRACK_TIME=1` is still off by default. Relevant
offline training/export checks passed; gameplay evidence remains required.

Useful checks from Windows PowerShell:

```powershell
Get-Content logs/day_active.json
Get-Content logs/resume_queue_20260910/state.json
Get-Content logs/residual_net_20260910_resume/status.json
Get-Content logs/residual_net_20260910_resume.console.log -Tail 20
Get-CimInstance Win32_Process | Where-Object CommandLine -Match 'train_champion|run_evening|ab_yolo|run_production' | Select-Object ProcessId,Name,CommandLine
wsl -d Ubuntu --exec pgrep -af mame
```

Windows Python: `C:/Users/strid/code/.venv/Scripts/python.exe`.
WSL Python: `/home/strider/Code/robotron-rl/.venv-collision/bin/python`;
ML training needs `PYTHONPATH=/home/strider/Code/robotron-rl/.venv/lib/python3.12/site-packages`.
Use `wsl --exec` for commands with regex/metacharacters so WSL does not parse a shell pipeline.
Preserve preexisting developer edits, especially sibling `robotron/brain_yolo.py`.

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
