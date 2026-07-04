# FORENSIC AUDIT — SLEEPING PASSENGER

**Audit type:** Investor-grade, adversarial, production-readiness due diligence
**Audit window:** 2026-07-03 19:00 IST → 2026-07-04 (evidence timestamps noted per finding)
**Branch audited:** `live-data-config-sprint` (clean tree at audit start, HEAD `4bae13c`)
**Method:** 12 dedicated segment auditors + repo mapper (multi-agent), followed by main-line spot-verification of the highest-severity findings, full backend/frontend validation runs, read-only SQLite/git/schtasks forensics. No production behavior was changed. No secrets are printed anywhere in this report.

---

## 1. Executive Summary

Sleeping Passenger is a **functional but fragile MVP (overall 4.96/10)** — an unusually honest, unusually well-tested advisory scaffold wrapped around an empirical core that is currently **empty**. The single most important number in this audit is **N = 0**: zero closed, scored, real forward outcomes exist anywhere in the system (every outcome table queried read-only returns 0 rows; `data/calibration_corpus/live_outcomes.jsonl` has 0 lines). The 56 forward predictions locked on 2026-05-31 — the product's scarcest asset — expired on 2026-06-05 and were never matured, because the entire outcome-maturation loop was committed to branch `chore/real-forward-outcome-maturation` and **never merged**. The working tree cannot even read the DB table those predictions sit in.

The same disconnection pattern repeats across the system:

- The **risk engine monitors a phantom portfolio**: the only stop-breach/EXIT_NOW logic (`scripts/action_engine.py:404`) reads `moltbook/open_positions.json` — the ledger the project itself demoted as stale/phantom — while the canonical holdings file has **no stop/target fields at all**, is **6 weeks stale** (`run_date: 2026-05-22`), has `broker_confirmed: false` on all 10 rows, and includes two **4× leveraged NSE positions with no recorded stops**.
- The **daily advisory output has been empty for ~6 weeks**: all four `today_*` payloads sit on `STATIC_UNIVERSE_FALLBACK` (`is_live: false`), so fresh discovery honestly fail-closes with `NO_FRESH_DISCOVERY_GENERATED` every day.
- **Data sources die silently**: Kalshi and Polymarket have persisted zero rows since 2026-06-22 while health surfaces report "Source healthy (filtered)"; scheduled prices cover only 4 default ETFs, not the actual holdings.
- **Two flagship sprints live on unmerged branches**: the outcome-maturation loop AND the isolated-model-lanes/interpretation-defense scoring (`fb6f396`) exist only outside the canonical branch, so the documented system and the running system are different codebases.

The genuine strengths are real and rare for an MVP: a **machine-enforced no-execution lock** (repo-wide AST guard, per-role permission guard), **7,567 passing backend tests + 201 frontend tests with real assertions**, a **hash-chained audit log**, **clean secrets forensics** (the feared `pre-gitleaks-rewrite` history contained only synthetic test fixtures; nothing real was ever committed under any ref), and a pervasive honesty culture (fail-closed gates, ADVISORY_ONLY stamps, self-admitted placeholder labels).

**Verdict in one sentence:** this is a meticulously guarded measurement instrument that has never taken a measurement — the guards are more mature than the edge they protect, and one disciplined sprint (merge the maturation loop, repoint risk at real holdings, make silent failures loud) converts it from "honest but empty" to "measuring."

**Headline numbers:** Current **4.96/10** → one-sprint ceiling **~5.9** → near-term ceiling **6.50** → ultimate ceiling **8.01**.

---

## 2. Repo Evidence Map

Status legend: mature / partial / stub / missing / contradictory.

### 1 backend architecture — functional but inverted: 427 loose scripts/ files carry the bulk of logic while src/ is a thin core — partial, monolith-by-accretion
  * scripts/api_server.py:399 — FastAPI app assembly (3,359 lines, includes no-op FastAPI stand-in at :373); monolithic route hub
  * scripts/signal_inbox_api.py — 2,392-line signal-inbox + manual-trade + reconciliation API module
  * src/models/ + src/scoring/ + src/paper/ + src/storage/ — small typed core (signal/market/paper_trade models, sqlite/csv stores)
  * scripts/core/ — apollo_abort_guard.py, apollo_checklist_gate.py, external_evidence_router.py (guard layer)
  * scripts/core_module_boundary.py — registry that new scripts must join (boundary enforcement)
  * scripts/runtime_common.py — shared runtime helpers
  * scripts/config.py + scripts/config_contract.py — typed config contract
  * docs/ARCHITECTURE.md — stated architecture
### 2 frontend architecture — mature for a local single-operator UI; 'npm run lint' broken (Next 16 removed next lint); Streamlit duplicate surface unresolved
  * frontend/src/app/ — Next.js 16 app router, 16 routes verified by build (/, /cockpit, /nbi, /signal-inbox/[id], etc.)
  * frontend/src/lib/apiClient.ts — API client to local FastAPI
  * frontend/src/components/ — ~30 advisory-focused components (NoExecutionBanner.tsx, AdvisoryOnlyBadge.tsx, ManualTradeLogForm.tsx)
  * frontend/playwright.config.ts + frontend/e2e/ — Playwright e2e harness
  * frontend/vitest.config.ts — 201/201 vitest pass (35 files)
  * src/dashboard/streamlit_app.py — 195-line legacy Streamlit dashboard alongside Next.js (duplicate UI surface)
### 3 data ingestion paths — partial — many paths exist but historical evidence (memory + Kalshi truth split) shows live rows frequently DEGRADED/0; breadth exceeds proven live coverage
  * src/ingestion/kalshi_live_client.py + kalshi_live_loader.py — Kalshi live ingestion
  * src/ingestion/polymarket_public_client.py + scripts/fetch_polymarket.py — Polymarket public ingestion
  * src/ingestion/snapshot_writer.py — snapshot persistence
  * scripts/build_today_news_events.py + build_today_market_snapshot.py + build_today_price_movers.py — daily payload builders
  * scripts/live_source_runner.py + live_source_runner_phase2.py — source poll loop (two-phase split)
  * scripts/nbi_claim_ingestion.py + nbi_feed_bridge.py — NBI narrative ingestion
  * configs/sources.yaml — Phase-2 read-only source loader config
### 4 market data providers — partial — wide adapter surface but keyed providers unproven; real global coverage historically near-zero (C_global ~0 per memory), Yahoo is the load-bearing provider
  * scripts/yahoo_market_data_adapter.py — primary unkeyed price provider (only proven live canary per prior audits)
  * scripts/market_data_adapter.py — provider abstraction
  * scripts/kalshi_market_data_adapter.py + polymarket_gamma_adapter.py + polymarket_clob_adapter.py — prediction-market adapters
  * scripts/backfill_ohlcv_history.py + update_global_ohlcv_latest.py — OHLCV backfill/update
  * scripts/provider_verification.py + live_provider_compliance_trace.py — provider health checks
  * configs/api_keys.example.env — 10+ keyed providers declared (NewsAPI, Polygon, AlphaVantage, TwelveData, EDINET...) all placeholder-only
### 5 signal generation pipeline — partial/contradictory — pipeline is deep, but scripts/isolated_model_lanes.py and model_vote_aggregator.py (claimed in project memory as shipped) are ABSENT from the canonical branch — they exist only on unmerged branches (commit fb6f396 lineage, verified via git log --all); the documented lane architecture does not match the running tree
  * scripts/fresh_discovery_contract.py — 607-line provenance gate; fails closed with NO_FRESH_DISCOVERY_GENERATED
  * scripts/fresh_market_discovery.py — fresh candidate discovery
  * scripts/daily_synthesis_pipeline.py — 429-line daily synthesis orchestrator
  * scripts/chicken_gate.py + chicken_gate_daily_bridge.py — demote-only 4-stage freshness/asymmetry gate
  * scripts/signal_refinery.py + adaptive_signal_router.py — refinement/routing
  * scripts/run_five_model_synthesis.ps1 — five-model synthesis entry
  * scripts/nbi_daily_bridge.py + nbi_store.py — narrative-branch signal lane
### 6 scoring/probability/confidence — mature in breadth, weak in ground truth — scoring machinery is extensive but probability calibration rests on a near-empty outcome corpus (see area 13)
  * scripts/daily_scoring.py — daily scoring gate (imports candidate_memory_decay)
  * scripts/composite_edge_score.py — composite edge scoring
  * scripts/score_output_contract.py + derived_score_ledger.py + verify_derived_score_ledger.py — score contract and ledger verification
  * src/scoring/ — liquidity_score.py, net_signal_value.py, evidence_quality_layer.py, state_classifier.py
  * scripts/score_calibration.py + calibration_map.py — score-to-probability mapping
  * scripts/signal_arbitrage/ — Fable-5 multiplicative gating (final = merit x purity x ... invariant) + mythos.py front-end
  * scripts/model_scorecard.py + model_reliability_ledger.py — per-model reliability
### 7 risk & position sizing — intentionally absent by policy — no sizing engine exists (real-money sizing PROHIBITED); the no-execution lock is genuinely machine-checked, which is the strongest control in the repo
  * configs/no_execution_policy.yaml:12 — execution_gate: LOCKED; forbidden methods/imports machine-enforced by tests/test_no_execution_policy_config.py
  * scripts/execution_governance.py — governance enforcement
  * docs/OPERATOR_LOAD_AND_SURVIVAL_SIZING.md — sizing doctrine (doc only)
  * docs/PRE_REAL_MONEY_READINESS_GATE.md — real-money gate doc
  * scripts/promotion_downgrade.py — grade demotion logic
  * scripts/position_conflict_detector.py — conflict detection on advisory positions
### 8 portfolio state management — contradictory/stale — well-designed truth-gate code, but the canonical holdings file itself is dated 2026-05-22 with broker_confirmed:false on positions; truth freshness is not enforced
  * data/daily_payload/verified_current_holdings.json:2 — canonical OPEN-position truth, but run_date is 2026-05-22 (6 weeks stale as of 2026-07-03)
  * scripts/portfolio_truth_gate.py:90 — build_portfolio_truth_gate + classify_ticker/may_generate_management_action
  * scripts/position_truth_resolver.py — truth resolution across sources
  * data/daily_payload/closed_positions.json + sold_positions.json + do_not_treat_as_open.json — state partitions
  * scripts/portfolio_truth_integrity.py — integrity checks
  * moltbook/ — demoted historical-only ledger
### 9 Google Sheets sync — partial — one-directional-ish sync dependent on a locally running API server and gspread lazy imports; no evidence of scheduled/automated Sheets runs; CSV export path is more mature than live Sheets path
  * scripts/sync_google_sheet_reconciliation.py:24 — gspread service-account read, writeback columns, POSTs to http://127.0.0.1:8000/reconciliation/auto-update (740 lines)
  * scripts/gsheet_export.py:230 — CSV log exporter with _neutralize_csv_cell injection defense and advisory-status enforcement (446 lines)
  * frontend/src/app/reconciliation/ — reconciliation UI
  * scripts/reconciliation_queue.py + repair_manual_trade_reconciliation.py — queue and repair
### 10 manual trade logging — mature — full CRUD + provenance + quarantine tooling; history of fake demo rows shows why quarantine exists
  * scripts/signal_inbox_api.py:1207 — log_manual_trade endpoint (plus cancel/list/export wired in api_server.py:77-112)
  * frontend/src/app/manual-trade-log/ + frontend/src/components/ManualTradeLogForm.tsx — operator UI
  * scripts/bulk_log_manual_trades.py — bulk import
  * scripts/backfill_manual_trade_log_provenance.py — provenance backfill
  * scripts/quarantine_fake_manual_trades.py — fake-row quarantine (813 demo rows previously quarantined)
  * scripts/manual_trade_origin.py — origin tagging
### 11 exit/TP/SL/runner logic — stub-by-design — no automated TP/SL/runner engine exists (consistent with advisory-only), but there is also no structured advisory exit-plan object per position; exits are manual and paper close is a one-function affair
  * src/paper/paper_position_tracker.py:10 — close_paper_trade(exit_price, simulated_friction): the only concrete exit mechanic
  * src/paper/paper_trade_engine.py:53 — compute_paper_pnl
  * scripts/action_engine.py — advisory action generation referencing stop/target fields
  * docs/hedge_trade_entry_playbook.md — entry/exit doctrine (doc only)
  * scripts/temporal_position_engine.py — time-based position logic
  * scripts/moltbook_reconciliation_bridge.py — closed-position reconciliation
### 12 evidence & audit logging — mature — tamper-evident hash chain is a genuine strength; evidence volume, not machinery, is the constraint
  * scripts/audit_log.py:64 — hash-chained JSONL audit log (canonical_json + compute_event_hash + previous_hash) at logs/audit_log.jsonl, with metadata redaction
  * scripts/evidence_bridge.py + outcome_evidence.py + outcome_evidence_extractor.py — evidence pipeline
  * data/evidence/ — thesis_contracts + edgar_counterparty_edges.jsonl
  * scripts/nbi_evidence_factory.py + nbi_track_record_ledger.py — NBI evidence/track-record
  * docs/EVIDENCE_PIPELINE.md + docs/OUTCOME_EVIDENCE_MODEL.md — evidence doctrine
  * scripts/artifact_coherence_check.py — artifact coherence guard
### 13 calibration & outcome tracking — machinery mature, data starved — zero closed live outcomes on disk; the system's core empirical claim (calibrated signals) is currently unfalsifiable with N=0 live outcomes
  * data/calibration_corpus/forward_snapshots.jsonl — 2 rows; live_outcomes.jsonl — 0 rows; retrocast.jsonl — 56 rows (wc -l verified)
  * scripts/run_calibration_pipeline.py + model_calibration.py — calibration pipeline (historically reports INSUFFICIENT_EVIDENCE)
  * scripts/snapshot_maturity_scanner.py:65 — PENDING/matured outcome scanning
  * scripts/calibration_gate.py + calibration_map.py — gates and mapping
  * scripts/import_outcomes_csv.py + review_signal_outcomes.py — outcome intake
  * scripts/live_calibration_report.py + nbi_calibration_report.py — reporting
  * data/calibration_corpus/pm_probability_ledger.jsonl — 846 prediction-market probability rows (largest real dataset)
### 14 scheduler/daily discovery/operator loops — partial/operational — genuine OS-level scheduling with honest verification design, but entirely single-Windows-machine; no server-grade scheduling or failure alerting beyond local checks
  * scripts/nbi_scheduler.py:101 — schtasks install/remove/verify (daily 08:30, truth = schtasks query, not module existence)
  * scripts/daily_model_operating_loop.py + daily_synthesis_pipeline.py — daily loop orchestrators
  * scripts/windows/register_live_signal_refresh_task.ps1 + refresh_live_signals_every_6h.ps1 — Windows task registration
  * scripts/check_live_signal_refresh_task.py — task health check
  * scripts/nbi_live_ops_cockpit.py + frontend/src/app/cockpit/ — live ops cockpit
  * scripts/daily_signal_readiness.py + minimum_daily_universe.py — readiness gates
  * scripts/run_live_refresh.py + refresh_live_signals.py — refresh entrypoints
### 15 tests & CI — mature — unusually strong test discipline for an MVP; lint pipeline broken is the only tooling gap; caveat: massive test count partly tests advisory scaffolding, not market performance
  * tests/ — 443 files, 7567 passed / 3 skipped in 14m14s (validated this session)
  * frontend vitest — 201/201 pass; next build 16 routes OK; npm run lint BROKEN (Next 16 removed next lint)
  * .github/workflows/pytest.yml:39 — full pytest + frontend build on ubuntu-latest
  * .github/workflows/e2e.yml:17 — Playwright e2e weekly cron (Tue 07:23 UTC) + owner-auth flow
  * .github/workflows/kante_defensive_gate.yml — defensive gate workflow
  * .github/workflows/dep_audit.yml — dependency audit
  * scripts/audit_github_actions_pinning.py — actions-pinning self-audit
### 16 config & environment handling — contradictory — two config directories with a colliding sources.yaml filename is an operator trap and a code-review smell; the typed contract layer itself is sound
  * config/ — 20 files (thresholds.yaml, sources.yaml, llm_provider_config.json, archetype configs)
  * configs/ — 7 files (no_execution_policy.yaml, sources.yaml, api_keys.example.env, jurisdictions.yaml)
  * config/sources.yaml vs configs/sources.yaml — SAME NAME, DIFFERENT SCHEMAS (polymarket URLs vs Phase-2 advisory loader config; diff verified)
  * scripts/config.py + scripts/config_contract.py — typed config contract (kind=secret names feed secret_provider)
  * scripts/daily_discovery_config.py — discovery config
  * docs/ENVIRONMENT_CONTRACT.md — environment doctrine
### 17 security/secrets handling — mature for local single-operator scope — but the pre-gitleaks-rewrite branch still exists locally referencing pre-rewrite history, and default secret mode is plain .env (documented lower-security)
  * scripts/secret_provider.py:8 — env / windows-credential-manager custody modes, hydrate_environment(), never logs values
  * configs/api_keys.example.env — placeholder-only key template (verified no real values); .env/.env.local/secrets/ untracked per git ls-files
  * .gitignore:4-29 — runtime/, logs/, .env* excluded
  * git branch backup/pre-gitleaks-rewrite — evidence of a PAST secrets-in-history incident and rewrite
  * docs/SECRET_CUSTODY.md + docs/INCIDENT_LOCKDOWN.md — custody and lockdown runbooks
  * scripts/gsheet_export.py:230 — CSV injection neutralization
  * frontend LocalApiTokenPanel.tsx + docs/E2E_OWNER_AUTH.md — owner-token auth surface
### 18 deployment/runtime scripts — partial — thoroughly scripted for one Windows laptop; zero actual hosted/multi-user deployment; SQLite + local schtasks is the entire production story
  * scripts/windows/start_mvp_stack.ps1 + start_mvp_stack_silent.ps1 — local stack launch
  * scripts/windows/register_mvp_startup_task.ps1 + register_mvp_silent_startup_task.ps1 — boot-time tasks
  * scripts/windows/local_frontend_reverse_proxy.py + add_sleepingpassenger_host_alias.ps1 — local reverse proxy + hosts alias
  * scripts/local_deploy_preflight.py — deploy preflight
  * scripts/backup_db.py + scripts/windows/backup_sleepingpassenger_db.ps1 — backup path
  * docs/HOSTED_DEPLOYMENT_PLAN.md + docs/POSTGRES_MIGRATION_PLAN.md — hosted deployment exists ONLY as plans
  * runtime/ — gitignored artifact sprawl (dozens of report JSONs at top level)
### 19 documentation & operator UX — partial — enormous volume but doctrine-heavy; ratio of reflection/doctrine docs to operational docs suggests docs written for the author, not an incoming operator; discoverability poor without SCRIPT_INVENTORY
  * docs/OPERATOR_QUICKSTART.md — PowerShell operator quickstart
  * docs/ARCHITECTURE.md + ARCHITECTURE_BOUNDARIES.md + CORE_ENGINE_MANIFEST.md — architecture docs
  * docs/ADVISORY_ONLY_SAFETY_MODEL.md + ADVISORY_DISCLOSURE.md — safety/compliance posture
  * docs/LOCAL_RECOVERY_RUNBOOK.md + PRIVATE_RECOVERY_RUNBOOK.md + BACKUP_RESTORE.md — recovery runbooks
  * frontend/src/app/help/ — in-app help route
  * docs/SCRIPT_INVENTORY.md + module_census.md — attempts to index the 427-script sprawl
  * docs/ — ~140 markdown files total, many doctrine/reflection docs (e.g. COMPLEX_SYSTEMS_SIGNAL_DOCTRINE.md, signal_metabolism.md)
