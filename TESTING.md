# TESTING — what is and isn't covered

## Backend (pytest)

```powershell
python -m pytest tests -q
```

Runs 460+ test files / 7,800+ tests (last full verified run: 7,567 passed,
3 platform skips, 14m14s on 2026-07-03; ~290 tests added by the
Close-the-Loop sprint on 2026-07-04). CI runs the full suite on every push
(`.github/workflows/pytest.yml`).

> **Last verified: 2026-07-04.** If the counts above drift from
> `python -m pytest tests -q` reality, fix THIS file — stale testing docs
> were a forensic-audit finding (segment L).

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
| API: token gate | `tests/test_api_token_gate.py` | `MVP_API_TOKEN` set → all journal routes require Bearer token. Startup fails closed without a token (`tests/test_owner_only_hardening.py`, `tests/test_hackathon_sprint1.py`) |
| API: error honesty | `tests/test_api_error_honesty.py` | global handler returns sanitized JSON with explicit HTTP status |
| Persistence | `tests/test_persistence.py` | schema init, advisory stamp enforcement on writes |
| Persistence truth model | `tests/test_persistence_truth_model.py` | doctrine doc exists, inbox/list responses expose `truth_source`, fallback is never claimed canonical |
| Inbox bridge | `tests/test_signal_inbox_bridge.py` | dedup, freshness window, candidate promotion |
| DB backup/restore | `tests/test_db_backup_restore.py` | backup is non-mutating, restore is dry-run by default, pre-restore backup is mandatory, invalid backup files are rejected, same-path restore is refused |
| Smoke check | `tests/test_smoke_check.py` | offline backend = FAIL, missing safety stamps = FAIL, `broker_api_called=true` or `ai_execution_count>0` = FAIL |
| Security middleware | `tests/test_security_middleware.py` | security headers on every response, request size guard returns 413 with advisory stamps, 429 returns advisory stamps + Retry-After, rate limit auto-disabled under pytest |
| Rate limiter (pure) | `tests/test_rate_limiter.py` | sliding-window logic with a controlled clock — limit + window + per-key isolation + reset |
| SQLite hardening | `tests/test_sqlite_hardening.py` | WAL on by default, busy_timeout applied, foreign_keys on, `/db/status` exposes pragmas, backup still works post-WAL, db_path display does not leak home directory |
| API version | `tests/test_api_version.py` | `/api/version` returns advisory stamps, never touches the DB, never leaks `MVP_API_TOKEN` |
| Reconciliation queue | `tests/test_reconciliation_queue.py` | unreconciled-trade filter, journal-quality attached, age computed, summary distributions, no DB writes, safety stamps locked |
| Process quality classifier | `tests/test_process_quality_classifier.py` | 4-state matrix, incomplete record, unknown outcome, skill/luck score aggregation, deterministic, no execution permission |
| Self-test report monthly mode | `tests/test_self_test_report_monthly.py` | `--days N` / `--period monthly` filter, process_quality embed, reconciliation_queue embed, no DB writes |
| DB integrity check | `tests/test_db_integrity_check.py` | `PRAGMA integrity_check`, required tables/columns, backup openable, stale backup WARN, no DB writes, safety stamps |
| Local security audit | `tests/test_local_security_audit.py` | secret values never printed, placeholder token WARN, wildcard CORS WARN, tracked-env/db detection, no execution surface in api_server, safety stamps |
| Source refresh audit | `tests/test_source_refresh_audit.py` | registry-only audit works, missing credentials counted skipped, no secret exposure, run-history reliability, days-filter applied, per-source safety stamps |
| Error contracts | `tests/test_error_contracts.py` | envelope shape, word-boundary secret redaction, severity coerced, check_result coerces invalid status, safety stamps |
| Pre-real-money preflight | `tests/test_pre_real_money_preflight.py` | healthy repo passes, DB failure blocks, security failure blocks, unreconciled backlog escalates to BLOCK/FULL_REVIEW, no secret exposure, no DB writes |
| Signal field geometry | `tests/test_signal_field_geometry.py` | trace classification, phase alignment, resonance, damping, geometry labels, hypothesis-only flag, safety stamps locked, deterministic |
| Echo risk + source independence | `tests/test_echo_risk_engine.py` | independence vs. echo, canonical-URL dedupe, primary-source lowers risk, AI-echo guard, confirmation_quality classes, safety stamps |
| Signal decay + waste manager | `tests/test_signal_decay_waste.py` | per-type half-life, social hype decays faster than filings, stale/duplicate/contradicted/failed-thesis classes, waste-load score, recommendations, safety stamps |
| Fission branch mapper | `tests/test_fission_branch_mapper.py` | central-bank shock branches across families, high uncertainty → map_only, low severity → do_not_promote, branch energies clamped, safety stamps, no execution language |
| Fusion thesis engine | `tests/test_fusion_thesis_engine.py` | independent aligned signals → valid_fusion, repeated same source → echo_not_fusion, high heat low containment → overheated_uncontained, deterministic, safety stamps |
| Operator control rods | `tests/test_operator_control_rods.py` | calm = low heat, revenge/fomo/sleep deficit/altered state → gallardo block, containment reduces meltdown, `broker_execute` always false, manual_trade_logging gated on compliance, safety stamps |
| Adaptive signal router | `tests/test_adaptive_signal_router.py` | high nutrient/low terrain → reinforce, hostile terrain → quarantine, echo/contradiction shrinks weight, summary state counts, no DB/live calls, safety stamps |
| Signal reactor orchestrator | `tests/test_signal_reactor.py` | echo cluster → ECHO_SUPPRESSED, independent aligned → FUSION_REVIEW_CANDIDATE, unclear shock → FISSION_MAP_ONLY, operator heat → OPERATOR_CONTROL_RODS, stale → WASTE_DECAY, CLI `--example --json` works, `broker_execute` always false, nested outputs all safety-locked |
| Signal reactor safety invariants | `tests/test_signal_reactor_safety_invariants.py` | walks every public function on every new module, asserts canonical safety stamps and no execution permission anywhere, asserts module source has no forbidden execution tokens or banned theatrical runtime names |

