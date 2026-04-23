# External Data Integration

This repo now has an additive external-data ingestion layer for two sources only:

- Polymarket
  - Gamma API
  - Data API
  - CLOB API read endpoints only
- Blockscout
  - explorer/API read endpoints only

## What Is Real Today

- `scripts/polymarket_gamma_adapter.py` reads public Gamma discovery endpoints and writes `runtime/polymarket_gamma_report.json`.
- `scripts/polymarket_gamma_adapter.py` can also derive a conservative watchlist-only ETIL input from public Gamma market/event data and write `runtime/signal_vocoder_etil_inputs.json`.
- `scripts/polymarket_data_adapter.py` reads public Data API trades and sampled open interest and writes `runtime/polymarket_data_report.json`.
- `scripts/polymarket_clob_adapter.py` reads public CLOB time, simplified markets, price, spread, orderbook, and price-history endpoints and writes `runtime/polymarket_clob_report.json`.
- `scripts/blockscout_adapter.py` reads Blockscout explorer/API endpoints and writes `runtime/blockscout_report.json`.
- `scripts/external_data_runtime_sync.py` aggregates those source reports into `runtime/external_data_report.json`.
- `scripts/run_diagnostics_pipeline.py --include-external-data` is the canonical full-pipeline path. It runs the sync first, promotes the current run to `LIVE_ETIL` only when a fresh Gamma signal input exists, and then routes that signal through SCM, action selection, and the health report.

## Canonical Command

Use this command when you want one real read-only Gamma-origin signal to enter the decision pipeline:

```powershell
python scripts\run_diagnostics_pipeline.py --summary --include-external-data
```

Notes:

- This is the path that updates `pipeline_health_report` with real-vs-seeded signal attribution for the current run.
- `scripts/pipeline_health_report.py` on its own stays seed-neutral by default; it does not auto-promote old cached external artifacts into the current run.
- If Gamma coverage is unavailable or too sparse to build a conservative watchlist candidate, `runtime/signal_vocoder_etil_inputs.json` records `signal_count=0` and the run remains synthetic.

## Truth Boundaries

- All of this is read-only and advisory.
- No order placement exists.
- No wallet signing exists.
- No live trading path was added.
- No hardcoded secrets were added.
- If an endpoint is unavailable, unauthorized, or empty, the report records that failure state instead of fabricating coverage.

## Configuration

- Config file: `config/external_data_config.json`
- Environment variables:
  - `POLY_GAMMA_BASE_URL`
  - `POLY_DATA_BASE_URL`
  - `POLY_CLOB_BASE_URL`
  - `BLOCKSCOUT_API_BASE_URL`
  - `BLOCKSCOUT_API_KEY`
  - `BLOCKSCOUT_DEFAULT_CHAIN_ID`

## Known Limits

- Blockscout routing differs between per-instance explorers and the multichain PRO API. The adapter probes the configured base URL conservatively and reports gaps instead of assuming universal support.
- Polymarket CLOB trading endpoints are intentionally excluded even though the same API also supports authenticated trading operations.
- External observation can shift the repo into `hybrid` mode, but that means external observation is present, not that execution or settlement truth exists.
