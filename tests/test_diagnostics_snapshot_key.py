"""Tests for the deterministic diagnostics snapshot key."""
from __future__ import annotations

import sqlite3

from scripts import diagnostics_snapshot_key as key_mod


def _seed_db(path, *, rows=10, watermark="2026-05-20T10:00:00Z",
             reset=True):
    conn = sqlite3.connect(str(path))
    try:
        if reset:
            conn.executescript(
                """
                DROP TABLE IF EXISTS signal_events;
                DROP TABLE IF EXISTS source_run_log;
                """
            )
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS signal_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                source_name TEXT NOT NULL,
                raw_payload TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS source_run_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_name TEXT NOT NULL,
                run_started_at TEXT,
                run_ended_at TEXT
            );
            """
        )
        for i in range(rows):
            conn.execute(
                "INSERT INTO signal_events (event_id, source_name, "
                "raw_payload, fetched_at) VALUES (?,?,?,?)",
                (f"e-{i}", "test", "{}", f"2026-05-{(i % 20) + 1:02d}T01:00:00Z"),
            )
        conn.execute(
            "INSERT INTO source_run_log (source_name, run_started_at, "
            "run_ended_at) VALUES (?,?,?)",
            ("test", "2026-05-20T09:00:00Z", watermark),
        )
        conn.commit()
    finally:
        conn.close()


def test_snapshot_key_changes_when_row_count_changes(tmp_path):
    db = tmp_path / "k.db"
    _seed_db(db, rows=5)
    inputs_a = key_mod.collect_canonical_inputs(db)
    key_a = key_mod.compute_snapshot_key(inputs_a)

    _seed_db(db, rows=7)  # rewrites schema + adds 7 rows instead of 5
    inputs_b = key_mod.collect_canonical_inputs(db)
    key_b = key_mod.compute_snapshot_key(inputs_b)

    assert inputs_a["signal_event_count"] != inputs_b["signal_event_count"]
    assert key_a != key_b


def test_snapshot_key_changes_when_watermark_advances(tmp_path):
    db = tmp_path / "k.db"
    _seed_db(db, rows=3, watermark="2026-05-20T10:00:00Z")
    inputs_a = key_mod.collect_canonical_inputs(db)
    key_a = key_mod.compute_snapshot_key(inputs_a)

    _seed_db(db, rows=3, watermark="2026-05-21T11:00:00Z")
    inputs_b = key_mod.collect_canonical_inputs(db)
    key_b = key_mod.compute_snapshot_key(inputs_b)

    assert inputs_a["source_health_watermark_utc"] != inputs_b["source_health_watermark_utc"]
    assert key_a != key_b


def test_snapshot_key_is_deterministic_for_same_inputs(tmp_path):
    db = tmp_path / "k.db"
    _seed_db(db, rows=4)
    inputs_a = key_mod.collect_canonical_inputs(db)
    inputs_b = key_mod.collect_canonical_inputs(db)
    assert key_mod.compute_snapshot_key(inputs_a) == key_mod.compute_snapshot_key(inputs_b)


def test_current_snapshot_key_carries_safety_stamps(tmp_path):
    db = tmp_path / "k.db"
    _seed_db(db, rows=1)
    payload = key_mod.current_snapshot_key(db)
    assert payload["snapshot_key"]
    assert payload["advisory_status"] == "ADVISORY_ONLY"
    assert payload["execution_gate"] == "LOCKED"
    assert payload["broker_api_called"] is False
    assert payload["ai_execution_count"] == 0


def test_no_db_returns_safe_inputs(tmp_path):
    inputs = key_mod.collect_canonical_inputs(tmp_path / "missing.db")
    assert inputs["db_exists"] is False
    assert inputs["signal_event_count"] == 0
    # Snapshot key still computable from the no-DB inputs.
    assert key_mod.compute_snapshot_key(inputs)
