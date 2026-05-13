# DEPLOYMENT — current status and the path to production

> TL;DR: This project is currently **local-only by design**. The blockers below
> are real. Don't deploy a public version until they are addressed.

## Current status

- **Demo-ready locally:** YES — runs on Windows via `python scripts\api_server.py` and `npm run dev`.
- **Single-machine MVP:** YES — one user on loopback.
- **Private beta:** NOT READY — no auth (unless `MVP_API_TOKEN` is set), no hosted DB, no container artifacts.
- **Public launch:** NOT READY — no horizontal scaling, no multi-user model, no compliance review.

## Production blockers (ranked)

| # | Blocker | Severity | Notes |
|---|---|---|---|
| 1 | No multi-user auth | P0 | Token gate exists for mutations (`MVP_API_TOKEN`) but there is no user model, no session, no per-user data. |
| 2 | SQLite at `runtime/mvp_local.db` | P0 | Not viable past a few concurrent writers. Plan a Postgres swap. |
| 3 | No Dockerfile/compose | P0 | No reproducible build artifact. |
| 4 | Hardcoded `127.0.0.1` was the default | P1 | Fixed: `API_HOST` / `API_PORT` env vars now control bind. CORS via `ALLOWED_ORIGINS`. |
| 5 | Sync FastAPI routes | P1 | Blocking under any concurrency. Switch to `async def` + `aiosqlite`/asyncpg before opening to >5 users. |
| 6 | Automated backup story | P1 | `scripts/backup_db.py` + `scripts/windows/backup_sleepingpassenger_db.ps1` + `docs/WINDOWS_BACKUP_TASK.md` give a Task-Scheduler-ready daily snapshot. Still local-only; off-machine replication unsolved. |
| 7 | Secrets in `.env` on disk | P2 | Move to OS keyring / vault if leaving the laptop. |
| 8 | Rate-limiting | P2 | In-memory sliding-window limiter (`scripts/rate_limiter.py`) now wraps the API. Strict mutating-route limit + softer GET limit, both env-driven. Auto-disabled under pytest. For real exposure put a reverse proxy in front anyway. |
| 9 | No structured logging | P2 | Plain stdout/file logs in `runtime/logs/`. Add `structlog` for JSON. |
| 10 | No legal review | P2 | Yahoo OHLCV redistribution, news article body retention, and "advisory" language all need counsel before multi-user. |

## What was added in this sprint to raise the floor

- Env-driven `API_HOST`, `API_PORT`, `ALLOWED_ORIGINS`, `MVP_API_TOKEN`,
  `MVP_DB_PATH`, `MVP_ENVIRONMENT` (`scripts/runtime_config.py`).
- Token-gated mutations (opt-in via `MVP_API_TOKEN`).
- Global FastAPI exception handler returning sanitized JSON + real HTTP status codes.
- Expanded `/health` reporting DB availability, allowed-origins count, token-required flag, environment tag.
- Manual SQLite backup/restore tooling (`scripts/backup_db.py`,
  `scripts/restore_db.py`) — restore is dry-run by default and always
  takes a pre-restore backup before overwriting.
- Container scaffold (`Dockerfile.backend`, `Dockerfile.frontend`,
  `docker-compose.yml`, `.dockerignore`) — local-demo grade, not production.
- Smoke check script (`scripts/smoke_check.py`) that hits `/health` and
  verifies the advisory safety stamps before a demo.
- Persistence truth doctrine (`docs/PERSISTENCE_MODEL.md`).

### Day 11-25 hardening additions

- **Security headers middleware** on every response: `X-Content-Type-Options`,
  `X-Frame-Options=DENY`, `Referrer-Policy=no-referrer`, conservative
  `Permissions-Policy`, `Cross-Origin-Resource-Policy`, `X-Robots-Tag`.
  Tuned for a JSON API (no CSP — frontend ships its own).
- **Request size guard** — mutating routes reject requests whose
  `Content-Length` exceeds `MVP_MAX_REQUEST_BYTES` (default 1 MB) with
  a 413 stamped with the same advisory invariants as 200s.
- **In-memory rate limiter** (`scripts/rate_limiter.py`) — sliding
  window, per-client, stricter quota on mutating routes than reads.
  Auto-disabled under pytest; enabled by default in normal runs.
- **SQLite hardening** — every connection now applies `journal_mode=WAL`,
  `busy_timeout=5000`, `synchronous=NORMAL`, `foreign_keys=ON`,
  `temp_store=MEMORY`. Backup script unchanged (still uses the hot-copy
  `connection.backup()` API).
- **API contract** — new `GET /api/version` for cheap uptime/version
  pings without touching the DB. `/health` now reports
  `rate_limit_enabled`, `max_request_bytes`, `security_headers_enabled`.
  `/db/status` reports the applied pragmas and a `wal_enabled` flag.
- **Windows backup automation** — `scripts/windows/backup_sleepingpassenger_db.ps1`
  + `docs/WINDOWS_BACKUP_TASK.md` (Task Scheduler walkthrough).
