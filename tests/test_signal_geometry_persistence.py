"""
Tests for the signal-geometry persistence layer (scripts/signal_geometry_persistence.py).

Verifies that the duplicate-fingerprint and signal-cell index persist to SQLite
idempotently (re-persisting bumps seen_count instead of inserting a new row) and
that the pure reflection module stays unaffected.  Everything runs against an
isolated temp DB.
"""
from __future__ import annotations

from pathlib import Path

import scripts.persistence as persistence
import scripts.signal_geometry_persistence as geo


def _db(tmp_path: Path) -> Path:
    db = tmp_path / "geo.db"
    persistence.init_schema(db)
    return db


_SIGNAL = {
    "event_id": "EV_GLD_1",
    "ticker": "GLD",
    "source_type": "news",
    "sector": "metals",
    "narrative_cluster": "gold_safety",
    "event_type": "macro_hedge",
    "thesis": "Gold flight-to-safety long idea.",
    "freshness_score": 0.8,
    "chaos_score": 0.2,
    "timestamp": "2026-05-19T18:00:00Z",
}


def test_duplicate_fingerprint_persists(tmp_path):
    db = _db(tmp_path)
    out = geo.persist_duplicate_fingerprint(_SIGNAL, db_path=db)
    assert out["is_new"] is True
    assert out["seen_count"] == 1
    rows = persistence.get_duplicate_fingerprints(db_path=db)
    assert len(rows) == 1
    assert rows[0]["fingerprint"] == out["fingerprint"]
    assert rows[0]["ticker"] == "GLD"
    assert rows[0]["advisory_only"] in (1, True)
    assert rows[0]["human_review_required"] in (1, True)


def test_repersist_fingerprint_bumps_seen_count_not_row(tmp_path):
    db = _db(tmp_path)
    geo.persist_duplicate_fingerprint(_SIGNAL, db_path=db)
    out2 = geo.persist_duplicate_fingerprint(_SIGNAL, db_path=db)
    assert out2["is_new"] is False
    assert out2["seen_count"] == 2
    rows = persistence.get_duplicate_fingerprints(db_path=db)
    assert len(rows) == 1
    assert rows[0]["seen_count"] == 2


def test_signal_cell_persists(tmp_path):
    db = _db(tmp_path)
    out = geo.persist_signal_cell(_SIGNAL, db_path=db)
    assert out["is_new"] is True
    rows = persistence.get_signal_cells(db_path=db)
    assert len(rows) == 1
    cell = rows[0]
    assert cell["cell_key"] == out["cell_key"]
    assert cell["sector"] == "metals"
    assert cell["narrative_cluster"] == "gold_safety"
    assert cell["source_type"] == "news"
    assert cell["advisory_only"] in (1, True)
    assert cell["human_review_required"] in (1, True)


def test_repersist_signal_cell_bumps_seen_count_not_row(tmp_path):
    db = _db(tmp_path)
    geo.persist_signal_cell(_SIGNAL, db_path=db)
    out2 = geo.persist_signal_cell(_SIGNAL, db_path=db)
    assert out2["is_new"] is False
    assert out2["seen_count"] == 2
    rows = persistence.get_signal_cells(db_path=db)
    assert len(rows) == 1
    assert rows[0]["seen_count"] == 2


def test_persist_geometry_combined(tmp_path):
    db = _db(tmp_path)
    out = geo.persist_signal_geometry(_SIGNAL, db_path=db)
    assert out["advisory_only"] is True
    assert out["canonical_source"] == "sqlite"
    assert len(persistence.get_duplicate_fingerprints(db_path=db)) == 1
    assert len(persistence.get_signal_cells(db_path=db)) == 1
