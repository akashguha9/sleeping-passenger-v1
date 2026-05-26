# sleeping-passenger-v1

> A **local-first, single-operator, advisory-only signal review cockpit**.
> It ingests public read-only signals into a local SQLite store, surfaces
> them in a Next.js dashboard, and lets a human reflect, log a manual
> trade, and reconcile the outcome.  It does not place trades.

## 1. What this MVP is

* A **signal review and reflection journal** that runs on one operator's
  laptop.
* A **read-only ingestion** layer for 13 public source families
  (Polymarket, Kalshi, GDELT, SEC EDGAR, NewsAPI, Event Registry,
  Etherscan, Grok/xAI, Market Data via yfinance, India NSE/RBI/SEBI,
  Global Filings, Asia Disclosure, plus a derived
  Prediction-Market-Disagreement scanner).
* A **6-hour refresh orchestrator** plus a **30-minute watchdog** that
  share the same freshness model — the cockpit and the watchdog cannot
  disagree.
* A **Moltbook learning loop** that turns closed losing manual trades
  into one advisory-only learning entry (`docs/MOLTBOOK_HIPPOCAMPUS.md`).

## 2. What this MVP is not

* **Not a broker.**  No order routing.  No execution.
* **Not a trading bot.**  No automated buy / sell / order placement.
* **Not multi-user.**  No auth, no accounts.
* **Not hosted.**  Binds to loopback by default.
* **Not financial advice.**  All output is advisory-only journaling.

## 3. Advisory-only safety guarantee

Every backend response and every UI surface carries:

```
advisory_status          = "ADVISORY_ONLY"
execution_mode           = "HUMAN_ONLY"
execution_gate           = "LOCKED"
broker_api_called        = false
ai_execution_count       = 0
execution_permission     = false
can_execute              = false
broker_order_id          = "NONE"
human_review_required    = true
```

The refusal is enforced at four layers:

1. **UI** — no Buy / Sell / Execute / Auto-trade button or wording.
2. **API surface** — no `/buy`, `/sell`, `/order`, `/execute`, `/broker`
   route exists (`tests/test_api_server.py:790-820` AST proof).
3. **Persistence** — every row carries the stamp set above
   (`scripts/advisory_contract.py`).
4. **Read-only HTTP client** — `src/ingestion/kalshi_live_client.py`
   refuses every non-GET method and every forbidden path segment
   (`/orders`, `/portfolio`, `/fills`, `/positions`, `/balance`,
   `/deposits`, `/withdrawals`, `/api_keys`, …) **before** a request is
   formed.

### Advisory safety rules (permanent — never change)

* No Buy, Sell, Execute, or Auto-trade button or endpoint exists anywhere.
* `execution_mode = HUMAN_ONLY` on every trade record.
* `advisory_status = ADVISORY_ONLY` on every record.
* `ai_execution_count = 0` always.
* `broker_api_called = False` always.
* `broker_order_id = NONE` always.
* `execution_gate = LOCKED` on every signal event.
* No `.env` contains broker credentials.  No broker API is imported.

## 4. First-day operator quickstart

```powershell
# Backend (one-time)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt

# First-day seed — populate canonical SQLite from FREE public sources only.
# Default is --dry-run; pass --write to actually persist rows.
python scripts\first_run_seed_free_sources.py --dry-run
python scripts\first_run_seed_free_sources.py --write

# Backend server
python scripts\api_server.py
# (or: python -m uvicorn scripts.api_server:app --reload)

# Frontend (new terminal)
cd frontend
npm install
npm run dev
# Open http://localhost:3000
```

See `SETUP.md` for the full setup story (env vars, troubleshooting,
Windows scheduler recipes).

## 5. Canonical workflow

```
1. Ingest      — first-run seed or 6h refresh.
2. Review      — open Signal Inbox; filter, sort, drill in.
3. Reflect     — write a thesis or note on a signal.
4. Decide      — mark watchlist / human_review / rejected.
5. Log         — record a manual trade you placed yourself.
6. Reconcile   — match the logged trade against the actual outcome.
7. Learn       — log a Moltbook entry capturing the mistake / bias /
                 rule update (loss-only by design).
```

Every step is human-driven.  The MVP never decides for you.

## 6. Source truth model

