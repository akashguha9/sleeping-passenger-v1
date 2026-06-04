# Securities Master Coverage

`scripts/securities_master_coverage.py` + `configs/securities_seed_universe.yaml`
(40 active tickers: India NSE + US/EU/UK/JP/KR), static advisory metadata.

## Metrics
- C = |resolvable| / |required|
- completeness_j = 0.20·symbol + 0.20·exchange + 0.20·country + 0.15·currency
  + 0.15·name + 0.10·asset_type; M = mean over the universe (missing → 0)
- J = |jurisdiction ∈ {INDIA, REST_OF_WORLD}| / |U|
- **S = 0.50·C + 0.30·M + 0.20·J**
Status: CRITICAL <0.50, PARTIAL <0.80, STRONG <0.95, COMPLETE_ENOUGH ≥0.95.

## Seeding (explicit only)
`python scripts/securities_master_coverage.py --seed` upserts the universe into
the runtime DB. Read-only otherwise; tests seed temp DBs. Seeded master makes
bare tickers (AAPL, RELIANCE, HSBA, 8306, 003550) resolve via SECURITIES_MASTER
in leverage governance; unknown tickers stay UNKNOWN_FAIL_CLOSED.
