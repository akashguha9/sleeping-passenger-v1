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
| 6 | No backup of `runtime/mvp_local.db` | P1 | Add a daily dump (e.g. `sqlite3 runtime/mvp_local.db .dump | gzip > backups/...`). |
| 7 | Secrets in `.env` on disk | P2 | Move to OS keyring / vault if leaving the laptop. |
| 8 | No rate-limiting | P2 | Add `slowapi` once auth is real. |
| 9 | No structured logging | P2 | Plain stdout/file logs in `runtime/logs/`. Add `structlog` for JSON. |
| 10 | No legal review | P2 | Yahoo OHLCV redistribution, news article body retention, and "advisory" language all need counsel before multi-user. |

## What was added in this sprint to raise the floor

- Env-driven `API_HOST`, `API_PORT`, `ALLOWED_ORIGINS`, `MVP_API_TOKEN`,
  `MVP_DB_PATH`, `MVP_ENVIRONMENT` (`scripts/runtime_config.py`).
- Token-gated mutations (opt-in via `MVP_API_TOKEN`).
- Global FastAPI exception handler returning sanitized JSON + real HTTP status codes.
- Expanded `/health` reporting DB availability, allowed-origins count, token-required flag, environment tag.

These are floor-raisers, not deployment readiness.

## Recommended deployment plan (when you're ready)

### Phase A — Containerize (1 day)
1. Add `Dockerfile.backend` (multistage; final image runs `uvicorn scripts.api_server:app --host 0.0.0.0 --port 8000`).
2. Add `Dockerfile.frontend` (Next.js standalone build, `next start`).
3. Add `docker-compose.yml` wiring both, with `runtime/` mounted as a volume
   and a `.env` file path injected.
4. Verify `docker compose up` reproduces the local experience on another machine.

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
