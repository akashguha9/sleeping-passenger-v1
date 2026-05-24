"""
Backend API filter tests — verify that the existing /live-signals endpoint
serves Kalshi rows alongside other approved sources without leaking
disallowed Kalshi categories or mixing Kalshi into Polymarket.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.kalshi_normalizer import (
    CANONICAL_SOURCE,
    normalize_kalshi_market,
)


def _seed(persistence, db_path: Path, payload, fetched_at: str = "2026-05-24T00:00:00Z"):
    persistence.insert_signal_event(
        event_id=payload["event_id"],
        source_name=payload["source_name"],
        raw_payload=payload,
        fetched_at=fetched_at,
        db_path=db_path,
    )


@pytest.fixture()
def seeded_db(tmp_path: Path, monkeypatch):
    """Seed a temp SQLite with two Kalshi rows (Crypto, Economics), one
    Polymarket row, and one disallowed Kalshi attempt (which must NOT
    appear because we filter at normalisation time)."""
    from scripts import persistence

    db_path = tmp_path / "kalshi_api.db"
    monkeypatch.setattr(persistence, "DB_PATH", db_path, raising=False)

    # Approved Kalshi rows.
    btc = normalize_kalshi_market(
        {
            "source": "Kalshi",
            "source_market_id": "BTCMAY-2026",
            "title": "How high will Bitcoin get in May?",
            "category": "Crypto",
            "yes_price": 0.42,
            "close_time_utc": "2026-05-31T23:59:00Z",
        },
        fetched_at_utc="2026-05-24T00:00:00Z",
    )
    fed = normalize_kalshi_market(
        {
            "source": "kalshi",
            "source_market_id": "FED-CUT-JUN-2026",
            "title": "Will the Fed cut rates at the June 2026 meeting?",
            "category": "Economics",
            "yes_price": 0.31,
        },
        fetched_at_utc="2026-05-24T00:00:00Z",
    )
    assert btc is not None and fed is not None

    # Synthesize the persistence keys the way the runner does.
    for payload in (btc, fed):
        payload_for_db = dict(payload)
        payload_for_db.setdefault("source_name", CANONICAL_SOURCE)
        _seed(persistence, db_path, {**payload_for_db, "event_id": payload["event_id"], "source_name": CANONICAL_SOURCE})

    # Polymarket row.
    poly = {
        "event_id": "polymarket_test_001",
        "source_name": "polymarket",
        "title": "Will Apple announce a foldable iPhone in 2026?",
        "market_id": "test-001",
        "advisory_status": "ADVISORY_ONLY",
        "human_review_required": True,
        "execution_gate": "LOCKED",
        "ai_execution_count": 0,
    }
    persistence.insert_signal_event(
        event_id=poly["event_id"],
        source_name="polymarket",
        raw_payload=poly,
        fetched_at="2026-05-24T00:00:00Z",
        db_path=db_path,
    )

    # An attempt to seed a rejected Kalshi category — normalize_kalshi_market
    # returns None, so it CANNOT be persisted.
    rejected = normalize_kalshi_market(
        {
            "source": "Kalshi",
            "source_market_id": "NBA-FINALS-2026",
            "title": "Will the Lakers win the NBA Finals?",
            "category": "Sports",
        }
    )
    assert rejected is None, "rejected categories must not produce a payload"

    return db_path


def test_live_signals_kalshi_filter_returns_only_kalshi(seeded_db):
    from scripts.api_server import _get_live_signals

    response = _get_live_signals(source_name=CANONICAL_SOURCE, limit=50)
    assert response["advisory_status"] == "ADVISORY_ONLY"
    assert response["human_review_required"] is True
    assert response["ai_execution_count"] == 0
    events = response["live_signal_events"]
    assert len(events) == 2
    for ev in events:
        assert ev["source_name"] == "kalshi"
        payload = ev["raw_payload"]
        assert payload["source"] == "kalshi"
        assert payload["source_label"] == "Kalshi"
        assert payload["category"] in {"Crypto", "Economics"}
        assert payload["execution_permission"] == "ADVISORY_ONLY"
        assert payload["broker_api_called"] is False
        assert payload["ai_execution_count"] == 0


def test_live_signals_polymarket_filter_excludes_kalshi(seeded_db):
    from scripts.api_server import _get_live_signals

    response = _get_live_signals(source_name="polymarket", limit=50)
    events = response["live_signal_events"]
    assert len(events) == 1
    assert events[0]["source_name"] == "polymarket"
    # Kalshi data must not leak into the Polymarket filter.
    for ev in events:
        assert ev["source_name"] != "kalshi"


def test_live_signals_all_sources_includes_kalshi(seeded_db):
    from scripts.api_server import _get_live_signals

    response = _get_live_signals(source_name=None, limit=50)
    events = response["live_signal_events"]
    source_set = {ev["source_name"] for ev in events}
    assert "kalshi" in source_set
    assert "polymarket" in source_set
