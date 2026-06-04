# Chronology / Observation Readiness

**Status: OBSERVATION-GATED. Current readiness ≈ 2/10. Do not raise without
forward observations.**

This document is the honest record of what the chronology subsystem can and
cannot do today. It exists so no reader mistakes *scaffolding* for *capability*.

## 1. What exists today (real)

- `scripts/chronology_store.py` — a SQLite store with:
  - **v0 (live):** `observations`, `snapshots` tables + validated insert helpers.
    These are used by `snapshot_logger` on the active path.
  - **v1 (scaffold only):** `signal_candidates`, `chronology_events`,
    `pattern_hit_rates` tables now exist (created additively, `IF NOT EXISTS`),
    with fail-closed insert helpers. **They are empty. Nothing populates them.**
- `scripts/chronology_detectors.py` — typed interfaces for T1–T4 detectors.
  **All return `available=False` / `NOT_IMPLEMENTED`.** No synthetic fallback.

## 2. What does NOT exist (do not claim)

- **T1 (event prior: probability delta + z-score + volume floor)** — NOT
  implemented. `scripts/event_prior_detector.py` performs *time-clustering of
  observations only*; it does **not** satisfy the T1 specification and must not
  be represented as T1.
- **T2 (asset attachment), T3 (commitment), T4 (market confirmation)** — NOT
  implemented.
- **Backfill adapter** (coarse classes `BF_CHAOS` / `BF_PIPELINE_APPROVED` /
  `BF_DISCRETIONARY` from moltbook) — NOT implemented.
- **Pattern classifier / hit-rate surface** — table exists; no classifier
  writes to it.
- **Observation-cycle runner** — NOT implemented.

## 3. Why this is deliberately low

Observation mode must be **earned by forward observations**, not asserted by
code. Building detectors before there is observed data to validate them would
manufacture false confidence — exactly the failure this project guards against.
The discipline is *observation-before-execution*.

## 4. No authority is conferred by chronology

Chronology authorizes **no action**. It is not wired into any execution path,
it does not influence `can_deploy_capital`, `system_readiness_state`, or any
governance flag, and it cannot lift any lock. It is an observation substrate
only.

## 5. Minimum bar before the score may rise

The readiness score may rise **only** when all of the following are true and
test-backed:

1. A real T1 detector exists with the specified inputs (probability delta,
   z-score, volume floor) — not time-clustering — and is unit-tested against
   fixtures with known-correct outcomes.
2. `signal_candidates` and `chronology_events` are populated by a real
   observation-cycle runner that **refuses synthetic fallback** (fails closed
   when live observations are absent).
3. A documented minimum number of **forward** (not backfilled) observation
   cycles has accumulated — enough that `pattern_hit_rates` is computed from
   observed outcomes, never fabricated (hit_rate stays `NULL` at zero
   observations; this is already enforced).
4. The backfill adapter, if added, emits only coarse classes and never invents
   T1–T4 chronology for historical rows.

Until then: readiness stays low **for the right reason**.