### Persistence truth (canonical vs fallback vs mock)

The doctrine lives in `docs/PERSISTENCE_MODEL.md`. In short:
SQLite is the canonical store; JSONL is an audit trace and a fallback for
reads; mock data is UI-only and must always be visibly labelled.

`GET /signals` and `list_manual_trades` now expose three flags
(`truth_source`, `fallback_used`, `canonical`) so callers can never confuse
a fallback slice with canonical state. Verified by
`tests/test_persistence_truth_model.py`.

### What is not tested

- ~~The frontend~~ **CORRECTED 2026-07-04:** the frontend IS tested —
  Vitest runs 36 spec files / 207 tests (`cd frontend; npm test`), Playwright
  e2e specs exist (`frontend/e2e/`, weekly CI cron), and `next build`
  compiles all 16 routes. The prior claim that no frontend test stack was
  installed was stale and wrong (forensic-audit finding).
- **Frontend lint is BLOCKED, documented, not silent:** Next 16 removed
  `next lint`; `npm run lint` now prints the exact migration required
  (`npm i -D eslint eslint-config-next`, add `eslint.config.js`, script
  becomes `eslint .`). Until migrated there is no frontend lint gate.
- **End-to-end against a REAL backend.** Playwright specs mock backend
  routes; no CI job boots the FastAPI server and drives the UI unstubbed.
  Contract drift between backend payloads and frontend stubs would pass
  both suites green.
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
1. Start backend with a token: `python scripts/generate_api_token.py --write-env` (or set MVP_ALLOW_UNAUTH=1 for a throwaway unauthenticated loopback run).
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
