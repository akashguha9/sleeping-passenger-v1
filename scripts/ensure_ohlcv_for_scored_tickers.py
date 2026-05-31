"""Increase Forward-Eligible Throughput Sprint — Phase 3: ingest OHLCV for
scored tickers that are missing an entry price.

A scored decision candidate is forward-outcome-eligible only when a *real* entry
price can be resolved from ingested OHLCV bars (see
:mod:`scripts.real_price_outcome_evidence`).  In the runtime data several scored
tickers (``NVDA``, ``TSLA``) have a valid symbol but **no OHLCV series** — so
they fail with ``MISSING_ENTRY_PRICE`` even though they carry a complete score
vector and a clean ticker.

This module closes that gap *honestly*:

* It reads the SCORED side-table vectors, resolves each to a clean symbol via the
  Phase 2 deterministic resolver, and finds the symbols that have **no** OHLCV
  series in ``signal_events`` (``source_name='market_data'``).
* It fetches OHLCV **read-only** via an injectable ``ohlcv_loader`` (the default
  uses ``yfinance`` — free, no API key, no broker).  Tests inject a fixture
  loader, so the unit suite never touches the network.
* It persists each real bar as a ``market_data`` ``signal_events`` row with a
  stable, idempotent ``event_id`` (a second run inserts 0 duplicate bars).
* It NEVER calls a broker, places an order, or unlocks execution.  It NEVER
  fabricates a price — a fetch failure is reported truthfully and the ticker
  stays ``MISSING_ENTRY_PRICE``.
* Every persisted bar is marked real (``mock_flag=false``) and carries the
  advisory-only stamps inherited from :func:`persistence.insert_signal_event`.

Entry-price validity (enforced downstream, restated here for the contract)::

    EntryPriceValid_i = I(P_entry_i not null) · I(P_entry_i > 0)
                      · I(entry_ts_i <= decision_ts_i)
                      · I(decision_ts_i - entry_ts_i <= max_lookback_days)
                      · I(price_source real) · I(mock_flag == false)
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Callable, Iterable, Mapping, Sequence

try:  # package layout
    from scripts import persistence
    from scripts.real_price_outcome_evidence import (
        DEFAULT_MAX_GAP_DAYS,
        MARKET_DATA_SOURCE,
        load_price_series,
        normalize_symbol,
        resolve_entry_price,
    )
    from scripts.score_real_signal_events import (
        SCORE_VECTOR_TABLE,
        ensure_score_vector_schema,
    )
    from scripts.real_signal_score_vector import SCORED
    from scripts.ticker_resolution import resolve_ticker
    from scripts.advisory_contract import advisory_safety_stamps
except ModuleNotFoundError:  # pragma: no cover - flat-layout fallback
    import persistence  # type: ignore[no-redef]
    from real_price_outcome_evidence import (  # type: ignore[no-redef]
        DEFAULT_MAX_GAP_DAYS,
        MARKET_DATA_SOURCE,
        load_price_series,
        normalize_symbol,
        resolve_entry_price,
    )
    from score_real_signal_events import (  # type: ignore[no-redef]
        SCORE_VECTOR_TABLE,
        ensure_score_vector_schema,
    )
    from real_signal_score_vector import SCORED  # type: ignore[no-redef]
    from ticker_resolution import resolve_ticker  # type: ignore[no-redef]
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]

# Bar provenance marker (distinct from seed/backfill so all three can coexist).
OHLCV_SOURCE_TAG = "yahoo_throughput_ingest"
DEFAULT_PERIOD = "3mo"
DEFAULT_INTERVAL = "1d"

# An ``ohlcv_loader`` returns an iterable of ``(timestamp_iso, close)`` pairs for
# a symbol, or raises / returns empty on failure.  Injected in tests.
OhlcvLoader = Callable[[str], Iterable[tuple[str, float]]]


def _symbol_clean(symbol: str) -> str:
    return symbol.replace("-", "_").replace("/", "_").replace(".", "_").lower()


def bar_event_id(symbol: str, interval: str, date_str: str) -> str:
    """Stable, idempotent event id for one ingested bar."""
    return f"ohlcv_ingest_{_symbol_clean(symbol)}_{interval}_{date_str}"


def scored_symbols(db_path: Any) -> dict[str, int]:
    """Return ``{symbol: scored_row_count}`` for SCORED side-table vectors.

    Each scored vector's ticker is resolved to a clean symbol via the Phase 2
    deterministic resolver (so ``"Tesla, Inc."`` becomes ``"TSLA"``).  Rows whose
    ticker cannot be confidently resolved are skipped (not fabricated).
    """
    ensure_score_vector_schema(db_path)
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"SELECT ticker FROM {SCORE_VECTOR_TABLE} WHERE score_status=?",
            (SCORED,),
        ).fetchall()
    finally:
        conn.close()

    out: dict[str, int] = {}
    for r in rows:
        resolved = resolve_ticker(score_vector={"ticker": r["ticker"]})["ticker"]
        sym = normalize_symbol(resolved) if resolved else None
        if sym:
            out[sym] = out.get(sym, 0) + 1
    return out


def symbols_with_ohlcv(db_path: Any) -> set[str]:
    """The set of symbols that already have at least one real OHLCV bar."""
    return set(load_price_series(db_path).keys())


def missing_entry_price_symbols(
    db_path: Any,
    *,
    as_of: str | None = None,
    max_lookback_days: float = DEFAULT_MAX_GAP_DAYS,
) -> dict[str, int]:
    """Scored symbols (with counts) lacking a usable entry price.

    When ``as_of`` is ``None`` a symbol is "missing" iff it has **no** OHLCV
    series at all.  When ``as_of`` is given a symbol is "missing" iff no real bar
    sits within ``max_lookback_days`` of that timestamp — this catches a *stale*
    series (bars exist but are too old to anchor a recent decision's entry
    price), which is the production failure mode for AAPL/MSFT here.
    """
    scored = scored_symbols(db_path)
    if as_of is None:
        have = symbols_with_ohlcv(db_path)
        return {sym: n for sym, n in scored.items() if sym not in have}

    series = load_price_series(db_path, symbols=set(scored) or None)
    missing: dict[str, int] = {}
    for sym, n in scored.items():
        ev = resolve_entry_price(
            db_path, ticker=sym, decision_timestamp_utc=as_of,
            max_lookback_days=max_lookback_days, series_by_symbol=series,
        )
        if ev is None:
            missing[sym] = n
    return missing


def _default_yfinance_loader(
    symbol: str,
    *,
    period: str = DEFAULT_PERIOD,
    interval: str = DEFAULT_INTERVAL,
) -> list[tuple[str, float]]:
    """Read-only OHLCV via yfinance (free, no key, no broker).  Never executes."""
    import yfinance as yf  # imported lazily so the unit suite need not install it

    hist = yf.Ticker(symbol).history(period=period, interval=interval)
    out: list[tuple[str, float]] = []
    for ts, row in hist.iterrows():
        close = row.get("Close")
        if close is None:
            continue
        try:
            close_f = float(close)
        except (TypeError, ValueError):
            continue
        if close_f <= 0:
            continue
        out.append((str(ts), close_f))
    return out


def _persist_bars(
    db_path: Any,
    *,
    symbol: str,
    bars: Iterable[tuple[str, float]],
    interval: str,
) -> tuple[int, int]:
    """Persist real bars idempotently.  Returns ``(bars_added, bars_skipped)``."""
    added = 0
    skipped = 0
    for ts, close in bars:
        try:
            close_f = float(close)
        except (TypeError, ValueError):
            skipped += 1
            continue
        if close_f <= 0:
            skipped += 1
            continue
        date_str = str(ts)[:10]
        eid = bar_event_id(symbol, interval, date_str)
        payload = {
            "event_id": eid,
            "source_name": MARKET_DATA_SOURCE,
            "signal_type": "market_price",
            "symbol": symbol.upper(),
            "interval": interval,
            "provider": "yahoo",
            "source": OHLCV_SOURCE_TAG,
            "timestamp": str(ts),
            "close": round(close_f, 6),
            "mock_flag": False,
            "backfill_flag": False,
        }
        is_new = persistence.insert_signal_event(
            event_id=eid,
            source_name=MARKET_DATA_SOURCE,
            raw_payload=payload,
            fetched_at=str(ts),
            db_path=db_path,
        )
        if is_new:
            added += 1
        else:
            skipped += 1
    return added, skipped


def ensure_ohlcv_for_scored_tickers(
    *,
    db_path: Any = None,
    ohlcv_loader: OhlcvLoader | None = None,
    interval: str = DEFAULT_INTERVAL,
    write: bool = True,
    only_symbols: Sequence[str] | None = None,
    as_of: str | None = None,
    max_lookback_days: float = DEFAULT_MAX_GAP_DAYS,
) -> dict[str, Any]:
    """Fetch + persist OHLCV for scored tickers missing an entry price.

    ``ohlcv_loader`` (injected in tests) maps a symbol to an iterable of
    ``(timestamp_iso, close)`` real bars; the default uses yfinance.  ``write``
    False makes the run side-effect free (it still reports what *would* be
    fetched).  Returns an honest, secret-free summary.
    """
    stamps = advisory_safety_stamps()
    target = db_path if db_path is not None else persistence.DB_PATH
    persistence.init_schema(target)
    ensure_score_vector_schema(target)

    loader = ohlcv_loader or _default_yfinance_loader

    missing_before = missing_entry_price_symbols(
        target, as_of=as_of, max_lookback_days=max_lookback_days
    )
    targets = sorted(missing_before)
    if only_symbols is not None:
        wanted = {normalize_symbol(s) for s in only_symbols}
        targets = [s for s in targets if s in wanted]

    tickers_seen = sorted(scored_symbols(target))
    tickers_fetched: list[str] = []
    failures: dict[str, str] = {}
    bars_added = 0
    bars_skipped = 0

    for sym in targets:
        try:
            bars = list(loader(sym))
        except Exception as exc:  # pragma: no cover - network/loader failure path
            failures[sym] = type(exc).__name__
            continue
        if not bars:
            failures[sym] = "NO_BARS_RETURNED"
            continue
        if not write:
            tickers_fetched.append(sym)
            continue
        added, skipped = _persist_bars(target, symbol=sym, bars=bars, interval=interval)
        bars_added += added
        bars_skipped += skipped
        if added > 0 or skipped > 0:
            tickers_fetched.append(sym)

    missing_after = (
        missing_entry_price_symbols(target, as_of=as_of, max_lookback_days=max_lookback_days)
        if write else missing_before
    )

    return {
        "tickers_seen": tickers_seen,
        "tickers_missing_ohlcv_before": sorted(missing_before),
        "tickers_missing_ohlcv_after": sorted(missing_after),
        "tickers_fetched": sorted(tickers_fetched),
        "bars_added": bars_added,
        "bars_skipped": bars_skipped,
        "failures": failures,
        "entry_price_recheck_count": len(missing_before) - len(missing_after),
        "wrote_artifacts": bool(write),
        # Honest gates — this ingester can NEVER unlock either.
        "predictive_claim_allowed": False,
        "edge_claimed": False,
        **stamps,
        "advisory_only": True,
        "human_execution_required": True,
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Ingest read-only OHLCV for scored tickers missing an entry price (advisory-only)."
    )
    p.add_argument("--write", action="store_true", help="persist fetched OHLCV bars")
    p.add_argument("--interval", default=DEFAULT_INTERVAL)
    p.add_argument("--symbols", default=None, help="comma-separated symbol allow-list")
    p.add_argument("--as-of", default=None,
                   help="decision timestamp (ISO); flags symbols whose series is stale, not just absent")
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    persistence.init_schema()
    only = [s.strip() for s in args.symbols.split(",")] if args.symbols else None
    summary = ensure_ohlcv_for_scored_tickers(
        interval=args.interval, write=bool(args.write), only_symbols=only,
        as_of=args.as_of,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))


__all__ = [
    "OHLCV_SOURCE_TAG",
    "bar_event_id",
    "scored_symbols",
    "symbols_with_ohlcv",
    "missing_entry_price_symbols",
    "ensure_ohlcv_for_scored_tickers",
    "main",
]
