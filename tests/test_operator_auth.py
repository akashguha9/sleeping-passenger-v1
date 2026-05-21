"""Local operator authorization floor — advisory-only role gate.

Proves the Kanté "no unclear responsibility" invariant: every write-like
action is gated by an explicit role, no role can unlock broker execution, and
every authorization stamp is advisory-only.
"""
from __future__ import annotations

import pytest

from scripts import operator_auth as auth


# ---------------------------------------------------------------------------
# Roles + ranking
# ---------------------------------------------------------------------------


def test_three_roles_least_privilege_ordered():
    assert auth.ROLE_ORDER == ("VIEWER", "OPERATOR", "ADMIN")
    assert auth.role_rank("VIEWER") < auth.role_rank("OPERATOR") < auth.role_rank("ADMIN")


def test_unknown_role_fails_closed_to_viewer():
    assert auth.normalize_role("root") == "VIEWER"
    assert auth.normalize_role(None) == "VIEWER"
    assert auth.normalize_role("operator") == "OPERATOR"  # case-insensitive


# ---------------------------------------------------------------------------
# VIEWER cannot perform write-like actions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("action", sorted(auth.WRITE_LIKE_ACTIONS))
def test_viewer_cannot_perform_write_like_actions(action):
    decision = auth.authorize("VIEWER", action)
    assert decision["authorized"] is False, action


def test_viewer_can_read():
    for action in auth.READ_ACTIONS:
        assert auth.authorize("VIEWER", action)["authorized"] is True, action


# ---------------------------------------------------------------------------
# OPERATOR can run the reconciliation bridge + write-like advisory ops
# ---------------------------------------------------------------------------


def test_operator_can_run_reconciliation_bridge():
    assert auth.authorize("OPERATOR", "run_moltbook_bridge")["authorized"] is True
    assert auth.authorize("OPERATOR", "reconciliation_update")["authorized"] is True
    assert auth.authorize("OPERATOR", "manual_trade_log")["authorized"] is True
    assert auth.authorize("OPERATOR", "export_reports")["authorized"] is True


def test_operator_cannot_perform_admin_actions():
    for action in ("cleanup_scripts", "restore_db", "config_mutation",
                   "release_gate_override"):
        assert auth.authorize("OPERATOR", action)["authorized"] is False, action


# ---------------------------------------------------------------------------
# ADMIN required for cleanup / restore-like actions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "action",
    ["cleanup_scripts", "restore_db", "config_mutation", "release_gate_override"],
)
def test_admin_required_for_maintenance(action):
    assert auth.authorize("ADMIN", action)["authorized"] is True
    assert auth.authorize("OPERATOR", action)["authorized"] is False
    assert auth.authorize("VIEWER", action)["authorized"] is False


# ---------------------------------------------------------------------------
# No role can unlock broker execution
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["VIEWER", "OPERATOR", "ADMIN"])
@pytest.mark.parametrize("action", sorted(auth.FORBIDDEN_ACTIONS))
def test_no_role_can_unlock_broker_execution(role, action):
    decision = auth.authorize(role, action)
    assert decision["authorized"] is False
    assert decision["kind"] == "forbidden"
    assert "structurally_locked" in decision["reason"]


def test_unknown_action_fails_closed():
    decision = auth.authorize("ADMIN", "do_something_undefined")
    assert decision["authorized"] is False
    assert decision["kind"] == "unknown"


# ---------------------------------------------------------------------------
# Every authorization stamp is advisory-only
# ---------------------------------------------------------------------------


def _all_decisions():
    decisions = []
    for role in auth.ROLE_ORDER:
        for action in list(auth.ACTION_REGISTRY) + list(auth.FORBIDDEN_ACTIONS):
            decisions.append(auth.authorize(role, action))
        decisions.append(auth.authorization_stamp(role))
    return decisions


def test_all_authorization_stamps_are_advisory_only():
    for stamp in _all_decisions():
        assert stamp["authorization_scope"] == "LOCAL_OPERATOR_ONLY"
        assert stamp["execution_permission"] is False
        assert stamp["execution_gate"] == "LOCKED"
        assert stamp["ai_execution_count"] == 0
        assert stamp["can_execute"] is False
        assert stamp["broker_api_called"] is False
        assert stamp["human_review_required"] is True


def test_require_raises_when_denied():
    with pytest.raises(PermissionError):
        auth.require("VIEWER", "manual_trade_log")
    # Allowed path returns the stamp.
    stamp = auth.require("OPERATOR", "manual_trade_log")
    assert stamp["authorized"] is True


def test_no_execution_language_in_module():
    import pathlib
    text = pathlib.Path(auth.__file__).read_text(encoding="utf-8").lower()
    # The module names forbidden actions as data; it must never *grant* them.
    assert '"authorized": true' not in text
    assert "broker_api_called=true" not in text