- **Postgres migration plan** (`docs/POSTGRES_MIGRATION_PLAN.md`) —
  design, not implementation. SQLite remains canonical.

These are floor-raisers, not deployment readiness.

## Local backup procedure

```powershell
# write runtime/backups/mvp_local-YYYYMMDD-HHMMSS.db
python scripts\backup_db.py

# preview a restore
python scripts\restore_db.py --backup-file runtime\backups\<chosen-file>.db

# apply (pre-restore backup is automatic)
python scripts\restore_db.py --backup-file runtime\backups\<chosen-file>.db --yes
```

Backups are byte-equivalent SQLite files produced via the online backup API,
so they're safe to take with the backend running. Anyone moving this MVP into
a private beta MUST automate this (cron, Task Scheduler, or a wrapper script)
before exposing it to non-developer users.

## Recommended deployment plan (when you're ready)

### Phase A — Containerize (DONE for local/demo)

A local-demo scaffold now ships in the repo. It is intentionally not a
production deployment artifact:

```powershell
# build both images
docker compose build

# bring the stack up (backend on 8000, frontend on 3000)
docker compose up --build

# render the merged config without building or starting anything
docker compose config

# stop and remove containers (named volumes / host mounts persist)
docker compose down
```

Files:

- `Dockerfile.backend` — `python:3.13-slim`, installs `requirements-dev.txt`,
  runs `python scripts/api_server.py` on `0.0.0.0:8000`, with a `HEALTHCHECK`
  that probes `/health`.
- `Dockerfile.frontend` — multi-stage Node 20 Alpine build, `npm ci`,
  `npm run build`, then `npm start`. `NEXT_PUBLIC_API_BASE_URL` is a build-arg
  because Next.js inlines it into the bundle.
- `docker-compose.yml` — backend + frontend, `./runtime` and `./logs`
  bind-mounted into the backend container so SQLite state survives container
  removal. No secrets are baked in: `MVP_API_TOKEN` is read from the shell
  env (or a local `.env`) and is empty by default for parity with local dev.
- `.dockerignore` — excludes `runtime/`, `logs/`, `.env*`, `node_modules/`,
  `.git/`, `__pycache__/`, `*.db`, and other heavy/sensitive files.

Limitations of this scaffold:

- single replica per service, no reverse proxy, no TLS
- SQLite under `/app/runtime` is bind-mounted from the host; if two
  developers run compose on the same checkout they will fight over the file
- no rate limiting, no Prometheus metrics, no log shipping
- the frontend bakes a single `NEXT_PUBLIC_API_BASE_URL` per build; to point
  at a different backend you must rebuild

The follow-up production work below still applies.

### Phase B — Hosted DB (1–2 days)
1. Add SQLAlchemy or asyncpg.
2. Mirror the SQLite schema in Postgres (use Alembic).
3. Add a one-time migration script: `python scripts/migrate_sqlite_to_postgres.py`.
4. Keep SQLite as a local-only fallback if `DATABASE_URL` is unset.

### Phase C — Real auth (2–3 days)
1. Decide: single shared token, OAuth, or per-user accounts.
2. Add a `users` table and a `user_id` column to `manual_trades`,
   `signal_decisions`, `user_reflections`, `moltbook_entries`,
   `reconciliation_results`.
3. Replace the bearer-token check with a session/JWT verifier.
4. Add a sign-in screen on the frontend.

### Phase D — Hosting (1 day)
1. Pick a host: Fly.io / Railway / Render / your own VM.
2. Set env vars on the host: `API_HOST=0.0.0.0`, `ALLOWED_ORIGINS=https://your.domain`,
   `MVP_API_TOKEN=<strong-random>`, `DATABASE_URL=...`.
3. Wire HTTPS in front (Cloudflare, host-provided cert, or Caddy).
4. Wire daily DB backups.

### Phase E — Observability (1 day)
1. Switch logger to JSON via `structlog`.
2. Add a `request_id` middleware that propagates through to persistence logs.
3. Add `/metrics` (Prometheus-compatible) if multi-user.
4. Add an external uptime check on `/health`.

### Phase F — Compliance pass (1+ days, possibly external)
1. Audit `yfinance` redistribution clause.
2. Strip stored news article bodies if redistributing publicly.
3. Add Terms of Use + Privacy Policy pages.
4. Have a lawyer review the "ADVISORY_ONLY" disclaimer if any user is in a
   regulated jurisdiction.

## Acceptance criteria for "deployable"

All of these must be true:

- [ ] `docker compose up` runs the full stack on a clean Linux box.
- [ ] All POST/PUT/DELETE routes require auth.
- [ ] DB is Postgres (or SQLite + Litestream replica with documented restore).
- [ ] Daily DB backup is automated.
- [ ] `/health` returns 200 from the public URL behind HTTPS.
- [ ] No `127.0.0.1` or `localhost` hardcoded in code (only as defaults).
- [ ] CI runs pytest + (eventually) frontend tests + (eventually) Playwright e2e.
- [ ] CHANGELOG.md and a versioned release tag.

Until that list is green, this is a local tool.
