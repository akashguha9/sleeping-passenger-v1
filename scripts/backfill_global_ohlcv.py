"""
Phase F — Global OHLCV historical backfill (advisory-only).

Fetches full OHLCV history for global securities via yfinance and stores each
daily candle as a signal_events row (source_name='market_data').
Also upserts security metadata into global_securities via discovery.

Event IDs are stable: ohlcv_{symbol}_{interval}_{YYYY-MM-DD}
Re-running is fully idempotent — INSERT OR IGNORE means 0 new rows on repeat.

yfinance is imported lazily — safe to import without yfinance installed.
No network calls occur until backfill_symbol() is called.

ADVISORY ONLY — No broker API. No execution. No order placement. No private keys.
Every stored record carries:
  advisory_status      = ADVISORY_ONLY
  execution_gate       = LOCKED
  human_review_required = True
  ai_execution_count   = 0
  broker_api_called    = False
  broker_order_id      = NONE

Usage
-----
    # Dry-run:
    python scripts/backfill_global_ohlcv.py --symbols SBIN.NS,2002.TW --period max --interval 1d

    # Write:
    python scripts/backfill_global_ohlcv.py --symbols SBIN.NS,2002.TW --period max --interval 1d --write

    # All securities in DB:
    python scripts/backfill_global_ohlcv.py --all-known --period max --interval 1d --write
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_ADVISORY_STATUS = "ADVISORY_ONLY"
_EXECUTION_GATE = "LOCKED"
_AI_EXECUTION_COUNT = 0

_DEFAULT_SYMBOLS: list[str] = ["SBIN.NS", "RELIANCE.NS", "2002.TW", "2330.TW", "SPY"]
_DEFAULT_PERIOD: str = "max"
_DEFAULT_INTERVAL: str = "1d"


# ---------------------------------------------------------------------------
# Re-use event_id + candle builder from backfill_ohlcv_history
# ---------------------------------------------------------------------------

def _symbol_clean(symbol: str) -> str:
    return symbol.replace("-", "_").replace("/", "_").lower()


def event_id(symbol: str, interval: str, date_str: str) -> str:
    return f"ohlcv_{_symbol_clean(symbol)}_{interval}_{date_str}"


def _build_candle(symbol: str, interval: str, ts: str, row: object) -> dict:
    open_ = float(getattr(row, "Open", None) or row.get("Open", 0.0) or 0.0)  # type: ignore[union-attr]
    high = float(getattr(row, "High", None) or row.get("High", 0.0) or 0.0)  # type: ignore[union-attr]
    low = float(getattr(row, "Low", None) or row.get("Low", 0.0) or 0.0)  # type: ignore[union-attr]
    close = float(getattr(row, "Close", None) or row.get("Close", 0.0) or 0.0)  # type: ignore[union-attr]
    volume = float(getattr(row, "Volume", None) or row.get("Volume", 0.0) or 0.0)  # type: ignore[union-attr]
    return {
        "symbol": symbol.upper(),
        "interval": interval,
        "timestamp": ts,
        "open": round(open_, 6),
        "high": round(high, 6),
        "low": round(low, 6),
        "close": round(close, 6),
        "volume": volume,
        "source": "yahoo_global_backfill",
        "advisory_status": _ADVISORY_STATUS,
        "execution_gate": _EXECUTION_GATE,
        "human_review_required": True,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "broker_api_called": False,
        "broker_order_id": "NONE",
    }


def fetch_candles(
    symbol: str,
    period: str = _DEFAULT_PERIOD,
    interval: str = _DEFAULT_INTERVAL,
) -> list[dict]:
    """Fetch OHLCV candles via yfinance. No network call until this function is called."""
    try:
        import yfinance as yf  # lazy import — advisory read-only
    except ImportError:
        print(
            "ERROR: yfinance is not installed.\n"
            "Install it with:\n"
            "  python -m pip install yfinance",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        hist = yf.Ticker(symbol).history(period=period, interval=interval)
    except Exception as exc:
        print(f"  WARNING: yfinance fetch failed for {symbol}: {exc}", file=sys.stderr)
        return []

    if hist is None or hist.empty:
        print(f"  WARNING: no data returned for {symbol}", file=sys.stderr)
        return []

    candles: list[dict] = []
    for idx, row in hist.iterrows():
        try:
            ts_str = str(idx)
            date_str = ts_str[:10]
            if len(date_str) < 10:
                continue
            ts = date_str + "T16:00:00Z"
        except Exception:
            continue
        candles.append(_build_candle(symbol, interval, ts, row))
    return candles


def backfill_symbol(
    symbol: str,
    period: str = _DEFAULT_PERIOD,
    interval: str = _DEFAULT_INTERVAL,
    write: bool = False,
    db_path: Path | None = None,
    discover: bool = True,
) -> tuple[int, int]:
    """Fetch + optionally persist candles and discovery metadata for *symbol*.

    Returns (fetched_count, inserted_count).
    When discover=True, also upserts security info into global_securities.
    """
    sym = symbol.strip().upper()
    candles = fetch_candles(sym, period=period, interval=interval)
    fetched = len(candles)

    if not write:
        for c in candles:
            print(json.dumps(c))
        return fetched, fetched

    # Optionally run discovery to populate global_securities
    if discover:
        try:
            try:
                from scripts.global_security_master_discovery import discover_and_upsert
            except ModuleNotFoundError:
                from global_security_master_discovery import discover_and_upsert  # type: ignore[no-redef]
            discover_and_upsert([sym], write=True, db_path=db_path)
        except Exception as exc:
            print(f"  WARNING: discovery failed for {sym}: {exc}", file=sys.stderr)

    try:
        from scripts.persistence import insert_signal_event
    except ModuleNotFoundError:
        from persistence import insert_signal_event  # type: ignore[no-redef]

    kwargs: dict = {} if db_path is None else {"db_path": db_path}
    fetched_at = datetime.now(timezone.utc).isoformat()
    inserted = 0
    for c in candles:
        date_str = c["timestamp"][:10]
        eid = event_id(sym, interval, date_str)
        ok = insert_signal_event(
            event_id=eid,
            source_name="market_data",
            raw_payload=c,
            fetched_at=fetched_at,
            **kwargs,
        )
        if ok:
            inserted += 1
    return fetched, inserted


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Phase F: Global OHLCV historical backfill (advisory-only).\n"
            "Uses yfinance (free, no API key). Idempotent. No broker API."
        ),
    )
    parser.add_argument(
        "--symbols",
        default="",
        help="Comma-separated symbol list (e.g. SBIN.NS,2002.TW,RELIANCE.NS)",
    )
    parser.add_argument(
        "--all-known",
        action="store_true",
        dest="all_known",
        help="Backfill all symbols currently in global_securities table",
    )
    parser.add_argument(
        "--period",
        default=_DEFAULT_PERIOD,
        help="yfinance period: max, 10y, 5y, 2y, 1y, 6mo, 3mo, 1mo (default: max)",
    )
    parser.add_argument(
        "--interval",
        default=_DEFAULT_INTERVAL,
        help="yfinance interval: 1d, 1wk, 1mo (default: 1d)",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write to DB (default: dry-run, prints JSON to stdout)",
    )
    parser.add_argument(
        "--no-discover",
        action="store_true",
        dest="no_discover",
        help="Skip security discovery step (only write candles)",
    )
    args = parser.parse_args(argv)

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    if args.all_known:
        try:
            from scripts.persistence import search_global_securities
        except ModuleNotFoundError:
            from persistence import search_global_securities  # type: ignore[no-redef]
        rows = search_global_securities("%", limit=500)
        symbols = list({r["canonical_symbol"] for r in rows} | set(symbols))

    if not symbols:
        symbols = _DEFAULT_SYMBOLS

    write = args.write
    if not write:
        print("[dry-run] No DB writes. Use --write to persist.", file=sys.stderr)

    total_fetched = total_inserted = 0
    for sym in symbols:
        print(f"  Fetching {sym} (period={args.period}, interval={args.interval}) ...")
        fetched, inserted = backfill_symbol(
            sym,
            period=args.period,
            interval=args.interval,
            write=write,
            discover=not args.no_discover,
        )
        total_fetched += fetched
        total_inserted += inserted
        if write:
            print(f"  {sym}: {fetched} fetched, {inserted} new, {fetched - inserted} existing")

    if write:
        print(f"Global backfill complete: {total_fetched} fetched, {total_inserted} new candles.")
    else:
        print(
            f"[dry-run] {total_fetched} candles across {len(symbols)} symbols. Use --write.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
