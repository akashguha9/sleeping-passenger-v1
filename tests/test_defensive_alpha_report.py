"""Defensive-alpha report — what the MVP prevented.

Proves it counts blocked stale signals, source echoes, fake-data blocks, and
verifies advisory-only invariants — and never claims a P/L gain.
"""
from __future__ import annotations

import json
import sqlite3

import scripts.persistence as persistence
from scripts import defensive_alpha_report as dar


def test_report_runs_on_empty_db(tmp_path):
    db = tmp_path / "empty.db"
    persistence.init_schema(db)
    rep = dar.build_report(db)
    assert rep["db_available"] is True
    assert rep["total_defensive_events"] == 0
    assert rep["claims_pl_improvement"] is False


def test_report_counts_stale_and_repaired(tmp_path):
    db = tmp_path / "stale.db"
    persistence.init_schema(db)
    # A stale signal cell + a repaired loss + a duplicate thesis echo.
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO signal_cell_index (cell_key, freshness_state, first_seen_at,"
        " last_seen_at) VALUES ('c1','stale','t','t')"
    )
    conn.commit()
    conn.close()
    persistence.upsert_duplicate_fingerprint("fp1", ticker="GLD", db_path=db)
    persistence.upsert_duplicate_fingerprint("fp1", ticker="GLD", db_path=db)
    persistence.insert_moltbook_entry(
        "MB1", "EV1", "GLD", "t", "ai", "r", "d", "MT1", "Closed at a loss",
        "manual_exit_loss", "lesson", "", "", "", "t", db_path=db,
    )
    rep = dar.build_report(db)
    assert rep["stale_signals_downgraded"] == 1
    assert rep["closed_losses_captured_as_lessons"] == 1
    assert rep["source_echoes_detected"] >= 1


def test_report_counts_fake_data_blocked(tmp_path):
    """A quarantined fake row is a defensive WIN — it was successfully excluded
    from canonical active truth, so it counts as ``fake_data_rows_blocked``."""
    from scripts.manual_trade_origin import QUARANTINE_PROVENANCE
    db = tmp_path / "fake.db"
    persistence.init_schema(db)
    persistence.insert_manual_trade(
        "MT_blocked", "FABRIC_SPY", "SPY", "BUY", 1.0, 400.0,
        "2026-05-16T07:00:00+00:00", "Persistence above 0.8", "", "seed", db,
        created_via=QUARANTINE_PROVENANCE,
    )
    rep = dar.build_report(db)
    assert rep["fake_data_rows_blocked"] >= 1


def test_report_counts_fake_data_still_leaking(tmp_path):
    """A detected-but-not-yet-cleaned fake row is NOT a win — it is surfaced as
    ``fake_data_rows_still_leaking`` and excluded from the blocked count."""
    db = tmp_path / "leaking.db"
    persistence.init_schema(db)
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO moltbook_entries (entry_id, event_id, ticker,"
        " original_signal_thesis, mistake_type, lesson_learned, logged_at,"
        " manual_trade_log_id) VALUES"
        " ('MBx','FABRIC_SPY','SPY','Persistence above 0.8','no_trade_correct',"
        " 'd','t','')"
    )
    conn.commit()
    conn.close()
    rep = dar.build_report(db)
    assert rep["fake_data_rows_still_leaking"] >= 1
    assert rep["fake_data_rows_blocked"] == 0


def test_report_verifies_advisory_invariants(tmp_path):
    db = tmp_path / "inv.db"
    persistence.init_schema(db)
    rep = dar.build_report(db)
    assert rep["advisory_only_invariants_verified"] is True
    assert rep["human_execution_required_verified"] is True
    assert rep["advisory_status"] == "ADVISORY_ONLY"
    assert rep["broker_api_called"] is False


def test_report_never_claims_pl(tmp_path):
    db = tmp_path / "pl.db"
    persistence.init_schema(db)
    rep = dar.build_report(db)
    blob = json.dumps(rep).lower()
    for forbidden in ("profitable", "made a profit", "beat the market",
                      "outperform", "increased returns"):
        assert forbidden not in blob, forbidden
