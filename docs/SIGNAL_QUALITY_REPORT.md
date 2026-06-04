# Signal Quality Report

`scripts/signal_quality_report.py` + `GET /api/signal-quality`. Advisory-only.

## Score
`SQ = 10·(0.25·C + 0.20·ECE_score + 0.15·Brier_score + 0.15·Coverage +
0.15·Feedback + 0.10·BehavioralTests)` where C maps calibration status
(NO_DATA 0 … CALIBRATED 0.8 real / 0.7 paper), ECE_score = max(0,1−ECE/0.20),
Brier_score = max(0,1−Brier/0.25), Coverage = securities S, Feedback grows with
reviewed recommendations, BehavioralTests = passed/expected.

## Caps
no real/paper outcomes → 7.0 · NO_DATA → 7.0 · fixtures-only → 7.0 ·
ECE>0.20 with n≥50 → 6.5 · no score contract → 6.0.

Outputs strongest/weakest bucket, over/under-confident buckets, and the next
data most worth collecting. Above 7.5 requires real calibrated evidence.
