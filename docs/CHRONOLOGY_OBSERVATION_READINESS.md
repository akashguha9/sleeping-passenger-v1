# Chronology / Observation Readiness

**Status: OBSERVATION-GATED. Current readiness ≈ 7/10 (structural). CANNOT rise
above 7 without accumulated FORWARD-REAL observations over time.**

This document is the honest record of what the chronology subsystem can and
cannot do today. It exists so no reader mistakes *scaffolding* for *capability*.

## Detector implementation matrix

| Detector | Status | Fires on | Fail-closed |
|---|---|---|---|
| **T1 event-prior** | IMPLEMENTED | prob-delta ≥ floor **and** z-score ≥ floor **and** volume ≥ floor; ≥ N prior steps | `INSUFFICIENT_DATA` |
| **T2 persistence** | IMPLEMENTED | repeated T1 fires ≥ `min_hits` | `INSUFFICIENT_DATA` below sample |
| **T3 contradiction** | IMPLEMENTED | probability reversal / volume collapse / stale-source marker | `INSUFFICIENT_DATA` on missing fields |
| **T4 outcome** | IMPLEMENTED | a real **logged** resolved outcome | `OUTCOME_PENDING` (never infers outcome/PnL) |

All four are observation-only, deterministic, and authorize nothing.

## 1. What exists today (real)

- `scripts/chronology_store.py` — `observations`/`snapshots` (v0, active path)
  plus `signal_candidates`/`chronology_events`/`pattern_hit_rates` (v1) with
  fail-closed insert helpers.
- `scripts/chronology_detectors.py` — **T1–T4 all implemented**, observation-only,
  fail-closed (matrix above). No synthetic fallback; no action authorization.
- `scripts/run_observation_cycle.py` — runs T1–T4 over `signal_candidates`,
  writes one `chronology_events` row per detector, and **recomputes**
  `pattern_hit_rates` from the events table as honest observation *frequencies*
  (never PnL/edge; `hit_rate` stays `NULL` at zero). T2 accumulates across
  repeated cycles.
- `scripts/chronology_replay_lab.py` — deterministic replay that labels every
  row's provenance as `FORWARD_REAL` / `HISTORICAL_BACKFILL` / `SYNTHETIC_TEST`,
  **conservatively defaulting unlabelled rows to `SYNTHETIC_TEST`** and keeping
  structural replay coverage SEPARATE from forward-observation confidence.
- `scripts/chronology_observation_runner.py` — the earlier T1-only runner (kept).

All of the above import no execution/broker/action code (ast-test enforced).

## 2. What is NOT earned (do not claim)

- A real **FORWARD-REAL observation dataset**. The detectors are correct and
  tested on synthetic/historical fixtures, but **zero forward-real observations
  have accumulated**. `pattern_hit_rates` reflects *observation frequency over
  whatever data was replayed*, NOT live forward performance.
- Replaying `HISTORICAL_BACKFILL` / `SYNTHETIC_TEST` data is **structural only**
  and is never counted as forward-real (enforced in `chronology_replay_lab`).
- **Backfill adapter** (`BF_CHAOS` / `BF_PIPELINE_APPROVED` / `BF_DISCRETIONARY`
  coarse classes from moltbook) — still NOT implemented.
- `scripts/event_prior_detector.py` remains a separate time-clustering helper;
  it is distinct from T1 and does not feed it.

## 3. Why this is 7, not higher

Observation mode is now **operational** — the full T1–T4 cycle runs end-to-end
on existing/historical/synthetic data with honest provenance labels. That earns
*structural* readiness (≈7). It does **not** earn *confidence*: confidence must
be accumulated from FORWARD-REAL observations over time, and there are none yet.
Score is capped at 7 until `forward_real_count` rises with real elapsed
observation. The discipline remains *observation-before-execution*.

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
