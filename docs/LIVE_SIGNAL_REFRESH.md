# Live Signal Refresh — Operator Guide

> Paired with:
> - `scripts/refresh_live_signals.py` — the executing orchestrator
> - `scripts/windows/run_live_signal_refresh_once.ps1` — manual one-shot wrapper
> - `scripts/windows/register_live_signal_refresh_task.ps1` — register the
>   `SleepingPassengerLiveSignalRefresh` Windows Scheduled Task
> - `scripts/live_source_registry.py` — registry of 11 source families
> - `scripts/run_live_refresh.py` — the plan-only reporter (kept for tests)
> - `docs/LIVE_SIGNALS_REFRESH_MODEL.md` — the mental model

---

## 1. What "live signals" means in this local MVP

The MVP fetches data from 11 live source families and stores normalized rows
in `runtime/mvp_local.db` (table `signal_events`). The frontend Live Signals
page reads from the backend API, which reads from this DB.

There is NO server-side background job. The frontend cannot pull from the
internet directly. Data freshness is a function of how recently the local
refresh orchestrator was invoked — manually or by the Windows scheduler.

All output is **advisory-only**. Nothing here connects to a broker, places
an order, or implies that an AI has approved anything.

---

## 2. Why the frontend does not magically fetch every 6 hours

The frontend is a Next.js client that calls the FastAPI server (`/live-signals`
and `/live-sources/status`). The FastAPI server reads pre-ingested rows from
SQLite. It does not run schedulers. It does not call external APIs on its
own. If `signal_events` is stale, the API will report stale rows — that is
expected by design.

To keep the data fresh you need ONE of:

1. The `SleepingPassengerLiveSignalRefresh` Windows Scheduled Task registered
   (recommended).
2. A manual run of the orchestrator before each session.

Both invoke the same local Python orchestrator. Neither connects to a broker.

---

## 3. Manual refresh command

```powershell
# Dry-run — adapters run in their own dry-run mode (safe).
python scripts/refresh_live_signals.py

# Actually persist signal_events rows (the cadence-scheduled mode).
python scripts/refresh_live_signals.py --write

# Subset of sources:
python scripts/refresh_live_signals.py --sources newsapi,event_registry --write

# Print what WOULD run, without invoking any adapter:
python scripts/refresh_live_signals.py --summary

# JSON output (for scripted automation):
python scripts/refresh_live_signals.py --write --json
```

Or via PowerShell wrapper (appends to `logs/live_signal_refresh.log`):

```powershell
.\scripts\windows\run_live_signal_refresh_once.ps1            # dry-run
.\scripts\windows\run_live_signal_refresh_once.ps1 -WriteMode # writes
.\scripts\windows\run_live_signal_refresh_once.ps1 -Sources "polymarket,gdelt"
```

The orchestrator:

- Calls the existing phase1 / phase2 runners — no new ingestion logic.
- Skips sources missing required credentials, never crashing the run.
- Records one row per source attempt to `live_source_refresh_runs` and a
  full summary to `logs/live_signal_refresh_summary.json`.
- Never prints secret values.
- Stamps `ADVISORY_ONLY`, `execution_gate=LOCKED`, `broker_api_called=false`,
  `can_execute=false`, `ai_execution_count=0` on every row and summary.

---

## 4. Windows scheduled task setup

```powershell
# Default: every 6 hours, --write mode, starting at 00:00 local time.
.\scripts\windows\register_live_signal_refresh_task.ps1

# Overwrite an existing task with the same name:
.\scripts\windows\register_live_signal_refresh_task.ps1 -Force

# Register a safety-test version (--dry-run mode):
.\scripts\windows\register_live_signal_refresh_task.ps1 -DryRunOnly

# Shift the cadence anchor:
.\scripts\windows\register_live_signal_refresh_task.ps1 -StartTime "03:00"
```

The task name is `SleepingPassengerLiveSignalRefresh`. To inspect / manage:

```powershell
Get-ScheduledTask -TaskName SleepingPassengerLiveSignalRefresh
Start-ScheduledTask -TaskName SleepingPassengerLiveSignalRefresh
Unregister-ScheduledTask -TaskName SleepingPassengerLiveSignalRefresh -Confirm:$false
```

The task runs under the current user and reads `.env` for API keys. There
are no secrets in the task definition itself.

If `Register-ScheduledTask` is blocked by group policy, fall back to the
classic `schtasks.exe` recipe printed in the script's NOTES section.

