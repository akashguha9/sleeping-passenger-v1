"""Tests — live price / price-mover bridge (read-only, honest fallback)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from scripts import persistence
from scripts.live_price_movers_bridge import (
    build_live_price_movers,
    build_price_row,
    valid_price,
)

NOW = datetime(2026, 5, 28, 12, 0, 0, tzinfo=timezone.utc)


def _insert_candle(db, symbol, close, ts, volume=1000.0, eid=None):
    persistence.insert_signal_event(
        event_id=eid or f"{symbol}-{ts}",
        source_name="market_data",
        raw_payload={"symbol": symbol, "close": close, "volume": volume, "timestamp": ts},
        fetched_at=ts,
        db_path=db,
    )


def test_valid_price_true_when_fresh_mark_present(tmp_path):
    db = tmp_path / "t.db"
    _insert_candle(db, "MSFT", 410.0, (NOW - timedelta(minutes=30)).isoformat())
    row = build_price_row("MSFT", db_path=db, now_utc=NOW, market_state="open")
    assert row["price"] == 410.0
    assert row["valid_price"] is True
    assert row["currency"] == "USD"
    assert row["is_live"] is True


def test_null_price_when_no_mark(tmp_path):
    db = tmp_path / "t.db"  # exists but empty -> no market_data rows
    persistence.insert_signal_event(
        event_id="seed", source_name="other", raw_payload={"x": 1},
        fetched_at=NOW.isoformat(), db_path=db,
    )
    row = build_price_row("NVDA", db_path=db, now_utc=NOW, market_state="open")
    assert row["price"] is None
    assert row["valid_price"] is False
    assert row["failure_reason"] in {"MARKET_CLOSED_NO_RECENT_MARK", "PRICE_PROVIDER_UNAVAILABLE"}


def test_provider_unavailable_when_db_missing(tmp_path):
    row = build_price_row("AAPL", db_path=tmp_path / "no.db", now_utc=NOW, market_state="open")
    assert row["price"] is None
    assert row["valid_price"] is False
    assert row["failure_reason"] == "PRICE_PROVIDER_UNAVAILABLE"


def test_valid_price_formula_requires_currency_and_age():
    assert valid_price(100.0, NOW.isoformat(), "USD", 30.0, 60.0) is True
    assert valid_price(None, NOW.isoformat(), "USD", 30.0, 60.0) is False
    assert valid_price(100.0, None, "USD", 30.0, 60.0) is False
    assert valid_price(100.0, NOW.isoformat(), None, 30.0, 60.0) is False
    assert valid_price(100.0, NOW.isoformat(), "USD", 120.0, 60.0) is False


def test_holdings_separated_from_new_candidates(tmp_path):
    db = tmp_path / "t.db"
    _insert_candle(db, "MSFT", 410.0, (NOW - timedelta(minutes=10)).isoformat())
    _insert_candle(db, "NVDA", 900.0, (NOW - timedelta(minutes=10)).isoformat())
    result = build_live_price_movers(
        db, now_utc=NOW, holdings=["MSFT"], candidate_tickers=["NVDA", "MSFT"], market_state="open",
    )
    existing = [r["ticker"] for r in result["existing_position_price_review"]]
    candidates = [r["ticker"] for r in result["new_candidate_price_movers"]]
    assert existing == ["MSFT"]
    assert "NVDA" in candidates
    assert "MSFT" not in candidates  # a holding is never re-listed as a new candidate


def test_non_us_suffix_symbol_is_carried_not_dropped(tmp_path):
    db = tmp_path / "t.db"
    row = build_price_row("RELIANCE.NS", db_path=db, now_utc=NOW, market_state="closed")
    assert row["ticker"] == "RELIANCE.NS"
    assert row["currency"] == "INR"
    assert row["country"] == "India"


def test_existing_risk_visibility_degraded_when_holding_price_missing(tmp_path):
    db = tmp_path / "t.db"  # no market_data rows
    persistence.insert_signal_event(
        event_id="seed", source_name="other", raw_payload={"x": 1},
        fetched_at=NOW.isoformat(), db_path=db,
    )
    result = build_live_price_movers(db, now_utc=NOW, holdings=["MSFT", "RTX"], market_state="open")
    assert result["meta"]["existing_risk_visibility_degraded"] is True
    assert set(result["meta"]["existing_holdings_missing_price"]) == {"MSFT", "RTX"}


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
