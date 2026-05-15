"""Tests for ``scripts.learning_completeness_report`` (Sprint 7C).

Contract:

* A trade is learning-complete iff outcome_status is known AND
  outcome_quality / process_quality / lesson / journal pre-trade fields
  are all present.
* Missing any of those leaves the trade learning-incomplete; the report
  must list exactly which fields are missing.
* The report is read-only and never grants execution permission.
* Empty DB / missing tables return a safe report with warnings, not an
  exception.
* CLI emits both JSON and text.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts import learning_completeness_report as lcr
from scripts import persistence


def _build_db(path: Path) -> None:
    persistence.init_schema(path)


def _log_trade(
    db: Path,
    trade_id: str,
    *,
    event_id: str = "EV",
    invalidation_level: str = "below 95",
    expected_horizon: str = "1w",
    risk_reason: str = "tight stop",
    entry_reason: str = "breakout",
    exit_plan: str = "trail",
    lesson: str = "log lesson",
    mistake_tags: str = "",
    created_via: str = "manual_trade_log",
) -> None:
    persistence.insert_manual_trade(
        trade_id=trade_id,
        event_id=event_id,
        ticker="QQQ",
        side="BUY",
        quantity=10.0,
        price=100.0,
        executed_at="2026-05-14T00:00:00Z",
        thesis="t",
        notes="",
        logged_by="human",
        db_path=db,
        invalidation_level=invalidation_level,
        expected_horizon=expected_horizon,
        risk_reason=risk_reason,
        entry_reason=entry_reason,
        exit_plan=exit_plan,
        lesson=lesson,
        mistake_tags=mistake_tags,
        created_via=created_via,
    )


def _reconcile_full(
    db: Path,
    trade_id: str,
    *,
    outcome_status: str = "WIN",
    outcome_quality: str = "skill",
    process_error: str = "none",
    lesson: str = "stick to stop",
    mistake_tags: str = "",
) -> None:
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "INSERT INTO reconciliation_results"
            " (reconciliation_id, trade_id, event_id, reconciled_at,"
            "  actual_fill_price, actual_quantity, outcome_notes,"
            "  pnl_estimate, outcome_status, outcome_quality, process_error,"
            "  lesson, mistake_tags)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                f"R_{trade_id}", trade_id, "EV",
                "2026-05-14T02:00:00Z", 100.5, 10.0,
                "notes", 0.0, outcome_status, outcome_quality,
                process_error, lesson, mistake_tags,
            ),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Empty / missing
# ---------------------------------------------------------------------------


def test_missing_db_returns_safe_payload(tmp_path):
    payload = lcr.build_report(tmp_path / "absent.db")
    assert payload["db_available"] is False
    assert payload["advisory_status"] == "ADVISORY_ONLY"
    assert payload["execution_gate"] == "LOCKED"
    assert "db_missing" in payload["warnings"]
    assert payload["items"] == []


def test_empty_db_safe(tmp_path):
    db = tmp_path / "mvp.db"
    _build_db(db)
    payload = lcr.build_report(db)
    assert payload["db_available"] is True
    assert payload["reconciled_count"] == 0
    assert payload["learning_complete_count"] == 0
    assert payload["learning_incomplete_count"] == 0


# ---------------------------------------------------------------------------
# Completeness rule
# ---------------------------------------------------------------------------


def test_fully_filled_trade_is_learning_complete(tmp_path):
    db = tmp_path / "mvp.db"
    _build_db(db)
    _log_trade(db, "T1")
    _reconcile_full(db, "T1")
    payload = lcr.build_report(db)
    assert payload["reconciled_count"] == 1
    assert payload["learning_complete_count"] == 1
    assert payload["learning_incomplete_count"] == 0
    assert payload["items"] == []  # only incomplete items are surfaced


def test_missing_outcome_quality_is_incomplete(tmp_path):
    db = tmp_path / "mvp.db"
    _build_db(db)
    _log_trade(db, "T1")
    _reconcile_full(db, "T1", outcome_quality="")
    payload = lcr.build_report(db)
    assert payload["learning_incomplete_count"] == 1
    item = payload["items"][0]
    assert "outcome_quality" in item["missing_fields"]
    assert item["learning_complete"] is False
    assert item["blocked_reason"]


def test_missing_lesson_is_incomplete(tmp_path):
    db = tmp_path / "mvp.db"
    _build_db(db)
    # Both pre-trade and reconciliation lessons empty.
    _log_trade(db, "T1", lesson="")
    _reconcile_full(db, "T1", lesson="")
    payload = lcr.build_report(db)
    assert payload["learning_incomplete_count"] == 1
    assert "lesson" in payload["items"][0]["missing_fields"]


def test_missing_process_quality_is_incomplete(tmp_path):
    db = tmp_path / "mvp.db"
    _build_db(db)
    _log_trade(db, "T1", lesson="")
    # No process_error, no mistake_tags, no rec lesson => process_quality missing
    _reconcile_full(db, "T1", process_error="", lesson="", mistake_tags="")
    payload = lcr.build_report(db)
    item = payload["items"][0]
    assert "process_quality" in item["missing_fields"]


def test_unknown_outcome_status_is_incomplete(tmp_path):
    db = tmp_path / "mvp.db"
    _build_db(db)
    _log_trade(db, "T1")
    _reconcile_full(db, "T1", outcome_status="UNKNOWN")
    payload = lcr.build_report(db)
    item = payload["items"][0]
    assert "outcome_status" in item["missing_fields"]
    assert "UNKNOWN" in item["blocked_reason"].upper() or "Reconcile" in item["blocked_reason"]


def test_missing_pre_trade_journal_field_is_incomplete(tmp_path):
    db = tmp_path / "mvp.db"
    _build_db(db)
    # Empty entry_reason on the manual_trade row.
    _log_trade(db, "T1", entry_reason="")
    _reconcile_full(db, "T1")
    payload = lcr.build_report(db)
    item = payload["items"][0]
    assert any(m == "journal:entry_reason" for m in item["missing_fields"])


# ---------------------------------------------------------------------------
# Distribution + limit
# ---------------------------------------------------------------------------


def test_missing_field_distribution_counts(tmp_path):
    db = tmp_path / "mvp.db"
    _build_db(db)
    _log_trade(db, "T1", lesson="")
    _reconcile_full(db, "T1", lesson="", outcome_quality="")
    _log_trade(db, "T2", event_id="EV2", lesson="")
    _reconcile_full(db, "T2", lesson="", outcome_quality="")
    payload = lcr.build_report(db)
    dist = payload["missing_field_distribution"]
    assert dist["outcome_quality"] == 2
    assert dist["lesson"] == 2


def test_limit_truncates_items_but_not_summary(tmp_path):
    db = tmp_path / "mvp.db"
    _build_db(db)
    for i in range(5):
        _log_trade(db, f"T{i}", event_id=f"EV{i}", lesson="")
        _reconcile_full(db, f"T{i}", lesson="", outcome_quality="")
    payload = lcr.build_report(db, limit=2)
    assert payload["learning_incomplete_count"] == 5
    assert len(payload["items"]) == 2
    assert payload["truncated"] is True


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------


def test_report_never_unlocks_execution(tmp_path):
    db = tmp_path / "mvp.db"
    _build_db(db)
    _log_trade(db, "T1")
    _reconcile_full(db, "T1")
    payload = lcr.build_report(db)
    assert payload["advisory_status"] == "ADVISORY_ONLY"
    assert payload["execution_gate"] == "LOCKED"
    assert payload["broker_api_called"] is False
    assert payload["ai_execution_count"] == 0
    assert payload["execution_permission"] is False
    assert payload["can_execute"] is False


def test_report_has_no_execution_language(tmp_path):
    db = tmp_path / "mvp.db"
    _build_db(db)
    _log_trade(db, "T1", lesson="")
    _reconcile_full(db, "T1", lesson="", outcome_quality="")
    payload = lcr.build_report(db)
    flat = str(payload).lower()
    for forbidden in (
        "place order",
        "execute trade",
        "auto-trade",
        "trade now",
        "ai-approved",
        "permission granted",
        "broker order placed",
    ):
        assert forbidden not in flat


def test_report_is_read_only(tmp_path):
    db = tmp_path / "mvp.db"
    _build_db(db)
    _log_trade(db, "T1")
    _reconcile_full(db, "T1")
    mtime_before = db.stat().st_mtime
    size_before = db.stat().st_size
    lcr.build_report(db)
    assert db.stat().st_mtime == mtime_before
    assert db.stat().st_size == size_before


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_json_mode(tmp_path, capsys):
    db = tmp_path / "mvp.db"
    _build_db(db)
    _log_trade(db, "T1", lesson="")
    _reconcile_full(db, "T1", outcome_quality="", lesson="")
    rc = lcr.main(["--db-path", str(db), "--json"])
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["learning_incomplete_count"] == 1
    assert rc == 0


def test_cli_text_mode(tmp_path, capsys):
    db = tmp_path / "mvp.db"
    _build_db(db)
    _log_trade(db, "T1")
    _reconcile_full(db, "T1")
    rc = lcr.main(["--db-path", str(db)])
    out = capsys.readouterr().out
    assert "Learning Completeness Report" in out
    assert "ADVISORY" in out or "advisory" in out
    assert rc == 0


def test_cli_missing_db_returns_nonzero(tmp_path):
    rc = lcr.main(["--db-path", str(tmp_path / "absent.db")])
    assert rc != 0


# ---------------------------------------------------------------------------
# Provenance contract — only count rows entered via Manual Trade Log
# ---------------------------------------------------------------------------


def test_seed_rows_excluded_from_learning_completeness(tmp_path):
    """SPY/QQQ seed rows with empty provenance must not be counted."""
    db = tmp_path / "mvp.db"
    _build_db(db)
    # Two seed rows (empty provenance) — must NOT appear in any count.
    _log_trade(db, "SEED_SPY", event_id="EV_SPY", created_via="")
    _reconcile_full(db, "SEED_SPY")
    _log_trade(db, "SEED_QQQ", event_id="EV_QQQ", created_via="")
    _reconcile_full(db, "SEED_QQQ", outcome_quality="")
    # One human row.
    _log_trade(db, "MT_human", event_id="EV_H", created_via="manual_trade_log")
    _reconcile_full(db, "MT_human")
    payload = lcr.build_report(db)
    assert payload["reconciled_count"] == 1
    assert payload["learning_complete_count"] == 1
    assert payload["learning_incomplete_count"] == 0
    # Distribution must reflect only the human row's missing fields.
    dist = payload["missing_field_distribution"]
    assert "outcome_quality" not in dist


def test_unknown_provenance_row_excluded_from_learning(tmp_path):
    db = tmp_path / "mvp.db"
    _build_db(db)
    _log_trade(db, "T_imp", event_id="EV_I", created_via="imported_csv")
    _reconcile_full(db, "T_imp", outcome_quality="")
    payload = lcr.build_report(db)
    assert payload["reconciled_count"] == 0
    assert payload["items"] == []
