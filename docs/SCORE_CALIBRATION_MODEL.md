# Score Calibration Model

The signal scores are hand-tuned weights (`config/thresholds.yaml`). They are
**not empirically calibrated** until enough reconciled outcomes exist. This
model labels that honesty; it does not fabricate calibration.

## Status ladder (`scripts/score_calibration.py`)
By resolved-outcome sample size (WIN/LOSS/BREAKEVEN; UNKNOWN excluded):
- `0` → **UNCALIBRATED**
- `1–19` → **LOW_SAMPLE**
- `20–49` → **CALIBRATING**
- `≥50` → **CALIBRATED**

Summary fields: `total_reconciled`, `win_rate`, `false_positive_rate`
(loss fraction of resolved), `average_realized_return`, `sample_size`,
`confidence_bucket`, `calibration_status`, `score_should_drive_sizing`.

## Score output contract (`scripts/score_output_contract.py`)
Any score-bearing response carries: `raw_score`, `calibrated_score`
(None unless CALIBRATED **and** human-approved), `calibration_status`,
`sample_size`, `should_drive_sizing` (False unless calibrated + human-approved),
`warning`, `human_review_required=True`, `advisory_only=True`.
Surfaced on `/signals` (`score_contract`) and `/api/score-calibration`;
rendered by the `ScoreCalibrationBadge` ("Do not size from this score").

## Feedback loop (`scripts/calibration_recommendations.py`)
Reconciled outcomes (and Moltbook cases) feed a **guarded** recommendation:
`OBSERVE_MORE_DATA` (no data) → `LOW_SAMPLE_DO_NOT_ADJUST` (<20) →
`RECOMMEND_TIGHTEN` (high false-positive) / `RECOMMEND_LOOSEN_SLIGHTLY`
(strong win-rate) / `RECOMMEND_MAINTAIN`. **Never auto-applied**
(`applied=False`, `auto_apply=False`, `human_review_required=True`).
Surfaced on `/api/calibration-recommendations`.

## Hard rule
No precise score is presented as sizing-grade unless status is CALIBRATED and a
human has approved sizing. Year-1 priority is survival and evidence, not PnL.

## Tests
`tests/test_score_calibration.py`, `…_api.py`,
`tests/test_score_output_contract.py`, `tests/test_calibration_recommendations.py`.
