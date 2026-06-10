# Journal-to-Replay Bridge

Advisory-only. Read-only over the operator journal. Replay metrics
measure historical advisory signal quality, never investment
performance.

## Data path

```text
manual trades + reconciliations + Moltbook        (existing SQLite journal)
  → scripts/outcome_evidence_extractor.extract_from_db   (existing, read-only)
  → OutcomeEvidence records (WIN/LOSS/BREAKEVEN/OPEN, score_at_entry, quality)
  → src/alpha/journal_replay_bridge.outcome_to_replay_record
  → replay records with lineage
  → src/alpha/replay.evaluate_replay
  → calibration_support
  → apply_calibration_gate in every opportunity v2 verdict
```

## Honesty rules

- **Skips are counted, never guessed**: `open_or_unknown_outcome`,
  `missing_score_at_entry`, `synthetic_fixture_source` each increment a
  named skip reason. Coverage is reported:
  `outcome_coverage = usable / max(1, discovered)`.
- **Probability proxying is explicit**: the journal stores scores, not
  probabilities. `event_probability = score/100` is attached only to
  calibration-eligible records and stamped
  `probability_derivation: score_proxy` in lineage — consistent with how
  `scripts/calibration_map.py` already calibrates scores against
  outcomes.
- **Score normalization is conservative and traceable**: mixed journal
  scales (0–1 fractions, 0–10 confidences, 0–100 scores) normalize to
  0–100 with the rule recorded in lineage.
- **Absent DB / table / schema mismatch** degrade to an empty dataset
  with `missing_inputs: ["journal_outcomes"]` — never a crash (the
  extractor is fail-closed to `[]`).

## Math

```text
Brier = (p − y)^2
precision@k = true_positive_top_k / k
calibration_support = 100 × min(1, resolved_probability_records / 50)
outcome_coverage = usable_replay_records / max(1, discovered_records)
calibrated_confidence =
  base_confidence × (0.5 + 0.5 × calibration_support/100) × outcome_coverage
```

All outputs bounded; empty inputs produce `None` metrics, not zeros
pretending to be measurements.

## Surfaces

- CLI: `python scripts/build_alpha_replay_from_journal.py [--db-path …] [--k …]`
  (prints the JSON report; writes nothing).
- API: `POST /alpha/replay/from-journal` (strict token gate).
- Dashboard: "Calibration / Journal Replay Bridge" panel — records
  discovered/usable/skipped with reasons, coverage, calibration support,
  precision@k, Brier, hit-rate by verdict, trap-flag false-positive
  rate, disclaimer.

## Limits

The bridge is live machinery over a young journal: until enough
reconciled outcomes accumulate (~50 resolved probability records for
full support), calibration_support stays low and the opportunity engine
keeps verdicts at research grade. That is the design, not a bug.
