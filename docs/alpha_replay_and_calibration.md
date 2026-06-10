# Alpha Replay Harness and Calibration Limits

Advisory-only. Replay metrics measure historical advisory **signal
quality** — whether the engine's classifications were later confirmed
by observable facts. They are not performance results, not backtested
returns, and imply nothing about future outcomes.

## Record shape

```json
{
  "signal_id": "...",
  "as_of_date": "...",
  "theme": "...",
  "ticker": "...",
  "opportunity_score": 0,
  "confidence": 0,
  "verdict": "...",
  "event_probability": 0.0,
  "predicted_narrative_persistence": 0.0,
  "trap_flags": [],
  "subsequent_observation_window_days": 30,
  "observed_outcome": {
    "price_return": null,
    "drawdown": null,
    "fundamental_confirmation": null,
    "narrative_persistence": null,
    "filing_confirmation": null
  }
}
```

Outcome buckets: **confirmed** (any explicit positive observation),
**refuted** (any explicit negative), **unresolved** (no observations).
Unresolved records count *against* precision — the engine gets no
credit for unverifiable calls.

## Metrics

```text
precision_at_k                    confirmed fraction of top-k by score
hit_rate_by_verdict               confirmation rate per advisory verdict
average_score_by_outcome_bucket   mean score among confirmed/refuted/unresolved
Brier = (p − y)²                  mean over resolved event probabilities
bucketed_probability_error        |mean predicted − empirical frequency| per bucket
narrative_decay_error             mean |predicted − observed persistence|
trap_flag_false_positive_rate     trap-flagged records that later confirmed
```

## calibration_support — the sizing gate

```text
calibration_support = 100 × min(1, resolved_event_probabilities / 50)
```

This is the single number that connects replay history to live scoring:
`aggregate_opportunity_score_v2` caps every verdict at `deep_research`
while `calibration_support < 10`. Until roughly 50 resolved event
probabilities exist, the engine may classify and explain but never
emits position-candidate verdicts. This is deliberate: a score with no
outcome history is a hypothesis, not a calibrated probability.

## Calibration limits (honest)

- The demo dataset (`demo_replay_dataset`) is three synthetic
  `manual_stub` records for dashboard wiring — it proves the math, not
  the engine.
- No live price or outcome feed is wired; observed outcomes must come
  from the journal/reconciliation workflow.
- Brier and bucket errors are only meaningful once each bucket has
  dozens of resolved events; with fewer, treat them as plumbing checks.
- Narrative persistence observations are operator judgments today, so
  narrative_decay_error inherits that subjectivity.
- TODO(replay): feed reconciled outcomes from the SQLite journal into
  replay records once enough advisory history accumulates, and pass the
  resulting `calibration_support` into `/alpha/score`.
