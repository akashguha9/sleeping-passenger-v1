"""Kanté Task 3 + 4 — function-level guard rollout proof.

These tests prove the operator-permission guard is enforced at the *write
boundary* of every mutation-capable repair script, not merely at the CLI
``main``.  A future caller that imports a write function directly cannot bypass
the guard: the function refuses to run without a clean, allowed
:class:`PermissionDecision`.

Scripts covered (all four):

* ``quarantine_fake_manual_trades.apply_quarantine``
* ``moltbook_cleanup_fake_seed.cleanup`` (apply branch)
* ``backfill_manual_trade_log_provenance.run`` (apply branch)
* ``repair_manual_trade_reconciliation.run`` (apply branch)

Advisory-only invariants: no broker call, no execution, dry-run receipts and
the audit log are audit-only, SQLite remains canonical truth.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import scripts.persistence as persistence
from scripts import operator_permission_guard as _guard
from scripts import quarantine_fake_manual_trades as quar
from scripts import moltbook_cleanup_fake_seed as molt
from scripts import backfill_manual_trade_log_provenance as backfill
from scripts import repair_manual_trade_reconciliation as repair


def _decision(
    operation_name: str,
    db: Path,
    *,
    role: _guard.OperatorRole = _guard.OperatorRole.OPERATOR,
    operation_class: _guard.OperationClass = _guard.OperationClass.REPAIR_WRITE,
    dry_run_completed: bool = True,
    safety_stamps: dict | None = None,
) -> _guard.PermissionDecision:
    return _guard.evaluate_permission(_guard.PermissionRequest(
        operation_name=operation_name,
        operation_class=operation_class,
        operator_role=role,
        apply_requested=True,
        dry_run_completed=dry_run_completed,
        db_path=str(db),
        safety_stamps=safety_stamps or _guard.caller_safety_stamps(),
    ))


@pytest.fixture
def db(tmp_path: Path) -> Path:
    target = tmp_path / "mvp_local.db"
    persistence.init_schema(target)
    return target


# ---------------------------------------------------------------------------
# 1. Direct-import bypass is blocked on EVERY write function.
# ---------------------------------------------------------------------------


def test_quarantine_write_blocks_missing_decision(db: Path) -> None:
    with pytest.raises(PermissionError):
        quar.apply_quarantine(db, [], permission_decision=None)


def test_moltbook_cleanup_blocks_missing_decision(db: Path) -> None:
    with pytest.raises(PermissionError):
        molt.cleanup(db, apply=True)  # no decision passed


def test_backfill_run_blocks_missing_decision(db: Path) -> None:
    with pytest.raises(PermissionError):
        backfill.run(db, apply=True)  # no decision passed


def test_repair_run_blocks_missing_decision(db: Path) -> None:
    with pytest.raises(PermissionError):
        repair.run(db, apply=True)  # no decision passed


# ---------------------------------------------------------------------------
# 2. A DENIED decision (VIEWER) is rejected at the write boundary.
# ---------------------------------------------------------------------------


def test_write_blocks_denied_decision(db: Path) -> None:
    denied = _decision("quarantine_fake_manual_trades", db,
                       role=_guard.OperatorRole.VIEWER)
    assert denied.allowed is False
    with pytest.raises(PermissionError):
        quar.apply_quarantine(db, [], permission_decision=denied)


# ---------------------------------------------------------------------------
# 3. A wrong-operation-class decision is rejected.
# ---------------------------------------------------------------------------


def test_write_blocks_operation_class_mismatch(db: Path) -> None:
    # An ADMIN RESTORE_WRITE allow is genuinely allowed, but it is the WRONG
    # class for a repair-write boundary — the function-level guard must reject.
    mismatch = _decision(
        "repair_manual_trade_reconciliation", db,
        role=_guard.OperatorRole.ADMIN,
        operation_class=_guard.OperationClass.RESTORE_WRITE)
    assert mismatch.allowed is True
    with pytest.raises(PermissionError):
        repair.run(db, apply=True, permission_decision=mismatch)


# ---------------------------------------------------------------------------
# 4. Dirty safety stamps cannot reach the write boundary.
# ---------------------------------------------------------------------------


def test_write_blocks_dirty_safety_stamps(db: Path) -> None:
    dirty = dict(_guard.caller_safety_stamps())
    dirty["execution_gate"] = "UNLOCKED"
    decision = _decision("backfill_manual_trade_log_provenance", db,
                         safety_stamps=dirty)
    assert decision.allowed is False
    with pytest.raises(PermissionError):
        backfill.run(db, apply=True, permission_decision=decision)


# ---------------------------------------------------------------------------
# 5. A clean ALLOWED decision passes the boundary (no PermissionError).
# ---------------------------------------------------------------------------


def test_allowed_decision_passes_write_boundary(db: Path) -> None:
    # No candidates → 0 rows changed, but crucially NO PermissionError: the
    # assertion accepted the clean OPERATOR decision.
    n = quar.apply_quarantine(
        db, [], permission_decision=_decision("quarantine_fake_manual_trades", db))
    assert n == 0
    rep = molt.cleanup(
        db, apply=True,
        permission_decision=_decision("moltbook_cleanup_fake_seed", db))
    assert rep["removed"] == 0
    out = repair.run(
        db, apply=True,
        permission_decision=_decision("repair_manual_trade_reconciliation", db))
    assert out.applied is True


# ---------------------------------------------------------------------------
# 6. CLI guard rollout for the two repair scripts (Task 3).
# ---------------------------------------------------------------------------


def _seed_manual_trade(db: Path) -> None:
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "INSERT INTO manual_trades (trade_id, event_id, ticker, side, "
            "quantity, price, executed_at, created_via) VALUES "
            "(?,?,?,?,?,?,?,?)",
            ("MT_x", "EV_x", "AAPL", "BUY", 1.0, 1.0,
             "2026-05-18T00:00:00+00:00", "manual_trade_log"),
        )
        conn.commit()
    finally:
        conn.close()


def test_backfill_dry_run_writes_receipt(db: Path, tmp_path: Path,
                                         monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_guard.RECEIPT_DIR_ENV_VAR, str(tmp_path / "receipts"))
    monkeypatch.setenv(_guard.AUDIT_PATH_ENV_VAR, str(tmp_path / "audit.jsonl"))
    rc = backfill.main(["--db-path", str(db), "--dry-run"])
    assert rc == 0
    assert _guard.validate_dry_run_receipt(
        "backfill_manual_trade_log_provenance", str(db))


def test_repair_dry_run_writes_receipt(db: Path, tmp_path: Path,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_guard.RECEIPT_DIR_ENV_VAR, str(tmp_path / "receipts"))
    rc = repair.main(["--db", str(db)])
    assert rc == 0
    assert _guard.validate_dry_run_receipt(
        "repair_manual_trade_reconciliation", str(db))


def test_repair_viewer_apply_denied(db: Path, tmp_path: Path,
                                    monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_guard.RECEIPT_DIR_ENV_VAR, str(tmp_path / "receipts"))
    monkeypatch.delenv("MVP_OPERATOR_ROLE", raising=False)  # default VIEWER
    repair.main(["--db", str(db)])  # write receipt first
    rc = repair.main(["--db", str(db), "--apply"])
    assert rc == 2  # denied


def test_backfill_operator_apply_without_receipt_denied(
    db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Fresh receipt dir → no receipt exists; OPERATOR --apply must be denied.
    monkeypatch.setenv(_guard.RECEIPT_DIR_ENV_VAR, str(tmp_path / "empty_receipts"))
    monkeypatch.setenv("MVP_OPERATOR_ROLE", "OPERATOR")
    rc = backfill.main(["--db-path", str(db), "--apply"])
    assert rc == 2  # denied: no dry-run receipt


def test_repair_operator_apply_with_receipt_allowed(
    db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_manual_trade(db)
    monkeypatch.setenv(_guard.RECEIPT_DIR_ENV_VAR, str(tmp_path / "receipts"))
    monkeypatch.setenv("MVP_OPERATOR_ROLE", "OPERATOR")
    assert repair.main(["--db", str(db)]) == 0          # dry-run writes receipt
    assert repair.main(["--db", str(db), "--apply"]) == 0  # allowed


# ---------------------------------------------------------------------------
# 7. The audit log records both ALLOW and DENY attempts.
# ---------------------------------------------------------------------------


def test_audit_log_records_allow_and_deny(
    db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setenv(_guard.AUDIT_PATH_ENV_VAR, str(audit))
    monkeypatch.setenv(_guard.RECEIPT_DIR_ENV_VAR, str(tmp_path / "receipts"))

    # DENY: VIEWER apply (no role env).
    monkeypatch.delenv("MVP_OPERATOR_ROLE", raising=False)
    backfill.main(["--db-path", str(db), "--dry-run"])
    backfill.main(["--db-path", str(db), "--apply"])

    # ALLOW: OPERATOR apply with receipt.
    monkeypatch.setenv("MVP_OPERATOR_ROLE", "OPERATOR")
    backfill.main(["--db-path", str(db), "--dry-run"])
    backfill.main(["--db-path", str(db), "--apply"])

    events = [json.loads(line) for line in
              audit.read_text(encoding="utf-8").splitlines() if line.strip()]
    relevant = [e for e in events
                if e["operation_name"] == "backfill_manual_trade_log_provenance"]
    assert any(e["allowed"] is False for e in relevant), "deny not audited"
    assert any(e["allowed"] is True for e in relevant), "allow not audited"
    # Audit-only invariants on every event.
    for e in relevant:
        assert e["audit_only"] is True
        assert e["broker_api_called"] is False
        assert e["ai_execution_count"] == 0
        assert e["execution_gate"] == "LOCKED"
