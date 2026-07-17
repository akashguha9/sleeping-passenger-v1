# SIL Calibration Methodology — Leakage-Safe & No Auto-Promotion

`scripts/simulation_intelligence/calibration_harness.py` links SIL council
predictions to real forward outcomes and reports **honest** calibration. It
reuses the existing outcome/calibration infrastructure rather than duplicating it,
and it **never auto-promotes** an evidence grade.

## What is calibrated

The council is advisory (no buy/sell). The harness calibrates the council's
**defensiveness** against realized adverse moves — an advisory target. Each run
becomes an immutable `SILPrediction` with `predicted_adverse_prob` derived from
the aggregate vote (RISK_BLOCK 0.85 → WATCH 0.20, nudged by fragility), plus
`tail_warning` and `risk_block` flags and the observation `data_cutoff`.

## Leakage guards (all enforced + tested)

| Guard | Rule |
|---|---|
| **LOOKAHEAD** | outcome bars must be **strictly after** the observation cutoff; the entry bar is the first bar after cutoff (no same-day ambiguity) |
| **FUTURE_UNRESOLVED** | a window that has not fully elapsed by the session date is OPEN and excluded — no peeking at incomplete outcomes |
| **DUPLICATE** | predictions/outcomes de-duplicated by `prediction_id` |
| **IMMUTABLE_PRED** | `SILPrediction` is a frozen dataclass — it cannot be edited after its outcome is known (post-outcome-mutation guard) |
| **SYNTHETIC** | synthetic fixtures are never calibration-eligible (via `outcome_evidence.build_outcome`) |
| **OOS split** | the isotonic/Platt fit uses `calibration_map.fit_from_outcomes`, whose deterministic disjoint train/test interleave is the look-ahead guard inside the fitter |

## Metrics (`CalibrationCohort`)

Brier score, log loss, Expected Calibration Error, reliability diagram,
adverse base rate, **tail-warning precision & recall**, **false-risk-block rate**,
**missed-risk-block rate**, and an OOS isotonic/Platt fit. Status ladder:
`NO_DATA` → `LOW_SAMPLE` (<20) → `CALIBRATING` (<50) → `CALIBRATED` (≥50).

## No auto-promotion (the firewall)

The cohort reports a `proposed_evidence_grade` — what the evidence *would* support
— but `evidence_grade_applied` stays **`SIMULATED_ONLY`** regardless. Even with 60
resolved samples and `human_approved=True`, the applied grade does not change
automatically (tested, `test_calibration_no_auto_promotion`). Promotion above
SIMULATED_ONLY requires an explicit governance decision; nothing in the code path
raises a lens/run to `BACKTEST_DERIVED` / `EMPIRICALLY_CALIBRATED` / `MEASURED` on
its own. This is why the empirical-validation score stays low until real,
governance-approved evidence exists.

## Reuse map

- `outcome_evidence.build_outcome` (source `IMPORTED_BACKTEST`) → eligibility +
  quality firewall.
- `calibration_map.fit_from_outcomes` → leakage-safe OOS isotonic/Platt.
- SIL predictions already persist to `simulation_runs` (`run_id`,
  `parent_signal_id`, `data_cutoff`); outcomes link back via those ids.
