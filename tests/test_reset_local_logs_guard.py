"""reset_local_logs.py is a guarded mutation script (Kanté Defensive Sprint).

``scripts/reset_local_logs.py`` clears the local Manual Trade Log,
Reconciliation, and Moltbook journal tables (a destructive ``DELETE FROM``
record-keeping wipe).  The mutation-guard scanner therefore classifies it as a
HIGH-severity mutation script; if it were not wired into the central operator
permission guard it would BLOCK the release gate.

These tests prove the safety wiring:

1. The scanner counts it as *guarded* (and the unguarded set is empty).
2. Dry-run is the default and mutates nothing.
3. --apply fails closed without an explicit confirmation + a passed operator
   guard (role floor + recent dry-run receipt + safe local DB path), and only
   succeeds with all of them.
4. The script names no broker / order-execution verbs.

Advisory-only invariants: no broker call, no execution; the dry-run receipt
and the audit log are audit-only; SQLite remains canonical truth.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import scripts.persistence as persistence
from scripts import local_deploy_preflight as preflight
from scripts import operator_permission_guard as _guard
from scripts import reset_local_logs as reset


@pytest.fixture
def db(tmp_path: Path) -> Path:
    target = tmp_path / "mvp_local.db"
    persistence.init_schema(target)
    return target


def _seed_rows(db_path: Path, n: int = 3) -> int:
    """Insert ``n`` manual_trades rows; return the resulting row count."""
    conn = sqlite3.connect(str(db_path))
    try:
        for i in range(n):
            conn.execute(
                "INSERT INTO manual_trades (trade_id, event_id, ticker, side,"
                " quantity, price, executed_at, created_via) VALUES"
                " (?,?,?,?,?,?,?,?)",
                (f"MT_{i}", f"EV_{i}", "AAPL", "BUY", 1.0, 1.0,
                 "2026-06-05T00:00:00+00:00", "manual_trade_log"),
            )
        conn.commit()
        return int(conn.execute("SELECT COUNT(*) FROM manual_trades").fetchone()[0])
    finally:
        conn.close()


def _manual_trade_count(db_path: Path) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        return int(conn.execute("SELECT COUNT(*) FROM manual_trades").fetchone()[0])
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 1. The scanner counts reset_local_logs.py as guarded.
# ---------------------------------------------------------------------------


def test_reset_local_logs_is_guarded() -> None:
    coverage = preflight.scan_mutation_script_guarding()
    assert "reset_local_logs.py" in coverage["guarded"]
    assert coverage["unguarded"] == []


# ---------------------------------------------------------------------------
# 2. Dry-run mutates nothing.
# ---------------------------------------------------------------------------


def test_dry_run_does_not_mutate(db: Path, tmp_path: Path,
                                 monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_guard.RECEIPT_DIR_ENV_VAR, str(tmp_path / "receipts"))
    n_before = _seed_rows(db, 3)
    rc = reset.main(["--db", str(db)])  # dry-run is the default
    n_after = _manual_trade_count(db)
    assert rc == 0
    assert n_after == n_before == 3
    # Dry-run writes a receipt so a subsequent --apply can prove it happened.
    assert _guard.validate_dry_run_receipt("reset_local_logs", str(db))


# ---------------------------------------------------------------------------
# 3. --apply requires explicit confirmation AND a passed operator guard.
# ---------------------------------------------------------------------------


def test_apply_denied_without_operator_role(
    db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Confirmation present (--apply) but role floor not met (default VIEWER)."""
    monkeypatch.setenv(_guard.RECEIPT_DIR_ENV_VAR, str(tmp_path / "receipts"))
    monkeypatch.delenv("MVP_OPERATOR_ROLE", raising=False)  # default VIEWER
    _seed_rows(db, 3)
    reset.main(["--db", str(db)])  # write receipt first
    rc = reset.main(["--db", str(db), "--apply"])
    assert rc == 2  # denied: VIEWER may not REPAIR_WRITE
    assert _manual_trade_count(db) == 3  # rows_deleted == 0


def test_apply_denied_without_dry_run_receipt(
    db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OPERATOR + --apply but no recent dry-run receipt → denied, no mutation."""
    monkeypatch.setenv(_guard.RECEIPT_DIR_ENV_VAR, str(tmp_path / "empty_receipts"))
    monkeypatch.setenv("MVP_OPERATOR_ROLE", "OPERATOR")
    _seed_rows(db, 3)
    rc = reset.main(["--db", str(db), "--apply"])
    assert rc == 2  # denied: no dry-run receipt
    assert _manual_trade_count(db) == 3


def test_apply_allowed_with_operator_and_receipt(
    db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OPERATOR + recent receipt + local DB path → allowed; rows deleted."""
    monkeypatch.setenv(_guard.RECEIPT_DIR_ENV_VAR, str(tmp_path / "receipts"))
    monkeypatch.setenv("MVP_OPERATOR_ROLE", "OPERATOR")
    _seed_rows(db, 3)
    assert reset.main(["--db", str(db)]) == 0          # dry-run writes receipt
    assert reset.main(["--db", str(db), "--apply"]) == 0  # allowed
    assert _manual_trade_count(db) == 0  # journal cleared


def test_write_function_blocks_missing_decision(db: Path) -> None:
    """Direct import bypass: apply_reset without a decision must raise."""
    with pytest.raises(PermissionError):
        reset.apply_reset(db, permission_decision=None)


def test_write_function_blocks_denied_decision(db: Path) -> None:
    """A VIEWER (denied) decision is rejected at the write boundary."""
    denied = _guard.evaluate_permission(_guard.PermissionRequest(
        operation_name="reset_local_logs",
        operation_class=_guard.OperationClass.REPAIR_WRITE,
        operator_role=_guard.OperatorRole.VIEWER,
        apply_requested=True,
        dry_run_completed=True,
        db_path=str(db),
        safety_stamps=_guard.caller_safety_stamps(),
    ))
    assert denied.allowed is False
    n_before = _seed_rows(db, 2)
    with pytest.raises(PermissionError):
        reset.apply_reset(db, permission_decision=denied)
    assert _manual_trade_count(db) == n_before  # nothing deleted


# ---------------------------------------------------------------------------
# 4. No broker / order-execution verbs in the script text.
# ---------------------------------------------------------------------------


def test_no_execution_verbs_in_script() -> None:
    text = Path(reset.__file__).read_text(encoding="utf-8").lower()
    for verb in ("place_order", "submit_order", "route_order",
                 "execute_trade", "broker_connect", "ai_execute",
                 "send_order_to_exchange", "modify_broker_account"):
        # The script names NONE of these (it is record-keeping only).
        assert verb not in text, verb


def test_apply_advisory_invariants_intact(
    db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A clean OPERATOR decision passing the boundary never flips an exec flag."""
    monkeypatch.setenv(_guard.RECEIPT_DIR_ENV_VAR, str(tmp_path / "receipts"))
    _guard.write_dry_run_receipt("reset_local_logs", 0, str(db))
    decision = _guard.evaluate_permission(_guard.PermissionRequest(
        operation_name="reset_local_logs",
        operation_class=_guard.OperationClass.REPAIR_WRITE,
        operator_role=_guard.OperatorRole.OPERATOR,
        apply_requested=True,
        dry_run_completed=True,
        db_path=str(db),
        safety_stamps=_guard.caller_safety_stamps(),
    ))
    assert decision.allowed is True
    assert decision.broker_api_called is False
    assert decision.ai_execution_count == 0
    assert decision.execution_gate == "LOCKED"
    summary = reset.apply_reset(db, permission_decision=decision)
    assert summary["applied"] is True
