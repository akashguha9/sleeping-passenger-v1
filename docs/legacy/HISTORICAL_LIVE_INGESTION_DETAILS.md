# Historical Live Ingestion Details (legacy)

> **Preserved for reference.**  The exhaustive Phase 1 / Phase 2 ingestion
> walkthroughs, Phase D chart-structure API examples, and the Windows
> auto-start ceremony were originally part of the top-level README.  The
> canonical content now lives in:
>
> * `docs/LIVE_SIGNALS_REFRESH_MODEL.md` — refresh model & cadence.
> * `docs/LIVE_SIGNALS_SCHEDULING.md` — Windows / cron scheduling.
> * `docs/LIVE_REFRESH_WATCHDOG.md` — watchdog state taxonomy.
> * `scripts/first_run_seed_free_sources.py` — one-command first run.
> * `docs/SCORING_STACK_VALIDATION.md` — score validation posture.
>
> The advisory-only safety contract still applies to every example:
> `advisory_status="ADVISORY_ONLY"`, `execution_gate="LOCKED"`,
> `broker_api_called=false`, `ai_execution_count=0`.

---

```

### Advisory safety rules (never change)

- `advisory_status = "ADVISORY_ONLY"` on every record
- `execution_mode = "HUMAN_ONLY"` on every trade record
- `ai_execution_count = 0` always
- `broker_api_called = False` always
- `broker_order_id = "NONE"` always (unless human-entered external reference)
- No buy/sell/execute endpoint exists. No broker API. No order placement.

## Offline-First Notes

- The verified path runs fully local.
- Do not treat placeholder adapters as live integrations.
- Keep external contact bounded and explicit if real data or execution is added later.

## Frontend — Signal Intelligence Cockpit

A Next.js frontend scaffold lives in `frontend/`. It is an advisory-only intelligence dashboard — no broker connection, no execution UI, no API keys.

### Requirements

- Node.js 18+ and npm

### Install and run

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000` in your browser.

### Build for production

```powershell
cd frontend
npm run build
npm run start
```

### Pages

| Route | Description |
|---|---|
| `/` | Dashboard — fabric state, status breakdown, top signals |
| `/signal-inbox` | Filterable signal list with state badges |
| `/signal-inbox/[id]` | Signal detail, score panel, evidence timeline, reflection |
| `/reflection-desk` | Human reflections and AI advisory context per signal |
| `/moltbook` | Self-correction and mistake-learning entries |
| `/manual-trade-log` | Record trades placed manually (HUMAN_ONLY) |
| `/reconciliation` | Match logged trades to actual outcomes |
| `/exports` | Download JSON/CSV exports of all advisory data |
| `/settings` | System constants and safety information |

### Safety rules enforced in the UI

- No Buy, Sell, Execute, or Auto-trade buttons exist anywhere in the UI.
- All trade actions are labelled **Log Manual Trade**.
- All signal actions carry **ADVISORY_ONLY** and **HUMAN_REVIEW_REQUIRED**.
- All trade-related UI carries **HUMAN_ONLY**.
- AI execution count displays `0` on every page and in every response shape.
- A persistent top banner states: **"This system does not place trades."**
- `EXECUTION_GATE: LOCKED` is shown in the header on every page.

### Data

Step 1 uses mock data in `frontend/src/lib/mockData.ts` that mirrors the FastAPI response shapes from `scripts/signal_inbox_api.py` and `scripts/moltbook_api.py`. Live backend connection is Step 2.

---

## Serious Local MVP Runbook

> **This MVP is advisory-only. It does not place trades. It has no broker execution path.**
>
> `advisory_status = ADVISORY_ONLY` | `execution_mode = HUMAN_ONLY` | `ai_execution_count = 0` | `broker_api_called = False`

### Prerequisites

```powershell
python -m pip install fastapi uvicorn requests
cd frontend
npm install
cd ..
```

### Start the full local stack

Open **three separate terminals** in the repo root.

**Terminal 1 — FastAPI advisory server**

