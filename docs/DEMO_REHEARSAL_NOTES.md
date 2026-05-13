# DEMO_REHEARSAL_NOTES — practical pre-demo checklist

> Not fluff. A working checklist to walk through before showing the MVP
> to anyone, including yourself two weeks from now.
>
> Rehearsal status of THIS doc: **code/test validation only**. The full
> stack (backend + frontend) was not run end-to-end during the Day 1-10
> sprint that produced this file -- tests, compose-config, and lint were
> the validation surface. The first operator who runs the steps below
> should annotate this file with any discrepancies.

## Pre-flight

- Date of rehearsal: _fill in_
- Current branch: `main` (confirm with `git branch --show-current`)
- Recent commits expected to be present:
  - `chore: harden MVP backup deployment smoke and persistence floor`
  - `fix: raise MVP safety setup and demo readiness floor`
- Clean working tree (or known-uncommitted changes documented below).

## Start the stack

```powershell
# Terminal 1 -- backend
python scripts\api_server.py

# Terminal 2 -- frontend
cd frontend
npm run dev
```

Wait for:
- `Uvicorn running on http://127.0.0.1:8000`
- `Local: http://localhost:3000`

## Smoke check (mandatory before continuing)

```powershell
python scripts\smoke_check.py --api http://127.0.0.1:8000
```

Expected last line: `RESULT: PASS`. If it says `FAIL`, fix the cause
before the dashboard work. The script exits non-zero so you can chain it.

## Expected backend `/health` fields

| Field | Expected value |
|---|---|
| `status` | `"ok"` |
| `advisory_status` | `"ADVISORY_ONLY"` |
| `execution_mode` | `"HUMAN_ONLY"` |
| `execution_gate` | `"LOCKED"` |
| `ai_execution_count` | `0` |
| `broker_api_called` | `false` |
| `broker_order_id` | `"NONE"` |
| `human_review_required` | `true` |
| `db_available` | `true` (false ⇒ DB missing on disk, demo will look empty) |
| `db_path` | repo-relative string, never an absolute path |
| `environment` | `"local"` (or `"docker"` under compose) |
| `api_token_required` | `false` unless `MVP_API_TOKEN` is set |

If any of `advisory_status`, `execution_gate`, `broker_api_called`,
`ai_execution_count` deviates, **STOP THE DEMO**. The safety contract has
been violated.

## Expected dashboard state

- Top bar: green dot, `connected — v1.0.0 · ADVISORY_ONLY · AI executions: 0`.
- No `BACKEND OFFLINE` amber banner.
- No `MOCK_FALLBACK` amber banner on Signal Inbox.
- Tickers in the inbox: real ingested tickers (post `run_live_sources_phase1.py`)
  OR `FABRIC_*` if only the legacy fabric path has run. **`FABRIC_*` tickers
  do not mean mock**; they mean legacy fabric. The truth signal is the banner.

### Mock fallback behaviour (intentional)

If the frontend can't reach the backend it falls back to
`frontend/src/lib/mockData.ts` and shows the `BACKEND OFFLINE` banner.
The Signal Inbox additionally shows `MOCK_FALLBACK`. The backend itself
never returns mock data — it returns the persistence-truth flags:

```json
{
  "truth_source": "sqlite" | "legacy_fabric" | "jsonl_fallback",
  "fallback_used": false | true,
  "canonical":     true | false
}
```

If `truth_source != "sqlite"` you are not showing canonical data, even if
the dashboard otherwise looks healthy.

## Token behaviour

- `MVP_API_TOKEN` unset (default): GETs and POSTs both work without auth.
- `MVP_API_TOKEN=<anything>`: POSTs require `Authorization: Bearer <token>`;
  a missing/incorrect token returns 401, not 500.
- The token gate is verified by `tests/test_api_token_gate.py`. Don't
  hand-test it before a demo; trust the suite.

## Canonical demo walkthrough

Follow `DEMO.md` step-by-step. The 9 sections cover dashboard → inbox →
detail → manual trade → reconciliation → moltbook → exports → wrap.

## Known demo risks

| Risk | Mitigation |
|---|---|
| `runtime/mvp_local.db` deleted before demo | Restore with `python scripts\restore_db.py --backup-file <latest>.db --yes` |
| Signal inbox empty | Run `python scripts\run_live_sources_phase1.py --write` in a third terminal |
| Frontend on mock data | Smoke check would have caught this; re-run it |
| CORS error in browser console | Add the origin to `ALLOWED_ORIGINS` in `.env`, restart backend |
| Backend takes 30+ seconds to start | Cold start with empty caches; pre-warm before audience joins |
| Manual trade POST returns 401 | `MVP_API_TOKEN` is set; either unset for the demo or include the Bearer header |
| Window scaling on Windows pytest tempdir | Cosmetic only; affects test cleanup, not test results |

## Recovery playbook (mid-demo)

1. **Backend died.** Restart it in Terminal 1. `python scripts\smoke_check.py`
   to confirm it's back. The frontend reconnects automatically within ~5s.
2. **Frontend died.** `cd frontend; npm run dev`. Browser refresh.
3. **Bad data showed up.** Note the page + the `truth_source` if visible.
   Do not pretend; say "this is fallback data, not canonical state."
4. **Trade was logged accidentally.** It's record-only; no broker call
   happened (the safety contract guarantees this). It can stay in the
   journal as a demo artifact or be ignored.
5. **DB corruption suspected.** Stop the backend. Restore from the most
   recent backup: `python scripts\restore_db.py --backup-file <path> --yes`.
   The restore script will automatically save a pre-restore copy.

## Open issues / known limitations to disclose

- No real multi-user auth. The token gate is single-shared-secret.
- SQLite, not Postgres. Single-writer.
- No frontend unit/e2e suite yet (see `docs/E2E_TEST_PLAN.md`). The
  frontend safety is manual + Next.js lint.
- Live source ingestion depends on external APIs; some may rate-limit.
- Docker scaffold exists but is local-demo-grade, not production.
- No automated backup; backup must be triggered manually.

If anyone asks "is this production-ready?": answer is **no**. It is a
local advisory journal. The DEPLOYMENT.md "Acceptance criteria for
deployable" list is the truthful one.

## Post-demo cleanup

```powershell
# take a fresh backup so today's journal entries are durable
python scripts\backup_db.py --label postdemo
```

That's it. Don't delete `runtime/`.