| Source | Phase | Env var (if any) | Status | CLI dry-run | CLI write | Frontend filter | Persistence |
|---|---|---|---|---|---|---|---|
| `polymarket` | 1 | — | Active | `run_live_sources_phase1.py --source polymarket --dry-run --json` | `--write` | Polymarket | signal_events / source_run_log |
| `gdelt` | 1 | — | Active | `run_live_sources_phase1.py --source gdelt --dry-run --json` | `--write` | GDELT | signal_events / source_run_log |
| `sec_edgar` | 1 | `SEC_USER_AGENT` | Skips cleanly if unset | `run_live_sources_phase1.py --source sec_edgar --dry-run --json` | `--write` | SEC EDGAR | signal_events / source_run_log |
| `newsapi` | 2 | `NEWS_API_KEY` | Skips cleanly if unset | `run_live_sources_phase2.py --source newsapi --dry-run --json` | `--write` | NewsAPI | signal_events / source_run_log |
| `event_registry` | 2 | `EVENT_REGISTRY_API_KEY` | Skips cleanly if unset | `run_live_sources_phase2.py --source event_registry --dry-run --json` | `--write` | Event Registry | signal_events / source_run_log |
| `etherscan` | 2 | `ETHERSCAN_API_KEY` | Skips cleanly if unset or no address | `run_live_sources_phase2.py --source etherscan --dry-run --json` | `--write` | Etherscan | signal_events / source_run_log |
| `grok_xai` | 2 | `XAI_API_KEY` | Skips cleanly if unset | `run_live_sources_phase2.py --source grok_xai --dry-run --json` | `--write` | Grok/xAI | signal_events / source_run_log |
| `market_data` | 2 | — (yfinance) | Active | `run_live_sources_phase2.py --source market_data --dry-run --json` | `--write` | Market Data | signal_events / source_run_log |
| `india` | 2 | — | Active (NSE/RBI/SEBI public) | `run_live_sources_phase2.py --source india --dry-run --json` | `--write` | India | signal_events / source_run_log |
| `global_filings` | 2 | — (ASX active; others placeholder) | ASX active, rest skip cleanly | `run_live_sources_phase2.py --source global_filings --dry-run --json` | `--write` | Global Filings | signal_events / source_run_log |
| `asia_disclosure` | 2 | — (EDINET / OpenDART active; rest placeholder) | All skip cleanly | `run_live_sources_phase2.py --source asia_disclosure --dry-run --json` | `--write` | Asia Disclosure | signal_events / source_run_log |

All sources set `advisory_status = ADVISORY_ONLY`, `execution_gate = LOCKED`,
`human_review_required = True`, `ai_execution_count = 0`, and
`broker_api_called = False` on every normalized record.

### Phase C Integrated Source Matrix

The matrix above is the canonical surface validated end-to-end by
`scripts/phase_c_final_audit.py`.  Run the static integration audit:

```powershell
python scripts/phase_c_final_audit.py --verbose
```

## 7. Mock / fallback / degraded mode truth model

* **SQLite is canonical.**  `runtime/mvp_local.db` is the application's
  source of truth.  `canonical_store = "sqlite"`, `jsonl_is_canonical = false`.
* **JSONL is audit-only.**  Append-only mirror under `runtime/logs/*.jsonl`.
* **Mock data is UI-only.**  Lives in `frontend/src/lib/mockData.ts`.
  Whenever the frontend cannot reach the backend it falls back to mock
  data **and** renders a top-bar `MOCK MODE / BACKEND OFFLINE` chip.
  Mock rows never enter canonical SQLite.
* **Scores are uncalibrated.**  Until `scripts/calibration_report.py`
  returns `calibration_status="MEASURED"` with Brier ≤ 0.25 and
  ECE ≤ 0.10 on ≥ 200 labelled outcomes, no predictive claim is
  permitted.  See `docs/SCORING_STACK_VALIDATION.md`.
* **Truthfulness gates.**  `runtime_truth_purity_audit.py`,
  `runtime_artifact_manifest.json`, and the
  `tests/test_runtime_artifact_coherence_strict.py` gate ensure no
  unstamped runtime artifact accumulates in `runtime/release/`.

Full reference: `docs/PERSISTENCE_MODEL.md`,
`docs/TRUTH_PURITY_AND_DEMO_DATA_GUARD.md`.

## 8. Local architecture