### 20 dead code/duplicates/contradictions — contradictory — significant accretion debt; the repo carries its whole development history in-tree
  * adapters/ + governance/ + scripts/api/routers/ — three EMPTY directories (0 tracked files; scripts/api/routers implies an abandoned router refactor)
  * scripts/isolated_model_lanes.py + model_vote_aggregator.py — claimed shipped in project memory (2026-06-07) but git log shows NO history for either path: memory/doctrine contradicts the tree
  * config/sources.yaml vs configs/sources.yaml — filename collision with different schemas
  * prompts/ — 8+ versioned paper_trading_prompt_v51..v57plus files; docs/mvp_master_archive.html + pipeline_architecture_v57.html — stale generated artifacts
  * backup/20260420-* + tmp/paper_trades_2026-06-02.tsv + linkedin/*.html — snapshots and marketing HTML inside the product repo
  * scripts/candidate_memory_decay.py AND candidate_memory_decay_v2.py — both imported (daily_scoring/why_today use v1, others v2): parallel versions live simultaneously
  * src/dashboard/streamlit_app.py — legacy dashboard duplicating the Next.js frontend
  * archived_experimental/_quarantine + tribev2 — quarantined experiments still in tree

DEAD CODE CANDIDATES:
  - adapters/ — empty tracked-nothing directory
  - governance/ — empty directory (referenced in repo layout, contains no files)
  - scripts/api/routers/ — empty directory from abandoned router refactor; api_server.py wires routes directly
  - backup/20260420-070849 and backup/20260420-092312 — in-repo filesystem snapshots from April 2026
  - tmp/paper_trades_2026-06-02.tsv — stray data file
  - linkedin/linkedin_portfolio.html, linkedin_scorecard.html, linkedin_scorecard_v2.html — marketing artifacts in product repo
  - prompts/paper_trading_prompt_v51.txt through v57plus.txt — superseded prompt versions (8+ files)
  - docs/mvp_master_archive.html, docs/pipeline_architecture_v57.html, docs/pipeline_full_architecture_v57.html — stale generated HTML archives
  - scripts/candidate_memory_decay.py — v1 kept alongside candidate_memory_decay_v2.py with split importers (daily_scoring.py/why_today.py on v1)
  - src/dashboard/streamlit_app.py — legacy Streamlit dashboard duplicating the Next.js UI
  - archived_experimental/_quarantine and archived_experimental/tribev2 — quarantined experiments still shipped in tree
  - config/sources.yaml vs configs/sources.yaml — one of the colliding configs should be renamed/retired

ARCH VERDICT: Sleeping Passenger is a single-operator, single-Windows-machine advisory system whose genuine strengths are defensive: a machine-enforced no-execution lock (configs/no_execution_policy.yaml + dedicated tests), a hash-chained audit log (scripts/audit_log.py), fail-closed provenance gates (fresh_discovery_contract.py), and an unusually large green test suite (7567 backend + 201 frontend). Its structural weaknesses are equally clear: the architecture is inverted (427 loose scripts in scripts/ carry the business logic while src/ is a thin shell), there are two colliding config directories, three empty directories from abandoned refactors, and heavy in-tree accretion (backups, prompt versions, marketing HTML, a duplicate Streamlit dashboard). Most damning for an investor: the empirical core is unproven — data/calibration_corpus holds 0 live outcomes and 2 forward snapshots, the canonical holdings truth file is dated 2026-05-22 (6 weeks stale), and modules that project doctrine claims were shipped (isolated_model_lanes.py, model_vote_aggregator.py) have no git history in the repo. This is a meticulously guarded paper system whose guards are more mature than the signal edge they protect — roughly a 5.5-6.5 band: functional-but-fragile MVP verging on serious paper-trading system, held back by zero closed-loop live evidence, stale portfolio truth, and unsustainable script sprawl.


---

## 3. Commands Run and Results

| # | Command | Result | Key output | Blocks production-readiness? | Segments affected |
|---|---------|--------|-----------|------------------------------|-------------------|
| 1 | `.venv/Scripts/python.exe -m pytest tests -q` | **PASS** (exit 0) | **7,567 passed, 3 skipped** (POSIX-permission skips on Windows), 14m14s | No — strongest asset | J↑, F↑ |
| 2 | `npm test` (frontend, vitest) | **PASS** | 201/201 tests, 35 files, 40.3s | No | G↑, J↑ |
| 3 | `npm run build` (Next.js 16) | **PASS** | 16 routes compiled (15 static + 1 dynamic) | No | G↑ |
| 4 | `npm run lint` | **FAIL** | `next lint` removed in Next 16 → "Invalid project directory" | No — tooling migration issue; migrate to ESLint CLI | J↓, G↓ (minor) |
| 5 | `git ls-files .env .env.local secrets/` | **CLEAN** | Only `.env.example` tracked; `.env`, `.env.local`, `secrets/` untracked | No | K↑ |
| 6 | `git log --all -- .env secrets/ .env.local` | **CLEAN** | Empty — never committed under any ref, including `backup/pre-gitleaks-rewrite` | No | K↑ |
| 7 | `Get-ScheduledTask` / `Get-ScheduledTaskInfo` | **MIXED** | `SleepingPassengerLiveSignalRefresh`: ran 2026-07-03 21:30, exit 0, 6h cadence. `SleepingPassenger_NBI_DailyLoop`: **never run as of audit**; first-ever scheduled execution 2026-07-04 09:11 (exit 0, delayed catch-up from 08:30). Orphaned `PipelineV57LocalMVPSilent` points at a deleted repo and fails every logon | Partially — one healthy loop, one 1-run-old loop, zero alerting | I |
| 8 | Read-only SQLite (`mode=ro`) on `runtime/mvp_local.db` | **DAMNING** | `external_evidence_outcomes=0`, `imported_outcomes=0`, `nbi_track_record=0`; `decision_probability_snapshots`: 480 rows, 56 forward-eligible, **0 with outcome_label**, max horizon close 2026-06-05 (28+ days overdue) | **Yes** — the evidence core is empty | D, B |
| 9 | `git branch -a --contains 4e4785d` | **CONFIRMED GAP** | Maturation-loop commit reachable only from `chore/real-forward-outcome-maturation` (local + origin); `scripts/run_daily_outcome_maturation.py` absent from working tree | **Yes** | D, I |
| 10 | Artifact freshness audit (`ls -lt` on `data/`, `logs/`, `runtime/`) | **MIXED** | `logs/live_signal_refresh*` + `runtime/mvp_local.db` current (same-day); `data/daily_payload/*` **26 days stale** (2026-06-07); `logs/sheet_sync_reconciliation_audit.jsonl` + `refresh_watchdog.log` frozen at 2026-05-26 | **Yes** — truth payloads stale | A, C, E, H, I |

Environment: Python 3.13.4 (repo venv), pytest 9.0.3, Node/Next 16, Windows 11. Install-from-scratch was assessed by reading (not executed): see SP-findings on packaging, interpreter pinning, and requirements gaps.

---

## 4. Segmented Scorecard

Scale: 0–2 toy · 2.1–4 prototype · 4.1–6 functional-but-fragile MVP · 6.1–7.5 serious paper-trading system · 7.6–8.5 investor-demo ready · 8.6–9.2 early production-grade · 9.3–10 institutional.

| Seg | Segment | Weight | Current | Near-Term Ceiling | Ultimate Ceiling | Gap→NT | Gap→Ult | W×Cur | W×NT | W×Ult | Confidence |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A | Product / Operator Value | 10% | 4.7 | 6.3 | 8 | +1.6 | +3.3 | 0.470 | 0.630 | 0.800 | Medium |
| B | Signal Quality / Model Logic | 12% | 4.8 | 6 | 7.7 | +1.2 | +2.9 | 0.576 | 0.720 | 0.924 | High |
| C | Risk Engine / Portfolio Discipline | 12% | 3.8 | 5.8 | 7.5 | +2.0 | +3.7 | 0.456 | 0.696 | 0.900 | High |
| D | Calibration / Outcome Evidence | 12% | 3.6 | 5.5 | 7.5 | +1.9 | +3.9 | 0.432 | 0.660 | 0.900 | High |
| E | Data Integrity / Provider Reliability | 9% | 4.8 | 6.3 | 8 | +1.5 | +3.2 | 0.432 | 0.567 | 0.720 | High |
| F | Backend Architecture | 8% | 4.7 | 6 | 7.5 | +1.3 | +2.8 | 0.376 | 0.480 | 0.600 | High |
| G | Frontend / UX / Operator Workflow | 7% | 6.7 | 7.6 | 8.5 | +0.9 | +1.8 | 0.469 | 0.532 | 0.595 | High |
| H | Google Sheets / External Sync | 7% | 4.4 | 6.3 | 8 | +1.9 | +3.6 | 0.308 | 0.441 | 0.560 | High |
| I | Scheduler / Runtime / Automation | 6% | 4.4 | 6.5 | 8 | +2.1 | +3.6 | 0.264 | 0.390 | 0.480 | High |
| J | Testing / CI / Regression Defense | 7% | 7.4 | 8.3 | 9 | +0.9 | +1.6 | 0.518 | 0.581 | 0.630 | Medium |
| K | Security / Secrets / Privacy | 5% | 7.8 | 8.6 | 9.3 | +0.8 | +1.5 | 0.390 | 0.430 | 0.465 | Medium |
| L | Documentation / Investor Readiness | 5% | 5.4 | 7.5 | 8.7 | +2.1 | +3.3 | 0.270 | 0.375 | 0.435 | High |
| **Σ** | **Overall** | **100%** | **4.96** | **6.50** | **8.01** | **+1.54** | **+3.05** | 4.961 | 6.502 | 8.009 | — |

**Overall (weighted):**

```text
Overall_Current_Score      = Σ(weight × current)  = 4.96
Overall_Near_Term_Ceiling  = Σ(weight × near)     = 6.50
Overall_Ultimate_Ceiling   = Σ(weight × ultimate) = 8.01
Overall_Gap_to_Near_Term   = 6.50 − 4.96          = 1.54
Overall_Gap_to_Ultimate    = 8.01 − 4.96          = 3.05
```

### Per-segment detail

**A. Product / Operator Value — 4.7 (near 6.3 / ult 8.0, Medium confidence).** Safety and honesty scaffolding is genuinely strong (ADVISORY_ONLY stamps everywhere, explicit do-not-buy states, fail-closed endpoints, two OS scheduled tasks). But the decision-grade content is nearly empty: zero fresh-discovery candidates since 2026-05-22, holdings truth 6 weeks stale, and the operator experience is fragmented across Next.js + runtime markdown artifacts + Streamlit + a 229-line manual checklist (~15–20 PowerShell commands/day). *Fastest unlock:* wire one live provider end-to-end into the `today_*` payloads and refresh holdings truth. *Blockers:* no VERIFIED_LIVE provider feeding discovery; runtime artifact hygiene (tests write to served paths); no holdings refresh process.

**B. Signal Quality / Model Logic — 4.8 (near 6.0 / ult 7.7, High).** Gate engineering is good (chicken gate demote-only invariants tested; `signal_arbitrage` multiplicative gating guarantees `final ≤ merit` structurally). But `compute_model_probability` is a self-labeled **placeholder** linear blend (`src/scoring/net_signal_value.py:10-15`), "mispricing" is |placeholder − market| (manufactured edge), the calibration corpus is fixtures-plus-emptiness, and **6+ parallel scoring vocabularies across 48 registered models** are reconciled only by a markdown doc. Five sprints of scoring logic are stranded on an unmerged branch. *Fastest unlock:* relabel `model_probability` → `heuristic_prior` everywhere, gate mispricing-derived reason codes behind an INSUFFICIENT_CALIBRATION guard, merge-or-retire the stranded branch.

**C. Risk Engine / Portfolio Discipline — 3.8 (near 5.8 / ult 7.5, High).** The no-execution prohibition is structural and real (repo-wide AST guard + per-role permission guard) — the segment's only strong pillar. Everything else is risk theater pointed at demo data: stop/TP monitoring reads the demoted phantom ledger; canonical holdings carry zero stop/target/invalidation fields; `max_open_positions=6` is counted against the wrong source while the real book holds 10; two 4×-leveraged INR positions are the least-instrumented in the book; no drawdown monitor exists outside backtests. *Fastest unlock:* add stop fields to holdings truth, repoint `action_engine` at it with a hard freshness gate, quarantine `moltbook/open_positions.json` from action selection.

**D. Calibration / Outcome Evidence — 3.6 (near 5.5 / ult 7.5, High).** **N = 0**, verified by direct read-only SQLite queries. The Brier/logloss/ECE machinery is well built and honest (nothing papers over the emptiness — gates correctly report NOT_READY / INSUFFICIENT_EVIDENCE), but the only data ever fed to it is fixtures; the 56 locked forward predictions expired unmatured because the maturation loop never merged; the daily scheduler runs no outcome-closing step; prediction/outcome rows are mutable with no tamper evidence (bare re-runnable UPDATE, no hash chain over the corpus). *Fastest unlock:* merge the maturation loop, wire it into the 08:30 task, retro-mature the 56 orphaned snapshots → N goes 0 → ~56 with pre-registered timestamps.

**E. Data Integrity / Provider Reliability — 4.8 (near 6.3 / ult 8.0, High).** Good plumbing (16,955 audited source runs, per-row `fetched_at`, honest skip taxonomy, read-only signed Kalshi client), thin and partly stale water: Kalshi/Polymarket zero-persisted for 11 days while reported healthy; live prices cover 4 default ETFs — not the holdings, not the 56-symbol multi-country security master; GDELT timed out with no same-cadence news fallback; `anti_staleness.py` cannot detect that its own input files are 26 days old; no retry/backoff in adapters. *Fastest unlock:* holdings-driven ticker list for the scheduled refresh + a `rows_persisted` axis that flips zero-yield sources to DEGRADED.

**F. Backend Architecture — 4.7 (near 6.0 / ult 7.5, High).** An accretion with governance bolted on: ~184k LOC across 495 files in a flat non-package `scripts/` (231 `sys.path` hacks), vestigial `src/` that imports back into `scripts/` (inverted layering), a 3,359-line API monolith with 63 routes and an abandoned empty `scripts/api/routers/` scaffold, SQLite opened directly in 54 files (7 set `busy_timeout`; 53 hardcode the DB name), two colliding config dirs. Redeeming: the 7,567-test suite makes refactoring safe; `persistence.py` is genuinely hardened; the governance registries show real self-awareness (while flattering themselves — 399/443 modules bucketed "SUPPORT", self-scored hygiene 9.97). *Fastest unlock:* pyproject.toml + package-ify + mechanically kill the sys.path hacks under green tests.

**G. Frontend / UX / Operator Workflow — 6.7 (near 7.6 / ult 8.5, High).** The strongest product surface: honest MOCK_FALLBACK/offline banners, a calibration badge that literally says "Do not size from this score" (n=0), DEGRADED taxonomy with recovery commands, real component tests. Holes: the flagship `/nbi` page is an **orphan route** (absent from Sidebar navigation); the NBI cockpit renders artifact-served health with **zero staleness check** (a dead scheduler would show HEALTHY 10/10 forever); the product's core risk vocabulary (DEFENSIVE, gate-refused, INSUFFICIENT_EVIDENCE) has zero frontend surface; the legacy Streamlit app bypasses every truth gate; sidebar "AI Executions: 0" is a hardcoded literal styled as live status. *Fastest unlock:* add `/nbi` to nav + render `generated_at` with age-based stale warnings (~30 lines).

**H. Google Sheets / External Sync — 4.4 (near 6.3 / ult 8.0, High).** Narrower than the product claim: the "sync" is one inbound script whose backend endpoint appends an audit JSONL line **that nothing consumes** — sheet-driven CLOSE_TRADE/STOP_HIT never reach holdings truth or the reconciliation queue. Only 1 of 4 actions is idempotent; neither sync client sends the Bearer token the endpoints require when auth is on; the endpoint reports "recorded" even when the audit write fails; hard-coded A:Z column offsets with no schema-drift check; no evidence it has ever run against a real sheet (audit log frozen 2026-05-26). The manual trade log itself is strong (Idempotency-Key replay, soft-cancel provenance, quarantine tooling). *Fastest unlock:* Bearer token + client dedupe key + terminal-status skip + wire the audit trail into the reconciliation queue.

**I. Scheduler / Runtime / Automation — 4.4 (near 6.5 / ult 8.0, High).** One loop is real (6-hour refresh: ran on schedule at audit time, honest logs). The NBI daily 08:30 task had **never fired** at audit time — the recorded "HEALTHY 10/10" came from manual runs; update: it fired for the first time 2026-07-04 09:11 (exit 0, delayed catch-up), which mildly de-risks installation but not the structural findings: `nbi_scheduler.py:573` returns **exit 0 for BROKEN runs** (compares against a status value `run_once` never sets — confirmed in code), there is **zero push alerting** (the watchdog died 2026-05-25 and its script no longer exists), the daily-payload/chicken-gate/holdings chain has **no scheduler entry at all**, no lock files, tasks pinned to non-venv interpreters, and an orphaned logon task fails at every boot. *Fastest unlock:* fix the exit-code bug + one staleness alarm surfaced in the existing UI panel.

**J. Testing / CI / Regression Defense — 7.4 (near 8.3 / ult 9.0, Medium).** The tests are real, not theater — every sampled file asserts behavior with negative paths (mid-batch POST failure, DB-lock contention, seeded property fuzzing, injected fake runners); conftest.py isolates the runtime DB per test (born from a real pollution incident); CI is SHA-pinned, least-privilege, runs the full suite on push/PR. Gaps are structural: **zero coverage instrumentation** (57 of 413 top-level scripts provably untested), merge gating unverifiable (and the observed dev flow auto-pushes, making CI post-hoc), no frontend-against-real-backend integration test, lint dead on both stacks. *Fastest unlock:* branch protection + pytest-cov floor.

**K. Security / Secrets / Privacy — 7.8 (near 8.6 / ult 9.3, Medium).** The strongest segment. Git-history forensics came back clean: the `pre-gitleaks-rewrite` branch is local-only, the rewrite diff touched only `.gitleaksignore` fingerprints, the findings were synthetic REDACTED test placeholders, and no real secret was ever committed under any of ~150 refs. CI hardened (SHA-pinned actions, `persist-credentials:false`, gitleaks full-history scan, pip-audit, npm audit). Deductions: gitleaks allowlist config stranded on an unmerged branch; deps range-pinned rather than locked; real personal broker holdings are git-tracked in a private repo one visibility flip from public. *Fastest unlock:* merge the gitleaks config + capture a green full-history scan as evidence.

**L. Documentation / Investor Readiness — 5.4 (near 7.5 / ult 8.7, High).** Enormous corpus (12 root docs + ~140 in `docs/`) with a genuinely strong honesty culture (MODEL_CARD.md is investor-grade candid). But the first documents a skeptic reads are stale and factually wrong **today**: TESTING.md claims ~100 test files and "no Vitest/Playwright installed" (reality: 443 files, 7,567 + 201 passing); two dueling self-audits (4.8/10 vs 8.2/10) sit unreconciled and undated; README's route table lists 9 of 16 pages and never mentions the flagship June/July systems (NBI, chicken gate, Mythos — zero README hits); SETUP.md contradicts README on Python version and auth. An investor finds contradictions in ten minutes. *Fastest unlock:* one doc truth-sync sprint (real counts, HISTORICAL markers on stale audits, route table, glossary for the codenames).

---

## 5. Weighted Score Math

Formulas applied (see scorecard table for per-segment values):

```text
Gap_to_Near_Term_Ceiling      = Near_Term_Ceiling − Current_Score        (per segment, column Gap→NT)
Gap_to_Ultimate_Ceiling       = Ultimate_Ceiling − Current_Score         (per segment, column Gap→Ult)
Weighted_Contribution         = Segment_Weight × Current_Score           (column W×Cur)
Weighted_Near_Term_Contribution  = Segment_Weight × Near_Term_Ceiling    (column W×NT)
Weighted_Ultimate_Contribution   = Segment_Weight × Ultimate_Ceiling     (column W×Ult)

Overall_Current_Score     = 0.470+0.576+0.456+0.432+0.432+0.376+0.469+0.308+0.264+0.518+0.390+0.270 = 4.96
Overall_Near_Term_Ceiling = 0.630+0.720+0.696+0.660+0.567+0.480+0.532+0.441+0.390+0.581+0.430+0.375 = 6.50
Overall_Ultimate_Ceiling  = 0.800+0.924+0.900+0.900+0.720+0.600+0.595+0.560+0.480+0.630+0.465+0.435 = 8.01
Overall_Gap_to_Near_Term  = 6.50 − 4.96 = 1.54
Overall_Gap_to_Ultimate   = 8.01 − 4.96 = 3.05
```

Reading the math: the three heaviest-weighted segments (B, C, D — 36% of the score) are also the three weakest content segments (4.8, 3.8, 3.6), which is why the overall lands at 4.96 despite J/K/G being investor-demo grade. The gap decomposition says the same thing the findings say: **the fastest weighted gains are in D (+0.228 weighted per sprint-reachable point), C (+0.240), and E (+0.135)** — evidence, risk truth, and data liveness.

---

## 6. Bottlenecks (what caps everything else)

1. **The unmerged maturation loop** (SP-002) — caps D, and through it every credibility claim. The code exists, tested, on `chore/real-forward-outcome-maturation`; the working tree can't close an outcome. This is the system's single point of maximum leverage.
2. **Stale, field-poor holdings truth** (SP-005/SP-010/SP-011) — caps C and A. Every downstream discipline (stops, capacity, exposure, reconciliation) is computed against a 6-week-old hand-edited snapshot with no stop fields and no freshness gate.
3. **No live provider feeding discovery** (SP-006) — caps A and B. Fresh discovery fail-closes daily; the product's morning output is structurally empty until one provider is wired end-to-end (the Yahoo canary was already proven in prior sessions).
4. **Silent-death health taxonomy** (SP-016/SP-017) — caps E and I. `ok_filtered` with zero persisted rows reads as healthy; nothing distinguishes "fetched" from "landed."
5. **Flat 184k-LOC non-package** (SP-020/SP-021/SP-022) — caps F and long-run velocity; not the next sprint's problem, but every sprint pays its tax.

## 7. Gaps (what simply doesn't exist)

- Outcome closing in any scheduled path; benchmark comparison (SPY/DAX) in the live outcome path; a resolution loop for the 846-row live Kalshi probability ledger (the largest real dataset in the repo, currently unusable for Brier).
- Stops/targets/invalidation on canonical holdings; capital-based position sizing math (bands only — partially by design); live drawdown monitoring; currency-normalized exposure aggregation.
- Push alerting of any kind (all failure signals are pull-based); lock files on scheduled runners; schema-drift validation on the Sheet; a consumer for the sheet-sync audit trail.
- Coverage instrumentation; frontend-against-real-backend integration test; Python linting in CI; a working frontend lint command.
- An investor-facing document that matches the current codebase.

## 8. Leakages (value silently draining)

- **Evidence leakage:** 56 pre-registered forward predictions expired unmatured (a month of the scarcest asset, forfeited); the NBI daily loop produces artifacts with no outcome-closing step; 65 REAL_MANUAL imported trades contribute zero outcomes.
- **Signal leakage:** test fixtures wrote to the exact `runtime/` artifacts the API serves (fixture ticker MACRO1 with fake evidence URL was live on `/nbi` from 2026-07-03 19:11 until overwritten 2026-07-04 09:31 — mechanism confirmed, recurrence guaranteed without a fix); stale `today_*` filenames invite misreading month-old data as current.
- **Capital-risk leakage:** stop monitoring on phantom positions while real leveraged positions go un-instrumented; capacity gate counting the wrong book (10 real vs cap 6, invisible).
- **Runtime leakage:** BROKEN scheduler runs exit 0; zero-persist provider runs classified healthy; news fallback chain not exercised in the scheduled cadence.
- **Calibration leakage:** placeholder probability drives "mispricing"/PAPER_EDGE_DETECTED reason codes; CE thresholds justified by three hindsight anecdotes; heuristics wearing statistical vocabulary.
- **Architecture leakage:** two flagship sprints stranded on unmerged branches; decay math implemented 4×; two config dirs with colliding `sources.yaml`; dead directories from abandoned refactors.

## 9. Vulnerabilities (security/privacy)

No Critical security findings. Verified clean: no tracked secrets, no secrets in history under any ref, CI hardened, localhost-only defaults, token stored hashed, CSV-injection defense in exports. Open items (Medium): gitleaks allowlist config unmerged (HEAD runs a raw scan whose CI status is unverifiable locally — `gh` not installed); dependencies range-pinned, not hash-locked; personal broker holdings are git-tracked content in a private repo (a deliberate choice, but one visibility mistake from exposure — consider moving to untracked local data with a tracked schema); both sync clients would fail against a token-secured API (security and sync currently can't be on together, which invites running with auth off).

---

## 10. Forensic Issue Register

**Verification statuses:** CONFIRMED = reproduced directly in this session's main line (read-only). CORROBORATED = auditor evidence consistent with independent same-session observations. AGENT-EVIDENCED = single-auditor evidence, plausible, not independently re-run (the adversarial verification wave was cut by usage limits; treat as high-probability but re-check before acting).

### 10.1 Critical and High (39)

### SP-001 — Stop/TP monitoring runs on the demoted phantom ledger, not real holdings

- **Category:** capital-risk-leakage  |  **Severity:** Critical  |  **Confidence:** High  |  **Source:** segment-C  |  **Effort:** S  |  **Next sprint:** Yes
- **Verification:** CONFIRMED (verified in-session: runtime_common.py:488, action_engine.py:404, UNG row read directly)
- **Evidence:**
  - `scripts/action_engine.py:404 — positions loaded via load_open_positions(open_positions_path)`
  - `scripts/runtime_common.py:488 — OPEN_POSITIONS_PATH = MOLTBOOK_DIR/open_positions.json`
  - `moltbook/open_positions.json:3-15 — UNG phantom row shown OPEN with current_price 12.5 below stop_loss 13.0`
  - `scripts/portfolio_truth_gate.py:1-27 — docstring: these moltbook rows are the stale/phantom set that hijacked synthesis`
- **Observed:** The only stop-breach / take-profit / EXIT_NOW logic in the system evaluates moltbook/open_positions.json (UNG/FCG/TLT/TIP), a file the project's own portfolio truth gate classifies as stale/phantom; the canonical holdings are never fed through it.
- **Why it matters:** The system's headline risk-discipline feature (stop enforcement advisories) is exercised exclusively against dead demo data, giving the operator false comfort that positions are watched.
- **Failure mode:** A real holding (e.g. 4x-leveraged HDFCBANK) gaps through its mental stop; the action engine emits nothing because that position does not exist in the file it reads, while it dutifully flags EXIT_NOW on UNG, a position that does not exist.
- **Business impact:** Direct capital loss on the real portfolio with zero system warning; destroys the 'risk engine' claim in any investor demo Q&A.
- **Score impact:** Drags C by ~2 points; also weakens A (signal-to-action credibility)
- **Recommended fix:** Rewire action_engine's position source to data/daily_payload/verified_current_holdings.json (via portfolio_truth_gate's H set), and treat moltbook/open_positions.json as read-never for action selection.

### SP-002 — N of closed, scored, real forward outcomes is 0 after 5+ weeks of claimed operation

- **Category:** evidence-leakage  |  **Severity:** Critical  |  **Confidence:** High  |  **Source:** segment-D  |  **Effort:** M  |  **Next sprint:** Yes
- **Verification:** CONFIRMED (verified in-session: read-only SQLite queries reproduced all zero counts; live_outcomes.jsonl 0 lines)
- **Evidence:**
  - `data/calibration_corpus/live_outcomes.jsonl — 0 lines`
  - `sqlite runtime/mvp_local.db — external_evidence_outcomes=0, imported_outcomes=0, nbi_track_record=0`
  - `sqlite decision_probability_snapshots — 480 rows all outcome_label NULL despite horizon_close max 2026-06-05`
- **Observed:** Every outcome table and JSONL in the repo is empty; the only 'outcomes' anywhere are 56 fixture retrocast rows and 2 retrospective 2015/2016 case studies.
- **Why it matters:** Calibration/outcome tracking is a headline product claim; the entire segment's deliverable (measured predictions) does not exist as data.
- **Failure mode:** Investor or operator believes the system has a measured track record; any calibration, hit-rate, or edge statement is unbacked because the denominator is zero.
- **Business impact:** The core value proposition (signals become measurable predictions) is unproven; due diligence fails on the first quantitative question.
- **Score impact:** D to ~3.5; also drags overall evidence credibility (segments touching track record) down 1-2 points
- **Recommended fix:** Restore the maturation loop, retro-mature the 56 orphaned snapshots, and add a daily assertion that N is monotonically reported in the ops cockpit.

### SP-003 — Outcome maturation loop exists only on an unmerged branch; canonical DB tables orphaned

- **Category:** architecture-leakage  |  **Severity:** Critical  |  **Confidence:** High  |  **Source:** segment-D  |  **Effort:** M  |  **Next sprint:** Yes
- **Verification:** CONFIRMED (verified in-session: git branch --contains 4e4785d; run_daily_outcome_maturation.py absent from tree)
- **Evidence:**
  - `git log -S decision_probability_snapshots — 4e4785d 'Add real-forward outcome maturation loop' (2026-06-01)`
  - `git branch -a --contains 4e4785d — only chore/real-forward-outcome-maturation`
  - `ls scripts/run_daily_outcome_maturation.py — No such file; grep decision_probability_snapshots in working tree — 0 hits`
- **Observed:** scripts/run_daily_outcome_maturation.py, forward_outcome_maturity_scanner.py, real_calibration_evidence.py and 7 test files were committed to a side branch and never merged; the working tree cannot read or close the 56 forward-eligible predictions it wrote to the DB.
- **Why it matters:** The single mechanism that converts locked predictions into scored outcomes was silently dropped during a branch pivot; prior session notes claim the loop was 'hardened' and pending, which is no longer true on the deployed branch.
- **Failure mode:** Predictions accumulate horizon-expired forever; the team believes outcomes are 'pending, not blocked' when they are structurally unreachable.
- **Business impact:** One month of forward evidence (the scarcest asset in this product) was forfeited; trust in internal status reporting is damaged.
- **Score impact:** D -2 directly; credibility of runbooks/docs (evidence segments) also affected
- **Recommended fix:** Merge or re-port the maturation loop to the main line, register it in core_module_boundary/private_scope_guard, and add a CI check that any DB table has at least one code reference.

### SP-004 — Live NBI operator card surface contains test-fixture data (MACRO1, fake evidence URL)

- **Category:** signal-leakage  |  **Severity:** High  |  **Confidence:** High  |  **Source:** segment-A  |  **Effort:** S  |  **Next sprint:** Yes
- **Verification:** CONFIRMED mechanism / surface self-healed (fixture MACRO1 served 2026-07-03 19:11 -> 2026-07-04 09:31; overwritten by first scheduled NBI run; recurrence guaranteed on next local test run without a fix)
- **Evidence:**
  - `runtime/nbi_operator_cards.md:20 — 'MACRO1 SURVIVING final=4.2268 base=8.0' placeholder ticker`
  - `runtime/nbi_operator_cards.md:33 — evidence ref 'https://e/filing' (not a real URL)`
  - `grep MACRO1 — matches only tests/test_nbi_operate_loop_v14.py, tests/test_nbi_evidence_factory.py, tests/test_nbi_operational_loop.py`
  - `scripts/api_server.py:3147-3152 — /nbi/cards serves runtime/nbi_operator_cards.json verbatim`
- **Observed:** runtime/nbi_operator_cards.{md,json,html} (regenerated 2026-07-03 19:11, same evening the 7567-test suite ran) contain a synthetic 'Loop summit event' with placeholder ticker MACRO1 and evidence URL https://e/filing; this exact file is served by GET /nbi/cards and rendered on the /nbi frontend page.
- **Why it matters:** The operator's flagship morning card surface can silently display synthetic events with hedge ratios, action verdicts, and final scores that look identical to real ones.
- **Failure mode:** Operator opens /nbi after the 08:30 loop, sees a scored event card with a WATCH/ACT recommendation for a fixture entity, and either wastes a session investigating it or — worse — anchors a real WATCH decision on fabricated evidence. Any reviewer who spots 'https://e/filing' loses trust in every other artifact.
- **Business impact:** Directly undermines the product's core claim of evidence-grounded advisory output; one fixture leak on the live surface invalidates the 'every number is a measurement' promise to any investor or user.
- **Score impact:** A -1.0; also drags F/evidence and J/test segments
- **Recommended fix:** Make all test/demo NBI exports write to a tmp or CI-scoped path (env var like NBI_ARTIFACT_DIR set by conftest), add a guard test asserting runtime/nbi_operator_cards.json never contains is_fixture/synthetic events, and have /nbi/cards refuse (fail-closed envelope) any card whose evidence refs are not http(s) URLs on a real host.

### SP-005 — Core product output — fresh discovery candidates — has been empty for ~6 weeks

- **Category:** signal-leakage  |  **Severity:** High  |  **Confidence:** High  |  **Source:** segment-A  |  **Effort:** M  |  **Next sprint:** Yes
- **Verification:** CORROBORATED (daily_payload mtimes 2026-06-07 verified in-session; STATIC_UNIVERSE_FALLBACK content per agent read)
- **Evidence:**
  - `runtime/daily_portfolio_truth_context.md:25-34 — NO_FRESH_DISCOVERY_GENERATED, current_session_date 2026-05-22, all four payloads source_health UNVERIFIED (artifact dated 2026-07-02)`
  - `data/daily_payload/today_market_snapshot.json:2-7 — run_date 2026-05-24, STATIC_UNIVERSE_FALLBACK, is_live false`
  - `data/daily_payload — all nine files last modified 2026-06-07`
- **Observed:** The July 2 portfolio-truth artifact honestly fail-closes: every discovery payload is static fallback, so the Fresh Discovery Board has emitted zero candidates since 2026-05-22. The 'today_*' filenames are 26+ days stale in content.
- **Why it matters:** Signal generation is the first claimed capability. The system's governance is excellent at saying 'no data', but the operator receives no positive advisory content at all — the product currently delivers only do-nothing verdicts.
- **Failure mode:** A non-author operator runs the morning routine for weeks and gets NO_FRESH_DISCOVERY_GENERATED every day; the product is indistinguishable from an empty journal, and stale 'today_' filenames invite misreading old data as current.
- **Business impact:** Zero demonstrable signal value = no investor story beyond safety scaffolding; retention of even a single operator is implausible.
- **Score impact:** A -1.2; also drags B/data and C/signal segments
- **Recommended fix:** Wire the already-proven Yahoo public canary (plus one news source) into the today_* payload builders so at least today_market_snapshot and today_price_movers report is_live=true/VERIFIED_LIVE, letting the Fresh Discovery Board emit real candidates; rename or date-stamp payload files so 'today_' can never be stale.

### SP-006 — Canonical holdings truth is a 6-week-stale, manually-authored snapshot

- **Category:** data-leakage  |  **Severity:** High  |  **Confidence:** High  |  **Source:** segment-A  |  **Effort:** S  |  **Next sprint:** Yes
- **Verification:** CONFIRMED (verified in-session)
- **Evidence:**
  - `data/daily_payload/verified_current_holdings.json:2 — run_date 2026-05-22`
  - `data/daily_payload/verified_current_holdings.json:8 — operator_note declares this file the ONLY canonical truth for OPEN positions`
  - `data/daily_payload/verified_current_holdings.json:23 — broker_confirmed false on rows (human_confirmed true only)`
- **Observed:** The single file the whole pipeline treats as authoritative open-position truth (feeding the PORTFOLIO TRUTH GATE in runtime/daily_portfolio_truth_context.md:6) was last verified 2026-05-22 and has no refresh mechanism; every row is broker_confirmed=false.
- **Why it matters:** All exit/TP/stop/hold advisory logic is scoped to tickers in this set. If the human sold or bought anything since May 22, the system gives position-management advice against a phantom portfolio — the exact failure mode the truth gate was built to prevent.
- **Failure mode:** Operator sold ASML in June; system continues generating hold/exit context for ASML and blocks discovery treatment of it, while a genuinely new position gets no management coverage.
- **Business impact:** Advisory outputs computed on wrong holdings are worse than none — they create false confidence in the 'truth gate' brand.
- **Score impact:** A -0.8; also drags B/data segment
- **Recommended fix:** Add a staleness gate: if verified_current_holdings.run_date is older than N days, the portfolio truth context must render HOLDINGS_TRUTH_STALE and demote all position-management advice to review-only; add a one-command refresh flow (prompted diff against manual_trade_log) to the daily checklist.

### SP-007 — model_probability is a placeholder heuristic dressed as a probability, and 'mispricing' is manufactured from it

- **Category:** calibration-leakage  |  **Severity:** High  |  **Confidence:** High  |  **Source:** segment-B  |  **Effort:** S  |  **Next sprint:** Yes
- **Verification:** CONFIRMED (verified in-session: src/scoring/net_signal_value.py:10-15 docstring read directly)
- **Evidence:**
  - `src/scoring/net_signal_value.py:9-15 — 'placeholder model probability used for paper-only scoring', clip(0.50 + 0.25(EQS−0.5) + 0.20(DS−0.5) − 0.15·EMS − 0.10·EFS, 0.01, 0.99)`
  - `src/scoring/net_signal_value.py:35-53 — mispricing = abs(model_prob − market_prob) drives NSV, APS, and HIGH_MISPRICING_ESTIMATE/PAPER_EDGE_DETECTED codes`
  - `scripts/run_scoring.py:63 — placeholder feeds the live scoring record`
- **Observed:** The only quantity named 'probability' in the core pipeline is an uncalibrated linear blend of heuristic 0-1 sub-scores; divergence from market-implied probability is then scored as edge.
- **Why it matters:** A noisier placeholder produces LARGER 'mispricing' and therefore higher NSV/APS — the system structurally rewards model error with apparent edge.
- **Failure mode:** Operator sees PAPER_EDGE_DETECTED and a 0.73 'model probability' on a signal where the number carries zero calibrated meaning; paper track record built on it is uninterpretable.
- **Business impact:** Any investor diligence that asks 'is this probability calibrated?' gets 'no, and it says placeholder in the source' — kills credibility of every downstream calibration report.
- **Score impact:** B −1.5; also drags calibration-adjacent segments
- **Recommended fix:** Rename to heuristic_prior in schema and UI; suppress mispricing-derived reason codes until calibration_gate reports N>=CALIBRATED_MIN; keep raw components visible.

### SP-008 — Calibration corpus is fixtures and emptiness — zero real model-vs-outcome pairs exist

- **Category:** calibration-leakage  |  **Severity:** High  |  **Confidence:** High  |  **Source:** segment-B  |  **Effort:** M  |  **Next sprint:** Yes
- **Verification:** CORROBORATED (live_outcomes 0 lines verified in-session; retrocast fixture rows per agent)
- **Evidence:**
  - `data/calibration_corpus/live_outcomes.jsonl — 0 lines`
  - `data/calibration_corpus/retrocast.jsonl — 56/56 rows contain data_mode=FIXTURE_DEMONSTRATION`
  - `docs/MODEL_PIPELINE_MAP.md:77-78 — 'Real outcome sample size is far below the CALIBRATED_MIN=50 ladder rung; every probability is provisional'`
- **Observed:** 11 calibration scripts (score_calibration.py, calibration_gate.py, etc.) implement ECE/Brier/Wilson machinery, but the tracked corpus feeding them contains only fixture rows and an empty live-outcomes file.
- **Why it matters:** Sophisticated calibration code with no data is negative evidence in diligence: it shows the loop was built but never closed after ~13 months of development.
- **Failure mode:** Calibration reports either honestly say INSUFFICIENT_EVIDENCE forever or someone runs them on fixture rows and produces a fake-calibrated artifact.
- **Business impact:** The product's central claim (calibration/outcome tracking) is unverifiable; near-term score ceiling for the whole product is data-gated.
- **Score impact:** B −1.2
- **Recommended fix:** Ruthlessly prioritize closing real forward snapshots (the NBI 2/30 accumulation) and record model heuristic_prior at entry so pairs become calibratable; add a corpus gate that refuses FIXTURE_DEMONSTRATION rows in any calibration computation.

### SP-009 — Scoring-system sprawl: 48 registered models, 6+ parallel gate vocabularies, reconciled only by a markdown doc

- **Category:** architecture-leakage  |  **Severity:** High  |  **Confidence:** High  |  **Source:** segment-B  |  **Effort:** M  |  **Next sprint:** Yes
- **Verification:** AGENT-EVIDENCED (model_registry.json 33KB consistent with count; vocabularies per agent reads)
- **Evidence:**
  - `model_registry.json — 48 model entries`
  - `scripts/composite_edge_score.py:149-154 — CE emits FIRE_MODE_ELIGIBLE/IL_STAGGER on its own thresholds`
  - `scripts/chicken_gate_daily_bridge.py:105-109 — maps a THIRD vocabulary (EXECUTABLE-PAPER-BUY etc.) onto chicken gate ranks`
  - `docs/chicken_gate_consolidation_map.md:29 — CE explicitly ruled a 'parallel scorer for the S-pipeline... IGNORE'`
- **Observed:** chicken_gate (BUY_*), daily_scoring tiers (EXECUTABLE*), composite_edge_score (STRONG_EDGE/FIRE_MODE), signal_arbitrage (BUY/LONG_TERM_COMPOUNDER), mythos, and NBI all score the same underlying question with different scales, weights, and action words; only chicken_gate↔daily tiers are bridged (correctly, via min-rank).
- **Why it matters:** The same candidate can simultaneously be BUY_BLOCKED (chicken gate) and STRONG_EDGE/FIRE_MODE_ELIGIBLE (CE) with no code-level reconciliation — the consolidation map is documentation, not enforcement.
- **Failure mode:** Operator or a future integration reads the CE FIRE_MODE label on a gate-blocked name and acts on the wrong scorer; auditors cannot say which number is 'the' signal score.
- **Business impact:** Diligence reads this as accreted sprint output rather than a designed system; maintenance cost and contradiction risk grow with every new scorer.
- **Score impact:** B −1.0
- **Recommended fix:** Enforce the consolidation map in code: a registry-level test that every scorer emitting action-shaped labels must route through chicken_gate_daily_bridge min-rank composition or be marked RESEARCH_ONLY in its output payload.

### SP-010 — Canonical holdings have no stop_loss, take_profit, or invalidation fields at all

- **Category:** capital-risk-leakage  |  **Severity:** High  |  **Confidence:** High  |  **Source:** segment-C  |  **Effort:** S  |  **Next sprint:** Yes
- **Verification:** CONFIRMED (verified in-session: parsed all 10 positions; zero stop/target fields; broker_confirmed=false on all)
- **Evidence:**
  - `data/daily_payload/verified_current_holdings.json:9-159 — every position has only quantity/entry_price/leverage; no stop or target fields`
  - `scripts/runtime_common.py:595-609 — OPEN_POSITION_REQUIRED_KEYS demands stop_loss/take_profit, proving the schema exists but is unmet by the truth file`
- **Observed:** The position schema used by the risk machinery requires stop_loss/take_profit/current_price, but the canonical truth file satisfies none of those keys, so real holdings are structurally incompatible with every risk check.
- **Why it matters:** Stops are the single most basic portfolio-discipline primitive; the real book has none recorded anywhere in canonical truth.
- **Failure mode:** Any attempt to run the existing risk checks on real holdings fails validation (missing keys) or silently skips; no per-position risk plan exists to enforce or even display.
- **Business impact:** Investor diligence question 'where are your stops?' has no answer backed by data.
- **Score impact:** C down ~1.5 points
- **Recommended fix:** Extend verified_current_holdings.json schema with operator-confirmed stop_loss/invalidation_level/take_profit per position and validate against OPEN_POSITION_REQUIRED_KEYS at load.

### SP-011 — Holdings truth file is 6 weeks stale with no freshness gate and no broker confirmation

- **Category:** data-leakage  |  **Severity:** High  |  **Confidence:** High  |  **Source:** segment-C  |  **Effort:** XS  |  **Next sprint:** Yes
- **Verification:** CONFIRMED (verified in-session: run_date 2026-05-22; file mtime 2026-06-07)
- **Evidence:**
  - `data/daily_payload/verified_current_holdings.json:2 — run_date 2026-05-22 vs audit date 2026-07-03`
  - `data/daily_payload/verified_current_holdings.json:22,37 — broker_confirmed false on every position`
  - `Grep 'holdings.*(age|stale|fresh)' across scripts/ — no file-age check on the holdings truth file exists`
- **Observed:** The file every gate calls 'the only canonical truth for OPEN positions' was last verified 2026-05-22; nothing in the codebase compares run_date to now, so all downstream discipline silently trusts a 6-week-old snapshot.
- **Why it matters:** Every portfolio-truth guarantee (phantom exclusion, management permission) is only as good as this file's currency; it is the single point of truth and it is unmonitored for age.
- **Failure mode:** Operator sold or added positions since May 22; the system manages a portfolio that no longer exists — the exact phantom-position failure mode the truth gate was built to prevent, reintroduced one layer up.
- **Business impact:** Reconciliation and risk outputs are unreliable; trust in 'verified' labeling collapses under scrutiny.
- **Score impact:** C down ~1 point; also drags reconciliation-adjacent segments
- **Recommended fix:** Add a hard freshness gate (fail-closed at N days) on verified_current_holdings.run_date inside load_daily_payload/portfolio_truth_gate, surfaced as a blocking issue in pre_real_money_preflight.

### SP-012 — Real portfolio (10 open) breaches configured max_open_positions=6 invisibly

- **Category:** architecture-leakage  |  **Severity:** High  |  **Confidence:** High  |  **Source:** segment-C  |  **Effort:** S  |  **Next sprint:** Yes
- **Verification:** CONFIRMED (verified in-session: config value 6 at line 28; 10 open positions parsed)
- **Evidence:**
  - `config/signal_refinery_config.json:28 — max_open_positions: 6`
  - `data/daily_payload/verified_current_holdings.json:9-159 — 10 OPEN positions (ANET, XOM, RTX, LMT, CVX, MSFT, HDFCBANK, RELIANCE, ASML, TSM)`
  - `scripts/signal_refinery.py:645-677 — thermal battery counts open positions from the refinery's own inputs, not the verified holdings file`
- **Observed:** The capacity gate (thermal battery SATURATED state) exists and is tested, but it counts positions from a different source than canonical truth, so the actual 10-vs-6 cap breach raises no state change.
- **Why it matters:** A capacity gate that cannot see the real book is a compliance prop; the one quantitative exposure limit the product has is not connected to reality.
- **Failure mode:** Operator keeps adding positions on REVIEW_FOR_ENTRY advisories; thermal_state stays READY because the counted set is empty/stale while the real book is already 167% of its cap.
- **Business impact:** Over-concentration accumulates with the system actively signaling headroom that does not exist.
- **Score impact:** C down ~0.8
- **Recommended fix:** Feed thermal battery's open_position_count from portfolio_truth_gate's H set and surface SATURATED against the real count.

### SP-013 — 4x-leveraged INR positions are the least protected in the book

- **Category:** capital-risk-leakage  |  **Severity:** High  |  **Confidence:** High  |  **Source:** segment-C  |  **Effort:** M  |  **Next sprint:** No
- **Verification:** CONFIRMED (verified in-session: HDFCBANK.NS & RELIANCE.NS leverage=4, no stop fields)
- **Evidence:**
  - `data/daily_payload/verified_current_holdings.json:109,124 — HDFCBANK.NS and RELIANCE.NS at leverage 4, no stop fields`
  - `scripts/persistence.py:488-496 — leverage governance only stamps leverage_breach/severity flags on records; it never blocks`
  - `Grep 'notional|total_exposure|portfolio_exposure' — no currency-normalized portfolio exposure aggregation exists`
- **Observed:** The two highest-risk positions (4x leverage, INR) have no recorded stop, no currency-normalized exposure contribution, and leverage governance is record-and-flag only; nothing computes what fraction of capital a 4x gap-down burns.
- **Why it matters:** Leverage multiplies the cost of every other gap in this segment; the 4x ceiling doctrine exists but no monitoring of leveraged positions' downside does.
- **Failure mode:** NSE gap-down of 8% on RELIANCE = ~32% position loss at 4x; system produces no alert, no drawdown accounting, no exposure recalc.
- **Business impact:** Largest plausible single-event capital loss in the product is entirely un-instrumented.
- **Score impact:** C down ~0.7
- **Recommended fix:** Compute per-position and portfolio notional exposure (leverage- and currency-adjusted) from verified holdings and add a leveraged-position stop-required rule to the truth-file validator.

### SP-014 — Installed daily scheduler runs no outcome-maturation step

- **Category:** runtime-leakage  |  **Severity:** High  |  **Confidence:** High  |  **Source:** segment-D  |  **Effort:** S  |  **Next sprint:** Yes
- **Verification:** CORROBORATED (agent grep of nbi_scheduler.py + first live scheduled run 2026-07-04 09:11 produced ingest/cards only)
- **Evidence:**
  - `scripts/nbi_scheduler.py:200-251 — run_once() imports only run_daily/export_cards/build_score_report from nbi_evidence_factory`
  - `grep maturity|live_outcomes in scripts/nbi_scheduler.py and nbi_evidence_factory.py — 0 hits`
- **Observed:** The schtasks 08:30 daily loop ingests NBI events and exports cards but never runs snapshot_maturity_scanner or any outcome-closing logic; live_outcomes.jsonl (created 2026-07-02) will remain empty under automation.
- **Why it matters:** Even the new-generation pipeline has no automated path from prediction to outcome; N=0 persists by construction, not by lack of elapsed time.
- **Failure mode:** Six months from now the corpus still shows NO_LIVE_EVIDENCE despite a 'HEALTHY 10/10' scheduler, because health measures ingest, not outcome closure.
- **Business impact:** Calibration readiness never advances; operator dashboards show green while the evidence flywheel is disconnected.
- **Score impact:** D -1; also flatters ops-health segments
- **Recommended fix:** Add a maturation step to run_once() (scan snapshots, append matured outcomes, refresh live_calibration_report) and include outcome-closure count in SchedulerHealth.

### SP-015 — All Brier/logloss/ECE metrics have only synthetic fixture data to operate on

- **Category:** calibration-leakage  |  **Severity:** High  |  **Confidence:** High  |  **Source:** segment-D  |  **Effort:** M  |  **Next sprint:** Yes
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `grep -c FIXTURE_DEMONSTRATION data/calibration_corpus/retrocast.jsonl — 56/56`
  - `data/calibration_corpus/forward_snapshots.jsonl:1-2 — both rows data_mode=FIXTURE_DEMONSTRATION`
  - `scripts/run_calibration_pipeline.py:1-16 — full ECE/Brier/Murphy/bootstrap stack exists`
- **Observed:** The metric machinery (ECE, Brier, Murphy decomposition, bootstrap CIs, isotonic/Platt recalibration) is implemented and tested, but no real-provenance row has ever flowed through it; real-outcome Brier/logloss has never been computed once.
- **Why it matters:** Metric code without real inputs is indistinguishable from a demo; the honest gates correctly refuse claims, but the product cannot demonstrate its central capability on real data.
- **Failure mode:** First real data arrives and exposes schema/provenance mismatches (e.g., the fixture entry_day integer convention vs real UTC timestamps) that fixtures never exercised.
- **Business impact:** Time-to-first-real-calibration is unknown; investor cannot distinguish 'ready pipeline' from 'untested pipeline'.
- **Score impact:** D capped near 4 until first real Brier exists
- **Recommended fix:** Prioritize one end-to-end real row (live snapshot -> matured outcome -> Brier report) as the sprint acceptance test rather than more fixture coverage.

### SP-016 — Prediction and outcome records are mutable with no tamper evidence

- **Category:** evidence-leakage  |  **Severity:** High  |  **Confidence:** High  |  **Source:** segment-D  |  **Effort:** M  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (nbi_track_record_ledger.py:317-327 bare UPDATE per agent read)
- **Evidence:**
  - `scripts/nbi_track_record_ledger.py:317-327 — close_track_record_entry is a bare UPDATE, re-runnable, overwrites realized_return/benchmark_return/close_timestamp with no re-close guard or history`
  - `data/calibration_corpus/*.jsonl — plain editable JSONL; no hash chain over prediction rows (grep hash_chain/immutab in scripts — only map-hash and audit-log verifier, not corpus)`
- **Observed:** Initial predictions and closed outcomes live in ordinary SQLite rows and JSONL lines; nothing prevents or detects post-hoc edits of locked probabilities, entry prices, or realized returns before commit. Git tracking of the corpus gives only weak, after-the-fact tamper evidence.
- **Why it matters:** A calibration track record is only as credible as its immutability; 'locked timestamp' is currently a convention, not a mechanism.
- **Failure mode:** A single well-intentioned 'data fix' silently rewrites a realized return; the track record becomes unauditable and any future edge claim is challengeable.
- **Business impact:** Track record fails third-party verification; the strongest asset (honesty culture) has no cryptographic backing.
- **Score impact:** D -0.5 now; blocks D>7 later
- **Recommended fix:** Make outcome tables append-only (SQLite triggers rejecting UPDATE on initial_* fields, close-once guard) and add a per-row content hash chained into the existing checksum/audit-log verifier.

### SP-017 — Kalshi/Polymarket persisted zero rows for 11 days while reporting 'Source healthy (filtered)'

- **Category:** data-leakage  |  **Severity:** High  |  **Confidence:** High  |  **Source:** segment-E  |  **Effort:** S  |  **Next sprint:** Yes
- **Verification:** CORROBORATED (agent SQLite queries; consistent with in-session refresh summary showing kalshi/polymarket ok_filtered)
- **Evidence:**
  - `runtime/mvp_local.db — select count(*) signal_events where source_name='kalshi' and fetched_at>'2026-06-23' → 0; same for polymarket; latest runs 2026-07-03T16:00 status ok_filtered fetched_count 75/20`
  - `scripts/source_health_summary.py:83-88 — OK_FILTERED → severity 'ok', 'Source healthy (filtered out off-domain rows)'`
  - `grep canonical_signal_status / api_health_status across repo → no matches (documented two-axis truth split not present in current code)`
- **Observed:** Both prediction-market sources fetch rows daily but every row has been filtered out before persistence since 2026-06-22; health surface classifies this as ok.
- **Why it matters:** Two of the product's headline signal lanes have been effectively dead for 11 days without any operator-visible degradation signal.
- **Failure mode:** Filter drift or upstream schema change silently reduces a source to zero yield forever; downstream signals keep running on 11+ day-old prediction-market data presented as current.
- **Business impact:** Advisory outputs cite prediction-market context that is stale; destroys trust the moment an operator or investor cross-checks a market price.
- **Score impact:** Primary drag on E (~-1.5); also touches auditability claims in K
- **Recommended fix:** Track rows_persisted separately from fetched_count in source_run_log; classify N consecutive zero-persisted OK_FILTERED runs as DEGRADED and include in api_server stale_sources.

### SP-018 — Live price coverage is 4 default ETFs; holdings and multi-country names have no live prices

- **Category:** signal-leakage  |  **Severity:** High  |  **Confidence:** High  |  **Source:** segment-E  |  **Effort:** M  |  **Next sprint:** Yes
- **Verification:** CORROBORATED (in-session refresh summary market_data ok/4; agent DB queries)
- **Evidence:**
  - `scripts/ingestion/market_data_loader.py:20 — _DEFAULT_TICKERS = ['SPY','QQQ','GLD','TLT']; latest run fetched_count=4`
  - `runtime/mvp_local.db — market_data rows last 7 days: 24, symbols only {GLD,QQQ,SPY,TLT}; ohlcv_bars=0, ohlcv_coverage_status=0`
  - `runtime/mvp_local.db global_securities — 56 rows incl. SAP.DE, 7203.T, 600519.SS with yahoo_symbol mapping, none fetched live`
- **Observed:** The 122k market_data signal_events rows are historical backfill; the scheduled refresh only pulls 4 index ETFs, and the OHLCV coverage-status table built to track this is empty.
- **Why it matters:** Risk scoring, movers detection, and outcome maturation for actual holdings cannot use canonical live prices — they depend on ad-hoc yf.Ticker calls scattered across scripts.
- **Failure mode:** A holding gaps down 20%; canonical store contains no bar for it; daily synthesis and staleness labels are computed from index ETFs and month-old payload files.
- **Business impact:** Cannot demonstrate mark-to-market on real positions to an investor; the 'portfolio sync' claim is unsupported by the data layer.
- **Score impact:** E (~-1.2); drags C/F wherever price-dependent scoring runs
- **Recommended fix:** Drive MarketDataLoader ticker list from verified_current_holdings.json + global_securities.yahoo_symbol; populate ohlcv_coverage_status per symbol per run.

### SP-019 — News fallback chain not exercised in scheduled cadence — GDELT timeout left today with no fresh news lane

- **Category:** runtime-leakage  |  **Severity:** High  |  **Confidence:** High  |  **Source:** segment-E  |  **Effort:** S  |  **Next sprint:** Yes
- **Verification:** CORROBORATED (agent source_run_log read; in-session summary shows 7 skipped sources)
- **Evidence:**
  - `source_run_log — gdelt 'timeout … primary=TIMEOUT, fallback=TIMEOUT' at 2026-07-03T16:00:14; newsapi last ok 2026-07-02T05:00:18; event_registry last ok 2026-07-02T05:00:19`
  - `scripts/refresh_live_signals.py:105-115 — newsapi/event_registry are phase2 keys, so the chain only works if that phase runs; today's 16:00 run skipped both`
- **Observed:** GDELT timed out in today's refresh and neither NewsAPI nor EventRegistry ran as a fallback in the same cadence; last successful news pull is 35 hours old.
- **Why it matters:** The GDELT→NewsAPI→EventRegistry chain is the documented resilience story; in practice a GDELT outage produces a zero-news day.
- **Failure mode:** Multi-day GDELT outage (it is a flaky free endpoint) leaves fresh-evidence sets empty; anti_staleness marks everything UNVERIFIED/STALE or, worse, discovery runs on old news.
- **Business impact:** News-driven signals degrade silently exactly when news volume spikes (outages correlate with load).
- **Score impact:** E (~-0.8)
- **Recommended fix:** In the scheduled refresh, on gdelt status timeout/rate_limited, immediately invoke newsapi then event_registry in the same run and log the chain hop in source_run_log.

### SP-020 — Holdings-truth payload frozen at 2026-06-07 with no wall-clock staleness detection

- **Category:** signal-leakage  |  **Severity:** High  |  **Confidence:** High  |  **Source:** segment-E  |  **Effort:** S  |  **Next sprint:** Yes
- **Verification:** CORROBORATED (mtimes verified in-session; anti_staleness.py logic per agent read)
- **Evidence:**
  - `data/daily_payload/verified_current_holdings.json, today_price_movers.json, today_news_events.json — all mtime 2026-06-07 (26 days before today)`
  - `scripts/anti_staleness.py:41-65,93-107 — freshness computed purely from set membership of these files' contents; no check of file age or content dates`
- **Observed:** The files designated as holdings truth and 'today' evidence are 26 days old; the anti-staleness layer consumes them as if current and cannot detect its own inputs are stale.
- **Why it matters:** The entire freshness system (FRESH_TODAY/STALE_24H labels, novelty ratio) is computed relative to a snapshot from June 7 — labels are semantically wrong.
- **Failure mode:** A position sold on June 10 still appears in verified_open_holdings; a ticker in June 7 movers gets FRESH_TODAY today; truth gate demotions fire on phantom state.
- **Business impact:** Wrong holdings truth is the single fastest way to embarrass this product in a live demo.
- **Score impact:** E (~-1.0); also drags the holdings/truth segments
- **Recommended fix:** Stamp generated_at_utc inside each daily_payload file and make build_anti_staleness fail closed (STALE_PAYLOAD warning + demote all labels) when generated_at is older than 24h.

### SP-021 — 98% of backend is a flat 184k-LOC scripts/ pile; src/ is vestigial and layering is inverted

- **Category:** architecture-leakage  |  **Severity:** High  |  **Confidence:** High  |  **Source:** segment-F  |  **Effort:** L  |  **Next sprint:** Yes
- **Verification:** CORROBORATED (427 top-level scripts verified in-session; LOC counts per agent)
- **Evidence:**
  - `scripts/: 183,744 LOC across 495 files vs src/: 3,266 LOC (find|wc -l)`
  - `src/ingestion/kalshi_live_loader.py:41-48 — src imports scripts.kalshi_normalizer, scripts.runtime_common (library layer depends on script pile)`
  - `scripts/private_scope_guard.py:348 — PREEXISTING_BASELINE grandfathers ~145 out-of-scope modules`
- **Observed:** 413 loose top-level scripts with no package structure carry essentially all business logic; the nominal src/ package (models/storage/ingestion) is 1.7% of the code and reaches back into scripts/ for core helpers.
- **Why it matters:** There is no dependency direction, no module ownership, and no way to reason about blast radius of a change without grepping 495 files.
- **Failure mode:** A second engineer modifies a 'support' script that turns out to be in the CORE import closure (399/443 modules are bucketed SUPPORT), silently altering signal scoring behavior consumed by the API and daily scheduler.
- **Business impact:** Onboarding cost measured in weeks; velocity collapses as headcount grows; acquirer technical DD will flag this immediately and discount valuation.
- **Score impact:** F -2.0; drags L (maintainability aspects of other segments) indirectly
- **Recommended fix:** Introduce pyproject.toml, promote the ~26 CORE modules plus their SUPPORT closure into a real package with subpackages (api/, persistence/, calibration/, nbi/), archive the 145 grandfathered modules under archived_experimental/.

### SP-022 — api_server.py is a 3,359-line monolith with 63 routes; the routers/ decomposition was started and abandoned

- **Category:** architecture-leakage  |  **Severity:** High  |  **Confidence:** High  |  **Source:** segment-F  |  **Effort:** M  |  **Next sprint:** Yes
- **Verification:** CORROBORATED (empty scripts/api/routers verified in-session; line/route counts per agent)
- **Evidence:**
  - `scripts/api_server.py:1 — 3,359 lines, 63 @app. route decorators, 35 except Exception blocks`
  - `scripts/api/routers — empty directory, zero .py files, no git history (never committed)`
  - `scripts/api_server.py:44-118 — try/except ImportError fallback stubs for FastAPI itself plus dual 'from scripts.X'/'from X' import paths`
- **Observed:** All HTTP surface (signal inbox, moltbook, exports, reconciliation, NBI) lives in one file, including a hand-rolled _NoopApp stand-in (line 827) and stub BaseModel/Field when FastAPI is absent.
- **Why it matters:** Single-file APIs of this size cannot be reviewed, own no clear contract per domain, and the FastAPI-optional stubbing means the module silently degrades into non-functional shims instead of failing fast.
- **Failure mode:** Two engineers editing the same 3,359-line file produce merge conflicts on unrelated endpoints; the FastAPI-absent stub path (HTTPException = Exception, line 57) masks a broken environment as a passing import.
- **Business impact:** API change lead time and defect rate scale with file size; investor demo of 'clean API' claim does not survive a code walk.
- **Score impact:** F -1.5
- **Recommended fix:** Split into APIRouter modules in scripts/api/routers (already scaffolded), one per domain; drop the FastAPI-optional stubs by moving pure helpers (sanitizer, health classifier) into a separate importable module.

### SP-023 — SQLite access fragmented: 54 files open the DB directly, only 7 set busy_timeout, 53 hardcode the DB filename vs 7 honoring MVP_DB_PATH

- **Category:** runtime-leakage  |  **Severity:** High  |  **Confidence:** Medium  |  **Source:** segment-F  |  **Effort:** M  |  **Next sprint:** Yes
- **Verification:** AGENT-EVIDENCED (grep counts from auditor; not independently re-run)
- **Evidence:**
  - `grep: sqlite3.connect = 95 hits / 54 files in scripts+src; busy_timeout present in only 7 files`
  - `scripts/persistence.py:344-378 — hardened _apply_pragmas exists but is bypassed by ~47 other direct openers`
  - `grep: 'mvp_local.db' literal in 53 files vs MVP_DB_PATH read in 7 files`
  - `scripts/chronology_store.py:117 — only module enabling WAL; main mvp_local.db connections are not WAL`
- **Observed:** A hardened central connection helper exists, yet most writers (schema_migrations, reconciliation_queue, moltbook_reconciliation_bridge, nbi_evidence_factory, event_prior_detector) call sqlite3.connect themselves with no busy_timeout; the env-var DB override is honored by the API server but not by most scripts. A diagnostics-cache write-race flake was already fixed once (memory 2026-05-30), confirming this class of bug is live.
- **Why it matters:** The daily 08:30 scheduled task, the API server, and operator-run scripts can hit the same non-WAL DB concurrently; connections without busy_timeout raise 'database is locked' immediately.
- **Failure mode:** Operator sets MVP_DB_PATH to a test DB; api_server writes there while the maturation/NBI scripts keep writing runtime/mvp_local.db — split-brain ledgers; or the scheduler collides with a manual script run and a write fails mid-loop with SQLITE_BUSY.
- **Business impact:** Silent data divergence in the evidence/outcome ledgers destroys the calibration truth chain the product's credibility rests on.
- **Score impact:** F -1.0; bleeds into data-integrity segments
- **Recommended fix:** One get_connection() (from persistence._get_conn) as the mandatory entry point; add a repo-wide test that greps for sqlite3.connect outside persistence.py and fails on new offenders; enable WAL centrally.

### SP-024 — NBI page is an orphan route — no navigation link exists anywhere in the app

- **Category:** ux-leakage  |  **Severity:** High  |  **Confidence:** High  |  **Source:** segment-G  |  **Effort:** XS  |  **Next sprint:** Yes
- **Verification:** CONFIRMED (verified in-session: no nbi match in Sidebar.tsx)
- **Evidence:**
  - `frontend/src/components/layout/Sidebar.tsx:12-54 — NAV_GROUPS lists 13 routes across Review/Decide/Learn/Admin; /nbi not among them`
  - `Grep '/nbi' in frontend/src — only hits are apiClient.ts:728,747 and the page's own comment; no <Link href="/nbi"> anywhere`
- **Observed:** The /nbi page (Narrative Branch Intelligence cards + live-ops cockpit, the headline feature of the last two commits) is reachable only by typing the URL manually.
- **Why it matters:** The sidebar is explicitly designed as 'what do I do next for an operator who has never seen the app' (Sidebar.tsx:10-11); the newest, most-invested feature is invisible to exactly that operator.
- **Failure mode:** Operator (or investor demo viewer) never sees the NBI cockpit, edge-claim gate, or CASE_ACCUMULATION progress; the daily scheduled loop produces artifacts nobody looks at, and evidence-repair next-actions go unread.
- **Business impact:** The feature that justifies the current sprint's engineering spend generates zero operator value and demos as if it does not exist.
- **Score impact:** G -0.4; also weakens the story for whichever segment scores the NBI subsystem
- **Recommended fix:** Add { href: '/nbi', label: 'Narrative Branches', icon: '…' } to the Review group in Sidebar.tsx NAV_GROUPS.

### SP-025 — NBI live-ops cockpit shows artifact health with no staleness detection — dead scheduler renders green forever

- **Category:** calibration-leakage  |  **Severity:** High  |  **Confidence:** High  |  **Source:** segment-G  |  **Effort:** S  |  **Next sprint:** Yes
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `scripts/api_server.py:3182-3200 — /nbi/cockpit returns runtime/nbi_live_ops_cockpit.json verbatim; only sets artifact_present, never computes age`
  - `frontend/src/app/nbi/page.tsx:84-113 — CockpitPanel renders status/HEALTHY 10/10/scheduler-installed but omits generated_at entirely; footer at :291-294 prints raw generated_at string with no age evaluation`
- **Observed:** The cockpit panel is wired to live data (runtime/nbi_live_ops_cockpit.json exists, mtime Jul 3 18:10) but if the 08:30 schtasks job silently stops, the UI keeps displaying the last HEALTHY 10/10 snapshot with no STALE flag at any layer.
- **Why it matters:** This page's whole purpose is operational truth about an unattended daily loop; an unattended loop's primary failure mode is silent death, which is exactly the case the UI cannot represent.
- **Failure mode:** Scheduler breaks on 2026-07-05; operator opens /nbi on 2026-07-20 and sees 'Status: HEALTHY · 10/10 · Scheduler installed: yes' — trusts a 15-day-old snapshot and believes case accumulation is progressing when it is frozen.
- **Business impact:** Destroys trust in the ops surface the moment the first silent failure is discovered; the 2/30 case-accumulation clock silently stops.
- **Score impact:** G -0.4; also drags whichever segment audits runtime/scheduler health
- **Recommended fix:** In CockpitPanel compute hours since generated_at; render an amber STALE badge >26h and red >50h with 'scheduler may be dead — check schtasks' remediation; optionally have the API stamp artifact_age_hours.

### SP-026 — Core risk vocabulary (DEFENSIVE, gate-refused, INSUFFICIENT_EVIDENCE, IDS demotions) has zero frontend surface

- **Category:** ux-leakage  |  **Severity:** High  |  **Confidence:** High  |  **Source:** segment-G  |  **Effort:** M  |  **Next sprint:** Yes
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `Grep 'DEFENSIVE|INSUFFICIENT_EVIDENCE|gate.refused|GATE_REFUSED' across frontend/src — No matches found`
  - `frontend/src/components/ScoreCalibrationBadge.tsx:19-44 — calibration is surfaced only via UNCALIBRATED/sample-size vocabulary; the IDS/half-life/payoff-capture DEFENSIVE caps and NBI gate-refused cases (e.g. CAA) exist only in scripts/ artifacts`
- **Observed:** The interpretation-defense stack (IDS, SNACK caps, WEAK_CAPTURE, mythos strategy eligibility) and gate-refusal outcomes are computed in scripts/ and written to runtime artifacts, but no Next.js page renders any of these states.
- **Why it matters:** These demote-only risk layers are the product's claimed differentiator ('interpretation defense > data collection'); an operator using only the UI sees priority scores and bull states but never the demotions that are supposed to protect them.
- **Failure mode:** A signal capped to DEFENSIVE by the half-life/payoff-capture demoters still appears in the inbox as a high-priority card; the operator manually acts on a signal the backend's own defense layers flagged, because the flag lives only in a CLI artifact.
- **Business impact:** The safety layers cannot prevent the operator mistake they were built to prevent; paper-trade journal quality degrades and the 'harder to fool' thesis is unverifiable from the product surface.
- **Score impact:** G -0.5
- **Recommended fix:** Add an IDS/risk-cap strip to SignalCard (grade + DEFENSIVE cap + primary_value_leak) fed by a new read-only endpoint over the existing artifacts, and render NBI gate-refused cases on /nbi.

### SP-027 — Sheet sync and bulk trade logger send no Authorization header — both fail 401 under the recommended token-secured config

- **Category:** runtime-leakage  |  **Severity:** High  |  **Confidence:** High  |  **Source:** segment-H  |  **Effort:** XS  |  **Next sprint:** Yes
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `scripts/sync_google_sheet_reconciliation.py:447 — requests.post(endpoint, json=payload, timeout=timeout) with no headers`
  - `scripts/api_server.py:2948 — _auth: None = Depends(require_api_token) on /reconciliation/auto-update`
  - `scripts/api_server.py:779-786 — _check_bearer_token raises 401 when MVP_API_TOKEN(_HASH) is set and no bearer supplied`
  - `scripts/bulk_log_manual_trades.py:98 — submit_one also posts bare`
- **Observed:** Neither client script references MVP_API_TOKEN or sets any Authorization header; both target endpoints enforce bearer auth whenever a token is configured.
- **Why it matters:** The moment the operator hardens the API (which other segments' security work pushes toward), every sheet row POST returns 401, the sync reports failed rows forever, and the integration silently dies.
- **Failure mode:** Operator sets MVP_API_TOKEN, runs sync_google_sheet_reconciliation.py --loop; every actionable row fails with 401, exit code 1 each pass, zero reconciliation entries recorded, sheet never written back.
- **Business impact:** Security and the flagship sheet integration are mutually exclusive; forces operators to run unauthenticated to use sync.
- **Score impact:** H down ~1.0; also drags security posture narrative
- **Recommended fix:** Read MVP_API_TOKEN from env in both scripts and send Authorization: Bearer <token> when set; add a smoke test asserting the header is attached.

### SP-028 — Sync is non-idempotent for 3 of 4 actions: column U is never cleared and the endpoint appends without dedupe

- **Category:** data-leakage  |  **Severity:** High  |  **Confidence:** High  |  **Source:** segment-H  |  **Effort:** S  |  **Next sprint:** Yes
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `scripts/sync_google_sheet_reconciliation.py:303-316 — STOP_HIT/CLOSE_TRADE/RECONCILE decisions have no already-synced guard (only LOG_PARTIAL_TP checks V at :294-297)`
  - `scripts/sync_google_sheet_reconciliation.py:25 — writeback touches 'status columns V/W/X/Y/Z only', never clears U (ACTION REQUIRED)`
  - `scripts/api_server.py:3008-3009 — endpoint unconditionally append_jsonl's every accepted POST, no idempotency lookup`
- **Observed:** A row with U='CLOSE TRADE' is re-posted on every run; in --loop --interval-minutes 30 mode that is a duplicate CLOSE_TRADE audit record every 30 minutes indefinitely.
- **Why it matters:** The audit trail — the only local artifact of sheet activity — fills with duplicates, making any future consumer (calibration, reconciliation counts, operator review) count the same close event N times.
- **Failure mode:** Operator marks CLOSE TRADE Monday, leaves the loop running; by Friday the audit log holds ~240 identical CLOSED records for one trade, and any downstream aggregation over the log is wrong by two orders of magnitude.
- **Business impact:** Corrupts the bookkeeping record the sync exists to create; destroys trust in sheet-derived history.
- **Score impact:** H down ~1.0 (idempotency is an explicit segment criterion)
- **Recommended fix:** Skip rows whose Z recon status is already terminal for the corresponding action, and/or dedupe server-side on (sheet_row_number, action, date) mirroring the existing /manual-trades Idempotency-Key machinery.

### SP-029 — Endpoint returns 'recorded' even when the audit append fails, then the sheet is marked SYNCED — silent data loss with false confirmation

- **Category:** data-leakage  |  **Severity:** High  |  **Confidence:** High  |  **Source:** segment-H  |  **Effort:** XS  |  **Next sprint:** Yes
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `scripts/api_server.py:3008-3012 — except Exception around append_jsonl only logs a warning`
  - `scripts/api_server.py:3014-3015 — handler proceeds to return {'status': 'recorded', ...} regardless`
  - `scripts/sync_google_sheet_reconciliation.py:601-611 — writeback (Z=CLOSED etc.) runs on any 2xx response`
- **Observed:** A disk-full/readonly-FS failure on the JSONL append is swallowed; the client sees 2xx, applies writeback, and the sheet row is permanently stamped CLOSED/SYNCED while no local record exists.
- **Why it matters:** The sheet's SYNCED stamp is the operator's only signal that the local system captured the event; a false stamp means the event is unrecoverable without manual sheet archaeology.
- **Failure mode:** runtime/ volume fills during a loop pass; five CLOSE_TRADE rows get Z=CLOSED on the sheet, zero audit records locally; the U-column workflow moves on and the events are never re-sent.
- **Business impact:** Permanent divergence between operator's sheet truth and local record with no error surfaced — exactly the failure a reconciliation system must not have.
- **Score impact:** H down ~0.7 (failure-recovery criterion)
- **Recommended fix:** Fail closed: return HTTP 500 (or status='audit_write_failed') when append_jsonl raises, so the client counts the row failed and skips writeback.

### SP-030 — Sheet sync is a write-only audit trail: nothing consumes the log, and CLOSE_TRADE/STOP_HIT never propagate to the reconciliation queue or holdings truth

- **Category:** architecture-leakage  |  **Severity:** High  |  **Confidence:** High  |  **Source:** segment-H  |  **Effort:** M  |  **Next sprint:** Yes
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `scripts/api_server.py:2989-3009 — handler builds an audit dict and appends JSONL; no persistence/queue/holdings call`
  - `repo-wide grep 'sheet_sync_reconciliation_audit' — only scripts/api_server.py and tests/test_sync_google_sheet_reconciliation.py reference it`
  - `scripts/sync_google_sheet_reconciliation.py:6-8 — docstring claims 'the audit log, learning surfaces, and reconciliation queue stay in sync' (overstated)`
  - `grep verified_current_holdings in scripts/ — 7 files, none in the sheet-sync path`
- **Observed:** A CLOSE_TRADE synced from the sheet produces one JSONL line and nothing else; verified_current_holdings.json, closed_positions.json, and /manual-trades/{id}/reconcile are untouched.
- **Why it matters:** The product claim 'portfolio/Google Sheets sync' reduces to an unread log file; real reconciliation still requires the operator to hand-edit holdings JSON and separately drive the Reconciliation UI.
- **Failure mode:** Operator closes a position in the sheet, trusts the CLOSED writeback, never edits verified_current_holdings.json; the portfolio truth gate keeps treating the ticker as OPEN and daily synthesis reasons over a phantom holding.
- **Business impact:** Stale holdings truth silently feeds every downstream advisory surface — the highest-trust artifact in the system diverges from reality.
- **Score impact:** H down ~1.2 (core sync-correctness criterion); touches A/B narrative on truth integrity
- **Recommended fix:** Have the endpoint (or a consumer job) cross-check audit records against verified_current_holdings.json and raise a visible mismatch item in the reconciliation queue; document the sync as audit-only until then.

### SP-031 — NBI run-once exits 0 on BROKEN runs — Task Scheduler will report success on failure

- **Category:** runtime-leakage  |  **Severity:** High  |  **Confidence:** High  |  **Source:** segment-I  |  **Effort:** XS  |  **Next sprint:** Yes
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `scripts/nbi_scheduler.py:573 — return 0 if record.get("status") != STATUS_FAILED else 1`
  - `scripts/nbi_scheduler.py:276-284 — statuses actually set are BROKEN/BROKEN_UNSAFE/HEALTHY/DEGRADED_BUT_SAFE; STATUS_FAILED (line 57) is a legacy alias never assigned`
- **Observed:** run-once maps its result to an exit code by comparing against STATUS_FAILED, a legacy constant run_once never produces; BROKEN and BROKEN_UNSAFE therefore exit 0.
- **Why it matters:** The scheduled task's ONLY machine-visible health signal is its exit code (schtasks Last Result). This bug guarantees Last Result=0 even when the factory cycle crashed or the safety check failed.
- **Failure mode:** run_daily throws tomorrow at 08:30 → status=BROKEN written to JSON → process exits 0 → schtasks shows Last Result 0 → operator and any future monitoring see green forever.
- **Business impact:** Silent daily-loop failure indefinitely; the NBI case-accumulation clock (2/30 toward edge claim) stalls without anyone noticing, undermining the core evidence-building narrative shown to investors.
- **Score impact:** Drags I heavily (~-1.0); also touches evidence segments that depend on daily accumulation
- **Recommended fix:** Return 0 only for HEALTHY/DEGRADED_BUT_SAFE, nonzero for BROKEN/BROKEN_UNSAFE; add a unit test asserting the mapping for all four statuses.

### SP-032 — No failure alerting anywhere — every scheduled loop dies silently; watchdog abandoned since 2026-05-25

- **Category:** runtime-leakage  |  **Severity:** High  |  **Confidence:** High  |  **Source:** segment-I  |  **Effort:** S  |  **Next sprint:** Yes
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `logs/refresh_watchdog.log — two 'watchdog start' lines dated 2026-05-25, nothing since; grep for refresh_watchdog across **/*.py returns no files (script deleted)`
  - `grep -i alert|notify|webhook|toast in scripts/*scheduler*.py — no matches`
  - `scripts/check_live_signal_refresh_task.py:1-13 — pure read-only pull diagnostic for the frontend panel; nothing pushes`
- **Observed:** Observability is entirely pull-based (log files, last-run JSON, a frontend status panel). No email, toast, webhook, or even a beep on failure or staleness. The one push-style component (refresh watchdog) was abandoned after one day and its script removed.
- **Why it matters:** A single-operator laptop system with unattended scheduled jobs and no alerting means failures are discovered days later, if at all — exactly the failure class the memory notes ('did the loop run TODAY?') keep re-litigating.
- **Failure mode:** Machine asleep at 08:30, or refresh task starts failing after a Windows update → nothing fires → operator discovers a multi-day gap only when manually opening the dashboard.
- **Business impact:** Data gaps corrupt freshness-dependent gates (chicken gate, calibration horizons) and destroy the 'evidence factory' credibility; investor demo of 'automated daily loop' is falsifiable on inspection.
- **Score impact:** Primary drag on I (~-1.5)
- **Recommended fix:** Add a tiny staleness sentinel: on each frontend/API load (and optionally a third schtasks heartbeat every hour) compare nbi_scheduler_last_run.json and live_signal_refresh_summary.json age vs cadence; raise a Windows toast + prominent red banner when stale or last status != HEALTHY/PASS.

### SP-033 — NBI daily 08:30 task has never fired via the scheduler; 'HEALTHY 10/10' claim comes from manual runs only

- **Category:** evidence-leakage  |  **Severity:** High  |  **Confidence:** High  |  **Source:** segment-I  |  **Effort:** S  |  **Next sprint:** Yes
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `schtasks /query /v — SleepingPassenger_NBI_DailyLoop: Last Run Time 30-11-1999 00:00:00, Last Result 267011 (task not yet run), Next Run 04-07-2026 08:30`
  - `runtime/nbi_scheduler.log — exactly two entries, 2026-07-03T08:03Z and 12:36Z, both manual run-once invocations (08:30 local task cannot have produced 08:03 UTC = 13:33 IST)`
- **Observed:** The task was installed today after its 08:30 start time, so the scheduled execution path (cmd /c cd ... C:\Python313\python.exe -m scripts.nbi_scheduler run-once, Interactive-only session) is untested end-to-end. The recorded 10/10 health came from manual shell runs under different conditions.
- **Why it matters:** Session notes and memory present 'OS task INSTALLED... HEALTHY 10/10' as if the automated loop is proven. Installation is proven; automated execution is not. These are different claims.
- **Failure mode:** Tomorrow 08:30: user not logged in (Interactive-only logon mode), or laptop on battery (No Start On Batteries), or asleep (no StartWhenAvailable on schtasks /Create) → run silently skipped; or the cmd/c non-interactive environment differs and the run breaks — and per the exit-code bug, may still report 0.
- **Business impact:** The flagship new capability (NBI daily evidence factory) may not actually run unattended; case accumulation toward the 30-case edge gate stalls.
- **Score impact:** Drags I (~-0.8) and the NBI evidence narrative
- **Recommended fix:** After the first genuinely scheduled run, verify schtasks Last Run Time/Result and runtime/nbi_scheduler_last_run.json agree; migrate registration to Register-ScheduledTask with -StartWhenAvailable, battery-allowed, and S4U/logon-independent settings (pattern already exists in scripts/windows/register_live_signal_refresh_task.ps1:105).

### SP-034 — Daily payload / holdings-truth chain is not scheduled at all — verified_current_holdings.json is 26 days stale

- **Category:** data-leakage  |  **Severity:** High  |  **Confidence:** High  |  **Source:** segment-I  |  **Effort:** M  |  **Next sprint:** Yes
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `data/daily_payload/verified_current_holdings.json LastWriteTime 07-06-2026 23:20:33 (all 8 daily_payload files stale since June 7)`
  - `grep chicken_gate_daily_bridge|build_daily_payloads in scripts/**/*.ps1 — no matches; schtasks shows only 3 tasks, none runs the payload/synthesis chain`
- **Observed:** The canonical holdings truth file and the entire daily payload set were last built 2026-06-07. No scheduled task, wrapper, or watchdog runs build_daily_payloads.py or chicken_gate_daily_bridge.py; they run only inside operator/agent sessions.
- **Why it matters:** The daily-synthesis truth gate doctrine says holdings truth lives in this file. Any consumer (chicken gate, cockpit, reconciliation) reading it today gets a month-old portfolio picture presented as 'verified current'.
- **Failure mode:** Operator sells or adds a position mid-June; advisory outputs and gates keep reasoning against June-7 holdings; a 'fresh' daily card silently mixes today's signals with stale positions.
- **Business impact:** Advisory recommendations grounded in stale holdings are the closest this advisory-only system gets to real capital harm; also directly falsifies the 'daily' product claim in diligence.
- **Score impact:** Drags I (~-0.7) and data-truth segments
- **Recommended fix:** Either schedule the payload build (extend the 6h refresh wrapper or a new daily task) with a freshness stamp, or make every consumer of verified_current_holdings.json hard-fail/flag when the file is older than N days.

### SP-035 — Zero coverage measurement; ~14% of scripts never touched by any test

- **Category:** test-leakage  |  **Severity:** High  |  **Confidence:** High  |  **Source:** segment-J  |  **Effort:** S  |  **Next sprint:** Yes
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `grep for pytest-cov/--cov/coverage across requirements*.txt, pytest.ini, workflows — no matches`
  - `Bash scan: 57 of 413 scripts/*.py never referenced by name in tests/ (e.g. composite_edge_score, narrative_drift_monitor, execution_quality_scorer, bulk_log_manual_trades)`
- **Observed:** 7567 tests pass but there is no line/branch coverage data anywhere; a name-grep shows 57 top-level scripts with zero test references, and name-reference is an upper bound on real coverage.
- **Why it matters:** The headline test count is unverifiable as protection: entire scoring/engine modules can regress silently, and an investor cannot distinguish tested core from untested experiments.
- **Failure mode:** A refactor breaks composite_edge_score or narrative_drift_monitor logic; the 7567-test suite stays green; the broken score feeds downstream advisory output undetected.
- **Business impact:** Silent signal-quality regression erodes the product's core claim (defensible advisory scores) and destroys diligence trust when discovered.
- **Score impact:** J −1.0; also drags A/B (signal quality assurance) indirectly
- **Recommended fix:** Add pytest-cov to requirements-dev.txt and pytest.yml (report-only first), publish the coverage report as a CI artifact, then set a floor (e.g. 70%) and quarantine or delete the 57 unreferenced scripts into archived_experimental/.

### SP-036 — CI does not demonstrably gate anything — direct-push workflow bypasses PR checks

- **Category:** test-leakage  |  **Severity:** High  |  **Confidence:** Medium  |  **Source:** segment-J  |  **Effort:** XS  |  **Next sprint:** Yes
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `.github/workflows/pytest.yml:11-13 — triggers on push/pull_request but branch protection state is unverifiable locally (gh not installed; git remote is github.com/akashguha9/sleeping-passenger-v1)`
  - `MEMORY.md auto-commit-push-hook note — harness auto-commits AND pushes edits directly to origin, i.e. commits land on branches without PR review`
- **Observed:** All four workflows run on push, but the development flow pushes commits straight to branches; there is no local evidence of branch protection or required status checks on main, so a red CI run blocks nothing.
- **Why it matters:** Regression defense requires a gate, not a dashboard. Post-hoc CI that nobody is forced to heed is materially weaker than its workflow files suggest.
- **Failure mode:** A commit that fails the kante defensive gate is pushed and merged to main anyway; the release gate failure is only noticed after downstream artifacts are already built from broken code.
- **Business impact:** Undermines the entire 'merge-blocking defensive gate' claim in kante_defensive_gate.yml; a diligence reviewer checking branch protection would flag the gap immediately.
- **Score impact:** J −0.8
- **Recommended fix:** Enable branch protection on main requiring backend pytest, safety floor, frontend, and defensive-gate checks; route work through PRs (the branches already exist); optionally add a repo test asserting required-checks config via a committed settings snapshot.

### SP-037 — TESTING.md is factually false about the test estate

- **Category:** documentation-gap  |  **Severity:** High  |  **Confidence:** High  |  **Source:** segment-L  |  **Effort:** S  |  **Next sprint:** Yes
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `TESTING.md:9 — 'Runs ~100 test files' vs actual 443 files / 7567 passing tests`
  - `TESTING.md:67-68 — 'No Vitest/Jest/Playwright installed' vs frontend/vitest.config.ts + playwright.config.ts present and vitest 201/201 passing`
  - `TESTING.md:68 — 'next lint is the only automated frontend check' — next lint is broken under Next 16 (validated this session)`
- **Observed:** The canonical testing doc understates backend coverage by 4x and denies the existence of the frontend test stack that actually passes.
- **Why it matters:** Testing depth is this repo's single strongest asset; the doc actively hides it and simultaneously plants a falsifiable claim an auditor disproves in one command.
- **Failure mode:** Investor runs pytest/vitest, sees 7567+201 tests, concludes the docs cannot be trusted on anything else — including the safety claims.
- **Business impact:** Credibility discount applied to the entire documentation corpus, including the advisory-only guarantees.
- **Score impact:** L -1.0; also drags perceived credibility of claims in other segments
- **Recommended fix:** Rewrite TESTING.md against current reality: real counts, vitest/playwright sections, note that next lint was removed in Next 16 and what replaces it.

### SP-038 — Dueling stale self-audits (4.8/10 vs 8.2/10) unreconciled at repo root

- **Category:** documentation-gap  |  **Severity:** High  |  **Confidence:** High  |  **Source:** segment-L  |  **Effort:** S  |  **Next sprint:** Yes
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `AUDIT_BRUTAL_MVP_ASSESSMENT.md:5 — 'Overall MVP score: 4.8/10'; :50 '90 Python test files'; last commit 2026-05-08`
  - `docs/FINAL_SCORECARD.md:22 — 'Post-Day 26-35 (today) 8.2' citing 2950 backend tests; last commit 2026-05-13`
  - `docs/FINAL_SCORECARD.md — Documentation/onboarding rated 9/10 'Truly complete top-to-bottom', contradicted by stale TESTING.md/README`
- **Observed:** Two authoritative-looking scorecards give scores 3.4 points apart, both citing repo statistics now off by 2.5-4x, with no in-file dates or superseded markers; SHOWCASE.md points readers to FINAL_SCORECARD as 'honest scoring'.
- **Why it matters:** Self-assessment coherence is exactly what a forensic investor tests first; contradictory undated scorecards read as either sloppiness or narrative management.
- **Failure mode:** Diligence reviewer quotes both numbers back at the founder and asks which one is the lie.
- **Business impact:** Undermines the 'honesty culture' differentiator that is otherwise this product's best investor story.
- **Score impact:** L -0.9
- **Recommended fix:** Add a dated HISTORICAL banner to AUDIT_BRUTAL_MVP_ASSESSMENT.md, date-stamp FINAL_SCORECARD, and add a single current-state assessment doc that reconciles or supersedes both.

### SP-039 — README (55KB) does not describe the current product: 7 of 16 routes and all June/July flagship features missing

- **Category:** documentation-gap  |  **Severity:** High  |  **Confidence:** High  |  **Source:** segment-L  |  **Effort:** M  |  **Next sprint:** Yes
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `README.md:771-783 — Pages table lists 9 routes; next build ships 16 (missing /nbi, /cockpit, /securities, /chart-structure, /help)`
  - `grep of README.md — 0 matches for Kanté|Mythos|chicken gate|NBI|narrative branch`
  - `README.md:140-180 — bulk of the 1274 lines is 'Pipeline V5.7 Core — historical reference' explicitly flagged as non-canonical`
- **Observed:** The front door of the repo documents the May-era product; the NBI cockpit (frontend /nbi route + installed OS scheduled task), chicken gate, and Mythos/signal-arbitrage layers — the subjects of every recent commit — are invisible.
- **Why it matters:** README is the investor's first 10 minutes; it currently undersells the newest work and oversells stale 'historical reference' plumbing.
- **Failure mode:** Reader opens /nbi in the running app, finds no README mention, and cannot tell what is product versus abandoned experiment.
- **Business impact:** The most differentiated recent work (real scheduler truth, calibration-eligible case corpus) contributes nothing to the pitch.
- **Score impact:** L -0.8
- **Recommended fix:** Add a CURRENT STATE (2026-07-03) section: full 16-route table, links to NARRATIVE_BRANCH_ENGINE.md / chicken_gate_runbook.md / MYTHOS_FABLE_OPERATIONAL_LOOP.md; move the historical-reference bulk to docs/history/.


### 10.2 Medium and Low (66)

### SP-040 — Same-day health artifacts contradict each other (HEALTHY 10/10 vs DEGRADED_BUT_SAFE 5.25)

- **Category:** evidence-leakage  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-A  |  **Effort:** S  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `runtime/nbi_scheduler_last_run.json:5-13 — status HEALTHY, SchedulerHealth10=10, feed_available=1, current_case_count 0 (12:36 UTC)`
  - `runtime/nbi_live_ops_cockpit.md:5-11 — DEGRADED_BUT_SAFE, LiveOpsHealth10=5.25, Feed FEED_NOT_WIRED usability 0.0, eligible cases 2/30 (12:40 UTC)`
- **Observed:** Four minutes apart on 2026-07-03, the scheduler report claims a fully healthy run with an available feed and 0 cases, while the cockpit reports no feed wired, no market fetch, and 2/30 cases.
- **Why it matters:** The operator has two 'truth' artifacts for the same loop that disagree on health, feed availability, and case count. Which one governs the morning decision is undefined.
- **Failure mode:** Operator sees HEALTHY 10/10 from the scheduled task, skips the cockpit, and never notices the feed is not wired — the accumulation loop silently stalls at 2/30 for weeks.
- **Business impact:** Contradictory self-reporting erodes the product's central differentiator: honest measurement.
- **Score impact:** A -0.4; also drags F/evidence segment
- **Recommended fix:** Make the scheduler's health components consume the same feed/case measurements the cockpit uses (single source module), and stamp both artifacts with the shared measurement snapshot ID.

### SP-041 — Operator experience fragmented across 4+ surfaces with ~15-20 manual daily commands

- **Category:** ux-leakage  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-A  |  **Effort:** M  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `docs/PRIVATE_OPERATOR_DAILY_CHECKLIST.md:45-114 — 9-step morning ritual, each a manual PowerShell command`
  - `docs/PRIVATE_OPERATOR_DAILY_CHECKLIST.md:148-174 — 6-step evening ritual`
  - `runtime/nbi_operator_cards.html + nbi_live_ops_cockpit.md — decision content delivered as loose runtime files outside the web app`
  - `src/dashboard/streamlit_app.py — a second dashboard stack alongside the 16-route Next.js app`
- **Observed:** Decision-grade information lives in the Next.js app (16 routes), raw runtime .md/.html/.json artifacts, a Streamlit app, reports/, and a private checklist; the morning routine alone requires ~9 manual commands before any signal review.
- **Why it matters:** The segment question is whether a non-author can act each morning. Today they must know which of four surfaces is canonical and run a git/audit/token/backup gauntlet first; the friction guarantees skipped steps and inconsistent data hygiene.
- **Failure mode:** Operator skips the 9-step preflight on a busy day, reviews signals against a stale refresh, and records paper decisions the calibration gate later has to discard.
- **Business impact:** High operator burden caps daily usage and makes the product undemonstrable to anyone but the author.
- **Score impact:** A -0.6
- **Recommended fix:** Ship a single 'morning brief' command/route that aggregates checklist readiness (already computable from local_mvp_audit sections), NBI cockpit, fresh discovery status, and holdings staleness into one pass/fail page in the Next.js app.

### SP-042 — Five-model synthesis loop is dormant and operationally hostile (5 per-session API keys, hardcoded model IDs)

- **Category:** runtime-leakage  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-A  |  **Effort:** M  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `runtime/five_model_synthesis — newest run directory 2026-06-03 (one month old)`
  - `scripts/run_five_model_synthesis.ps1:20-25 — hardcoded model IDs (gpt-5.5, claude-sonnet-4-6, grok-4.3, gemini-3.1-pro-preview, mistral-large-latest)`
  - `scripts/run_five_model_synthesis.ps1:31-60 — throws unless OPENAI/ANTHROPIC/XAI/GEMINI/MISTRAL keys are all set in the current window`
- **Observed:** The flagship five-model synthesis workflow requires manually exporting five vendor keys per PowerShell session and has produced no output since 2026-06-03, while docs still present it as part of the canonical daily loop.
- **Why it matters:** A headline capability in the architecture is effectively abandoned as an operator workflow; docs and reality have diverged.
- **Failure mode:** A new operator follows the synthesis docs, hits five sequential key-validation throws, and concludes the product does not work; or runs it with partial keys and gets an inconsistent synthesis context.
- **Business impact:** Dead flagship features in a demo are worse than absent ones — they read as abandonment.
- **Score impact:** A -0.3; also drags K/architecture segment
- **Recommended fix:** Either demote the five-model loop to explicitly-optional research tooling in docs, or automate it behind the existing scheduler with a single key-presence preflight that degrades to fewer models instead of throwing.

### SP-043 — Five sprints of 'shipped' scoring logic stranded on an unmerged branch; canonical branch diverges from documented system

- **Category:** architecture-leakage  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-B  |  **Effort:** M  |  **Next sprint:** Yes
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `git branch --contains fb6f396 — only backup/pre-gitleaks-rewrite and feature/p2-interpretation-defense-expansion; NOT live-data-config-sprint`
  - `docs/chicken_gate_consolidation_map.md:38-52 — IDS P2 stack, signal_half_life_estimator, payoff-capture, wrapper-premium all listed as 'Stranded on feature/p2-interpretation-defense-expansion'`
  - `scripts/chicken_gate.py:298-302 — word lists hand-ported from the branch, creating a fork of the same logic`
- **Observed:** scripts/isolated_model_lanes.py, model_vote_aggregator.py, and the entire interpretation_defense (IDS) stack do not exist on the working branch despite project memory describing them as shipped; a subset was manually copy-ported into chicken_gate.
- **Why it matters:** The scoring surface an auditor (or the operator) believes exists differs from what runs; hand-ported word lists will drift from their branch source.
- **Failure mode:** Branch merge later reintroduces a second demote stack that double-penalizes or contradicts the ported chicken_gate logic; or the branch rots and five sprints of work are silently lost.
- **Business impact:** Capability claims in docs/memory overstate the deployed system — a direct diligence-trust hit.
- **Score impact:** B −0.5
- **Recommended fix:** Decide once: merge feature/p2-interpretation-defense-expansion as input-estimators per the consolidation map, or formally retire it and delete the stranded-module references from docs.

### SP-044 — Composite Edge Score thresholds justified by three hindsight-picked anecdotes

- **Category:** calibration-leakage  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-B  |  **Effort:** XS  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `scripts/composite_edge_score.py:32 — 'Component weights (heuristic until calibrated on T=10+ outcomes)'`
  - `scripts/composite_edge_score.py:71-95 — RTX win, CVX loss, GLD hold retrofitted as validation of CE=0.70/0.55/0.40 tiers`
- **Observed:** CE weights and the FIRE_MODE-eligible 0.70 threshold are supported only by three retrospective portfolio stories written into comments; N=3, selected after outcomes were known.
- **Why it matters:** This is textbook hindsight fitting presented as evidence; the tier boundaries route real operator attention (IL_STAGGER/IL_PROBE).
- **Failure mode:** Thresholds that happened to separate three past cases fail silently on the next regime; the 'chemistry law: you need CE >= 0.70' becomes false confidence.
- **Business impact:** Anecdote-as-validation in source comments is exactly what a quant reviewer flags as unserious.
- **Score impact:** B −0.4
- **Recommended fix:** Mark CE output as UNCALIBRATED_HEURISTIC in its payload; move the anecdotes to docs as illustrations, not validation; wire CE into the same N>=50 recalibration gate chicken_gate declares.

### SP-045 — Hard blocks and half-life priors driven by brittle keyword lists, trivially evaded by paraphrase

- **Category:** signal-leakage  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-B  |  **Effort:** M  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `scripts/chicken_gate.py:144-192 — gambler's-fallacy detection is a fixed phrase list + 2 regexes; 'shares will revert to fair value' or 'the selloff is overdone' match nothing`
  - `scripts/chicken_gate.py:304-340 — SNACK/SIGNAL/DURABLE half-life classification = counting hits from two ~15-word lists`
- **Observed:** Reversal-language hard-blocking (fallacy_unbacked => BUY_BLOCKED) and catalyst-durability priors depend entirely on exact substring matches; negation handling is a 60-char token window.
- **Why it matters:** The gate's strongest behavioral protection (blocking unbacked mean-reversion theses) only fires on stock phrasings; any operator who writes naturally sidesteps it, so protection is illusory on the cases that matter.
- **Failure mode:** Thesis 'the market is overreacting, fair value is 30% higher' passes the fallacy guard with zero node evidence and reaches BUY_ALLOWED on otherwise-clean inputs.
- **Business impact:** Advertised 'harder to fool' properties do not survive adversarial or even casual rephrasing; a demo reviewer can break it in one prompt.
- **Score impact:** B −0.4
- **Recommended fix:** Add an LLM-assisted (or embedding-similarity) reversal/durability classifier as a second opinion, keeping the word lists as the deterministic floor; log misses when the two disagree.

### SP-046 — Exponential decay math independently implemented in four modules, including v1 and v2 of the same file

- **Category:** architecture-leakage  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-B  |  **Effort:** S  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `scripts/candidate_memory_decay.py:55-66 and scripts/candidate_memory_decay_v2.py:125 — both live, both exp(−λd)`
  - `scripts/signal_decay_waste.py (compute_decay_factor) and scripts/activation_trigger_tracker.py:64 — two more decay engines`
  - `docs/chicken_gate_consolidation_map.md:25 — duplication acknowledged, action 'IGNORE (different consumer; do not extend)'`
- **Observed:** Four separate half-life/decay implementations with independently chosen lambdas coexist; the consolidation map explicitly chooses to leave them.
- **Why it matters:** The same thesis age can decay at different rates depending on which pipeline touches it; parameter fixes must be applied in four places.
- **Failure mode:** A recalibrated half-life lands in signal_decay_waste but not candidate_memory_decay_v2, so gate freshness and candidate-board freshness silently disagree on the same name.
- **Business impact:** Quiet inconsistency between surfaces the operator compares side by side; erodes trust in the numbers.
- **Score impact:** B −0.3
- **Recommended fix:** Extract one decay module (keep signal_decay_waste as owner per the map) and make the other three import it; delete candidate_memory_decay v1.

### SP-047 — No capital-based position sizing math anywhere — bands and unit multipliers only

- **Category:** capital-risk-leakage  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-C  |  **Effort:** M  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `scripts/complex_systems_diagnostics.py:883-902 — survival_adjusted_size is base_size(1.0 notional unit) x quality factors, explicitly 'never an absolute order size'`
  - `moltbook/open_positions.json:7 — position_size is the string 'QUARTER_UNIT'`
  - `Grep 'position_size|risk_per_trade|kelly' in src/ — No files found`
- **Observed:** Sizing output is qualitative (avoid/watchlist/probe/small/normal) or a 0-1 multiplier on an undefined operator unit; there is no risk-per-trade %, no stop-distance R math, no account-size concept.
- **Why it matters:** Advisory-only does not excuse absent sizing math — 'risk 0.5R with stop at X implies N shares' is exactly the advisory arithmetic a risk engine should provide and it is nowhere.
- **Failure mode:** Operator receives 'band=small' with no translation to quantity; sizing decisions remain fully discretionary and unauditable against any rule.
- **Business impact:** The 'risk scoring' product claim reduces to adjectives; weak against any quant-literate diligence.
- **Score impact:** C down ~0.6
- **Recommended fix:** Ship an advisory R-based sizing calculator (account_size + risk_pct + stop distance -> suggested quantity, stamped ADVISORY_ONLY) and record planned R at trade-log time.

### SP-048 — No live portfolio drawdown monitor; drawdown math exists only in backtest and NBI edge gate

- **Category:** capital-risk-leakage  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-C  |  **Effort:** M  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `scripts/backtest_advisory_signals.py:81 — max_drawdown over backtest returns only`
  - `scripts/nbi_track_record_ledger.py:50,215-217 — 5R drawdown limit gates edge CLAIMS, not live risk`
  - `Grep 'drawdown' across scripts/ — remaining hits are scenario/report inputs (bruce_lee/chess/hedge modules), none reading verified holdings`
- **Observed:** No component computes running P&L or drawdown of the actual holdings set; there is no equity curve, no peak-to-trough tracking, and no de-risking rule (e.g. reduce after X% drawdown) wired to anything real.
- **Why it matters:** Drawdown control is a named requirement of this segment; the repo has the vocabulary in six modules but zero connection to live capital.
- **Failure mode:** Portfolio bleeds 20% across positions over weeks; no gate tightens, allow_new_risk stays wherever the operator left it, and REVIEW_FOR_ENTRY advisories keep flowing.
- **Business impact:** No systematic loss-containment story; compounding losses are invisible to the system that claims discipline.
- **Score impact:** C down ~0.5
- **Recommended fix:** Daily job: mark verified holdings to market, persist portfolio equity series, compute rolling drawdown, and demote policy to allow_new_risk=false past a threshold.

### SP-049 — No price-staleness guard in the stop-breach path (provider outage scenario unhandled)

- **Category:** runtime-leakage  |  **Severity:** Medium  |  **Confidence:** Medium  |  **Source:** segment-C  |  **Effort:** S  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `scripts/action_engine.py:190-199 — _price_breached_stop compares position['current_price'] to stop with no timestamp/age check`
  - `Grep 'stale|freshness|price_age' in action_engine.py — only degraded_mode annotation flags, nothing gating the price comparison itself`
- **Observed:** current_price is consumed as a bare float with no as-of timestamp; a provider outage leaves the last stored price in place and stop/target checks keep evaluating it as current.
- **Why it matters:** During exactly the adverse scenario where stops matter most (fast market + feed outage), the engine confidently reports no breach on frozen prices.
- **Failure mode:** Feed dies at 09:31, position gaps through its stop at 09:45; action engine keeps returning HOLD on the 09:30 price all day with no DEGRADED marker on the action itself.
- **Business impact:** Silent wrong advisories under stress — worse than no advisory because it suppresses operator vigilance.
- **Score impact:** C down ~0.4
- **Recommended fix:** Require price_as_of on position rows; if older than threshold, force action to MONITOR/DEGRADED with an explicit stale-price reason instead of evaluating breach logic.

### SP-050 — The 2 'REAL' NBI cases are retrospective historical events, not forward predictions

- **Category:** calibration-leakage  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-D  |  **Effort:** S  |  **Next sprint:** Yes
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `sqlite nbi_backtest_cases — case_kind='REAL' rows are case_id 'tpl-2016-brexit-referendum::template' and 'tpl-2015-vw-emissions::template', rumor_peak_timestamp NULL, resolution_timestamp 2026-07-03T14:00Z (stamped today)`
- **Observed:** CASE_ACCUMULATION 2/30 counts web-verified reconstructions of 2015/2016 events; they carry return_vs_benchmark (-0.081, -0.29) but no locked pre-event probability timestamp (rumor_peak NULL) and benchmark_json is an empty string.
- **Why it matters:** Retrospective cases are legitimate backtest corpus but cannot support forward-calibration claims; counting them toward the 30-case edge gate conflates hindsight with prediction.
- **Failure mode:** At 30/30 the edge gate opens on a corpus dominated by hindcast reconstructions with selection bias, producing a Brier score that overstates real skill.
- **Business impact:** First 'edge=true' claim would be methodologically indefensible to any quant reviewer.
- **Score impact:** D -0.5; poisons future edge-claim credibility
- **Recommended fix:** Split the gate: require N>=30 with a minimum quota of prospectively locked cases (rumor_peak_timestamp NOT NULL and < resolution), and populate benchmark_json provenance.

### SP-051 — No market-index benchmark (SPY/DAX) anywhere in the live outcome path

- **Category:** calibration-leakage  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-D  |  **Effort:** S  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `scripts/snapshot_maturity_scanner.py:86-95 — benchmark is SECTOR_RESIDUAL only if sector_prices injected, else BENCHMARK_UNAVAILABLE`
  - `data/calibration_corpus/retrocast.jsonl — fwd_return_1/5/21 fields, no benchmark fields`
  - `sqlite nbi_track_record — benchmark_return column exists but table has 0 rows`
- **Observed:** Benchmark comparison is schema-present but data-absent: the scanner defaults to no benchmark, retrocast rows carry raw returns only, and the one ledger with a benchmark column has never been written to.
- **Why it matters:** Raw hit rates without a benchmark cannot distinguish signal from beta; 'realized return' alone is not evidence of skill.
- **Failure mode:** A bull-market period produces high hit rates on long-biased signals; the system reports success that is entirely market beta.
- **Business impact:** Any performance narrative is dismissible in diligence; benchmark-relative reporting is table stakes.
- **Score impact:** D -0.5
- **Recommended fix:** Add SPY (and DAX for EU names) closes to the maturity scanner price fetch and emit residual_return vs index by default; backfill retrocast rows.

### SP-052 — 65 REAL_MANUAL trades are a single-day all-BUY bulk import contributing zero outcomes

- **Category:** data-leakage  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-D  |  **Effort:** XS  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `sqlite manual_trades — 65 rows, side=BUY 100%, trade_mode=REAL_MANUAL 100%, executed_at range 2026-07-02T10:06 to 16:36`
  - `calibration_gate.py --json output — with_outcome=0, with_lesson=0, with_trade_mode=0, status NOT_READY`
- **Observed:** The manual-trade lane, the other intended source of real outcomes, was populated by a one-shot holdings import with no exits, no lessons, and no reconciliation rows (reconciliation_results=0); the gate honestly scores it NOT_READY.
- **Why it matters:** The trade journal cannot yield closed round-trip outcomes until sells are logged; labeling imported holdings as REAL_MANUAL 'trades' also blurs entry-timestamp semantics (executed_at = import time, not true entry).
- **Failure mode:** If these rows later mature into outcome extraction, entry timestamps and prices reflect the import session, not actual acquisition, corrupting realized-return math.
- **Business impact:** Second evidence lane is inert and its data provenance is already slightly compromised for future calibration.
- **Score impact:** D -0.3
- **Recommended fix:** Tag imported rows with created_via=IMPORT and exclude them from outcome extraction unless true entry date/price is backfilled; log exits going forward.

### SP-053 — 846-row live Kalshi probability ledger has no resolution loop

- **Category:** calibration-leakage  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-D  |  **Effort:** M  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `data/calibration_corpus/pm_probability_ledger.jsonl — 846 rows, source_mode LIVE, is_live_verified true`
  - `grep pm_probability_ledger scripts/ — consumed only as row counts in run_daily_evidence.py:109,186 and signal_ceiling_score_report.py:101,145`
- **Observed:** The only genuinely live, accumulating dataset (Kalshi market probabilities with locked fetch timestamps) is used solely as an existence check ('rows>0 passes'); no code resolves markets to outcomes, so a free source of Brier-able (p, y) pairs is unexploited.
- **Why it matters:** Prediction-market resolutions arrive on known dates and would give the fastest, cheapest real Brier corpus the project could possibly have — faster than equity horizons.
- **Failure mode:** Months of live observations expire unresolved; the cheapest calibration evidence is permanently lost as markets close and delist.
- **Business impact:** Missed shortcut to a defensible real-data calibration curve.
- **Score impact:** D near-term ceiling suppressed ~0.5
- **Recommended fix:** Add a Kalshi settlement poller that joins observation_id to market resolution and appends (p, y, fetch_timestamp, resolve_timestamp) rows for Brier reporting.

### SP-054 — MarketDataLoader silently swallows empty frames and all per-ticker exceptions

- **Category:** evidence-leakage  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-E  |  **Effort:** XS  |  **Next sprint:** Yes
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `scripts/ingestion/market_data_loader.py:87-88 — 'if hist.empty: continue' with no record or log`
  - `scripts/ingestion/market_data_loader.py:148-149 — 'except Exception: continue' around the whole per-ticker body`
- **Observed:** A ticker that yfinance rejects (delisted, renamed, rate-limited) simply vanishes from the result; the run still logs status ok.
- **Why it matters:** Per-ticker failures are the most common yfinance failure mode (empty DataFrame on bad suffix or throttling); zero-diagnostics means symbol-mapping bugs (.DE/.L) are undetectable.
- **Failure mode:** Ticker list is expanded to holdings, half use wrong suffixes, run reports ok with fetched_count = half the list, nobody notices which half.
- **Business impact:** Coverage erosion without alarms; wasted operator debugging time.
- **Score impact:** E (~-0.4)
- **Recommended fix:** Emit a per-ticker failure record ({symbol, reason: empty|exception:<type>}) into the LoaderResult and count failures in source_run_log.skipped_reason.

### SP-055 — Duplicate health stores diverged: source_health table dead since 2026-06-02

- **Category:** architecture-leakage  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-E  |  **Effort:** XS  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `runtime/mvp_local.db — source_health max(run_at)='2026-06-02T17:03:51+00:00' (228 rows) while source_run_log has rows from 2026-07-03T16:00`
- **Observed:** Two tables claim to describe source health; one stopped updating a month ago and still exists as a queryable surface.
- **Why it matters:** Any consumer (dashboard, audit script) still reading source_health gets month-old health data presented as truth.
- **Failure mode:** Operator page or audit report wired to the dead table shows all-green from June 2 during a real outage.
- **Business impact:** Contradictory health answers depending on which table a page queries; audit credibility hit.
- **Score impact:** E (~-0.3)
- **Recommended fix:** Either migrate writers to source_health or drop/rename it to source_health_legacy and grep-audit consumers.

### SP-056 — No retry/backoff or 429 handling in adapters; only gdelt/etherscan/grok classify rate limits

- **Category:** runtime-leakage  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-E  |  **Effort:** S  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `src/ingestion/kalshi_live_client.py:266-272 — single session.get, raise_for_status, no retry/backoff/429 branch`
  - `grep -i 'retry|backoff|429|rate.limit' adapters(src/ingestion clients) → no matches outside scripts/ingestion/{gdelt,etherscan,grok}_loader.py`
- **Observed:** Transient HTTP failures on Kalshi/Polymarket/yfinance paths become hard run failures or silent skips; GDELT gets exactly one retry (gdelt_loader.py:32 _RETRY_SLEEP=0.5).
- **Why it matters:** Free-tier providers throttle routinely; a system claiming daily unattended operation (schtasks 08:30) needs bounded retries to survive ordinary flakiness.
- **Failure mode:** One 429 at 16:00 marks kalshi failed for the day; next data point is 24h later.
- **Business impact:** Elevated stale-source frequency on an unattended box; more operator babysitting.
- **Score impact:** E (~-0.4)
- **Recommended fix:** Add a shared bounded-retry helper (2 retries, exponential backoff, 429-aware Retry-After) used by all HTTP loaders and the Kalshi/Polymarket clients.

### SP-057 — fetched_count conflates fetched with persisted: today's market_data run says ok/4 but 0 rows landed

- **Category:** evidence-leakage  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-E  |  **Effort:** XS  |  **Next sprint:** Yes
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `source_run_log — market_data 'ok' fetched_count=4 at 2026-07-03T16:00:35, yet signal_events has 0 market_data rows with fetched_at>2026-07-03 (max is 2026-07-02T16:00:36)`
- **Observed:** The run log's only volume metric counts fetched records; INSERT OR IGNORE dedupe or filtering can persist zero without any trace in the log.
- **Why it matters:** The audit trail cannot answer 'did data actually land?' — the exact question a due-diligence reviewer asks; same mechanism hides the Kalshi/Polymarket zero-yield.
- **Failure mode:** Dedupe key bug makes every insert a no-op; logs show healthy fetch counts indefinitely while the store fossilizes.
- **Business impact:** Auditability claim weakened; silent data-loss class of bugs undetectable from logs.
- **Score impact:** E (~-0.4); overlaps issue 1's fix
- **Recommended fix:** Record rows_persisted (and rows_deduped) per run in source_run_log alongside fetched_count.

### SP-058 — OHLCV backfill fabricates bar timestamps (T16:00:00Z for every exchange) and coerces missing fields to 0.0

- **Category:** calibration-leakage  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-E  |  **Effort:** S  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `scripts/backfill_ohlcv_history.py:143 — ts = date_str + 'T16:00:00Z' unconditionally`
  - `scripts/backfill_ohlcv_history.py:73-77 — float(... or 0.0) turns missing/zero OHLC fields into 0.0 prices`
- **Observed:** All 122k historical bars carry a synthetic 16:00Z close time, wrong for .DE (17:30 CET), .T (15:00 JST), .SS sessions; a missing Close would be stored as 0.0 rather than rejected.
- **Why it matters:** Outcome maturation and calibration windows that compare event time vs bar time inherit systematic multi-hour error for non-US names; 0.0 closes would corrupt return calculations.
- **Failure mode:** 5-day horizon outcome for a Tokyo name evaluated against a bar timestamped 16:00Z picks the wrong session; return computed against a 0.0 close is -100%/inf.
- **Business impact:** Calibration corpus (already thin) polluted with timezone-skewed and potentially zero-price records.
- **Score impact:** E (~-0.3); touches calibration segment
- **Recommended fix:** Store the raw index timestamp with tz from yfinance, and drop (with a counted warning) any candle whose Close is None/NaN/0.

### SP-059 — Not a Python package: no __init__.py, 231 sys.path hacks, dual import fallbacks everywhere

- **Category:** install-fragility  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-F  |  **Effort:** M  |  **Next sprint:** Yes
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `ls: scripts/__init__.py and tests/conftest.py do not exist`
  - `grep: sys.path manipulation 131x in scripts/, 100x in tests/, 5x in src/`
  - `scripts/api_server.py:73-118 — every cross-module import wrapped in try ModuleNotFoundError with a bare-name fallback`
- **Observed:** Imports work only because the repo root happens to be cwd/on sys.path via per-file insertion; there is no pyproject.toml, so the codebase cannot be pip-installed or imported from anywhere else.
- **Why it matters:** Import behavior differs by invocation directory; the try/except dual-import pattern can bind DIFFERENT module objects (scripts.foo vs foo) in the same process, breaking module-level singletons and monkeypatched tests.
- **Failure mode:** A tool imports 'signal_inbox_api' while api_server imported 'scripts.signal_inbox_api'; module-level caches/state exist twice and a write recorded via one instance is invisible to the other.
- **Business impact:** Deployment beyond this one Windows machine (CI already needed the FastAPI-optional hack at api_server.py:36-43) requires re-plumbing; every new engineer trips over it on day one.
- **Score impact:** F -0.8
- **Recommended fix:** pyproject.toml with a package; delete all sys.path inserts and the dual-import fallbacks in one mechanical pass under the green test suite.

### SP-060 — Two live config directories with a colliding sources.yaml of unrelated content

- **Category:** architecture-leakage  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-F  |  **Effort:** S  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `config/ has 19 files incl. sources.yaml (polymarket/kalshi endpoints); configs/ has 7 files incl. sources.yaml ('Global Signal Fabric' loader config)`
  - `src/ingestion/kalshi_public_client.py:56 — DEFAULT_SOURCES_PATH = Path('config/sources.yaml')`
  - `scripts/global_security_master_discovery.py:50 — reads configs/global_securities_master.yaml; configs/no_execution_policy.yaml enforced by tests/test_no_execution_policy_config.py`
- **Observed:** Both directories are actively consumed by code; the same filename means two different schemas depending on which dir you look in.
- **Why it matters:** Config duplication is the classic source of 'edited the wrong file' incidents; the execution-lock policy lives in the less-referenced directory.
- **Failure mode:** An operator editing 'sources.yaml' changes the wrong file and the intended source config silently never takes effect; a future consolidation script merges the two and clobbers no_execution_policy.yaml semantics.
- **Business impact:** Operational misconfiguration risk on the very files that gate data sources and the no-execution policy.
- **Score impact:** F -0.4
- **Recommended fix:** Merge into one config/ dir with subfolders (sources/, policy/, universe/); leave a failing test if the old path is referenced.

### SP-061 — No static-analysis gate: zero lint/type-check config despite 71% annotation coverage; frontend lint already broken

- **Category:** test-leakage  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-F  |  **Effort:** S  |  **Next sprint:** Yes
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `ls: no pyproject.toml, ruff.toml, .ruff.toml, mypy.ini, setup.cfg — only pytest.ini exists`
  - `grep ratio: 3,364 annotated returns / 4,748 function defs in scripts/`
  - `session validation: 'npm run lint' broken (Next 16 removed next lint); CI workflows are pytest.yml/e2e.yml/dep_audit.yml/kante_defensive_gate.yml — no lint/typecheck job`
- **Observed:** Typing exists as convention only; nothing enforces it, and 423 except-Exception handlers (grep) plus the noqa'd import patterns suggest lint was never run repo-wide.
- **Why it matters:** In a 184k-LOC dynamic codebase, tests catch behavior but not type drift in the 29% unannotated surface; broad exception swallowing hides real faults as 'degraded' statuses.
- **Failure mode:** A refactor changes a return type from dict to dataclass; 423 catch-alls convert the resulting AttributeErrors into default/fallback values that flow into advisory scores without any test failing on the untested path.
- **Business impact:** Slow-burn correctness erosion; DD reviewers read no-lint-no-mypy as immaturity regardless of test count.
- **Score impact:** F -0.6
- **Recommended fix:** Add ruff (E/F/B rules) + mypy (start with CORE_MODULES list from core_module_boundary.py) to CI; fix frontend lint via ESLint CLI migration.

### SP-062 — Governance metrics flatter the architecture: 399/443 modules bucketed as catch-all SUPPORT, self-scored hygiene 9.97

- **Category:** evidence-leakage  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-F  |  **Effort:** S  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `scripts/core_module_boundary.py run output: n_core=26, n_support=399, n_experimental=16, n_unknown=2, CH=9.97`
  - `scripts/core_module_boundary.py:230-231 — anything in CORE's import closure is auto-promoted to SUPPORT ('never left UNKNOWN')`
  - `scripts/private_scope_guard.py:348 — ~145 modules grandfathered in PREEXISTING_BASELINE as out-of-scope-but-kept`
- **Observed:** The boundary tool reports near-perfect hygiene because SUPPORT is defined as 'reachable from CORE', which 90% of a flat monolith trivially is; the scope guard explicitly refuses to drive cleanup.
- **Why it matters:** Internal dashboards citing CH=9.97 as 'code hygiene' will mislead stakeholders about architectural health; the tooling measures classification coverage, not modularity.
- **Failure mode:** Investor or operator reads the hygiene score in a bundle/report as evidence of clean architecture; a code walk reveals the opposite, damaging trust in all other self-reported metrics.
- **Business impact:** Credibility risk to the entire self-audit apparatus this product leans on as a differentiator.
- **Score impact:** F -0.3; also touches evidence-trust segments
- **Recommended fix:** Rename metric to 'classification coverage'; add real modularity metrics (fan-in/fan-out per module, cycle count, top-level file count) with honest thresholds.

### SP-063 — Parallel persistence layers with different DBs and pragma postures

- **Category:** architecture-leakage  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-F  |  **Effort:** M  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `src/storage/sqlite_store.py:14 — SQLiteStore over data/processed/signal_refinery.sqlite`
  - `scripts/persistence.py:541-561 — schema+conn management for runtime/mvp_local.db with busy_timeout pragmas`
  - `scripts/nbi_store.py, scripts/chronology_store.py — additional store modules; WAL only in chronology_store.py:117`
- **Observed:** At least four independent storage modules manage separate SQLite files with inconsistent hardening (busy_timeout in some, WAL in one, neither in others).
- **Why it matters:** Each store re-solves schema init, migrations, and locking differently; cross-DB truth (holdings vs signals vs NBI cases) has no single transactional boundary.
- **Failure mode:** An outcome recorded in mvp_local.db references an NBI case updated in a different DB file mid-crash; there is no cross-store consistency check, so the evidence chain has a dangling reference.
- **Business impact:** Weakens the auditability story; multiplies the surface where the previously-observed write-race class of bug can recur.
- **Score impact:** F -0.3
- **Recommended fix:** One storage package exposing per-domain repositories over shared connection factory; document which DB is canonical for what (partially done for holdings).

### SP-064 — Legacy Streamlit dashboard reads SQLite directly with no quarantine/origin filtering — second UI contradicts truth gates

- **Category:** data-leakage  |  **Severity:** Medium  |  **Confidence:** Medium  |  **Source:** segment-G  |  **Effort:** S  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `src/storage/sqlite_store.py:108-141 — read_latest_signal_scores/read_paper_trades SELECT payload_json with no origin/quarantine WHERE clause`
  - `src/dashboard/streamlit_app.py:169-193 — renders those unfiltered tables as 'Signal Table'/'Paper Trades'; README.md:622 still documents the Streamlit app as a live surface`
  - `frontend/src/lib/apiClient.ts:548-556 — the Next.js path by contrast forces origin=manual_trade_log 'NEVER show seed / demo / fixture / probe rows'`
- **Observed:** Two parallel UIs exist with different truth guarantees: Next.js goes through FastAPI routes that enforce demo-row quarantine and origin filters; Streamlit bypasses the API and reads raw tables. Uncertainty: whether the 813 quarantined demo rows live in the specific tables Streamlit reads was not verified.
- **Why it matters:** The repo's hardest-won invariant is 'fake rows never reach canonical truth surfaces'; an officially documented dashboard that skips every one of those filters is a standing contradiction.
- **Failure mode:** An operator (or auditor) launches the README-documented Streamlit app and sees paper trades / signal scores that the canonical UI deliberately excludes, and reasonably concludes the truth gates are cosmetic.
- **Business impact:** Undermines the credibility of the entire truth-purity story during due diligence; two dashboards disagreeing about the same DB is a classic trust-killer.
- **Score impact:** G -0.3; also touches the data-integrity segment
- **Recommended fix:** Either retire streamlit_app.py to archived_experimental/ and delete the README reference, or route its reads through the same filtered accessors the API uses and label it LEGACY.

### SP-065 — Sidebar 'AI Executions: 0' is a hardcoded literal styled as live system status

- **Category:** evidence-leakage  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-G  |  **Effort:** XS  |  **Next sprint:** Yes
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `frontend/src/components/layout/Sidebar.tsx:144-156 — footer renders literal '0' and 'HUMAN_ONLY' as static JSX, no fetch`
  - `frontend/src/app/page.tsx:108 — home page correctly renders health.ai_execution_count fetched from /health, proving the live value is available`
- **Observed:** The persistent sidebar footer presents 'AI Executions 0 / Mode HUMAN_ONLY' as if it were telemetry, but it is a compile-time constant that would still read 0 if the backend counter ever became nonzero.
- **Why it matters:** This is the single always-visible safety indicator in the app; a hardcoded safety indicator is decoration, not monitoring, and a diligence reviewer who diffs it against the /health wiring on the home page will notice.
- **Failure mode:** If any invariant ever broke (ai_execution_count > 0 from /health), the most prominent UI element would continue asserting 0, actively masking the breach.
- **Business impact:** Converts the strongest trust signal in the UI into a liability the moment anyone checks how it is computed.
- **Score impact:** G -0.2
- **Recommended fix:** Fetch /health in the Sidebar (or lift it to a shared provider) and render ai_execution_count with a red alarm state when nonzero or unreachable.

### SP-066 — Frontend lint gate is broken — 'npm run lint' fails because Next 16 removed 'next lint'

- **Category:** install-fragility  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-G  |  **Effort:** S  |  **Next sprint:** Yes
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `Session-validated: 'npm run lint' is BROKEN (Next 16 removed next lint); vitest 201/201 and next build pass`
- **Observed:** The lint script still invokes the removed 'next lint' command, so no ESLint pass runs locally or in CI for the frontend.
- **Why it matters:** Type-check and vitest catch logic errors, but accessibility, unused-code, and react-hooks correctness rules are silently off across a 6,800-line page surface.
- **Failure mode:** A hooks-deps or dead-import regression lands unflagged; quality drifts on exactly the fast-changing pages (live-signals at 1,857 lines, chart-structure at 1,085 lines).
- **Business impact:** Slow quality erosion plus an embarrassing 'your lint doesn't even run' finding in any technical diligence.
- **Score impact:** G -0.15
- **Recommended fix:** Migrate to the ESLint CLI per Next 16 migration guide (eslint . with eslint-config-next) and wire it into the pytest.yml frontend job.

### SP-067 — NBI page has zero component tests and diverges from the app design system

- **Category:** test-leakage  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-G  |  **Effort:** S  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `frontend/src/app/__tests__/ — 16 spec files cover cockpit, live-signals, manual-trade-log, moltbook, reconciliation, chart-structure; no nbi spec exists`
  - `frontend/src/app/nbi/page.tsx:48-60 — uses ad-hoc inline CSSProperties objects instead of the Tailwind/slate token system every other page uses`
- **Observed:** The newest page (with the most complex payload shape: loosely-typed Record<string, unknown> artifacts) is the only major surface with no vitest coverage, and it visually diverges from the rest of the app.
- **Why it matters:** The NBI payload is explicitly 'loosely typed on purpose' (apiClient.ts:703-705), which is exactly where render-crash regressions come from as the artifact schema evolves with the subsystem.
- **Failure mode:** A schema change in nbi_evidence_factory export-cards (e.g. branches becomes an array) ships; the untested page renders wrong values or blanks silently, and no test catches it.
- **Business impact:** The flagship feature is the least protected against regression during its most active development phase.
- **Score impact:** G -0.15
- **Recommended fix:** Add nbi.spec.tsx covering artifact-present, artifact-missing, offline, fixture-tagged, and edge-claim-refused fixtures; restyle with the shared component set.

### SP-068 — No header/schema-drift validation: hard-coded A:Z offsets, row 1 skipped blindly

- **Category:** signal-leakage  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-H  |  **Effort:** XS  |  **Next sprint:** Yes
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `scripts/sync_google_sheet_reconciliation.py:108-124 — COL_TICKER=2 ... NUM_SHEET_COLUMNS=26 fixed offsets`
  - `scripts/sync_google_sheet_reconciliation.py:551-554 — 'if idx == 1: skipped' with no comparison of header cells to expected names`
- **Observed:** If the operator inserts, deletes, or reorders a column in the hand-maintained sheet, prices/action labels silently shift into the wrong fields; unknown action labels are skipped, but a shifted numeric column parses cleanly into the wrong price field.
- **Why it matters:** The sheet is explicitly operator-edited by hand; column drift is the most likely real-world failure, and the current code has zero detection for it.
- **Failure mode:** Operator inserts a 'BROKER' column after G; LIVE PRICE cells land in COL_STOP_LOSS, sl_price is recorded as the live price in every audit record, poisoning the bookkeeping trail without any error.
- **Business impact:** Corrupted price/stop bookkeeping that looks valid; costly to detect and repair after weeks of drift.
- **Score impact:** H down ~0.5 (schema-drift criterion)
- **Recommended fix:** Validate row 1 against the expected 26 header names on every run and abort with a named SCHEMA_DRIFT error on mismatch.

### SP-069 — LOG_PARTIAL_TP's only idempotency guard depends on a sheet writeback that can fail while the process exits 0

- **Category:** runtime-leakage  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-H  |  **Effort:** S  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `scripts/sync_google_sheet_reconciliation.py:610-619 — writeback exception is caught and only logged as a warning`
  - `scripts/sync_google_sheet_reconciliation.py:720-723 — _one_pass returns 0 iff counts['failed']==0; writeback failures are not counted as failed`
- **Observed:** POST succeeds, sheet write of V=YES fails (quota/permission/network); the run reports success (exit 0) and the next pass re-posts LOG_PARTIAL_TP, appending a duplicate partial-TP audit record.
- **Why it matters:** The one action the design bothered to make idempotent is idempotent only when a second, independently failing external write succeeds — and the failure is invisible to schedulers.
- **Failure mode:** Google API 429 during writeback; cron sees exit 0; three consecutive passes log three partial-TP events for one trade.
- **Business impact:** Duplicate booked-percent records distort the P/L bookkeeping trail; monitoring cannot detect it because exit codes lie.
- **Score impact:** H down ~0.4
- **Recommended fix:** Count writeback failures in the exit-code decision and retry writeback before re-posting on the next pass (or dedupe server-side per issue 2).

### SP-070 — bulk_log_manual_trades.py ignores the server's Idempotency-Key support and probes 6 guessed endpoints with a real trade record

- **Category:** data-leakage  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-H  |  **Effort:** XS  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `scripts/bulk_log_manual_trades.py:98 — requests.post(endpoint, json=payload, timeout=20) with no Idempotency-Key header`
  - `scripts/api_server.py:1363-1384 — server implements Idempotency-Key replay specifically to protect against double-logged trades`
  - `scripts/bulk_log_manual_trades.py:16-23,148-160 — --allow-all-endpoint-tries fires the first real entry at up to 6 candidate URLs until one accepts`
- **Observed:** Re-running the bulk loader after a partial failure re-submits already-accepted entries as new rows; the server annotates them as possible_duplicate (signal_inbox_api.py:2303-2313) but accepts them.
- **Why it matters:** Bulk backfill is exactly the retry-prone path idempotency keys exist for; the protection is built and unused.
- **Failure mode:** Network blip at entry 7 of 12; operator re-runs the script; entries 1-6 are duplicated in the manual trade log and must be individually soft-cancelled.
- **Business impact:** Manual-journal pollution and operator cleanup toil; duplicate rows skew reconciliation counts until cancelled.
- **Score impact:** H down ~0.4 (manual trade log reliability criterion)
- **Recommended fix:** Derive a deterministic Idempotency-Key per entry (hash of event_id+ticker+date) and send it; drop the endpoint-probing mode or restrict it to a --dry-run ping.

### SP-071 — Orphaned logon task PipelineV57LocalMVPSilent points at a deleted repo and fails every logon

- **Category:** install-fragility  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-I  |  **Effort:** XS  |  **Next sprint:** Yes
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `schtasks /query /tn PipelineV57LocalMVPSilent — Task To Run references C:\Users\akash\pipeline-v5.7-core\scripts\windows\start_mvp_stack_silent.ps1; Last Result -2147024629 (0x8007010B directory invalid); state Enabled`
  - `Test-Path C:\Users\akash\pipeline-v5.7-core → False`
- **Observed:** A still-enabled at-logon task from the repo's previous incarnation targets a directory that no longer exists and has been failing since at least 21-06-2026.
- **Why it matters:** Two consequences: the MVP stack does NOT auto-start at logon (the capability this task was for is silently dead), and the machine carries a permanently failing scheduled task that pollutes any future task-health audit.
- **Failure mode:** Operator assumes dashboard/API auto-start on reboot; after a restart the stack is down and nothing says why.
- **Business impact:** Startup reliability claim is false; demo-day reboot leaves the product dark.
- **Score impact:** Drags I (~-0.3)
- **Recommended fix:** schtasks /Delete /F /TN PipelineV57LocalMVPSilent, then re-register scripts/windows/register_mvp_silent_startup_task.ps1 with the current repo root if auto-start is still wanted.

### SP-072 — No lock files or single-instance protection on any scheduled runner

- **Category:** runtime-leakage  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-I  |  **Effort:** S  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `grep lock|single_instance|pid in scripts/refresh_live_signals.py — no matches`
  - `scripts/nbi_scheduler.py:187-316 — run_once has no concurrency guard; schtasks refresh task shows 'Repeat: Stop If Still Running: Disabled'`
- **Observed:** Neither the 6-hour refresh nor the NBI run-once takes a lock; a manual run overlapping a scheduled run (or a hung run overlapping the next repeat) writes to the same SQLite DB and log files concurrently.
- **Why it matters:** Prior memory records a diagnostics-cache write-race flake fixed with busy_timeout — the codebase has already been bitten by exactly this class of bug at the artifact layer.
- **Failure mode:** Operator manually runs refresh at 21:29 while the 21:30 task fires → interleaved log lines, double-ingested rows or SQLITE_BUSY partial cycles, health record overwritten by the loser.
- **Business impact:** Corrupted or duplicated signal_events rows undermine the canonical-truth story; intermittent, hard-to-reproduce failures.
- **Score impact:** Drags I (~-0.3)
- **Recommended fix:** Add a simple lockfile (msvcrt/portalocker or atomic O_EXCL pidfile in runtime/) around refresh_live_signals main and nbi_scheduler.run_once; exit with a disclosed ALREADY_RUNNING status.

### SP-073 — Scheduled jobs run on two different non-venv interpreters, neither the one the test suite validates

- **Category:** install-fragility  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-I  |  **Effort:** XS  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `scripts/windows/run_live_signal_refresh_once.ps1:82 — & python @pyArgs (bare PATH lookup)`
  - `schtasks NBI task action — C:\Python313\python.exe -m scripts.nbi_scheduler run-once (sys.executable captured at install time, scripts/nbi_scheduler.py:95-98); repo venv is .venv/Scripts/python.exe where 7567 tests passed`
- **Observed:** The refresh loop depends on whatever 'python' resolves to in the task's environment; the NBI task is pinned to system Python313. Import of the NBI chain under Python313 succeeds today (verified), but no scheduled job uses the tested venv.
- **Why it matters:** The 7567-test green suite certifies .venv, not the interpreters production actually runs on. Any pip install into the venv only, or a PATH change, splits test-truth from runtime-truth.
- **Failure mode:** A future NBI feature imports a venv-only package → tests pass, tomorrow's 08:30 run crashes at import before any log line is written (the _log call at nbi_scheduler.py:311 is unreachable on import failure) → fully silent given no alerting.
- **Business impact:** Classic works-on-my-shell drift; undermines install/runbook reproducibility that diligence checks.
- **Score impact:** Drags I (~-0.3)
- **Recommended fix:** Pin both task actions to <repo>\.venv\Scripts\python.exe; have nbi_scheduler doctor assert the installed task's action matches the venv interpreter.

### SP-074 — No frontend-to-real-backend integration test anywhere; e2e is 2 route-mocked specs run weekly

- **Category:** test-leakage  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-J  |  **Effort:** M  |  **Next sprint:** Yes
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `frontend/e2e/advisory-flow.spec.ts:16-59 — every backend route stubbed with hand-written JSON payloads via page.route`
  - `.github/workflows/e2e.yml:14-17 — Playwright runs only on workflow_dispatch + weekly cron (Tue 07:23 UTC)`
- **Observed:** Playwright starts a real production Next server but stubs 100% of API responses with hand-maintained fixtures; vitest specs likewise mock the API client. No test starts scripts/api_server.py and drives the UI against it.
- **Why it matters:** The stubs encode what the frontend authors believe the backend returns. If a FastAPI response shape changes (field rename, nesting change), backend tests and frontend tests both stay green while the real product breaks.
- **Failure mode:** Backend renames score_calibration.sample_size; test_api_server.py passes (it mocks backends), vitest passes (it mocks fetch), Playwright passes (stubbed payload), but the live cockpit renders blank calibration badges.
- **Business impact:** Demo-day breakage on the most visible surface (cockpit/signal-inbox) despite a fully green 7768-test wall — exactly the failure that makes investors distrust the test count.
- **Score impact:** J −0.6
- **Recommended fix:** Add one CI job that boots api_server via uvicorn against a seeded temp SQLite DB and runs 3-5 Playwright specs unstubbed; alternatively generate frontend stub fixtures from the backend's own response-contract tests so drift fails a test.

### SP-075 — Lint is dead on both stacks: npm run lint broken, no Python linter in CI

- **Category:** test-leakage  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-J  |  **Effort:** S  |  **Next sprint:** Yes
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `Session-validated: 'npm run lint' fails because Next 16 removed 'next lint' (tooling migration issue)`
  - `.github/workflows/pytest.yml:31-39 — install + compileall + pytest only; no ruff/flake8/mypy step in any of the 4 workflows`
- **Observed:** The only static gates are python -m compileall and tsc --noEmit. The declared frontend lint script cannot run at all, and 413+ Python scripts have no lint or type checking.
- **Why it matters:** compileall only catches syntax errors; unused imports, shadowed names, and type drift across 427 loose scripts accumulate unchecked, and a visibly broken npm script is a diligence red flag.
- **Failure mode:** A dead code path or mistyped kwarg in a rarely-tested script passes compileall, ships, and fails at runtime during the 08:30 scheduled NBI loop.
- **Business impact:** Quality erosion and an embarrassing broken developer command in an otherwise polished repo.
- **Score impact:** J −0.3
- **Recommended fix:** Migrate frontend to the ESLint CLI (eslint . via eslint.config.js, per Next 16 migration guide) and add ruff check to the pytest.yml backend job; both are report-only for one sprint then enforced.

### SP-076 — No suite-wide network guard — an unmocked test can silently hit live internet

- **Category:** test-leakage  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-J  |  **Effort:** XS  |  **Next sprint:** Yes
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `conftest.py:1-107 — DB and summary-path isolation only; no socket blocking, and pytest-socket absent from requirements-dev.txt (grep no matches)`
  - `grep requests.get|urlopen across tests/ — 26 files touch HTTP client surfaces, each relying on per-test patch('requests.get') discipline`
- **Observed:** Mocking is done per-test via unittest.mock.patch; nothing enforces that a forgotten patch fails fast instead of making a real HTTP call from CI or the operator's machine.
- **Why it matters:** One missed patch turns a unit test into a live call to SEC/GDELT/Polymarket — nondeterministic, rate-limited, and a policy violation for a suite documented as 'no live network refresh' (pytest.yml:8).
- **Failure mode:** A new provider test forgets the patch; CI passes while quietly hammering a real API, then flakes when the endpoint rate-limits, producing intermittent red builds nobody can reproduce locally.
- **Business impact:** Flaky CI degrades trust in the gate and risks provider bans on shared CI egress IPs.
- **Score impact:** J −0.3
- **Recommended fix:** Add pytest-socket with --disable-socket --allow-unix-socket (or an autouse fixture stubbing socket.create_connection) so any unmocked network attempt raises immediately.

### SP-077 — Real gspread I/O boundary excluded from coverage — partial sheet writeback untested

- **Category:** test-leakage  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-J  |  **Effort:** S  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `scripts/sync_google_sheet_reconciliation.py:409-414 — _read_rows and _apply_updates carry 'pragma: no cover — I/O'`
  - `tests/test_sync_google_sheet_reconciliation.py:332-350 — POST-failure path is tested, but no test simulates _apply_updates raising mid-batch (Sheets API quota/auth failure after some cells updated)`
- **Observed:** The pure decide_row/_process_rows logic is well tested including POST failure, but the actual Sheets write call and its partial-failure semantics (some Z-column cells updated, some not) have zero tests.
- **Why it matters:** This is the exact 'partial sheet write' risk flow: a half-applied writeback desynchronizes the sheet's recon_status column from the MVP's reconciliation state, which the operator treats as truth.
- **Failure mode:** Sheets API 429s after updating 3 of 8 writeback cells; on the next sync, rows whose Z-cell was updated are skipped while the MVP never received their POSTs (or vice versa), producing silent recon drift.
- **Business impact:** Reconciliation is a headline product claim; sheet/DB drift means the operator acts on stale trade state.
- **Score impact:** J −0.3; also touches C/D (data integrity)
- **Recommended fix:** Wrap _apply_updates with per-cell result tracking and a test using a fake worksheet whose update raises after N cells; assert the sync reports PARTIAL_WRITEBACK and retries idempotently.

### SP-078 — Gitleaks allowlist/config stranded on unmerged branches; HEAD runs raw full-history scan with unverifiable CI status

- **Category:** security-privacy  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-K  |  **Effort:** XS  |  **Next sprint:** Yes
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `git ls-files | grep gitleaks — rc=1: no .gitleaks.toml/.gitleaksignore tracked on live-data-config-sprint or main`
  - `git log --all --name-status -- '*gitleaks*' — configs added only at b40b54e (feature/p2-interpretation-defense-expansion) and 418ead6/f972472 (origin/claude/nifty-ramanujan-urihdx), neither merged to main`
  - `.github/workflows/dep_audit.yml:59-65 — secrets job scans full history (fetch-depth: 0) on every push with no repo config`
  - `gh run list — exit 127: gh CLI absent, CI outcome cannot be verified locally`
- **Observed:** The careful fingerprint-only allowlist (19 synthetic fixture findings) and its guard test live only on two unmerged branches; the branch that CI actually runs on has no gitleaks config, and there is no local way to confirm the secrets job passes.
- **Why it matters:** If the raw scan is red on main, the team either ignores a failing security gate (normalizing red) or the gate is silently not protecting anything; either way the flagship 'full-history secret scan' claim is unverified.
- **Failure mode:** A real secret lands in a commit; the secrets job has been red-and-ignored for weeks due to fixture false positives, so nobody notices the new genuine finding among the noise.
- **Business impact:** Erodes the single strongest security control in the repo; an investor diligence team asking 'show me the green secret-scan run' gets no answer.
- **Score impact:** K -0.4; also touches evidence-leakage credibility
- **Recommended fix:** Cherry-pick/merge b40b54e's .gitleaks.toml, .gitleaksignore, and tests/test_gitleaks_allowlist_config.py into main; install gh; attach a green dep_audit secrets run URL to the evidence pack.

### SP-079 — Python dependencies are range-pinned, not locked — the 'locked deps' hardening never merged

- **Category:** security-privacy  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-K  |  **Effort:** S  |  **Next sprint:** Yes
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `requirements.txt:1-11 — all entries use >=/< ranges (e.g. numpy>=2,<3, requests>=2.32,<3); grep -c '==' returns 0`
  - `git log --all --grep gitleaks — commit 7303587 'Release-grade ceiling-break: locked deps...' exists only on origin/claude/nifty-ramanujan-urihdx, not in HEAD ancestry`
  - `.github/workflows/dep_audit.yml:33-34 — pip-audit -r requirements.txt audits whatever the ranges resolve to at scan time, not what the operator actually runs`
- **Observed:** Backend builds are non-reproducible; pip-audit in CI audits a freshly-resolved dependency set that can differ from the operator's local .venv, so a vulnerable locally-installed version can pass CI.
- **Why it matters:** Supply-chain integrity: a compromised or vulnerable transitive release inside the allowed range installs silently on the next environment rebuild.
- **Failure mode:** A malicious yfinance/gspread point release within range is installed locally; CI stays green because the runner resolved a different version.
- **Business impact:** One poisoned dependency on the machine holding 83 API keys and the Google service account is a full credential-compromise event.
- **Score impact:** K -0.3
- **Recommended fix:** Generate a hash-pinned lock (pip-compile --generate-hashes) as requirements.lock.txt, install from it, and point pip-audit at the lock; merge or reimplement the stranded 7303587 work.

### SP-080 — Real personal broker holdings and trade history are git-tracked and pushed to GitHub

- **Category:** security-privacy  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-K  |  **Effort:** S  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `git ls-files data/daily_payload/ — verified_current_holdings.json, closed_positions.json, sold_positions.json all tracked`
  - `data/daily_payload/verified_current_holdings.json:1-10 — canonical truth for the operator's real OPEN positions ('GLD is intentionally absent because it was sold')`
  - `WebFetch github.com/akashguha9/sleeping-passenger-v1 — 404 unauthenticated: private today, but privacy rests entirely on one repo-visibility toggle`
- **Observed:** The operator's actual portfolio positions, sales, and dates are versioned in git history on a remote host; every clone, collaborator grant, or accidental visibility change exposes them permanently (history rewrite would be required to retract).
- **Why it matters:** Personal financial data has different custody requirements than code; it is currently protected only by repo privacy, not by design.
- **Failure mode:** Repo is made public for a demo/portfolio purpose (LinkedIn content already lives in the repo, suggesting publicity intent) and years of personal trading history leak irretrievably via git history.
- **Business impact:** Personal privacy/OPSEC breach for the operator; for an investor, signals immature data-classification discipline.
- **Score impact:** K -0.3
- **Recommended fix:** Move holdings truth files to a gitignored data/private/ path (pattern already exists for runtime/), keep a schema-only tracked example; document the classification in SECRET_CUSTODY.md.

### SP-081 — No docs index or glossary over 127 docs; internal codenames unexplained to outsiders

- **Category:** documentation-gap  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-L  |  **Effort:** S  |  **Next sprint:** Yes
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `ls docs | wc -l → 127 files; docs/README.md and docs/INDEX.md do not exist; no GLOSSARY.md anywhere`
  - `docs/FINAL_SCORECARD.md:20 — 'Post-Kanté Day 1-10' used as a timeline epoch with no definition; grep shows Kanté in 7 docs, defined in none`
  - `README.md:223 — prompts/ (25 .txt files) dismissed as 'supporting reference material and historical artifacts' with no per-file explanation`
- **Observed:** Navigation of the doc corpus requires tribal knowledge; chicken gate, Kanté, Moltbook (partially explained), Mythos, Fable, and NBI are load-bearing terms in runbooks and scorecards.
- **Why it matters:** An outsider cannot audit what they cannot decode; the codename density makes the corpus look like a personal lab notebook rather than a product.
- **Failure mode:** Investor's analyst spends an hour reverse-engineering what 'Post-Kanté' means and gives up on the docs tree.
- **Business impact:** Effective documentation value is a fraction of its volume; diligence cost inflates.
- **Score impact:** L -0.6
- **Recommended fix:** Ship docs/GLOSSARY.md (10-15 terms, one paragraph each) and docs/README.md index grouping the 127 files into ~8 categories with one-line purposes.

### SP-082 — SETUP.md contradicts README on minimum Python version (3.11+ vs >=3.12 hard requirement)

- **Category:** documentation-gap  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-L  |  **Effort:** XS  |  **Next sprint:** Yes
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `SETUP.md:26 — 'Python 3.11+ (CI uses 3.13)'`
  - `README.md:31-33 — 'requires Python >= 3.12 ... SyntaxError on 3.11 and earlier'`
- **Observed:** The canonical setup doc tells a new user 3.11 works; the README says 3.11 is a guaranteed SyntaxError.
- **Why it matters:** This is the one doc a fresh evaluator follows literally; a version contradiction breaks first-run trust on the very first page.
- **Failure mode:** Evaluator on Python 3.11 hits SyntaxErrors mid-install after following SETUP.md exactly, and files the whole project as broken.
- **Business impact:** Failed first-run demo for any external reviewer with a 3.11 default toolchain.
- **Score impact:** L -0.3 (also touches install-fragility)
- **Recommended fix:** One-line change: SETUP.md prerequisite to 'Python 3.12+ (CI uses 3.13)'.

### SP-083 — SETUP.md says 'There is no auth' while README/SECURITY.md describe fail-closed token auth

- **Category:** documentation-gap  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-L  |  **Effort:** XS  |  **Next sprint:** Yes
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `SETUP.md:15 — 'Not multi-tenant. There is no auth, no user accounts.'`
  - `README.md:15-18 — 'backend refuses to start without an owner MVP_API_TOKEN ... every journal read and write requires Authorization: Bearer'`
  - `SECURITY.md:35-39 — 'Fail-closed auth: the API refuses to start without MVP_API_TOKEN'`
- **Observed:** The setup doc's security posture statement is the opposite of the implemented (and tested) fail-closed owner-token model.
- **Why it matters:** Security posture is a headline claim; a contradiction here looks like either the doc or the control is fake.
- **Failure mode:** Security-minded reviewer reads SETUP.md first, concludes the API is wide open, then finds the token gate and wonders what else the docs get backwards.
- **Business impact:** Cheapens the otherwise strong SECURITY.md/OWNER_ACCESS.md story.
- **Score impact:** L -0.3
- **Recommended fix:** Reword SETUP.md:15 to 'No multi-user accounts; single-owner bearer-token auth is mandatory (fail-closed)'.

### SP-084 — Stale quantitative claims scattered across scorecards and checklists (2950/3017/~6700 tests)

- **Category:** documentation-gap  |  **Severity:** Medium  |  **Confidence:** High  |  **Source:** segment-L  |  **Effort:** S  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `docs/FINAL_ACCEPTANCE_CHECKLIST.md:70 — 'target: ~3017 tests' vs 7567 actual`
  - `docs/PRODUCT_DIRECTION_DECISION.md:41,65 — '2950 backend tests' as a decision input`
  - `MODEL_CARD.md:54 — '~6,700 total backend tests' (closest to truth but still stale)`
- **Observed:** At least five docs quote hard test counts from different eras (2950, 3017, 3464, ~6700), none matching the validated 7567.
- **Why it matters:** Every stale number is a contradiction a diligence pass can machine-detect; hard counts in prose rot within weeks in a repo moving this fast.
- **Failure mode:** Reviewer diffs the claimed counts against pytest output and flags the docs as systematically unmaintained.
- **Business impact:** Death by a thousand small contradictions; each one taxes the credibility of true claims.
- **Score impact:** L -0.4
- **Recommended fix:** Replace hard counts with dated order-of-magnitude language ('7,500+ as of 2026-07-03') or generate counts into one dated STATUS doc that others link to.

### SP-085 — 937-line README plus ~20 companion docs with the real daily truth in a 'PRIVATE' sprint-numbered checklist

- **Category:** documentation-gap  |  **Severity:** Low  |  **Confidence:** High  |  **Source:** segment-A  |  **Effort:** XS  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `README.md — 937 lines / 55,023 bytes (measured)`
  - `README.md:99-119 — doc map linking ~20 further documents plus 4 runbooks in docs/`
  - `docs/PRIVATE_OPERATOR_DAILY_CHECKLIST.md:1 — titled 'Private Operator Daily Checklist (Sprint 10D)', referencing internal sprint numbering`
- **Observed:** Onboarding requires traversing a 55KB README, SETUP, DEMO, SHOWCASE, and 20+ docs; the actual day-to-day operating procedure lives in a doc labeled private with sprint-era references (10D/10F) that may not match current tooling.
- **Why it matters:** For Segment A the test is whether a non-author can operate the system; the documentation volume is high but the single entry point for 'what do I do each morning' is buried and dated.
- **Failure mode:** A new operator reads README+DEMO, never finds the daily checklist, and operates without the readiness formula or review-only discipline the system depends on.
- **Business impact:** Slows any handoff, audit, or demo; increases bus-factor risk on a single-author product.
- **Score impact:** A -0.2
- **Recommended fix:** Add a one-page OPERATOR_DAILY.md (or /help route section) linked first in the README: morning brief command, the three defensive states, and links to the full checklist; strip sprint numbering from operator-facing docs.

### SP-086 — IAP price-move lateness score is direction-agnostic: a 50% adverse move scores as fully 'captured by others'

- **Category:** signal-leakage  |  **Severity:** Low  |  **Confidence:** Medium  |  **Source:** segment-B  |  **Effort:** XS  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `scripts/chicken_gate.py:465-467 — _price_move_iap_score returns clamp(abs(pct)/5, 0, 10); docstring: 'Move already captured by earlier participants'`
- **Observed:** abs() means a price that moved 50% AGAINST the thesis since first signal produces IAP 10 (hard-block territory), identical to a 50% move in the thesis direction.
- **Why it matters:** Lateness semantics only make sense for moves in the thesis direction; an adverse move is earliness/invalidation, a different risk that deserves a different flag.
- **Failure mode:** A contrarian thesis on a name down 50% since first signal is demoted for 'information access premium' rather than assessed on freshness/invalidation grounds — wrong reason code, misleading audit trail.
- **Business impact:** Demote-only, so it fails safe (over-blocks, never inflates) — but the explanation attached to the block is wrong, which undermines the explainability claim.
- **Score impact:** B −0.2
- **Recommended fix:** Pass thesis direction into evaluate_information_access; route adverse moves to a THESIS_INVALIDATION_CHECK note instead of the IAP lateness score.

### SP-087 — Trade journaling does not require a stop/invalidation at log time

- **Category:** ux-leakage  |  **Severity:** Low  |  **Confidence:** High  |  **Source:** segment-C  |  **Effort:** XS  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `scripts/api_server.py:918-922 — invalidation_level, exit_plan, risk_reason all optional with empty-string defaults`
  - `scripts/api_server.py:1003-1009 — stop_loss_price/take_profit fields only appear at RECONCILE time as optional record-keeping`
- **Observed:** A real-money manual trade can be logged with no stop, no invalidation, and no exit plan; stop data first becomes recordable after the trade closes, in the reconciliation body.
- **Why it matters:** The one enforcement point the advisory system legitimately owns — refusing to journal an undisciplined trade — is not used; discipline fields are decorative.
- **Failure mode:** Operator logs entries with empty risk fields indefinitely; journal-quality scoring degrades gracefully instead of gating, so the discipline dataset needed for calibration never accumulates.
- **Business impact:** Weakens the operator-discipline narrative and the future calibration corpus.
- **Score impact:** C down ~0.2
- **Recommended fix:** Make invalidation_level (or explicit 'no_stop_reason' text) required for trade_mode=REAL_MANUAL logs; keep PAPER lenient.

### SP-088 — no_execution_policy.yaml self-describes narrower enforcement than actually exists

- **Category:** documentation-gap  |  **Severity:** Low  |  **Confidence:** High  |  **Source:** segment-C  |  **Effort:** XS  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `configs/no_execution_policy.yaml:58 — audit_scope: scripts/ingestion/ only`
  - `tests/test_no_execution_guard_repowide.py:1-7 — the actual repo-wide guard exists in a separate test the policy file never references`
- **Observed:** The machine-readable policy names only the ingestion-scoped test as its enforcement, while the real structural guarantee (repo-wide AST + dependency guard) lives elsewhere and is invisible to anyone auditing the policy file alone.
- **Why it matters:** The prohibition IS structural — the strongest asset in this segment — but the canonical policy artifact undersells it, which reads as incoherence in diligence.
- **Failure mode:** Auditor reads the policy, concludes only ingestion is guarded, and flags a false gap; or a future refactor deletes the repo-wide test without tripping any policy reference.
- **Business impact:** Minor trust friction; cheap to fix, disproportionate diligence value.
- **Score impact:** C down ~0.1
- **Recommended fix:** Update enforcement.tested_by to list both tests and widen audit_scope wording to scripts/ + src/ + dependency manifests.

### SP-089 — Infrastructure-existence score report is conflatable with evidence quality

- **Category:** evidence-leakage  |  **Severity:** Low  |  **Confidence:** Medium  |  **Source:** segment-D  |  **Effort:** XS  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `scripts/signal_ceiling_score_report.py:143-145 — kalshi_live_ledger check passes on len(live_obs)>0; other checks pass on file existence (e.g. exists('runtime/env_requirements_report.json'))`
- **Observed:** The ceiling/score reports (the ~8.59-style numbers) award points for scripts, tests, and non-empty files, not for closed outcomes; the calibration reports themselves stay honest, but the headline number an operator sees is an infrastructure score.
- **Why it matters:** A stakeholder reading 'score 8.59' next to 'N=0 outcomes' will anchor on the flattering number; this is the closest thing in the repo to papering over INSUFFICIENT_EVIDENCE.
- **Failure mode:** Investor deck quotes the composite score as system quality; diligence later reveals the outcome denominator is zero, reading as misrepresentation.
- **Business impact:** Trust damage disproportionate to the underlying (honest) design.
- **Score impact:** D -0.2; mostly a presentation risk
- **Recommended fix:** Print the live-outcome ladder status (currently NO_LIVE_EVIDENCE / 0.0) adjacent to every composite score artifact and cockpit card.

### SP-090 — yfinance price canary dead since 2026-05-31 (CANARY_SKIPPED: network disabled)

- **Category:** runtime-leakage  |  **Severity:** Low  |  **Confidence:** High  |  **Source:** segment-E  |  **Effort:** XS  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `source_run_log — yfinance last row status='CANARY_SKIPPED', reason 'no fixtures and network disabled', 2026-05-31T16:16:09`
- **Observed:** The dedicated provider canary that proved real price coverage has not executed in 33 days; the only live yfinance validation is the 4-ETF loader.
- **Why it matters:** The canary was the mechanism for proving provider reachability independently of the ingest path; it is silently retired.
- **Failure mode:** yfinance API change breaks history() for suffixed tickers; nothing detects it until a backfill is manually run.
- **Business impact:** Longer detection time for provider breakage.
- **Score impact:** E (~-0.2)
- **Recommended fix:** Re-enable the canary in the scheduled refresh with network allowed, one US + one .DE + one .T symbol.

### SP-091 — 240 script-level CLIs as the operational API; no unified entrypoint or command registry

- **Category:** ux-leakage  |  **Severity:** Low  |  **Confidence:** High  |  **Source:** segment-F  |  **Effort:** M  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `grep -c 'if __name__' scripts/*.py — 240 files define a __main__ CLI`
  - `scripts/api_server.py:26-29 — even the API server is started as 'python scripts/api_server.py'`
- **Observed:** Operator workflows are 240 ad-hoc entrypoints with per-file argparse conventions; discoverability relies on docs/OPERATOR_QUICKSTART.md and memory files.
- **Why it matters:** No single 'sp <command>' surface means no consistent --help, no shared flags (e.g., --db, --dry-run semantics vary), and the operator_permission_guard convention for --apply scripts is enforced by convention/tests rather than a shared CLI framework.
- **Failure mode:** Operator runs the wrong of two similarly-named scripts (e.g., db_integrity_audit.py vs db_integrity_check.py, both exist) and believes a check passed that never ran.
- **Business impact:** Operator error rate and training cost; the product's 'operator workflow' claim is a pile of scripts, not a workflow.
- **Score impact:** F -0.2
- **Recommended fix:** Single console-script entrypoint (click/typer) registering the ~20 operator-facing commands; demote the rest to internal.

### SP-092 — Dependencies range-pinned with no lockfile

- **Category:** install-fragility  |  **Severity:** Low  |  **Confidence:** High  |  **Source:** segment-F  |  **Effort:** XS  |  **Next sprint:** Yes
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `requirements.txt:1-11 — numpy>=2,<3 style ranges; no requirements.lock/pip-tools/uv lock artifact in repo root`
- **Observed:** requirements.txt and requirements-dev.txt use compatible-range pins only; a fresh install resolves different versions than the validated .venv (Python 3.13.4).
- **Why it matters:** The 7,567-test green result is not reproducible on a fresh machine by construction; pandas/streamlit minor bumps have broken APIs historically.
- **Failure mode:** New machine installs pandas 2.4.x with a behavior change in a scoring path; suite fails or, worse, numeric outputs shift silently within test tolerances.
- **Business impact:** Undermines the reproducibility claims of an evidence/calibration product.
- **Score impact:** F -0.2
- **Recommended fix:** Add a lock (pip-compile or uv lock) and a CI job installing from the lock.

### SP-093 — Playwright e2e runs only weekly/on-dispatch — no-execution-language guard is not a per-push gate at browser level

- **Category:** test-leakage  |  **Severity:** Low  |  **Confidence:** High  |  **Source:** segment-G  |  **Effort:** S  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `.github/workflows/e2e.yml:14-17 — triggers are workflow_dispatch + cron '23 7 * * 2' only`
  - `frontend/e2e/advisory-flow.spec.ts:14 — FORBIDDEN regex banning execution CTAs is enforced only in this weekly suite (vitest has a separate no-execution-language.spec.tsx mitigating this)`
- **Observed:** Browser-level advisory-framing checks run at most weekly; a push introducing an execution-flavored CTA would be caught by vitest's jsdom check but not exercised in a real browser until the next Tuesday run.
- **Why it matters:** Advisory-only framing is a compliance-adjacent invariant; a week of exposure window is long for the product's core promise, though the vitest guard substantially mitigates it.
- **Failure mode:** A regression that only manifests in the built production bundle (e.g. route-level layout change dropping NoExecutionBanner) survives up to 7 days undetected.
- **Business impact:** Small but real window where the deployed UI could contradict the no-execution doctrine.
- **Score impact:** G -0.1
- **Recommended fix:** Add a fast per-push smoke job running only advisory-flow.spec.ts against the cached Chromium build, keeping the full matrix weekly.

### SP-094 — Single-shot data loads on cockpit/NBI/home — no refresh affordance or polling for a day-long operator session

- **Category:** ux-leakage  |  **Severity:** Low  |  **Confidence:** High  |  **Source:** segment-G  |  **Effort:** S  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `frontend/src/app/cockpit/page.tsx:143-150 — useEffect fetches once on mount, no interval or refresh button`
  - `frontend/src/app/nbi/page.tsx:121-136 — same pattern; only live-signals has auto-refresh (live-signals.autorefresh.spec.tsx exists)`
- **Observed:** Most operational pages fetch on mount only; an operator who leaves the cockpit tab open sees data frozen at page-load time with no indication or refresh control.
- **Why it matters:** Combined with the missing staleness rendering, an open tab quietly becomes a snapshot of the past while presenting itself as current.
- **Failure mode:** Operator keeps /cockpit open through the 08:30 scheduled run; the run fails, but the tab still shows the pre-run state and the operator sees nothing new to act on.
- **Business impact:** Marginal day-to-day, but compounds the staleness trust problem on the ops surfaces.
- **Score impact:** G -0.1
- **Recommended fix:** Add a shared 'Refreshed HH:MM · [Refresh]' header control to cockpit/nbi/home, reusing the live-signals auto-refresh hook.

### SP-095 — Home 'Top Signals' shows 2-decimal priority scores without the calibration badge shown on the inbox

- **Category:** calibration-leakage  |  **Severity:** Low  |  **Confidence:** High  |  **Source:** segment-G  |  **Effort:** XS  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `frontend/src/app/page.tsx:173-176 — priority_score.toFixed(2) with a green/yellow/red ScoreBar, no ScoreCalibrationBadge on this page`
  - `frontend/src/app/signal-inbox/page.tsx:161 — the inbox does render ScoreCalibrationBadge next to the same scores`
- **Observed:** The dashboard's first impression presents precise, color-coded scores with no uncertainty context; the honesty layer exists but only one click deeper.
- **Why it matters:** The repo's own doctrine (ScoreCalibrationBadge.tsx:15-17) is that 'a precise-looking number is never shown as if it were validated' — the landing page violates it for the highest-visibility numbers in the app.
- **Failure mode:** A new operator anchors on 0.87 vs 0.42 priority from the dashboard alone and forms sizing intuitions from uncalibrated scores before ever seeing the UNCALIBRATED warning.
- **Business impact:** Minor false-precision exposure on the most-viewed page; trivially inconsistent with the product's stated honesty standard.
- **Score impact:** G -0.1
- **Recommended fix:** Render the compact ScoreCalibrationBadge (already fetched with the same /signals payload) above the Top Signals list on the home page.

### SP-096 — Audit-record identity is ticker + sheet_row_number, which is unstable under sheet edits

- **Category:** data-leakage  |  **Severity:** Low  |  **Confidence:** High  |  **Source:** segment-H  |  **Effort:** S  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `scripts/sync_google_sheet_reconciliation.py:239-254 — payload carries only ticker and sheet_row_number as identity; no stable trade/row ID`
  - `scripts/api_server.py:2989-2999 — audit record persists the same unstable identity`
- **Observed:** If the operator sorts the sheet or inserts a row, sheet_row_number remaps to a different trade; two open rows on the same ticker are indistinguishable in the audit trail.
- **Why it matters:** Any future attempt to join the audit log back to specific trades (the obvious next step for real reconciliation) will mis-join on re-sorted sheets.
- **Failure mode:** Operator sorts by DATE after a STOP_HIT sync; a later CLOSE_TRADE for row 14 now refers to a different trade than the earlier STOP_HIT logged for row 14.
- **Business impact:** Audit trail becomes un-joinable history; limits how much the log can ever be trusted for outcome attribution.
- **Score impact:** H down ~0.2
- **Recommended fix:** Add a stable trade key column (e.g. SL. No. or a UUID column) to the payload and audit record.

### SP-097 — gsheet_export.py is offline CSV only — the 'Google Sheets sync' claim is one-way inbound; nothing pushes local state to the sheet beyond status stamps

- **Category:** documentation-gap  |  **Severity:** Low  |  **Confidence:** High  |  **Source:** segment-H  |  **Effort:** XS  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `scripts/gsheet_export.py:15 — 'No Google API credentials. No .env edits. No network calls.'`
  - `README.md — grep -i 'google sheet' returns zero matches`
- **Observed:** The export layer produces sheet-compatible CSVs the operator must upload by hand; local signals/holdings never flow to the sheet automatically, and the feature is undocumented in the README.
- **Why it matters:** Investors reading 'portfolio/Google Sheets sync' will assume bidirectional sync; the reality is manual CSV plus an inbound audit logger, and the gap is not disclosed anywhere.
- **Failure mode:** Demo day: asked to show local signals appearing in the sheet, the system has no such path; credibility hit on a claimed feature.
- **Business impact:** Expectation mismatch on a headline feature; trust cost is larger than the engineering gap.
- **Score impact:** H down ~0.3
- **Recommended fix:** Document the actual sync topology (inbound reconciliation + manual CSV export) in README/OPERATOR_QUICKSTART, or ship a gspread-based export push.

### SP-098 — SchedulerHealth 10/10 is a product of binary flags — reads as excellence, means 'did not crash'

- **Category:** calibration-leakage  |  **Severity:** Low  |  **Confidence:** High  |  **Source:** segment-I  |  **Effort:** XS  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `scripts/nbi_scheduler.py:265-273 — scheduler_health = product of five 0/1 components, health10 = 10 * that (only values possible: 0 or 10)`
  - `runtime/nbi_scheduler_last_run.json:7-27 — SchedulerHealth10: 10 alongside a single WATCH_ONLY event, claims_verified 0, edge_claim false, case_count 0`
- **Observed:** The health metric can only be 0 or 10; a run that ingests one unverified watch-only event scores identically to a rich productive cycle, and the 10/10 figure is quoted in session summaries as an achievement.
- **Why it matters:** For a project whose brand is calibration honesty, a metric that structurally cannot express partial quality invites over-claiming ('HEALTHY 10/10') that an auditor will discount.
- **Failure mode:** Stakeholder reads '10/10 HEALTHY' as loop quality; actual content throughput that day was near zero.
- **Business impact:** Optics/trust erosion when the binary nature is discovered during diligence.
- **Score impact:** Minor drag on I (~-0.1) and calibration-honesty optics
- **Recommended fix:** Rename to scheduler_pipeline_ok (boolean) or make it a genuine graded score including event/claim throughput; keep fail-closed semantics.

### SP-099 — Production logs/ directory polluted with pytest caches and test databases

- **Category:** test-leakage  |  **Severity:** Low  |  **Confidence:** High  |  **Source:** segment-I  |  **Effort:** XS  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `Glob logs/** — logs/.pytest_cache/*, logs/.pytest_tmp/** with ~40 test observation.db/-wal/-shm files interleaved with production JSONL logs (logs/audit_log.jsonl, logs/live_signal_refresh.log)`
- **Observed:** Test-run artifacts (pytest cache, per-test SQLite DBs with WAL/SHM files) live inside the same logs/ directory the runtime writes operational logs to.
- **Why it matters:** Blurs the production/test boundary in the exact directory an operator inspects during an incident; risks a freshness/health check accidentally matching a test artifact.
- **Failure mode:** A future 'latest .db in logs/' or glob-based freshness probe picks up logs/.pytest_tmp/*/observation.db and reports fake freshness.
- **Business impact:** Hygiene signal to diligence; small chance of misleading a future observability probe.
- **Score impact:** Minor drag on I (~-0.1)
- **Recommended fix:** Point pytest tmp/cache at tmp/ or the OS temp dir in pytest.ini; add logs/.pytest_* to cleanup.

