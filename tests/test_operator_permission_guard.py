"""Tests for the central operator_permission_guard (Kanté Defensive Sprint).

Proves the guard's pure decision logic, the dry-run-receipt lifecycle, the
audit-only logging (allow + deny, no secrets), and the wiring into
``quarantine_fake_manual_trades.py`` / ``moltbook_cleanup_fake_seed.py``.

The guard delegates *role* policy to operator_auth; these tests focus on the
operation-class taxonomy, receipts, DB-path safety, safety-invariant gate, and
the forbidden-execution ceiling that no role can cross.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts import operator_permission_guard as guard
from tests.helpers import scanner_probes as probes
from scripts.operator_permission_guard import (
    OperationClass,
    OperatorRole,
    PermissionRequest,
    evaluate_permission,
)


@pytest.fixture()
def clean_stamps() -> dict:
    return guard.caller_safety_stamps()


@pytest.fixture(autouse=True)
def _isolate_guard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect receipt dir + audit log to tmp; clear the role env."""
    monkeypatch.setenv(guard.RECEIPT_DIR_ENV_VAR, str(tmp_path / "receipts"))
    monkeypatch.setenv(guard.AUDIT_PATH_ENV_VAR, str(tmp_path / "audit.jsonl"))
    monkeypatch.delenv(guard.ROLE_ENV_VAR, raising=False)
    return tmp_path


def _db(tmp_path: Path) -> str:
    return str(tmp_path / "mvp_local.db")


def _req(tmp_path, **over) -> PermissionRequest:
    base = dict(
        operation_name="quarantine_fake_manual_trades",
        operation_class=OperationClass.REPAIR_WRITE,
        operator_role=OperatorRole.OPERATOR,
        apply_requested=True,
        dry_run_completed=True,
        db_path=_db(tmp_path),
        safety_stamps=guard.caller_safety_stamps(),
    )
    base.update(over)
    return PermissionRequest(**base)


# ---------------------------------------------------------------------------
# Role / operation-class matrix
# ---------------------------------------------------------------------------


def test_default_role_is_viewer(monkeypatch):
    monkeypatch.delenv(guard.ROLE_ENV_VAR, raising=False)
    assert guard.load_operator_role_from_env() == OperatorRole.VIEWER


def test_unknown_role_fails_closed_to_viewer(monkeypatch):
    monkeypatch.setenv(guard.ROLE_ENV_VAR, "superuser")
    assert guard.load_operator_role_from_env() == OperatorRole.VIEWER


def test_viewer_denied_repair_write_apply(tmp_path, clean_stamps):
    d = evaluate_permission(_req(tmp_path, operator_role=OperatorRole.VIEWER))
    assert d.allowed is False
    assert any("role_not_allowed" in r for r in d.denial_reasons)


def test_operator_repair_write_denied_without_dry_run(tmp_path):
    d = evaluate_permission(_req(tmp_path, dry_run_completed=False))
    assert d.allowed is False
    assert any("dry_run_required" in r for r in d.denial_reasons)


def test_operator_repair_write_allowed_after_dry_run(tmp_path):
    d = evaluate_permission(_req(tmp_path, dry_run_completed=True))
    assert d.allowed is True
    assert d.denial_reasons == []


def test_mutation_requires_explicit_apply(tmp_path):
    d = evaluate_permission(_req(tmp_path, apply_requested=False))
    assert d.allowed is False
    assert any("explicit_apply_required" in r for r in d.denial_reasons)


def test_operator_denied_restore_write(tmp_path):
    d = evaluate_permission(_req(
        tmp_path, operation_name="restore_db",
        operation_class=OperationClass.RESTORE_WRITE,
        operator_role=OperatorRole.OPERATOR))
    assert d.allowed is False
    assert any("role_not_allowed" in r for r in d.denial_reasons)


def test_admin_allowed_restore_write_after_dry_run(tmp_path):
    d = evaluate_permission(_req(
        tmp_path, operation_name="restore_db",
        operation_class=OperationClass.RESTORE_WRITE,
        operator_role=OperatorRole.ADMIN, dry_run_completed=True))
    assert d.allowed is True


