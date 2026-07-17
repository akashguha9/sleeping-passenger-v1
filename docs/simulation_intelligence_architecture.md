# Simulation Intelligence Layer (SIL) — Architecture & Decision Record

**Status:** Implemented, runtime-reached, tested.
**Package:** `scripts/simulation_intelligence/` · **Contract version:** `sil-1.0.0`
**Scope:** advisory-only, human-execution-required, SIMULATED_ONLY decision-support.

The SIL adds a **six-lens simulation council** to Sleeping Passenger. Given a
normalized market observation for one candidate, it runs six independent domain
lenses (physics, chemistry, biology, racing, chess, poker), aggregates them
*without naïve averaging*, and returns an explainable advisory stance
(`WATCH` / `WAIT` / `AVOID` / `RISK_BLOCK` / `OUTCOME_REVIEW`) with uncertainty
bands, stress-test outcomes, counterfactuals, and honest evidence labels.

Every output is `ADVISORY_ONLY`, `execution_gate=LOCKED`, `broker_api_called=false`,
`ai_execution_count=0`. The council result never feeds calibration and never
authorises sizing or execution.

---

## 1. Decision record (ADR)

### 1.1 Capability transplant, not dependency bloat
**Decision:** Transplant the *decision principle* of each engine in original code;
do not embed heavyweight or proprietary engines on the runtime path.
**Why:** The product constraints require SQLite-first, fail-closed operation with a
clean primary Python environment. Most listed engines (MD engines, game engines,
proprietary solvers) provide **zero market signal** natively and are heavyweight,
GPU-oriented, conda-only, browser-only, Windows-game-only, or licence-locked. See
`docs/simulation_engine_manifest.md` for the per-engine evidence. Net result:
**15 CONCEPT_TRANSPLANT, 1 NATIVE_LIBRARY (COPASI, optional), 1 EXTERNAL_PROCESS
(Stockfish, optional), 1 REJECTED (PhET)**.

### 1.2 Dependency isolation
**Decision:** The base app depends on **nothing new**. The two optional engine
adapters (Stockfish subprocess, COPASI `copasi-basico`) sit behind feature flags
(`SIL_STOCKFISH_ENABLED`, `SIL_COPASI_ENABLED`, both default `false`) and lazy
imports. `requirements.txt` is unchanged.
**Why:** "The ordinary Sleeping Passenger workflow must continue working without
them." Verified: the council runs all six lenses with every optional engine
`UNAVAILABLE`/`DISABLED`.

### 1.3 Unified, versioned contracts
**Decision:** One bedrock module `contracts.py` (pure dataclasses + enums, stdlib +
`advisory_contract` only) defines every object: `SimulationRequest`,
`MarketObservation`, `SimulationScenario`, `SimulationAssumption`, `UncertaintyBand`,
`EvidencePacket`, `CounterfactualBranch`, `StressTestResult`, `LensResult`,
`LensWeight`, `SimulationCouncilResult`, plus the evidence-label and disagreement
enums. Every serialized object carries `contract_version`.
**Why:** All six lenses return the *same* `LensResult` shape, so the aggregator has
no special cases. Evidence honesty is structural — an output must declare *what kind
of thing it is* (`MEASURED` … `SIMULATED_ONLY` … `INSUFFICIENT_DATA`), never
collapsed into a single confidence number.

### 1.4 Orchestration & aggregation
**Decision:** `council.py` runs the six lenses, deduplicates evidence by
fingerprint, computes explainable per-lens weights (evidence strength × correlation
penalty × staleness penalty × missing-data penalty × source-concentration penalty),
applies **RISK_BLOCK precedence**, preserves minority/tail warnings, and classifies
the disagreement structure.
**Why:** Agreement caused by *shared inputs* must not masquerade as independent
corroboration; a lone tail warning must survive; a weighted `RISK_BLOCK` must be able
to override a superficially attractive aggregate. Every weight and penalty is
explained in `aggregation_explanation`.

### 1.5 Persistence
**Decision:** SQLite remains canonical. One additive table `simulation_runs` stores
the full council result + input request (for seed/data-cutoff replay), with the
advisory stamps hard-coded on every row. Schema is created via the existing
`CREATE TABLE IF NOT EXISTS` + additive-migration convention in `persistence.py`.
**Why:** "SQLite-first for canonical runtime state; JSONL only for audit/export."
The table is isolated: SIL writes *only* `simulation_runs`, never `manual_trades`,
`imported_outcomes`, `reconciliation_results`, or any calibration table (verified).

### 1.6 Safety
**Decision:** Fail-closed everywhere. `SIL_ENABLED=false` → structured refusal.
Missing data → `INSUFFICIENT_DATA` + warnings, never invented values. Optional engine
absent → `ENGINE_UNAVAILABLE`, council still runs. No broker/order code anywhere in
the package (statically verified). No shell (`shell=False`, fixed arg list) for the
Stockfish subprocess. No untrusted pickle, no arbitrary file access, no network in
the lenses.

