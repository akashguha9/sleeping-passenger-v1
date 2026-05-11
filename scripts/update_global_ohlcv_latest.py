"""
Phase F — Incremental global OHLCV updater (advisory-only).

Fetches recent candles (default: last 10 calendar days) for all known global
securities and upserts them. Safe for polling — idempotent via stable event IDs.

yfinance is imported lazily — safe to import without yfinance installed.

ADVISORY ONLY — No broker API. No execution. No order placement. No private keys.

Usage
-----
    python scripts/update_global_ohlcv_latest.py --interval 1d --lookback-days 10 --write
    python scripts/update_global_ohlcv_latest.py --symbols SBIN.NS,2002.TW --write
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_DEFAULT_INTERVAL: str = "1d"
_DEFAULT_LOOKBACK_DAYS: int = 10


def _period_from_days(days: int) -> str:
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
            "Phase F: Incremental global OHLCV updater (advisory-only).\n"
            "Fetches recent candles for all or specified global securities. "
            "Safe for 5-minute polling. Idempotent. No broker API."
        ),
    )
    parser.add_argument(
        "--symbols",
        default="",
        help="Comma-separated symbols (default: all in global_securities table)",
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
        help="Calendar days to fetch (default: 10)",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Persist to DB (default: dry-run)",
    )
    args = parser.parse_args(argv)

    period = _period_from_days(args.lookback_days)
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    if not symbols:
        try:
            try:
                from scripts.persistence import search_global_securities
            except ModuleNotFoundError:
                from persistence import search_global_securities  # type: ignore[no-redef]
            rows = search_global_securities("%", limit=500)
            symbols = [r["canonical_symbol"] for r in rows if r.get("active", True)]
        except Exception as exc:
            print(f"WARNING: could not load symbols from DB: {exc}", file=sys.stderr)
            symbols = ["SBIN.NS", "RELIANCE.NS", "2002.TW", "SPY"]

    if not args.write:
        print("[dry-run] No DB writes. Use --write to persist.", file=sys.stderr)

    try:
        try:
            from scripts.backfill_global_ohlcv import backfill_symbol
        except ModuleNotFoundError:
            from backfill_global_ohlcv import backfill_symbol  # type: ignore[no-redef]
    except ImportError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    total_fetched = total_inserted = 0
    for sym in symbols:
        try:
            fetched, inserted = backfill_symbol(
                sym,
                period=period,
                interval=args.interval,
                write=args.write,
                discover=False,
            )
            total_fetched += fetched
            total_inserted += inserted
            if args.write:
                print(
                    f"  {sym}: {fetched} fetched, {inserted} new, "
                    f"{fetched - inserted} existing"
                )
        except Exception as exc:
            print(f"  WARNING: {sym} failed: {exc}", file=sys.stderr)

    if args.write:
        print(
            f"Update complete: {total_fetched} fetched, {total_inserted} new candles "
            f"across {len(symbols)} symbols."
        )
    else:
        print(
            f"[dry-run] {total_fetched} candles across {len(symbols)} symbols.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