```powershell
python -m uvicorn scripts.api_server:app --reload
# Server starts at http://localhost:8000
# Docs: http://localhost:8000/docs
```

**Terminal 2 — Next.js frontend**

```powershell
cd frontend
npm run dev -- -p 3000
# Dashboard at http://localhost:3000
# Note: port 3000 is required -- the sleepingpassenger proxy forwards port 80 -> 3000.
# If port 3000 is busy, stop the existing Next.js process first.
```

**Terminal 3 — Phase 1 live source ingestion**

```powershell
# Dry-run first (fetch only — no DB write):
python scripts/run_live_sources_phase1.py --dry-run --json

# Write run (fetch and persist to SQLite):
python scripts/run_live_sources_phase1.py --write
```

**Terminal 4 — Phase 2 live source ingestion (NewsAPI)**

Requires `NEWS_API_KEY` environment variable. Skips cleanly if unset.

```powershell
# Dry-run — fetch and normalize, no DB write:
python scripts/run_live_sources_phase2.py --source newsapi --dry-run --json

# Write run — fetch, normalize, and persist to SQLite:
python scripts/run_live_sources_phase2.py --source newsapi --write

# Custom query:
python scripts/run_live_sources_phase2.py --source newsapi --dry-run --query "AI semiconductors"
```

All NewsAPI signals are `ADVISORY_ONLY`, `HUMAN_REVIEW_REQUIRED`, `execution_gate=LOCKED`,
`ai_execution_count=0`, `broker_api_called=false`.

### Browser

| URL | Description |
|---|---|
| `http://localhost:3000` | Dashboard — fabric state, status breakdown, top signals |
| `http://localhost:3000/live-signals` | Live signal events from Phase 1 + Phase 2 sources |
| `http://localhost:3000/signal-inbox` | Filterable signal inbox |
| `http://localhost:3000/reflection-desk` | Human reflections and AI advisory context |
| `http://localhost:3000/manual-trade-log` | Record trades placed manually (HUMAN_ONLY) |
| `http://localhost:3000/moltbook` | Mistake-learning entries |
| `http://localhost:3000/reconciliation` | Match logged trades to actual outcomes |
| `http://localhost:3000/exports` | Download JSON/CSV exports |

### Run the smoke test

```powershell
# Quick local verification (mocks Phase 1 runner):
python scripts/local_mvp_smoke_test.py --skip-live-source

# Full check including Phase 1 dry-run (requires internet for Polymarket / GDELT):
python scripts/local_mvp_smoke_test.py

# JSON report:
python scripts/local_mvp_smoke_test.py --json
```

### Run the full test suite

```powershell
python -m pytest tests -q
python -m pytest tests/test_local_mvp_smoke_test.py -v
python -m pytest tests/test_persistence.py -v
```

### Compile-check all scripts and tests

```powershell
python -m compileall scripts tests
```

### Reset the local DB

```powershell
# Wipe the SQLite DB — auto-recreated on next API call or source run
Remove-Item runtime\mvp_local.db -ErrorAction SilentlyContinue
```

### Phase C Integrated Source Matrix

All sources are `execution_permission = ADVISORY_ONLY`. No auto-trading path exists for any source.

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
| `asia_disclosure` | 2 | — (all placeholder) | All skip cleanly | `run_live_sources_phase2.py --source asia_disclosure --dry-run --json` | `--write` | Asia Disclosure | signal_events / source_run_log |

All 11 sources set `advisory_status = ADVISORY_ONLY`, `execution_gate = LOCKED`,
`human_review_required = True`, `ai_execution_count = 0`, and `broker_api_called = False` on
every normalized record. `broker_order_id = NONE` on global_filings and asia_disclosure records.

Run the static integration audit at any time:

```powershell
python scripts/phase_c_final_audit.py --verbose
```

### Advisory safety rules (permanent — never change)

