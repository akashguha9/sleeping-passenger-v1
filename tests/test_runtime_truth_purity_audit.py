"""Runtime truth-purity audit — fake data in canonical memory is poisoning.

Proves demo rows are detected, a clean DB passes, fake rows cannot silently
pass release readiness, and the audit never deletes data.
"""
from __future__ import annotations

import sqlite3

import scripts.persistence as persistence
from scripts import runtime_truth_purity_audit as tpa


def _insert_moltbook(db, **over):
    cols = {
        "entry_id": "MB1", "event_id": "EV1", "ticker": "GLD",
        "original_signal_thesis": "real thesis", "ai_interpretation": "ai",
        "user_reflection": "r", "final_human_decision": "d",
        "manual_trade_log_id": "MT1", "outcome": "Closed at a loss",
        "mistake_type": "manual_exit_loss", "lesson_learned": "lesson",
        "bias_detected": "", "recalibration_note": "", "future_rule_update": "",
        "logged_at": "t",
    }
    cols.update(over)
    persistence.insert_moltbook_entry(
        cols["entry_id"], cols["event_id"], cols["ticker"],
        cols["original_signal_thesis"], cols["ai_interpretation"],
        cols["user_reflection"], cols["final_human_decision"],
        cols["manual_trade_log_id"], cols["outcome"], cols["mistake_type"],
        cols["lesson_learned"], cols["bias_detected"], cols["recalibration_note"],
        cols["future_rule_update"], cols["logged_at"], db_path=db,
    )


def test_clean_db_passes(tmp_path):
    db = tmp_path / "clean.db"
    persistence.init_schema(db)
    _insert_moltbook(db)
    rep = tpa.build_audit(db)
    assert rep["fake_rows_detected"] == 0
    assert rep["release_gate_passed"] is True
    assert rep["truth_purity_score"] == 1.0


def test_detects_fabric_demo_row(tmp_path):
    db = tmp_path / "fabric.db"
    persistence.init_schema(db)
    _insert_moltbook(
        db, entry_id="MBx", event_id="FABRIC_SPY", ticker="SPY",
        original_signal_thesis="Persistence above 0.8",
        mistake_type="no_trade_correct", manual_trade_log_id="",
    )
    rep = tpa.build_audit(db)
    assert rep["fake_rows_detected"] >= 1
    assert "moltbook_entries" in rep["affected_tables"]
    assert rep["release_gate_passed"] is False


def test_fake_rows_cannot_silently_pass_release(tmp_path):
    db = tmp_path / "poison.db"
    persistence.init_schema(db)
    _insert_moltbook(
        db, entry_id="MBz", event_id="DEMO_1", ticker="QQQ",
        original_signal_thesis="Thesis A", manual_trade_log_id="",
    )
    rep = tpa.build_audit(db)
    assert rep["release_gate_passed"] is False
    assert rep["recommended_cleanup_command"]


def test_loss_review_entry_without_trade_ref_is_pollution(tmp_path):
    db = tmp_path / "orphan.db"
    persistence.init_schema(db)
    _insert_moltbook(
        db, entry_id="MBorphan", event_id="EV9", ticker="TSM",
        original_signal_thesis="legit thesis", mistake_type="stop_loss_breach",
        manual_trade_log_id="",
    )
    rep = tpa.build_audit(db)
    assert rep["fake_rows_detected"] >= 1
    assert any(
        ex["reason"] == "loss_review_entry_without_trade_reference"
        for ex in rep["pollution_examples"]
    )


def test_audit_does_not_delete_data(tmp_path):
    db = tmp_path / "nodelete.db"
    persistence.init_schema(db)
    _insert_moltbook(
        db, entry_id="MBx", event_id="FABRIC_SPY", ticker="SPY",
        original_signal_thesis="Persistence above 0.8", manual_trade_log_id="",
    )
    tpa.build_audit(db)
    conn = sqlite3.connect(str(db))
    count = conn.execute("SELECT COUNT(*) FROM moltbook_entries").fetchone()[0]
    conn.close()
    assert count == 1  # detection only, never deletion


def test_missing_db_fails_gate_closed(tmp_path):
    rep = tpa.build_audit(tmp_path / "nope.db")
    assert rep["db_available"] is False
    assert rep["release_gate_passed"] is False


def test_quarantined_fake_trade_does_not_block_release(tmp_path):
    """A fake row already re-stamped to QUARANTINE_PROVENANCE is excluded
    from canonical active truth: it is reported under
    ``quarantined_rows_excluded`` but must NOT count as active pollution or
    fail the release gate.  This is the Mission-A 2026-05-21 contract."""
    db = tmp_path / "quarantined.db"
    persistence.init_schema(db)
    # Fake by event_id prefix, but already quarantined.
    persistence.insert_manual_trade(
        "MT_quar1", "FABRIC_SPY", "SPY", "BUY", 1.0, 400.0,
        "2026-05-16T07:00:00+00:00", "Persistence above 0.8", "", "seed", db,
        created_via=tpa.QUARANTINE_PROVENANCE,
    )
    rep = tpa.build_audit(db)
    assert rep["fake_rows_detected"] == 0
    assert rep["quarantined_rows_excluded"] == 1
    assert rep["release_gate_passed"] is True
    assert rep["truth_purity_score"] == 1.0


