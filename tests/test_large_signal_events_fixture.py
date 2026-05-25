"""Large signal_events performance fixture — proof of non-canonical, bounded.

Covers:
* refusal of the canonical runtime DB path (``runtime/mvp_local.db``),
* deterministic row count + advisory safety stamps on every row,
* sidecar metadata file marks the DB as non-canonical and safe-to-delete,
* row bounds enforced (and lifted under ``allow_large_local_test``),
* in-DB ``_perf_fixture_metadata`` table flags the synthetic role.

122k full-size proof runs from the CLI; unit tests use 200 rows so the suite
stays fast.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests.helpers import large_signal_events_fixture as fix


def test_refuses_canonical_runtime_db(tmp_path, monkeypatch):
    """The helper MUST refuse the canonical runtime DB outright."""
    # Point the helper's notion of "canonical" at a tmp path so we don't risk
    # touching the real runtime DB if the refusal logic ever regresses.
    fake_canonical = tmp_path / "mvp_local.db"
    monkeypatch.setattr(fix, "CANONICAL_RUNTIME_DB", fake_canonical)
    with pytest.raises(fix.FixtureRefusalError):
        fix.create_large_signal_events_db(fake_canonical, row_count=10)


def test_creates_exact_row_count(tmp_path):
    db = tmp_path / "fixture.db"
    fix.create_large_signal_events_db(db, row_count=500, create_indexes=True)
    conn = sqlite3.connect(str(db))
    try:
        n = conn.execute("SELECT COUNT(*) FROM signal_events").fetchone()[0]
    finally:
        conn.close()
    assert n == 500


def test_rows_carry_advisory_safety_stamps(tmp_path):
    db = tmp_path / "fixture.db"
    fix.create_large_signal_events_db(db, row_count=64)
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT advisory_status, human_review_required, execution_gate, "
            "ai_execution_count, event_id FROM signal_events"
        ).fetchall()
    finally:
        conn.close()
    assert rows
    for advisory, human, gate, ai, eid in rows:
        assert advisory == "ADVISORY_ONLY"
        assert int(human) == 1
        assert gate == "LOCKED"
        assert int(ai) == 0
        assert eid.startswith(fix.FIXTURE_EVENT_ID_PREFIX), eid


def test_sidecar_metadata_marks_non_canonical(tmp_path):
    db = tmp_path / "fixture.db"
    fix.create_large_signal_events_db(db, row_count=32)
    sidecar = db.with_suffix(db.suffix + ".meta.json")
    assert sidecar.exists()
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    assert meta["fixture_role"] == "synthetic_performance_fixture"
    assert meta["derived_non_canonical"] is True
    assert meta["safe_to_delete"] is True
    assert meta["runtime_db_polluted"] is False
    assert meta["canonical_truth_source"] == "sqlite_runtime_not_used"
    assert meta["execution_gate"] == "LOCKED"
    assert meta["broker_api_called"] is False
    assert meta["ai_execution_count"] == 0


def test_in_db_metadata_table_flags_synthetic_role(tmp_path):
    db = tmp_path / "fixture.db"
    fix.create_large_signal_events_db(db, row_count=16)
    conn = sqlite3.connect(str(db))
    try:
        rows = dict(conn.execute(
            "SELECT key, value FROM _perf_fixture_metadata"
        ).fetchall())
    finally:
        conn.close()
    assert rows["fixture_role"] == "synthetic_performance_fixture"
    assert rows["derived_non_canonical"] == "true"
    assert rows["safe_to_delete"] == "true"


def test_row_count_bound(tmp_path):
    db = tmp_path / "fixture.db"
    with pytest.raises(ValueError, match="exceeds bound"):
        fix.create_large_signal_events_db(
            db, row_count=fix.MAX_ROW_COUNT + 1, create_indexes=False,
        )


def test_allow_large_local_test_lifts_bound(tmp_path):
    """The 250k bound can be lifted but not removed — 500k cap still applies."""
    db = tmp_path / "fixture.db"
    with pytest.raises(ValueError, match="exceeds bound"):
        fix.create_large_signal_events_db(
            db,
            row_count=fix.MAX_ROW_COUNT_ALLOW_LARGE + 1,
            create_indexes=False,
            allow_large_local_test=True,
        )


def test_indexes_present_when_requested(tmp_path):
    db = tmp_path / "fixture.db"
    fix.create_large_signal_events_db(db, row_count=32, create_indexes=True)
    conn = sqlite3.connect(str(db))
    try:
        idx = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()}
    finally:
        conn.close()
    assert {"idx_se_source", "idx_se_fetched"}.issubset(idx)


def test_fixture_is_deterministic(tmp_path):
    """Same seed → same event_ids; the proof is reproducible."""
    db1 = tmp_path / "a.db"
    db2 = tmp_path / "b.db"
    fix.create_large_signal_events_db(db1, row_count=100, seed=42)
    fix.create_large_signal_events_db(db2, row_count=100, seed=42)
    rows1 = sqlite3.connect(str(db1)).execute(
        "SELECT event_id, source_name FROM signal_events ORDER BY id"
    ).fetchall()
    rows2 = sqlite3.connect(str(db2)).execute(
        "SELECT event_id, source_name FROM signal_events ORDER BY id"
    ).fetchall()
    assert rows1 == rows2


def test_canonical_runtime_db_not_touched_by_creation(tmp_path, monkeypatch):
    """Creating a fixture next to a fake-canonical path must not write the canonical path."""
    fake_canonical = tmp_path / "mvp_local.db"
    monkeypatch.setattr(fix, "CANONICAL_RUNTIME_DB", fake_canonical)
    db = tmp_path / "elsewhere" / "fixture.db"
    fix.create_large_signal_events_db(db, row_count=16)
    assert not fake_canonical.exists()
