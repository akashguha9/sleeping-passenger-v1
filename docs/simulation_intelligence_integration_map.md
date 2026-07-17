# Simulation Intelligence Layer — Existing-System Integration Map

The SIL is **not** a parallel orphan architecture. It reuses the repo's bedrock
contract, persistence conventions, API/route style, config contract, scope guard,
architecture-fitness boundaries, and frontend design system. This map shows, per
existing subsystem: the new SIL capability, the data contract, the API surface, the
frontend surface, and the tests.

Format: **EXISTING MODULE → NEW SIL CAPABILITY → DATA CONTRACT → API SURFACE →
FRONTEND SURFACE → TESTS**

---

## Reused bedrock (not duplicated)

| Existing | How SIL reuses it |
|---|---|
| `scripts/advisory_contract.py` | Every SIL dict is stamped via `advisory_safety_stamps()`; `contracts.stamp_advisory` wraps it. No new safety vocabulary. |
| `scripts/persistence.py` | SIL adds one table (`simulation_runs`) using the existing `CREATE TABLE IF NOT EXISTS` + additive-migration + late-bound `db_path` conventions; conftest DB isolation applies unchanged. |
| `scripts/api_server.py` | SIL routes use the existing app, `require_api_token[_for_reads]` deps, `_safe_exc_summary`, rate-limit buckets, and Pydantic body validation. |
| `scripts/config_contract.py` | Six `SIL_*` vars registered in `CONTRACT`. |
| `scripts/private_scope_guard.py` | `"simulation"` approved as an advisory-only domain. |
| `scripts/architecture_fitness.py` | SIL lives in a subpackage (not scanned by the top-level `scripts/*.py` globs), imports no broker/frontend/sqlite in pure layers; arch score stays **1.0**. |
| `frontend` design system | `AdvisoryOnlyBadge`, `NoExecutionBanner`, Tailwind idioms, `apiClient` pattern, `types/index.ts`. |

## Per-subsystem integration

### Signal reactor / titration / chicken gate
- **NEW SIL CAPABILITY:** the six-lens council consumes a `MarketObservation` whose
  fields (returns, volatility, liquidity/spread, catalysts, freshness, source_count)
  map directly onto the reactor's signal inputs, and returns an advisory stance that
  *complements* the reactor's gate.
- **DATA CONTRACT:** `MarketObservation` / `SimulationRequest` → `SimulationCouncilResult`.
- **API:** `POST /api/simulation/run` (accepts `parent_signal_id` to link back).
- **FRONTEND:** Simulation Lab council card.
- **TESTS:** `tests/test_simulation_intelligence.py` (contracts, council, determinism).
- **STATUS:** Council is runtime-reached via API/frontend. **Auto-population of the
  observation directly from the live reactor is the top next-step** (today the
  observation is supplied in the request payload / frontend demo).

### Prediction-market disagreement + narrative cascade
- **NEW SIL CAPABILITY:** the **poker lens** (imperfect-information, regret,
  exploitability, multi-agent) and **biology lens** (contagion, thesis lifecycle)
  generalise "disagreement" into equilibrium-robustness and narrative-lifecycle
  classification; the council's `disagreement_class` mirrors the existing model-
  disagreement idea at the *lens* level.
- **DATA CONTRACT:** `LensResult` (regret, exploitability, `ThesisLifecycle`).
- **API:** council result fields; `GET /api/simulation/council/{ticker}`.
- **FRONTEND:** six-lens council + disagreement classification.
- **TESTS:** lens-independence, dedup, correlation-penalty tests.

### Five-model synthesis
- **NEW SIL CAPABILITY:** the council is a *second, orthogonal* synthesis — six domain
  lenses aggregated without naïve averaging, with correlation/shared-evidence
  penalties the five-model synthesis can borrow conceptually. SIL does **not** replace
  or modify the five-model workflow.
- **DATA CONTRACT:** `SimulationCouncilResult` (separate from model synthesis).
- **API:** `/api/simulation/*` (distinct namespace).
- **TESTS:** aggregation tests; full suite confirms no regression to synthesis paths.

