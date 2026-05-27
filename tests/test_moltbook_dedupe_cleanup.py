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
    """Insert two structurally-identical rows that are NOT a fixture signature.

    Uses a non-denylisted ticker / non-fixture numeric signature so the
    new dynamic classifier collapses them as semantic duplicates (and
    not as the curated fixture denylist).  Operator-confirmed flag is
    set so the legacy thesis-only test/demo gate also stays out of the
    way — the test is about cross-source dedupe.
    """
    bridge.record_reconciliation_learning(
        trade_id="MT_DUP1", event_id="EV1", ticker="ZZZ",
        post_trade_outcome="CLOSED_WIN",
        actual_exit_price=137.42, exit_quantity=3.5,
        entry_price=125.13, entry_quantity=3.5, realized_pl=42.815,
        thesis="Real operator thesis for the duplicate-pair seed.",
        db_path=db,
    )
    conn = sqlite3.connect(str(db))
    try:
        existing = conn.execute(
            "SELECT * FROM moltbook_entries WHERE ticker='ZZZ'"
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
    dup_rows = [r for r in rows if r["ticker"] == "ZZZ"]
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
    assert len([r for r in visible if r["ticker"] == "ZZZ"]) == 1
    all_rows = persistence.get_moltbook_entries(db_path=db, include_hidden=True)
    # And the hidden row is still there (advisory: never delete).
    assert len([r for r in all_rows if r["ticker"] == "ZZZ"]) == 2
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
    # New dynamic visibility classifier uses HIDE_* reasons; accept either
    # the new HIDE_TEST_DEMO_FIXTURE or the legacy SKIP_TEST_DEMO_FIXTURE.
    assert polluted["hidden_reason"] in {
        "HIDE_TEST_DEMO_FIXTURE",
        bridge.SKIP_TEST_DEMO_FIXTURE,
    }


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


# -- New visibility-classifier mirror tests ---------------------------------


def _insert_raw(db: Path, **overrides) -> None:
    conn = sqlite3.connect(str(db))
    try:
        cols = [d[1] for d in conn.execute("PRAGMA table_info(moltbook_entries)")]
        defaults = {
            "entry_id": "MB_FAKE",
            "event_id": "EV_X",
            "ticker": "AAPL",
            "original_signal_thesis": "Real thesis.",
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
            "logged_at": "2026-05-27T07:00:00+00:00",
            "advisory_status": "ADVISORY_ONLY",
            "human_review_required": 1,
            "execution_mode": "HUMAN_ONLY",
            "ai_execution_count": 0,
            "trade_id": "MT_X",
            "source_trade_state": "CLOSED_WIN",
            "event_type": "CLOSED_WIN",
            "outcome_quality": "GOOD_PROCESS_WIN",
            "entry_price": 100.0,
            "exit_price": 110.0,
            "exit_quantity": 1.0,
            "stop_loss_price": None,
            "take_profit_price": None,
            "realized_pl": 10.0,
            "booked_percent": None,
            "ride_percent": None,
            "mistake_tags": "",
            "success_tags": "",
            "lesson": "",
            "notes": "",
            "created_at": "2026-05-27T07:00:00+00:00",
            "updated_at": "2026-05-27T07:00:00+00:00",
            "idempotency_key": "MBK_FAKE",
            "learning_direction": "SUCCESS_PATTERN",
            "hidden_from_default_view": 0,
            "hidden_reason": "",
            "is_duplicate": 0,
            "duplicate_of": "",
            "eligibility_reason": "",
        }
        defaults.update(overrides)
        values = [defaults.get(c) for c in cols]
        conn.execute(
            f"INSERT INTO moltbook_entries ({','.join(cols)}) VALUES "
            f"({','.join('?' for _ in cols)})",
            values,
        )
        conn.commit()
    finally:
        conn.close()


def test_cleanup_dry_run_emits_visibility_breakdown(db, tmp_path):
    _insert_raw(db, entry_id="MB_DUP_F", ticker="DUP",
                idempotency_key="MBK_DUP_F",
                entry_price=100.0, exit_price=110.0, exit_quantity=2.0,
                realized_pl=20.0, original_signal_thesis="fixture")
    _insert_raw(db, entry_id="MB_SAFE_F", ticker="SAFE",
                idempotency_key="MBK_SAFE_F",
                entry_price=50.0, exit_price=55.0, exit_quantity=1.0,
                realized_pl=5.0, original_signal_thesis="fixture")
    _insert_raw(db, entry_id="MB_MSFT_F", ticker="MSFT",
                idempotency_key="MBK_MSFT_F",
                entry_price=400.0, exit_price=430.0, exit_quantity=2.0,
                realized_pl=60.0,
                original_signal_thesis="Operator long MSFT for swing setup")
    report_path = tmp_path / "moltbook_visibility_cleanup_report.json"
    report = cleanup.run(db, apply_changes=False, report_path=report_path,
                         hide_ineligible=True)
    assert report["raw_total"] == 3
    assert report["would_hide_fixture"] >= 3
    assert "visibility_counts" in report
    assert "visible_symbols" in report
    assert "hidden_symbols" in report
    # MSFT/DUP/SAFE all hidden, not visible.
    assert "DUP" in report["hidden_symbols"]
    assert "SAFE" in report["hidden_symbols"]
    assert "MSFT" in report["hidden_symbols"]
    assert report_path.exists()


def test_cleanup_dry_run_does_not_mutate(db, tmp_path):
    _insert_raw(db, entry_id="MB_DUP_F", ticker="DUP",
                idempotency_key="MBK_DUP_NM",
                entry_price=100.0, exit_price=110.0, exit_quantity=2.0,
                realized_pl=20.0)
    before = persistence.get_moltbook_entries(db_path=db, include_hidden=True)
    cleanup.run(db, apply_changes=False, hide_ineligible=True,
                report_path=tmp_path / "r.json")
    after = persistence.get_moltbook_entries(db_path=db, include_hidden=True)
    assert len(after) == len(before)
    for a, b in zip(after, before):
        assert int(a["hidden_from_default_view"] or 0) == int(b["hidden_from_default_view"] or 0)


def test_cleanup_yes_mirrors_api_classifier(db, tmp_path, monkeypatch):
    """Cleanup --yes hides exactly the rows the API classifier would hide."""
    import scripts.moltbook_api as moltbook_api
    monkeypatch.setattr(persistence, "DB_PATH", db)
    _insert_raw(db, entry_id="MB_DUP_F", ticker="DUP",
                idempotency_key="MBK_DUP_F",
                entry_price=100.0, exit_price=110.0, exit_quantity=2.0,
                realized_pl=20.0)
    _insert_raw(db, entry_id="MB_REAL", ticker="NVDA",
                idempotency_key="MBK_REAL_NVDA",
                original_signal_thesis="Real NVDA close.",
                entry_price=900.0, exit_price=920.0, exit_quantity=1.0,
                realized_pl=20.0)
    api_before = moltbook_api.list_moltbook_entries()
    api_visible_ids_before = {e["entry_id"] for e in api_before["items"]}

    cleanup.run(db, apply_changes=True, hide_ineligible=True,
                report_path=tmp_path / "r.json",
                permission_decision=_admin_decision(db))

    api_after = moltbook_api.list_moltbook_entries()
    api_visible_ids_after = {e["entry_id"] for e in api_after["items"]}
    # The same set is visible after the apply — the classifier was
    # already truthful and the apply only persisted the verdict.
    assert api_visible_ids_after == api_visible_ids_before
    # DB now reflects hidden flags.
    rows = persistence.get_moltbook_entries(db_path=db, include_hidden=True)
    dup_row = next(r for r in rows if r["entry_id"] == "MB_DUP_F")
    assert int(dup_row["hidden_from_default_view"] or 0) == 1
