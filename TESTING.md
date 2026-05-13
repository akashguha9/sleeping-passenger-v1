# TESTING — what is and isn't covered

## Backend (pytest)

```powershell
python -m pytest tests -q
```

Runs ~100 test files. CI runs this on every push (`.github/workflows/pytest.yml`).

### Survival-critical coverage

These are the tests that protect the safety contract and the canonical API
surface. **Do not delete or weaken these without a written reason.**

| Area | Test file | What it pins |
|---|---|---|
| API: `/health` | `tests/test_api_server.py` | advisory stamps present, `ai_execution_count=0`, version returned |
| API: `/health` extended | `tests/test_health_extended.py` | DB availability flag, token-required flag, env tag, locked execution gate |
| API: signals (GET/POST) | `tests/test_api_server.py` | advisory stamps, 422 on missing fields |
| API: manual trades | `tests/test_api_server.py` | `broker_api_called=false`, `broker_order_id=NONE`, 422 on missing fields |
| API: reconciliation | `tests/test_api_server.py` | advisory stamps, 422 on missing fields |
| API: exports CSV | `tests/test_api_server.py` | content-type `text/csv` |
| API: AST proof | `tests/test_api_server.py` | no `/execute`, `/buy`, `/sell`, `/order`, `place_order`, etc. exist in router or function names |
| API: token gate | `tests/test_api_token_gate.py` | `MVP_API_TOKEN` unset → mutating POSTs allowed; set → require Bearer token; GETs always open |
| API: error honesty | `tests/test_api_error_honesty.py` | global handler returns sanitized JSON with explicit HTTP status |
| Persistence | `tests/test_persistence.py` | schema init, advisory stamp enforcement on writes |
| Inbox bridge | `tests/test_signal_inbox_bridge.py` | dedup, freshness window, candidate promotion |

### What is not tested

- **The frontend.** No Vitest/Jest/Playwright. The canonical click-through in
  `DEMO.md` is a manual smoke test.
- **End-to-end.** No Playwright/Cypress. See "Frontend smoke test" below for
  the manual flow.
- **Live source adapters against real APIs.** Tests mock the network. Real
  Polymarket / NewsAPI / SEC behavior is verified only by running ingestion
  manually (`python scripts\run_live_sources_phase1.py --dry-run --json`).
- **Performance.** No load tests. The system targets one user on localhost.
- **Most `scripts/*.py` engines** (archetype, narrative inertia, signal
  buoyancy, tennis/football archetypes) have unit tests but **are not wired
  to the UI/API**. See `docs/SCRIPT_INVENTORY.md` for the active vs. research
  classification.

## Frontend manual smoke test

After both services are started (see `SETUP.md`):

1. http://localhost:3000 — Dashboard loads, green dot, no `BACKEND OFFLINE` banner.
2. Click **Signal Inbox** — items render, filter pills work, sort changes order.
3. Click any signal — detail page loads, validate button returns a result.
4. Click **Manual Trade Log** — form renders, submit a tiny trade, success card appears.
5. Click **Reconciliation** — your trade is listed, reconcile succeeds.
6. Click **Moltbook** — entries render or empty-state message.
7. Click **Exports** — download `signal-inbox.csv`, opens as CSV.
8. Click **Settings** — backend status green, DB table counts render.

If any step fails, the demo isn't ready. Do not present.

## Canonical e2e flow to automate later

The single most valuable end-to-end test to write (when Playwright is wired):

```
1. Start backend with MVP_API_TOKEN unset.
2. POST a synthetic signal_event row via the persistence layer (fixture).
3. Open Dashboard → assert backend dot is green.
4. Open Signal Inbox → assert the synthetic ticker appears, status=pending.
5. Click into detail → assert advisory stamps are visible.
6. POST a reflection via the API → reload detail → assert it renders.
7. POST a decision (status=watchlist) → reload → assert status changed.
8. POST a manual trade for the same event_id.
9. Open Manual Trade Log → assert the trade card renders.
10. Reconcile the trade with outcome=WIN.
11. Open Moltbook → POST a moltbook entry.
12. Open Exports → fetch every CSV → assert non-empty body, content-type csv.
13. GET /health → assert `ai_execution_count=0`, `broker_api_called=false`,
    `execution_gate=LOCKED` everywhere they appear.
```

Each step should be a single assertion. If any single step fails, the demo
is not ready.

## Running a single test file

```powershell
python -m pytest tests\test_api_server.py -v
python -m pytest tests\test_api_token_gate.py -v
python -m pytest tests\test_api_error_honesty.py -v
```

## Adding new tests

- Backend tests live in `tests/test_*.py`.
- Use the `client` fixture pattern from `tests/test_api_server.py` for new
  API tests — it patches the persistence layer so tests don't touch disk.
- Tests that depend on env vars (`MVP_API_TOKEN`, etc.) must use `monkeypatch`
  and **must not** rely on the module-scoped `client` fixture in
  `test_api_server.py` (it's patched at module import). Put them in their own
  file with their own fixture, like `test_api_token_gate.py`.