- No Buy, Sell, Execute, or Auto-trade button or endpoint exists anywhere.
- `execution_mode = HUMAN_ONLY` on every trade record.
- `advisory_status = ADVISORY_ONLY` on every record.
- `ai_execution_count = 0` always.
- `broker_api_called = False` always.
- `broker_order_id = NONE` always.
- `execution_gate = LOCKED` on every signal event.
- No `.env` contains broker credentials. No broker API is imported.

## Local Auto-Start, 5-Minute Refresh, and sleepingpassenger URL

These Windows helper scripts auto-start the full local advisory MVP stack at logon, refresh live signals every 5 minutes, and serve the frontend at `http://sleepingpassenger`.

**Local-only setup.** This uses a Windows hosts-file alias pointing `sleepingpassenger` at `127.0.0.1`. It does not configure public DNS, cloud hosting, or internet access.

### One-time setup

**1. Add local host aliases (requires Administrator):**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\add_sleepingpassenger_host_alias.ps1
```

Adds to `C:\Windows\System32\drivers\etc\hosts`:

```
127.0.0.1 sleepingpassenger
127.0.0.1 sleepingpassenger.local
```

**2. Register startup task (runs at logon):**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\register_mvp_startup_task.ps1
```

Registers Windows Scheduled Task `PipelineV57LocalMVP` to launch `start_mvp_stack.ps1` at user logon with highest privileges (required for the port-80 proxy).

### Manual run

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\start_mvp_stack.ps1
```

Opens four separate PowerShell windows:

| Window | Command | URL |
|---|---|---|
| Backend | `python -m uvicorn scripts.api_server:app --reload` | `http://localhost:8000` |
| Frontend | `npm run dev -- -p 3000` (in `frontend/`, port pinned) | `http://localhost:3000` |
| Poller | `poll_live_sources.ps1` | runs every 300 s |
| Proxy | `start_sleepingpassenger_proxy.ps1` | port 80 → port 3000 |

### URLs

| URL | Notes |
|---|---|
| `http://sleepingpassenger` | Requires host alias + port-80 proxy (Administrator) |
| `http://sleepingpassenger.local` | Requires host alias + port-80 proxy (Administrator) |
| `http://localhost:3000` | Direct frontend — always available, no proxy needed |
| `http://localhost:8000` | Backend API |
| `http://localhost:8000/docs` | API docs (Swagger UI) |

Backend remains `http://localhost:8000` in all cases.

### Stop / unregister

```powershell
# Unregister the startup task:
powershell -ExecutionPolicy Bypass -File scripts\windows\unregister_mvp_startup_task.ps1

# Remove host aliases (requires Administrator):
powershell -ExecutionPolicy Bypass -File scripts\windows\remove_sleepingpassenger_host_alias.ps1
```

### Logs

All logs write to `runtime/logs/` (gitignored):

| File | Content |
|---|---|
| `runtime/logs/live_source_poller.log` | Timestamped poller runs (polymarket, gdelt, market_data) |
| `runtime/logs/sleepingpassenger_proxy.log` | Reverse proxy activity and errors |

### Port 80 and Administrator privileges

The reverse proxy (`local_frontend_reverse_proxy.py`) binds port 80 so the frontend is reachable at `http://sleepingpassenger` without a port number. On Windows, port 80 requires Administrator or a `netsh` port-sharing rule. If the proxy cannot bind, it prints a clear message and you can use `http://localhost:3000` instead.

The startup task runs with highest privileges so the proxy can bind port 80 at logon.

### Scripts added

| Script | Purpose |
|---|---|
| `scripts/windows/start_mvp_stack.ps1` | Launch all four processes |
| `scripts/windows/poll_live_sources.ps1` | 300-second advisory signal poller |
| `scripts/windows/register_mvp_startup_task.ps1` | Register logon auto-start task |
| `scripts/windows/unregister_mvp_startup_task.ps1` | Remove logon auto-start task |
| `scripts/windows/add_sleepingpassenger_host_alias.ps1` | Add hosts-file aliases |
| `scripts/windows/remove_sleepingpassenger_host_alias.ps1` | Remove hosts-file aliases |
| `scripts/windows/start_sleepingpassenger_proxy.ps1` | Start port-80 reverse proxy |
| `scripts/windows/local_frontend_reverse_proxy.py` | Python HTTP reverse proxy (stdlib only) |

