"""Kanté Defensive Sprint — Task B: @guarded_mutation decorator / context proof.

Proves the collapsed write-boundary guard (decorator, context manager, and the
shared :func:`assert_guarded_mutation` helper) enforces exactly the invariants
the hand-rolled per-script preamble used to: a valid, allowed, correctly-classed
:class:`PermissionDecision` with clean locked safety stamps, plus the new
defence-in-depth dry-run and role-floor checks.  ``FORBIDDEN_EXECUTION`` can
never be wrapped.  No decorator performs IO or mutation.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import operator_permission_guard as guard
from scripts.operator_permission_guard import (
    OperationClass,
    OperatorRole,
    PermissionRequest,
    evaluate_permission,
)


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(guard.RECEIPT_DIR_ENV_VAR, str(tmp_path / "receipts"))
    monkeypatch.setenv(guard.AUDIT_PATH_ENV_VAR, str(tmp_path / "audit.jsonl"))
    monkeypatch.delenv(guard.ROLE_ENV_VAR, raising=False)
    return tmp_path


def _decision(
    tmp_path: Path,
    *,
    role: OperatorRole = OperatorRole.OPERATOR,
    op_class: OperationClass = OperationClass.REPAIR_WRITE,
    dry_run: bool = True,
    stamps: dict | None = None,
) -> guard.PermissionDecision:
    return evaluate_permission(PermissionRequest(
        operation_name="test_guarded_op",
        operation_class=op_class,
        operator_role=role,
        apply_requested=True,
        dry_run_completed=dry_run,
        db_path=str(tmp_path / "mvp_local.db"),
        safety_stamps=stamps or guard.caller_safety_stamps(),
    ))


# A representative decorated write target — pure, no IO.
@guard.guarded_mutation(
    operation_name="test_guarded_op",
    operation_class=OperationClass.REPAIR_WRITE,
    expected_role_floor=OperatorRole.OPERATOR,
    require_dry_run=True,
)
def _writer(value: int, *, permission_decision=None) -> int:
    return value * 2


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------


def test_decorated_write_without_decision_raises():
    with pytest.raises(PermissionError):
        _writer(21)  # no permission_decision kwarg


def test_decorated_write_with_denied_decision_raises(tmp_path):
    denied = _decision(tmp_path, role=OperatorRole.VIEWER)
    assert denied.allowed is False
    with pytest.raises(PermissionError):
        _writer(21, permission_decision=denied)


def test_decorated_write_with_wrong_operation_class_raises(tmp_path):
    # ADMIN RESTORE_WRITE is genuinely allowed, but it is the wrong class for a
    # REPAIR_WRITE-decorated boundary.
    mismatch = _decision(tmp_path, role=OperatorRole.ADMIN,
                         op_class=OperationClass.RESTORE_WRITE)
    assert mismatch.allowed is True
    with pytest.raises(PermissionError):
        _writer(21, permission_decision=mismatch)


def test_decorated_write_with_dirty_safety_stamps_raises(tmp_path):
    dirty = dict(guard.caller_safety_stamps())
    dirty["broker_api_called"] = True
    decision = _decision(tmp_path, stamps=dirty)
    assert decision.allowed is False
    with pytest.raises(PermissionError):
        _writer(21, permission_decision=decision)


def test_decorated_write_with_allowed_decision_succeeds(tmp_path):
    decision = _decision(tmp_path)
    assert decision.allowed is True
    assert _writer(21, permission_decision=decision) == 42


def test_decorator_records_metadata():
    meta = _writer.__guarded_mutation__
    assert meta["operation_class"] == "REPAIR_WRITE"
    assert meta["expected_role_floor"] == "OPERATOR"
    assert meta["require_dry_run"] is True


def test_decorator_cannot_wrap_forbidden_execution():
    with pytest.raises(ValueError):
        guard.guarded_mutation(
            operation_class=OperationClass.FORBIDDEN_EXECUTION)(lambda **k: None)


# ---------------------------------------------------------------------------
# Defence in depth: dry-run + role floor at the write boundary
# ---------------------------------------------------------------------------


def test_role_floor_blocks_below_floor_even_if_allowed(tmp_path):
    # An OPERATOR REPAIR_WRITE decision is allowed, but an ADMIN-floor boundary
    # must still reject it (defence in depth).
    decision = _decision(tmp_path, role=OperatorRole.OPERATOR)
    assert decision.allowed is True
    with pytest.raises(PermissionError):
        guard.assert_guarded_mutation(
            decision, operation_class=OperationClass.REPAIR_WRITE,
            expected_role_floor=OperatorRole.ADMIN)


def test_require_dry_run_blocks_missing_dry_run(tmp_path):
    # AUDIT_ONLY_WRITE is allowed without a dry-run, but a require_dry_run=True
    # boundary rejects a decision whose dry_run_completed is False.
    decision = _decision(tmp_path, op_class=OperationClass.AUDIT_ONLY_WRITE,
                         dry_run=False)
    assert decision.allowed is True
    with pytest.raises(PermissionError):
        guard.assert_guarded_mutation(
            decision, operation_class=OperationClass.AUDIT_ONLY_WRITE,
            require_dry_run=True)
    # …and passes when require_dry_run is relaxed.
    guard.assert_guarded_mutation(
        decision, operation_class=OperationClass.AUDIT_ONLY_WRITE,
        require_dry_run=False)


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


def test_context_manager_blocks_denied_decision(tmp_path):
    denied = _decision(tmp_path, role=OperatorRole.VIEWER)
    with pytest.raises(PermissionError):
        with guard.guarded_mutation_context(
            denied, operation_class=OperationClass.REPAIR_WRITE):
            raise AssertionError("body must not run on a denied decision")


def test_context_manager_yields_on_allowed_decision(tmp_path):
    decision = _decision(tmp_path)
    ran = False
    with guard.guarded_mutation_context(
        decision, operation_class=OperationClass.REPAIR_WRITE) as d:
        ran = True
        assert d is decision
    assert ran is True


# ---------------------------------------------------------------------------
# CLI helper: build_apply_decision
# ---------------------------------------------------------------------------


def test_build_apply_decision_allows_operator_with_receipt(tmp_path):
    db = str(tmp_path / "mvp_local.db")
    guard.write_dry_run_receipt("test_guarded_op", 3, db)
    decision = guard.build_apply_decision(
        "test_guarded_op", OperationClass.REPAIR_WRITE, db,
        operator_role="OPERATOR")
    assert decision.allowed is True


def test_build_apply_decision_denies_viewer(tmp_path):
    db = str(tmp_path / "mvp_local.db")
    guard.write_dry_run_receipt("test_guarded_op", 3, db)
    with pytest.raises(PermissionError):
        guard.build_apply_decision(
            "test_guarded_op", OperationClass.REPAIR_WRITE, db,
            operator_role="VIEWER")


def test_build_apply_decision_denies_unsafe_db_path():
    with pytest.raises(PermissionError):
        guard.build_apply_decision(
            "test_guarded_op", OperationClass.REPAIR_WRITE,
            "/etc/shadow", operator_role="OPERATOR")
