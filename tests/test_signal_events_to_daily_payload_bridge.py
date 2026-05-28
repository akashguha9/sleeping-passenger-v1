"""Tests — signal_events -> daily payload bridge (read-only, honest fallback)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from scripts import persistence
from scripts.signal_events_to_daily_payload import (
    build_filings_payload_from_signal_events,
    build_news_payload_from_signal_events,
    load_fresh_signal_events_for_daily_payload,
)

NOW = datetime(2026, 5, 28, 12, 0, 0, tzinfo=timezone.utc)


def _insert(db, *, event_id, source_name, raw, fetched_at=None):
    persistence.insert_signal_event(
        event_id=event_id,
        source_name=source_name,
        raw_payload=raw,
        fetched_at=fetched_at or NOW.isoformat(),
        db_path=db,
    )


def test_fresh_news_event_appears_in_news_payload(tmp_path):
    db = tmp_path / "t.db"
    _insert(
        db,
        event_id="n1",
        source_name="gdelt",
        raw={
            "event_id": "n1",
            "ticker": "RHM.DE",
            "jurisdiction": "DE",
            "headline": "Rheinmetall wins fresh defense order today",
            "published_at": (NOW - timedelta(hours=2)).isoformat(),
            "provider": "gdelt",
        },
    )
    result = build_news_payload_from_signal_events(db, now_utc=NOW)
    tickers = [e["ticker"] for e in result["events"]]
    assert "RHM.DE" in tickers
    assert result["meta"]["is_live"] is True
    row = next(e for e in result["events"] if e["ticker"] == "RHM.DE")
    assert row["country"] == "Germany"
    assert row["mapping_status"] == "MAPPED"
    assert row["freshness_score"] > 0


def test_stale_event_is_excluded(tmp_path):
    db = tmp_path / "t.db"
    _insert(
        db,
        event_id="old1",
        source_name="newsapi",
        raw={
            "event_id": "old1",
            "ticker": "AAPL",
            "country": "US",
            "headline": "Old news",
            "published_at": (NOW - timedelta(hours=200)).isoformat(),
        },
    )
    rows, diag = load_fresh_signal_events_for_daily_payload(
        db, now_utc=NOW, lookback_hours=24.0, source_types=["newsapi"]
    )
    assert rows == []
    assert diag["stale_excluded_count"] == 1
    assert diag["fallback_reason"] == "NO_ROWS_WITHIN_TTL"


def test_fresh_filing_event_appears_in_filings_payload(tmp_path):
    db = tmp_path / "t.db"
    _insert(
        db,
        event_id="f1",
        source_name="sec_edgar",
        raw={
            "event_id": "f1",
            "ticker": "MSFT",
            "jurisdiction": "US",
            "disclosure_type": "8-K",
            "published_at": (NOW - timedelta(hours=5)).isoformat(),
            "provider": "sec_edgar",
        },
    )
    result = build_filings_payload_from_signal_events(db, now_utc=NOW)
    assert any(e["ticker"] == "MSFT" for e in result["events"])
    assert result["meta"]["is_live"] is True


def test_missing_db_triggers_honest_fallback(tmp_path):
    rows, diag = load_fresh_signal_events_for_daily_payload(
        tmp_path / "nope.db", now_utc=NOW, source_types=["gdelt"]
    )
    assert rows == []
    assert diag["fallback_reason"] == "SIGNAL_EVENTS_DB_MISSING"
    # And the news payload meta is an honest fallback, never claiming live.
    result = build_news_payload_from_signal_events(tmp_path / "nope.db", now_utc=NOW)
    assert result["meta"]["is_live"] is False
    assert result["meta"]["source_health"] == "STATIC_OR_EMPTY_FALLBACK"


def test_fresh_unmapped_event_is_retained_not_dropped(tmp_path):
    db = tmp_path / "t.db"
    _insert(
        db,
        event_id="u1",
        source_name="newsapi",
        raw={
            "event_id": "u1",
            "entity_name": "Some Completely Unknown Private GmbH",
            "country": "DE",
            "headline": "Unknown entity does a thing today",
            "published_at": (NOW - timedelta(hours=1)).isoformat(),
        },
    )
    result = build_news_payload_from_signal_events(db, now_utc=NOW)
    assert len(result["events"]) == 1
    row = result["events"][0]
    assert row["mapping_status"] == "UNMAPPED"
    assert row["ticker"] is None
    assert row["mapping_failure_reason"]  # explicit reason present
    # Unmapped-but-fresh -> live row, but executable is not allowed.
    assert result["meta"]["is_live"] is True
    assert result["meta"]["executable_allowed"] is False


def test_bridge_is_read_only(tmp_path):
    db = tmp_path / "t.db"
    _insert(
        db,
        event_id="r1",
        source_name="gdelt",
        raw={
            "event_id": "r1",
            "ticker": "RHM.DE",
            "headline": "x",
            "published_at": (NOW - timedelta(hours=1)).isoformat(),
        },
    )
    before = len(persistence.get_signal_events(db_path=db, limit=1000))
    build_news_payload_from_signal_events(db, now_utc=NOW)
    build_news_payload_from_signal_events(db, now_utc=NOW)
    after = len(persistence.get_signal_events(db_path=db, limit=1000))
    assert before == after == 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
