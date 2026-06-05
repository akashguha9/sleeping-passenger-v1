# Sleeping Passenger Coordination Audit

> Read-only static audit. Advisory-only: no broker calls, no execution, no runtime mutation. Every scored number is derived from committed source files (STATIC_CODE provenance).

## Executive Summary

- **Overall grade:** `RHYTHMIC_UNISON`
- **Overall score:** 1.0 (weighted mean of six layers, equal weights)
- **NO_DATA ratio:** 0.0417 (evidence sufficient)
- **Mode:** `PARTIAL_DATA`
- **Biggest blocker:** none
- **Biggest strength:** `choreography` layer (score 1.0)
- **Generated (UTC):** 2026-06-05T21:20:08+00:00
- **Repo commit:** `13093be8870c36626c0034d2dd78e213dbb1ef1a`

**Verdict — the MVP's _coordination machinery_ behaves like a _synchronized rowing crew_.**

Crew-rhythm scale: synchronized rowing crew > decent school drill with gaps > fragmented team > unsynchronized rowers.

> **Scope & honesty caveat.** This grade measures *code-level* coordination — whether the workflow, clock, finite states, collision guards, rehearsal boundaries, and ops controls are present, wired together by stable identifiers, and backed by tests. It is **not** a claim of live trading performance or edge. Calibration on **real operator outcomes is `NO_DATA`** (none are committed to the repo), so `mode = PARTIAL_DATA`, not `MEASURED`. A perfectly-drilled crew can still be untested on open water.

## Layer 1 — Choreography

- **Score:** 1.0
- **Status:** `PASS`
- **What it checks:** End-to-end show: signal generation -> inbox -> live -> manual log -> reconciliation -> outcome -> Moltbook -> dashboard, linked by stable event_id/trade_id/ticker identifiers in the persistence schema.

| Metric | Value | Status | Expected | Provenance |
| --- | --- | --- | --- | --- |
| workflow_stage_presence_ratio | 1.0 | `PASS` | >=0.875 PASS; 0.625-0.875 WARN; <0.625 FAIL | static: 8/8 workflow stages have an identifiable module |
| workflow_link_coverage_ratio | 1.0 | `PASS` | >=0.80 PASS; 0.50-0.80 WARN; <0.50 FAIL | static: 7/7 stage transitions linked by stable IDs |
| identity_continuity_score | 1.0 | `PASS` | >=0.90 PASS; >=0.70 WARN; else FAIL | static: 6/6 identity keys present in persistence schema |

**Evidence:**

- `scripts/signal_engine.py` (STATIC_CODE) — stage:signal_generation
- `scripts/signal_inbox_api.py` (STATIC_CODE) — stage:signal_inbox
- `scripts/refresh_live_signals.py` (STATIC_CODE) — stage:live_signals
- `scripts/bulk_log_manual_trades.py` (STATIC_CODE) — stage:manual_trade_log
- `scripts/paper_reconciliation.py` (STATIC_CODE) — stage:reconciliation
- `scripts/outcome_evidence.py` (STATIC_CODE) — stage:outcome_tracking
- `scripts/moltbook_api.py` (STATIC_CODE) — stage:moltbook_reflection
- `src/dashboard/streamlit_app.py` (STATIC_CODE) — stage:dashboard_summary
- `scripts/persistence.py:97` (STATIC_CODE) — trade_id FK chain
- `scripts/signal_inbox_bridge.py:262` (STATIC_CODE) — event_id continuity
- `scripts/moltbook_reconciliation_bridge.py:4` (STATIC_CODE) — reconciliation->moltbook bridge

## Layer 2 — Timing

- **Score:** 1.0
- **Status:** `PASS`
- **What it checks:** Shared clock: all persistence writes use a single UTC timestamp helper; signals carry freshness labels with configurable stale thresholds; holding periods are computed from real ISO dates.

| Metric | Value | Status | Expected | Provenance |
| --- | --- | --- | --- | --- |
| timestamp_field_coverage | 1.0 | `PASS` | >=0.875 PASS; 0.625-0.875 WARN; else FAIL | static: 6/6 required time fields/policies present |
| stale_signal_guard_status | True | `PASS` | configurable freshness thresholds + stale labelling exist | static: scripts/anti_staleness.py + docs/LIVE_SIGNALS_REFRESH_MODEL.md |
| holding_period_calculation_integrity | {"computes_from_dates": true, "missing_date_returns_none": true, "negative_rejected": true, "tested": true} | `PASS` | computes from dates; None on missing/invalid; no negative periods; tested | static: scripts/paper_reconciliation.py _compute_holding_period_days + tests |

