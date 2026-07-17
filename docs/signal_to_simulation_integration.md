# Signal → Simulation Integration (Priority 1 Bridge)

`scripts/simulation_intelligence/signal_bridge.py` turns live, canonical DB state
into a validated `MarketObservation` the council can run on — so the daily
discovery flow (or the API) can invoke the council for a ticker **without an
operator hand-typing the observation**, and without letting incomplete data look
complete. It never creates a trade action, never sizes, never executes.

## Data sources (runtime-reached)

- **Primary:** `persistence.get_ohlcv_bars(ticker)` — canonical, date-ascending
  OHLCV. Returns/volumes/price/prev_close/volatility/ADV are reconstructed from
  `adjusted_close` (fallback `close`) and `volume`. Nothing is invented.
- **Fallback:** `persistence.get_signal_events_for_symbol(ticker, "market_data")`
  — live market-data events (reversed to ascending).
- **Market:** `leverage_governance.resolve_leverage_ceiling(ticker)` →
  jurisdiction group, mapped `INDIA → "IN"`; US inferred from exchange/currency
  (NASDAQ/NYSE/USD → "US"); otherwise ROW/UNKNOWN.

## Fail-closed guarantees

- **Freshness is UNKNOWN unless the caller supplies today's session date** — the
  bridge never claims FRESH without knowing "now". Gap ≤10d → FRESH, ≤30d → AGING,
  else STALE (matching the repo's freshness thresholds). A future-dated bar → fail
  closed to UNKNOWN.
- **Every absent numeric field is recorded in `missing_fields`** (returns, price,
  volatility, adv_usd, prev_close) so the lenses fail closed with
  INSUFFICIENT_DATA rather than fabricating confidence.
- **Empty OHLCV → `ok=False`**, observation carries the missing fields, no crash.
- **Provenance preserved:** `price_source`, `latest_bar_date`, `exchange`,
  `currency`, `bridge_source` flow into `observation.provenance`.

## Parent-signal linkage

`parent_signal_id` is threaded end-to-end (`BridgeResult.parent_signal_id`), and
the council's `SimulationRequest.parent_signal_id` persists into
`simulation_runs.parent_signal_id`, so a simulation run links back to the
candidate it came from (tested, `test_bridge_db_backed`).

## API

`GET /api/simulation/observation/{ticker}?session_date=YYYY-MM-DD&parent_signal_id=…`
returns the validated observation + warnings, advisory-stamped. Fails closed (200,
`ok=false`) when the canonical data is incomplete.

## Design split

A **pure core** (`build_observation_from_bars`) is DB-free and unit-testable; a
**persistence-backed** entry point (`build_observation_for_ticker`) pulls from the
DB and calls the core. The core reuses `api_surface.build_observation` (bounded,
missing-field aware) so the bridge and the manual API path produce identical,
validated observations.
