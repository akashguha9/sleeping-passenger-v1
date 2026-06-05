# Coordination Audit — Phase 0 Baseline & Inventory

> Companion to the generated report `docs/coordination_audit.md`
> (produced by `python -m scripts.coordination_audit`). This file is the
> hand-authored **baseline + inventory** captured while building the audit;
> the report file is machine-regenerated and should not be hand-edited.

## 1. Repo status at audit time

| Item | Value |
| --- | --- |
| Branch | `claude/affectionate-thompson-qzbjZ` |
| Latest commit (pre-audit) | `13093be` — "Guard local log reset mutation script" |
| Working tree (pre-change) | clean |
| Runtime stores present | `runtime/mvp_local.db` (266 KB, **git-ignored, non-canonical/seeded**), `logs/*.jsonl`, `runtime/operator_audit_log.jsonl` |
| Ignored runtime paths | `runtime/`, `logs/`, `data/` runtime artifacts (per `.gitignore`) |

## 2. Test baseline

| Command | Result |
| --- | --- |
| `python3.13 -m pytest -q -o addopts=""` | **6456 passed in 255.73s (exit 0)** |
| Python | Repo requires ≥3.12 (PEP 701 f-strings). Container default is 3.11.15 — **must run on `python3.13`** or 5 files fail to import. Audit + suite were run on `python3.13`. |
| Lint/type | No standalone mypy/ruff gate wired into CI for this run; `.pre-commit-config.yaml` exists. Not separately executed. |
| Frontend | `frontend/` is a Next.js app with vitest + Playwright specs (not executed in this backend-focused audit; loading-state specs are referenced as static evidence). |

## 3. Module map (six layers)

| Layer | Key modules |
| --- | --- |
| Choreography | `scripts/signal_engine.py`, `signal_refinery.py`, `signal_inbox_api.py`, `signal_inbox_bridge.py`, `refresh_live_signals.py`, `bulk_log_manual_trades.py`, `paper_reconciliation.py`, `reconciliation_queue.py`, `outcome_evidence.py`, `moltbook_api.py`, `moltbook_reconciliation_bridge.py`, `src/dashboard/streamlit_app.py`, `api_server.py` |
| Timing | `scripts/runtime_common.py` (`utc_timestamp`), `anti_staleness.py`, `paper_reconciliation.py` (`_compute_holding_period_days`), `docs/LIVE_SIGNALS_REFRESH_MODEL.md` |
| Position/Control | `scripts/signal_inbox_api.py` (`VALID_USER_STATUSES`, `VALID_RECONCILIATION_STATUSES`, `VALID_LOG_CANCEL_STATUSES`, `_TRADE_MODE_ALLOWED`), `paper_trade_ledger.py` (`_OUTCOME_STATUS_ALLOWED`), `signal_lifecycle_tracker.py`, frontend loading-state specs |
| Collision/Safety | `scripts/persistence.py` (`duplicate_fingerprints`, `INSERT OR IGNORE`, `global_securities`/`global_security_aliases`), `manual_trade_origin.py`, `advisory_contract.py`, `configs/no_execution_policy.yaml` |
| Simulation | `tests/helpers/large_signal_events_fixture.py`, `paper_trade_ledger.py`, `run_imported_backtest.py`, `import_outcomes_csv.py`, `outcome_evidence.py`, `calibration_gate.py`, `calibration_map.py` |
| Operations | `scripts/local_deploy_preflight.py`, `release_gate.py`, `governance_status.py`, `reset_local_logs.py` (+ `operator_permission_guard.py`), `gsheet_export.py`, `export_paper_trades.py`, `operator_audit_log.py`, `pipeline_health_report.py` |

## 4. Detected data stores