```
Public read-only sources
        |
        v
scripts/refresh_live_signals.py  ── (every 6h)
scripts/watchdog_refresh_stale_sources.py  ── (every 30 min)
        |
        v
scripts/persistence.py  --->  runtime/mvp_local.db  (SQLite, canonical)
        |                       |
        |                       +--- runtime/logs/*.jsonl  (audit-only)
        v
scripts/api_server.py  (FastAPI, advisory-only, no broker route)
        |
        v
frontend/  (Next.js cockpit; MOCK MODE banner when backend offline)
```

* `scripts/advisory_contract.py` — the single source of safety stamps.
* `scripts/live_source_registry.py` — adapter status, freshness, derived
  parents, source tiers.
* `scripts/calibration_report.py` — Brier + ECE gate for the scoring stack.
* `scripts/first_run_seed_free_sources.py` — first-day operator seed.

## 9. Testing commands

```powershell
# Backend
python -m compileall scripts tests
python -m pytest tests -q
python -m pytest tests/test_advisory_contract.py tests/test_api_server.py -q
python -m pytest tests/test_advisory_stamp_property.py -q
python -m pytest tests/test_runtime_artifact_coherence_strict.py -q
python -m pytest tests/test_calibration_report.py -q
python -m pytest tests/test_first_run_seed_free_sources.py -q

# Frontend
cd frontend
npm test -- --run

# Opt-in real-API canary (skipped by default):
$env:RUN_REAL_API_CANARY = '1'
python -m pytest tests/test_real_api_canary.py -v
```

## 10. Current readiness label

| Lens | Score /10 | Verdict |
|---|---:|---|
| Local-first showcase | 8.2 | **SHIP** — see `docs/FINAL_SCORECARD.md`. |
| Controlled private beta | 4.5 | Design complete, implementation pending. |
| Public production SaaS | 1.5 | **Do not pursue this year.** |

Run the role-fit scorecard (regenerates both JSON + Markdown):

```powershell
python scripts/segment_role_scorecard.py `
  --json runtime/release/segment_role_scorecard.json `
  --markdown docs/scorecards/SEGMENT_ROLE_SCORECARD.md
```

This is an **alpha MVP** with a production-grade safety floor.  It is
suitable for a single technical operator running it locally.  It is not
suitable for second users, hosted multi-tenant deployment, or any
predictive-validity claim until the calibration gate reports `MEASURED`.

## 11. Links to deeper docs

| Doc | Purpose |
|---|---|
| [SETUP.md](SETUP.md) | Install, env vars, troubleshooting |
| [SHOWCASE.md](SHOWCASE.md) | One-stop product showcase |
| [DEMO.md](DEMO.md) | 5-minute scripted walkthrough |
| [TESTING.md](TESTING.md) | What is and isn't tested, how to run |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Current status and the path to production |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System / safety / persistence / refresh diagrams |
| [docs/PERSISTENCE_MODEL.md](docs/PERSISTENCE_MODEL.md) | SQLite canonical / JSONL audit-only contract |
| [docs/ADVISORY_ONLY_SAFETY_MODEL.md](docs/ADVISORY_ONLY_SAFETY_MODEL.md) | The canonical advisory-only contract |
| [docs/LIVE_SIGNALS_REFRESH_MODEL.md](docs/LIVE_SIGNALS_REFRESH_MODEL.md) | 6-hour refresh cadence + source-health |
| [docs/LIVE_REFRESH_WATCHDOG.md](docs/LIVE_REFRESH_WATCHDOG.md) | 30-min watchdog state taxonomy |
| [docs/SCORING_STACK_VALIDATION.md](docs/SCORING_STACK_VALIDATION.md) | EMS/EQS/DS/LS/EFS/APS calibration posture |
| [docs/MOLTBOOK_HIPPOCAMPUS.md](docs/MOLTBOOK_HIPPOCAMPUS.md) | One-loss-one-lesson learning loop |
| [docs/TRUTH_PURITY_AND_DEMO_DATA_GUARD.md](docs/TRUTH_PURITY_AND_DEMO_DATA_GUARD.md) | Fake-row detection + release gate |
| [docs/runtime_artifact_manifest.json](docs/runtime_artifact_manifest.json) | Coherence manifest for `runtime/release/*.json` |
| [docs/LEGAL_PRIVACY_NOTES.md](docs/LEGAL_PRIVACY_NOTES.md) | Advisory-only, no-financial-advice, source ToS |
| [docs/SOURCE_TOS_CHECKLIST.md](docs/SOURCE_TOS_CHECKLIST.md) | Per-source ToS verification |
| [docs/PRODUCT_DIRECTION_DECISION.md](docs/PRODUCT_DIRECTION_DECISION.md) | Local-showcase vs private-beta vs public-prod |
| [docs/FINAL_SCORECARD.md](docs/FINAL_SCORECARD.md) | Honest before/after readiness scorecard |
| [docs/scorecards/ROLE_FIT_SCORING_MODEL.md](docs/scorecards/ROLE_FIT_SCORING_MODEL.md) | Role-fit vs absolute scoring model + formulas |
| [docs/scorecards/SEGMENT_ROLE_MAP.md](docs/scorecards/SEGMENT_ROLE_MAP.md) | Per-segment roles, ceilings, unlocks |
| [docs/scorecards/SEGMENT_ROLE_SCORECARD.md](docs/scorecards/SEGMENT_ROLE_SCORECARD.md) | Generated role-fit scorecard |
| [docs/FINAL_ACCEPTANCE_CHECKLIST.md](docs/FINAL_ACCEPTANCE_CHECKLIST.md) | Local-showcase acceptance walkthrough |
| [docs/CALIBRATION_CORPUS.md](docs/CALIBRATION_CORPUS.md) | Calibration corpus pipeline + N_real reality check |
| [docs/HOSTED_CANARY.md](docs/HOSTED_CANARY.md) | Nightly real-API canary workflow + safety bounds |
| [docs/OPERATOR_REFRESH_CONTROL.md](docs/OPERATOR_REFRESH_CONTROL.md) | In-app advisory-only refresh button contract |
| [docs/CREDENTIAL_HYGIENE.md](docs/CREDENTIAL_HYGIENE.md) | Root service-account refusal + secrets path policy |

