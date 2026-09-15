# Champion residual test — 2026-09-09

Question: can a small learned correction improve the current champion under
the calibrated vision defects, when trained on actual score/death economy?
Prior residual failures and the changed conditions are documented in DAY_REPORT.

Training: `logs/residual_net_20260909_v2`, 3M decisions (2.5-hour hard budget),
12 independent fresh-episode MAME workers, seed base 91026000. Policy only sees
processed sprites, their velocities, the champion's proposed controls, previous
movement, and analytic heading clearances. No memory identifiers or true-state
features. Reward is NET*25. The frozen trainer initially chooses keep/left45/
right45 with probabilities .98/.01/.01. Checkpoints every 200k decisions.

Evaluation plan, recorded before held-out gameplay:

1. Final greedy actor: a small fresh-game smoke run, inspect actual override
   counts. A model that never overrides cannot improve the baseline.
   A global negative logit bound (tanh hidden units plus final linear weights)
   can instead prove it is identically no-op and avoid redundant gameplay.
2. Final sampled actor: 144 valid games per arm versus the champion on independent
   seed base 91027000. Dedicated action RNG never consumes the defect RNG.
3. If NET delta > +0.03, independently confirm with 576 games per arm on seed
   base 91028000; require the 95% game-bootstrap lower bound above zero. Training
   reward and selected best waves do not qualify a model for promotion.
4. A convincing sampled-policy gain also needs comparison with the initial
   constant-probability actor to distinguish learned choices from random steering.
5. Xenia real-vision testing is required before any hardware recommendation.

All MAME results concern W5–25 only. Do not run Xenia alongside MAME. Do not
promote automatically. When time is limited, preserve the incomplete stage and
label it incomplete; do not turn a stopped job into a negative result.

September 10 recovery: the original process disappeared after logging 2,543,616
decisions, without a final model. Resume from its latest checkpoint (2,400,048)
in `logs/residual_net_20260910_resume`, same frozen policy source and optimizer,
new training seed base 91036000, cumulative target still 3M. The initial resumed
actor is bit-identical to the saved actor. In-flight episodes/rollout are not
recoverable; this is checkpoint continuation, not an exact replay of the lost
process. Held-out seeds and evaluation gates above remain unchanged.

Separately, the timestamp-aware production tracker will be compared against
production defaults through the actual hardware-sim loop, interleaved on Xenia.
HUD bookkeeping supplies the per-wave log; an independent read-only memory
header log audits it, and never supplies policy input. Each game has separate
telemetry. Focus ownership is guarded by the existing supervisor.
