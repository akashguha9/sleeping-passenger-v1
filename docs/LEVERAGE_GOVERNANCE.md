# Leverage Governance

Single source of truth: `scripts/leverage_governance.py`. Advisory-only. It
validates leverage on **logged** manual trades; it never places or blocks an
order.

## Doctrine
- India equities (NSE / BSE / IN): ceiling **4.0x** (a ceiling, never a default).
- Rest-of-world equities: **1.0x** (spot-only).
- Unknown jurisdiction: **fails closed to 1.0x** — leverage above 1.0x is a breach.
- Default leverage is always 1.0x.

## Jurisdiction resolution precedence
`jurisdiction_resolution_source` records how the group was decided:
1. `EXPLICIT` — caller-supplied jurisdiction / country / exchange.
2. `SECURITIES_MASTER` — `persistence.get_global_security(ticker)` row's
   `exchange_code` / `country` (injected as a lookup callable; the module stays pure).
3. `TICKER_HEURISTIC` — ticker suffix/prefix (`.NS`/`NSE:` → India, `.L`/etc → ROW).
4. `UNKNOWN_FAIL_CLOSED` — none of the above; spot-only.

## Result contract (`validate_leverage_policy`)
`allowed`, `ceiling`, `actual_leverage`, `breach`, `severity`
(`NONE` / `WARNING` / `POLICY_BREACH`), `jurisdiction_group`,
`jurisdiction_resolution_source`, `reason`, plus constant advisory stamps
(`advisory_only=True`, `human_execution_required=True`, `broker_api_called=False`).

## Journal, not blocker
A breaching trade is **still recorded** (it is a journal of what the human did)
but stamped `leverage_breach=True` with severity + reason, persisted on the
`manual_trades` row, returned by `POST /manual-trades`, and shown on the Manual
Trade Log card as a "Policy breach" warning.

## Tests
`tests/test_leverage_governance.py`, `…_securities_master.py`,
`…_securities_master_api.py`, `tests/test_leverage_governance_api.py`,
and the breach/precedence cases in `tests/test_core_engine_behavior.py`.