### SP-100 — Fault-injection tests trust the probe's own self-assessment

- **Category:** test-leakage  |  **Severity:** Low  |  **Confidence:** High  |  **Source:** segment-J  |  **Effort:** XS  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `tests/test_fault_injection_resilience.py:21-24 — asserts report['results'][*]['handled_safely'] and resilience == 1.0, both computed by scripts/fault_injection_probe.py itself`
- **Observed:** The tests assert fields the probe module computes about itself (handled_safely, any_unsafe_output). The judge and the defendant are the same module; only the fault-set completeness and per-fault expected states are independently asserted.
- **Why it matters:** If the probe's safety classifier weakens (e.g. a marker regex loosened), the tests keep passing while the actual resilience guarantee degrades — mild self-grading circularity in a merge-gate test.
- **Failure mode:** A refactor makes unsafe_markers detection miss a new execution token; probe still reports handled_safely=True for a fault that now emits it, and the defensive gate stays green.
- **Business impact:** Marginal today, but this file is part of the merge-blocking kante gate, so its assurance value is overstated.
- **Score impact:** J −0.1
- **Recommended fix:** Add tests that feed the probe's classifier known-unsafe fixture outputs and assert it flags them (test the judge), independent of the end-to-end probe run.

### SP-101 — Frontend vitest coverage skips several shipped routes (nbi, settings, exports, securities, reflection-desk)

