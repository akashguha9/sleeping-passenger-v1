# Paper book review — TP1/TP2/runner/stop strategy

**As of 2026-06-04.** 61 positions, €50 deployed each → **€3,050 total capital.**

## Strategy applied
- TP1 = entry ×1.05 → book 50%
- TP2 = entry ×1.08 → book 30%
- Runner = 20% → let it run, marked at today's price
- Stop = entry ×0.95 (fixed, never moved to breakeven) → exits all remaining shares
- A standing stop: if −5% is tagged before any TP, the full position stops out.

## Headline results
| Metric | Value |
|---|---|
| Capital deployed | €3,050 |
| **Net P/L** | **+€14.74** |
| **Net P/L %** | **+0.48%** |
| Wins / Losses / Flat | 24 / 25 / 12 |
| Win rate | 39.3% (of 61) |
| Positions that booked a TP | 13 |
| Positions stopped at −5% | 5 |

The book is **roughly flat** (+0.48%). The €36.44 of booked take-profit gains were almost
entirely offset by small open drawdowns across the ~30 names that drifted down without
hitting a target, plus €12.50 from five −5% stop-outs.

## Where the P/L came from
**TP-booked winners (+€36.44):** ASML +4.27, AMD +4.05, SAP +4.01, TSM +3.55, BHP +3.46,
CSCO +3.16, KRX:016880 +3.05, KOSDAQ:394280 +2.97, RTX +2.46, AVGO +2.28, VALE +2.01,
INFY +0.70, RHM +0.46.

**Stopped −5% (−€12.50):** CVX, HDFCBANK, WMT, GOOGL, AMZN.

**AVGO is the textbook case for this strategy:** it ran to an all-time high of ~$481 (+16%)
on Jun 2 *after* entry — booking TP1 and TP2 — then plunged ~13% on guidance. The booked
profits turned a position that's now red (−1.7%) into a net winner (+€2.28).

## Confidence
Only a subset of the daily high/low *path* is reliably reconstructable from public web data
in this environment (every bulk/historical feed is firewalled). Each row carries a confidence
flag in `market_data.csv`.

- **High-confidence subset (10 names, €500):** net **+€8.62 = +1.72%**.
- **Low-confidence names** are mostly the thin Tokyo/Korea tickers bought 1–3 days before the
  cutoff; they sit ≈flat (entry-anchored) because clean June 2026 quotes weren't available.

## Known caveats / things to verify
- **MSFT, NVDA**: their period-high windows straddled the entry date, so I could not confirm a
  TP fired *after* entry — neutralized to "open at current" rather than crediting a take-profit.
- **HDFCBANK**: scored as a −5% stop, but its low may predate entry; could be only ≈−3%.
- **ETR:XAD5**: instrument ambiguous, no reliable quote — treated flat.
- **ASML / AMD**: big booked winners but on low-confidence (mixed EUR/USD or thin) data.
- FX between entry and today is ignored (P/L = local return × €50).

## Files
- `positions.csv` — the 61 entries (date, exchange, ticker, entry, currency)
- `market_data.csv` — gathered current price + period high/low + confidence per ticker
- `engine.py` — deterministic strategy simulator (`python3 engine.py`)
