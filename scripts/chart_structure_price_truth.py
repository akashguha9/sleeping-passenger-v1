"""
Generic Chart Structure price-truth layer.

Purpose
-------
The Chart Structure page renders daily-candle OHLCV technicals.  A daily
close from yesterday's candle is NOT the same number as today's Yahoo
delayed quote, and silently treating it as if it were causes the
operator to mis-read the symbol's current state.  This module is the
symbol-agnostic computation that fuses both signals so the UI can tell
them apart for every ticker the user enters — not just one.

Inputs (per request)
--------------------
- ``symbol``                — user-entered ticker (any exchange suffix).
- ``daily_close``           — close of the selected latest daily candle.
- ``daily_candle_utc``      — ISO-8601 timestamp of that candle.
- ``freshness_latest_utc``  — ISO-8601 timestamp the freshness gate
                              chose as ``latest_candle_utc``.  When the
                              two timestamps disagree we emit
                              ``INTERNAL_TIMESTAMP_MISMATCH`` so the
                              frontend warns instead of rendering a
                              normal verdict over inconsistent fields.
- ``quote_fetcher``         — callable that returns the latest delayed
                              quote.  Defaults to a thin wrapper around
                              ``scripts.yahoo_market_data_adapter`` so
                              this module reuses the existing
                              integration instead of duplicating one.

Outputs (always present)
------------------------
The returned dict includes the fields the API response promises:

* ``latest_daily_close`` / ``latest_daily_candle_utc``
* ``latest_quote_price`` / ``latest_quote_currency`` / ``latest_quote_timestamp_utc``
* ``latest_quote_source``         — e.g. ``yahoo_finance``
* ``quote_freshness_status`` / ``quote_freshness_gate`` / ``quote_age_minutes``
* ``quote_price_delta`` / ``quote_price_delta_pct``
* ``price_truth_status``          — DAILY_ONLY / QUOTE_ALIGNED /
                                    QUOTE_DIVERGES_FROM_DAILY /
                                    QUOTE_UNAVAILABLE /
                                    INTERNAL_TIMESTAMP_MISMATCH /
                                    SYMBOL_UNSUPPORTED_BY_QUOTE_SOURCE
* ``price_truth_reason``
* ``suggested_next_step``         — HUMAN_REVIEW_PRICE_MISMATCH /
                                    QUOTE_REVIEW_REQUIRED /
                                    WATCH_ONLY (when aligned).

Safety contract
---------------
Read-only.  No broker calls.  No order placement.  No
``ai_execution_count`` mutation.  Quote fetch failure is *not* an error:
the function degrades cleanly to ``QUOTE_UNAVAILABLE`` so chart-structure
still renders.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Callable

# Threshold (percent) where the quote-vs-daily delta starts being called
# out as a material divergence rather than rounded into "aligned".  2 %
# warns and 5 % is "strong" (suggested_next_step escalates).  Both are
# constants here rather than spread across the codebase so test fixtures
# can pin a deterministic boundary.
QUOTE_DIVERGENCE_WARN_PCT: float = 2.0
QUOTE_DIVERGENCE_STRONG_PCT: float = 5.0

# Status labels — stable strings the frontend pattern-matches on.
STATUS_DAILY_ONLY = "DAILY_ONLY"
STATUS_QUOTE_ALIGNED = "QUOTE_ALIGNED"
STATUS_QUOTE_DIVERGES = "QUOTE_DIVERGES_FROM_DAILY"
STATUS_QUOTE_UNAVAILABLE = "QUOTE_UNAVAILABLE"
STATUS_INTERNAL_TIMESTAMP_MISMATCH = "INTERNAL_TIMESTAMP_MISMATCH"
STATUS_SYMBOL_UNSUPPORTED = "SYMBOL_UNSUPPORTED_BY_QUOTE_SOURCE"

ALL_PRICE_TRUTH_STATUSES: frozenset[str] = frozenset(
    {
        STATUS_DAILY_ONLY,
        STATUS_QUOTE_ALIGNED,
        STATUS_QUOTE_DIVERGES,
        STATUS_QUOTE_UNAVAILABLE,
        STATUS_INTERNAL_TIMESTAMP_MISMATCH,
        STATUS_SYMBOL_UNSUPPORTED,
    }
)


def _coerce_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:  # NaN
        return None
    return out


def _parse_iso(value: Any) -> _dt.datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = _dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt


def _normalise_timestamp_for_compare(value: Any) -> str | None:
    parsed = _parse_iso(value)
    if parsed is None:
        return None
    return parsed.astimezone(_dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _quote_age_minutes(quote_ts: Any, now: _dt.datetime) -> float | None:
    parsed = _parse_iso(quote_ts)
    if parsed is None:
        return None
    delta_seconds = (now - parsed).total_seconds()
    if delta_seconds < 0:
        return None
    return round(delta_seconds / 60.0, 4)


def _default_yahoo_quote_fetcher(symbol: str) -> dict[str, Any] | None:
    """Thin wrapper around the existing Yahoo adapter.

    Returns a minimal quote dict ``{price, currency, timestamp, source}``
    or ``None`` if the adapter is unavailable / yfinance is not installed
    in this environment.  Never raises — the caller treats absence as
    ``QUOTE_UNAVAILABLE`` and keeps rendering daily-candle features.
    """
    try:
        try:
            from scripts.yahoo_market_data_adapter import fetch_yahoo_mark_row
        except ModuleNotFoundError:  # pragma: no cover - script-style fallback
            from yahoo_market_data_adapter import fetch_yahoo_mark_row  # type: ignore[no-redef]
        from scripts.runtime_common import load_current_pipeline_state
    except Exception:
        return None
    try:
        runtime_state = load_current_pipeline_state()
    except Exception:
        runtime_state = {}
    try:
        row = fetch_yahoo_mark_row(symbol, runtime_state=runtime_state)
    except Exception:
        return None
    if not isinstance(row, dict) or not row.get("ok"):
        return None
    price = _coerce_float(row.get("last_price"))
    if price is None:
        return None
    return {
        "price": price,
        "currency": str(row.get("currency") or "") or None,
        "timestamp": row.get("regular_market_time") or row.get("observed_at"),
        "source": str(row.get("source_name") or "yahoo_finance"),
    }


def compute_price_truth(
    *,
    symbol: str,
    daily_close: Any,
    daily_candle_utc: Any,
    freshness_latest_utc: Any = None,
    quote_fetcher: Callable[[str], dict[str, Any] | None] | None = None,
    now: _dt.datetime | None = None,
    divergence_warn_pct: float = QUOTE_DIVERGENCE_WARN_PCT,
) -> dict[str, Any]:
    """Symbol-agnostic price-truth computation.

    Returns a dict whose keys can be merged directly into the Chart
    Structure response.  ``daily_close`` is the selected latest daily
    candle close; ``daily_candle_utc`` is its timestamp.  Passing
    ``freshness_latest_utc`` lets the function detect the internal
    timestamp mismatch that produced "freshness says 5-14 but summary
    says 5-13" in the original screenshot.

    ``quote_fetcher`` defaults to the existing Yahoo adapter wrapper.
    Tests pass a stub so they never touch the network.
    """
    now = now or _dt.datetime.now(_dt.timezone.utc)
    symbol_norm = str(symbol or "").strip().upper()
    daily_close_val = _coerce_float(daily_close)
    daily_candle_iso = _normalise_timestamp_for_compare(daily_candle_utc)
    freshness_iso = _normalise_timestamp_for_compare(freshness_latest_utc)

    out: dict[str, Any] = {
        "symbol": symbol_norm,
        "latest_daily_close": daily_close_val,
        "latest_daily_candle_utc": daily_candle_iso,
        "latest_quote_price": None,
        "latest_quote_currency": None,
        "latest_quote_timestamp_utc": None,
        "latest_quote_source": None,
        "quote_freshness_status": None,
        "quote_freshness_gate": None,
        "quote_age_minutes": None,
        "quote_price_delta": None,
        "quote_price_delta_pct": None,
        "price_truth_status": STATUS_DAILY_ONLY,
        "price_truth_reason": "",
        "suggested_next_step": "WATCH_ONLY",
        # Safety stamps — always present.
        "advisory_status": "ADVISORY_ONLY",
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "ai_execution_count": 0,
        "execution_permission": False,
        "can_execute": False,
        "record_keeping_only": True,
    }

    # Internal consistency first — if the freshness gate and OHLCV
    # summary disagree about which candle is "latest", the whole
    # response is internally inconsistent and we surface that loudly
    # rather than picking one number and hoping.
    if (
        freshness_iso is not None
        and daily_candle_iso is not None
        and freshness_iso != daily_candle_iso
    ):
        out["price_truth_status"] = STATUS_INTERNAL_TIMESTAMP_MISMATCH
        out["price_truth_reason"] = (
            "Internal latest_candle_utc mismatch: freshness reports "
            f"{freshness_iso} but OHLCV summary reports {daily_candle_iso}."
        )
        out["suggested_next_step"] = "HUMAN_REVIEW_PRICE_MISMATCH"
        return out

    # Try to enrich with a delayed quote.  Failure is silent — we still
    # ship the daily-candle truth and label the response DAILY_ONLY.
    fetcher = quote_fetcher or _default_yahoo_quote_fetcher
    quote: dict[str, Any] | None
    try:
        quote = fetcher(symbol_norm) if symbol_norm else None
    except Exception:
        quote = None

    if quote is None:
        out["price_truth_status"] = STATUS_QUOTE_UNAVAILABLE
        out["price_truth_reason"] = (
            "Latest quote unavailable; showing latest daily candle close only."
        )
        out["suggested_next_step"] = "WATCH_ONLY"
        return out

    quote_price = _coerce_float(quote.get("price"))
    quote_ts_iso = _normalise_timestamp_for_compare(quote.get("timestamp"))
    out["latest_quote_price"] = quote_price
    out["latest_quote_currency"] = (
        str(quote.get("currency") or "") or None
    )
    out["latest_quote_timestamp_utc"] = quote_ts_iso
    out["latest_quote_source"] = str(quote.get("source") or "yahoo_finance")
    out["quote_age_minutes"] = _quote_age_minutes(quote_ts_iso, now)
    age_min = out["quote_age_minutes"]
    if age_min is None:
        out["quote_freshness_status"] = "UNKNOWN"
        out["quote_freshness_gate"] = "WARN"
    elif age_min <= 15.0:
        out["quote_freshness_status"] = "FRESH"
        out["quote_freshness_gate"] = "PASS"
    elif age_min <= 60.0 * 24.0:
        out["quote_freshness_status"] = "DELAYED"
        out["quote_freshness_gate"] = "WARN"
    else:
        out["quote_freshness_status"] = "STALE"
        out["quote_freshness_gate"] = "WARN"

    # Unsupported-symbol heuristic: the adapter returned no usable
    # price.  ``QUOTE_UNAVAILABLE`` already covers the network case; if
    # we got *here* with a None price the adapter explicitly said the
    # symbol isn't on its book.
    if quote_price is None:
        out["price_truth_status"] = STATUS_SYMBOL_UNSUPPORTED
        out["price_truth_reason"] = (
            f"Quote source did not return a price for {symbol_norm}; "
            "showing latest daily candle close only."
        )
        out["suggested_next_step"] = "WATCH_ONLY"
        return out

    if daily_close_val is None or daily_close_val <= 0:
        # No daily close to compare against — surface the quote but
        # cannot compute divergence.  Treat as DAILY_ONLY equivalent.
        out["price_truth_status"] = STATUS_DAILY_ONLY
        out["price_truth_reason"] = (
            "Latest daily close unavailable; quote shown without "
            "divergence comparison."
        )
        out["suggested_next_step"] = "WATCH_ONLY"
        return out

    delta = round(quote_price - daily_close_val, 6)
    delta_pct = round((delta / daily_close_val) * 100.0, 6)
    out["quote_price_delta"] = delta
    out["quote_price_delta_pct"] = delta_pct

    if abs(delta_pct) >= divergence_warn_pct:
        out["price_truth_status"] = STATUS_QUOTE_DIVERGES
        severity = (
            "strong"
            if abs(delta_pct) >= QUOTE_DIVERGENCE_STRONG_PCT
            else "material"
        )
        out["price_truth_reason"] = (
            f"Latest quote differs {severity}ly from latest daily "
            f"candle close ({delta_pct:+.2f}%). Treat chart features as "
            "daily-candle technicals, not live price."
        )
        out["suggested_next_step"] = "HUMAN_REVIEW_PRICE_MISMATCH"
    else:
        out["price_truth_status"] = STATUS_QUOTE_ALIGNED
        out["price_truth_reason"] = (
            f"Latest quote within {divergence_warn_pct:.1f}% of latest "
            "daily close."
        )
        out["suggested_next_step"] = "WATCH_ONLY"

    return out


__all__ = [
    "QUOTE_DIVERGENCE_WARN_PCT",
    "QUOTE_DIVERGENCE_STRONG_PCT",
    "STATUS_DAILY_ONLY",
    "STATUS_QUOTE_ALIGNED",
    "STATUS_QUOTE_DIVERGES",
    "STATUS_QUOTE_UNAVAILABLE",
    "STATUS_INTERNAL_TIMESTAMP_MISMATCH",
    "STATUS_SYMBOL_UNSUPPORTED",
    "ALL_PRICE_TRUTH_STATUSES",
    "compute_price_truth",
]
