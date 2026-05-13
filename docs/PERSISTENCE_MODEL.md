# PERSISTENCE_MODEL — what is canonical, what is fallback, what is mock

> One rule, repeated: **SQLite is canonical. JSONL is an audit/event trace.
> Mock data is a UI-only degraded demo state and must never be presented
> as live truth.**

## The three storage layers

| Layer | Location | Role | Canonical? |
|---|---|---|---|
| SQLite | `runtime/mvp_local.db` (default; override via `MVP_DB_PATH`) | Application state — every journaled decision, reflection, manual trade, reconciliation, moltbook entry | **YES** |
| JSONL | `runtime/logs/*.jsonl` (e.g. `user_reflections.jsonl`, `manual_trade_log.jsonl`, `signal_inbox_states.jsonl`) | Append-only event/audit trace + read-side fallback when SQLite is unavailable | NO — audit only |
| Mock | `frontend/src/lib/mockData.ts` | UI-only static seed used when the backend is unreachable | NO — must always render a visible banner |

## Why split this hair

JSONL writes happen alongside SQLite writes today (so the audit trail
survives a corrupt DB), and the read paths fall back to JSONL when SQLite
isn't there. That fallback is convenient but dangerous: without explicit
metadata, callers can't tell whether the data they're seeing is canonical
SQLite state or a stale JSONL slice. This doc defines the contract.

## Canonical model

For the journal entities (decisions, reflections, AI summaries, manual
trades, reconciliations, moltbook entries):

```
Application_State(t)  = SQLite_DB(t)
Audit_Log(t)          = JSONL_Events[0:t]

UI_Visible_State(t) =
    if API_available AND SQLite_available:
        Application_State(t)               # truth_source = "sqlite"
    else if API_available AND SQLite_unavailable AND JSONL_present:
        JSONL_Fallback_Slice(t)            # truth_source = "jsonl_fallback"
                                            # fallback_used = True
                                            # canonical    = False
    else:
        Mock_Seed                           # truth_source = "mock"
                                            # MOCK_FALLBACK banner is mandatory
```

## Rules for code

1. **No silent truth fallback.** Any handler that may fall back from
   SQLite to JSONL must include `truth_source` (and `fallback_used`) in
   its response payload, or be explicitly documented as
   "SQLite-only — refuses to serve on fallback".

2. **All journaled writes must hit SQLite first.** JSONL is mirrored, not
   substituted. A write that succeeds in JSONL but fails in SQLite is a
   bug, not a success; surface it.

3. **JSONL never overrides SQLite.** If both exist, SQLite wins. JSONL is
   only consulted when SQLite is unavailable for read.

4. **Mock data must always be labelled.** The frontend already shows
   `BACKEND OFFLINE` and `MOCK_FALLBACK` banners. Do not remove or
   weaken those signals. Do not introduce a code path that returns mock
   data without a visible banner.

5. **Schema evolution stays additive.** Backups exist (`scripts/backup_db.py`,
   `scripts/restore_db.py`) but the migration story is "drop tables, ALTER
   only, never destructive". Run a backup before any schema change.

## Response metadata fields

Endpoints that may serve from a fallback path expose these fields when
practical. Older clients ignore them safely; newer clients can render a
banner.

| Field | Type | Meaning |
|---|---|---|
| `truth_source` | `"sqlite" \| "jsonl_fallback" \| "mock" \| "legacy_fabric" \| "live_events"` | Where the rows came from. `sqlite` is canonical; everything else needs a UI cue. |
| `fallback_used` | `bool` | True iff the response came from a non-canonical source. |
| `canonical` | `bool` | True iff `truth_source == "sqlite"`. |
| `mock_fallback` | `bool` | Existing field on `GET /signals`. The backend always returns `False`; the **frontend** flips this when it can't reach the API. |

Today the explicit `truth_source` / `fallback_used` / `canonical`
metadata is wired into `GET /manual-trades` and `GET /signals` (the two
endpoints that actually have a JSONL fallback path). Other endpoints
remain SQLite-first with a silent fallback — fixing them is on the
follow-up plan in `DEPLOYMENT.md`.

## Backup / restore

- `python scripts/backup_db.py` — writes
  `runtime/backups/mvp_local-YYYYMMDD-HHMMSS.db`. Safe to run while the
  backend is live (uses the SQLite online backup API).
- `python scripts/restore_db.py --backup-file <path>` — dry-run by
  default. Add `--yes` to apply. A pre-restore backup is always taken
  before overwrite.

These tools target the SQLite layer. There is no separate JSONL backup;
the JSONL files live in `runtime/logs/` and are covered if you back up
the entire `runtime/` tree at the OS level.

## Data-loss risks (today)

- `runtime/` is git-ignored. Deleting it deletes everything.
- SQLite single-file durability is fsync-bound; a hard power loss during
  a write can corrupt the DB. Mitigation: backup before risky ops.
- JSONL files are appended without fsync between rows; a crash mid-write
  can leave a partial last line. The loader tolerates `json.JSONDecodeError`
  per row, so this is annoying but not corrupting.

## Future migration path

When the project outgrows SQLite (see DEPLOYMENT.md Phase B):

1. Define schema in Postgres mirroring `_SCHEMA_SQL` in
   `scripts/persistence.py`.
2. Write `scripts/migrate_sqlite_to_postgres.py` (additive, idempotent).
3. Switch the persistence module to read `DATABASE_URL`; keep SQLite as
   a local-only fallback if unset.
4. JSONL audit trail continues as-is.
5. Mock data layer is unaffected.

Until then, the SQLite file under `runtime/mvp_local.db` is the entire
source of truth. Treat it accordingly.