### Safety invariant

The poller runs only these advisory/read-only commands — no broker API, no order placement:

```powershell
python scripts\run_live_sources_phase1.py --source polymarket --write
python scripts\run_live_sources_phase1.py --source gdelt --write
python scripts\run_live_sources_phase2.py --source market_data --write
python scripts\update_ohlcv_latest.py --symbols AAPL,GLD,TLT,BTC-USD,SPY --interval 1d --lookback-days 10 --write
```

`advisory_status = ADVISORY_ONLY` on every ingested record.

---

## Phase E.3 — Real OHLCV History + Incremental Candle Updater

### OHLCV data modes

| Mode | Script | Data | Use |
|---|---|---|---|
| Demo seed (offline) | `scripts/seed_chart_ohlcv_history.py` | **Synthetic, NOT real market prices** | UI demo without internet |
| Real historical backfill | `scripts/backfill_ohlcv_history.py` | Real OHLCV via yfinance (free) | Full history for chart analysis |
| Incremental refresh | `scripts/update_ohlcv_latest.py` | Real recent candles via yfinance | 5-minute poller, keeps DB current |

> **Important:** `seed_chart_ohlcv_history.py` creates deterministic **synthetic** sample candles
> generated with a random number generator. They are **not real market prices** and must not be
> used for analysis or decision-making. Use `backfill_ohlcv_history.py` for real data.

### Commands

**Demo-only seed (synthetic, no internet required):**

```bash
python scripts/seed_chart_ohlcv_history.py --write
```

**Real historical backfill (requires yfinance + internet):**

```bash
# Install dependency if needed:
python -m pip install yfinance

# Backfill full history (may fetch several years per symbol):
python scripts/backfill_ohlcv_history.py --symbols AAPL,GLD,TLT,BTC-USD,SPY --period max --interval 1d --write

# Dry-run (prints JSON, no DB write):
python scripts/backfill_ohlcv_history.py --symbols AAPL,GLD,TLT,BTC-USD,SPY --period max --interval 1d
```

**Incremental update (safe to run every 5 minutes):**

```bash
python scripts/update_ohlcv_latest.py --symbols AAPL,GLD,TLT,BTC-USD,SPY --interval 1d --lookback-days 10 --write
```

**Start full local stack:**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\start_mvp_stack.ps1
```

### Chart Structure data preference

The `/chart-structure` API endpoint:
1. Queries candles for the requested symbol directly (symbol-filtered DB query — no per-symbol cap)
2. Prefers **real backfill** candles (`ohlcv_*` event IDs) over demo seed (`seed_ohlcv_*`) for the same date
3. Returns up to `limit` (default 100) candles in chronological order
4. Falls back to seed candles for dates not covered by real data

### Event ID scheme

| Source | Event ID format | Example |
|---|---|---|
| Demo seed | `seed_ohlcv_{symbol}_{YYYY-MM-DD}` | `seed_ohlcv_aapl_2024-01-15` |
| Real backfill / incremental | `ohlcv_{symbol}_{interval}_{YYYY-MM-DD}` | `ohlcv_aapl_1d_2024-01-15` |

Both use `INSERT OR IGNORE` — re-running either script is fully idempotent.

### Dependency

yfinance is required for real data. The seed script has no external dependencies.

```bash
python -m pip install yfinance
```

### Safety invariant (unchanged)

All OHLCV records carry:

```
advisory_status    = ADVISORY_ONLY
execution_gate     = LOCKED
human_review_required = True
ai_execution_count = 0
broker_api_called  = False
broker_order_id    = NONE
```

No broker API is called. No orders are placed. No private keys are used.

---

## Phase E.5 — Silent local startup

Starts the full MVP stack in the background with no visible PowerShell windows.
All output is redirected to `runtime\logs\`.

### Scripts

| Script | Purpose |
|---|---|
| `scripts\windows\start_mvp_stack_silent.ps1` | Start backend, frontend, poller, proxy silently |
| `scripts\windows\stop_mvp_stack_silent.ps1` | Stop all MVP stack processes by command-line pattern |
| `scripts\windows\register_mvp_silent_startup_task.ps1` | Register Windows Scheduled Task at logon |
| `scripts\windows\unregister_mvp_silent_startup_task.ps1` | Remove the scheduled task |

### One-time setup

```powershell
# 1. Add sleepingpassenger host alias (run as Administrator, once):
powershell -ExecutionPolicy Bypass -File scripts\windows\add_sleepingpassenger_host_alias.ps1

