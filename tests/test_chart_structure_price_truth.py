"""Tests for the symbol-agnostic Chart Structure price-truth layer.

The matrix here intentionally covers multiple markets (NSE India, US
stocks, US ETFs, European stocks, unknown tickers) so the fix cannot
regress into a per-symbol special case.  BHARTIARTL.NS is included as a
regression fixture using the screenshot values (1789.20 daily close vs
1905.40 Yahoo quote → QUOTE_DIVERGES_FROM_DAILY) but the implementation
must produce the right verdict for every other symbol too.

Safety invariants:
- no broker calls,
- no execution,
- no AI count mutation,
- advisory_status / execution_gate stay stamped.
"""
from __future__ import annotations

import datetime as _dt

import pytest

from scripts.chart_structure_price_truth import (
    QUOTE_DIVERGENCE_WARN_PCT,
    STATUS_DAILY_ONLY,
    STATUS_INTERNAL_TIMESTAMP_MISMATCH,
    STATUS_QUOTE_ALIGNED,
    STATUS_QUOTE_DIVERGES,
    STATUS_QUOTE_UNAVAILABLE,
    STATUS_SYMBOL_UNSUPPORTED,
    compute_price_truth,
)


_FROZEN_NOW = _dt.datetime(2026, 5, 15, 16, 0, 0, tzinfo=_dt.timezone.utc)


def _quote(price, *, currency="USD", timestamp="2026-05-15T15:55:00Z",
           source="yahoo_finance"):
    return lambda symbol: {
        "price": price,
        "currency": currency,
        "timestamp": timestamp,
        "source": source,
    }


def _safety_ok(result):
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["execution_gate"] == "LOCKED"
    assert result["broker_api_called"] is False
    assert result["ai_execution_count"] == 0
    assert result["execution_permission"] is False
    assert result["can_execute"] is False


# ---------------------------------------------------------------------------
# Regression fixture: BHARTIARTL.NS daily 1789.20 vs Yahoo 1905.40 ~ 6.5 %
# This is the screenshot the user filed.  The matrix below proves the
# same code path handles every other symbol too.
# ---------------------------------------------------------------------------


def test_bhartiartl_ns_regression_diverges():
    result = compute_price_truth(
        symbol="BHARTIARTL.NS",
        daily_close=1789.20,
        daily_candle_utc="2026-05-14T16:00:00Z",
        quote_fetcher=_quote(1905.40, currency="INR"),
        now=_FROZEN_NOW,
    )
    assert result["price_truth_status"] == STATUS_QUOTE_DIVERGES
    assert result["suggested_next_step"] == "HUMAN_REVIEW_PRICE_MISMATCH"
    assert result["latest_quote_currency"] == "INR"
    assert result["latest_quote_source"] == "yahoo_finance"
    assert result["quote_price_delta"] == pytest.approx(1905.40 - 1789.20, abs=1e-4)
    assert result["quote_price_delta_pct"] > 5.0
    _safety_ok(result)


# ---------------------------------------------------------------------------
# Symbol matrix — same predicate must handle every market
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "symbol,daily_close,quote_price,currency,expected",
    [
        ("ICICIBANK.NS", 950.0, 952.0, "INR", STATUS_QUOTE_ALIGNED),
        ("AAPL", 180.0, 181.5, "USD", STATUS_QUOTE_ALIGNED),
        ("AAPL", 180.0, 200.0, "USD", STATUS_QUOTE_DIVERGES),
        ("SPY", 520.0, 522.0, "USD", STATUS_QUOTE_ALIGNED),
        ("TLT", 90.0, 89.5, "USD", STATUS_QUOTE_ALIGNED),
        ("SAP.DE", 165.0, 170.0, "EUR", STATUS_QUOTE_DIVERGES),
        ("RELIANCE.NS", 2750.0, 2760.0, "INR", STATUS_QUOTE_ALIGNED),
    ],
)
def test_symbol_matrix_classifies_correctly(
    symbol, daily_close, quote_price, currency, expected
):
    result = compute_price_truth(
        symbol=symbol,
        daily_close=daily_close,
        daily_candle_utc="2026-05-14T16:00:00Z",
        quote_fetcher=_quote(quote_price, currency=currency),
        now=_FROZEN_NOW,
    )
    assert result["price_truth_status"] == expected, (symbol, result)
    assert result["latest_quote_currency"] == currency
    _safety_ok(result)


# ---------------------------------------------------------------------------
# Quote unavailable / unsupported symbol degrade gracefully
# ---------------------------------------------------------------------------


def test_quote_unavailable_falls_back_to_daily_only():
    result = compute_price_truth(
        symbol="UNKNOWN_TICKER_XYZ",
        daily_close=42.0,
        daily_candle_utc="2026-05-14T16:00:00Z",
        quote_fetcher=lambda s: None,
        now=_FROZEN_NOW,
    )
    assert result["price_truth_status"] == STATUS_QUOTE_UNAVAILABLE
    assert "Latest quote unavailable" in result["price_truth_reason"]
    assert result["latest_daily_close"] == 42.0
    _safety_ok(result)


