# Pipeline V5.7 Core

This repo is a local decision shell for inspecting seeded signal state, blocker state, action posture, and transition readiness. It is not a live trading system.

## Verified Now

- Local diagnostics run from checked-in Moltbook data and local signal ledger files.
- Runtime artifacts are stamped with a shared `run_id`, `source_mode`, `operating_mode`, `truth_origin`, `commit_hash`, and `config_fingerprint`.
- The main repo-scoped test suite passes from `tests/`.
- The system can classify its current operating mode from local runtime state and environment flags.

## Not Yet Live

- No live quote adapter is wired.
- No paper execution adapter is wired.
- No live execution path is wired.
- No reconciliation loop exists.
- Local logic quality should not be confused with live readiness.

## Current Operating Stance

- Default mode is `seeded`.
- Default truth origin is `seeded`.
- Quote-provider handling is placeholder-only unless explicitly replaced later.
- External connectivity is optional and currently absent from the verified path.

## Repo Layout

- `scripts/`: runtime logic, diagnostics, adapters, and reports
- `moltbook/`: seeded local inputs
- `config/`: runtime configuration
- `tests/`: repo-scoped verification only
- `docs/`, `architecture/`, `scorecards/`, `prompts/`: supporting reference material and historical artifacts

## Repo-Scoped Verification

```powershell
python -m pytest -q tests
python scripts\repo_operating_mode.py --summary
python scripts\pipeline_health_report.py --summary --no-write
python scripts\run_diagnostics_pipeline.py --summary --no-write
```

## Environment Template

Copy `.env.example` into your local environment management flow if you want to test paper/live-prepared mode flags later. The checked-in verified path does not require secrets.

## Offline-First Notes

- The verified path runs fully local.
- Do not treat placeholder adapters as live integrations.
- Keep external contact bounded and explicit if real data or execution is added later.