def test_admin_restore_write_denied_without_dry_run(tmp_path):
    d = evaluate_permission(_req(
        tmp_path, operation_name="restore_db",
        operation_class=OperationClass.RESTORE_WRITE,
        operator_role=OperatorRole.ADMIN, dry_run_completed=False))
    assert d.allowed is False
    assert any("dry_run_required" in r for r in d.denial_reasons)


def test_audit_only_write_needs_no_dry_run(tmp_path):
    d = evaluate_permission(_req(
        tmp_path, operation_name="append_audit",
        operation_class=OperationClass.AUDIT_ONLY_WRITE,
        operator_role=OperatorRole.OPERATOR, dry_run_completed=False))
    assert d.allowed is True


# ---------------------------------------------------------------------------
# Forbidden execution — no role may ever cross this ceiling
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", list(OperatorRole))
def test_every_role_denied_forbidden_execution(tmp_path, role):
    d = evaluate_permission(_req(
        tmp_path, operation_name="place_order",
        operation_class=OperationClass.FORBIDDEN_EXECUTION,
        operator_role=role))
    assert d.allowed is False
    assert any("forbidden_execution" in r for r in d.denial_reasons)


@pytest.mark.parametrize("name", [
    "place_order", "submit_order", "execute_trade",
    "unlock_execution_gate", "broker_execute",
])
def test_forbidden_by_operation_name_even_if_class_repair(tmp_path, name):
    """A broker-ish operation name is rejected even if mislabelled REPAIR_WRITE."""
    d = evaluate_permission(_req(
        tmp_path, operation_name=name,
        operation_class=OperationClass.REPAIR_WRITE,
        operator_role=OperatorRole.ADMIN))
    assert d.allowed is False
    assert any("forbidden_execution" in r for r in d.denial_reasons)


def test_forbid_execution_operation_helper():
    assert guard.forbid_execution_operation(
        "anything", OperationClass.FORBIDDEN_EXECUTION) is True
    assert guard.forbid_execution_operation(
        "place_order", OperationClass.REPAIR_WRITE) is True
    assert guard.forbid_execution_operation(
        "quarantine", OperationClass.REPAIR_WRITE) is False


# ---------------------------------------------------------------------------
# Safety invariants + DB path
# ---------------------------------------------------------------------------


def test_dirty_safety_stamps_deny(tmp_path):
    dirty = guard.caller_safety_stamps()
    dirty["execution_gate"] = "UNLOCKED"
    d = evaluate_permission(_req(tmp_path, safety_stamps=dirty))
    assert d.allowed is False
    assert any("safety_invariant_dirty" in r for r in d.denial_reasons)


def test_broker_called_stamp_denies(tmp_path):
    dirty = guard.caller_safety_stamps()
    dirty["broker_api_called"] = True
    d = evaluate_permission(_req(tmp_path, safety_stamps=dirty))
    assert d.allowed is False
    assert any("safety_invariant_dirty" in r for r in d.denial_reasons)


def test_ai_execution_count_stamp_denies(tmp_path):
    dirty = guard.caller_safety_stamps()
    dirty["ai_execution_count"] = 1
    d = evaluate_permission(_req(tmp_path, safety_stamps=dirty))
    assert d.allowed is False


def test_unsafe_db_path_denies(tmp_path):
    for bad in ("/etc/shadow", "C:\\Windows\\System32\\evil.db", "", None):
        d = evaluate_permission(_req(tmp_path, db_path=bad))
        assert d.allowed is False
        assert any("db_path_not_allowed" in r for r in d.denial_reasons)


def test_safe_db_path_allowed_repo_and_temp(tmp_path):
    assert guard.safe_db_path_allowed(str(tmp_path / "x.db")) is True
    repo_runtime = guard._REPO_ROOT / "runtime" / "mvp_local.db"
    assert guard.safe_db_path_allowed(str(repo_runtime)) is True
    assert guard.safe_db_path_allowed("/etc/passwd") is False
    assert guard.safe_db_path_allowed(None) is False


