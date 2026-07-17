# Decision Twin Methodology

A Decision Twin (`scripts/simulation_intelligence/decision_twin.py`) is a frozen,
immutable, replayable representation of a decision at a specific information
cutoff. It is NOT a clone of the user and imitates no personality.

## What it freezes
- **Known / unknown:** the observation snapshot + `unknown` (missing fields) + `stale_evidence`.
- **Beliefs:** each lens's vote/label/confidence + the council's aggregate belief.
- **Context:** regime state (`regime.py`) + typed uncertainty (`actionable_uncertainty.py`).
- **Action space:** the five advisory states available.
- **Value of information:** the top research action + verdict.
- **Predictions:** a bounded set of `FalsifiablePrediction`s (see falsifiable_prediction_contracts.md).
- **Refusals:** `refused_predictions` — what it will NOT predict (e.g. no price history). Refusing is a feature: it prevents prediction spam and false confidence.

## Immutability
The twin is a frozen dataclass. `immutability_hash` is SHA-256 over the frozen
payload (candidate, cutoff, run_id, council belief, prediction hashes, advisory
state, unknowns). `verify_integrity()` recomputes and compares — any mutation is
detected (tested: `test_twin_immutable_and_hash_detects_tamper`). Operator choices
and outcomes attach via **separate** append-only records, never by editing the twin.

## Why it matters
It makes the whole decision process falsifiable, replayable, comparable,
calibratable, auditable and **learnable from process quality, not just returns**.
Runtime: frozen inside `daily_shadow_run.run_candidate`, persisted via
`persistence.insert_decision_twin`, read at `GET /api/intelligence/twins/{id}`.