def test_quote_fetcher_returning_none_price_is_unsupported_symbol():
    result = compute_price_truth(
        symbol="BTC-USD",
        daily_close=60000.0,
        daily_candle_utc="2026-05-14T16:00:00Z",
        # Adapter answers but cannot price this symbol.
        quote_fetcher=lambda s: {
            "price": None,
            "currency": None,
            "timestamp": None,
            "source": "yahoo_finance",
        },
        now=_FROZEN_NOW,
    )
    assert result["price_truth_status"] == STATUS_SYMBOL_UNSUPPORTED
    _safety_ok(result)


def test_quote_fetcher_exception_does_not_raise():
    def explode(symbol):
        raise RuntimeError("network down")

    result = compute_price_truth(
        symbol="AAPL",
        daily_close=180.0,
        daily_candle_utc="2026-05-14T16:00:00Z",
        quote_fetcher=explode,
        now=_FROZEN_NOW,
    )
    assert result["price_truth_status"] == STATUS_QUOTE_UNAVAILABLE
    _safety_ok(result)


# ---------------------------------------------------------------------------
# Internal timestamp consistency
# ---------------------------------------------------------------------------


def test_internal_timestamp_mismatch_is_flagged():
    # Freshness says 5-14 but the summary picked 5-13 → the response is
    # internally inconsistent and must be flagged loudly.
    result = compute_price_truth(
        symbol="BHARTIARTL.NS",
        daily_close=1789.20,
        daily_candle_utc="2026-05-13T16:00:00Z",
        freshness_latest_utc="2026-05-14T16:00:00Z",
        quote_fetcher=_quote(1905.40, currency="INR"),
        now=_FROZEN_NOW,
    )
    assert result["price_truth_status"] == STATUS_INTERNAL_TIMESTAMP_MISMATCH
    assert result["suggested_next_step"] == "HUMAN_REVIEW_PRICE_MISMATCH"
    _safety_ok(result)


def test_matching_timestamps_pass_internal_consistency():
    result = compute_price_truth(
        symbol="AAPL",
        daily_close=180.0,
        daily_candle_utc="2026-05-14T16:00:00Z",
        freshness_latest_utc="2026-05-14T16:00:00Z",
        quote_fetcher=_quote(180.5, currency="USD"),
        now=_FROZEN_NOW,
    )
    assert result["price_truth_status"] == STATUS_QUOTE_ALIGNED


# ---------------------------------------------------------------------------
# Daily close missing
# ---------------------------------------------------------------------------


def test_missing_daily_close_returns_daily_only():
    result = compute_price_truth(
        symbol="AAPL",
        daily_close=None,
        daily_candle_utc="2026-05-14T16:00:00Z",
        quote_fetcher=_quote(180.0, currency="USD"),
        now=_FROZEN_NOW,
    )
    assert result["price_truth_status"] == STATUS_DAILY_ONLY
    assert result["latest_quote_price"] == 180.0
    _safety_ok(result)


# ---------------------------------------------------------------------------
# Threshold boundary
# ---------------------------------------------------------------------------


def test_divergence_threshold_boundary():
    # Exactly at the warn threshold → diverges.
    daily = 100.0
    quote = daily * (1 + QUOTE_DIVERGENCE_WARN_PCT / 100.0)
    result = compute_price_truth(
        symbol="TEST",
        daily_close=daily,
        daily_candle_utc="2026-05-14T16:00:00Z",
        quote_fetcher=_quote(quote, currency="USD"),
        now=_FROZEN_NOW,
    )
    assert result["price_truth_status"] == STATUS_QUOTE_DIVERGES


def test_below_threshold_is_aligned():
    daily = 100.0
    quote = daily * (1 + (QUOTE_DIVERGENCE_WARN_PCT - 0.1) / 100.0)
    result = compute_price_truth(
        symbol="TEST",
        daily_close=daily,
        daily_candle_utc="2026-05-14T16:00:00Z",
        quote_fetcher=_quote(quote, currency="USD"),
        now=_FROZEN_NOW,
    )
    assert result["price_truth_status"] == STATUS_QUOTE_ALIGNED


def test_currency_never_hardcoded():
    # The function trusts the quote source's currency field.
    for cur in ("INR", "USD", "EUR", "GBP", "JPY"):
        result = compute_price_truth(
            symbol=f"FAKE.{cur}",
            daily_close=100.0,
            daily_candle_utc="2026-05-14T16:00:00Z",
            quote_fetcher=_quote(101.0, currency=cur),
            now=_FROZEN_NOW,
        )
        assert result["latest_quote_currency"] == cur
