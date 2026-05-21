"""Local operator authorization floor — a lightweight, advisory-only role gate.

This is **not** a web login, an external auth provider, or a SaaS account
system.  It is the smallest possible thing that answers one local question:

    "For this single-machine private operator, is the role attempting this
     write-like action allowed to do so?"

Three roles, least-privilege ordered::

    VIEWER  < OPERATOR < ADMIN

* ``VIEWER``   — read dashboard / status / moltbook / reconciliation.
* ``OPERATOR`` — VIEWER, plus: manual trade log, reconciliation update,
  run the moltbook bridge, export reports.
* ``ADMIN``    — OPERATOR, plus: cleanup scripts, restore DB, config
  mutation, release-gate override.

Hard ceiling — advisory-only
----------------------------
Authorization here gates *local advisory record-keeping operations only*.  It
**never** grants broker execution.  No role — not even ADMIN — can unlock the
execution gate: :func:`authorize` returns ``authorized=False`` for any broker /
order / execution-unlock action regardless of role.  Every authorization stamp
carries the locked execution invariants from :mod:`scripts.advisory_contract`:

    authorization_scope     = "LOCAL_OPERATOR_ONLY"
    execution_permission    = False
    execution_gate          = "LOCKED"
    ai_execution_count      = 0
    human_review_required   = True

Unknown roles fail closed to ``VIEWER`` (least privilege); unknown actions fail
closed to "not authorized".  Pure module: no DB, no network, no broker calls.
"""
from __future__ import annotations

import argparse
import json
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

VIEWER = "VIEWER"
OPERATOR = "OPERATOR"
ADMIN = "ADMIN"

# Ordered least → most privileged.  Rank is the index.
ROLE_ORDER: tuple[str, ...] = (VIEWER, OPERATOR, ADMIN)
ROLES: frozenset[str] = frozenset(ROLE_ORDER)

AUTHORIZATION_SCOPE = "LOCAL_OPERATOR_ONLY"

# Canonical action registry.  Each action maps to the *minimum* role required
# and a human-readable kind.  ``read`` actions are available to everyone;
# ``write`` actions need OPERATOR; ``admin`` actions need ADMIN.
ACTION_REGISTRY: dict[str, dict[str, str]] = {
    # VIEWER (read-only)
    "read_dashboard": {"min_role": VIEWER, "kind": "read"},
    "read_status": {"min_role": VIEWER, "kind": "read"},
    "read_moltbook": {"min_role": VIEWER, "kind": "read"},
    "read_reconciliation": {"min_role": VIEWER, "kind": "read"},
    # OPERATOR (write-like advisory record-keeping)
    "manual_trade_log": {"min_role": OPERATOR, "kind": "write"},
    "reconciliation_update": {"min_role": OPERATOR, "kind": "write"},
    "run_moltbook_bridge": {"min_role": OPERATOR, "kind": "write"},
    "export_reports": {"min_role": OPERATOR, "kind": "write"},
    # ADMIN (privileged maintenance)
    "cleanup_scripts": {"min_role": ADMIN, "kind": "admin"},
    "restore_db": {"min_role": ADMIN, "kind": "admin"},
    "config_mutation": {"min_role": ADMIN, "kind": "admin"},
    "release_gate_override": {"min_role": ADMIN, "kind": "admin"},
}

# Actions that are STRUCTURALLY forbidden for every role.  These exist so a
# caller that mistakenly asks "can this role place a broker order / unlock
# execution?" always gets a hard NO with a clear reason — the answer can never
# be yes, by product invariant.
FORBIDDEN_ACTIONS: frozenset[str] = frozenset({
    "broker_execution",
    "place_order",
    "submit_order",
    "execute_trade",
    "unlock_execution_gate",
    "enable_auto_trading",
})

# Convenience views used by callers and tests.
READ_ACTIONS: frozenset[str] = frozenset(
    a for a, m in ACTION_REGISTRY.items() if m["kind"] == "read"
)
WRITE_LIKE_ACTIONS: frozenset[str] = frozenset(
    a for a, m in ACTION_REGISTRY.items() if m["kind"] in {"write", "admin"}
)


def normalize_role(value: Any) -> str:
    """Coerce ``value`` to a known role; unknown input fails closed to VIEWER."""
    text = str(value or "").strip().upper()
    return text if text in ROLES else VIEWER


def role_rank(role: Any) -> int:
    """Return the privilege rank of ``role`` (VIEWER=0 .. ADMIN=2)."""
    return ROLE_ORDER.index(normalize_role(role))