The task only invokes a local PowerShell wrapper which only invokes a
local Python orchestrator. No broker connection exists anywhere in this
chain.

---

## 5. Verifying `latest_fetched`

```powershell
# Quick visual: open the Live Signals page in the frontend. Stale sources
# now show a STALE badge with the refresh age.

# Or query the API directly:
curl http://localhost:8000/live-sources/status | ConvertFrom-Json

# Inspect raw DB rows (advisory-only, read-only):
python - <<'PY'
import sqlite3
from pathlib import Path

db = Path("runtime/mvp_local.db")
print("DB:", db.resolve(), "exists:", db.exists())

if db.exists():
    con = sqlite3.connect(db)
    cur = con.cursor()
    for table in ["signal_events", "source_run_log", "live_source_refresh_runs"]:
        exists = cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,)
        ).fetchone()
        if exists:
            n = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"\nTABLE {table}: {n} rows")
    con.close()
PY
```

---

## 6. Checking logs

```powershell
Get-Content .\logs\live_signal_refresh.log -Tail 80
Get-Content .\logs\live_signal_refresh_summary.json
```

The summary JSON includes the full per-source breakdown and the safety
stamps. It is overwritten on every run — to retain history, query the
`live_source_refresh_runs` table.

Sprint 10B note on encoding: `run_live_signal_refresh_once.ps1` forces
`PYTHONIOENCODING=utf-8`, sets `[Console]::OutputEncoding` to UTF-8, and
writes the log file via `Out-File -Encoding utf8`. Older log lines written
before this fix may show wide-byte artefacts ("S l e e p i n g") or
question marks where em-dashes appeared; new entries are plain UTF-8.

To inspect scheduled-task health without re-registering anything:

```powershell
Get-ScheduledTask -TaskName SleepingPassengerLiveSignalRefresh
Get-ScheduledTaskInfo -TaskName SleepingPassengerLiveSignalRefresh
.\scripts\windows\run_local_mvp_audit.ps1   # surfaces state + last_run + next_run + last_result
```

---

## 7. Required environment variables (presence only)

The orchestrator never prints the values of these — only whether they are
configured.

| Env var | Used by | Required for |
|---|---|---|
| `NEWS_API_KEY` (or `NEWSAPI_KEY`) | NewsAPI | newsapi source |
| `EVENT_REGISTRY_API_KEY` | Event Registry | event_registry source |
| `ETHERSCAN_API_KEY` | Etherscan | etherscan source |
| `XAI_API_KEY` (or `GROK_API_KEY`) | Grok/xAI | grok_xai source |
| `SEC_USER_AGENT` | SEC EDGAR | sec_edgar source |

A source whose env var is missing is **skipped** with a clear reason like
`missing_credentials: ETHERSCAN_API_KEY`. The orchestrator does not fail.

Polymarket, GDELT, Market Data, India, Global Filings (ASX), and Asia
Disclosure require no API keys.

---

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Live Signals page shows STALE badge | No recent refresh attempt recorded | Run the manual command, or register the scheduled task |
| Source skipped: `missing_credentials: X` | Env var X is unset or empty | Add to `.env` (do not commit secrets); restart any long-lived process |
| Source `rate_limited` or `http_error` | Provider rate-limited or down | Wait and re-run; reduce `--sources` to one |
| Wrong DB path | Two Python processes using different `runtime/` paths | Confirm both use the repo root; restart everything |
| Stale UI even after refresh | Frontend has cached page state | Reload the page (the orchestrator updates the DB; the frontend re-reads on the next request) |
| Scheduler not registered | Need elevated privileges or task name conflict | Re-run the register script; or use the `schtasks.exe` fallback printed in the script's NOTES |

---

## 9. Safety

This refresh path is **advisory-only**:

- Every persisted row carries `advisory_status=ADVISORY_ONLY`,
  `execution_gate=LOCKED`, `broker_api_called=false`, `can_execute=false`,
  `ai_execution_count=0`.
- The orchestrator never calls a broker, never places an order, and never
  unlocks the execution gate.
- The Live Signals page continues to display the
  `ADVISORY_ONLY / HUMAN_REVIEW_REQUIRED / execution_gate=LOCKED` copy.
- The 6-hour scheduled task only runs a local Python script. Any change
  that ever needed to relax that property would be a much larger change
  than this sprint and must be reviewed separately.

Refreshing data does **not** authorize a trade. The system never trades.