# ---------------------------------------------------------------------------
# Dry-run receipts
# ---------------------------------------------------------------------------


def test_receipt_validates_within_ttl(tmp_path):
    db = _db(tmp_path)
    guard.write_dry_run_receipt("op_a", 3, db)
    assert guard.validate_dry_run_receipt("op_a", db) is True


def test_receipt_target_count_zero_is_valid(tmp_path):
    db = _db(tmp_path)
    guard.write_dry_run_receipt("op_zero", 0, db)
    assert guard.validate_dry_run_receipt("op_zero", db) is True


def test_stale_receipt_denied(tmp_path):
    db = _db(tmp_path)
    guard.write_dry_run_receipt("op_a", 3, db)
    # max_age 0 minutes → any receipt is already stale.
    assert guard.validate_dry_run_receipt("op_a", db, max_age_minutes=0) is False


def test_mismatched_receipt_denied(tmp_path):
    db = _db(tmp_path)
    guard.write_dry_run_receipt("op_a", 3, db)
    # Wrong operation name.
    assert guard.validate_dry_run_receipt("op_b", db) is False
    # Wrong DB path.
    assert guard.validate_dry_run_receipt("op_a", str(tmp_path / "other.db")) is False


def test_missing_receipt_denied(tmp_path):
    assert guard.validate_dry_run_receipt("never_written", _db(tmp_path)) is False


# ---------------------------------------------------------------------------
# Audit log — records allow + deny, no secrets, hashed db path
# ---------------------------------------------------------------------------


def test_audit_log_records_allowed_decision(tmp_path, _isolate_guard):
    guard.require_permission_or_exit(_req(tmp_path))
    events = guard.read_recent_audit_events()
    assert events and events[-1]["allowed"] is True
    assert events[-1]["operation_class"] == "REPAIR_WRITE"


def test_audit_log_records_denied_decision(tmp_path):
    with pytest.raises(PermissionError):
        guard.require_permission_or_exit(
            _req(tmp_path, operator_role=OperatorRole.VIEWER))
    events = guard.read_recent_audit_events()
    assert events and events[-1]["allowed"] is False
    assert events[-1]["denial_reasons"]


def test_audit_log_carries_locked_invariants(tmp_path):
    guard.require_permission_or_exit(_req(tmp_path))
    last = guard.read_recent_audit_events()[-1]
    assert last["execution_gate"] == "LOCKED"
    assert last["broker_api_called"] is False
    assert last["ai_execution_count"] == 0
    assert last["advisory_only"] is True
    assert last["audit_only"] is True


def test_audit_log_does_not_expose_secrets(tmp_path):
    # Probe assembled at runtime — never literal scanner bait in source.
    fake_key = probes.sk_style_token("ABCDEFGHIJKLMNOPQRST")
    leaky = f"quarantine?{probes.api_key_assignment(fake_key)}"
    with pytest.raises(PermissionError):
        guard.require_permission_or_exit(_req(
            tmp_path, operation_name=leaky,
            operator_role=OperatorRole.VIEWER))
    blob = json.dumps(guard.read_recent_audit_events())
    assert fake_key not in blob
    assert "[REDACTED]" in blob


def test_audit_log_hashes_db_path_not_raw(tmp_path):
    guard.require_permission_or_exit(_req(tmp_path))
    last = guard.read_recent_audit_events()[-1]
    # The raw DB path must not appear; only its hash.
    assert str(tmp_path) not in json.dumps(last)
    assert last["db_path_hash"] == guard.db_path_hash(_db(tmp_path))


# ---------------------------------------------------------------------------
# Wiring: quarantine_fake_manual_trades.py
# ---------------------------------------------------------------------------


def _init_db_with_fake_row(tmp_path: Path) -> Path:
    from scripts import persistence
    db = tmp_path / "mvp_local.db"
    persistence.init_schema(db)
    # Plant one obviously-fake row the quarantine classifier will flag.
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "INSERT INTO manual_trades (trade_id, event_id, ticker, side, "
            "quantity, price, thesis, created_via, executed_at) VALUES "
            "(?,?,?,?,?,?,?,?,?)",
            ("MT_fake1", "FABRIC_SPY", "SPY", "BUY", 1.0, 1.0,
             "Persistence above 0.8", "manual_trade_log", "2026-01-01T00:00:00Z"),
        )
        conn.commit()
    finally:
        conn.close()
    return db