def authorization_stamp(role: Any) -> dict[str, Any]:
    """Build the advisory-only authorization stamp every write-like surface
    should record.  Carries the locked execution invariants verbatim."""
    stamp: dict[str, Any] = {
        "operator_role": normalize_role(role),
        "authorization_scope": AUTHORIZATION_SCOPE,
        "human_review_required": True,
        "execution_permission": False,
        "execution_gate": _contract.EXECUTION_GATE_LOCKED,
        "ai_execution_count": _contract.AI_EXECUTION_COUNT,
        "can_execute": False,
        "broker_api_called": False,
        "broker_order_id": _contract.BROKER_ORDER_NONE,
        "advisory_status": _contract.ADVISORY_STATUS,
    }
    return stamp


def authorize(role: Any, action: Any) -> dict[str, Any]:
    """Decide whether ``role`` may perform ``action`` (advisory-only).

    Returns the authorization stamp plus ``authorized`` / ``required_role`` /
    ``reason``.  Forbidden execution actions are always ``authorized=False``;
    unknown actions fail closed.
    """
    resolved_role = normalize_role(role)
    action_key = str(action or "").strip().lower()
    out = authorization_stamp(resolved_role)
    out["action"] = action_key

    if action_key in FORBIDDEN_ACTIONS:
        out["authorized"] = False
        out["required_role"] = None
        out["kind"] = "forbidden"
        out["reason"] = (
            "execution_structurally_locked: no role can unlock broker "
            "execution — this MVP is advisory-only."
        )
        return out

    meta = ACTION_REGISTRY.get(action_key)
    if meta is None:
        out["authorized"] = False
        out["required_role"] = None
        out["kind"] = "unknown"
        out["reason"] = "unknown_action: failing closed (least privilege)."
        return out

    required = meta["min_role"]
    authorized = role_rank(resolved_role) >= role_rank(required)
    out["authorized"] = bool(authorized)
    out["required_role"] = required
    out["kind"] = meta["kind"]
    if authorized:
        out["reason"] = (
            f"{resolved_role} satisfies minimum role {required} for "
            f"{action_key} (advisory-only, execution still LOCKED)."
        )
    else:
        out["reason"] = (
            f"{resolved_role} is below required role {required} for "
            f"{action_key}."
        )
    return out


def require(role: Any, action: Any) -> dict[str, Any]:
    """Like :func:`authorize` but raises ``PermissionError`` when not allowed.

    Useful at the top of a write-like helper.  The returned stamp (on success)
    is the value a caller should persist alongside the operation.
    """
    decision = authorize(role, action)
    if not decision["authorized"]:
        raise PermissionError(decision["reason"])
    return decision


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="operator_auth.py",
        description=(
            "Local operator authorization floor (advisory-only).  Check "
            "whether a role may perform an action.  Never unlocks execution."
        ),
    )
    p.add_argument("--role", default=VIEWER, help="VIEWER | OPERATOR | ADMIN")
    p.add_argument("--action", default=None, help="Action key to check.")
    p.add_argument("--json", action="store_true", help="Emit JSON.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.action:
        decision = authorize(args.role, args.action)
        if args.json:
            print(json.dumps(decision, indent=2, sort_keys=True))
        else:
            verdict = "ALLOW" if decision["authorized"] else "DENY"
            print(f"[{verdict}] role={decision['operator_role']} "
                  f"action={decision['action']} :: {decision['reason']}")
        return 0 if decision["authorized"] else 1
    # No action: print the role/permission matrix.
    matrix = {
        role: sorted(
            a for a in ACTION_REGISTRY
            if authorize(role, a)["authorized"]
        )
        for role in ROLE_ORDER
    }
    payload = {
        "report": "operator_auth_matrix",
        "roles": list(ROLE_ORDER),
        "authorization_scope": AUTHORIZATION_SCOPE,
        "allowed_actions_by_role": matrix,
        "forbidden_actions": sorted(FORBIDDEN_ACTIONS),
        **_contract.advisory_safety_stamps(),
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("Local Operator Authorization Floor (advisory-only)")
        for role in ROLE_ORDER:
            print(f"  {role:<9}: {', '.join(matrix[role]) or '(none)'}")
        print(f"  forbidden (any role): {', '.join(sorted(FORBIDDEN_ACTIONS))}")
    return 0


__all__ = [
    "VIEWER",
    "OPERATOR",
    "ADMIN",
    "ROLE_ORDER",
    "ROLES",
    "AUTHORIZATION_SCOPE",
    "ACTION_REGISTRY",
    "FORBIDDEN_ACTIONS",
    "READ_ACTIONS",
    "WRITE_LIKE_ACTIONS",
    "normalize_role",
    "role_rank",
    "authorization_stamp",
    "authorize",
    "require",
]


if __name__ == "__main__":
    raise SystemExit(main())
