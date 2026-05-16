"""Sprint 10F tests — outcome-calibration readiness gate."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.calibration_gate import (  # noqa: E402
    STATUS_LOW,
    STATUS_NO_REAL_EVIDENCE,
    STATUS_NOT_READY,
    STATUS_REVIEWABLE,
    STATUS_UNAVAILABLE,
    STATUS_VERY_LOW,
    build_report,
)


def _make_db(tmp_path: Path) -> Path:
    db = tmp_path / "mvp_local.db"
    con = sqlite3.connect(str(db))
    con.executescript(
        """
        CREATE TABLE manual_trades (
            trade_id TEXT PRIMARY KEY,
            ticker TEXT NOT NULL DEFAULT '',
            trade_mode TEXT NOT NULL DEFAULT '',
            reactor_state_at_decision TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE reconciliation_results (
            reconciliation_id TEXT PRIMARY KEY,
            trade_id TEXT NOT NULL,
            outcome_status TEXT NOT NULL DEFAULT 'UNKNOWN',
            outcome_quality TEXT NOT NULL DEFAULT '',
            process_error TEXT NOT NULL DEFAULT '',
            lesson TEXT NOT NULL DEFAULT ''
        );
        """
    )
    con.commit()
    con.close()
    return db


def _add_trade(
    db: Path,
    trade_id: str,
    *,
    trade_mode: str,
    reactor: str,
    outcome_status: str | None,
    outcome_quality: str = "",
    process_error: str = "",
    lesson: str = "",
) -> None:
    con = sqlite3.connect(str(db))
    con.execute(
        "INSERT INTO manual_trades (trade_id, ticker, trade_mode, reactor_state_at_decision) VALUES (?, ?, ?, ?)",
        (trade_id, "AAPL", trade_mode, reactor),
    )
    if outcome_status is not None:
        con.execute(
            "INSERT INTO reconciliation_results "
            "(reconciliation_id, trade_id, outcome_status, outcome_quality, process_error, lesson) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (f"r-{trade_id}", trade_id, outcome_status, outcome_quality, process_error, lesson),
        )
    con.commit()
    con.close()


# ---------------------------------------------------------------------------
# Gate behavior
# ---------------------------------------------------------------------------


def test_zero_rows_returns_not_ready(tmp_path):
    db = _make_db(tmp_path)
    rep = build_report(db)
    assert rep["db_available"] is True
    assert rep["paper"]["status"] == STATUS_NOT_READY
    assert "Do not interpret paper outcomes yet" in rep["paper"]["message"]
    assert rep["paper"]["rows"]["with_snapshot_and_outcome"] == 0
    assert rep["paper"]["rows_needed_next"] == 5


def test_real_zero_rows_returns_no_real_evidence(tmp_path):
    db = _make_db(tmp_path)
    rep = build_report(db)
    assert rep["real"]["status"] == STATUS_NO_REAL_EVIDENCE
    assert "No real-manual outcome rows" in rep["real"]["message"]


def test_paper_rows_without_outcome_do_not_unlock(tmp_path):
    db = _make_db(tmp_path)
    # 10 paper rows with reactor snapshots but no reconciliation outcomes.
    for i in range(10):
        _add_trade(
            db,
            f"t{i}",
            trade_mode="PAPER",
            reactor="ARMED",
            outcome_status=None,
        )
    rep = build_report(db)
    assert rep["paper"]["rows"]["with_reactor_snapshot"] == 10
    # No outcomes means no qualifying rows.
    assert rep["paper"]["rows"]["with_snapshot_and_outcome"] == 0
    assert rep["paper"]["status"] == STATUS_NOT_READY


def test_paper_rows_with_outcome_but_no_label_or_lesson(tmp_path):
    """Rows with snapshot + outcome unlock the *band* by count, but
    ``fully_qualifying`` stays low until the operator records process
    labels and lessons. The gate exposes both numbers."""
    db = _make_db(tmp_path)
    for i in range(7):
        _add_trade(
            db,
            f"t{i}",
            trade_mode="PAPER",
            reactor="ARMED",
            outcome_status="WIN",  # outcome present
            outcome_quality="",  # process label missing
            lesson="",  # lesson missing
        )
    rep = build_report(db)
    assert rep["paper"]["rows"]["with_snapshot_and_outcome"] == 7
    # 7 is in the 5..19 band -> VERY_LOW_CONFIDENCE.
    assert rep["paper"]["status"] == STATUS_VERY_LOW
    # But the fully-qualifying count must still be zero — the operator
    # has not written process labels or lessons.
    assert rep["paper"]["rows"]["fully_qualifying"] == 0


def test_paper_band_thresholds(tmp_path):
    db = _make_db(tmp_path)

    def _seed(n: int) -> None:
        for i in range(n):
            _add_trade(
                db,
                f"t{i}",
                trade_mode="PAPER",
                reactor="ARMED",
                outcome_status="WIN",
                outcome_quality="clean",
                lesson="captured at decision time",
            )

    _seed(4)
    assert build_report(db)["paper"]["status"] == STATUS_NOT_READY

    sqlite3.connect(str(db)).executescript("DELETE FROM manual_trades; DELETE FROM reconciliation_results;")
    _seed(5)
    assert build_report(db)["paper"]["status"] == STATUS_VERY_LOW

    sqlite3.connect(str(db)).executescript("DELETE FROM manual_trades; DELETE FROM reconciliation_results;")
    _seed(20)
    assert build_report(db)["paper"]["status"] == STATUS_LOW

    sqlite3.connect(str(db)).executescript("DELETE FROM manual_trades; DELETE FROM reconciliation_results;")
    _seed(50)
    assert build_report(db)["paper"]["status"] == STATUS_REVIEWABLE


def test_real_rows_independent_of_paper(tmp_path):
    db = _make_db(tmp_path)
    # Some paper rows that should NOT count toward the real band.
    for i in range(6):
        _add_trade(
            db,
            f"p{i}",
            trade_mode="PAPER",
            reactor="ARMED",
            outcome_status="WIN",
            outcome_quality="clean",
            lesson="x",
        )
    # And a single real-manual row.
    _add_trade(
        db,
        "r1",
        trade_mode="REAL_MANUAL",
        reactor="ARMED",
        outcome_status="WIN",
        outcome_quality="clean",
        lesson="captured",
    )
    rep = build_report(db)
    # Paper band has been seeded over 5 -> VERY_LOW.
    assert rep["paper"]["status"] == STATUS_VERY_LOW
    # Real band has 1 row -> still NOT_READY (not NO_REAL_OUTCOME_EVIDENCE).
    assert rep["real"]["status"] == STATUS_NOT_READY
    assert rep["real"]["rows"]["with_snapshot_and_outcome"] == 1


def test_unknown_outcome_does_not_count(tmp_path):
    db = _make_db(tmp_path)
    for i in range(8):
        _add_trade(
            db,
            f"t{i}",
            trade_mode="PAPER",
            reactor="ARMED",
            outcome_status="UNKNOWN",  # still pending
            outcome_quality="",
            lesson="",
        )
    rep = build_report(db)
    assert rep["paper"]["rows"]["with_snapshot_and_outcome"] == 0
    assert rep["paper"]["status"] == STATUS_NOT_READY


def test_safety_stamps_present(tmp_path):
    db = _make_db(tmp_path)
    rep = build_report(db)
    assert rep["advisory_only"] is True
    assert rep["execution_gate"] == "LOCKED"
    assert rep["broker_api_called"] is False
    assert rep["ai_execution_count"] == 0
    assert rep["execution_permission"] is False
    assert rep["can_execute"] is False
    # No-claims list rejects edge / alpha / profitability language.
    no_claims_paper = rep["paper"]["no_claims"]
    assert any("alpha" in c for c in no_claims_paper)
    assert any("profit" in c for c in no_claims_paper)
    assert any("real_money" in c for c in no_claims_paper)
    assert any("production" in c for c in no_claims_paper)


def test_db_missing_returns_unavailable(tmp_path):
    rep = build_report(tmp_path / "no.db")
    assert rep["db_available"] is False
    assert rep["paper"]["status"] == STATUS_UNAVAILABLE
    assert rep["real"]["status"] == STATUS_UNAVAILABLE


def test_old_schema_without_trade_mode_column(tmp_path):
    """If the DB is older than Sprint 7B.2 and lacks the trade_mode
    column, the gate must degrade safely to NOT_READY rather than crash."""
    db = tmp_path / "old.db"
    con = sqlite3.connect(str(db))
    con.executescript(
        """
        CREATE TABLE manual_trades (trade_id TEXT PRIMARY KEY, ticker TEXT);
        CREATE TABLE reconciliation_results (
            reconciliation_id TEXT PRIMARY KEY,
            trade_id TEXT,
            outcome_status TEXT,
            outcome_quality TEXT,
            process_error TEXT,
            lesson TEXT
        );
        """
    )
    con.execute("INSERT INTO manual_trades (trade_id, ticker) VALUES ('x', 'AAPL')")
    con.commit()
    con.close()

    rep = build_report(db)
    assert rep["paper"]["status"] == STATUS_NOT_READY
    assert rep["paper"]["rows"]["with_snapshot_and_outcome"] == 0
