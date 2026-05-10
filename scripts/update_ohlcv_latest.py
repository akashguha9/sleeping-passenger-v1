"""
Phase E.3 — Incremental OHLCV updater (advisory-only, read-only).

Fetches recent candles (default: last 10 calendar days) for specified symbols
via yfinance and upserts them into the local SQLite signal_events table.

Safe to run every 5 minutes — idempotent via stable event IDs (ohlcv_{symbol}_{interval}_{date}).
Re-running after candles are already stored inserts 0 new rows (no duplicates).
Logs inserted count and skipped/existing count for each symbol.

ADVISORY ONLY — No broker API. No execution. No order placement. No private keys.

Usage
-----
    python scripts/update_ohlcv_latest.py --symbols AAPL,GLD,TLT,BTC-USD,SPY --interval 1d --lookback-days 10 --write
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_DEFAULT_SYMBOLS: list[str] = ["AAPL", "GLD", "TLT", "BTC-USD", "SPY"]
_DEFAULT_INTERVAL: str = "1d"
_DEFAULT_LOOKBACK_DAYS: int = 10


def _period_from_days(days: int) -> str:
    """Map a lookback-days integer to the nearest yfinance period string."""
    if days <= 5:
        return "5d"
    if days <= 10:
        return "10d"
    if days <= 30:
        return "1mo"
    if days <= 90:
        return "3mo"
    return "6mo"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Phase E.3: Incremental OHLCV updater (advisory-only).\n"
            "Fetches recent candles and upserts into local DB. "
            "Safe for 5-minute polling. No duplicates. No broker API."
        ),
    )
    parser.add_argument(
        "--symbols",
        default=",".join(_DEFAULT_SYMBOLS),
        help="Comma-separated symbol list (default: AAPL,GLD,TLT,BTC-USD,SPY)",
    )
    parser.add_argument(
        "--interval",
        default=_DEFAULT_INTERVAL,
        help="yfinance interval: 1d, 1wk (default: 1d)",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=_DEFAULT_LOOKBACK_DAYS,
        dest="lookback_days",
        help="Calendar days of history to fetch (default: 10)",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Persist to DB (default: dry-run, prints JSON to stdout)",
    )
    args = parser.parse_args(argv)

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    period = _period_from_days(args.lookback_days)

    try:
        from scripts.backfill_ohlcv_history import backfill_symbol
    except ModuleNotFoundError:
        from backfill_ohlcv_history import backfill_symbol  # type: ignore[no-redef]

    total_fetched = 0
    total_inserted = 0
    total_skipped = 0

    for sym in symbols:
        fetched, inserted = backfill_symbol(
            sym,
            period=period,
            interval=args.interval,
            write=args.write,
        )
        skipped = fetched - inserted
        total_fetched += fetched
        total_inserted += inserted
        total_skipped += skipped
        if args.write:
            print(
                f"  [{sym}] fetched={fetched} "
                f"inserted={inserted} skipped/existing={skipped}"
            )
        else:
            print(
                f"  [{sym}] fetched={fetched} (dry-run, no DB write)",
                file=sys.stderr,
            )

    if args.write:
        print(
            f"OHLCV incremental update complete. "
            f"Total: fetched={total_fetched} "
            f"inserted={total_inserted} "
            f"skipped={total_skipped}"
        )
    else:
        print(
            f"[dry-run] {total_fetched} total candles across {len(symbols)} symbols. "
            "Use --write to persist.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