- **Category:** test-leakage  |  **Severity:** Low  |  **Confidence:** Medium  |  **Source:** segment-J  |  **Effort:** S  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `Glob frontend/src/**/__tests__/* — 35 spec files cover cockpit, live-signals, manual-trade-log, moltbook, reconciliation, chart-structure; no specs match nbi, settings, exports, securities, or reflection-desk pages`
  - `Session-validated build: 16 routes shipped`
- **Observed:** Roughly a third of the shipped Next.js routes have no dedicated vitest spec; only the no-execution-language spec and build/typecheck cover them at all.
- **Why it matters:** The NBI page is the newest, most actively developed surface (nbi-v1.6 shipped this week) and has the least render-level test protection precisely where churn is highest.
- **Failure mode:** A refactor of the NBI payload shape breaks the /nbi page render; tsc and build pass (types loosened via any/optional), vitest passes, and the operator finds a blank cockpit panel the next morning.
- **Business impact:** Operator-facing breakage on the daily-loop page; low direct capital risk since advisory-only.
- **Score impact:** J −0.2
- **Recommended fix:** Add render + loading/error-state specs for the 5 uncovered routes mirroring the existing manualTradeLog.loadingState pattern.

### SP-102 — 83 provider keys sit in plaintext .env by default; DPAPI custody mode is opt-in and unverified

