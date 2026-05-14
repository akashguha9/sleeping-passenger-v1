"""Tests for the dashboard self-test summary helper.

These exercise ``scripts.self_test_report.build_self_test_summary`` directly
against an isolated SQLite DB so no FastAPI client is required and
``runtime/mvp_local.db`` is never touched.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scripts import persistence
from scripts import self_test_report


_SAFETY = {
    "advisory_status": "ADVISORY_ONLY",
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "ai_execution_count": 0,
    "execution_permission": False,
    "can_execute": False,
}


def _assert_safety(payload: dict) -> None:
    for k, v in _SAFETY.items():
        assert payload[k] == v, f"safety stamp {k} expected {v!r}"


@pytest.fixture()
def populated_db(tmp_path: Path) -> Path:
    db = tmp_path / "summary.db"
    persistence.init_schema(db)
    # Disciplined trade (high journal completeness)
    persistence.insert_manual_trade(
        trade_id="MT_FULL",
        event_id="EV_FULL",
        ticker="ETH",
        side="BUY",
        quantity=2.0,
        price=1500.0,
        executed_at="2026-05-01T00:00:00Z",
        thesis="reclaim of 1500",
        notes="",
        logged_by="human",
        db_path=db,
        invalidation_level="1450",
        expected_horizon="2-5d",
        risk_reason="<=0.5R",
        entry_reason="break of structure",
        exit_plan="trim 50% at 1600, stop 1450",
        confidence_before=0.65,
        emotional_state="calm",
        mistake_tags="",
        lesson="capture more on first leg next time",
    )
    # Bare-bones trade (low journal completeness)
    persistence.insert_manual_trade(
        trade_id="MT_BARE",
        event_id="EV_BARE",
        ticker="DOGE",
        side="BUY",
        quantity=100.0,
        price=0.10,
        executed_at="2026-05-02T00:00:00Z",
        thesis="vibes",
        notes="",
        logged_by="human",
        db_path=db,
    )
    # Reconciliation with attribution
    persistence.insert_reconciliation(
        reconciliation_id="REC_1",
        trade_id="MT_FULL",
        event_id="EV_FULL",
        reconciled_at="2026-05-05T00:00:00Z",
        actual_fill_price=1605.0,
        actual_quantity=2.0,
        outcome_notes="hit target",
        pnl_estimate=210.0,
        outcome_status="WIN",
        db_path=db,
        outcome_quality="good_decision",
        process_error="",
        process_error_notes="",
        mistake_tags="",
        lesson="trust the plan",
    )
    persistence.insert_reconciliation(
        reconciliation_id="REC_2",
        trade_id="MT_BARE",
        event_id="EV_BARE",
        reconciled_at="2026-05-06T00:00:00Z",
        actual_fill_price=0.05,
        actual_quantity=100.0,
        outcome_notes="stopped",
        pnl_estimate=-5.0,
        outcome_status="LOSS",
        db_path=db,
        outcome_quality="process_error",
        process_error="no_invalidation_set",
        process_error_notes="no stop set",
        mistake_tags="no_stop",
        lesson="never enter without a stop",
    )
    return db


def test_build_self_test_summary_basic_counts(populated_db: Path) -> None:
    summary = self_test_report.build_self_test_summary(populated_db)
    _assert_safety(summary)
    assert summary["db_available"] is True
    assert summary["manual_trades_logged_count"] == 2
    assert summary["reconciled_trades_count"] == 2
    assert summary["unreconciled_trades_count"] == 0


def test_build_self_test_summary_journal_metrics(populated_db: Path) -> None:
    summary = self_test_report.build_self_test_summary(populated_db)
    # At least one of the trades is journal-rich, so completeness > 0.
    assert summary["average_journal_completeness"] > 0
    assert summary["lesson_count"] >= 1
    assert summary["confidence_before_average"] is not None
    # Emotional state distribution captured.
    assert summary["emotional_state_distribution"].get("calm", 0) >= 1
    # Incomplete journal count reflects the bare trade.
    assert summary["incomplete_journal_count"] >= 1


def test_build_self_test_summary_outcome_attribution(populated_db: Path) -> None:
    summary = self_test_report.build_self_test_summary(populated_db)
    oq = summary["outcome_quality_distribution"]
    pe = summary["process_error_distribution"]
    assert oq.get("good_decision") == 1
    assert oq.get("process_error") == 1
    assert pe.get("no_invalidation_set") == 1


def test_build_self_test_summary_missing_db(tmp_path: Path) -> None:
    summary = self_test_report.build_self_test_summary(tmp_path / "absent.db")
    _assert_safety(summary)
    assert summary["db_available"] is False
    assert summary["manual_trades_logged_count"] == 0
    assert summary["unreconciled_trades_count"] == 0


def test_build_self_test_summary_tolerates_legacy_db(tmp_path: Path) -> None:
    """A DB created before the additive migration must produce a summary."""
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript(
            """
            CREATE TABLE manual_trades (
                trade_id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                ticker TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity REAL NOT NULL,
                price REAL NOT NULL,
                executed_at TEXT NOT NULL,
                thesis TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                logged_by TEXT NOT NULL DEFAULT 'human',
                execution_mode TEXT NOT NULL DEFAULT 'HUMAN_ONLY',
                ai_execution_count INTEGER NOT NULL DEFAULT 0,
                advisory_status TEXT NOT NULL DEFAULT 'ADVISORY_ONLY',
                human_review_required INTEGER NOT NULL DEFAULT 1,
                broker_order_id TEXT NOT NULL DEFAULT 'NONE',
                broker_api_called INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE reconciliation_results (
                reconciliation_id TEXT PRIMARY KEY,
                trade_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                reconciled_at TEXT NOT NULL,
                actual_fill_price REAL NOT NULL,
                actual_quantity REAL NOT NULL,
                outcome_notes TEXT NOT NULL DEFAULT '',
                pnl_estimate REAL NOT NULL DEFAULT 0.0,
                outcome_status TEXT NOT NULL DEFAULT 'UNKNOWN',
                execution_mode TEXT NOT NULL DEFAULT 'HUMAN_ONLY',
                ai_execution_count INTEGER NOT NULL DEFAULT 0,
                advisory_status TEXT NOT NULL DEFAULT 'ADVISORY_ONLY',
                human_review_required INTEGER NOT NULL DEFAULT 1
            );
            """
        )
        conn.execute(
            "INSERT INTO manual_trades"
            " (trade_id, event_id, ticker, side, quantity, price, executed_at, thesis)"
            " VALUES (?,?,?,?,?,?,?,?)",
            ("MT_LEG", "EV_LEG", "BTC", "BUY", 1.0, 100.0, "2024-01-01T00:00:00Z", "x"),
        )
        conn.commit()
    finally:
        conn.close()
    summary = self_test_report.build_self_test_summary(db)
    _assert_safety(summary)
    assert summary["manual_trades_logged_count"] == 1
    # Legacy DB has no journal-quality columns — distributions empty but no crash.
    assert summary["emotional_state_distribution"] == {}
    assert summary["mistake_tags_distribution"] == {}


def test_summary_does_not_write_db(populated_db: Path) -> None:
    """Read-only contract — running the summary must not change row counts."""
    before = sqlite3.connect(str(populated_db))
    try:
        n1 = before.execute("SELECT COUNT(*) FROM manual_trades").fetchone()[0]
    finally:
        before.close()
    self_test_report.build_self_test_summary(populated_db)
    self_test_report.build_self_test_summary(populated_db)
    after = sqlite3.connect(str(populated_db))
    try:
        n2 = after.execute("SELECT COUNT(*) FROM manual_trades").fetchone()[0]
    finally:
        after.close()
    assert n1 == n2
