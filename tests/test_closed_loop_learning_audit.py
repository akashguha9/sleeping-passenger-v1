"""Closed-loop learning audit — read-only chain integrity + learning efficiency.

Proves the audit runs safely, never creates execution state, detects a closed
loss that never reached Moltbook, and verifies the advisory-only invariants.
"""
from __future__ import annotations

import sqlite3

import scripts.persistence as persistence
from scripts import closed_loop_learning_audit as cla


def _real_losing_trade(db, *, trade_id="MT1", event_id="EV1", ticker="GLD"):
    persistence.insert_manual_trade(
        trade_id, event_id, ticker, "BUY", 100.0, 50.0, "2026-01-01T00:00:00+00:00",
        "Real operator thesis on gold", "", "human", db_path=db,
        created_via="manual_trade_log", trade_mode="REAL_MANUAL",
    )
    persistence.insert_reconciliation(
        f"REC_{trade_id}", trade_id, event_id, "2026-01-05T00:00:00+00:00",
        45.0, 100.0, "closed out", -500.0, "LOSS", db_path=db,
    )


def test_audit_runs_safely_on_empty_db(tmp_path):
    db = tmp_path / "empty.db"
    persistence.init_schema(db)
    rep = cla.build_audit(db)
    assert rep["db_available"] is True
    assert rep["closed_losses_without_moltbook"] == 0
    assert rep["unresolved_repair_debt"] == 0


def test_audit_handles_missing_db_honestly(tmp_path):
    rep = cla.build_audit(tmp_path / "nope.db")
    assert rep["db_available"] is False
    assert any("not available" in n.lower() for n in rep["notes"])


def test_audit_does_not_create_execution_state(tmp_path):
    db = tmp_path / "noexec.db"
    persistence.init_schema(db)
    _real_losing_trade(db)
    # Snapshot row counts before + after; a read-only audit must not mutate.
    conn = sqlite3.connect(str(db))
    before = conn.execute("SELECT COUNT(*) FROM moltbook_entries").fetchone()[0]
    conn.close()

    rep = cla.build_audit(db)

    conn = sqlite3.connect(str(db))
    after = conn.execute("SELECT COUNT(*) FROM moltbook_entries").fetchone()[0]
    conn.close()
    assert after == before  # no rows created by a read-only audit
    assert rep["broker_api_called"] is False
    assert rep["ai_execution_count"] == 0
    assert rep["execution_gate"] == "LOCKED"


def test_audit_detects_missing_moltbook_entry(tmp_path):
    db = tmp_path / "missing.db"
    persistence.init_schema(db)
    _real_losing_trade(db)
    rep = cla.build_audit(db)
    assert rep["closed_losses_without_moltbook"] == 1
    assert rep["unresolved_repair_debt"] >= 1
    # The chain is not fully closed when a loss has no lesson.
    assert rep["closed_loop_coverage"] < 1.0


def test_audit_clean_when_loss_has_moltbook(tmp_path):
    db = tmp_path / "clean.db"
    persistence.init_schema(db)
    _real_losing_trade(db)
    persistence.insert_moltbook_entry(
        "MB1", "EV1", "GLD", "thesis", "ai", "refl", "exit", "MT1",
        "Closed at a loss", "manual_exit_loss", "lesson learned",
        "", "recalibrate position sizing", "", "t", db_path=db,
    )
    rep = cla.build_audit(db)
    assert rep["closed_losses_without_moltbook"] == 0
    assert rep["closed_loop_coverage"] == 1.0
    assert rep["lessons_without_recalibration_candidate"] == 0


def test_audit_verifies_advisory_only_invariants(tmp_path):
    db = tmp_path / "inv.db"
    persistence.init_schema(db)
    _real_losing_trade(db)
    rep = cla.build_audit(db)
    assert rep["advisory_only_verified"] is True
    assert rep["human_execution_verified"] is True
    assert rep["broker_api_called_false_verified"] is True
    assert rep["ai_execution_count_zero_verified"] is True


def test_audit_flags_broker_api_breach(tmp_path):
    db = tmp_path / "breach.db"
    persistence.init_schema(db)
    _real_losing_trade(db)
    # Inject a forbidden execution-state leak directly into canonical truth.
    conn = sqlite3.connect(str(db))
    conn.execute("UPDATE manual_trades SET broker_api_called = 1 WHERE trade_id='MT1'")
    conn.commit()
    conn.close()
    rep = cla.build_audit(db)
    assert rep["broker_api_called_false_verified"] is False
    assert any("broker_api_called" in n for n in rep["notes"])


def test_learning_efficiency_formula():
    le = cla.compute_learning_efficiency(
        closed_loss_count=10, moltbook_lesson_count=8,
        recalibration_candidate_count=5, future_rule_candidate_count=2,
        repeat_mistake_count=2,
    )
    assert le["lesson_conversion_rate"] == 0.8
    assert le["repeat_error_rate"] == 0.25
    assert le["learning_efficiency_score"] == round(0.8 * 0.75, 4)


def test_learning_efficiency_repeats_penalize_score():
    low = cla.compute_learning_efficiency(
        closed_loss_count=4, moltbook_lesson_count=4,
        recalibration_candidate_count=0, future_rule_candidate_count=0,
        repeat_mistake_count=3,
    )
    high = cla.compute_learning_efficiency(
        closed_loss_count=4, moltbook_lesson_count=4,
        recalibration_candidate_count=0, future_rule_candidate_count=0,
        repeat_mistake_count=0,
    )
    assert low["learning_efficiency_score"] < high["learning_efficiency_score"]


def test_learning_efficiency_zero_loss_is_safe():
    le = cla.compute_learning_efficiency(
        closed_loss_count=0, moltbook_lesson_count=0,
        recalibration_candidate_count=0, future_rule_candidate_count=0,
        repeat_mistake_count=0,
    )
    assert le["no_loss_history"] is True
    assert 0.0 <= le["learning_efficiency_score"] <= 1.0