- **SQLite** `runtime/mvp_local.db` via `scripts/persistence.py` (schema: `signal_events`, `manual_trades`, `reconciliation_results`, `moltbook_entries`, `imported_outcomes`, `global_securities`, `global_security_aliases`, `duplicate_fingerprints`, `signal_cell_index`, …).
- **JSONL fallbacks** under `logs/` (`manual_trade_log.jsonl`, `trade_reconciliations.jsonl`, `manual_trade_cancellations.jsonl`, `moltbook_entries.jsonl`) and `runtime/operator_audit_log.jsonl`.
- **CSV/YAML** config + securities master under `config/`, `configs/`, `data/`.

## 5. Detected status enums / state vocabularies

| Object | Allowed values | Location |
| --- | --- | --- |
| Signal `user_status` | `pending, watchlist, human_review, rejected` | `signal_inbox_api.py:94` `VALID_USER_STATUSES` |
| Reconciliation outcome | `WIN, LOSS, BREAKEVEN, UNKNOWN` | `signal_inbox_api.py:97` `VALID_RECONCILIATION_STATUSES` |
| Log-cancel | `CANCELLED_DUPLICATE, CANCELLED_LOG` | `signal_inbox_api.py:107` `VALID_LOG_CANCEL_STATUSES` |
| Paper outcome | `"", OPEN, WIN, LOSS, BREAKEVEN, UNKNOWN` | `paper_trade_ledger.py:125` `_OUTCOME_STATUS_ALLOWED` |
| Trade mode | `PAPER, REAL_MANUAL, UNKNOWN` | `signal_inbox_api.py:1134` `_TRADE_MODE_ALLOWED` |
| Outcome source type | `REAL_MANUAL_TRADE, PAPER_TRADE, IMPORTED_BACKTEST, SYNTHETIC_FIXTURE` | `outcome_evidence.py` |
| Signal lifecycle stage | `IGNITION, VALIDATION, EXPANSION, CROWDING, EXHAUSTION, CLOSURE` | `signal_lifecycle_tracker.py:59` |

## 6. Detected provenance fields

- `trade_mode` (PAPER vs REAL_MANUAL), `created_via` (`manual_trade_log` gate), `logged_by` (synthetic markers excluded), `source_type` (outcome evidence), `advisory_status`/`execution_mode`/`broker_api_called`/`ai_execution_count` stamped on every read and write (`persistence.py:28`, `:546`), `imported_at` on imported outcomes, fixture `_perf_fixture_metadata` + `FIXTURE_EVENT_ID_PREFIX`.
- Disallowed-mixing rules enforced by `manual_trade_origin.EXCLUDED_TRADE_MODES` and `signal_inbox_api.SYNTHETIC_LOGGED_BY_MARKERS`.

## 7. Pre-existing tests covering these areas

`test_advisory_contract.py`, `test_anti_staleness_rules.py`, `test_reset_local_logs_guard.py`,
`test_release_gate.py`, `test_paper_reconciliation.py`, `test_reconciliation_queue.py`,
`test_import_outcomes_csv.py`, `test_run_imported_backtest.py`, `test_backtest_calibration.py`,
`test_calibration_gate.py`, `test_large_signal_events_fixture.py`,
`test_runtime_truth_purity_audit.py`, plus frontend
`manualTradeLog.loadingState.spec.tsx`, `moltbook.loadingState.spec.tsx`,
`live-signals.display-state.spec.tsx`, `AdvisoryEmptyState.spec.tsx`.

## 8. New artifacts added by this audit

- `scripts/coordination_audit.py` — the six-layer audit (read-only, advisory-only) + CLI.
- `tests/test_coordination_audit.py` — schema, scoring math, NO_DATA handling, report generation, determinism, and layer-guard proofs (24 tests).
- `tests/test_holding_period_invariants.py` — timing invariants for holding-period math (6 tests, SYNTHETIC fixtures).
- One-line behaviour fix: `_compute_holding_period_days` now returns `None` for exit-before-entry (no negative holding periods).
- `docs/coordination_audit.md` — generated report. `runtime/coordination_audit.json` — machine-readable (git-ignored).
