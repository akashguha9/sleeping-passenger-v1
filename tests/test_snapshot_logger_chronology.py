"""Task D verification: snapshot_logger.log_snapshot writes to chronology DB.

Proves that after one successful snapshot write:
    * the JSONL log has one row
    * the chronology DB has one row in snapshots and one in observations
    * both chronology rows carry the same run_id as the current process
    * chronology hook is passive — a broken DB path does not crash log_snapshot
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.runtime_common import get_run_id  # noqa: E402
from scripts.snapshot_logger import log_snapshot  # noqa: E402


def _minimal_runtime_state() -> dict:
    """Smallest runtime_state that satisfies build_snapshot_row's access paths."""
    return {
        "scm_review": {"scm_rate": 0.5, "scm_state": "NORMAL"},
        "signal_summary": {
            "status_counts_above_threshold": {"WATCHLIST": 0, "EXECUTED_CHAOS": 0},
            "signals_above_ce_threshold": 0,
        },
        "active_blockers": [],
        "execution_policy": {"policy_state": "READY", "allow_new_risk": True},
        "moltbook_summary": {"clean_entries": 0, "chaos_entries": 0},
        "watchlist_diagnostics": {"watchlist_signals": []},
        "simulation_context": {"scenario": "LIVE"},
    }


def test_log_snapshot_writes_observation_and_snapshot_rows(scratch_path: Path):
    jsonl_path = scratch_path / "system_snapshots.jsonl"
    db_path = scratch_path / "observation.db"

    row = log_snapshot(
        path=jsonl_path,
        runtime_state=_minimal_runtime_state(),
        chronology_db_path=db_path,
    )

    # jsonl side
    assert jsonl_path.exists()
    assert jsonl_path.read_text(encoding="utf-8").strip(), "jsonl log is empty"

    # chronology side
    assert db_path.exists(), "chronology DB was not created"
    conn = sqlite3.connect(str(db_path))
    try:
        snap_count = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
        obs_count = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        assert snap_count == 1, f"expected 1 snapshot row, got {snap_count}"
        assert obs_count == 1, f"expected 1 observation row, got {obs_count}"

        snap_run_id, snap_ts = conn.execute(
            "SELECT run_id, snapshot_ts FROM snapshots"
        ).fetchone()
        obs_run_id, obs_source = conn.execute(
            "SELECT run_id, source FROM observations"
        ).fetchone()
    finally:
        conn.close()

    # coherence: DB rows carry the same run_id used by runtime artifacts
    current_run_id = get_run_id()
    assert snap_run_id == current_run_id
    assert obs_run_id == current_run_id
    assert obs_source == "snapshot_logger"
    assert snap_ts == row["timestamp"]


def test_log_snapshot_is_passive_when_chronology_db_path_is_invalid(
    scratch_path: Path, capsys
):
    """A broken DB path must not crash log_snapshot. The jsonl must still be written."""
    jsonl_path = scratch_path / "system_snapshots.jsonl"
    # point at a path that cannot be opened as a sqlite file (a directory)
    bad_db_path = scratch_path / "not_a_db_dir"
    bad_db_path.mkdir()

    # must not raise
    row = log_snapshot(
        path=jsonl_path,
        runtime_state=_minimal_runtime_state(),
        chronology_db_path=bad_db_path,
    )

    assert row["timestamp"]
    assert jsonl_path.exists() and jsonl_path.read_text(encoding="utf-8").strip()
    captured = capsys.readouterr()
    assert "chronology" in captured.err.lower()
