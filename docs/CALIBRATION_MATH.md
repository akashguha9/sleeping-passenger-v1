# Calibration Math

`scripts/score_calibration.py :: compute_calibration_metrics(outcomes)` over
eligible OutcomeEvidence. BREAKEVEN modelled as `y = 0.5`. Score normalised:
`s = score/100` if >1 else `score`, clamped to [0,1].

## Buckets
[0.00,0.20) [0.20,0.40) [0.40,0.60) [0.60,0.75) [0.75,0.90) [0.90,1.00]
Per bucket: `confidence_k = mean(s)`, `accuracy_k = mean(y)`, avg (levered) return.

## Metrics
- ECE = Σ_k (n_k/n)·|acc_k − conf_k|
- MCE = max_k |acc_k − conf_k|
- Brier = (1/n) Σ (s_i − y_i)²
- LogLoss = −(1/n) Σ [y ln s' + (1−y) ln(1−s')], s' clamped by δ=1e-6
- Wilson 95% interval on win rate (z=1.96)
- Bayesian: α = 1 + wins + 0.5·be, β = 1 + losses + 0.5·be; mean = α/(α+β)

## Status
NO_DATA (n=0) · FIXTURE_ONLY (only synthetic) · LOW_SAMPLE (1–19) ·
CALIBRATING (20–49) · CALIBRATED (n≥50, ECE≤0.10, Brier≤0.25) ·
MIS_CALIBRATED (n≥50, ECE>0.10 or Brier>0.25).

`should_drive_sizing` is True only when status=CALIBRATED **and** real_n≥50
**and** a human has approved. Paper-only calibration is never real-grade.

## Feedback (advisory, never applied)
`calibration_recommendations.build_recommendation_from_metrics`: per-bucket
gap & FPR → bounded Δτ (η=0.10, FPR_target=0.35, |Δτ|≤0.10), n-weighted global
Δτ, confidence = min(1, √(n/50)·(1−ECE)). Categories OBSERVE_MORE_DATA /
LOW_SAMPLE_DO_NOT_ADJUST / TIGHTEN_THRESHOLDS / MAINTAIN_THRESHOLDS /
CONSIDER_MINOR_LOOSENING / MIS_CALIBRATED_REVIEW_REQUIRED. `applied`=False always.
