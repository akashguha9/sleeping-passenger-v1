# poly_data Adapter

- License boundary: `GPL-3.0 sidecar - no source code copied into MVP core`
- Mode: exported CSV sidecar only
- Inputs: `markets.csv`, `trades.csv`, `processed/trades.csv`, `orderFilled.csv`, `goldsky/orderFilled.csv`
- Output type: `PREDICTION_MARKET`
- Max action: `WATCH_ONLY`

The adapter reads exported files only. It never imports GPL source and never creates execution authority.
