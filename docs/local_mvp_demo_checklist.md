# Local MVP Demo Checklist

> **Advisory-only. No trades placed. No broker connection. No execution path.**

Use this checklist to verify the full local MVP before a demo or handoff.

---

## Pre-flight

- [ ] Python 3.11+ available: `python --version`
- [ ] Node.js 18+ available: `node --version`
- [ ] Dependencies installed: `pip install fastapi uvicorn requests`
- [ ] Frontend dependencies installed: `cd frontend && npm install`
- [ ] DB reset (clean slate): `Remove-Item runtime\mvp_local.db -ErrorAction SilentlyContinue`

---

## Smoke test

- [ ] Compile-check passes: `python -m compileall scripts tests`
- [ ] Smoke test passes (offline): `python scripts/local_mvp_smoke_test.py --skip-live-source`
- [ ] Full test suite passes: `python -m pytest tests -q`
- [ ] Smoke test JSON report looks clean: `python scripts/local_mvp_smoke_test.py --json`

---

## Backend

- [ ] FastAPI server starts: `uvicorn scripts.api_server:app --reload`
- [ ] `/docs` responds at `http://localhost:8000/docs`
- [ ] `/db/status` returns `advisory_status: ADVISORY_ONLY`
- [ ] `/db/status` returns `ai_execution_count: 0`
- [ ] `/db/status` returns `broker_api_called: false`

---

## Phase 1 live source ingestion

- [ ] Dry-run completes without crashing: `python scripts/run_live_sources_phase1.py --dry-run --json`
- [ ] Dry-run report shows `total_persisted: 0`
- [ ] Write run persists events: `python scripts/run_live_sources_phase1.py --write`
- [ ] `/live-signals` endpoint returns events with `execution_gate: LOCKED`

---

## Frontend

- [ ] Dashboard loads at `http://localhost:3000`
- [ ] No "Buy", "Sell", "Execute", or "Auto-trade" button visible anywhere
- [ ] ADVISORY_ONLY banner is visible
- [ ] `EXECUTION_GATE: LOCKED` shown in header
- [ ] `ai_execution_count: 0` displayed
- [ ] Live Signals page loads at `http://localhost:3000/live-signals`
- [ ] Signal Inbox loads at `http://localhost:3000/signal-inbox`
- [ ] Manual Trade Log loads at `http://localhost:3000/manual-trade-log`
- [ ] Reflection Desk loads at `http://localhost:3000/reflection-desk`
- [ ] Moltbook loads at `http://localhost:3000/moltbook`
- [ ] Reconciliation loads at `http://localhost:3000/reconciliation`
- [ ] Exports page loads at `http://localhost:3000/exports`
- [ ] Settings page shows safety constants at `http://localhost:3000/settings`

---

## Safety invariant verification

Run each check and confirm output:

```powershell
# All records carry advisory stamps
python -m pytest tests/test_persistence.py -v

# No forbidden execution functions in source files
python -m pytest tests/test_local_mvp_smoke_test.py::test_no_forbidden_functions_in_persistence -v
python -m pytest tests/test_local_mvp_smoke_test.py::test_no_forbidden_functions_in_live_source_runner -v

# ai_execution_count is always 0
python -m pytest tests/test_local_mvp_smoke_test.py::test_ai_execution_count_always_zero_all_tables -v

# broker_api_called is always False
python -m pytest tests/test_local_mvp_smoke_test.py::test_broker_api_called_always_false -v
```

---

## Frontend production build

```powershell
cd frontend
npm run build
```

- [ ] Build completes with no errors
- [ ] No TypeScript errors reported

---

## Final readiness statement

| Item | Status |
|---|---|
| SQLite DB initializes cleanly | |
| All persistence tables exist | |
| advisory_status = ADVISORY_ONLY on all records | |
| ai_execution_count = 0 always | |
| broker_api_called = False always | |
| broker_order_id = NONE always | |
| execution_gate = LOCKED on all signal events | |
| No forbidden execution functions in codebase | |
| Phase 1 runner works in dry-run mode | |
| Frontend loads with no buy/sell/execute UI | |
| Full test suite passes | |
| Frontend build passes | |

**When all rows above are checked: MVP is advisory-only and demo-ready.**