def test_quarantine_dry_run_writes_receipt(tmp_path, monkeypatch):
    from scripts import quarantine_fake_manual_trades as q
    db = _init_db_with_fake_row(tmp_path)
    rc = q.main(["--db", str(db), "--dry-run"])
    assert rc == 0
    assert guard.validate_dry_run_receipt(q.OPERATION_NAME, str(db)) is True


def test_quarantine_apply_denied_for_viewer(tmp_path, monkeypatch):
    from scripts import quarantine_fake_manual_trades as q
    db = _init_db_with_fake_row(tmp_path)
    monkeypatch.setenv("MVP_OPERATOR_ROLE", "VIEWER")
    q.main(["--db", str(db), "--dry-run"])  # receipt exists...
    rc = q.main(["--db", str(db), "--apply"])  # ...but VIEWER cannot apply.
    assert rc == 2
    events = guard.read_recent_audit_events()
    assert events[-1]["allowed"] is False


def test_quarantine_apply_denied_without_receipt(tmp_path, monkeypatch):
    from scripts import quarantine_fake_manual_trades as q
    db = _init_db_with_fake_row(tmp_path)
    monkeypatch.setenv("MVP_OPERATOR_ROLE", "OPERATOR")
    # No dry-run first → no receipt → apply must be denied.
    rc = q.main(["--db", str(db), "--apply"])
    assert rc == 2


def test_quarantine_apply_allowed_for_operator_with_receipt(tmp_path, monkeypatch):
    from scripts import quarantine_fake_manual_trades as q
    db = _init_db_with_fake_row(tmp_path)
    monkeypatch.setenv("MVP_OPERATOR_ROLE", "OPERATOR")
    assert q.main(["--db", str(db), "--dry-run"]) == 0
    assert q.main(["--db", str(db), "--apply"]) == 0
    # The fake row was re-stamped, not deleted.
    conn = sqlite3.connect(str(db))
    try:
        created_via = conn.execute(
            "SELECT created_via FROM manual_trades WHERE trade_id=?",
            ("MT_fake1",),
        ).fetchone()[0]
    finally:
        conn.close()
    from scripts.manual_trade_origin import QUARANTINE_PROVENANCE
    assert created_via == QUARANTINE_PROVENANCE


# ---------------------------------------------------------------------------
# Wiring: moltbook_cleanup_fake_seed.py (keeps its ADMIN gate; guard adds
# safety-invariant verification + unified audit alongside)
# ---------------------------------------------------------------------------


def test_moltbook_cleanup_apply_denied_for_operator(tmp_path, monkeypatch):
    from scripts import persistence
    from scripts import moltbook_cleanup_fake_seed as cleanup
    monkeypatch.setenv(
        "MVP_OPERATOR_AUDIT_PATH", str(tmp_path / "op_audit.jsonl"))
    db = tmp_path / "mvp_local.db"
    persistence.init_schema(db)
    assert cleanup.main(["--db-path", str(db), "--apply",
                         "--operator-role", "OPERATOR"]) == 2


def test_moltbook_cleanup_apply_allowed_for_admin(tmp_path, monkeypatch):
    from scripts import persistence
    from scripts import moltbook_cleanup_fake_seed as cleanup
    monkeypatch.setenv(
        "MVP_OPERATOR_AUDIT_PATH", str(tmp_path / "op_audit.jsonl"))
    db = tmp_path / "mvp_local.db"
    persistence.init_schema(db)
    assert cleanup.main(["--db-path", str(db), "--apply",
                         "--operator-role", "ADMIN"]) == 0
    # The guard recorded a unified audit event for the allowed ADMIN apply.
    events = guard.read_recent_audit_events()
    assert any(e["operation_name"] == "moltbook_cleanup_fake_seed"
               and e["allowed"] for e in events)
