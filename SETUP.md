# SETUP — sleeping-passenger-v1

A short, practical setup guide. PowerShell-first because the project targets Windows.

## What this is

A **local, single-user advisory signal journal**. It pulls public-data signals
(Polymarket, GDELT, SEC EDGAR, NewsAPI, Etherscan, Yahoo OHLCV, Grok/xAI) into
a SQLite store, surfaces them in a Next.js dashboard, and lets a human reflect,
log a manual trade, and reconcile outcomes.

## What this is NOT

- Not a broker. No order routing. No execution.
- Not multi-tenant. There is no auth, no user accounts.
- Not a hosted product. It binds to loopback by default.
- Not a recommendation engine. Every signal is advisory only; the human decides.

The advisory contract is enforced everywhere:
`advisory_status=ADVISORY_ONLY`, `execution_mode=HUMAN_ONLY`,
`execution_gate=LOCKED`, `broker_api_called=false`, `ai_execution_count=0`.

## Prerequisites

- Windows 10/11 with PowerShell 5+ (or PowerShell 7).
- Python 3.11+ (CI uses 3.13).
- Node.js 18+ and npm.
- ~500 MB free disk for `runtime/`, `logs/`, and the dashboard build.

Optional (only needed if you want live data — placeholders work fine without):
- Free API keys for any of: NewsAPI, Event Registry, xAI/Grok, Etherscan.
- SEC EDGAR requires a `User-Agent` header — set `SEC_USER_AGENT="Name email@example.com"`.

## Backend setup

```powershell
# from repo root
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r requirements-dev.txt   # adds fastapi/uvicorn/pydantic/httpx for the API
```

Copy the example env if you want to override defaults:

```powershell
Copy-Item .env.example .env
# then edit .env to taste — see "Env vars" below
```

## Frontend setup

```powershell
cd frontend
npm install
Copy-Item .env.example .env.local      # only if you need to point at a non-default backend
cd ..
```

## Env vars

The backend reads a small set of env vars. All have safe defaults — nothing
below is required.

| Var | Default | Purpose |
|---|---|---|
| `API_HOST` | `127.0.0.1` | uvicorn bind host. Set `0.0.0.0` inside containers. |
| `API_PORT` | `8000` | uvicorn bind port. |
| `ALLOWED_ORIGINS` | localhost:3000,127.0.0.1:3000,sleepingpassenger,sleepingpassenger.local | CORS allowlist (comma-separated). |
| `MVP_API_TOKEN` | _(unset)_ | If set, mutating POST routes require `Authorization: Bearer <token>`. Unset = permissive local mode. |
| `MVP_DB_PATH` | `runtime/mvp_local.db` | SQLite location. |
| `MVP_ENVIRONMENT` | `local` | Tag for `/health`. |
| `PIPELINE_ENABLE_PAPER_EXECUTION` | `false` | Leave false unless you know what you're doing. |
| `PIPELINE_ENABLE_LIVE_EXECUTION` | `false` | **Do not enable** — the repo refuses live execution by design. |

The frontend uses:

| Var | Default | Purpose |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | Backend URL the dashboard fetches from. |

Optional live source keys (skip cleanly when missing): `NEWS_API_KEY`,
`EVENT_REGISTRY_API_KEY`, `XAI_API_KEY`, `ETHERSCAN_API_KEY`, `SEC_USER_AGENT`.
See `configs/api_keys.example.env` for the full list.

## Start the backend

```powershell
python scripts\api_server.py
# or, with auto-reload:
python -m uvicorn scripts.api_server:app --reload --host 127.0.0.1 --port 8000
```

## Start the frontend

```powershell
cd frontend
npm run dev
```

Open http://localhost:3000.

## Verify health

```powershell
curl http://127.0.0.1:8000/health
```

Expected: `{"status":"ok","advisory_status":"ADVISORY_ONLY","execution_mode":"HUMAN_ONLY","ai_execution_count":0,...}`.

The dashboard's top bar also shows backend status as a green dot.

## Run tests

```powershell
python -m pytest tests -q
```

## Stop services

- Backend: `Ctrl+C` in its terminal.
- Frontend: `Ctrl+C` in its terminal.
- No background daemons or system services are installed.

## "BACKEND OFFLINE" and "MOCK_FALLBACK" — what they mean

The frontend has explicit honesty about whether it's showing real data:

- **BACKEND OFFLINE** (amber banner): the dashboard could not reach `NEXT_PUBLIC_API_BASE_URL`. It is showing mock seed data from `frontend/src/lib/mockData.ts`. Start the backend.
- **MOCK_FALLBACK** (amber banner on Signal Inbox): same thing, scoped to the inbox. Tickers like `FABRIC_BTC` / `FABRIC_ETH` are not real signals.
- **No banner + green dot + non-mock tickers**: the backend is alive and you are looking at the real local database.

This is by design. Never silently lie about whether data is real.

## Common failure fixes

| Symptom | Cause | Fix |
|---|---|---|
| `FastAPI is not installed` on backend start | `requirements-dev.txt` not installed | `pip install -r requirements-dev.txt` |
| `ModuleNotFoundError: scripts.x` from a test | running from inside `tests/` instead of repo root | `cd <repo-root>; python -m pytest tests -q` |
| Dashboard stays on mock data | backend not running, wrong port, or `NEXT_PUBLIC_API_BASE_URL` mismatch | confirm `curl /health` works; restart `next dev` after changing `.env.local` |
| `CORS error` in browser console | origin not in `ALLOWED_ORIGINS` | add it to `.env` and restart backend |
| SQLite `database is locked` | another process opened `runtime/mvp_local.db` | close it, or set `MVP_DB_PATH` to a fresh path |
| SEC EDGAR returns 403 | missing `SEC_USER_AGENT` | `$env:SEC_USER_AGENT = "Your Name your@email"` |

See also: **DEMO.md** for the 5-minute demo script, **TESTING.md** for what is and isn't tested, **DEPLOYMENT.md** for the path to production.
