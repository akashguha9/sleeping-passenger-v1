"""Tests for the prewarm diagnostics snapshot script."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scripts import diagnostics_snapshot_cache as cache_mod
from scripts import prewarm_diagnostics_snapshot as prewarm_mod


def _seed_db(path: Path, rows: int = 10) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(
            """
            CREATE TABLE signal_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                source_name TEXT NOT NULL,
                raw_payload TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            );
            CREATE TABLE source_run_log (
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
                (f"e-{i}", "test", "{}", "2026-05-20T01:00:00Z"),
            )
        conn.commit()
    finally:
        conn.close()


def _stub_collect(_db_path):
    return {
        "stub_subreport": {
            "status": "OK",
            "elapsed_ms": 1.23,
            "data": {"release_gate_passed": True},
        }
    }


def test_prewarm_writes_summary_with_cache_hit(tmp_path, monkeypatch):
    db = tmp_path / "rt.db"
    _seed_db(db)
    cache_dir = tmp_path / "diag_cache"
    monkeypatch.setattr(cache_mod, "CACHE_DIR", cache_dir, raising=False)
    monkeypatch.setattr(cache_mod, "CACHE_FILE",
                        cache_dir / "diagnostics_snapshot.json", raising=False)
    monkeypatch.setattr(cache_mod, "collect_subreports", _stub_collect,
                        raising=False)
    summary_path = tmp_path / "release" / "diagnostics_prewarm_summary.json"

    summary = prewarm_mod.prewarm(
        db_path=db,
        write_summary=True,
        summary_path=summary_path,
    )

    assert summary["ok"] is True
    assert summary["cache_hit_after_prewarm"] is True
    assert summary["row_count"] == 10
    assert summary["snapshot_key"]
    assert summary["cold_recompute_count"] == 1
    assert summary["cold_recompute_count_after_prewarm"] == 0
    assert summary_path.exists()
    persisted = prewarm_mod.read_summary(summary_path)
    assert persisted is not None
    assert persisted["snapshot_key"] == summary["snapshot_key"]


def test_prewarm_advisory_stamps_present(tmp_path, monkeypatch):
    db = tmp_path / "rt.db"
    _seed_db(db, rows=3)
    cache_dir = tmp_path / "diag_cache2"
    monkeypatch.setattr(cache_mod, "CACHE_DIR", cache_dir, raising=False)
    monkeypatch.setattr(cache_mod, "CACHE_FILE",
                        cache_dir / "diagnostics_snapshot.json", raising=False)
    monkeypatch.setattr(cache_mod, "collect_subreports", _stub_collect,
                        raising=False)
    summary = prewarm_mod.prewarm(
        db_path=db,
        write_summary=False,
    )
    assert summary["advisory_only"] is True
    assert summary["execution_gate"] == "LOCKED"
    assert summary["broker_api_called"] is False
    assert summary["ai_execution_count"] == 0


def test_prewarm_summary_reads_back_none_when_missing(tmp_path):
    assert prewarm_mod.read_summary(tmp_path / "absent.json") is None
