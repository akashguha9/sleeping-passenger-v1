# Discovery Backtest Runbook (Sprint 3, Track B)

**Standing caveat (applies to every number this tool prints):**
retrospective / in-sample, survivorship- and look-ahead-sensitive, NOT
predictive, NOT evidence of forward edge. Evidence of edge moves ONLY on
closed forward paper trades (T→10). If a discipline fix makes a
backtested return *lower*, that is the tool getting MORE correct.

The CI/audit sandbox is firewalled from market-data hosts, so the fetch
and the actual backtest run on **your Windows machine**. Everything else
(mapping, guards, report) is offline and fully unit-tested against
fixtures.

## One-time setup

```powershell
cd C:\path\to\sleeping-passenger-v1
pip install yfinance   # only needed for the fetch step
```

## 1. Define the universe (exchange-prefixed or Yahoo symbols)

`data\discovery_universe.txt` — one symbol per line, `#` comments allowed:

```
# operator holdings + watchlist
NASDAQ:ANET
NYSE:RTX
NSE:RELIANCE
NSE:HDFCBANK
ETR:SAP
LON:BARC
TYO:7203
KOSDAQ:035720
SPY            # plain US symbols pass through
SBIN.NS        # already-suffixed Yahoo symbols pass through
```

Unknown prefixes **fail the whole run with the full list** — nothing is
guessed or silently dropped. `TSE:` is refused as ambiguous (use `TYO:`
for Tokyo, `TSX:` for Toronto).

## 2. Fetch the pinned data snapshot (network step — your machine)

```powershell
python scripts\fetch_discovery_snapshot.py `
    --symbols-file data\discovery_universe.txt `
    --start 2024-01-01 --end 2026-06-01 `
    --out runtime\discovery_snapshot_2026-06-10.json
```

This validates every symbol BEFORE fetching, fails loud if any fetch
errors (no partial snapshots), and stamps the file with its sha256. Keep
the file: re-running the backtest against the same snapshot is
byte-identical (reproducibility is the point).

## 3. Prepare signals

`data\discovery_signals.json` — a JSON list; `ticker` must match the
snapshot's Yahoo symbol; `timestamp` is the decision date (entry uses the
first bar **on or after** it — never before):

```json
[
  {"ticker": "RELIANCE.NS", "timestamp": "2025-03-10", "score": 0.71, "signal_id": "SIG_001"},
  {"ticker": "ANET",        "timestamp": "2025-04-02", "score": 0.64, "signal_id": "SIG_002"}
]
```

## 4. Run the backtest (offline, deterministic)

```powershell
python scripts\run_discovery_backtest.py `
    --snapshot runtime\discovery_snapshot_2026-06-10.json `
    --signals data\discovery_signals.json `
    --horizon-days 20 `
    --out runtime\discovery_report_2026-06-10.json
```

## 5. Read the report — in this order

1. `methodology` — entry/exit conventions and the caveat block.
2. `coverage` — "N requested → M validated → K with clean data" plus the
   per-symbol flags (`gaps`, `suspected_splits`, `delisting_suspected`).
   A shrinking K is the tool being honest, not broken.
3. `survivorship_guard` — signals whose price series ends before the
   window closes. These are the trades that silently *vanish* in naive
   backtests (usually losers). They are counted here on purpose.
4. `results` — wins/losses/open with the caveat re-printed. There is no
   headline return without its caveat in the same view, by design.
5. `run_metadata` — date range, universe/signals/snapshot sha256 hashes,
   `run_id_sha256`. Two runs with the same hashes are byte-identical; a
   result without these hashes is an anecdote.

## Template for recording a run

```
Run: <run_id_sha256 first 16>
Snapshot: <file> (<snapshot_sha256 first 16>)   Range: <start>..<end>
Coverage: <N> requested -> <M> validated -> <K> clean
Survivorship-flagged signals: <count>
Outcomes: <closed> closed (<wins>W/<losses>L), <open> unclosed
Caveat: retrospective tooling result; NOT evidence of forward edge.
```
