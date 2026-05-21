"""Operator audit log + write-like action enforcement (advisory-only).

Kanté Sprint 2 — Task 1.  :mod:`scripts.operator_auth` answers *"is this role
allowed?"* as a pure decision.  This module is the **enforcement boundary**:
it resolves the operator role, asks :mod:`operator_auth`, writes an immutable
audit event (allow *and* deny), and **fails closed** — raising
:class:`PermissionError` — when the action is not authorized.

Every operator-facing maintenance entrypoint (Moltbook bridge ``--write``,
fake-seed cleanup ``--apply``, DB restore ``--yes``, DB backup) routes its
write through :func:`enforce` so that:

* an unauthorized role can never perform the mutation (fail closed),
* every attempt — allowed or denied — leaves an audit trail,
* the audit trail is **JSONL audit-only**, never canonical truth, and never
  contains a secret value.

Role resolution
---------------
The role comes from (in order): an explicit argument, the ``MVP_OPERATOR_ROLE``
environment variable, else the safest role (``VIEWER``).  Unknown roles fail
closed to ``VIEWER`` via :func:`operator_auth.normalize_role`.

No role — not even ADMIN — can unlock broker execution: forbidden execution
actions are rejected by :mod:`operator_auth` before they ever reach here, and
every audit event carries the locked execution invariants.

Pure-ish contract
------------------
The only side effect is appending one JSON line to the audit log (best-effort;
a write failure never blocks the security decision).  No DB, no network, no
broker calls.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts import operator_auth as _auth
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import operator_auth as _auth  # type: ignore[no-redef]

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_AUDIT_PATH = _REPO_ROOT / "logs" / "operator_audit.jsonl"

# Env var that lets the operator declare their role for a maintenance session.
ROLE_ENV_VAR = "MVP_OPERATOR_ROLE"
# Env var that lets tests (and a hardened deployment) redirect the audit log.
AUDIT_PATH_ENV_VAR = "MVP_OPERATOR_AUDIT_PATH"

# Secret-like token patterns scrubbed from any free text that reaches the audit
# event (resource / reason / operator_id).  Mirrors compliance_preflight so the
# audit trail can never become a secret-leak surface.
_SECRET_RE: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(api[_-]?key|secret|token|bearer|password)\s*[=:]\s*\S{6,}"),
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"xai-[A-Za-z0-9]{16,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _redact(text: Any) -> str:
    s = str(text or "")
    for pattern in _SECRET_RE:
        s = pattern.sub("[REDACTED]", s)
    return s


def audit_path(explicit: Path | None = None) -> Path:
    """Resolve the audit-log path: explicit arg → env → repo default."""
    if explicit is not None:
        return Path(explicit)
    env = os.environ.get(AUDIT_PATH_ENV_VAR)
    if env:
        return Path(env)
    return _DEFAULT_AUDIT_PATH


def resolve_operator_role(explicit: Any = None) -> str:
    """Resolve the operator role: explicit arg → env → safest (VIEWER).

    Unknown / missing roles fail closed to ``VIEWER`` (least privilege).
    """
    if explicit is not None and str(explicit).strip():
        return _auth.normalize_role(explicit)
    env_role = os.environ.get(ROLE_ENV_VAR)
    return _auth.normalize_role(env_role)  # normalize_role(None) -> VIEWER


def build_audit_event(
    *,
    operator_id: str,
    operator_role: str,
    action: str,
    resource: str,
    allowed: bool,
    reason: str,
) -> dict[str, Any]:
    """Build the canonical audit event.  All free text is secret-redacted."""
    return {
        "timestamp_utc": _utc_now(),
        "operator_id": _redact(operator_id) or "local_operator",
        "operator_role": _auth.normalize_role(operator_role),
        "action": str(action or "").strip().lower(),
        "resource": _redact(resource),
        "allowed": bool(allowed),
        "reason": _redact(reason),
        # Locked execution invariants — every audit event re-asserts them.
        "advisory_status": _contract.ADVISORY_STATUS,
        "execution_gate": _contract.EXECUTION_GATE_LOCKED,
        "broker_api_called": False,
        "ai_execution_count": _contract.AI_EXECUTION_COUNT,
        "audit_only": True,
        "canonical_store": _contract.CANONICAL_STORE,
    }


def record_audit_event(event: dict[str, Any], *, path: Path | None = None) -> bool:
    """Append one audit event as a JSONL line (audit-only, never canonical).

    Best-effort: returns False (never raises) if the write fails, so a hostile
    filesystem cannot block the underlying security decision.
    """
    target = audit_path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(event, separators=(",", ":"), sort_keys=True) + "\n")
        return True
    except OSError:  # pragma: no cover - defensive
        return False


def enforce(
    action: str,
    *,
    role: Any = None,
    resource: str = "",
    operator_id: str | None = None,
    audit_path: Path | None = None,
) -> dict[str, Any]:
    """Authorize ``action`` for the resolved role; audit it; fail closed.

    Returns the authorization decision stamp on success.  Raises
    :class:`PermissionError` when the action is not authorized — the caller
    must therefore call this *before* performing any mutation, so a denied
    action never reaches the write.
    """
    resolved_role = resolve_operator_role(role)
    decision = _auth.authorize(resolved_role, action)
    event = build_audit_event(
        operator_id=operator_id or "local_operator",
        operator_role=resolved_role,
        action=action,
        resource=resource,
        allowed=bool(decision["authorized"]),
        reason=str(decision.get("reason", "")),
    )
    record_audit_event(event, path=audit_path)
    if not decision["authorized"]:
        raise PermissionError(
            f"operator_auth DENY: role={resolved_role} action={action} "
            f"resource={resource or '-'} :: {decision.get('reason', '')}"
        )
    decision["audit_event"] = event
    return decision


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="operator_audit_log.py",
        description=(
            "Inspect the operator audit log, or test-enforce an action. "
            "Advisory-only; never unlocks execution."
        ),
    )
    p.add_argument("--tail", type=int, default=20, help="Show the last N events.")
    p.add_argument("--audit-path", type=str, default=None)
    p.add_argument("--json", action="store_true")
    return p


def read_recent(path: Path | None = None, *, limit: int = 20) -> list[dict[str, Any]]:
    """Read the last ``limit`` audit events (read-only; tolerant of bad lines)."""
    target = audit_path(path)
    if not target.exists():
        return []
    events: list[dict[str, Any]] = []
    try:
        for line in target.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except (json.JSONDecodeError, ValueError):
                continue
    except OSError:  # pragma: no cover - defensive
        return []
    return events[-max(int(limit), 0):] if limit else events


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    path = Path(args.audit_path) if args.audit_path else None
    events = read_recent(path, limit=args.tail)
    if args.json:
        print(json.dumps({"report": "operator_audit_log", "events": events,
                          **_contract.advisory_safety_stamps()}, indent=2,
                         default=str))
    else:
        print(f"Operator audit log ({len(events)} recent event(s))")
        for e in events:
            verdict = "ALLOW" if e.get("allowed") else "DENY"
            print(f"  [{verdict}] {e.get('timestamp_utc')} "
                  f"{e.get('operator_role')} {e.get('action')} "
                  f"-> {e.get('resource') or '-'}")
    return 0


__all__ = [
    "ROLE_ENV_VAR",
    "AUDIT_PATH_ENV_VAR",
    "audit_path",
    "resolve_operator_role",
    "build_audit_event",
    "record_audit_event",
    "enforce",
    "read_recent",
]


if __name__ == "__main__":
    raise SystemExit(main())