def test_unquarantined_fake_trade_still_blocks_release(tmp_path):
    """A NEWLY leaked fake row (not yet quarantined) must still fail the gate
    closed — quarantine recognition must not blunt detection of fresh
    pollution."""
    db = tmp_path / "fresh_pollution.db"
    persistence.init_schema(db)
    persistence.insert_manual_trade(
        "MT_fresh", "FABRIC_QQQ", "QQQ", "BUY", 1.0, 400.0,
        "2026-05-16T07:00:00+00:00", "Persistence above 0.8", "", "seed", db,
        created_via="manual_trade_log",
    )
    rep = tpa.build_audit(db)
    assert rep["fake_rows_detected"] >= 1
    assert rep["release_gate_passed"] is False
    assert "manual_trades" in rep["affected_tables"]
    assert rep["recommended_cleanup_command"]


def test_real_trade_preserved_alongside_quarantined(tmp_path):
    """A genuine operator trade is never confused with a quarantined fake row
    and stays visible (origin USER_MANUAL)."""
    db = tmp_path / "mixed.db"
    persistence.init_schema(db)
    persistence.insert_manual_trade(
        "MT_quar2", "FABRIC_SPY", "SPY", "BUY", 1.0, 400.0,
        "2026-05-16T07:00:00+00:00", "Persistence above 0.8", "", "seed", db,
        created_via=tpa.QUARANTINE_PROVENANCE,
    )
    persistence.insert_manual_trade(
        "MT_real_ok", "EV_USER_REAL", "ICICIBANK.NS", "BUY", 3.0, 40.0,
        "2026-05-16T08:00:00+00:00",
        "break of pivot on bank-nifty breadth confirmation", "", "human", db,
        created_via="manual_trade_log",
    )
    rep = tpa.build_audit(db)
    assert rep["fake_rows_detected"] == 0
    assert rep["quarantined_rows_excluded"] == 1
    assert rep["release_gate_passed"] is True
    # Real row is still a visible user-manual trade.
    from scripts.manual_trade_origin import is_visible_manual_trade
    import sqlite3 as _sql
    conn = _sql.connect(str(db)); conn.row_factory = _sql.Row
    real = dict(conn.execute(
        "SELECT * FROM manual_trades WHERE trade_id='MT_real_ok'").fetchone())
    conn.close()
    assert is_visible_manual_trade(real) is True


def test_advisory_only_stamps_present(tmp_path):
    db = tmp_path / "stamp.db"
    persistence.init_schema(db)
    rep = tpa.build_audit(db)
    assert rep["advisory_status"] == "ADVISORY_ONLY"
    assert rep["broker_api_called"] is False
    assert rep["ai_execution_count"] == 0


# ---------------------------------------------------------------------------
# Large-scale performance proof sprint — synthetic fixture leak detection
# ---------------------------------------------------------------------------


def test_clean_db_has_no_perf_fixture_markers(tmp_path):
    db = tmp_path / "clean.db"
    persistence.init_schema(db)
    rep = tpa.build_audit(db)
    assert rep["perf_fixture_pollution_detected"] == 0
    assert rep["perf_fixture_markers"] == []
    assert rep["release_gate_passed"] is True


def test_detects_perf_fixture_event_id_in_canonical_db(tmp_path):
    """A leaked PERF_FIXTURE_ event_id MUST fail the truth-purity gate."""
    db = tmp_path / "leaked.db"
    persistence.init_schema(db)
    # Simulate a leaked synthetic row landing in canonical truth.
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "INSERT INTO signal_events (event_id, source_name, raw_payload, "
            "fetched_at, advisory_status, human_review_required, "
            "execution_gate, ai_execution_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("PERF_FIXTURE_0000001_SPY", "rss",
             '{"fixture_role":"synthetic_performance_fixture"}',
             "2026-05-24T00:00:00Z",
             "ADVISORY_ONLY", 1, "LOCKED", 0),
        )
        conn.commit()
    finally:
        conn.close()
    rep = tpa.build_audit(db)
    assert rep["perf_fixture_pollution_detected"] >= 1
    assert any("PERF_FIXTURE_" in m for m in rep["perf_fixture_markers"])
    assert "signal_events" in rep["affected_tables"]
    assert rep["release_gate_passed"] is False


def test_detects_perf_fixture_metadata_table_in_canonical_db(tmp_path):
    """A leaked ``_perf_fixture_metadata`` table MUST fail the gate too."""
    db = tmp_path / "leaked.db"
    persistence.init_schema(db)
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript(
            "CREATE TABLE _perf_fixture_metadata "
            "(key TEXT PRIMARY KEY, value TEXT NOT NULL);"
        )
        conn.commit()
    finally:
        conn.close()
    rep = tpa.build_audit(db)
    assert any("_perf_fixture_metadata" in m for m in rep["perf_fixture_markers"])
    assert rep["release_gate_passed"] is False
