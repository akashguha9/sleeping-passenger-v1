"""Tests — P3 SQLite-bridge-aware REAL_RUN coverage proof.

Proves that fresh canonical SQLite ``signal_events`` evidence is preferred over
stale on-disk JSON, and that Germany coverage (hence C_global=1/30) unlocks when
all five layers align — WITHOUT fabricating any layer:
  1. Fresh SQLite Rheinmetall row satisfies Germany news_support.
  2. Fresh SQLite mapped RHM.DE row satisfies Germany mapping_support.
  3. Stale today_news_events.json cannot suppress fresh SQLite evidence.
  4. C_global becomes 1/30 only when all Germany layers are true.
  5. FIXTURE and REAL_RUN proof kinds remain separate.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from scripts.country_coverage_proof import (
    build_proof_from_sqlite_bridge,
    germany_fixture_coverage,
)
from scripts.persistence import insert_signal_event

NOW = datetime(2026, 5, 30, 12, 0, tzinfo=timezone.utc)
FRESH_ISO = NOW.isoformat()


def _fresh_db(tmp_path):
    """A fresh SQLite DB with the schema applied."""
    from scripts import persistence

    db = tmp_path / "signals.db"
    persistence.apply_schema(db) if hasattr(persistence, "apply_schema") else None
    # Touch the table via an insert (apply schema lazily if needed).
    return db


def _insert_rheinmetall_news(db):
    raw = {
        "title": "Rheinmetall wins major new defense order in Germany",
        "summary": "Rheinmetall AG secured a multi-year artillery contract today.",
        "url": "https://example.de/rheinmetall-order",
        "published_at": FRESH_ISO,
        "country": "Germany",
        "sourcecountry": "Germany",
        "source": "gdelt",
    }
    insert_signal_event(
        event_id="evt-rheinmetall-1",
        source_name="gdelt",
        raw_payload=raw,
        fetched_at=FRESH_ISO,
        db_path=db,
    )


def _write_stale_news_json(payload_dir):
    payload_dir.mkdir(parents=True, exist_ok=True)
    stale = {
        "events": [
            {
                "ticker": "AAPL",
                "country": "United States",
                "event_timestamp_utc": "2026-04-01T00:00:00+00:00",  # ~2 months old
                "is_live": False,
            }
        ],
        "meta": {"generated_at_utc": "2026-04-01T00:00:00+00:00"},
    }
    (payload_dir / "today_news_events.json").write_text(json.dumps(stale), encoding="utf-8")


# --- 1 + 2 + 4: fresh SQLite unlocks Germany coverage -----------------------

def test_fresh_sqlite_rheinmetall_unlocks_germany(tmp_path):
    db = tmp_path / "signals.db"
    _insert_rheinmetall_news(db)
    payload_dir = tmp_path / "daily_payload"
    payload_dir.mkdir(parents=True, exist_ok=True)

    # Germany price support comes from a real valid price row (RHM.DE).
    price_rows = [{"ticker": "RHM.DE", "country": "Germany", "valid_price": True}]

    proof = build_proof_from_sqlite_bridge(
        db,
        payload_dir=payload_dir,
        price_rows=price_rows,
        now_utc=NOW,
    )
    assert proof["proof_kind"] == "REAL_RUN"
    assert "SQLITE_BRIDGE" in proof["proof_sources_used"]
    assert proof["sqlite_fresh_rows_count"] >= 1

    germany = next(r for r in proof["country_rows"] if r["country"] == "Germany")
    assert germany["universe_loaded"] == 1
    assert germany["price_support"] == 1
    assert germany["news_support"] == 1       # fresh SQLite Rheinmetall row
    assert germany["mapping_support"] == 1    # fresh mapped RHM.DE row
    assert germany["synthesis_consumed"] == 1
    assert germany["coverage"] == 1
    assert proof["C_global"] == round(1 / 30, 4)
    assert proof["covered_country_count"] == 1
    assert proof["first_covered_country"] == "Germany"


# --- 3: stale JSON cannot suppress fresh SQLite evidence --------------------

def test_stale_json_cannot_suppress_fresh_sqlite(tmp_path):
    db = tmp_path / "signals.db"
    _insert_rheinmetall_news(db)
    payload_dir = tmp_path / "daily_payload"
    _write_stale_news_json(payload_dir)

    price_rows = [{"ticker": "RHM.DE", "country": "Germany", "valid_price": True}]
    proof = build_proof_from_sqlite_bridge(
        db, payload_dir=payload_dir, price_rows=price_rows, now_utc=NOW
    )
    assert proof["payload_stale"] is True
    germany = next(r for r in proof["country_rows"] if r["country"] == "Germany")
    assert germany["news_support"] == 1      # SQLite still wins over stale JSON
    assert germany["coverage"] == 1
    assert proof["C_global"] == round(1 / 30, 4)


# --- 4b: missing news layer stays honest (no price -> no coverage) ----------

def test_no_news_keeps_germany_uncovered(tmp_path):
    db = tmp_path / "signals.db"
    # No signal_events inserted; DB does not yet exist -> honest fallback.
    payload_dir = tmp_path / "daily_payload"
    payload_dir.mkdir(parents=True, exist_ok=True)
    price_rows = [{"ticker": "RHM.DE", "country": "Germany", "valid_price": True}]
    proof = build_proof_from_sqlite_bridge(
        db, payload_dir=payload_dir, price_rows=price_rows, now_utc=NOW
    )
    germany = next(r for r in proof["country_rows"] if r["country"] == "Germany")
    assert germany["price_support"] == 1
    assert germany["news_support"] == 0
    assert germany["mapping_support"] == 0
    assert germany["coverage"] == 0
    assert proof["C_global"] == 0.0
    assert "news_support" in germany["missing_layers"]
    assert "mapping_support" in germany["missing_layers"]


# --- 5: fixture and real proof kinds remain separate ------------------------

def test_fixture_and_real_proof_kinds_separate(tmp_path):
    db = tmp_path / "signals.db"
    _insert_rheinmetall_news(db)
    payload_dir = tmp_path / "daily_payload"
    payload_dir.mkdir(parents=True, exist_ok=True)
    real = build_proof_from_sqlite_bridge(
        db,
        payload_dir=payload_dir,
        price_rows=[{"ticker": "RHM.DE", "country": "Germany", "valid_price": True}],
        now_utc=NOW,
    )
    fixture = germany_fixture_coverage()
    assert real["proof_kind"] == "REAL_RUN"
    assert fixture["proof_kind"] == "FIXTURE"
    # Real proof carries SQLite provenance the fixture never claims.
    assert "proof_sources_used" in real
    assert "proof_sources_used" not in fixture


def test_real_proof_safety_stamps(tmp_path):
    db = tmp_path / "signals.db"
    _insert_rheinmetall_news(db)
    proof = build_proof_from_sqlite_bridge(
        db, payload_dir=tmp_path / "dp", now_utc=NOW
    )
    assert proof["advisory_only"] is True
    assert proof["executable_allowed"] is False
    assert proof["safety"]["execution_gate"] == "LOCKED"
    assert proof["safety"]["broker_api_called"] is False
    assert proof["safety"]["ai_execution_count"] == 0