### Silent local startup (Windows)

A small set of PowerShell helpers run the stack at user logon with no
visible windows.  See `docs/legacy/HISTORICAL_LIVE_INGESTION_DETAILS.md`
for the full ceremony.  Quick reference:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\register_mvp_silent_startup_task.ps1
powershell -ExecutionPolicy Bypass -File scripts\windows\start_mvp_stack_silent.ps1
powershell -ExecutionPolicy Bypass -File scripts\windows\stop_mvp_stack_silent.ps1
```

The optional reverse proxy serves the frontend at `http://sleepingpassenger`
(local-only; requires the host alias and port-80 proxy registered by
`scripts\windows\add_sleepingpassenger_host_alias.ps1` and
`scripts\windows\start_sleepingpassenger_proxy.ps1`).  Logs land in
`runtime/logs/` (gitignored).

### Historical reference (legacy, non-canonical)

These documents preserve content that previously lived in this README.
They are historical, not the current canonical workflow.

| Doc | What it preserves |
|---|---|
| [docs/legacy/V5_7_HISTORICAL_REFERENCE.md](docs/legacy/V5_7_HISTORICAL_REFERENCE.md) | Pipeline V5.7 operator-control / perception-control / paper-execution ledger / archetype layers. |
| [docs/legacy/SIGNAL_REFINERY_HISTORICAL_REFERENCE.md](docs/legacy/SIGNAL_REFINERY_HISTORICAL_REFERENCE.md) | Signal-Refinery MVP_1 doctrine, scoring formulas, IGNORE/WATCH/VALIDATE/PAPER_TRADE classifier. |
| [docs/legacy/HISTORICAL_LIVE_INGESTION_DETAILS.md](docs/legacy/HISTORICAL_LIVE_INGESTION_DETAILS.md) | Exhaustive Phase 1 / Phase 2 / Phase D walkthroughs; Windows auto-start ceremony. |
| [scripts/_legacy_layers/README.md](scripts/_legacy_layers/README.md) | Inventory of archetype / metabolism / metaphor scripts not on the canonical workflow. |

### What is NOT in this README

* No execution claim.  No broker integration.  No auto-trade.
* No predictive-validity claim — see `docs/SCORING_STACK_VALIDATION.md`.
* No archetype / metabolism / metaphor framework — see legacy docs.

> If you came here expecting a trading bot, you are in the wrong repo.
> This is an advisory journal whose hardest-won property is that it
> **cannot place a trade**.
