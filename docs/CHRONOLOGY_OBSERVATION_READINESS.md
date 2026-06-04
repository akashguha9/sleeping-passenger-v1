# Chronology / Observation Readiness

**Status: OBSERVATION-GATED. Current readiness ≈ 4/10. Do not raise above 5
without accumulated FORWARD observations.**

This document is the honest record of what the chronology subsystem can and
cannot do today. It exists so no reader mistakes *scaffolding* for *capability*.

## 1. What exists today (real)

- `scripts/chronology_store.py` — a SQLite store with:
  - **v0 (live):** `observations`, `snapshots` tables + validated insert helpers.
    These are used by `snapshot_logger` on the active path.
  - **v1 (now populated by the runner):** `signal_candidates`,
    `chronology_events`, `pattern_hit_rates` tables exist (created additively,
    `IF NOT EXISTS`), with fail-closed insert helpers.
- `scripts/chronology_detectors.py`:
  - **T1 event-prior — IMPLEMENTED, observation-only, fail-closed.** Fires only
    when the latest probability step is both large (≥ delta floor) and
    statistically anomalous (z-score of the latest step vs prior steps ≥
    z-floor) AND clears a volume floor; requires ≥ N prior steps or returns
    `INSUFFICIENT_DATA`. Never fabricates, never authorizes action.
  - **T2/T3/T4 — still `NOT_IMPLEMENTED` / fail-closed.**
- `scripts/chronology_observation_runner.py` — reads `signal_candidates`,
  evaluates T1, writes one `chronology_events` row per candidate, and updates
  `pattern_hit_rates` **observation frequencies only**. It imports no execution
  /broker/action code (test-enforced) and fails closed on missing data.

## 2. What does NOT exist (do not claim)

- **T2 (asset attachment), T3 (commitment), T4 (market confirmation)** — NOT
  implemented.
- A real **forward-observation dataset**. T1 is correct and tested on synthetic
  fixtures, but no live forward observations have been accumulated. The
  `pattern_hit_rates` "hit_rate" is an observation *frequency*, NOT a
  performance/edge claim, and stays `NULL` at zero observations.
- `scripts/event_prior_detector.py` remains a *time-clustering* helper; it is
  distinct from the T1 detector above and does not feed it.
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
