"""Business / demo value report — honest, advisory-only risk-prevention summary.

Kanté "no unlogged loss": counts risk prevented and losses repaired, never a
P/L gain, and flags missing data honestly.
"""
from __future__ import annotations

import json

import scripts.persistence as persistence
from scripts import business_value_report as bvr


def test_report_generates_with_empty_db(tmp_path):
    db = tmp_path / "empty.db"
    persistence.init_schema(db)
    rep = bvr.build_report(db)
    assert rep["db_available"] is True
    assert rep["stale_signals_detected"] == 0
    assert rep["duplicate_ai_thesis_detected"] == 0
    assert rep["unreconciled_risk_count"] == 0


def test_report_handles_missing_db_honestly(tmp_path):
    rep = bvr.build_report(tmp_path / "nope.db")
    assert rep["db_available"] is False
    assert any("not available" in n.lower() for n in rep["notes"])


def test_report_never_claims_pl_improvement(tmp_path):
    db = tmp_path / "pl.db"
    persistence.init_schema(db)
    rep = bvr.build_report(db)
    assert rep["claims_pl_improvement"] is False
    blob = json.dumps(rep).lower()
    # The report must not *claim* a gain.  (The disclaimer legitimately uses
    # the word "profit" to disclaim it, so we check claim phrases, not the
    # bare word.)
    for forbidden in ("profitable", "made a profit", "return improved",
                      "outperform", "beat the market", "gains of",
                      "increased returns"):
        assert forbidden not in blob, forbidden


def test_report_includes_advisory_disclaimer(tmp_path):
    db = tmp_path / "disc.db"
    persistence.init_schema(db)
    rep = bvr.build_report(db)
    assert "advisory-only" in rep["advisory_disclaimer"].lower()
    assert rep["human_execution_required"] is True
    assert rep["advisory_status"] == "ADVISORY_ONLY"


def test_report_detects_duplicate_thesis_and_repaired_loss(tmp_path):
    db = tmp_path / "data.db"
    persistence.init_schema(db)
    # Two sightings of one fingerprint → a duplicate AI thesis (echo).
    persistence.upsert_duplicate_fingerprint("fp1", ticker="GLD", db_path=db)
    persistence.upsert_duplicate_fingerprint("fp1", ticker="GLD", db_path=db)
    # A repaired closed loss in Moltbook.
    persistence.insert_moltbook_entry(
        "MB1", "EV1", "GLD", "thesis", "ai", "refl", "exit", "MT1",
        "Closed at a loss", "manual_exit_loss", "lesson", "", "", "", "t",
        db_path=db,
    )
    rep = bvr.build_report(db)
    assert rep["duplicate_ai_thesis_detected"] == 1
    assert rep["closed_losses_repaired_into_moltbook"] == 1


def test_report_flags_fake_pollution(tmp_path):
    import sqlite3
    db = tmp_path / "poll.db"
    persistence.init_schema(db)
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "INSERT INTO moltbook_entries (entry_id, event_id, ticker,"
            " original_signal_thesis, mistake_type, lesson_learned, logged_at,"
            " manual_trade_log_id) VALUES"
            " ('MBx','FABRIC_SPY','SPY','Persistence above 0.8','no_trade_correct',"
            " 'd','t','')"
        )
        conn.commit()
    finally:
        conn.close()
    rep = bvr.build_report(db)
    assert rep["fake_demo_pollution_active"] == 1
    assert rep["fake_demo_pollution_prevented"] is False