**Evidence:**

- `scripts/persistence.py:101` (STATIC_CODE) — reconciliation timestamp
- `scripts/runtime_common.py:647` (STATIC_CODE) — UTC normalization
- `scripts/anti_staleness.py:32` (STATIC_CODE) — staleness labels
- `scripts/paper_reconciliation.py:246` (STATIC_CODE) — holding-period math

## Layer 3 — Position / Control

- **Score:** 1.0
- **Status:** `PASS`
- **What it checks:** Finite control: signals/trades/reconciliations validate against explicit frozenset status vocabularies; async UI sections resolve to finite loading states (empty/offline/loaded) instead of infinite spinners.

| Metric | Value | Status | Expected | Provenance |
| --- | --- | --- | --- | --- |
| finite_status_enum_coverage | 1.0 | `PASS` | >=0.875 PASS; 0.625-0.875 WARN; else FAIL | static: 5/5 major objects use finite status sets |
| invalid_transition_rejection | True | `PASS` | out-of-enum status values are rejected (raise) and tested | static: signal_inbox_api enforces VALID_* sets; proven in test_coordination_audit.py |
| loading_state_finiteness | 4/4 sections | `PASS` | >=0.75 of async sections have finite loading-state specs | static: presence of frontend loading-state regression specs |

**Evidence:**

- `scripts/signal_inbox_api.py:94` (STATIC_CODE) — signal status enum
- `scripts/signal_inbox_api.py:97` (STATIC_CODE) — reconciliation status enum
- `frontend/src/app/__tests__/manualTradeLog.loadingState.spec.tsx` (STATIC_CODE) — loading-state finiteness

## Layer 4 — Collision / Safety

- **Score:** 1.0
- **Status:** `PASS`
- **What it checks:** No unsafe overlaps: duplicate signals/trades collapse idempotently at the DB boundary; tickers canonicalize through a securities master so exchanges can't silently collide; paper/live/synthetic/imported records stay separated by mode+provenance; advisory-only stamps are enforced on every read and write.

| Metric | Value | Status | Expected | Provenance |
| --- | --- | --- | --- | --- |
| duplicate_signal_collision_guard | True | `PASS` | duplicate signal natural-key blocked/merged idempotently | static: duplicate_fingerprints PK + INSERT OR IGNORE |
| duplicate_trade_collision_guard | True | `PASS` | duplicate trade_id blocked idempotently | static: INSERT OR IGNORE INTO manual_trades (trade_id PK) |
| ticker_normalization_collision_guard | True | `PASS` | canonical symbol UNIQUE + alias map prevents cross-exchange collision | static: global_securities.canonical_symbol UNIQUE + global_security_aliases |
| paper_live_contamination_guard | True | `PASS` | PAPER/LIVE_MANUAL/IMPORTED_BACKTEST/SYNTHETIC kept separate by mode+provenance | static: trade_mode + created_via + manual_trade_origin exclusions |
| advisory_only_guard_status | True | `PASS` | advisory-only/no-execution stamps enforced + tested | static: advisory_contract + persistence _ADVISORY_STATUS + test_advisory_contract.py |

**Evidence:**

- `scripts/persistence.py:141` (STATIC_CODE) — duplicate signal guard
- `scripts/persistence.py:1068` (STATIC_CODE) — duplicate trade guard
- `scripts/persistence.py:249` (STATIC_CODE) — ticker canonicalization
- `scripts/manual_trade_origin.py:49` (STATIC_CODE) — provenance separation
- `scripts/advisory_contract.py:12` (STATIC_CODE) — advisory-only guard

## Layer 5 — Simulation

- **Score:** 1.0
- **Status:** `PASS`
- **What it checks:** Safe rehearsal: synthetic fixtures and imported backtests are labelled and refused from runtime/live stats; calibration on REAL outcomes is reported NO_DATA honestly because no real operator outcomes are committed to the repo.