### Risk engine / tail-loss governor
- **NEW SIL CAPABILITY:** stress library (32 scenarios) + **RISK_BLOCK precedence** in
  aggregation; tail warnings are preserved and can override an attractive aggregate,
  echoing the tail-loss governor's defensiveness.
- **DATA CONTRACT:** `StressTestResult`, `UncertaintyBand` (tail_low/high),
  `risk_block_engaged`.
- **API:** `GET /api/simulation/stress-summary`, `GET /api/simulation/scenarios`.
- **FRONTEND:** tail-risk warnings, robustness-vs-fragility, scenario catalog.
- **TESTS:** stress, risk-block precedence, tail-warning preservation (probe +
  pytest).

### Calibration system / outcome ledger
- **NEW SIL CAPABILITY:** honest evidence labels + a `usefulness_score` that is
  explicitly **not** predictive accuracy; empirical validation hard-set to 0 until
  leakage-safe outcomes exist.
- **DATA CONTRACT:** `EvidenceLabel`, `CalibrationRecord`-style honesty fields.
- **API:** `/api/simulation/health`, report artifact `simulation_intelligence_summary.json`.
- **INTEGRATION BOUNDARY:** SIL **never writes** calibration/outcome tables (verified
  `no_leak_into_execution_tables`). Wiring reconciled outcomes *into* the lenses is a
  documented next-step that must pass the existing leakage guards.

### Manual trade validation / Google Sheets reconciliation
- **NEW SIL CAPABILITY:** none that touches execution — SIL is orthogonal. It writes
  only `simulation_runs`, never `manual_trades` / `reconciliation_results`.
- **INTEGRATION BOUNDARY:** verified isolation; the Sheets reconciliation workflow is
  unaffected.

### Source-health / freshness / discovery (India+US)
- **NEW SIL CAPABILITY:** the observation carries `freshness_status`, `source_count`,
  and provenance; the aggregator applies **staleness** and **source-concentration**
  penalties, matching the fail-closed discovery posture.
- **DATA CONTRACT:** `MarketObservation.freshness_status/source_count/provenance`.
- **TESTS:** stale-data penalty, source-concentration, missing-data fail-closed.

### Governance stamps / operational-readiness audit
- **NEW SIL CAPABILITY:** `report.py` emits a machine-readable
  `simulation_intelligence_summary.json` following the `*_summary.json` convention,
  with the standard `[safety]` line and the honest usefulness/empirical scores.
- **API:** `GET /api/simulation/health`.
- **TESTS:** advisory-contract test suite unchanged and green (35 passed);
  architecture-fitness PASS at score 1.0.

## API additions (10 routes)

`GET /api/simulation/health` · `GET /api/simulation/engines` ·
`GET /api/simulation/scenarios` · `POST /api/simulation/run` ·
`GET /api/simulation/runs` · `GET /api/simulation/runs/{run_id}` ·
`GET /api/simulation/runs/{run_id}/replay` · `GET /api/simulation/council/{ticker}` ·
`GET /api/simulation/stress-summary`

## Frontend additions

- `frontend/src/app/simulation-lab/page.tsx` — the Simulation Lab.
- `frontend/src/lib/apiClient.ts` — `getSimulation{Health,Engines,Scenarios,Runs}`,
  `postSimulationRun` (null-resolving on error, matching existing wrappers).
- `frontend/src/types/index.ts` — `Sim*` response types.
- `frontend/src/components/layout/Sidebar.tsx` — nav entry.
- `frontend/src/app/__tests__/simulationLab.spec.tsx` — 3 rendering tests.

## Database additions

- Table `simulation_runs` (+ 3 indexes) in `scripts/persistence.py`, with advisory
  stamps hard-coded per row. Functions: `insert_simulation_run`,
  `get_simulation_run`, `get_recent_simulation_runs`,
  `get_latest_simulation_run_for_ticker`. Added to `get_db_status` table list.
