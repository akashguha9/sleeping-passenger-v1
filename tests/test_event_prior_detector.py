"""Task E verification: event_prior_detector is deterministic and read-only.

Covered behaviors:
    * empty DB -> no windows
    * threshold respected (min_count, window_minutes)
    * source filter isolates observations
    * time-range filters (since / until) respected
    * unparseable timestamps are skipped, not fabricated
    * connection opened via open_readonly refuses writes
    * CLI on missing DB exits non-zero with a JSON error payload
    * CLI on live chronology writes from snapshot_logger reports >=1 observation

These tests never invent chronology: every assertion is driven by rows we
explicitly seed into a tmp sqlite DB via scripts.chronology_store.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.chronology_store import (  # noqa: E402
    get_connection,
    init_schema,
    log_observation,
)
from scripts.event_prior_detector import (  # noqa: E402
    count_observations_by_source,
    detect_prior_windows,
    open_readonly,
)


def _seed_db(scratch_path: Path, rows: list[dict]) -> Path:
    db_path = scratch_path / "observation.db"
    conn = get_connection(db_path)
    init_schema(conn)
    for row in rows:
        log_observation(conn, row)
    conn.close()
    return db_path


def _ro(db_path: Path) -> sqlite3.Connection:
    return open_readonly(db_path)


# --------------------------------------------------------------------------
# core detection logic
# --------------------------------------------------------------------------

def test_empty_db_returns_no_windows(scratch_path: Path):
    db_path = _seed_db(scratch_path, [])
    conn = _ro(db_path)
    try:
        assert detect_prior_windows(conn) == []
        assert count_observations_by_source(conn) == {}
    finally:
        conn.close()


def test_three_observations_within_window_yield_one_window(scratch_path: Path):
    rows = [
        {"ts": ts, "source": "snapshot_logger", "payload_json": "{}"}
        for ts in (
            "2026-04-21T00:00:00Z",
            "2026-04-21T00:15:00Z",
            "2026-04-21T00:50:00Z",
        )
    ]
    conn = _ro(_seed_db(scratch_path, rows))
    try:
        windows = detect_prior_windows(
            conn, source="snapshot_logger", window_minutes=60, min_count=3
        )
    finally:
        conn.close()
    assert len(windows) == 1
    w = windows[0]
    assert w["count"] == 3
    assert w["source"] == "snapshot_logger"
    assert w["start_ts"] == "2026-04-21T00:00:00Z"
    assert w["end_ts"] == "2026-04-21T00:50:00Z"


def test_two_observations_do_not_form_window_with_min_count_three(scratch_path: Path):
    rows = [
        {"ts": "2026-04-21T00:00:00Z", "source": "A", "payload_json": "{}"},
        {"ts": "2026-04-21T00:30:00Z", "source": "A", "payload_json": "{}"},
    ]
    conn = _ro(_seed_db(scratch_path, rows))
    try:
        assert detect_prior_windows(conn, min_count=3) == []
    finally:
        conn.close()


def test_observations_outside_window_do_not_merge(scratch_path: Path):
    # 3 rows inside a 60-min window, then a later row >60m after first
    rows = [
        {"ts": "2026-04-21T00:00:00Z", "source": "A", "payload_json": "{}"},
        {"ts": "2026-04-21T00:05:00Z", "source": "A", "payload_json": "{}"},
        {"ts": "2026-04-21T00:10:00Z", "source": "A", "payload_json": "{}"},
        {"ts": "2026-04-21T03:00:00Z", "source": "A", "payload_json": "{}"},
    ]
    conn = _ro(_seed_db(scratch_path, rows))
    try:
        windows = detect_prior_windows(
            conn, source="A", window_minutes=60, min_count=3
        )
    finally:
        conn.close()
    assert len(windows) == 1
    assert windows[0]["count"] == 3
    assert windows[0]["end_ts"] == "2026-04-21T00:10:00Z"


def test_source_filter_is_respected(scratch_path: Path):
    rows = [
        {"ts": "2026-04-21T00:00:00Z", "source": "A", "payload_json": "{}"},
        {"ts": "2026-04-21T00:05:00Z", "source": "A", "payload_json": "{}"},
        {"ts": "2026-04-21T00:10:00Z", "source": "B", "payload_json": "{}"},
        {"ts": "2026-04-21T00:15:00Z", "source": "B", "payload_json": "{}"},
    ]
    conn = _ro(_seed_db(scratch_path, rows))
    try:
        assert detect_prior_windows(conn, source="B", min_count=3) == []
        assert (
            count_observations_by_source(conn)
            == {"A": 2, "B": 2}
        )
    finally:
        conn.close()


def test_since_until_bounds_are_inclusive(scratch_path: Path):
    rows = [
        {"ts": f"2026-04-21T0{h}:00:00Z", "source": "A", "payload_json": "{}"}
        for h in (0, 1, 2, 3, 4)
    ]
    conn = _ro(_seed_db(scratch_path, rows))
    try:
        windows = detect_prior_windows(
            conn,
            source="A",
            window_minutes=600,  # wide enough to include all rows in range
            min_count=3,
            since="2026-04-21T01:00:00Z",
            until="2026-04-21T03:00:00Z",
        )
    finally:
        conn.close()
    # inclusive bounds keep 3 rows (01, 02, 03)
    assert len(windows) == 1
    assert windows[0]["count"] == 3
    assert windows[0]["start_ts"] == "2026-04-21T01:00:00Z"
    assert windows[0]["end_ts"] == "2026-04-21T03:00:00Z"


def test_unparseable_timestamp_is_skipped_not_fabricated(scratch_path: Path):
    rows = [
        {"ts": "2026-04-21T00:00:00Z", "source": "A", "payload_json": "{}"},
        {"ts": "not-a-real-ts", "source": "A", "payload_json": "{}"},
        {"ts": "2026-04-21T00:30:00Z", "source": "A", "payload_json": "{}"},
        {"ts": "2026-04-21T00:45:00Z", "source": "A", "payload_json": "{}"},
    ]
    conn = _ro(_seed_db(scratch_path, rows))
    try:
        windows = detect_prior_windows(
            conn, source="A", window_minutes=60, min_count=3
        )
    finally:
        conn.close()
    # 3 valid rows, all within 45 min -> exactly one window of count 3
    assert len(windows) == 1
    assert windows[0]["count"] == 3


def test_mixed_source_without_filter_reports_mixed(scratch_path: Path):
    rows = [
        {"ts": "2026-04-21T00:00:00Z", "source": "A", "payload_json": "{}"},
        {"ts": "2026-04-21T00:05:00Z", "source": "B", "payload_json": "{}"},
        {"ts": "2026-04-21T00:10:00Z", "source": "C", "payload_json": "{}"},
    ]
    conn = _ro(_seed_db(scratch_path, rows))
    try:
        windows = detect_prior_windows(conn, window_minutes=60, min_count=3)
    finally:
        conn.close()
    assert len(windows) == 1
    assert windows[0]["source"] == "MIXED"


def test_invalid_window_minutes_raises(scratch_path: Path):
    db_path = _seed_db(scratch_path, [])
    conn = _ro(db_path)
    try:
        with pytest.raises(ValueError):
            detect_prior_windows(conn, window_minutes=0)
        with pytest.raises(ValueError):
            detect_prior_windows(conn, min_count=0)
    finally:
        conn.close()


# --------------------------------------------------------------------------
# read-only enforcement
# --------------------------------------------------------------------------

def test_open_readonly_refuses_writes(scratch_path: Path):
    rows = [{"ts": "2026-04-21T00:00:00Z", "source": "A", "payload_json": "{}"}]
    db_path = _seed_db(scratch_path, rows)
    conn = open_readonly(db_path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute(
                "INSERT INTO observations(ts, source, payload_json) "
                "VALUES (?, ?, ?)",
                ("2026-04-21T00:30:00Z", "A", "{}"),
            )
            conn.commit()
    finally:
        conn.close()


def test_open_readonly_missing_db_raises(scratch_path: Path):
    with pytest.raises(sqlite3.OperationalError):
        open_readonly(scratch_path / "does-not-exist.db")


# --------------------------------------------------------------------------
# CLI behavior
# --------------------------------------------------------------------------

def test_cli_reports_error_on_missing_db(scratch_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "event_prior_detector.py"),
            "--db",
            str(scratch_path / "nope.db"),
            "--summary",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["window_count"] == 0
    assert payload["total_observations"] == 0
    assert "error" in payload


def test_cli_on_seeded_db_returns_window(scratch_path: Path):
    rows = [
        {"ts": ts, "source": "snapshot_logger", "payload_json": "{}"}
        for ts in (
            "2026-04-21T00:00:00Z",
            "2026-04-21T00:05:00Z",
            "2026-04-21T00:10:00Z",
        )
    ]
    db_path = _seed_db(scratch_path, rows)
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "event_prior_detector.py"),
            "--db",
            str(db_path),
            "--source",
            "snapshot_logger",
            "--window-min",
            "60",
            "--min-count",
            "3",
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["total_observations"] == 3
    assert payload["window_count"] == 1
    assert payload["windows"][0]["count"] == 3
    assert payload["windows"][0]["source"] == "snapshot_logger"