- **Category:** security-privacy  |  **Severity:** Low  |  **Confidence:** High  |  **Source:** segment-K  |  **Effort:** S  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `ls -la .env — 10,324 bytes, 83 KEY= lines, untracked`
  - `docs/SECRET_CUSTODY.md:9-14 — 'env (default): plaintext in .env ... readable by any same-user process'`
  - `docs/SECRET_CUSTODY.md:29-40 — windows-credential-manager mode + manage_secrets.py exist but require manual migration; no evidence it was run`
- **Observed:** Default custody is plaintext-on-disk for all read-only data-source keys; the well-designed Credential Manager alternative exists but whether the operator migrated cannot be verified read-only.
- **Why it matters:** Any same-user process (including a compromised npm/pip package) can read all 83 keys in one file read.
- **Failure mode:** Malicious dev dependency exfiltrates .env; attacker burns paid API quota (xAI, EDINET, OpenDART, Etherscan) under the operator's identity.
- **Business impact:** Quota theft and key-rotation churn; bounded because keys are read-only data keys with no trade/money capability (docs/SECRET_CUSTODY.md:3-5).
- **Score impact:** K -0.2
- **Recommended fix:** Run the documented migration (manage_secrets.py set for each key, delete plaintext lines), run harden_local_owner_files.ps1, record 'manage_secrets.py audit' output as evidence.

