"""Operator-auth enforcement at write-like call sites (Kanté Sprint 2 — Task 1).

operator_auth answers "is this role allowed?"; operator_audit_log.enforce is the
boundary that *applies* the answer: it fails closed, and it leaves an audit
trail for both allow and deny.  These tests prove the enforcement, not just the
policy.
"""
from __future__ import annotations

import json

import pytest

from scripts import operator_audit_log as audit
from scripts import moltbook_reconciliation_bridge as bridge
from scripts import moltbook_cleanup_fake_seed as cleanup
from scripts import restore_db
from scripts import backup_db


@pytest.fixture(autouse=True)
def _isolated_audit(tmp_path, monkeypatch):
    """Redirect the audit log to a per-test file and clear the role env."""
    path = tmp_path / "operator_audit.jsonl"
    monkeypatch.setenv(audit.AUDIT_PATH_ENV_VAR, str(path))
    monkeypatch.delenv(audit.ROLE_ENV_VAR, raising=False)
    return path


# ---------------------------------------------------------------------------
# enforce(): fail-closed decision + audit trail
# ---------------------------------------------------------------------------


def test_operator_allowed_for_moltbook_bridge(_isolated_audit):
    decision = audit.enforce("run_moltbook_bridge", role="OPERATOR",
                             resource="moltbook_entries")
    assert decision["authorized"] is True
    events = audit.read_recent()
    assert events and events[-1]["allowed"] is True
    assert events[-1]["action"] == "run_moltbook_bridge"


def test_viewer_denied_for_moltbook_bridge(_isolated_audit):
    with pytest.raises(PermissionError):
        audit.enforce("run_moltbook_bridge", role="VIEWER",
                      resource="moltbook_entries")
    # A denied attempt is still audited (allowed=False).
    events = audit.read_recent()
    assert events and events[-1]["allowed"] is False


def test_operator_denied_admin_actions(_isolated_audit):
    for action in ("cleanup_scripts", "restore_db"):
        with pytest.raises(PermissionError):
            audit.enforce(action, role="OPERATOR")


def test_admin_allowed_cleanup_and_restore(_isolated_audit):
    assert audit.enforce("cleanup_scripts", role="ADMIN")["authorized"] is True
    assert audit.enforce("restore_db", role="ADMIN")["authorized"] is True


def test_missing_role_fails_closed_to_viewer(_isolated_audit):
    # No explicit role and no env → VIEWER → write denied.
    with pytest.raises(PermissionError):
        audit.enforce("run_moltbook_bridge")
    assert audit.resolve_operator_role() == "VIEWER"


def test_unknown_role_denied_for_write(_isolated_audit):
    with pytest.raises(PermissionError):
        audit.enforce("manual_trade_log", role="superuser")


@pytest.mark.parametrize("role", ["VIEWER", "OPERATOR", "ADMIN"])
def test_no_role_can_unlock_execution(role, _isolated_audit):
    with pytest.raises(PermissionError):
        audit.enforce("unlock_execution_gate", role=role)
    with pytest.raises(PermissionError):
        audit.enforce("place_order", role=role)


def test_audit_event_has_locked_invariants_and_no_secrets(_isolated_audit):
    # A resource string carrying a secret-looking token must be redacted.
    with pytest.raises(PermissionError):
        audit.enforce("manual_trade_log", role="VIEWER",
                      resource="db?api_key=sk-ABCDEFGHIJKLMNOPQRST")
    events = audit.read_recent()
    last = events[-1]
    assert last["advisory_status"] == "ADVISORY_ONLY"
    assert last["execution_gate"] == "LOCKED"
    assert last["broker_api_called"] is False
    assert last["ai_execution_count"] == 0
    blob = json.dumps(events)
    assert "sk-ABCDEFGHIJKLMNOPQRST" not in blob
    assert "[REDACTED]" in blob


# ---------------------------------------------------------------------------
# CLI entrypoints fail closed
# ---------------------------------------------------------------------------


def _make_db(tmp_path):
    from scripts import persistence
    db = tmp_path / "mvp_local.db"
    persistence.init_schema(db)
    return db


def test_bridge_cli_write_denied_for_viewer(tmp_path, _isolated_audit):
    db = _make_db(tmp_path)
    rc = bridge.main(["--db-path", str(db), "--write", "--operator-role", "VIEWER"])
    assert rc == 2  # fail closed
    events = audit.read_recent()
    assert events[-1]["allowed"] is False


def test_bridge_cli_write_allowed_for_operator(tmp_path, _isolated_audit):
    db = _make_db(tmp_path)
    rc = bridge.main(["--db-path", str(db), "--write", "--operator-role", "OPERATOR"])
    assert rc == 0
    events = audit.read_recent()
    assert events[-1]["allowed"] is True


def test_bridge_cli_dry_run_open_to_any_role(tmp_path, _isolated_audit):
    db = _make_db(tmp_path)
    # No --write: read-only, no enforcement, no audit event required.
    rc = bridge.main(["--db-path", str(db), "--operator-role", "VIEWER"])
    assert rc == 0


def test_cleanup_cli_apply_requires_admin(tmp_path, _isolated_audit):
    db = _make_db(tmp_path)
    assert cleanup.main(["--db-path", str(db), "--apply",
                         "--operator-role", "OPERATOR"]) == 2
    assert cleanup.main(["--db-path", str(db), "--apply",
                         "--operator-role", "ADMIN"]) == 0


def test_restore_cli_apply_denied_for_operator(tmp_path, _isolated_audit):
    rc = restore_db.main(["--backup-file", str(tmp_path / "nope.db"),
                          "--yes", "--operator-role", "OPERATOR"])
    assert rc == 2  # denied before any restore work


def test_backup_cli_denied_for_viewer(tmp_path, _isolated_audit):
    db = _make_db(tmp_path)
    rc = backup_db.main(["--db-path", str(db), "--backup-dir",
                         str(tmp_path / "bk"), "--operator-role", "VIEWER"])
    assert rc == 2
