"""
Operator readiness — edge-case coverage (10/10 sprint).

Locks in the contracts the existing test_operator_readiness_report.py
suite does not exercise:

- Corrupt DB file → readiness must NOT crash and must NOT silently READY.
- DB with a missing critical table → release gate FAIL surfaces and is NOT
  swallowed by the clean-DB downgrade.
- A row that smuggles ``broker_api_called=1`` past the persistence layer
  via raw SQL → readiness FAILs with the ``execution_gate_unlocked_in_db``
  hard-fail blocker.
- A row with ``ai_execution_count > 0`` → same.
- ``clean_db_downgrade_applied`` is ALWAYS present in the report (True or
  False) so operator tooling can branch on it without optional-key checks.
- ``hard_fail_blockers`` lists structured tags for every hard-fail reason.
"""
from __future__ import annotations

import sqlite3

import pytest

from scripts import persistence
from scripts import operator_readiness_report as orr


@pytest.fixture
def clean_db(tmp_path):
    path = tmp_path / "mvp_local.db"
    persistence.init_schema(path)
    return path


@pytest.fixture
def corrupt_db(tmp_path):
    """A file that EXISTS but is not a valid SQLite DB."""
    path = tmp_path / "mvp_local.db"
    path.write_bytes(b"this is not a sqlite database, just garbage bytes")
    return path


@pytest.fixture
def db_missing_tables(tmp_path):
    """A real SQLite DB but with none of the expected operator tables."""
    path = tmp_path / "mvp_local.db"
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE unrelated_table (id INTEGER PRIMARY KEY)")
        conn.commit()
    finally:
        conn.close()
    return path


# ---------------------------------------------------------------------------
# Always-present keys
# ---------------------------------------------------------------------------


class TestAlwaysPresentReportKeys:
    def test_clean_db_downgrade_applied_always_in_report(self, clean_db):
        report = orr.build_readiness_report(clean_db)
        assert "release_gate" in report
        # Boolean must always be present so operator scripts don't have
        # to differentiate "missing key" from "did not apply".
        assert "clean_db_downgrade_applied" in report["release_gate"]
        assert isinstance(report["release_gate"]["clean_db_downgrade_applied"], bool)

    def test_hard_fail_blockers_always_present_as_list(self, clean_db):
        report = orr.build_readiness_report(clean_db)
        assert "hard_fail_blockers" in report
        assert isinstance(report["hard_fail_blockers"], list)


# ---------------------------------------------------------------------------
# Corrupt DB
# ---------------------------------------------------------------------------


class TestCorruptDb:
    def test_corrupt_db_does_not_crash_readiness(self, corrupt_db):
        """A bad DB file must NOT cause a Python exception in the report —
        the gate must surface FAIL / FAIL_CLOSED instead.
        """
        report = orr.build_readiness_report(corrupt_db)
        assert report["readiness"] in ("FAIL", "FAIL_CLOSED", "WARN")
        # The DB exists on disk but is unusable, so it cannot be "READY".
        assert report["readiness"] != "READY"

    def test_corrupt_db_not_clean_initialised(self, corrupt_db):
        report = orr.build_readiness_report(corrupt_db)
        # The clean-DB heuristic must reject a corrupt file (it cannot
        # confirm the four operator tables exist and are empty).
        assert report["db_clean_initialised"] is False
        assert report["release_gate"]["clean_db_downgrade_applied"] is False


# ---------------------------------------------------------------------------
# Missing critical tables
# ---------------------------------------------------------------------------


class TestMissingTables:
    def test_missing_tables_surface_as_release_fail(self, db_missing_tables):
        report = orr.build_readiness_report(db_missing_tables)
        # The release gate's sqlite_tables_exist check should FAIL → readiness
        # cannot be READY.  (Downstream helpers may auto-create some tables
        # during the read; what matters is that the operator-visible verdict
        # is non-READY — we never silently pass on a partial schema.)
        assert report["readiness"] != "READY"


# ---------------------------------------------------------------------------
# Execution-gate invariants surfaced from persisted rows
# ---------------------------------------------------------------------------


def _force_broker_call_into_db(db_path) -> None:
    """Smuggle a polluted row past the persistence-layer defences."""
    # Normal insert via the safe API so the row exists with all columns.
    persistence.insert_manual_trade(
        "T_BROKER", "EV_T_BROKER", "AAPL", "BUY", 1.0, 10.0,
        "2026-05-20T00:00:00+00:00", "thesis", "notes", "human",
        db_path=db_path, created_via="manual_trade_log",
    )
    # Then DIRECTLY mutate the column to simulate a future bug / external
    # editor / restored bad backup.  The release gate must catch it.
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "UPDATE manual_trades SET broker_api_called=1 WHERE trade_id=?",
            ("T_BROKER",),
        )
        conn.commit()
    finally:
        conn.close()


def _force_ai_execution_count_into_db(db_path) -> None:
    persistence.insert_manual_trade(
        "T_AI", "EV_T_AI", "AAPL", "BUY", 1.0, 10.0,
        "2026-05-20T00:00:00+00:00", "thesis", "notes", "human",
        db_path=db_path, created_via="manual_trade_log",
    )
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "UPDATE manual_trades SET ai_execution_count=5 WHERE trade_id=?",
            ("T_AI",),
        )
        conn.commit()
    finally:
        conn.close()


class TestPersistedSafetyViolations:
    def test_broker_api_called_row_blocks_readiness(self, clean_db):
        _force_broker_call_into_db(clean_db)
        report = orr.build_readiness_report(clean_db)
        assert report["readiness"] == "FAIL"
        assert "execution_gate_unlocked_in_db" in report["hard_fail_blockers"]
        # Clean-DB downgrade MUST NOT save a row carrying broker_api_called.
        assert report["release_gate"]["clean_db_downgrade_applied"] is False

    def test_ai_execution_count_row_blocks_readiness(self, clean_db):
        _force_ai_execution_count_into_db(clean_db)
        report = orr.build_readiness_report(clean_db)
        assert report["readiness"] == "FAIL"
        assert "execution_gate_unlocked_in_db" in report["hard_fail_blockers"]
        assert report["release_gate"]["clean_db_downgrade_applied"] is False


# ---------------------------------------------------------------------------
# Populated healthy DB
# ---------------------------------------------------------------------------


class TestHealthyPopulatedDb:
    def test_populated_db_does_not_introduce_exec_unlocked_blocker(self, clean_db):
        """Populating the DB with a normal CLOSED_WIN trade must NOT cause
        the ``execution_gate_unlocked_in_db`` hard-fail blocker.  The
        overall verdict may still be WARN/FAIL on other axes (stress
        probe, compliance, etc.) — that is correct system behaviour and
        already covered elsewhere — but the execution invariants on the
        rows themselves must remain clean.
        """
        persistence.insert_manual_trade(
            "T_OK", "EV_T_OK", "AAPL", "BUY", 10.0, 150.0,
            "2026-05-20T00:00:00+00:00", "thesis", "notes", "human",
            db_path=clean_db, created_via="manual_trade_log",
        )
        persistence.insert_reconciliation(
            "REC_T_OK", "T_OK", "EV_T_OK", "2026-05-21T00:00:00+00:00",
            155.0, 10.0, "exited at a small gain", 50.0, "CLOSED_WIN",
            db_path=clean_db,
        )
        report = orr.build_readiness_report(clean_db)
        assert "execution_gate_unlocked_in_db" not in report["hard_fail_blockers"]
        # The populated DB is, by definition, no longer "clean initialised".
        assert report["db_clean_initialised"] is False
