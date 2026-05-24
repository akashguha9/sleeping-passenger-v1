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
    # Absurd inputs are clamped, never launched verbatim.  The iteration
    # ceiling was lifted from 1000 to 5000 for the large-fixture path; the
    # worker ceiling is unchanged.
    report = probe.run_stress_probe(
        db_path=empty_db, workers=10_000, iterations=10_000_000)
    assert report["workers"] <= probe.MAX_WORKERS == 64
    assert report["iterations"] <= probe.MAX_ITERATIONS == 5000


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


# ---------------------------------------------------------------------------
# Large-scale performance proof sprint — fixture / contention / refusal
# ---------------------------------------------------------------------------


def test_report_stamps_runtime_db_not_polluted(empty_db):
    """Every stress report stamps ``runtime_db_polluted=False`` for the gate."""
    report = probe.run_stress_probe(db_path=empty_db, workers=1, iterations=2)
    assert report["runtime_db_polluted"] is False


def test_iteration_bound_lifted_to_5000(empty_db):
    """The large-fixture path needs more iterations — the ceiling is 5000."""
    report = probe.run_stress_probe(
        db_path=empty_db, workers=1, iterations=10_000_000)
    assert report["iterations"] <= probe.MAX_ITERATIONS == 5000


def test_refuses_canonical_for_large_fixture(monkeypatch):
    """``--large-fixture --db-path runtime/mvp_local.db`` must refuse."""
    canonical = probe.CANONICAL_RUNTIME_DB
    with pytest.raises(ValueError, match="refuse_to_pollute_canonical_runtime_db"):
        probe.main([
            "--large-fixture", "--db-path", str(canonical),
            "--no-summary", "--json", "--fixture-rows", "100",
        ])


def test_refuses_canonical_for_write_contention():
    """``--include-write-contention --db-path runtime/mvp_local.db`` must refuse."""
    with pytest.raises(ValueError, match="refuse_to_pollute_canonical_runtime_db"):
        probe.main([
            "--include-write-contention", "--db-path",
            str(probe.CANONICAL_RUNTIME_DB), "--no-summary", "--json",
        ])


def test_refuses_canonical_for_output(tmp_path, monkeypatch):
    """``--output`` to the canonical runtime DB must refuse as well."""
    with pytest.raises(ValueError, match="refuse_to_pollute_canonical_runtime_db"):
        probe.main([
            "--no-summary", "--json",
            "--output", str(probe.CANONICAL_RUNTIME_DB),
        ])


def test_large_fixture_creates_non_canonical_db_and_runs_probe(tmp_path, capsys, monkeypatch):
    """``--large-fixture --db-path tmp.db`` builds a fixture + runs the probe."""
    # Redirect the summary to tmp so we don't touch the real runtime/.
    monkeypatch.setattr(probe, "SUMMARY_DIR", tmp_path / "stress")
    monkeypatch.setattr(probe, "SUMMARY_FILE", tmp_path / "stress" / "last_run.json")
    fixture_path = tmp_path / "small_fixture.db"
    rc = probe.main([
        "--large-fixture",
        "--db-path", str(fixture_path),
        "--fixture-rows", "2000",
        "--workers", "2",
        "--iterations", "4",
        "--json",
    ])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["large_fixture_used"] is True
    assert payload["large_fixture_rows"] == 2000
    assert payload["large_fixture_path"] == str(fixture_path)
    assert payload["runtime_db_polluted"] is False
    assert payload["fixture_role"] == "synthetic_performance_fixture"
    assert payload["derived_non_canonical"] is True
    # Sidecar metadata travels through to the report.
    assert payload["large_fixture_sidecar"]["safe_to_delete"] is True


def test_write_contention_uses_temp_db_and_recovers(tmp_path, capsys, monkeypatch):
    """The write-contention scenario runs against a TEMP DB and recovers."""
    monkeypatch.setattr(probe, "SUMMARY_DIR", tmp_path / "stress")
    monkeypatch.setattr(probe, "SUMMARY_FILE", tmp_path / "stress" / "last_run.json")
    rc = probe.main([
        "--include-write-contention",
        "--workers", "2", "--iterations", "2",
        "--json",
    ])
    payload = json.loads(capsys.readouterr().out)
    assert rc in (0, 1)  # PASS or WARN both fine; only a hard BLOCK is RC=1
    assert payload["write_contention_enabled"] is True
    cr = payload["write_contention_report"]
    assert cr["temp_db_only"] is True
    assert cr["reads_during_lock"] > 0
    assert cr["runtime_db_polluted"] is False
    assert cr["fixture_role"] == "synthetic_performance_fixture"
    assert cr["derived_non_canonical"] is True
    # The contention gate is one of the recognised statuses, not crash.
    assert cr["contention_gate_status"] in {"PASS", "WARN", "BLOCK"}
    # Stress + contention metrics are mirrored onto the main report so the
    # release gate / summary can read them at top level.
    assert payload["contention_gate_status"] == cr["contention_gate_status"]
    assert payload["contention_recovery_score"] == cr["contention_recovery_score"]


def test_run_write_contention_scenario_refuses_canonical():
    with pytest.raises(ValueError, match="refuse_to_pollute_canonical_runtime_db"):
        probe.run_write_contention_scenario(db_path=probe.CANONICAL_RUNTIME_DB)


def test_run_write_contention_scenario_handles_clean_temp(tmp_path):
    """Direct API: temp DB only, classified result, no crash."""
    db = tmp_path / "contention.db"
    rep = probe.run_write_contention_scenario(
        db_path=db,
        writer_lock_hold_ms=50,
        reads_during_lock=8,
        target_recovery_ms=2000,
        reader_workers=2,
    )
    assert rep["temp_db_only"] is False  # caller-provided path
    assert rep["db_path"] == str(db)
    assert rep["runtime_db_polluted"] is False
    assert rep["fixture_role"] == "synthetic_performance_fixture"
    assert rep["contention_gate_status"] in {"PASS", "WARN", "BLOCK"}
    assert rep["reads_during_lock"] == 8
    assert rep["reads_successful_during_lock"] + rep["db_locked_errors"] <= 8


def test_write_contention_bounds():
    """Writer lock hold and reads_during_lock are clamped to safe ceilings."""
    rep = probe.run_write_contention_scenario(
        writer_lock_hold_ms=10**9,
        reads_during_lock=10**9,
        target_recovery_ms=1000,
        reader_workers=2,
    )
    assert rep["writer_lock_hold_ms"] <= probe.MAX_WRITER_LOCK_HOLD_MS
    assert rep["reads_during_lock"] <= probe.MAX_CONTENTION_READS
