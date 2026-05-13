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

---

## 10. Day 33 enrichment — user-isolation–aware migration map

> Added during the Day 26–35 finalization sprint. Pairs with
> `docs/PRIVATE_BETA_AUTH_DESIGN.md`. Still **plan, not implementation**.

### 10.1 Required env vars

| Variable | Default | Purpose |
|---|---|---|
| `DB_BACKEND` | `sqlite` | `sqlite` or `postgres` |
| `DATABASE_URL` | unset | Full Postgres DSN. Required when `DB_BACKEND=postgres`. |
| `MVP_DB_PATH` | `runtime/mvp_local.db` | SQLite file path (sqlite mode only). |
| `POSTGRES_SSL_MODE` | `require` | TLS posture for hosted PG. |

### 10.2 Recommended approach — staged adapter pattern

1. Define a thin persistence interface (or accept the existing
   `scripts/persistence.py` shape as the canonical signature surface).
2. Keep SQLite as one implementation.
3. Add Postgres as a second implementation behind `DB_BACKEND=postgres`.
4. Run the **same contract tests** against both adapters in CI.
5. Introduce Alembic or hand-rolled SQL migrations as soon as the
   Postgres path is real.

A heavy ORM rewrite is not required. The schema is small enough that
hand-managed SQL with parameter binding is fine.

### 10.3 Table-by-table migration map

| Table | Owner | Needs `user_id`? | Migration risk | Required indexes |
|---|---|---|---|---|
| `signal_events` | shared | no | low | `(source_name, created_at)`, `event_id UNIQUE` |
| `signal_decisions` | user | **yes** | medium | `(user_id, event_id)`, `(user_id, created_at)` |
| `user_reflections` | user | **yes** | medium | `(user_id, event_id)`, `(user_id, created_at)` |
| `ai_discussion_summaries` | user | **yes** | medium | `(user_id, event_id)`, `(user_id, prompt_version)` |
| `manual_trades` | user | **yes** | medium | `(user_id, symbol)`, `(user_id, executed_at)` |
| `reconciliation_results` | user | **yes** | medium | `(user_id, trade_id)` |
| `moltbook_entries` | user | **yes** | low | `(user_id, created_at)` |
| `live_source_runs` | system | no | low | `(source_name, timestamp_utc)` |
| `live_refresh_runs` (if introduced) | system | no | low | `(timestamp_utc)`, `(run_id UNIQUE)` |
| `global_securities` | shared | no | low | `symbol UNIQUE` |
| `global_security_aliases` | shared | no | low | `(symbol, alias)` |
| Source-registry persistence (if introduced) | shared | no | low | `source_key UNIQUE` |

### 10.4 Index plan (cross-cutting)

| Index | Reason |
|---|---|
| `user_id` (every user-owned table) | hot path for `WHERE user_id = ?` |
| `created_at` / `timestamp_utc` | recent-first listings |
| `symbol` | symbol-scoped queries |
| `source_name` | source-scoped queries |
| `event_id` UNIQUE | dedupe on idempotent ingestion |
| `trade_id` UNIQUE | idempotent reconciliation |
| `decision_id` UNIQUE | idempotent decision capture |
| `last_success_at` | source-health "freshness" queries |
| `refresh_run_id` (if introduced) | per-run trace |

### 10.5 Rollback plan

1. Trigger a final SQLite backup with `scripts/backup_db.py`.
2. Export every table to CSV (or JSONL) before cutover.
3. Import into Postgres via `\copy` or `pg_dump` of the export.
4. Verify row counts table-by-table.
5. Keep the SQLite file as a **read-only archive** for ≥ 30 days.
6. If a row-count mismatch or behavior drift appears, flip `DB_BACKEND`
   back to `sqlite` (the SQLite path was never decommissioned in the
   staged-adapter approach).

### 10.6 Acceptance criteria

Postgres migration is complete only when:

- [ ] Contract tests pass for SQLite and Postgres adapters.
- [ ] `scripts/backup_db.py` (or its PG equivalent) is wired and
      restored once in staging.
- [ ] User isolation is enforced at the DB layer (per
      `docs/PRIVATE_BETA_AUTH_DESIGN.md`).
- [ ] Hosted deployment uses Postgres.
- [ ] Live refresh writes `source_health` rows reliably in PG.
- [ ] Local dev still works with `DB_BACKEND=sqlite`.
- [ ] No secret (DATABASE_URL with credentials) appears in `/health`,
      `/db/status`, or any logging surface.

### 10.7 Migration risk model

```
Migration_Risk =
    Schema_Drift
  + Data_Loss_Risk
  + User_Isolation_Bugs
  + Query_Behavior_Difference
  + Deployment_Config_Error
  + Refresh_Duplicate_Risk
```

Mitigations:

| Term | Mitigation |
|---|---|
| Schema_Drift | Single source-of-truth migration files committed in repo. |
| Data_Loss_Risk | Pre-cutover backup + CSV export; SQLite kept read-only post-cutover. |
| User_Isolation_Bugs | Required `user_id` argument on every persistence helper; isolation tests in CI. |
| Query_Behavior_Difference | Same contract tests on both adapters; explicit `RETURNING` shaping. |
| Deployment_Config_Error | Hosted deploy template stores DSN in provider secret store, never in repo. |
| Refresh_Duplicate_Risk | `event_id UNIQUE` constraint; idempotent INSERTs. |

This appendix is the design floor. Promote it to implementation only when
`docs/ROADMAP_DECISION_DAY_30.md` says private-beta scaffolding is the
active milestone.

