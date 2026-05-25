# Local Release Runbook

> Advisory-only MVP. There is no broker execution, no autonomous trading,
> and no order-placement path anywhere in this runbook. The "release" here
> means "start the local stack for a single operator on one machine".

This runbook is the **positioning layer** of the Kanté defensive sprint: run
cheap, read-only checks *before* serving the UI so you never demo on a broken
or polluted local state.

## TL;DR

```bash
# 1. Read-only preflight (PASS / WARN / FAIL / INFO per check)
python -m scripts.local_deploy_preflight

# 2. Single gate verdict with exact reasons
python -m scripts.release_gate            # offline checks only
python -m scripts.release_gate --check-backend   # also probes /health

# 3. Start the stack (Windows) — refuses to start on a FAIL verdict
powershell -File scripts/start_local_stack.ps1
```

## What the release gate checks

`scripts/release_gate.py` aggregates `scripts/local_deploy_preflight.py` into
one verdict:

| Check | Severity if bad | Meaning |
|---|---|---|
| `python_available` | — | Python interpreter present (it is — you're running it). |
| `node_npm_available` | INFO | Frontend tooling. Absent → frontend skipped; backend is unaffected. |
| `runtime_db_exists` | FAIL | `runtime/mvp_local.db` must exist. |
| `sqlite_tables_exist` | FAIL | All core tables present. |
| `moltbook_no_fake_pollution` | FAIL | No fake SPY/QQQ/FABRIC demo Moltbook rows. |
| `moltbook_bridge_idempotent` | FAIL | Bridge dry-run produces a stable created count. |
| `closed_losses_detectable` | INFO | Closed losses + their Moltbook coverage are visible. |
| `execution_gate_locked` | FAIL | No persisted row carries a broker flag or AI execution count. |
| `no_broker_route_exposed` | FAIL | `api_server.py` exposes no broker / order route. |
| `frontend_env_points_to_backend` | WARN | `frontend/.env.local` points at the expected backend. |
| `mock_fallback_explicit` | WARN | The synthetic fallback mode is named, not silent. |
| `backend_health` | WARN | (only with `--check-backend`) `/health` is reachable. |

### Verdict rules

- Any **FAIL** → gate **FAIL** (do not release).
- Any **WARN** → gate **WARN** (release with eyes open; `-Force` to launch).
- Otherwise → **PASS**.
- **INFO never affects the verdict.**

## Common failures and fixes

- **`runtime_db_exists` FAIL** — initialize the DB:
  `python -c "import scripts.persistence as p; p.init_schema()"`.
- **`moltbook_no_fake_pollution` FAIL** — clean the residual demo rows:
  `python scripts/moltbook_cleanup_fake_seed.py --apply`.
- **`execution_gate_locked` FAIL** — a row in `manual_trades` /
  `reconciliation_results` carries `broker_api_called != 0` or
  `ai_execution_count != 0`. This is a data-integrity violation; investigate
  the row before serving anything.
- **`backend_health` WARN** — start the backend:
  `python -m uvicorn scripts.api_server:app --host 127.0.0.1 --port 8000`.

## Authorization

Starting the stack, mutating config, restoring the DB, and overriding the
release gate are **ADMIN** actions in `scripts/operator_auth.py`. Running the
reconciliation bridge / exporting reports are **OPERATOR** actions. Reading the
dashboard is **VIEWER**. Authorization here is advisory-only — it never unlocks
broker execution (no role can).

## Safety invariants (unchanged by any release)

```
advisory_status     = ADVISORY_ONLY
execution_gate      = LOCKED
execution_permission = false
can_execute         = false
broker_api_called   = false
ai_execution_count  = 0
human_review_required = true
```

SQLite (`runtime/mvp_local.db`) is canonical. JSONL is an audit-only mirror.
