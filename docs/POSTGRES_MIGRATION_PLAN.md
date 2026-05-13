# POSTGRES_MIGRATION_PLAN — design, not implementation

> **Status: PLAN, NOT EXECUTED.** This document exists to make a future
> migration deliberate instead of chaotic. **No Postgres migration runs
> as part of the Day 11-25 hardening sprint.** SQLite remains canonical
> until at least one of the conditions in §3 is met.

## 1. Why SQLite is still the right choice today

- The MVP is a single-user, local-first advisory journal. There is no
  multi-user contention, no cross-region read latency, no shared write
  load.
- SQLite with WAL + `busy_timeout=5000` (now applied in
  `scripts/persistence.py`) handles concurrent readers and the
  occasional second writer (e.g. `live_source_runner.py` while
  `api_server` is up) just fine for one laptop.
- The backup story already works: `scripts/backup_db.py` uses
  `sqlite3.Connection.backup()` (hot-copy backup API), and
  `scripts/restore_db.py` enforces a pre-restore backup and a
  dry-run-by-default contract.
- The schema (~14 tables in `scripts/persistence.py`) is dominated by
  small write-once-read-many records: reflections, manual trades,
  reconciliations, moltbook entries, source-health snapshots. None of
  this is throughput-bound today.
- Switching to a hosted DB now would buy ops complexity (a server to
  babysit, a connection string to leak, a backup pipeline to wire),
  for no current user-facing value.

So: don't migrate yet. Move when the **operating conditions** change,
not when the engineer feels bored.

## 2. When SQLite stops being enough

| Signal | Threshold | Why it forces a move |
|---|---|---|
| Concurrent users | More than 1 actual human writing | SQLite WAL handles N readers + 1 writer per machine; multiple human writers across processes start fighting on a single `.db` file |
| Cross-machine state | Any | SQLite is a file. The moment "the journal" lives on more than one device, you need a server |
| Hosted deployment | The day someone wants the app behind a URL they can hit from a phone | A hosted FastAPI can't sit on `runtime/mvp_local.db` for serious traffic |
| Auth (real multi-tenant) | Per-user data isolation | SQLite has no real RLS; per-user partitioning by schema is hacky |
| Audit / compliance | Any external review | "Where does the data live?" should not answer with "my laptop in the corner" |
| Reporting load | Heavy analytical queries co-running with ingestion | Long-running aggregations starve writers in SQLite even with WAL |

None of these are true on 2026-05-13. The earliest realistic trigger is
"a second person logs in" — and that is **not on the roadmap** for this
sprint or the next.

## 3. Target architecture, when the move happens

```
┌─────────────────────┐    ┌─────────────────────┐
│  Next.js frontend   │───▶│  FastAPI service    │
│  (Vercel / Fly /    │    │  (Fly / Render /    │
│   self-host)        │    │   self-host VPS)    │
└─────────────────────┘    └────────┬────────────┘
                                    │
                            ┌───────▼─────────┐
                            │  Postgres 16    │
                            │  (managed:       │
                            │   Supabase /    │
                            │   Neon / RDS)   │
                            └─────────────────┘
```

### Connection layer

- New env vars (in `runtime_config.py`):
  - `MVP_DB_BACKEND` — `sqlite` (default) or `postgres`.
  - `MVP_PG_DSN` — full DSN, never logged.
  - `MVP_PG_POOL_MIN`, `MVP_PG_POOL_MAX`.
- Replace direct `sqlite3` calls with a thin adapter. Recommended:
  **SQLAlchemy Core** (not full ORM) — gives both engines the same
  binding/parameterization API without dragging in heavy mapping
  machinery.
- Why not asyncpg? FastAPI handlers are mostly fast point queries; sync
  is fine until profiled otherwise. Don't complicate the model first.

### Migration framework

- **Alembic** (because SQLAlchemy is already in scope) — additive
  migrations only, same `IF NOT EXISTS` discipline as today's schema.
- Migration files live at `migrations/versions/`. CI gates: each PR that
  touches a table must include a migration; lint check enforces this.

### User isolation

- Add `user_id UUID NOT NULL` to every business table.
- Default value during the SQLite → Postgres copy: a single
  `00000000-0000-0000-0000-000000000001` (the existing single user).
- Real multi-tenant auth is a *separate* project — JWT + session table
  + per-row `user_id` filter in every read query. Don't rush it in the
  same week as the DB move.

### Backup / restore

- Hosted Postgres: rely on the provider's PITR + daily snapshots.
- Bonus: nightly `pg_dump` to S3-compatible object storage. Same
  retention philosophy as today's SQLite backups: backup script does
  not delete; retention is a separate concern with its own script.
