# Environment / Config Contract

Kanté Sprint 2 — Task 6.  The local advisory MVP is configured entirely through
environment variables.  `scripts/config_contract.py` turns that surface into a
**typed contract** and a **drift detector** so the documented `.env.example`
and the code's expectations can never silently diverge.

Run it:

```powershell
python scripts/config_contract.py            # human-readable
python scripts/config_contract.py --json      # machine-readable
```

## Contract model

```
ConfigScore = valid_required / required
              − penalty(dangerous_unknowns)
              − penalty(missing_example)

Drift       = | vars(.env.example) △ vars(contract) |   (symmetric difference)
```

`evaluate()` never prints a secret **value** — only variable names and presence
booleans.  It never touches the DB and never calls a broker.

## Variable classes

| Class | Severity if missing | Examples |
|---|---|---|
| **required** | `FAIL` if blank/unresolvable | `MVP_DB_PATH` (falls back to `runtime/mvp_local.db`) |
| **secret** (optional) | `WARN` (source stays off) | `XAI_API_KEY`, `EDINET_API_KEY`, `MVP_API_TOKEN` |
| **source** (optional) | `WARN` (source stays off) | `SEC_USER_AGENT`, `POLY_*_BASE_URL`, `PIPELINE_QUOTE_PROVIDER` |
| **plain** | `INFO`/default | `API_HOST`, `API_PORT`, `ALLOWED_ORIGINS`, `MVP_ENVIRONMENT` |
| **exec_flag** | must stay OFF | `PIPELINE_ENABLE_LIVE_EXECUTION` (truthy → `FAIL`), `PIPELINE_ENABLE_PAPER_EXECUTION` (truthy → `WARN`) |

## Hard rules

* A **blank `MVP_DB_PATH`** fails closed — the canonical SQLite path must resolve.
* **`PIPELINE_ENABLE_LIVE_EXECUTION` truthy → `FAIL`.** The advisory MVP keeps
  live execution OFF; the broker is never called regardless of any flag.
* A **dangerous unknown** env var (name matching `broker`, `alpaca`, `ibkr`,
  `oanda`, `place_order`, `auto_trade`, `live_trading`, …) that is **not** a
  declared contract variable → `FAIL`.  No broker / live-trading toggle belongs
  in this MVP.
* **Drift**: any variable that exists in the contract but not in `.env.example`
  (or vice-versa) is reported as drift (`WARN`) so the example stays honest.

## Adding a new variable

1. Add it to `.env.example` (blank value; never a real secret).
2. Add it to `CONTRACT` in `scripts/config_contract.py` with the right class.
3. `python scripts/config_contract.py` should report **no drift**.

This is engineering hygiene, not legal advice.
