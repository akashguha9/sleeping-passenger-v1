"""Tests for scripts/chronology_store.

Uses the repo-local scratch_path fixture so each test writes its DB into a
throwaway directory under ``~/.codex/memories/pipeline_pytest_scratch``. This
avoids the Windows tmp_path cleanup failures seen on this checkout.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.chronology_store import (
    get_connection,
    init_schema,
    log_observation,
    log_snapshot,
)


@pytest.fixture
def conn(scratch_path: Path):
    db_path = scratch_path / "observation.db"
    connection = get_connection(db_path)
    init_schema(connection)
    try:
        yield connection
    finally:
        connection.close()


def test_get_connection_creates_parent_dirs(scratch_path: Path):
    db_path = scratch_path / "nested" / "sub" / "observation.db"
    connection = get_connection(db_path)
    try:
        assert db_path.parent.is_dir()
        assert db_path.exists()
    finally:
        connection.close()


def test_schema_creates_expected_tables(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    names = {row[0] for row in rows}
    assert {"observations", "snapshots"}.issubset(names)


def test_init_schema_is_idempotent(conn):
    # second and third call must not raise
    init_schema(conn)
    init_schema(conn)
    rows = conn.execute("SELECT COUNT(*) FROM observations").fetchone()
    assert rows[0] == 0


def test_log_observation_roundtrip(conn):
    row_id = log_observation(
        conn,
        {
            "ts": "2026-04-21T00:00:00Z",
            "source": "snapshot_logger",
            "payload_json": '{"k":1}',
            "run_id": "abc123",
        },
    )
    assert row_id >= 1
    fetched = conn.execute(
        "SELECT ts, source, payload_json, run_id FROM observations WHERE id = ?",
        (row_id,),
    ).fetchone()
    assert fetched == (
        "2026-04-21T00:00:00Z",
        "snapshot_logger",
        '{"k":1}',
        "abc123",
    )


def test_log_observation_rejects_missing_required_keys(conn):
    with pytest.raises(ValueError):
        log_observation(conn, {"ts": "2026-04-21T00:00:00Z", "source": "x"})


def test_log_snapshot_persists_and_serializes_payload(conn):
    row_id = log_snapshot(
        conn,
        run_id="run-abc",
        snapshot={"timestamp": "2026-04-21T00:05:00Z", "scm_rate": 0.286},
    )
    assert row_id >= 1
    run_id, ts, payload_json = conn.execute(
        "SELECT run_id, snapshot_ts, payload_json FROM snapshots WHERE id = ?",
        (row_id,),
    ).fetchone()
    assert run_id == "run-abc"
    assert ts == "2026-04-21T00:05:00Z"
    assert '"scm_rate": 0.286' in payload_json


def test_log_snapshot_handles_missing_timestamp(conn):
    row_id = log_snapshot(conn, run_id="run-xyz", snapshot={"note": "no ts"})
    ts = conn.execute(
        "SELECT snapshot_ts FROM snapshots WHERE id = ?", (row_id,)
    ).fetchone()[0]
    assert ts == ""
