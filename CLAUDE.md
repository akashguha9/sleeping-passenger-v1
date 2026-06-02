# CLAUDE.md — Sleeping Passenger

Advisory-only MVP for global stock/signal discovery, trade-candidate
evaluation, paper/live **manual** trade logging, Moltbook feedback, outcome
review, and safety-gated decision support.

## Critical invariant (never violate)

- This MVP is **NOT** an execution bot. It must never place broker orders,
  generate broker-API execution code, or tell the operator what to buy/sell as
  financial advice.
- Human execution is mandatory. Allowed advisory labels only: `WATCH`, `WAIT`,
  `AVOID`, `RISK_BLOCK`, `TRADE_CANDIDATE_FOR_MANUAL_REVIEW`,
  `WATCH_CAP_LIMITED`, `OUTCOME_REVIEW_NEEDED`. No `BUY`/`SELL`/`EXECUTE` as
  instructions.
- Every advisory output carries the canonical safety stamps from
  `scripts/advisory_contract.py:advisory_safety_stamps()`:
  `execution_gate=LOCKED`, `broker_api_called=False`, `ai_execution_count=0`.

## Persistence model

- **SQLite is canonical** (`runtime/mvp_local.db`); **JSONL under `logs/` is
  audit-only**. Never flip JSONL to canonical.
- Canonical truth files (e.g. `data/daily_payload/verified_current_holdings.json`)
  are read-only to new tooling — record conflicts, never destructively overwrite.

## Common commands

```
python -m compileall scripts tests
python -m pytest tests -q
python -m pytest tests/test_trade_log_metrics.py -q     # one file
python scripts/trade_log_metrics.py --input exports/trade_log.csv --starting-capital 4000
python scripts/dashboard_contract.py --input exports/trade_log.csv --starting-capital 4000
```

## Conventions

- Pure, deterministic, typed functions; dataclasses (`frozen=True`); `argparse`
  CLI + `__all__`. `from __future__ import annotations`.
- Dual import shim: `try: from scripts import X / except ModuleNotFoundError: import X`.
- Reuse `scripts/runtime_common.py` (`utc_timestamp`, `append_jsonl`, `LOG_DIR`,
  `write_json_atomic`) and `scripts/advisory_contract.py` rather than re-rolling.
- Tests pin runtime side-channels (DB/log paths) to `tmp_path` so they never
  touch canonical state.

## Important directories

- `scripts/` — engines + CLIs. `tests/` — pytest. `config/` — YAML/JSON config.
- `data/daily_payload/` — daily synthesis payload + canonical holdings.
- `docs/` — design notes (see `TRADE_LOG_DISCOVERY_METRICS.md`).

## Google-Sheet export workflow

The operator keeps a manual trade log in a Google Sheet (messy headers, mixed
`80%`/`0.8`, comma numbers, `"OPEN | Cum P/L: 29.76"`). Export to CSV →
`scripts/google_sheet_schema.py` normalizes it → `scripts/trade_log_metrics.py`
and `scripts/dashboard_contract.py` compute metrics. `CAPITAL AFTER ROW` is
**free cash, not total equity**.

## Do NOT commit

Runtime files (`runtime/`, `*.db`), secrets (`.env*`, `secrets/`), CSV exports
(`*.csv` is gitignored — the one tracked fixture is force-added), generated
daily-payload backups.

## Working style

Plan before large edits; run tests before declaring done; keep new modules
small and advisory-only; do not introduce pandas/network/broker dependencies.