- Restore drill once per quarter — actually restore a snapshot into a
  staging DB, run `smoke_check.py` against it, throw it away.

### Observability

- `/db/status` endpoint adapts to expose: backend type, Postgres
  version, latency to first query, current connection-pool size,
  replication lag (if a read replica is added later).
- `/health` already exposes `db_available`; extend with
  `db_backend = "postgres"` / `"sqlite"`.

## 4. Data export / import plan

The migration is **one-way and additive**:

1. **Freeze writes.** Stop the API server and any runner.
2. **Backup SQLite.** Run `python scripts/backup_db.py --label premigration`.
   That file is the rollback anchor.
3. **Run a new `scripts/export_sqlite_to_postgres.py`** (does not exist
   yet — see §6 acceptance). It opens both DBs, copies every row
   table-by-table, in dependency order, with a fixed `user_id`.
4. **Validate row counts**. `get_db_status(...)` from both sides must
   produce identical `table_row_counts` (modulo `user_id`).
5. **Smoke-check both surfaces.** Run `scripts/smoke_check.py` against
   the new Postgres-backed API. Advisory stamps must still be
   `ADVISORY_ONLY` / `LOCKED` / `broker_api_called=false` / `ai_execution_count=0`
   on every response.
6. **Flip the env var.** Update `MVP_DB_BACKEND=postgres` and restart.
7. **Leave SQLite in place for 30 days.** Do not delete it. If anything
   goes wrong in Postgres, swap the env var back to `sqlite` and you're
   running again in seconds.

## 5. Rollback plan

- The migration script is idempotent and read-only against SQLite — it
  never mutates the source.
- Set `MVP_DB_BACKEND=sqlite` and restart to go back.
- Postgres data after the cutover that is *not yet* in SQLite is the
  only thing that gets stranded by a rollback. Mitigation: in the first
  30 days post-cutover, run a daily `export_postgres_to_sqlite.py`
  back-sync so the SQLite file stays close to current.

## 6. Acceptance criteria — what "done" looks like

The migration is done when:

- [ ] `scripts/persistence_pg.py` (or equivalent in the adapter layer)
      passes the existing `tests/test_persistence*.py` suite against a
      real Postgres in CI.
- [ ] `scripts/export_sqlite_to_postgres.py` exists and is covered by a
      golden-file test (small fixture DB → row-by-row equality).
- [ ] `tests/test_db_backup_restore.py` has Postgres equivalents
      (`pg_dump` round-trip).
- [ ] `/health` and `/db/status` report the new backend.
- [ ] `DEPLOYMENT.md` documents the env-var flip and the rollback path.
- [ ] A staging environment has been running on Postgres for at least
      72 hours with no errors in the log.
- [ ] Safety invariants verified end-to-end: `advisory_status`,
      `execution_gate=LOCKED`, `broker_api_called=false`,
      `ai_execution_count=0` are present on every endpoint and every
      stored row, exactly as today.

## 7. Risks and how to handle them

| Risk | Mitigation |
|---|---|
| Schema drift during migration | Lock SQLite writes during the export step. The 5-minute downtime is acceptable for a single-user system |
| Connection-string leakage | DSN is read from env, never logged, never echoed in `/health`. New tests must assert no PG creds appear in `/health` or `/db/status` |
| Backup story regression | Don't cut over until `pg_dump` is wired AND restored once in staging |
| Latency surprise | Add a `/db/status` `latency_ms` field during the cutover window; alert if > 500ms |
| Test suite drift | Run the existing pytest suite against the new adapter in CI, not just in a one-off script |

## 8. What this plan deliberately omits

- Read replicas, sharding, multi-region — premature, single-tenant.
- Migration to a different ORM (Django, Tortoise, etc.) — out of scope.
- Encrypting data at rest beyond what the managed provider gives us
  for free — defer until there is real PII, which today there isn't.
- Switching to a serverless DB (PlanetScale, etc.) — Postgres is
  boring on purpose; pick exotic infrastructure once.

## 9. First safe step (when the trigger fires)

> _Do not do this yet. The trigger is "concurrent users" or "hosted
> deployment" — neither is true today._

The first commit on the migration branch should add only:

1. The `MVP_DB_BACKEND` env var to `scripts/runtime_config.py`,
   defaulting to `sqlite`.
2. An empty `scripts/persistence_pg.py` with the same public function
   signatures as `scripts/persistence.py` but raising `NotImplementedError`.
3. A `tests/test_persistence_backend_switch.py` that asserts both
   adapters expose the same public surface (by name, even if pg is a
   stub).

That commit changes zero behaviour. Everything that follows is a
deliberate, reviewable, reversible step on top of that scaffold.
