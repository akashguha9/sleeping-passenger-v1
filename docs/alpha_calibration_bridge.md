# Alpha Calibration Bridge

Advisory-only. A calibrated probability never enables sizing on its
own; the calibration gate and human review still apply.

## Why raw scores are not probabilities

A score of 72 is a hand-tuned ranking statement, not a claim that 72%
of such signals resolve positively. Treating scores as probabilities is
the easiest way for the system to fool itself — overconfident scores
produce overconfident verdicts with no empirical basis. The bridge
exists to replace that assumption with measurement:

```text
raw_probability = clamp(score / 100, 0, 1)            (a labelled hypothesis)
calibrated_probability = f_calibration(raw_probability) (an earned frequency)
```

## How the map works

`src/alpha/calibration_bridge.py` reuses `scripts/calibration_map.py`
(stdlib-only) end to end:

1. Resolved replay records (confirmed=1, refuted=0; unresolved records
   are excluded — unverifiable calls teach nothing) become
   (probability, outcome) pairs.
2. **Isotonic regression** (pool-adjacent-violators, monotone) and
   **Platt scaling** (`sigmoid(A·s + B)`) are both fitted on a
   deterministic train split.
3. The winner is chosen by **out-of-sample Brier** on the held-out
   split — and kept only if it strictly beats the raw probabilities.
   Otherwise `method = "identity"`: we never claim a recalibration that
   does not generalise.
4. Below `MIN_RESOLVED_FOR_FIT = 12` resolved records the bridge
   refuses to fit at all: `method = "insufficient_data"`, identity
   behavior, explicit `missing_inputs`.

```text
Brier = (p − y)^2
calibration_error_bucket =
  |mean(predicted_probability_bucket) − empirical_frequency_bucket|
expected_calibration_error =
  Σ_bucket weight_bucket × calibration_error_bucket
```

## Artifacts

`calibration_map.py` had no model serialization; the bridge adds it.
An artifact carries the isotonic knots / Platt coefficients, the OOS
metrics, and a content-derived `artifact_id` (sha256 prefix), so every
calibrated probability in a replay record can name the exact map that
produced it (`lineage.calibration_source = "artifact:<id>"`).

```bash
python3.13 scripts/build_alpha_replay_from_journal.py --fit-calibration \
    --calibration-artifact runtime/alpha_calibration.json
python3.13 scripts/build_alpha_replay_from_journal.py --apply-calibration \
    --calibration-artifact runtime/alpha_calibration.json
```

## Why insufficient data must not unlock aggressive verdicts

The entire chain is gated on evidence volume:

```text
calibration_support = 100 × min(1, resolved_probability_records / 50)
calibration_weight = 0.5 + 0.5 × calibration_support/100
calibration_adjusted_confidence =
  base_confidence × calibration_weight × max(0.25, outcome_coverage)
```

With zero resolved outcomes, support is 0, adjusted confidence is at
most half of base, and the verdict gate caps everything at
`deep_research`. A fitted map on 12 records unlocks nothing by itself —
support reaches the first gate tier only at 5+ resolved records per
support point. This is deliberate: the system may research immediately,
but it earns the right to express position-grade conviction only at the
rate it accumulates verifiable history.
