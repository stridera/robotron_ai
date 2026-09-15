# Overnight Robotron results — audited after reboot

**Daytime update: all seven screens have now been completed at 144 valid games
per arm.** The small score decreases were confirmed as non-atomic BCD carry
reads. After an exact-replay pilot, rejected seeds were replayed with a bounded
measurement filter and frozen policies. Results: no variant demonstrates a gain.
Completed artifacts: `logs/score_repair_20260909`; see [DAY_REPORT.md](DAY_REPORT.md).
The account below preserves what actually finished overnight, before repair.

**The queue stopped at 3:09 a.m. PDT, before Windows rebooted at 3:32 a.m.**

All seven smoke comparisons completed. All seven full screens stopped at their
rejected-episode limit, short of the planned 144 valid games per arm.
No 576-game confirmations or Xenia follow-up ran. Production is unchanged.

| Variant | Usable baseline / candidate games | Partial NET change |
|---|---:|---:|
| turn1 | 131 / 140 | -0.3369 |
| turnguard | 131 / 136 | -0.1717 |
| turncommit | 126 / 141 | -0.2705 |
| shot2 | 131 / 135 | -0.0262 |
| shot4 | 133 / 132 | +0.0004 |
| fan12 | 130 / 133 | -0.0177 |
| fan24 | 128 / 140 | -0.1159 |

1,867 usable full-screen games were saved, with 149 rejected attempts.

These are incomplete, selectively filtered samples. The uncertainty intervals in
each `partial_summary.json` do not account for exclusion bias. They are diagnostic
results, not reliable promotion evidence. Turning variants point worse; the shooting
variants and smaller velocity fan show no clear gain in the retained sample.

The score guard rejected every observed decrease, including 366,875 → 366,800
at W17. Such small decreases may be transient reads during score updates; the
earlier 41,242,365-point corruption is a separate, clearly invalid value.
The guard needs diagnosis before using additional gameplay to complete these tests.

The original automatic report incorrectly said "finished" and "no screen met the
entry threshold." The queue had exhausted its stages, but the stages had failed.
Original state/report are preserved in `logs/night_20260909/*_before_audit.*`.

The prior two-step turning screen did complete after replacement of its corrupt
episode and showed NET −0.2033 versus baseline. Default settings remain unchanged.
