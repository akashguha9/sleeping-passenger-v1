"""Tests — scripts/live_price_marks.py."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scripts.live_price_marks import (
    DEGRADED,
    DELAYED_BUT_USABLE,
    LIVE_VERIFIED,
    NO_LIVE_MARKS,
    NO_LIVE_MARK,
    PARTIAL,
    REASON_CURRENCY_MISMATCH,
    REASON_LIVE_MARK_FROM_YFINANCE,
    REASON_LIVE_MARK_MISSING,
    REASON_LIVE_MARK_PROVIDER_DISAGREEMENT,
    REASON_LIVE_MARK_STALE,
    REASON_NETWORK_DISALLOWED,
    REASON_NO_LIVE_MARKS,
    REASON_NO_USABLE_LIVE_MARK,
    REASON_STATIC_SYMBOL_ONLY_NO_PRICE,
    STALE_PRICE,
    LiveMark,
    LiveMarkResult,
    PROVIDER_WEIGHT_DEFAULTS,
    compute_live_mark_quality,
    fetch_live_marks,
    infer_market_from_ticker,
    live_mark_result_to_summary,
    normalize_ticker_for_market_data,
    write_live_mark_summary,
)


NOW = datetime(2026, 5, 26, 16, 0, 0, tzinfo=timezone.utc)


def _fixture_fetcher(prices: dict[str, dict]):
    def fake(symbol: str) -> dict:
        return prices.get(symbol.upper(), {"last_price": None, "currency": None})

    return fake


# ---------------------------------------------------------------------------
# Section 11 — normalize_ticker_for_market_data
# ---------------------------------------------------------------------------


def test_normalize_strips_us_exchange_prefix():
    assert normalize_ticker_for_market_data("NASDAQ:GOOGL") == "GOOGL"
    assert normalize_ticker_for_market_data("NYSE:GD") == "GD"
    assert normalize_ticker_for_market_data("GOOGL") == "GOOGL"


def test_normalize_maps_german_listing_to_yahoo_suffix():
    assert normalize_ticker_for_market_data("ETR:SAP") == "SAP.DE"
    assert normalize_ticker_for_market_data("SAP.DE") == "SAP.DE"


def test_normalize_maps_french_listing_to_yahoo_suffix():
    assert normalize_ticker_for_market_data("EPA:AIR") == "AIR.PA"
    assert normalize_ticker_for_market_data("AIR.PA") == "AIR.PA"


def test_normalize_maps_indian_listing_to_yahoo_suffix():
    assert normalize_ticker_for_market_data("NSE:HDFCBANK") == "HDFCBANK.NS"
    assert normalize_ticker_for_market_data("NSE:RELIANCE") == "RELIANCE.NS"
    assert normalize_ticker_for_market_data("HDFCBANK.NS") == "HDFCBANK.NS"


def test_normalize_class_share_uses_provider_hyphen():
    assert normalize_ticker_for_market_data("NYSE:BRK.B") == "BRK-B"


def test_normalize_blank_input_returns_empty():
    assert normalize_ticker_for_market_data("") == ""
    assert normalize_ticker_for_market_data(None) == ""


# ---------------------------------------------------------------------------
# infer_market_from_ticker
# ---------------------------------------------------------------------------


def test_infer_market_for_us_default():
    info = infer_market_from_ticker("NASDAQ:GOOGL")
    assert info.country == "United States"
    assert info.trading_currency == "USD"
    assert info.market_code in {"NASDAQ", "US"}


def test_infer_market_for_indian_listing():
    info = infer_market_from_ticker("NSE:HDFCBANK")
    assert info.country == "India"
    assert info.trading_currency == "INR"
    assert info.provider_symbol == "HDFCBANK.NS"


# ---------------------------------------------------------------------------
# Quality math (Section 4)
# ---------------------------------------------------------------------------


def test_quality_zero_when_price_missing():
    info = infer_market_from_ticker("NASDAQ:GOOGL")
    quality, freshness, currency, reasons = compute_live_mark_quality(
        price=None,
        age_hours=1.0,
        stale_after_hours=info.stale_after_hours,
        returned_currency="USD",
        expected_currency="USD",
        provider_symbol="GOOGL",
        market=info,
        provider_weight=PROVIDER_WEIGHT_DEFAULTS["existing_yfinance_provider"],
        market_closed_tolerated=True,
        ticker="GOOGL",
    )
    assert quality == 0.0
    assert freshness == 0.0


def test_quality_fresh_currency_match_is_high():
    info = infer_market_from_ticker("NASDAQ:GOOGL")
    quality, _, _, _ = compute_live_mark_quality(
        price=382.97,
        age_hours=0.5,
        stale_after_hours=info.stale_after_hours,
        returned_currency="USD",
        expected_currency="USD",
        provider_symbol="GOOGL",
        market=info,
        provider_weight=PROVIDER_WEIGHT_DEFAULTS["existing_yfinance_provider"],
        market_closed_tolerated=True,
        ticker="GOOGL",
    )
    assert quality >= 0.80


def test_quality_currency_mismatch_lowers_score_and_flags_reason():
    info = infer_market_from_ticker("NASDAQ:GOOGL")
    quality, _, currency_score, reasons = compute_live_mark_quality(
        price=382.97,
        age_hours=0.5,
        stale_after_hours=info.stale_after_hours,
        returned_currency="EUR",  # mismatch vs USD
        expected_currency="USD",
        provider_symbol="GOOGL",
        market=info,
        provider_weight=PROVIDER_WEIGHT_DEFAULTS["existing_yfinance_provider"],
        market_closed_tolerated=True,
        ticker="GOOGL",
    )
    assert currency_score == 0.0
    assert REASON_CURRENCY_MISMATCH in reasons
    assert quality < 0.80


# ---------------------------------------------------------------------------
# fetch_live_marks behaviours
# ---------------------------------------------------------------------------


def test_fetch_live_marks_no_provider_returns_no_live_marks():
    result = fetch_live_marks(
        ["NASDAQ:GOOGL"],
        allow_network=False,
        fallback_to_snapshot=False,
        now_utc=NOW,
    )
    assert result.aggregate_source_health == NO_LIVE_MARKS
    assert REASON_NO_LIVE_MARKS in result.reason_codes
    assert REASON_NETWORK_DISALLOWED in result.reason_codes
    mark = result.marks["GOOGL"]
    assert mark.live_price is None
    assert mark.is_usable is False
    assert mark.source_health == NO_LIVE_MARK
    assert REASON_LIVE_MARK_MISSING in mark.reason_codes


def test_fetch_live_marks_with_fresh_fixture_marks_live_verified():
    result = fetch_live_marks(
        ["NASDAQ:GOOGL", "ETR:SAP"],
        allow_network=False,
        fallback_to_snapshot=False,
        fetcher=_fixture_fetcher(
            {
                "GOOGL": {
                    "last_price": 382.97,
                    "currency": "USD",
                    "regular_market_time": NOW.isoformat(),
                },
                "SAP.DE": {
                    "last_price": 195.0,
                    "currency": "EUR",
                    "regular_market_time": NOW.isoformat(),
                },
            }
        ),
        ticker_metadata={
            "GOOGL": {"country": "United States", "currency": "USD"},
            "SAP": {"country": "Germany", "currency": "EUR"},
        },
        now_utc=NOW,
    )
    assert result.aggregate_source_health == LIVE_VERIFIED
    assert result.coverage_ratio == pytest.approx(1.0)
    assert result.usable_coverage_ratio == pytest.approx(1.0)
    for mark in result.marks.values():
        assert mark.is_usable is True
        assert mark.live_price is not None
        assert mark.live_mark_quality_score >= 0.80
        assert REASON_LIVE_MARK_FROM_YFINANCE in mark.reason_codes


def test_fetch_live_marks_stale_snapshot_keeps_delay_window():
    snapshot = {
        "snapshot_timestamp_utc": "2026-05-22T15:00:00Z",
        "live_marks": {"GOOGL": {"live_price": 382.97, "currency": "USD"}},
    }
    result = fetch_live_marks(
        ["NASDAQ:GOOGL"],
        allow_network=False,
        market_snapshot=snapshot,
        ticker_metadata={"GOOGL": {"country": "United States", "currency": "USD"}},
        now_utc=NOW,
    )
    mark = result.marks["GOOGL"]
    # Snapshot age ~97h; with 96h market-closed tolerance freshness is low.
    assert mark.live_price == pytest.approx(382.97)
    assert mark.source_health in {DELAYED_BUT_USABLE, PARTIAL, STALE_PRICE}


def test_fetch_live_marks_static_fallback_never_usable():
    # No provider returns a price but the snapshot lists the symbol with no
    # price → mark must remain unusable (no fabrication).
    snapshot = {
        "snapshot_timestamp_utc": "2026-05-26T15:00:00Z",
        "live_marks": {"GOOGL": {}},
    }
    result = fetch_live_marks(
        ["NASDAQ:GOOGL"],
        allow_network=False,
        market_snapshot=snapshot,
        now_utc=NOW,
    )
    mark = result.marks["GOOGL"]
    assert mark.live_price is None
    assert mark.is_usable is False


def test_fetch_live_marks_provider_disagreement():
    snapshot = {
        "snapshot_timestamp_utc": NOW.isoformat(),
        "live_marks": {
            "GOOGL": {"live_price": 380.0, "currency": "USD", "market_time": NOW.isoformat()}
        },
    }
    result = fetch_live_marks(
        ["NASDAQ:GOOGL"],
        allow_network=False,
        market_snapshot=snapshot,
        fetcher=_fixture_fetcher(
            {"GOOGL": {"last_price": 420.0, "currency": "USD", "regular_market_time": NOW.isoformat()}}
        ),
        ticker_metadata={"GOOGL": {"country": "United States", "currency": "USD"}},
        now_utc=NOW,
    )
    mark = result.marks["GOOGL"]
    assert REASON_LIVE_MARK_PROVIDER_DISAGREEMENT in mark.reason_codes
    # Consensus must still produce a number (weighted), not None.
    assert mark.live_price is not None


def test_fetch_live_marks_advisory_stamps_present():
    result = fetch_live_marks(["NASDAQ:GOOGL"], allow_network=False, now_utc=NOW)
    assert result.advisory_only is True
    assert result.broker_api_called is False
    assert result.ai_execution_count == 0
    assert result.human_execution_required is True
    assert result.execution_permission == "ADVISORY_ONLY"
    mark = next(iter(result.marks.values()))
    assert mark.advisory_only is True
    assert mark.broker_api_called is False
    assert mark.ai_execution_count == 0


def test_live_mark_result_to_summary_carries_stamps():
    result = fetch_live_marks(["NASDAQ:GOOGL"], allow_network=False, now_utc=NOW)
    summary = live_mark_result_to_summary(result)
    assert summary["advisory_only"] is True
    assert summary["broker_api_called"] is False
    assert summary["ai_execution_count"] == 0
    assert "marks" in summary
    assert "reason_codes" in summary


def test_write_live_mark_summary_creates_file(tmp_path):
    result = fetch_live_marks(["NASDAQ:GOOGL"], allow_network=False, now_utc=NOW)
    path = write_live_mark_summary(result, release_dir=tmp_path)
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "advisory_only" in text
    assert "aggregate_source_health" in text
