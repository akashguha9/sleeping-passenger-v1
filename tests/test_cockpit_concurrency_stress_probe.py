"""Kanté Defensive Sprint — Task C: concurrency/stress probe proof.

Proves the read-only stress probe over signal_events + cockpit hot paths:
handles empty / missing-table DBs safely, computes its metrics + gate correctly,
classifies failures / db-locks / timeouts, never issues a mutation statement,
emits the advisory safety stamps, supports JSON output, and enforces bounded
workers/iterations.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts import cockpit_concurrency_stress_probe as probe
from scripts import persistence


@pytest.fixture
def empty_db(tmp_path: Path) -> Path:
    db = tmp_path / "mvp_local.db"
    persistence.init_schema(db)
    return db


@pytest.fixture
def schemaless_db(tmp_path: Path) -> Path:
    # A real SQLite file with NO signal_events table.
    db = tmp_path / "bare.db"
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
        conn.commit()
    finally:
        conn.close()
    return db


# ---------------------------------------------------------------------------
# Safe handling of empty / missing-table / missing-file DBs
# ---------------------------------------------------------------------------


def test_probe_handles_empty_db_safely(empty_db):
    report = probe.run_stress_probe(db_path=empty_db, workers=2, iterations=4)
    assert report["failed_operations"] == 0
    assert report["db_locked_errors"] == 0
    assert report["stress_gate_status"] in {"PASS", "WARN"}
    assert report["total_operations"] == 8


def test_probe_handles_missing_signal_events_table_safely(schemaless_db):
    report = probe.run_stress_probe(db_path=schemaless_db, workers=2, iterations=4)
    # Missing-table reads return cleanly; they do not fail.
    assert report["failed_operations"] == 0
    assert report["stress_gate_status"] in {"PASS", "WARN"}


def test_probe_handles_missing_db_file_safely(tmp_path):
    missing = tmp_path / "does_not_exist.db"
    report = probe.run_stress_probe(db_path=missing, workers=2, iterations=3)
    assert report["db_available"] is False
    assert report["db_locked_errors"] == 0
    assert report["failed_operations"] == 0


# ---------------------------------------------------------------------------
# Metric / gate computation
# ---------------------------------------------------------------------------


def test_percentile_helper():
    vals = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert probe._percentile(vals, 50) == 30.0
    assert probe._percentile(vals, 100) == 50.0
    assert probe._percentile([], 95) == 0.0


def test_stress_gate_blocks_on_db_lock():
    gate, rec = probe._stress_gate(
        success_rate=0.5, timeout_rate=0.0, error_rate=0.5, p95_ms=10,
        target_p95_ms=500, db_locked_errors=3, uncaught_exception=None)
    assert gate == probe.BLOCK
    assert any("db_locked" in r for r in rec)


def test_stress_gate_blocks_on_high_error_rate():
    gate, _ = probe._stress_gate(
        success_rate=0.9, timeout_rate=0.0, error_rate=0.10, p95_ms=10,
        target_p95_ms=500, db_locked_errors=0, uncaught_exception=None)
    assert gate == probe.BLOCK


def test_stress_gate_blocks_on_high_timeout_rate():
    gate, _ = probe._stress_gate(
        success_rate=0.9, timeout_rate=0.10, error_rate=0.0, p95_ms=10,
        target_p95_ms=500, db_locked_errors=0, uncaught_exception=None)
    assert gate == probe.BLOCK


def test_stress_gate_warns_on_high_latency_but_otherwise_clean():
    gate, _ = probe._stress_gate(
        success_rate=1.0, timeout_rate=0.0, error_rate=0.0, p95_ms=900,
        target_p95_ms=500, db_locked_errors=0, uncaught_exception=None)
    assert gate == probe.WARN


def test_stress_gate_passes_when_all_green():
    gate, _ = probe._stress_gate(
        success_rate=1.0, timeout_rate=0.0, error_rate=0.0, p95_ms=50,
        target_p95_ms=500, db_locked_errors=0, uncaught_exception=None)
    assert gate == probe.PASS


# ---------------------------------------------------------------------------
# Failure / db-lock classification through the full run
# ---------------------------------------------------------------------------


def test_failed_operation_blocks(empty_db, monkeypatch):
    def _boom(db_path, max_rows):
        raise RuntimeError("synthetic hot-path failure")

    monkeypatch.setattr(probe, "_OPERATIONS", (("boom", _boom),))
    report = probe.run_stress_probe(db_path=empty_db, workers=2, iterations=5)
    assert report["failed_operations"] == report["total_operations"]
    assert report["error_rate"] > 0.05
    assert report["stress_gate_status"] == probe.BLOCK


def test_db_lock_classified_and_blocks(empty_db, monkeypatch):
    def _locked(db_path, max_rows):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(probe, "_OPERATIONS", (("locked", _locked),))
    report = probe.run_stress_probe(db_path=empty_db, workers=2, iterations=4)
    assert report["db_locked_errors"] > 0
    assert report["stress_gate_status"] == probe.BLOCK


# ---------------------------------------------------------------------------
# No-mutation invariant
# ---------------------------------------------------------------------------


def test_read_only_assertion_rejects_mutation_verbs():
    for bad in ("DELETE FROM signal_events",
                "UPDATE signal_events SET x=1",
                "DROP TABLE signal_events",
                "INSERT INTO signal_events VALUES (1)"):
        with pytest.raises(AssertionError):
            probe._assert_read_only(bad)


def test_read_only_assertion_allows_select():
    # Must not raise.
    probe._assert_read_only("SELECT * FROM signal_events LIMIT 10")
    probe._assert_read_only(
        "SELECT created_via FROM manual_trades WHERE created_via = ?")


def test_report_carries_safety_stamps(empty_db):
    report = probe.run_stress_probe(db_path=empty_db, workers=1, iterations=2)
    assert report["advisory_only"] is True
    assert report["human_execution_required"] is True
    assert report["read_only"] is True
    assert report["broker_api_called"] is False
    assert report["ai_execution_count"] == 0
    assert report["execution_gate"] == "LOCKED"
    assert report["canonical_truth_source"] == "sqlite"


# ---------------------------------------------------------------------------
# Bounds + JSON CLI
# ---------------------------------------------------------------------------


def test_workers_and_iterations_are_bounded(empty_db):
    # Absurd inputs are clamped, never launched verbatim.
    report = probe.run_stress_probe(
        db_path=empty_db, workers=10_000, iterations=10_000_000)
    assert report["workers"] <= 64
    assert report["iterations"] <= 1000


def test_json_mode_emits_valid_json(empty_db, capsys):
    rc = probe.main(["--db-path", str(empty_db), "--workers", "2",
                     "--iterations", "3", "--no-summary", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["report"] == "cockpit_concurrency_stress_probe"
    assert payload["total_operations"] == 6
    assert payload["canonical_truth_source"] == "sqlite"


def test_summary_round_trip(empty_db, tmp_path, monkeypatch):
    # Redirect the summary file into tmp so the real runtime/ is untouched.
    monkeypatch.setattr(probe, "SUMMARY_DIR", tmp_path / "stress")
    monkeypatch.setattr(probe, "SUMMARY_FILE", tmp_path / "stress" / "last_run.json")
    report = probe.run_stress_probe(db_path=empty_db, workers=1, iterations=2)
    probe.write_summary(report)
    summary = probe.read_summary()
    assert summary is not None
    assert summary["stress_gate_status"] == report["stress_gate_status"]
    assert summary["cache_role"] == "derived_non_canonical"
