# Eureka Sprint — Closed-Loop Decision Intelligence

**Status:** Implemented, runtime-reached, tested. **Verdict:** EUREKA (loop-closure).

## The dominant bottleneck (found by executable inspection)

Before this sprint, three greps established the real constraint:

```
grep calibration_harness / prediction_from_council in runtime paths  → NONE (TEST_ONLY)
grep signal-bridge invocation in daily pipeline                      → NOT wired
grep prediction-freeze / outcome-resolution / resolution_window      → ABSENT
```

The system produced elite analysis (council, RACR, exact-Shapley ablation) and
even shipped a *leakage-safe calibration harness* — but **nothing turned a
simulation into a frozen, falsifiable prediction, scheduled its resolution, or
fed outcomes back.** `simulation_runs` was a record, not a prediction. So the
loop was **open**: the system accumulated outputs, never evidence. Empirical
Score was stuck near 1.0 not for lack of data, but for lack of a machine that can
*generate, freeze, resolve and learn from* evidence.

This is the deepest bottleneck because it simultaneously suppressed Decision
Utility (no falsifiable output), Product Integration (discovery→simulation manual),
Calibration Quality (harness unfed), Empirical Readiness (nothing resolvable), and
Learning Speed (no feedback). Closing it lifts all of them.

## The breakthrough: Decision Twin + closed-loop shadow run

A **Decision Twin** is a frozen, immutable, replayable representation of a
decision at a specific information cutoff — what the system knew, did not know,
each lens/council belief, the regime, typed uncertainty, the value-of-information
verdict, the falsifiable predictions it froze, and **what it refused to predict**.
Its content is hashed; outcomes and belief revisions attach via *separate
append-only records* and never rewrite the twin.

The **daily shadow run** (`POST /api/intelligence/daily-shadow-run`) is the
runtime that closes the loop:

```
candidates → build MarketObservation → intelligence budget (cheap-reject weak)
   → six-lens council (at allocated depth) → value-of-information ranking
   → freeze Decision Twin + falsifiable predictions → immutable shadow policies
   → process-quality score → register outcome-resolution windows
   → (later) leakage-safe resolution → prediction_outcomes → calibration
```

Shadow mode is the default: predictions are recorded, **no human action is
required, no broker interaction occurs**, and outcomes resolve later — so
leakage-safe empirical evidence accumulates automatically.

## Modules (new this sprint)

```
scripts/simulation_intelligence/
  decision_twin.py          # frozen twin + FalsifiablePrediction + immutability hash
  regime.py                 # regime-state contract (cohorting key)
  actionable_uncertainty.py # typed, reducible-vs-not uncertainty decomposition
  value_of_information.py    # VoI ranking + "no research worthwhile" + SURPRISE
  intelligence_budget.py     # cheap-reject / deep-allocate triage
  shadow_policies.py         # immutable advisory-policy comparison (no hindsight)
  process_outcome.py         # process-quality (outcome-free) + 4-quadrant
  outcome_resolution.py      # leakage-safe forward-price resolution
  belief_revision.py         # append-only belief timeline + dynamics classes
  daily_shadow_run.py        # the closed-loop orchestrator (runtime)
```

Persistence: `decision_twins`, `decision_twin_predictions`,
`outcome_resolution_jobs`, `prediction_outcomes`, `belief_revisions` (additive,
advisory-stamped, append-only history). API: `/api/intelligence/*`. Frontend:
`/intelligence` (Intelligence Loop).

## Empirical Score vs Empirical Readiness (the honest split)

The sprint does **not** fabricate outcomes. It raises **Empirical Readiness** (can
the machine generate/freeze/resolve/learn without leakage — measured 9.0/10) while
**Empirical Score** stays honestly low (validated real outcomes — 1.0/10). The two
are reported separately at `GET /api/intelligence/eureka-health` and never merged.

## Safety

`ADVISORY_ONLY` / `execution_gate=LOCKED` / `broker_api_called=false` /
`ai_execution_count=0` on every route, orchestrator output, and persisted row.
No route name contains an execution verb. Fail-closed when disabled or data is
missing. Architecture-fitness stays PASS at 1.0.
