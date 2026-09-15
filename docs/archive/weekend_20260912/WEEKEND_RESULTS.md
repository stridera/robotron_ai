# Weekend result — September 14, 2026

The weekend did not establish a gameplay improvement and did not reach W100.
No experimental setting is promoted. The supervisor recorded its final stop at
09:00:28 PDT, within its 30-second polling interval. At 10:35 PDT, root verified
that the supervisor and all Xenia/production gameplay processes were gone.
No testing was restarted or deadline extended; subsequent work was saved-data analysis.

Twelve isolated gameplay changes were screened, and the strongest positive
received a separate confirmation. Most initial comparisons used 8–12 games per
arm; these small screens leave substantial uncertainty about modest effects.
The nominal positive after many screens was not treated as a reliable win.

| Confirmed-projectile-ghost policy | Games | NET difference, lives/wave | Whole-game 95% interval |
|---|---:|---:|---|
| Discovery | 24 | +0.185921 | [+0.031038, +0.334994] |
| Independent confirmation | 18 | -0.025568 | [-0.185006, +0.129503] |

This option stops extrapolating unseen projectiles after only one detection;
it requires a second associated sighting before retaining an unseen track.
The confirmation fails the predeclared benefit gate. Baseline NET was -0.109646
versus candidate -0.135215 in W5–25. The candidate's estimated deaths fell
0.047396/wave, but score income fell 1824.12/wave. Discovery and confirmation
were not pooled to rescue the result. The option remains off.

Earlier timing, reset, player-position, velocity, electrode, association,
projectile-birth and command-history changes did not produce a confirmed win.
These results do not establish impossibility; they do not support installing
any of these isolated options as an improvement either. Late-wave causal
coverage remains sparse, and most recent efficacy screens were capped at W25.

The final diagnostic completed both games: default W29 / 722925 and visually
recorded default W22 / 567900. Root audited both saved games after the deadline:
initial/terminal headers pass, both process markers exist, all 20 source hashes
match, decision summaries show 17,545 written records without errors/truncation,
and no startup retries or delayed shutdown traces occurred. HUD missed six and
three life-balance deaths respectively, so HUD-only scoring remains unsuitable.

The recorder wrote all 16,114 frames with zero drops/errors/truncation; its
index ends at the actual archive size. Its game ended at W22, so the final job
adds no W26–40 visual exposure. No new late-window images require certification,
and no late survival/efficacy conclusion can be drawn from this diagnostic.
The W29 control did not record images. No selective replacement was run.

Evidence:
- logs/weekend_20260912/review_053217_science.md
- logs/weekend_20260912/review_081556_science.md
- logs/weekend_20260912/final_latephase_audit_1035.json
- logs/weekend_20260912/final_latephase_checks_1035.json
- logs/weekend_20260912/state.json

Operational progress: shutdown/restart verification passed, subsequent serial
batches and reviews progressed through the deadline, and completed artifacts
are preserved. This infrastructure improvement is separate from gameplay efficacy.
