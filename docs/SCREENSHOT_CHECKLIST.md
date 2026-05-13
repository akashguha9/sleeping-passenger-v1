# Screenshot Checklist

> What to capture for the local-first showcase release. Order matches the
> 13-step canonical workflow plus operational evidence.

These screenshots are **not generated automatically** in this sprint —
they're a post-sprint deliverable. This document is the to-do list.

| # | Screen / artifact | Where | What to show |
|---:|---|---|---|
| 1 | Dashboard / mission-control | `frontend://` | Next-best-action card, source-health overview, advisory banner |
| 2 | Live Signals / Source Health | `frontend://live-signals` (or `/source-health`) | All 11 source families with `adapter_status`, `freshness_state`, redacted credential state |
| 3 | Signal Inbox | `frontend://signals` | Recent normalized signals, source attribution, advisory tag |
| 4 | Signal Detail | `frontend://signals/<event_id>` | Title, source, payload, validate / discuss / reflect / decide controls |
| 5 | Reflection panel | signal detail | Written reflection, save state |
| 6 | Manual Trade Log | `frontend://manual-trades` | Trade entry form, list, reconcile button |
| 7 | Reconciliation | `frontend://reconciliation` | Reconciled trades, status badges |
| 8 | Moltbook / Reflection | `frontend://moltbook` | Aggregated learning journal entries |
| 9 | Settings / Help | `frontend://help` | Workflow grouping, safety disclaimer, advisory copy |
| 10 | Backend offline / mock fallback | toggle backend off | Mock-fallback banner, mock data visible |
| 11 | `/health` JSON | `curl http://127.0.0.1:8000/health` | health green, advisory stamps |
| 12 | `/api/version` JSON | `curl http://127.0.0.1:8000/api/version` | version, git_sha, build date |
| 13 | `/db/status` JSON | `curl http://127.0.0.1:8000/db/status` | DB path, WAL on, busy timeout, fk on, table counts |
| 14 | `/source-health/summary` JSON | `curl http://127.0.0.1:8000/source-health/summary` | per-source severity, advisory stamps |
| 15 | Smoke check output | `python scripts/smoke_check.py` | PASS lines for each check |
| 16 | Backup command output | `python scripts/backup_db.py` | path of new backup file in `runtime/backups/` |
| 17 | Refresh dry-run output (text) | `python scripts/run_live_refresh.py --source all --dry-run` | per-source action + summary + advisory banner |
| 18 | Refresh dry-run output (JSON) | `python scripts/run_live_refresh.py --source all --dry-run --json` | JSON envelope with advisory stamps |
| 19 | Plan-only output | `python scripts/run_live_refresh.py --source all --plan-only --json` | Same shape, `mode: dry_run`, `plan_only: true` |
| 20 | Single-source refresh dry-run | `python scripts/run_live_refresh.py --source polymarket --dry-run` | One-row summary |
| 21 | AI output validation test pass | `python -m pytest tests/test_ai_output_schema.py -q` | "28 passed" green |
| 22 | Live source registry test pass | `python -m pytest tests/test_live_source_registry.py -q` | "24 passed" green |
| 23 | Orchestrator test pass | `python -m pytest tests/test_live_refresh_orchestrator.py -q` | "15 passed" green |
| 24 | Full pytest pass | `python -m pytest tests -q` | "~3017 passed" green |
| 25 | Docker compose config | `docker compose config` | rendered config; advisory banner if used |

## Tips for nice screenshots

- Use a terminal with a clean theme (no truncated lines).
- Crop to relevant content; do not leave OS chrome that exposes other windows.
- For the dashboard, the safety banner should be visible.
- For JSON, format with `python -m json.tool` so safety stamps are obvious.
- Redact any local API key or DB path that contains a username.

## Recorded demo (post-sprint)

Aim for a 5-minute screen recording that walks through:
1. `smoke_check` + `/health` JSON
2. orchestrator plan-only output
3. dashboard → signal inbox → signal detail → AI summary
4. manual trade log → reconciliation
5. backup output
6. final shot: `/source-health/summary` JSON with all 11 families

Audio: voice-over describing **what is real vs mock** at each step.