### 1.7 Performance
**Decision:** Bounded Monte-Carlo (`SIL_MAX_RUNS`, default 512), bounded scenarios
(`SIL_MAX_SCENARIOS`, default 24), timeout budget (`SIL_TIMEOUT_MS`, default 2000),
deterministic-by-seed RNG (`deterministic_rng.py`), CPU-safe defaults, vectorised
NumPy where it matters (no O(n²) graph blow-ups). `/api/simulation/` gets the
stricter rate-limit bucket.

### 1.8 Testing
**Decision:** Contract/serialization, determinism, seed reproducibility, scenario
generation, stress tests, counterfactuals, lens independence, evidence dedup,
correlation penalties, risk-block precedence, missing/stale/engine-unavailable
behaviour, bounded runs, API validation, no-execution invariants, leakage
prevention, and frontend rendering are all covered. 45 backend SIL tests + 3
frontend tests, plus a 17-check adversarial probe.

### 1.9 Licensing boundaries
**Decision:** No proprietary code is scraped, reverse-engineered, or imitated. Only
published algorithmic principles are re-implemented in original code. PhET is
rejected outright (GPLv3 source copyleft). Stockfish is used arm's-length via
subprocess (GPLv3 does not contaminate our code). COPASI is Artistic-2.0. See the
manifest for per-engine licence evidence.

---

## 2. Package layout

```
scripts/simulation_intelligence/
  contracts.py            # bedrock dataclasses + enums (pure)
  deterministic_rng.py    # seed-stable RNG (OpenMM reproducibility principle)
  engine_manifest.py      # the 18-engine verified manifest (source of truth)
  feature_flags.py        # SIL_ENABLED, optional-engine flags, bounds
  provenance.py           # evidence dedup + source-concentration (Herfindahl)
  uncertainty.py          # distribution → UncertaintyBand summariser
  scenario_graph.py       # dependency-graph shock propagation (Chrono principle)
  scenario_library.py     # 32 India/US stress + operational scenarios
  stress_testing.py       # bounded Monte-Carlo stress suite
  replay.py               # deterministic replay from stored run
  council.py              # orchestration + explainable aggregation
  api_surface.py          # bounded, fail-closed request/observation builders + reports
  report.py               # machine-readable runtime artifact + usefulness score
  lenses/
    base.py               # common Lens interface (evaluate() -> LensResult)
    physics.py chemistry.py biology.py racing.py chess.py poker.py
  adapters/
    base.py registry.py   # honest availability map for optional engines
    stockfish_adapter.py  # optional EXTERNAL_PROCESS (flag-gated, Threads=1)
    copasi_adapter.py     # optional NATIVE_LIBRARY (flag-gated, lazy import)
```

## 3. Data flow (runtime-reached)

```
Frontend /simulation-lab ─┐
                          ├─► POST /api/simulation/run (api_server.py)
apiClient.postSimulationRun┘        │  validate SimulationRunBody (bounded)
                                    ▼
                     api_surface.run_simulation(payload)
                                    │  build_request → build_observation (fail-closed)
                                    ▼
                     council.run_council(request)
                        ├─ lenses[6].evaluate(obs, req, seed) → LensResult × 6
                        ├─ provenance.deduplicate(evidence)
                        ├─ _weights(...) explainable penalties
                        ├─ _aggregate_vote(...) RISK_BLOCK precedence
                        ├─ stress_testing.run_stress_suite(...)
                        └─ engine_availability_map()
                                    ▼
                     SimulationCouncilResult.to_dict()  (advisory-stamped)
                                    ▼
        persistence.insert_simulation_run(...) → SQLite simulation_runs (SIMULATED_ONLY)
                                    ▼
        GET /api/simulation/runs/{id}, /replay, /council/{ticker}, /stress-summary
```

## 4. Non-negotiable invariants (verified)

| Invariant | Where enforced | Evidence |
|---|---|---|
| `ADVISORY_ONLY` | every serialized SIL dict via `advisory_safety_stamps()` | adversarial probe `no_execution_stamps` PASS |
| `execution_gate=LOCKED` | contracts `to_dict()`, persistence row, API responses | probe + persisted-row check PASS |
| `broker_api_called=false` | hard-coded 0 on `simulation_runs` row; no broker imports | `no_broker_or_order_code` PASS, arch-fitness PASS |
| `ai_execution_count=0` | hard-coded everywhere | probe PASS |
| Fail-closed | `SIL_ENABLED=false` refuses; missing data → `INSUFFICIENT_DATA` | probe `sil_disabled_fail_closed`, `missing_data_flagged` PASS |
| No calibration leakage | SIL writes only `simulation_runs` | probe `no_leak_into_execution_tables` PASS |
| Reproducible by seed | deterministic RNG + seed in run_id | probe `determinism_same_seed` PASS |

## 5. What is deliberately *not* built

- No signal→observation auto-bridge from the live reactor yet (observations arrive
  via the API payload / frontend demo). This is the top integration next-step.
- No neural training (Leela/Maia) — insufficient leakage-safe data.
- No proprietary engine embedding or API egress (GTO Wizard, PioSOLVER, Monker).
- No predictive-accuracy or profitability claim — empirical validation is 0/10 by
  design until leakage-safe real outcomes exist (see the limitations doc).