# 2. Register silent auto-start task (run as Administrator for port 80):
powershell -ExecutionPolicy Bypass -File scripts\windows\register_mvp_silent_startup_task.ps1
```

### Manual start / stop

```powershell
# Start silently (idempotent — skips components already running):
powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File scripts\windows\start_mvp_stack_silent.ps1

# Stop all MVP stack processes:
powershell -ExecutionPolicy Bypass -File scripts\windows\stop_mvp_stack_silent.ps1
```

### After startup

| URL | Notes |
|---|---|
| `http://sleepingpassenger` | Requires host alias + port-80 proxy (Administrator) |
| `http://localhost:3000` | Frontend direct |
| `http://localhost:8000/health` | Backend health check |

### Logs

All logs are written to `runtime\logs\`:

| File | Content |
|---|---|
| `silent_startup.log` | Startup progress and port-ready timestamps |
| `silent_stop.log` | Process stop events |
| `backend_stdout.log` / `backend_stderr.log` | uvicorn output |
| `frontend_stdout.log` / `frontend_stderr.log` | Next.js dev server output |
| `poller_stdout.log` / `poller_stderr.log` | poll_live_sources.ps1 output |
| `proxy_stdout.log` / `proxy_stderr.log` | sleepingpassenger proxy output |

### Safety invariant (unchanged)

Advisory only. No broker API is called. No orders are placed.

---

## Run local frontend as http://sleepingpassenger/

Simpler alternative to the reverse-proxy path above: bind Next.js dev server directly
to port 80 so `http://sleepingpassenger/` works without a separate proxy process.

Backend is unchanged — FastAPI continues to serve on `http://127.0.0.1:8000`. The
frontend reads it from `NEXT_PUBLIC_API_BASE_URL` in `frontend/.env.local`.

### One-time hosts entry (Administrator PowerShell)

```powershell
Add-Content -Path "C:\Windows\System32\drivers\etc\hosts" -Value "`n127.0.0.1 sleepingpassenger"
ipconfig /flushdns
ping sleepingpassenger
```

### Start the backend (regular PowerShell)

```powershell
cd C:\Users\akash\sleeping-passenger-v1
python -m uvicorn scripts.api_server:app --host 127.0.0.1 --port 8000 --reload
```

### Start the frontend on port 80 (Administrator PowerShell)

Port 80 binding on Windows requires Administrator. Use either:

```powershell
cd C:\Users\akash\sleeping-passenger-v1\frontend
npm run dev:sleepingpassenger
```

Or the preflight helper (checks hosts entry and port 80 availability first):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\start_sleepingpassenger_local.ps1
```

Then open:

```
http://sleepingpassenger/
```

### Verify

```powershell
ping sleepingpassenger
netstat -ano | findstr ":80"
```

### Fallback if port 80 is blocked

If Administrator is unavailable, port 80 is held by IIS/Skype/another service, or
the bind otherwise fails, use the standard dev script:

```powershell
cd C:\Users\akash\sleeping-passenger-v1\frontend
npm run dev
# open http://localhost:3000
```

The existing reverse-proxy path (`scripts\windows\start_sleepingpassenger_proxy.ps1`)
is also still available — it runs Next.js on 3000 and proxies 80 → 3000.
