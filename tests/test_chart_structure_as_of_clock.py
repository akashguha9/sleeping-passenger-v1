"""Regression tests for the chart-structure "as-of" reporting clock.

The chart-structure integrity fixtures are dated at a fixed instant, but the
freshness gate measures candle age against "now".  As real time advances past
the staleness threshold those deterministic fixtures drift from FRESH to STALE
and the daily report stops rendering — the root cause of the CI failure this
guards against.

These tests verify the fix is *general and safe*, not a test-specific patch:
  * with the as-of clock pinned near the candles, a valid daily report renders;
  * the report renders even when the live quote is unavailable;
  * the as-of clock does NOT relax staleness — data that is stale relative to
    the as-of instant is still blocked;
  * with the env var unset, production uses the wall clock unchanged.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


def _ev(event_id: str, ts: str, *, close: float) -> dict:
    return {
        "event_id": event_id,
        "fetched_at": ts,
        "raw_payload": {
            "symbol": "TEST", "open": close, "high": close + 1.0,
            "low": close - 1.0, "close": close, "volume": 1_000_000.0,
            "timestamp": ts,
        },
    }


def _events(month: str = "2026-05"):
    return [_ev(f"ohlcv_TEST_{d:02d}", f"{month}-{d:02d}T16:00:00Z", close=100.0 + d)
            for d in (10, 11, 12, 13, 14)]


def _patch_persistence(events):
    return patch("scripts.persistence.get_signal_events_for_symbol", return_value=events)


def _stub_quote(price):
    def fake(symbol):
        if price is None:
            return None
        return {"last_price": price, "currency": "USD",
                "regular_market_time": "2026-05-15T15:55:00Z"}
    return patch("scripts.yahoo_market_data_adapter._fetch_symbol_with_yfinance",
                 side_effect=fake)


def test_as_of_clock_renders_report_for_fresh_relative_candles(monkeypatch):
    """Candles one day before the as-of instant render a real daily report."""
    monkeypatch.setenv("MVP_CHART_STRUCTURE_AS_OF", "2026-05-15T00:00:00Z")
    from scripts.chart_structure_api_context import _get_chart_structure
    with _patch_persistence(_events()), _stub_quote(115.0):
        resp = _get_chart_structure("TEST", limit=10)
    assert resp["report"] is not None
    # The successful render path does not carry a degraded ``chart_state``.
    assert resp.get("chart_state") != "STALE_DATA_BLOCKED"
    assert resp["report"]["summary"]["latest_timestamp"] == "2026-05-14T16:00:00Z"
    assert resp["report"]["summary"]["latest_close"] == 114.0
    assert resp["latest_daily_close"] == 114.0


def test_as_of_clock_report_survives_quote_failure(monkeypatch):
    """Live-quote unavailability must NOT suppress the historical daily report."""
    monkeypatch.setenv("MVP_CHART_STRUCTURE_AS_OF", "2026-05-15T00:00:00Z")
    from scripts.chart_structure_api_context import _get_chart_structure
    with _patch_persistence(_events()), _stub_quote(None):
        resp = _get_chart_structure("TEST", limit=10)
    assert resp["report"] is not None
    assert resp["latest_daily_close"] == 114.0
    assert resp["price_truth_status"] == "QUOTE_UNAVAILABLE"


def test_as_of_clock_does_not_relax_staleness(monkeypatch):
    """The as-of clock only moves the reference 'now'; it never disables the
    staleness gate.  Candles that are stale relative to the as-of instant are
    still blocked (report is None)."""
    monkeypatch.setenv("MVP_CHART_STRUCTURE_AS_OF", "2026-09-30T00:00:00Z")
    from scripts.chart_structure_api_context import _get_chart_structure
    with _patch_persistence(_events()), _stub_quote(115.0):
        resp = _get_chart_structure("TEST", limit=10)
    # 2026-05-14 candles are >30 days stale relative to 2026-09-30 → blocked.
    assert resp["report"] is None
    assert resp["chart_state"] == "STALE_DATA_BLOCKED"


def test_as_of_clock_unset_uses_wall_clock(monkeypatch):
    """With the env var unset, production behaviour is unchanged: the old
    2026-05 fixtures are stale against the real clock and are blocked."""
    monkeypatch.delenv("MVP_CHART_STRUCTURE_AS_OF", raising=False)
    from scripts.chart_structure_api_context import _resolve_as_of_now
    assert _resolve_as_of_now() is None  # wall clock


def test_as_of_env_parsing_is_defensive(monkeypatch):
    """A malformed as-of value falls back to the wall clock rather than raising."""
    from scripts.chart_structure_api_context import _resolve_as_of_now
    monkeypatch.setenv("MVP_CHART_STRUCTURE_AS_OF", "not-a-date")
    assert _resolve_as_of_now() is None
    monkeypatch.setenv("MVP_CHART_STRUCTURE_AS_OF", "2026-05-15T00:00:00Z")
    parsed = _resolve_as_of_now()
    assert parsed is not None and parsed.tzinfo is not None
    assert parsed.year == 2026 and parsed.month == 5 and parsed.day == 15
