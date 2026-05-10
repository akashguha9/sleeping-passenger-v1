"""
Phase E.3 — Real OHLCV historical backfill (advisory-only, read-only).

Fetches full OHLCV history for specified symbols via yfinance (free, no API key
required). Stores each daily candle as a signal_events row (source_name='market_data').

Event IDs are stable:  ohlcv_{symbol}_{interval}_{YYYY-MM-DD}
Re-running is fully idempotent — INSERT OR IGNORE means a repeated run inserts 0 new rows.

ADVISORY ONLY — No broker API. No execution. No order placement. No private keys.
Every stored record carries:
  advisory_status    = ADVISORY_ONLY
  execution_gate     = LOCKED
  human_review_required = True
  ai_execution_count = 0
  broker_api_called  = False
  broker_order_id    = NONE

Usage
-----
    # Dry-run (prints JSON to stdout, no DB write):
    python scripts/backfill_ohlcv_history.py --symbols AAPL,GLD,TLT,BTC-USD,SPY --period max --interval 1d

    # Real historical backfill (writes to runtime/mvp_local.db):
    python scripts/backfill_ohlcv_history.py --symbols AAPL,GLD,TLT,BTC-USD,SPY --period max --interval 1d --write

If yfinance is not installed the script exits with a clear install command.
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

_DEFAULT_SYMBOLS: list[str] = ["AAPL", "GLD", "TLT", "BTC-USD", "SPY"]
_DEFAULT_PERIOD: str = "max"
_DEFAULT_INTERVAL: str = "1d"


# ---------------------------------------------------------------------------
# Event ID
# ---------------------------------------------------------------------------

def _symbol_clean(symbol: str) -> str:
    return symbol.replace("-", "_").replace("/", "_").lower()


def event_id(symbol: str, interval: str, date_str: str) -> str:
    """Stable event ID: ohlcv_{symbol}_{interval}_{YYYY-MM-DD}.

    Safe for INSERT OR IGNORE idempotency across repeated runs.
    Distinct from seed script IDs (seed_ohlcv_*) so both can coexist.
    """
    return f"ohlcv_{_symbol_clean(symbol)}_{interval}_{date_str}"


# ---------------------------------------------------------------------------
# Candle builder
# ---------------------------------------------------------------------------

def _build_candle(symbol: str, interval: str, ts: str, row: object) -> dict:
    """Build an advisory-stamped candle dict from a yfinance history row."""
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
        "source": "yahoo_backfill",
        "advisory_status": _ADVISORY_STATUS,
        "execution_gate": _EXECUTION_GATE,
        "human_review_required": True,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "broker_api_called": False,
        "broker_order_id": "NONE",
    }


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_candles(
    symbol: str,
    period: str = _DEFAULT_PERIOD,
    interval: str = _DEFAULT_INTERVAL,
) -> list[dict]:
    """Fetch OHLCV candles for *symbol* via yfinance. Returns list of advisory-stamped dicts.

    Exits with a clear error if yfinance is not installed.
    No network call occurs when this module is imported — only when this function is called.
    """
    try:
        import yfinance as yf  # lazy import — advisory read-only data fetch
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
        print(
            f"  WARNING: no data returned for {symbol} "
            f"(period={period}, interval={interval})",
            file=sys.stderr,
        )
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


# ---------------------------------------------------------------------------
# Persist
# ---------------------------------------------------------------------------

def backfill_symbol(
    symbol: str,
    period: str = _DEFAULT_PERIOD,
    interval: str = _DEFAULT_INTERVAL,
    write: bool = False,
    db_path: Path | None = None,
) -> tuple[int, int]:
    """Fetch and optionally persist candles for *symbol*.

    Returns (fetched_count, inserted_count).
    inserted_count is 0 on dry-run; equals new rows on first run; 0 on repeat run.
    """
    candles = fetch_candles(symbol, period=period, interval=interval)
    fetched = len(candles)

    if not write:
        for c in candles:
            print(json.dumps(c))
        return fetched, fetched

    try:
        from scripts.persistence import insert_signal_event
    except ModuleNotFoundError:
        from persistence import insert_signal_event  # type: ignore[no-redef]

    kwargs: dict = {} if db_path is None else {"db_path": db_path}
    fetched_at = datetime.now(timezone.utc).isoformat()
    inserted = 0
    for c in candles:
        date_str = c["timestamp"][:10]
        eid = event_id(symbol, interval, date_str)
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
            "Phase E.3: Real OHLCV historical backfill (advisory-only).\n"
            "Uses yfinance (free, no API key). Idempotent via stable event IDs.\n"
            "Does NOT perform trading, order placement, or broker API calls."
        ),
    )
    parser.add_argument(
        "--symbols",
        default=",".join(_DEFAULT_SYMBOLS),
        help="Comma-separated symbol list (default: AAPL,GLD,TLT,BTC-USD,SPY)",
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
        help="Write candles to DB (default: dry-run, prints JSON to stdout)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Explicit dry-run flag (same as omitting --write)",
    )
    args = parser.parse_args(argv)

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    write = args.write and not args.dry_run

    if not write:
        print(
            "[dry-run] No DB writes. Use --write to persist real historical candles.",
            file=sys.stderr,
        )

    total_fetched = 0
    total_inserted = 0
    for sym in symbols:
        print(f"  Fetching {sym} (period={args.period}, interval={args.interval}) ...")
        fetched, inserted = backfill_symbol(
            sym,
            period=args.period,
            interval=args.interval,
            write=write,
        )
        total_fetched += fetched
        total_inserted += inserted
        if write:
            skipped = fetched - inserted
            print(f"  {sym}: {fetched} fetched, {inserted} new inserted, {skipped} existing/skipped")

    if write:
        print(
            f"Backfill complete. "
            f"Total: {total_fetched} fetched, {total_inserted} new candles inserted."
        )
    else:
        print(
            f"[dry-run] {total_fetched} total candles across {len(symbols)} symbols. "
            "Use --write to persist.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
