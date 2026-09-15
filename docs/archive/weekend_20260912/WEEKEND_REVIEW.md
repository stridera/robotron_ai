# Weekend Robotron review instructions

The user explicitly authorized this machine for unattended Xenia/MAME testing
through Monday September 14, 2026 at 09:00 Pacific, and requested periodic checks that keep work
moving. This file is the prompt for a bounded scheduled Codex review. Read
`logs/weekend_20260912/state.json`, `plan.json`, `WEEKEND_STATUS.md`, and the
latest completed job's artifacts first. Read RESUME.md/DAY_REPORT.md for history
as needed. Each invocation has a 15-minute outer limit. Work concisely; save a
useful result before that limit. Do not wait for long tests inside this review.

September 12 14:08 operator update: the user reports 80% account capacity
remaining with 4.5 hours until reset. The root supervisor removed its arbitrary
150k-token and six-review rolling-day gates, which had unnecessarily idled the
machine. Recorded token totals are telemetry, not a measured account quota.
Keep the 15-minute review bound, non-overlap, and failure/actual-limit cooldown;
use remaining capacity for useful tests. First read DAY_REPORT.md's twelve-hour
audit and the two *_audit_1330.json files instead of recomputing those audits.

Objective: improve video-only Robotron console play toward W100. No production
promotion without credible evidence. MAME is calibrated only for W5–25; late
game claims require real-vision Xenia. Existing sampled residual screen 144/arm
was inconclusive (NET +.01086, CI [-.03099,+.05506]); don't repeat it without a
new hypothesis. Seven repaired heuristic screens also found no convincing gain.
The user's latest direction is to USE THE REMAINING TIME FOR FURTHER TESTS,
including after the initial queue finishes or an improvement is found. Read
WEEKEND_TEST_PLAN.md for the research backlog. Do not treat an empty queue as
completion while useful authorized tests remain before Monday 09:00 Pacific.

The production timestamp comparison previously failed from test-rig lifecycle:
cold emulator starts worked but a replacement virtual pad did not restart a
game-over emulator. ab_yolo now restarts Xenia after EVERY production game,
and run_production_game has a startup-only 180-second HUD progress guard.
No mid-game watchdog: previous watchdogs harmed play. The first weekend job
verifies two full consecutive games; the next is an independent 8/arm timing
screen. Require completed games and audit HUD wave/score/deaths against saved
oracle headers. Memory is evaluation-only; never feed it into the policy.

You may diagnose/fix test infrastructure, analyze recordings, implement new
opt-in hypotheses, run short necessary offline tests, and append bounded jobs
to `logs/weekend_20260912/plan.json`. Do not launch long gameplay directly;
the supervisor exclusively owns those jobs. Do not change the supervisor's
deadline, review budget, model, or safety controls. Do not edit managed state.json.
Do not edit gameplay files while a gameplay job is running. The supervisor
starts reviews only between jobs. Preserve preexisting edits, especially dev
brain_yolo.py. Update ../robotron/SCRIPTS.md for added scripts.

Job schema: unique lowercase id, kind xenia or mame, games per arm, candidate
lowercase name (not base), settings (comma-separated ROOT/VSEARCH/FSM assignments
for Xenia; list of KEY=VALUE for MAME), max_hours <= 4, optional depends_on id.
Xenia: max_wave 6..100. MAME: seed (new independent integer), games <= 576.
All job log directories must be new; never reuse/overwrite a completed batch.
Append to the plan's `jobs` list; never remove or change completed jobs.
MAME candidate settings may include LAB_. Normally review after a job. To use
machine time efficiently within the review budget, one review may prepare a
small batch of 2–4 independent, predeclared screens sharing verified frozen
implementation. Set `review_after: false` on intermediate screens and true on
the last. Do not use this to bypass review of failures, confirmation gates, or
dependent experimental changes. A failed job always triggers review.

If a job failed, diagnose before queuing a revised retry with a NEW id. Preserve
the failure; no blind retry loops. You may append a replacement and change the
depends_on of an unstarted job to the successful replacement. Evaluate positive
screens with independent confirmation; compare NET and deaths/score separately,
and bootstrap whole games. A weak or partial result is not evidence of success.
Prioritize production parity and actionable death clusters over more blind tuning.

Review records may report errors, budget cooldown, or completed queue. If the
queue is empty, use the evidence to prepare the next useful experiment or small
screen batch rather than declaring the weekend finished because one knob failed.
If meaningful work truly needs user input, write a clear blocker. Never invent
results, claim W100 without a valid run, or repeatedly rerun the same failed test.

Do not upgrade/restart WSL or Windows, change machine/security/power settings,
install software, modify authentication, spend API money, send external
messages, commit/push/deploy, or contact the hardware owner. Use existing CLI
ChatGPT authentication. No subagents or recursive Codex invocations. Use this
single review session; scheduled retries belong to the supervisor.

Return a concise Markdown report: verified results, fixes/checks, new queued
job IDs, and remaining uncertainty. Keep WEEKEND_STATUS.md owned by the
supervisor; put detailed science notes in DAY_REPORT.md or a dedicated report.
