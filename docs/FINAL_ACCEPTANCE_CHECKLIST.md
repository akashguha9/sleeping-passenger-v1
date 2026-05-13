# Final Acceptance Checklist

> The verbatim checklist a fresh reviewer (or future self) walks before
> declaring the local-first showcase release "done." Pair with
> `docs/FINAL_SCORECARD.md`.
>
> Replace each `[ ]` with `[x]` only after the corresponding command or
> page has been visually confirmed.

---

## 1. Local setup

- [ ] `git clone <repo>` works end-to-end on a fresh machine.
- [ ] `python -m venv .venv` succeeds.
- [ ] `pip install -r requirements.txt` succeeds.
- [ ] `.env` is set up from `.env.example` (or equivalent) with no secrets
      checked in.
- [ ] Backend starts: `python -m uvicorn scripts.api_server:app --host 127.0.0.1 --port 8000`.
- [ ] Frontend starts (dependencies pre-installed): `cd frontend && npm run dev`.
- [ ] `GET /health` returns 200 with `advisory_status="ADVISORY_ONLY"`.
- [ ] `python scripts/smoke_check.py --api http://127.0.0.1:8000` exits 0.

## 2. Safety

- [ ] `advisory_status` banner visible in dashboard.
- [ ] No broker SDK in any `import` statement: `grep -ri 'ib_insync\|alpaca\|ccxt\|kite\|robinhood' scripts frontend` returns empty.
- [ ] Token gate enabled in local mode if `MVP_API_TOKEN` is set.
- [ ] Mutating endpoints rejected without token when token gate is on.
- [ ] AI output validation enforces `execution_permission=false`, asserted by
      `tests/test_ai_output_schema.py::test_invalid_payload_never_creates_action_permission`.
- [ ] Live refresh prints `Advisory: ADVISORY_ONLY | Execution gate: LOCKED`.

## 3. Data

- [ ] DB file present at `runtime/mvp_local.db`.
- [ ] `python scripts/backup_db.py` writes a timestamped file in `runtime/backups/`.
- [ ] `python scripts/restore_db.py --source <backup> --dry-run` runs cleanly.
- [ ] `docs/PERSISTENCE_MODEL.md` is current.
- [ ] `runtime/` is in `.gitignore`; DB file is not committed.

## 4. Live signals

- [ ] `scripts/live_source_registry.py` lists 11 source families.
- [ ] `python scripts/run_live_refresh.py --source all --plan-only --json` returns 11 entries.
- [ ] `credential_configured` is `true/false` only — no secret values visible.
- [ ] `default_refresh_hours == 6` for every family.
- [ ] `python scripts/run_live_refresh.py --source all --dry-run` exits 0.
- [ ] Source-health visible at `GET /source-health/summary`.
- [ ] No "latest data is fresh" claim anywhere unless `freshness_state="fresh"`.
- [ ] No paid API has been called unintentionally (no surprise quota burn in
      the provider dashboard since this sprint started).

## 5. Frontend

- [ ] Dashboard loads at `http://localhost:3000`.
- [ ] Sidebar workflow grouping renders.
- [ ] Signal Inbox loads.
- [ ] Signal Detail loads for at least one event.
- [ ] Manual Trade Log loads.
- [ ] Reconciliation page loads.
- [ ] Moltbook / Reflection loads.
- [ ] Help / Onboarding loads.
- [ ] Mock fallback banner visible when backend is offline (toggle backend
      off and confirm).

## 6. Tests

- [ ] `python -m compileall scripts tests` succeeds with no errors.
- [ ] `python -m pytest tests -q` passes (target: ~3017 tests).
- [ ] `python -m pytest tests/test_ai_output_schema.py -q` passes (28).
- [ ] `python -m pytest tests/test_live_source_registry.py -q` passes (24).
- [ ] `python -m pytest tests/test_live_refresh_orchestrator.py -q` passes (15).
- [ ] Frontend lint runs (or noted as skipped): `cd frontend && npm run lint`.
- [ ] Frontend unit tests run if a test script exists (or noted as skipped).
- [ ] Playwright run if configured (or noted as skipped).

## 7. Deployment

- [ ] `docker compose config` lints clean.
- [ ] `Dockerfile.backend` and `Dockerfile.frontend` exist.
- [ ] `docker-compose.yml` exists.
- [ ] `docs/HOSTED_DEPLOYMENT_PLAN.md` is current.
- [ ] No production claim in README / SHOWCASE.md.

## 8. Private beta readiness

- [ ] `docs/PRIVATE_BETA_AUTH_DESIGN.md` exists.
- [ ] `docs/POSTGRES_MIGRATION_PLAN.md` (incl. Day 33 enrichment) exists.
- [ ] `docs/HOSTED_DEPLOYMENT_PLAN.md` exists.
- [ ] `docs/MONITORING_AND_INCIDENTS.md` exists.
- [ ] `docs/LEGAL_PRIVACY_NOTES.md` exists.
- [ ] `docs/SOURCE_TOS_CHECKLIST.md` exists.
- [ ] None of the above promise implementation that has not happened.

## 9. Documentation

- [ ] `README.md` Documentation map links every new doc.
- [ ] `SHOWCASE.md` reads cleanly to a non-author.
- [ ] `docs/ARCHITECTURE.md` Mermaid diagrams render correctly on GitHub.
- [ ] `docs/PRODUCT_DIRECTION_DECISION.md` clearly states "local showcase yes, private beta design-only, public production no."
- [ ] `docs/ROADMAP_DECISION_DAY_30.md` 30/90 plan reads as actionable.
- [ ] `docs/AI_OUTPUT_VALIDATION.md` matches the implementation surface.
- [ ] `docs/LIVE_SIGNALS_REFRESH_MODEL.md` matches `scripts/live_source_registry.py`.
- [ ] `docs/LIVE_SIGNALS_SCHEDULING.md` Windows + cron recipes are runnable.
- [ ] `docs/FINAL_SCORECARD.md` exists.

## 10. Known blockers (remaining P0 / P1)

These are **acceptable to ship around** for a local-first showcase, but
each is a blocker for private beta:

- [ ] Real multi-user auth not implemented.
- [ ] Per-user data isolation not implemented.
- [ ] Hosted Postgres not implemented.
- [ ] Hosted deployment not executed.
- [ ] Monitoring not wired (logs only).
- [ ] Legal / counsel review not done.
- [ ] Source-ToS clearance per family not signed off.
- [ ] Frontend e2e coverage is partial.
- [ ] Performance / concurrency work not done (single-operator only).

If any of these is unexpectedly flipped to ✓ before the corresponding
plan doc is implemented, that is a regression — investigate before
celebrating.

---

## Sign-off line

> The sleeping-passenger-v1 MVP, as of 2026-05-13, is a **local-first
> showcase release**. It is not hosted, not multi-user, not auto-executing,
> not financial advice. The safety contract holds. The 13-step canonical
> workflow runs. Live source refresh is dry-run by default. AI output is
> schema-validated. Backup / restore work. Tests pass.
>
> Reviewer: ____________________  Date: ____________
