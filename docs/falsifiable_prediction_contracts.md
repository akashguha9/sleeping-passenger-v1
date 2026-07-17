# Falsifiable Prediction Contracts

Every Decision Twin freezes a bounded set of `FalsifiablePrediction`s
(`decision_twin.py`) — resolvable, immutable, non-vague.

## Fields
`prediction_id, twin_id, candidate_id, parent_signal_id, info_cutoff,
target_variable, kind (PROBABILITY|INTERVAL), probability|interval_[low,high],
outcome_window_days, benchmark, resolution_method, invalidation_condition,
evidence_grade, calibration_cohort (regime key), immutability_hash, status`.

## The five frozen predictions (price-resolvable)
1. `adverse drawdown <= -5% within window` (PROBABILITY)
2. `tail drawdown <= -10% within window` (PROBABILITY)
3. `forward return > 0 at window` (PROBABILITY)
4. `realized max drawdown in band` (INTERVAL)
5. `realized daily volatility in band` (INTERVAL)

When there is no price history, the twin **refuses** to predict rather than emit a
vague target (tested: `test_twin_refuses_prediction_without_price`).

## Immutability + no retroactive redefinition
Each prediction is a frozen dataclass with a content hash. The target is fixed at
freeze time; resolution (`outcome_resolution.py`) computes the realized value from
forward prices and never edits the prediction. Two builds from identical inputs
produce identical hashes (tested: `test_prediction_hash_integrity`).

## Resolution status lifecycle
`FROZEN → RESOLVED` (window elapsed, outcome recorded) or stays `FROZEN` until due.
`persistence.record_prediction_outcome` marks the row RESOLVED and writes a
separate `prediction_outcomes` row — the frozen prediction is untouched.
