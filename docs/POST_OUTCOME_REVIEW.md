# Post-outcome review loop

Tooling: `scripts/review_signal_outcomes.py` (proofs:
`tests/test_post_outcome_review.py`). The loop closes the circle the
journal opens: every advisory signal that resolved gets scored on what
actually happened, and the lessons feed the next scorecard review.

## What each review measures

| Question | Field / math |
| --- | --- |
| Did the thesis play out? | `thesis_played_out` (y ∈ {0,1}) |
| Was confidence calibrated? | `Error_i = y_i − p_i`, `AbsoluteError_i = |y_i − p_i|`; gap ≥ 0.3 flagged over/underconfident |
| Outcome vs expectation | `PredictionError_i = R_actual − R_expected` |
| Outcome vs benchmark | `excess_vs_benchmark`; positive return under the benchmark is flagged — the index did it for free |
| Was evidence stale? | `evidence_age_days_at_decision > 14` |
| Should it have abstained? | sensitivity `ABSTAIN` recommendation + failure ⇒ `should_have_abstained` |
| Over-weighted feature? | `dominant_feature` + failure ⇒ lesson |

Aggregates: `MAE = (1/N) Σ |PredictionError_i|`,
`Bias = (1/N) Σ PredictionError_i` (|bias| > 2% per signal flags a
systematic optimism/pessimism drift), stale-evidence rate, thesis hit
rate, deduplicated top lessons.

## Cadence (see MODEL_GOVERNANCE.md)

Each decision memo carries a `Post-decision review date`; review the
signal then — not when you happen to remember it (that's how
survivorship sneaks into your own memory). Monthly, run the aggregate
over everything resolved and write the lessons into the moltbook.

## Honesty rules

- Review every resolved signal, including the embarrassing ones; the
  reconciliation queue exists so none go quietly missing.
- A lesson is a hypothesis, not a rule: it earns weight through the same
  minimum-evidence ladder as any new signal.
- All review output is advisory and feeds a human; nothing here adjusts
  weights automatically.
