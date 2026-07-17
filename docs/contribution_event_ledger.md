# Contribution-Event Ledger

Football ratings move on individual events; this is the system-intelligence
equivalent (`scripts/simulation_intelligence/contribution_ledger.py`). Events are
the audit trail behind every role rating — each one is **derived from an
observable run fact**, never asserted, so a score can be inspected down to what
caused it.

## Event shape

`ContributionEvent`: `event_id, component_id, run_id, event_type, direction
(POSITIVE/NEGATIVE/NEUTRAL), severity (MINOR/MODERATE/MAJOR/SEVERE), event_class
(CONTRIBUTION/PREVENTION/RECOVERY/ENABLING), target_dimension, base_value,
context_difficulty, confidence, counterfactual_impact, evidence,
affected_final_result, created_at` + advisory stamps.

## Taxonomy (35 event types)

- **17 positive** (e.g. `tail_risk_detected`, `stale_data_blocked`,
  `duplicate_evidence_removed`, `correlated_agreement_penalised`,
  `minority_warning_preserved`, `risk_block_overrode_aggregate`,
  `deterministic_replay_matched`, `counterfactual_changed_conclusion`,
  `false_certainty_reduced`, `runtime_recovered_clean_state`).
- **18 negative**, of which **9 are SEVERE integrity failures** (`unsafe_authority`,
  `hidden_execution_path`, `false_evidence_grade`, `corrupted_persistence`,
  `nondeterministic_replay_claimed_deterministic`, `leakage_detected`,
  `silent_failure`, `unbounded_execution`, `simulated_presented_as_measured`).

## Scoring (`score_events`) — two anti-gaming rules

1. **Diminishing returns.** The k-th (0-indexed) event of a type contributes
   `base / (1 + 0.6k)`. The 5th identical event is worth ~1/3.4 of the first; a
   50× volume increase yields only ~6× the points. Event volume cannot inflate.
2. **Severe-integrity penalties.** A SEVERE negative event applies a full-strength
   penalty and flags the component; the RACR engine then caps that component at
   6.0 and subtracts the penalty — a single integrity failure materially cuts the
   rating.

Context difficulty scales *positive* credit up (handling a hard context is worth
more, up to +50% at maximal difficulty) but **never** softens negative events and
never rewards a bad input on its own.

## Derivation from runs (`derive_events_from_run`)

Events are emitted from concrete council + ablation facts:
`risk_block_engaged` → `risk_block_overrode_aggregate` (+ `tail_risk_detected`);
`minority_warnings` → `minority_warning_preserved`; dedup/correlation lines in
`aggregation_explanation` → provenance events; `missing_data_warnings` →
`missing_data_prevented_false_confidence`; ablation `tail_warning_lost` →
`tail_risk_detected` for the specific lens; ablation `vote_changed` →
`counterfactual_changed_conclusion`; ablation Shapley > 0.02 without a vote change
→ `orthogonal_scenario_surfaced` (the quiet Kanté contribution). Every event
records the run field it was derived from as its `evidence`.

## Persistence

`scripts/persistence.py`: `sil_contribution_events` (idempotent on `event_id`,
advisory-stamped rows). Accessors `insert_contribution_events` /
`get_contribution_events`. Exposed read-only at
`GET /api/simulation/contribution-events`.
