# Temporal integrity

Enforced by `scripts/temporal_guard.py` (proofs: `tests/test_temporal_guard.py`).
Every evaluation sample must satisfy:

```
t_published ≤ t_observed ≤ t_decision < t_outcome
```

Violations mark the sample INVALID with recorded reasons — never silently
dropped (that hides bias) and never silently kept (that *is* bias). The
only escape is `override_sample(...)` which demands a written reason and
writes a tamper-evident audit event.

## Lookahead bias, worked example

You evaluate a "buy on filing language" signal for 2025-11-03. ACME's
earnings beat was published 2025-11-03 **17:30 UTC**; your signal stamp
is 12:00 UTC. If the earnings row carries only a date (no time, or a
naive timestamp parsed as midnight IST), the backtest happily feeds the
beat into the noon decision — your hit rate inflates with information no
real decision could have had. The guard refuses naive timestamps
outright and rejects `t_published > t_decision`.

A subtler variant: **revised financials**. The Q2 figure you scored in
August gets restated in October; the data vendor overwrites the row,
keeping its original ID. Re-running the backtest now scores August
decisions against October numbers. Detection: `t_published > t_observed`
(the system "saw" the value before its current publication stamp) —
flagged as revision leakage.

Timezones are leakage-sized: 09:00 IST is 03:30 UTC; 09:00 CET is 08:00
UTC. A "published the morning before" Indian filing read as CET is off
by 4.5 hours — sometimes exactly the hours that decide whether the
information was knowable. Hence: aware timestamps only, everything
normalized to UTC (test: `test_timezone_conversion_ist_cet_utc`).

## Survivorship bias, worked example

You backtest "my watchlist tickers" over two years — but the watchlist
is *today's* watchlist. Everything that crashed got removed along the
way, so the universe itself encodes the outcomes. Correct procedure: the
candidate universe for date *t* must be reconstructed **as of** *t*
(the signal ledger keeps entry/exit history for this). The same applies
to journaling: post-mortems written only for trades you remember fondly
make the moltbook a survivorship sample — reconciliation counts *all*
manual trades for exactly this reason.

## Where the guard is wired

- `scripts/backtest_advisory_signals.py` runs every sample through
  `filter_evaluation_samples` and reports the reject list in the result.
- `scripts/data_quality.py` refuses `observed_at < published_at` and all
  naive timestamps at ingestion time.
- Legacy backtests (`backtest_calibration.py`) were already
  no-lookahead by construction (`history[:i+1]`); the guard adds the
  same protection to anything sample-shaped.
