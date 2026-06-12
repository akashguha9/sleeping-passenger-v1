"""Sprint I patch — integration tests for the chart-structure API context.

These tests are about the *contract* of _get_chart_structure as the
single source of truth for "latest candle":

  - The freshness gate's `latest_candle_utc`, the engine's
    `summary.latest_timestamp`, the price-truth layer's
    `latest_daily_candle_utc`, and the top-level `latest_candle_utc`
    must all be the same string for the same request.

  - When candles for the latest calendar day fail strict OHLCV
    validation (e.g., high < low), the response must NOT show
    freshness pointing at the latest day while the summary points at
    the prior day — the `selected_candles` pipeline drops the invalid
    row BEFORE freshness sees it, so both layers agree by construction.

  - Currency resolution falls through PROVIDER → MARKET_METADATA →
    SYMBOL_SUFFIX_FALLBACK → UNKNOWN and the response carries
    `display_currency` / `currency_source` for the frontend.

The tests stub persistence (get_signal_events_for_symbol) and the
Yahoo quote fetcher so no network or DB is touched.

Clock discipline: the route runs a wall-clock-relative freshness gate
(DELAYED at 10d, STALE at 30d -> report becomes None). Fixture dates
are therefore DERIVED from the current clock — hardcoded calendar
dates here are time bombs that detonate one per day as each crosses
the staleness horizon (this file's original 2026-05-1x fixtures did
exactly that).
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

# Anchor: yesterday at 16:00 UTC — always in the past, always far
# inside the FRESH window regardless of when the suite runs.
_ANCHOR = (
    datetime.now(timezone.utc) - timedelta(days=1)
).replace(hour=16, minute=0, second=0, microsecond=0)


def _day(offset: int, *, hour: int = 16) -> str:
    """ISO timestamp ``offset`` days before the anchor day."""
    stamp = (_ANCHOR - timedelta(days=offset)).replace(hour=hour)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


# The five-day fixture ladder (oldest -> newest) used across tests.
D4, D3, D2, D1, D0 = (_day(o) for o in (4, 3, 2, 1, 0))
_QUOTE_TS = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ev(event_id: str, ts: str, *, close: float, high: float | None = None,
        low: float | None = None, open_: float | None = None,
        volume: float = 1_000_000.0) -> dict:
    """Build a synthetic signal_events row.  Helper for the tests below."""
    h = high if high is not None else max(close, (open_ or close)) + 1.0
    lo = low if low is not None else min(close, (open_ or close)) - 1.0
    o = open_ if open_ is not None else close
    return {
        "event_id": event_id,
        "fetched_at": ts,
        "raw_payload": {
            "symbol": "TEST",
            "open": o,
            "high": h,
            "low": lo,
            "close": close,
            "volume": volume,
            "timestamp": ts,
        },
    }


def _ladder(prefix: str = "ohlcv_TEST", base_close: float = 100.0) -> list[dict]:
    """Five consecutive daily candles ending at the anchor day."""
    return [
        _ev(f"{prefix}_{4 - offset}", _day(offset),
            close=base_close + (4 - offset))
        for offset in (4, 3, 2, 1, 0)
    ]


def _patch_persistence(events: list[dict]):
    """Patch the persistence accessor used by _get_chart_structure."""
    return patch(
        "scripts.persistence.get_signal_events_for_symbol",
        return_value=events,
    )


def _stub_quote_fetcher(price: float | None = None, currency: str = "USD",
                       timestamp: str | None = None):
    """Replace the Yahoo adapter with a deterministic fetcher."""
    quote_ts = timestamp or _QUOTE_TS

    def fake_fetch(symbol):
        if price is None:
            return None
        return {
            "last_price": price,
            "currency": currency,
            "regular_market_time": quote_ts,
        }

    return patch(
        "scripts.yahoo_market_data_adapter._fetch_symbol_with_yfinance",
        side_effect=fake_fetch,
    )


# ---------------------------------------------------------------------------
# Single source of truth — freshness and OHLCV summary report the same ts
# ---------------------------------------------------------------------------


def test_freshness_and_summary_agree_on_latest_candle_utc():
    """Every "latest candle" field in the response must point at the
    same timestamp.  This is the regression the original Sprint I
    patch missed."""
    from scripts.chart_structure_api_context import _get_chart_structure

    with _patch_persistence(_ladder()), _stub_quote_fetcher(price=115.0):
        resp = _get_chart_structure("TEST", limit=10)

    expected = D0
    assert resp["latest_candle_utc"] == expected
    assert resp["freshness"]["latest_candle_utc"] == expected
    assert resp["report"]["summary"]["latest_timestamp"] == expected
    assert resp["latest_daily_candle_utc"] == expected
    assert resp["price_truth"]["latest_daily_candle_utc"] == expected


def test_invalid_latest_candle_is_dropped_before_freshness_sees_it():
    """The screenshot bug: a latest-day row with high < low was
    silently dropped by the engine validator but the freshness gate
    happily reported it as latest_candle_utc.  Pre-validation in
    _validate_and_dedupe_candles makes both layers see the same set."""
    from scripts.chart_structure_api_context import _get_chart_structure

    events = [
        _ev("ohlcv_TEST_prior", D1, close=100.0),
        # Latest-day candle has high < low — engine validator rejects it.
        {
            "event_id": "ohlcv_TEST_latest_bad",
            "fetched_at": D0,
            "raw_payload": {
                "symbol": "TEST",
                "open": 100.0,
                "high": 90.0,     # invalid: high < low
                "low": 110.0,
                "close": 100.0,
                "volume": 1_000_000.0,
                "timestamp": D0,
            },
        },
    ]
    with _patch_persistence(events), _stub_quote_fetcher(price=101.0):
        resp = _get_chart_structure("TEST", limit=10)

    # Both layers report the prior day because the latest row was
    # rejected.  No internal mismatch is ever surfaced because the data
    # the freshness gate sees and the data the engine sees are the same.
    assert resp["latest_candle_utc"] == D1
    assert resp["freshness"]["latest_candle_utc"] == D1
    assert resp["report"]["summary"]["latest_timestamp"] == D1
    assert resp.get("chart_state") != "INTERNAL_DATA_CONSISTENCY_ERROR"


def test_dedupe_keeps_latest_per_date():
    """Two candles for the same calendar day — keep the lexicographically
    latest timestamp string.  Daily-candle datasets must have exactly
    one row per date."""
    from scripts.chart_structure_api_context import _get_chart_structure

    events = [
        _ev("ohlcv_TEST_prior", D1, close=100.0),
        # First latest-day candle, fetched in the morning.
        _ev("ohlcv_TEST_latest_am", _day(0, hour=10), close=104.0),
        # Second latest-day candle, fetched at close — the keeper.
        _ev("ohlcv_TEST_latest_pm", D0, close=110.0),
    ]
    with _patch_persistence(events), _stub_quote_fetcher(price=110.5):
        resp = _get_chart_structure("TEST", limit=10)

    assert resp["latest_candle_utc"] == D0
    assert resp["report"]["summary"]["latest_close"] == 110.0


# ---------------------------------------------------------------------------
# Currency resolution — provider → metadata → suffix → UNKNOWN
# ---------------------------------------------------------------------------


def test_currency_from_provider_wins():
    """Quote currency from provider beats every other source."""
    from scripts.chart_structure_api_context import _get_chart_structure

    events = [_ev("ohlcv_TEST_latest", D0, close=100.0)]
    with _patch_persistence(events), _stub_quote_fetcher(price=101.0, currency="JPY"):
        resp = _get_chart_structure("ABCXYZ", limit=5)

    assert resp["display_currency"] == "JPY"
    assert resp["currency_source"] == "PROVIDER"
    assert resp["latest_daily_close_currency"] == "JPY"


def test_currency_suffix_fallback_inr_for_ns():
    """No provider currency → fall back to symbol suffix.  .NS → INR."""
    from scripts.chart_structure_api_context import _get_chart_structure

    events = [_ev("ohlcv_TEST_latest", D0, close=1789.20)]
    with _patch_persistence(events), _stub_quote_fetcher(price=1905.40, currency=""):
        resp = _get_chart_structure("BHARTIARTL.NS", limit=5)

    assert resp["display_currency"] == "INR"
    assert resp["currency_source"] in {"MARKET_METADATA", "SYMBOL_SUFFIX_FALLBACK"}


def test_currency_suffix_fallback_eur_for_de():
    from scripts.chart_structure_api_context import _get_chart_structure

    events = [_ev("ohlcv_TEST_latest", D0, close=165.0)]
    with _patch_persistence(events), _stub_quote_fetcher(price=170.0, currency=""):
        resp = _get_chart_structure("SAP.DE", limit=5)

    assert resp["display_currency"] == "EUR"


def test_currency_suffix_fallback_usd_for_bare_ticker():
    from scripts.chart_structure_api_context import _get_chart_structure

    events = [_ev("ohlcv_TEST_latest", D0, close=180.0)]
    with _patch_persistence(events), _stub_quote_fetcher(price=181.0, currency=""):
        resp = _get_chart_structure("AAPL", limit=5)

    assert resp["display_currency"] == "USD"


def test_currency_unknown_when_no_clues():
    """Symbol like '.XYZ' with no provider/metadata → currency UNKNOWN
    rather than a hardcoded fallback."""
    from scripts.chart_structure_api_context import _resolve_display_currency

    cur, src = _resolve_display_currency("WEIRD.XYZ", None, None)
    assert cur is None
    assert src == "UNKNOWN"


# ---------------------------------------------------------------------------
# BHARTIARTL.NS divergence — end-to-end
# ---------------------------------------------------------------------------


def test_bhartiartl_end_to_end_divergence():
    """Full screenshot scenario: daily 1789.20, Yahoo quote 1905.40,
    INR currency, 6.49 % divergence, HUMAN_REVIEW_PRICE_MISMATCH."""
    from scripts.chart_structure_api_context import _get_chart_structure

    events = [
        _ev(f"ohlcv_BHARTIARTL_{4 - offset}", _day(offset),
            close=1789.20 if offset == 0 else 1780.0 + (4 - offset))
        for offset in (4, 3, 2, 1, 0)
    ]
    with _patch_persistence(events), _stub_quote_fetcher(
        price=1905.40, currency="INR",
    ):
        resp = _get_chart_structure("BHARTIARTL.NS", limit=10)

    assert resp["latest_daily_close"] == 1789.20
    assert resp["latest_quote_price"] == 1905.40
    assert resp["latest_quote_currency"] == "INR"
    assert resp["display_currency"] == "INR"
    assert resp["price_truth_status"] == "QUOTE_DIVERGES_FROM_DAILY"
    assert resp["suggested_next_step"] == "HUMAN_REVIEW_PRICE_MISMATCH"
    assert resp["quote_price_delta"] == pytest.approx(116.20, abs=1e-3)
    assert resp["quote_price_delta_pct"] > 5.0
    # Safety stamps preserved.
    assert resp["advisory_status"] == "ADVISORY_ONLY"
    assert resp["execution_gate"] == "LOCKED"
    assert resp["broker_api_called"] is False
    assert resp["ai_execution_count"] == 0


# ---------------------------------------------------------------------------
# Quote unavailable degrades but report still renders
# ---------------------------------------------------------------------------


def test_quote_unavailable_still_renders_daily_report():
    from scripts.chart_structure_api_context import _get_chart_structure

    with _patch_persistence(_ladder()), _stub_quote_fetcher(price=None):
        resp = _get_chart_structure("TEST", limit=10)

    assert resp["report"] is not None
    assert resp["latest_daily_close"] == 104.0
    assert resp["price_truth_status"] == "QUOTE_UNAVAILABLE"
    assert resp["latest_quote_price"] is None


# ---------------------------------------------------------------------------
# Freshness gate: stale data nulls the report SAFELY (regression for the
# time-bomb this file used to be — pinned dates crossing the 30d horizon)
# ---------------------------------------------------------------------------


def test_stale_candles_degrade_to_safe_response_not_crash():
    from scripts.chart_structure_api_context import _get_chart_structure

    stale = [
        _ev(f"ohlcv_TEST_stale_{offset}", _day(offset), close=100.0)
        for offset in (45, 44, 43)  # well past the 30-day STALE horizon
    ]
    with _patch_persistence(stale), _stub_quote_fetcher(price=101.0):
        resp = _get_chart_structure("TEST", limit=10)

    assert resp["report"] is None  # stale-safe response, not a report
    assert resp["freshness"]["freshness_gate"] == "BLOCK"
    assert resp["chart_state"] == "STALE_DATA_BLOCKED"
    assert resp["advisory_status"] == "ADVISORY_ONLY"
    assert resp["execution_gate"] == "LOCKED"


# ---------------------------------------------------------------------------
# Safety: broker stamps preserved across every code path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("symbol,have_quote", [
    ("AAPL", True), ("AAPL", False), ("BHARTIARTL.NS", True), ("EMPTY.XX", False),
])
def test_safety_stamps_always_present(symbol, have_quote):
    from scripts.chart_structure_api_context import _get_chart_structure

    quote_stub = _stub_quote_fetcher(price=110.5 if have_quote else None)
    with _patch_persistence(_ladder()), quote_stub:
        resp = _get_chart_structure(symbol, limit=10)

    assert resp["advisory_status"] == "ADVISORY_ONLY"
    assert resp["execution_gate"] == "LOCKED"
    assert resp["human_review_required"] is True
    assert resp["ai_execution_count"] == 0
    assert resp["broker_api_called"] is False
    assert resp["broker_order_id"] == "NONE"