| Metric | Value | Status | Expected | Provenance |
| --- | --- | --- | --- | --- |
| test_fixture_provenance_integrity | True | `PASS` | synthetic fixtures labelled SYNTHETIC/TEST_FIXTURE | static: SYNTHETIC_LOGGED_BY_MARKERS + fixture prefix/metadata |
| imported_backtest_provenance_integrity | True | `PASS` | imported backtest carries source_type + import timestamp + raw inputs | static: imported_outcomes table with imported_at + source_type |
| simulation_to_runtime_boundary_guard | True | `PASS` | synthetic cannot enter live stats; missing outcomes -> NO_DATA | static: run_imported_backtest refuses synthetic in runtime; tested |
| calibration_evidence_status | None | `NO_DATA` | MEASURED only with real outcomes; none committed -> NO_DATA (honest) | NO_DATA: no real operator outcomes are committed; runtime DB is non-canonical |
| calibration_gate_present | True | `PASS` | calibration gate emits NO_REAL_OUTCOME_EVIDENCE when real_n=0 | static: scripts/calibration_gate.py NO_REAL_OUTCOME_EVIDENCE |

**Evidence:**

- `scripts/signal_inbox_api.py:129` (STATIC_CODE) — fixture labelling
- `scripts/run_imported_backtest.py:17` (STATIC_CODE) — sim->runtime boundary
- `scripts/outcome_evidence.py:5` (STATIC_CODE) — provenance-weighted outcomes
- `runtime/mvp_local.db` (NO_DATA) — real operator outcomes (none committed; git-ignored runtime store)

## Layer 6 — Operations

- **Score:** 1.0
- **Status:** `PASS`
- **What it checks:** Daily rhythm: startup preflight + health endpoint, destructive resets guarded behind dry-run+role+allowlist+backup, dashboards degrade gracefully, journals export to CSV/JSON, and a release gate emits a single PASS/WARN/FAIL verdict.

| Metric | Value | Status | Expected | Provenance |
| --- | --- | --- | --- | --- |
| startup_health_status | True | `PASS` | startup runs diagnostics (DB/tables/health endpoint) | static: local_deploy_preflight checks + api_server health route |
| runtime_log_safety_status | True | `PASS` | reset script: dry-run default, guard, allowlist, safe-path, tested | static: reset_local_logs guarded_mutation + _ALLOWED_TABLES + tests |
| dashboard_operability_status | True | `PASS` | dashboard renders under empty/error/stale data without infinite spinner | static: defensive .get() + frontend loading-state specs |
| export_auditability_status | True | `PASS` | exportable manual log/reconciliation/outcomes (CSV/JSON) + audit log | static: gsheet_export / export_paper_trades + operator_audit_log |
| release_gate_status | True | `PASS` | release gate aggregates preflight into PASS/WARN/FAIL + tested | static: release_gate.py + test_release_gate.py |

**Evidence:**

- `scripts/reset_local_logs.py:172` (STATIC_CODE) — reset guard
- `scripts/reset_local_logs.py:37` (STATIC_CODE) — reset allowlist
- `scripts/release_gate.py:1` (STATIC_CODE) — release gate verdict
- `scripts/gsheet_export.py` (STATIC_CODE) — CSV/JSON export

## Blocking Findings

None. No FAIL-level metric was detected by static inspection.

## Provenance Statement

Where the numbers came from:

- **Static code inspection:** every scored metric (deterministic across machines/CI).
- **Tests:** the full pytest suite is run separately (see baseline in the engineering report); the audit references specific test files as evidence but does not auto-execute them.
- **Runtime files / local logs:** listed for transparency, **not scored** — the runtime DB is git-ignored and non-canonical.
- **Synthetic fixtures / imported backtests:** labelled rehearsal data, never scored as live.
- **Real / manual data:** **NO_DATA** — no real operator outcomes are committed to the repo, so calibration-on-real-outcomes is reported NO_DATA rather than fabricated.

Allowed sources:
- STATIC_CODE (committed source files — the only source folded into the score)
- TEST_RESULT (separately run pytest suite; not auto-folded here)
- RUNTIME_DB / LOCAL_LOG (listed for transparency; NOT scored — git-ignored, non-canonical)
- FIXTURE / IMPORTED_BACKTEST / SYNTHETIC (rehearsal data; never scored as live)

Disallowed mixing rules:
- Synthetic fixtures must never enter live/manual performance stats.
- Imported backtest must never be presented as live performance.
- Paper and real-manual records must not be aggregated without grouped provenance.
- Missing real outcomes must surface as NO_DATA, never fabricated confidence.

Runtime files inspected (not scored):
- runtime/mvp_local.db (exists=True; non-canonical, NOT scored)
- logs/*.jsonl (append-only operator journals; NOT scored)

## Next Fixes

Ranked by safety/coordination impact vs implementation risk:

1. No blocking or warning findings from static inspection. Maintain the guards; re-run this audit in CI to catch regressions. _Acceptance:_ overall grade stays >= MOSTLY_COORDINATED and no layer drops to FAIL.
