"""
Tests for scripts/moltbook_dedupe_cleanup.py.

Contract:
  - Dry-run by default; never mutates without --yes.
  - Groups duplicates by idempotency_key, falls back to normalized signature.
  - Picks canonical row by earliest created_at, ties broken by richness.
  - Marks duplicates hidden_from_default_view + is_duplicate + duplicate_of.
  - --hide-ineligible additionally hides rows that fail the eligibility
    contract (test/demo theses, open trades, missing exit/realized_pl).
  - Writes a JSON report to the supplied report path.
  - Never deletes any row.  Never touches broker state.  Safety stamps
    preserved on every surviving row.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import scripts.persistence as persistence
import scripts.moltbook_dedupe_cleanup as cleanup
import scripts.moltbook_learning_bridge as bridge
import scripts.operator_permission_guard as guard


def _admin_decision(db: Path):
    """Build an ADMIN PermissionDecision the cleanup boundary will accept.

    Writes a dry-run receipt first so the guard sees a recent dry-run was
    completed before the apply call.
    """
    op = "moltbook_dedupe_cleanup"
    guard.write_dry_run_receipt(op, target_count=0, db_path=str(db))
    return guard.build_apply_decision(
        op, guard.OperationClass.REPAIR_WRITE, str(db),
        operator_role="ADMIN",
        reason=f"{guard.NO_DRY_RUN_NEEDED}: hidden_from_default_view is reversible.",
    )


@pytest.fixture
def db(tmp_path: Path) -> Path:
    target = tmp_path / "cleanup.db"
    persistence.init_schema(target)
    return target


def _seed_pair_of_duplicates(db: Path) -> tuple[str, str]:
    """Insert two structurally-identical rows that share an idempotency_key."""
    bridge.record_reconciliation_learning(
        trade_id="MT_DUP1", event_id="EV1", ticker="DUP",
        post_trade_outcome="CLOSED_WIN",
        actual_exit_price=110.0, exit_quantity=2.0,
        entry_price=100.0, entry_quantity=2.0, realized_pl=20.0,
        thesis="Real operator thesis for the trade.",
        db_path=db,
    )
    # Second insert with the same trade_id + event_type → same idempotency_key
    # → updates the existing row (no duplicate).  To simulate the historical
    # bug where two trade_ids ended up with identical signatures, force-write
    # a clone with a different trade_id directly.
    conn = sqlite3.connect(str(db))
    try:
        existing = conn.execute(
            "SELECT * FROM moltbook_entries WHERE ticker='DUP'"
        ).fetchone()
        cols = [d[1] for d in conn.execute("PRAGMA table_info(moltbook_entries)")]
        existing_d = dict(zip(cols, existing))
        existing_d["entry_id"] = "MB_DUP_TWIN"
        existing_d["trade_id"] = "MT_DUP2"
        existing_d["idempotency_key"] = ""  # collapse to signature
        existing_d["created_at"] = "2026-05-21T10:00:00+00:00"
        existing_d["logged_at"] = existing_d.get("logged_at") or existing_d["created_at"]
        placeholders = ",".join("?" for _ in cols)
        conn.execute(
            f"INSERT INTO moltbook_entries ({','.join(cols)}) VALUES ({placeholders})",
            [existing_d[c] for c in cols],
        )
        conn.commit()
    finally:
        conn.close()
    rows = persistence.get_moltbook_entries(db_path=db)
    dup_rows = [r for r in rows if r["ticker"] == "DUP"]
    assert len(dup_rows) == 2
    return dup_rows[0]["entry_id"], dup_rows[1]["entry_id"]


def test_dry_run_writes_no_mutations(db, tmp_path):
    _seed_pair_of_duplicates(db)
    before = persistence.get_moltbook_entries(db_path=db)
    report_path = tmp_path / "report.json"
    report = cleanup.run(db, apply_changes=False, report_path=report_path)
    assert report["applied"] is False
    assert report["would_hide_duplicates"] == 1
    assert report["raw_total"] == 2
    # No mutation: every row still visible.
    after = persistence.get_moltbook_entries(db_path=db, include_hidden=False)
    assert len(after) == len(before)


def test_dry_run_writes_visibility_report_json(db, tmp_path):
    _seed_pair_of_duplicates(db)
    report_path = tmp_path / "moltbook_visibility_cleanup_report.json"
    cleanup.run(db, apply_changes=False, report_path=report_path)
    assert report_path.exists()
    parsed = json.loads(report_path.read_text(encoding="utf-8"))
    assert parsed["operation"] == "moltbook_dedupe_cleanup"
    assert parsed["advisory_status"] == "ADVISORY_ONLY"
    assert parsed["broker_api_called"] is False
    assert parsed["ai_execution_count"] == 0


def test_apply_yes_hides_duplicates_keeps_canonical(db, tmp_path):
    _seed_pair_of_duplicates(db)
    report = cleanup.run(db, apply_changes=True, report_path=tmp_path / "r.json",
                permission_decision=_admin_decision(db))
    assert report["applied"] is True
    assert report["applied_changes"]["hidden_duplicates_applied"] == 1
    visible = persistence.get_moltbook_entries(db_path=db, include_hidden=False)
    # Exactly one canonical row remains visible.
    assert len([r for r in visible if r["ticker"] == "DUP"]) == 1
    all_rows = persistence.get_moltbook_entries(db_path=db, include_hidden=True)
    # And the hidden row is still there (advisory: never delete).
    assert len([r for r in all_rows if r["ticker"] == "DUP"]) == 2
    hidden = [r for r in all_rows if r.get("hidden_from_default_view")]
    assert hidden
    assert hidden[0]["is_duplicate"] in (1, True)
    assert hidden[0]["duplicate_of"]


def test_hide_ineligible_marks_test_thesis_rows(db, tmp_path):
    # Insert a row whose thesis is "test" directly (bypassing the bridge
    # gate, simulating legacy polluted data).
    conn = sqlite3.connect(str(db))
    try:
        cols = [d[1] for d in conn.execute("PRAGMA table_info(moltbook_entries)")]
        defaults = {
            "entry_id": "MB_POLLUTED",
            "event_id": "EV_X",
            "ticker": "SPY",
            "original_signal_thesis": "test",
            "ai_interpretation": "",
            "user_reflection": "",
            "final_human_decision": "",
            "manual_trade_log_id": "",
            "outcome": "",
            "mistake_type": "good_signal_good_execution",
            "lesson_learned": "n/a",
            "bias_detected": "",
            "recalibration_note": "",
            "future_rule_update": "",
            "logged_at": "2026-05-27T07:53:06+00:00",
            "advisory_status": "ADVISORY_ONLY",
            "human_review_required": 1,
            "execution_mode": "HUMAN_ONLY",
            "ai_execution_count": 0,
            "trade_id": "MT_X",
            "source_trade_state": "CLOSED_WIN",
            "event_type": "CLOSED_WIN",
            "outcome_quality": "GOOD_PROCESS_WIN",
            "entry_price": 450.0,
            "exit_price": 452.0,
            "exit_quantity": 1.0,
            "stop_loss_price": None,
            "take_profit_price": None,
            "realized_pl": 2.0,
            "booked_percent": None,
            "ride_percent": None,
            "mistake_tags": "",
            "success_tags": "",
            "lesson": "",
            "notes": "",
            "created_at": "2026-05-27T07:53:06+00:00",
            "updated_at": "2026-05-27T07:53:06+00:00",
            "idempotency_key": "MBK_FAKE",
            "learning_direction": "SUCCESS_PATTERN",
            "hidden_from_default_view": 0,
            "hidden_reason": "",
            "is_duplicate": 0,
            "duplicate_of": "",
            "eligibility_reason": "",
        }
        values = [defaults.get(c) for c in cols]
        conn.execute(
            f"INSERT INTO moltbook_entries ({','.join(cols)}) VALUES "
            f"({','.join('?' for _ in cols)})",
            values,
        )
        conn.commit()
    finally:
        conn.close()

    report = cleanup.run(
        db, apply_changes=True, hide_ineligible=True,
        report_path=tmp_path / "r.json",
        permission_decision=_admin_decision(db),
    )
    assert report["applied_changes"]["hidden_ineligible_applied"] >= 1
    visible = persistence.get_moltbook_entries(db_path=db, include_hidden=False)
    assert not any(r["entry_id"] == "MB_POLLUTED" for r in visible)
    all_rows = persistence.get_moltbook_entries(db_path=db, include_hidden=True)
    polluted = next(r for r in all_rows if r["entry_id"] == "MB_POLLUTED")
    assert polluted["hidden_from_default_view"] in (1, True)
    assert polluted["hidden_reason"] == bridge.SKIP_TEST_DEMO_FIXTURE


def test_cleanup_never_deletes(db, tmp_path):
    _seed_pair_of_duplicates(db)
    before = persistence.get_moltbook_entries(db_path=db, include_hidden=True)
    cleanup.run(db, apply_changes=True, hide_ineligible=True,
                report_path=tmp_path / "r.json",
                permission_decision=_admin_decision(db))
    after = persistence.get_moltbook_entries(db_path=db, include_hidden=True)
    assert len(after) == len(before)


def test_cleanup_safety_stamps_preserved(db, tmp_path):
    _seed_pair_of_duplicates(db)
    cleanup.run(db, apply_changes=True, report_path=tmp_path / "r.json",
                permission_decision=_admin_decision(db))
    rows = persistence.get_moltbook_entries(db_path=db, include_hidden=True)
    for row in rows:
        assert row["advisory_status"] == "ADVISORY_ONLY"
        assert row["execution_mode"] == "HUMAN_ONLY"
        assert row["ai_execution_count"] == 0
