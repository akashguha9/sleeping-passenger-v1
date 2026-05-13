# DEMO — 5-minute walkthrough

A scripted demo that exercises every screen in the canonical workflow.
Run from a clean repo state after the steps in `SETUP.md`.

> Total time: ~5 minutes if both services are pre-started. Add ~2 minutes for cold start.

## 0. Pre-flight (30s)

```powershell
# terminal 1
python scripts\api_server.py

# terminal 2
cd frontend; npm run dev
```

Wait for:
- backend logs `Uvicorn running on http://127.0.0.1:8000`
- frontend logs `Local: http://localhost:3000`

Verify:

```powershell
curl http://127.0.0.1:8000/health
```

Look for `"status":"ok"` and `"ai_execution_count":0`. If the call fails, fix
the backend before continuing — the dashboard will fall back to mock data and
the demo will not exercise the real path.

## 1. Open the Dashboard (45s)

Open http://localhost:3000.

Talking points:
- Top right: **ADVISORY_ONLY** and **HUMAN_ONLY** badges. These are everywhere.
- Top center: green dot + `connected — v1.0.0 · ADVISORY_ONLY · AI executions: 0`.
  - If the dot is amber and the banner says `BACKEND OFFLINE`, the dashboard
    is on mock data. Stop here, restart backend.
- Bottom right of the safety panel: `AI Executions: 0`. This number is immutable.

## 2. Verify backend health from the UI (15s)

Navigate to **Settings** (sidebar bottom).

Talking points:
- `Backend Status: Connected (v1.0.0)`.
- `Database Status` lists every table's row count. If counts are 0, the
  database is empty — that's fine for a fresh demo; we'll add a row in step 5.
- `Safety Constants` panel shows all immutable values.
- "What This System Does NOT Do" — read aloud, this is the safety story.

## 3. Review the Signal Inbox (60s)

Navigate to **Signal Inbox**.

Talking points:
- The header shows the **Fabric Bull State** badge and the **signal_source**
  (`live_events` if live ingestion has been run, `legacy_fabric` otherwise,
  `mock` if backend is offline).
- Filter pills (Action / Status / State / Sort) let you narrow the queue.
- Each signal card shows the ticker, state badge, priority score, and the
  derived **next human action** (IGNORE / HAVE_A_LOOK / WATCHLIST / HUMAN_REVIEW
  / MANUAL_CANDIDATE).
- Hover the state badge: tooltip explains MIURA / MURCIÉLAGO / AVENTADOR /
  GALLARDO / ISLERO / DIABLO / HURACÁN in plain English.

If the inbox is empty, run live ingestion in a third terminal:

```powershell
python scripts\run_live_sources_phase1.py --write
```

## 4. Inspect a Signal Detail (30s)

Click any signal card.

Talking points:
- Ticker summary on the left.
- Reflections, AI summaries, and any prior manual trades listed below.
- The `validate` button runs deterministic checks and stamps the result —
  but never authorizes execution.

## 5. Log a manual trade (45s)

Navigate to **Manual Trade Log**.

Fill the form:
- Signal Event ID: `FABRIC_DEMO` (or copy from the inbox)
- Ticker: `DEMO`
- Direction: `Long (BUY)`
- Quantity: `1`
- Price: `100`
- Leverage: `1.0` (allowed 1.0–25.0; record-only)
- Thesis: `Demo trade — record-keeping only`
- Click **Log Manual Trade**.

Talking points:
- Success card explicitly states: `No broker API was called. AI executions: 0`.
- This is **record-keeping only**. The trade has already happened outside this
  system; we're just journaling it for later reconciliation.

## 6. Reconcile the trade (30s)

Navigate to **Reconciliation**.

Find the demo trade. Click **Reconcile**.

Fill:
- Actual fill price: `101`
- Actual quantity: `1`
- Outcome status: `WIN`
- PnL estimate: `1.0`
- Notes: `Demo reconcile`

Talking points:
- Reconciliation closes the loop: signal → human decision → manual trade →
  outcome. Every step is journaled.

## 7. View the learning log (30s)

Navigate to **Moltbook** (sidebar).

Talking points:
- Moltbook is the self-correction journal. Each entry captures the mistake
  type (`late_entry`, `bad_signal_correct_rejection`, etc.), the bias
  detected, and a future rule update.
- This is the artifact that makes the journal useful over time.

Optionally add an entry referencing the demo trade.

## 8. Export and close out (30s)

Navigate to **Exports**.

Talking points:
- Every journal stream (signal inbox, reflections, manual trades, reconciliations,
  moltbook, source health) is exportable as CSV — for offline analysis or to
  paste into a spreadsheet.

Click any export link to verify it downloads.

## 9. Wrap — restate the safety posture (30s)

Open **Settings** again and walk through the "What This System Does NOT Do"
list one more time:

- No buy/sell orders on any exchange or broker
- No broker API connection
- No automated execution
- AI execution count cannot exceed 0
- No API keys / broker credentials stored
- Cannot modify execution policy or governance from this UI

That's the entire safety story. Demo over.

## What's real vs. mock during a demo

| If you see... | Then... |
|---|---|
| Green dot, non-`FABRIC_*` tickers, `signal_source=live_events` | Real local DB, real live ingestion |
| Green dot, `FABRIC_*` tickers, `signal_source=legacy_fabric` | Real local DB, legacy fabric path (no live sources run yet) |
| Amber dot, `BACKEND OFFLINE` banner, `FABRIC_*` tickers | Mock data from `frontend/src/lib/mockData.ts` — fix the backend |

## Demo failure modes (and recoveries)

| Failure | Recovery |
|---|---|
| Backend won't start: `FastAPI is not installed` | `pip install -r requirements-dev.txt` |
| Frontend stays on mock data | Verify `curl http://127.0.0.1:8000/health` returns 200; check `frontend/.env.local` |
| Signal inbox is empty | Run `python scripts\run_live_sources_phase1.py --write` |
| CORS error in browser console | Add origin to `ALLOWED_ORIGINS` in `.env`, restart backend |
| Manual trade POST returns 401 | `MVP_API_TOKEN` is set; either unset it for the demo or pass `Authorization: Bearer <token>` (see SETUP.md) |