### SP-103 — Local-only pre-rewrite refs (branch + tag) still present; rewrite closure never formally documented

- **Category:** security-privacy  |  **Severity:** Low  |  **Confidence:** High  |  **Source:** segment-K  |  **Effort:** XS  |  **Next sprint:** Yes
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `git branch -a / git tag — backup/pre-gitleaks-rewrite branch and backup/pre-gitleaks-rewrite-tag exist locally; absent from git ls-remote origin`
  - `git diff 8537585 81366fa --stat — only .gitleaksignore differs, confirming no real secret was removed by the rewrite (fixture-fingerprint churn from a rebase)`
- **Observed:** The scary-sounding backup refs are benign (verified: tree-identical to rewritten history except allowlist fingerprints) but nothing in the repo records that conclusion, so every future audit re-runs this forensics.
- **Why it matters:** Undocumented history-rewrite artifacts read as a possible past secret leak to any diligence reviewer; the answer 'false positives only' is currently rediscoverable but not stated.
- **Failure mode:** A future auditor or acquirer sees 'pre-gitleaks-rewrite' and prices in a secret-leak incident that never happened.
- **Business impact:** Trust discount on diligence with zero underlying substance — the cheapest kind of value leak to fix.
- **Score impact:** K -0.1; touches evidence-leakage
- **Recommended fix:** Add a short SECURITY_GITLEAKS.md incident note (referenced by b40b54e's toml but not on main) stating the rewrite scope = synthetic fixture fingerprints, then delete the local backup branch/tag or archive them explicitly.

### SP-104 — gh CLI absent on the operator machine — no local way to confirm security gates (gitleaks, pip-audit, owner-controls) actually pass

- **Category:** install-fragility  |  **Severity:** Low  |  **Confidence:** High  |  **Source:** segment-K  |  **Effort:** XS  |  **Next sprint:** No
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `bash: gh run list — exit 127; PowerShell: CommandNotFoundException`
  - `.github/workflows/dep_audit.yml:82-86 — scripts/audit_github_owner_controls.py needs GH_TOKEN in CI, implying GitHub-API-side checks the operator cannot mirror locally`
- **Observed:** The machine that pushes daily (schtasks 08:30 NBI loop) cannot query whether its pushes passed the four security workflows.
- **Why it matters:** Security gates that nobody watches are indistinguishable from no gates; the OS-scheduled daily loop pushes autonomously without a feedback channel.
- **Failure mode:** dep_audit goes red (new CVE or a real gitleaks finding) and stays red for weeks because failure notifications are unmonitored email at best.
- **Business impact:** Silent decay of the strongest controls in the repo.
- **Score impact:** K -0.1; also touches runtime-leakage
- **Recommended fix:** Install gh, authenticate, and add a read-only 'gh run list' check to the operator daily checklist or the NBI cockpit.

### SP-105 — Strongest honesty assets (MODEL_CARD, NBI doc, DEPLOYMENT blockers) are buried and unlinked from the investor path

- **Category:** documentation-gap  |  **Severity:** Low  |  **Confidence:** High  |  **Source:** segment-L  |  **Effort:** XS  |  **Next sprint:** Yes
- **Verification:** AGENT-EVIDENCED (single-auditor evidence; verification wave was cut by usage limits)
- **Evidence:**
  - `MODEL_CARD.md:36-57 — exemplary limitations section ('no performance claim exists', 'Independent validation: none') but absent from README's documentation map (README.md:97-119)`
  - `docs/NARRATIVE_BRANCH_ENGINE.md:1-20 — current, evidence-grade, honest ('edge claim remains false', gate-refused case documented) yet unlinked from README/SHOWCASE`
  - `DEPLOYMENT.md:12-24 — ranked P0/P1/P2 production blocker table, honest, but framed as generic 'path to production' rather than surfaced as a diligence artifact`
- **Observed:** The docs that would most impress a skeptical investor are exactly the ones the entry-point docs fail to route to.
- **Why it matters:** The repo's real differentiator is calibrated self-honesty; it is currently discoverable only by accident.
- **Failure mode:** Investor forms their opinion from stale README/TESTING.md and never reaches MODEL_CARD.md.
- **Business impact:** Best evidence for the 'trustworthy advisory system' pitch goes unused.
- **Score impact:** L -0.3; fixing it is most of the near-term ceiling upside
- **Recommended fix:** Add a 'Read these five docs first' investor path at the top of README: MODEL_CARD.md, SECURITY.md, DEPLOYMENT.md blockers, docs/NARRATIVE_BRANCH_ENGINE.md, docs/FINAL_SCORECARD.md (re-dated).


---

## 11. Current Standing Diagnosis

**Classification: 4.96/10 → "Functional MVP but fragile" (4.1–6.0 band), upper-middle of the band.** It is not yet a "serious paper-trading system" (6.1+) for one reason above all: a paper-trading system must close its loop, and this one has never closed a single real outcome.

1. **What is it today?** A single-operator, single-Windows-machine advisory scaffold with institutional-grade honesty reflexes and zero measured track record. It is a *measurement instrument that has never measured*. The safety layer (no-execution, fail-closed gates, audit chain) is investor-demo grade; the evidence layer is pre-prototype; everything else is in between.
2. **Strongest part:** Security/secrets posture (7.8) and the test culture (7.4) — 7,567 real tests, hash-chained audit logs, clean history forensics, machine-enforced execution lock. The frontend's honesty (6.7) is a close third and is rarer than it sounds.
3. **Weakest part:** Calibration/Outcome Evidence (3.6) — N=0 — with Risk Discipline (3.8) right behind it, and the two compound: no outcomes means no calibration, and phantom-pointed risk machinery means no protection while you wait.
4. **What breaks first under real-money use?** The risk path: a gap-down on a 4×-leveraged NSE position produces zero system response — no stop breach (no stops recorded), no exposure alarm (no aggregation), no staleness warning (no age gate on holdings truth). SP-001 + SP-010 + SP-012 chained.
5. **What embarrasses you in front of an investor?** Documentation contradictions, within ten minutes: TESTING.md denying test infrastructure that demonstrably passes; two self-audits 3.4 points apart, both undated and unreconciled; "verified_current_holdings" branding on a 6-week-stale hand-edited file; `model_probability` whose docstring says "placeholder."
6. **What quietly loses money?** Acting on advisory context computed from stale substrate: 11-day-dead prediction-market lanes presented as healthy, month-old "today_" payloads, phantom-position management advice (holding sold positions / not covering new ones).
7. **What creates false confidence?** "HEALTHY 10/10" that measures installation/ingest rather than outcomes; `ok_filtered` zero-persistence reported as source health; artifact-served cockpit health with no staleness check (a dead scheduler renders green forever); statistical vocabulary (probability, mispricing, edge) on uncalibrated heuristics.
8. **Highest-leverage fix:** Merge + wire + retro-run the outcome maturation loop. It converts N=0 → N≈56 using **already-locked, pre-registered, pre-horizon predictions** — evidence that cannot be manufactured retroactively and that no marketing can substitute for. Nothing else in the backlog buys credibility at that price.
9. **What should not be touched yet?** The architecture inversion (184k-LOC flat scripts/). It's real debt, but a big-bang refactor would burn the sprint that should buy evidence, and the green suite makes deferred mechanical packaging safe. Also: the five-model synthesis loop and the signal_arbitrage/mythos internals — self-consistent, advisory-only, not the bottleneck.
10. **What should be deleted, simplified, or merged?**
    - *Merge (decide once):* `chore/real-forward-outcome-maturation` (merge it); `feature/p2-interpretation-defense-expansion` (merge as input-estimators or formally retire — stop carrying a shadow codebase).
    - *Delete:* orphaned `PipelineV57LocalMVPSilent` logon task; `scripts/candidate_memory_decay.py` v1 (after repointing 2 importers to v2); `backup/2026-04-*` in-repo snapshots; `linkedin/*.html`; `prompts/paper_trading_prompt_v51–v57plus`; stale generated HTML in `docs/`; the empty `adapters/`, `governance/`, `scripts/api/routers/` dirs (or fill the last one — see sprint).
    - *Simplify:* retire `src/dashboard/streamlit_app.py` to `archived_experimental/` (it bypasses every truth gate the other UI respects); merge `config/` and `configs/` (colliding `sources.yaml` with different schemas is an operator trap).

---

## 12. Ceiling Projection

| Horizon | Target overall | Segments reachable | Required fixes | Non-negotiable blockers | Risks that remain |
|---|---|---|---|---|---|
| **After 1 excellent sprint** | **~5.9** | D→5.5, C→5.6, E→6.2, I→5.8, G→7.2, A→5.4, L→7.0 | The Next Best Sprint below (maturation merge, risk repointing, silent-death fixes, loud failures, doc truth-sync) | Maturation loop must merge cleanly; holdings truth must be refreshed by the operator (only you know your real positions) | N≈56 is one cohort, not a track record; sheets loop still open; architecture untouched |
| **After 3 excellent sprints** | **~6.6–6.8** (serious paper-trading system) | D→6.3, B→5.8, C→6.2, E→6.5, H→6.3, F→5.8, J→8.0 | Sprint 2: sheets loop closed or formally descoped + provider coverage on full security master + benchmark-relative Brier + Kalshi ledger resolution loop. Sprint 3: packaging (pyproject, kill sys.path hacks, split api_server) + coverage floor + branch protection | Daily loop must run unattended for ≥3 weeks with alerting proving itself; a second forward cohort must be locked | Signal quality still heuristic (calibration corpus young); single-machine deployment |
| **After 1 month disciplined** | **~7.0–7.3** | Above plus A→6.5 (live morning brief), L→7.8 | Live discovery producing real candidates daily; scorer consolidation enforced in code; first calibration report on N≥50 real outcomes with benchmark | 30 days of unbroken scheduled-loop evidence; no fixture pollution incidents | Edge remains unproven (calibrated ≠ profitable); operator burden still high |
| **Before real-money use** (system-informed manual trades; execution stays locked by design) | **≥7.5** with segment floors: D≥6.5, C≥6.5, E≥6.5, I≥6.5 | — | N≥50 real forward outcomes with benchmark-relative Brier **beating the market-prior baseline or honestly reported as not**; stops + invalidation on every position incl. leveraged; live drawdown monitor; staleness fail-closed on every truth surface; push alerting | **Hard gate:** never before the calibration report exists and is unflattering-capable. The repo's own PRE_REAL_MONEY_READINESS_GATE doc should be wired to these floors and machine-checked | Model risk (heuristics may calibrate poorly); regime risk (one cohort ≠ all weather); the human override problem |
| **Before investor demo** | **≥6.5** and zero doc contradictions | G, J, K already there; L→7.5+, A→6.0+ | Doc truth-sync; orphan route fixed; fixture-proof served artifacts; one end-to-end live demo path (morning brief → NBI card → evidence trail → honest N) | An investor will ask "what's your track record?" — the answer must be a number with provenance, even if small ("N=56, Brier 0.21 vs baseline 0.25, locked timestamps, here's the ledger") | Small N invites "come back later"; that is still the honest, fundable answer |
| **Before charging users** | **≥8.0** | F→7+, H→7.5+, K→9+ | Hosted multi-user deployment (the plans exist: HOSTED_DEPLOYMENT_PLAN.md, POSTGRES_MIGRATION_PLAN.md — currently plans only); auth beyond single-owner token; per-user data isolation; compliance/legal review of advisory status in target jurisdictions; SLAs on data freshness | Regulatory clarity on "advisory" in each jurisdiction; support burden; real uptime engineering | Charging converts honesty debt into liability; every "verified" label becomes a representation |

---

## 13. Next Best Sprint — "Close the Loop"

**Thesis:** every sprint before this one built machinery; this sprint makes the machinery touch reality. Maximize `Score_Gain_Per_Unit_Effort = (Expected_Weighted_Score_Increase × Risk_Reduction × Evidence_Quality_Gain) / Estimated_Effort` with `Risk_Reduction ∈ [1.0,2.0]`, `Evidence_Quality_Gain ∈ [1.0,2.0]`, `Effort ∈ {1,2,3,5,8}`.

Projected sprint outcome: **4.96 → ~5.9 overall** (weighted lift ≈ +0.93).

| # | Item | Weighted lift | Risk | Evid | Effort | **SGPUE** | Priority |
|---|------|--------------|------|------|--------|-----------|----------|
| 1 | Loud failures: scheduler exit codes + staleness alarms + orphan route | 0.139 | 1.8 | 1.3 | 1 | **0.325** | P0 (do first — 1 day, protects everything else) |
| 2 | Merge outcome-maturation loop + retro-mature 56 snapshots | 0.276 | 1.5 | 2.0 | 3 | **0.276** | P0 (the strategic core) |
| 3 | Repoint risk machinery at canonical holdings + stops + freshness gate | 0.246 | 2.0 | 1.5 | 3 | **0.246** | P0 |
| 4 | Kill silent data death: rows_persisted + holdings-driven prices + payload age gates | 0.144 | 1.7 | 1.6 | 2 | **0.196** | P1 |
| 5 | Doc truth-sync | 0.080 | 1.0 | 1.7 | 2 | **0.068** | P1 |
| 6 | Runtime artifact hygiene (tests can't write served paths) | 0.047 | 1.4 | 1.5 | 2 | **0.049** | P2 |

### Item 1 — Make failure loud (P0, Effort 1)
- **Files:** `scripts/nbi_scheduler.py:573`; `frontend/src/components/layout/Sidebar.tsx` (add `/nbi`); `frontend/src/app/nbi/page.tsx` (render `generated_at` + age warning); `scripts/api_server.py` `/nbi/cockpit` (compute artifact age); `scripts/check_live_signal_refresh_task.py`.
- **Why it beats alternatives:** highest SGPUE on the board; every other sprint item's value depends on failures being visible; ~1 day of work.
- **Segment lift:** I 4.4→5.8, G 6.7→7.2, A +0.2.
- **Acceptance tests:** unit test: `run-once` returns exit 1 when status ∈ {BROKEN, BROKEN_UNSAFE}; schtasks Last Result becomes nonzero on a forced-failure dry run; `/nbi` reachable from sidebar (vitest spec); cockpit renders amber at artifact age >26h, red >50h (component test with frozen clock).
- **Rollback:** single-file reverts; exit-code change is isolated to the CLI return.

### Item 2 — Merge the outcome-maturation loop, retro-mature the 56 (P0, Effort 3)
- **Files:** port from `chore/real-forward-outcome-maturation`: `scripts/run_daily_outcome_maturation.py`, `scripts/forward_outcome_maturity_scanner.py`, `scripts/real_calibration_evidence.py` + their 7 test files; wire a maturation step into `scripts/nbi_scheduler.py` `run_once()`; register new modules in `core_module_boundary.py` + `private_scope_guard.py`; add SPY benchmark closes to the scanner (from SP-050).
- **Why it beats alternatives:** converts the only expired-but-recoverable evidence asset (56 pre-registered, timestamp-locked, pre-horizon predictions from 2026-05-31; June prices are fetchable) into the system's first real track record. Nothing else produces evidence of this quality at any price.
- **Segment lift:** D 3.6→5.5, B +0.4.
- **Acceptance tests:** `decision_probability_snapshots` shows ≥50 rows with `outcome_label NOT NULL` and `is_real_outcome=1`; first Brier/logloss report generated from real rows with benchmark column populated (or explicitly BENCHMARK_UNAVAILABLE per row, never silently absent); scheduled `run_once` output includes `outcomes_closed` count; new CI guard: every DB table written by the working tree has ≥1 reading reference (kills the orphaned-table failure mode permanently); fixture rows (`data_mode=FIXTURE_DEMONSTRATION`) provably excluded from every calibration computation (negative test).
- **Rollback:** revert the merge commit; maturation writes are additive columns/rows — snapshot `runtime/mvp_local.db` via existing `scripts/backup_db.py` before first live run.

### Item 3 — Point the risk engine at reality (P0, Effort 3)
- **Files:** `data/daily_payload/verified_current_holdings.json` (schema: add per-position `stop_loss`, `invalidation_level`, `take_profit`, `price_as_of`; operator fills values — the audit cannot invent stops); `scripts/runtime_common.py` (new canonical loader + freshness gate); `scripts/action_engine.py` (source swap); `scripts/signal_refinery.py` (thermal battery count from truth gate H set); `scripts/portfolio_truth_gate.py`; `scripts/pre_real_money_preflight` surface.
- **Why it beats alternatives:** the current configuration is worse than nothing — it emits EXIT_NOW on positions that don't exist and silence on 4×-leveraged ones that do. This is the "quietly loses money" fix.
- **Segment lift:** C 3.8→5.6, A +0.3.
- **Acceptance tests:** action_engine evaluates all 10 real positions (test against a fixture copy of the real schema); missing stop fields on a leveraged position → blocking validation error; `run_date` older than 3 days → `HOLDINGS_TRUTH_STALE`, all position-management advice demoted to review-only (fail-closed test); thermal battery reports SATURATED at 10/6; regression test proving `moltbook/open_positions.json` is unreachable from action selection.
- **Rollback:** loader behind `HOLDINGS_SOURCE` env/config flag defaulting to the new path; `--legacy-moltbook` escape hatch for one release.

### Item 4 — Kill silent data death (P1, Effort 2)
- **Files:** `scripts/source_health_summary.py` (zero-persist classification); `scripts/refresh_live_signals.py` (record `rows_persisted`); `scripts/ingestion/market_data_loader.py` (ticker list from holdings + `global_securities.yahoo_symbol`; per-ticker failure records); `scripts/anti_staleness.py` (wall-clock `generated_at` gate); `scripts/api_server.py` stale_sources.
- **Segment lift:** E 4.8→6.2, I +0.3.
- **Acceptance tests:** fixture run-log with 3 consecutive `ok_filtered`/0-persisted runs → source classified DEGRADED and listed in `/health` stale_sources; scheduled refresh fetches all 10 holdings symbols (incl. `.NS` names) + master list; payload with `generated_at` >24h → anti_staleness emits STALE_PAYLOAD and demotes labels (fail-closed test).
- **Rollback:** classification thresholds in config; revert restores old taxonomy.

### Item 5 — Doc truth-sync (P1, Effort 2)
- **Files:** `TESTING.md` (real counts), `README.md` (16-route table + 30-line CURRENT STATE section linking NBI/chicken-gate/Mythos docs), `AUDIT_BRUTAL_MVP_ASSESSMENT.md` + `docs/FINAL_SCORECARD.md` (HISTORICAL banners with dates), new `docs/GLOSSARY.md` (codenames an outsider can follow), `SETUP.md` (Python version + auth reality).
- **Why:** pure investor-credibility purchase; the contradictions are the cheapest embarrassment to eliminate.
- **Acceptance tests:** a doc-reality test asserting TESTING.md's stated test-file count matches `tests/` glob count ±10%; README route table matches `next build` route output; both stale audits carry a dated HISTORICAL header.
- **Rollback:** docs-only.

### Item 6 — Runtime artifact hygiene (P2, Effort 2)
- **Files:** `conftest.py` (autouse fixture setting `NBI_ARTIFACT_DIR`/`RUNTIME_ARTIFACT_DIR` to tmp); `scripts/nbi_evidence_factory.py` + card exporters (honor the env var); new guard test.
- **Acceptance tests:** full-suite run leaves `runtime/nbi_operator_cards.json` byte-identical (hash before/after in CI); guard test fails if served artifacts contain fixture markers (`MACRO1`, `https://e/`); `/nbi/cards` fail-closes on artifacts carrying fixture provenance.
- **Rollback:** env-var redirect only; no production code path changes.

**Explicitly deferred (and why):** architecture packaging (F) — highest effort (8), zero evidence gain, safe to defer under green tests; Sheets sync overhaul (H) — real but the sheet loop has never run in production, so it blocks nothing this sprint (schedule for Sprint 2); scorer consolidation (B) — needs the calibration substrate from Item 2 to decide *which* scorer survives.

---

## 14. Acceptance Criteria for the Sprint (definition of done)

1. `SELECT COUNT(*) FROM decision_probability_snapshots WHERE outcome_label IS NOT NULL` ≥ 50, all with locked pre-horizon timestamps (2026-05-31 cohort).
2. A committed, dated calibration report: Brier + logloss on real outcomes vs market-prior baseline, benchmark column populated, fixtures excluded by construction (negative test proves it).
3. `action_engine` stop-breach evaluation runs against the refreshed canonical holdings (10/10 positions, stops present, leveraged positions covered) and cannot read the moltbook ledger.
4. `verified_current_holdings.json` refreshed by the operator with `run_date` = sprint week and a freshness gate that fail-closes at +3 days thereafter.
5. A forced scheduler failure produces: nonzero exit code, nonzero schtasks Last Result, and a red/amber state visible in the frontend without CLI use.
6. Kalshi/Polymarket zero-persistence visible as DEGRADED in `/health`; scheduled prices cover all holdings symbols.
7. Full test suite green (≥7,567 + new tests); no doc contradiction from §L's list survives; `/nbi` reachable from navigation.
8. Everything advisory-only: no change touches the execution lock, and `tests/test_no_execution_guard_repowide.py` still passes.

---

## 15. Final Brutal Verdict

**What it is:** a one-person, one-laptop advisory scaffold with genuinely rare engineering honesty — fail-closed gates, demote-only scoring, machine-enforced no-execution, 7,700+ real tests — currently running on stale truth and zero closed evidence. Score: **4.96/10, functional-but-fragile**, at the top of the prototype-to-MVP transition but below every threshold that matters commercially.

**What it is not:** a trading system (by design), a calibrated model (N=0), a track record (none exists), a product an investor can diligence without hitting contradictions in the first ten minutes, or a system that would protect your capital today (its risk engine watches a portfolio you don't own).

**What it pretends to be** (mostly by naming, not by lying): "verified_current_holdings" that no broker verified and no process refreshes; "model_probability" that is a placeholder blend; "HEALTHY 10/10" that measures installation, not function; "Source healthy" for lanes that persisted nothing in 11 days. The honesty culture is real at the layer of *labels on states* — it is the *names of things* that oversell.

**What it can become:** the ultimate ceiling computes to 8.01 — a legitimate early production-grade advisory instrument — and unusually, the path is not blocked by research risk. Every blocking item in this audit is engineering: merge a branch, repoint a loader, add an age check, refresh a file. The 56 expired-but-recoverable locked predictions are a one-time gift; every week they age, retro-maturation gets harder to defend.

**Before you trust it with real money:** N≥50 closed real outcomes with a benchmark-honest calibration report; stops on every position including the 4× leveraged ones; a freshness gate on every truth surface; an alerting path that has caught at least one real failure. Not one of these exists today. The repo's own `PRE_REAL_MONEY_READINESS_GATE.md` should be wired to machine-checked floors so this promise cannot be quietly relaxed.

**Before you show investors:** fix the documents (a morning of work that removes the cheapest embarrassment), fix the orphan route and the fixture-polluted surface, and — above all — walk in with a number: "56 pre-registered predictions, locked timestamps, here is the Brier score against the market prior, here is the ledger." Small N with honest provenance is a fundable story. Big machinery with N=0 is not.

The system's defining irony: it was built to stop its operator from fooling themselves about markets, and it currently fools its operator about itself — green healths on dead loops, stops on phantom positions, "today" files from last month. One sprint closes that gap. Close the loop.

---

*Audit limitations (honest accounting): the multi-agent verification wave (24 adversarial re-checks), 6 specialized hunters, and the completeness critic were cut by session usage limits. All 12 segment auditors and the repo mapper completed. The main line independently confirmed both Critical findings and 10 of the High findings (marked CONFIRMED in the register); findings marked AGENT-EVIDENCED rest on single-auditor evidence with exact file:line citations and should be re-checked before acting. One dedicated pass that did not complete: lookahead/temporal-leakage in the backtest scripts (`backtest_signals.py`, `belief_backtest.py`, walk-forward) — segment B/D coverage was partial there; flag for the next audit. Where post-audit reality changed mid-audit (NBI task's first firing 2026-07-04 09:11; fixture card overwritten), both states are reported with timestamps.*


---

## Post-Sprint Appendix: Close the Loop (2026-07-04)

The "Close the Loop" sprint recommended in §13 was executed the same day.
Full detail: `CLOSE_THE_LOOP_SPRINT_REPORT.md`. This appendix records what
changed against this audit's findings; the body above is preserved as the
2026-07-03 baseline and is NOT rewritten.

**Score movement (same weights, honest re-scoring):**

| | Overall | A | B | C | D | E | F | G | H | I | J | K | L |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Audit (07-03) | **4.96** | 4.7 | 4.8 | 3.8 | 3.6 | 4.8 | 4.7 | 6.7 | 4.4 | 4.4 | 7.4 | 7.8 | 5.4 |
| Post-sprint (07-04) | **5.78** | 5.2 | 5.1 | 5.4 | 5.6 | 5.6 | 4.8 | 7.2 | 4.4 | 5.8 | 7.7 | 7.8 | 7.0 |

Near-term ceiling 6.50 → **~6.70**; ultimate ceiling 8.01 → **~8.11**
(structural caps removed: the evidence loop is live on the canonical branch
and guarded against re-stranding).

**Evidence of execution (commands run, all real):**
- Both Criticals closed: SP-001 (risk engine now sources
  `verified_current_holdings.json` via fail-closed
  `scripts/holdings_truth_gate.py`; moltbook never a default source —
  regression-tested) and SP-002 (maturation loop ported: 26 modules +
  22 test files from `chore/real-forward-outcome-maturation`).
- **N = 0 → 56**: after appending 92 real June OHLCV bars,
  `run_daily_outcome_maturation --write --benchmark-symbol SPY` attached
  all 56 expired locked predictions. Locked prediction fields verified
  byte-identical (SHA-256) before/after. Honest result: Brier 0.2794,
  base rate 0.214, mean alpha vs SPY −2.08% — **NO DEMONSTRATED EDGE**,
  `predictive_claim_allowed` remains false. The system's first real
  measurement is unflattering and correctly reported as such.
- Scheduler exit-code bug (segment I evidence) fixed and pinned:
  BROKEN → exit 1 (`tests/test_nbi_scheduler_exit_codes.py`); maturation
  step now runs in the daily 08:30 loop and participates in its health.
- SP-016 closed (`ZERO_PERSISTED_DEGRADED` axis), SP-017 closed
  (holdings-driven price list), SP-023 closed (/nbi in navigation),
  SP-003 mechanism closed (tests can no longer write served artifacts;
  guard fixtures in `conftest.py`).
- Truth surface shipped: `GET /truth-surface` /
  `python -m scripts.truth_surface_report` — HEALTHY/DEGRADED/BLOCKED/
  BROKEN with per-axis evidence; N=0, missing stops, stale holdings/
  artifacts, zero-persist sources each cap the state (11 rule tests).
- Branch-stranding guard shipped (`tests/test_branch_stranding_guard.py`)
  — during the sprint it caught a doc referencing a script absent from the
  branch, which was then ported. The month-long silent-stranding failure
  mode now fails the suite instead.
- Docs truth-synced: TESTING.md counts corrected, README route table +
  current-state section, both stale self-audits marked HISTORICAL,
  `docs/OPERATIONAL_TRUTH.md` added (probability semantics, calibration
  criteria, scheduler exit semantics, canonical holdings, glossary).
- Validation: backend **7,893 passed / 3 skipped / 0 failed** (16m04s);
  frontend vitest 207/207; `next build` 16 routes.

**Remaining Critical/High (unchanged by this sprint, sequenced next):**
fresh discovery still fail-closes on static payloads (SP-006 family);
sheets sync loop unproven end-to-end (segment H, all findings open);
no push alerting (segment I residue); scorer sprawl and placeholder
`model_probability` semantics (SP-008/SP-006-B) — now *measured* but not
consolidated; architecture inversion (SP-020/021/022) untouched by design.

**Real-money readiness: STILL BLOCKED — and now the system says so itself.**
The blockers are machine-visible in `/truth-surface`: calibration gate
unmet (N=56 < 200, Brier 0.2794 > 0.25), 10/10 positions missing stops
(risk state BLOCKED, leveraged INR names flagged CRITICAL), holdings truth
stale pending operator re-verification, no drawdown monitor, no alerting.
Advisory-only execution lock unchanged and re-verified
(`tests/test_no_execution_guard_repowide.py` passing).


---

## Post-Sprint Appendix: Feed the Loop / Gap Closer (2026-07-04)

Same-day follow-up to Close-the-Loop, executed on branch
`sprint/feed-the-loop-gap-closer`. Full detail:
`FEED_THE_LOOP_SPRINT_REPORT.md`. The audit body and the first appendix are
preserved unmodified.

**Score movement (same weights):**

| | Overall | A | B | C | D | E | F | G | H | I | J | K | L |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Audit (07-03) | 4.96 | 4.7 | 4.8 | 3.8 | 3.6 | 4.8 | 4.7 | 6.7 | 4.4 | 4.4 | 7.4 | 7.8 | 5.4 |
| Close-the-Loop | 5.78 | 5.2 | 5.1 | 5.4 | 5.6 | 5.6 | 4.8 | 7.2 | 4.4 | 5.8 | 7.7 | 7.8 | 7.0 |
| Feed-the-Loop | **6.30** | 6.0 | 5.2 | 6.2 | 6.3 | 6.3 | 4.9 | 7.6 | 5.4 | 6.8 | 7.9 | 7.8 | 7.2 |

Gap-closure ratio vs the 6.70 near-term ceiling: ρ = (6.30−5.78)/0.92 =
**0.565 — minimum success**, honestly not the 6.50 strong target: the
remaining lift is operator action (stop confirmation) and elapsed calendar
time (horizons, unattended runs), not missing code. New near-term ceiling
≈ 6.75; new ultimate ceiling ≈ 8.20.

**What now compounds daily** (`nbi_scheduler run-once`, six stages, each
with recorded health): discovery refresh (canary-gated, VERIFIED_LIVE
payloads — first live discovery data since 2026-05-22) → snapshot producer
(25 timestamp-locked forward predictions/day, same-day idempotent; 25
locked live on 2026-07-04 → forward-eligible cohort 56→81, maturing
2026-07-09) → Kalshi settlement harvest (846-row ledger; provider OK; all
polled markets honestly UNSETTLED) → NBI ingest/cards → outcome maturation
→ operator alert dispatch (append-only queue; 5 real alerts on day one,
2 CRITICAL).

**Risk truth became operator-actionable without faking anything:** the stop
compiler generated `data/daily_payload/stop_loss_backfill_template.json`
(10 suggestions, named policy, `requires_operator_confirmation: true`);
`--apply-confirmed --write` activates ONLY operator-confirmed stops with
provenance and can refresh `run_date` only via an explicit
`holdings_confirmed_current` confirmation. Until then the system stays
BLOCKED and says so on every surface (validator exit 1, truth surface,
cockpit panel, CRITICAL alerts).

**Validation:** backend 7,935 passed / 3 skipped / 0 failed (17m26s);
targeted subset 869 passed; frontend 37 files / 213 tests, zero unhandled
errors; build 16 routes. Execution lock unchanged
(`tests/test_no_execution_guard_repowide.py` green).

**Still true:** NOT real-money ready (N=56<200, Brier 0.2794 — no
demonstrated edge; stops unconfirmed; <30 days unattended evidence);
investor-demo-able only as an honesty story. The system remains advisory-
only with the execution gate machine-locked.


---

## Post-Sprint Appendix: Open the Gate / Second Gap Closer (2026-07-04)

Third same-day sprint (`sprint/open-the-gate-gap-closer`); full detail in
`OPEN_THE_GATE_SPRINT_REPORT.md`.

**Scores:** 6.30 -> **6.45** unconditional (A 6.3, C 6.4, D 6.4, G 7.7,
H 5.9, I 7.0, J 8.1, L 7.4; B/E/F/K unchanged). Gap-closure ratio 0.333 —
**below the 0.4444 minimum, reported without excuse**: the remaining lift
is the operator's stop confirmation (S_conditional ≈ 6.54, zero further
code) plus five calendar days (N=81 matures 2026-07-09; evidence calendar
projects the N=200 calibration gate ~33 days out at current velocity).

**What shipped:** strict stop-confirmation contract (typed acknowledgement
`I_CONFIRM_THESE_STOPS_ARE_MY_OPERATOR_RISK_LIMITS`, confirmation id, risk
ack, leveraged ack — six rejection tests prove fake confirmation is
structurally impossible); confirmation-required artifacts + generated
`OPERATOR_ACTION_CHECKLIST.md`; three-tier holdings freshness (1d/3d);
archive provenance backups; drawdown/stop-breach monitor in the (now
8-stage) daily loop — live run honestly reports NO_MONITORABLE_POSITIONS;
Sheets round-trip proof (fixture PASS: schema, idempotency, SHA-256
read-back; --live-safe DEGRADED pending sheet config); real-app cockpit
honesty smoke (PASSED live: BLOCKED state, no overclaims) + Playwright
spec; evidence maturity calendar; alert escalation (L2 >24h, L3 >72h).

**Validation:** backend 7,976 passed / 3 skipped / 0 failed (14m51s);
targeted 442 passed; frontend 213/213 + build green. Execution lock intact; no stop was
confirmed by software; the state remains **BLOCKED and says so**.
