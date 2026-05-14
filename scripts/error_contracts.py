"""
Lightweight error / warning envelope helpers.

Purpose
-------
Failures should tell the operator what to do. This module defines the
standard envelope shape used by the local-operating-discipline scripts
(``db_integrity_check``, ``local_security_audit``, ``source_refresh_audit``,
``reconciliation_queue``, ``pre_real_money_preflight``) so error responses
are diffable and never leak secrets.

The envelope is intentionally tiny. It is not a framework. It does not
swallow exceptions, retry, or hide failures — it just labels them.

Safety contract
---------------

    advisory_status        = "ADVISORY_ONLY"
    execution_gate         = "LOCKED"
    broker_api_called      = False
    ai_execution_count     = 0
    execution_permission   = False
    can_execute            = False

A failure response NEVER grants execution permission.
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Mapping

ADVISORY_STATUS = "ADVISORY_ONLY"
EXECUTION_GATE_LOCKED = "LOCKED"

VALID_SEVERITIES: frozenset[str] = frozenset(
    {"error", "warning", "info", "fatal"}
)

_SAFETY_STAMPS: dict[str, Any] = {
    "advisory_status": ADVISORY_STATUS,
    "execution_gate": EXECUTION_GATE_LOCKED,
    "broker_api_called": False,
    "ai_execution_count": 0,
    "execution_permission": False,
    "can_execute": False,
}

# Conservative secret-shaped patterns. We only redact in the details dict;
# error_id, message, and operator_action are written by the caller so the
# caller is responsible for not putting secrets there.
_SECRET_KEY_HINTS = re.compile(
    r"(?:^|[_\W])(token|api[_-]?key|secret|password|passphrase|bearer|auth)"
    r"(?:$|[_\W])",
    re.IGNORECASE,
)


def _is_secret_key(key: str) -> bool:
    """Return True if ``key`` looks like it would hold a secret.

    Uses a regex that requires the secret-shaped term to be at a word
    boundary so ``non_secret`` / ``not_a_secret`` are *not* matched.
    Also accepts an exact match for the bare term.
    """
    if not key:
        return False
    norm = key.lower()
    bare_terms = {
        "token", "secret", "password", "passphrase", "bearer", "auth",
        "api_key", "apikey", "api-key",
    }
    if norm in bare_terms:
        return True
    # Pad with underscores so the regex word-boundary clause fires reliably
    # for keys like "mvp_api_token" or "auth_header".
    return bool(_SECRET_KEY_HINTS.search(f"_{norm}_"))


def _now_iso() -> str:
    return (
        _dt.datetime.now(_dt.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _sanitize_details(details: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a copy of ``details`` with values redacted under secret-shaped keys.

    - Top-level only (defensive: if details is deeply nested, callers should
      flatten before passing).
    - Booleans / numbers are preserved unchanged.
    - String values under secret-shaped keys are replaced with ``"<redacted>"``.
    """
    if not isinstance(details, Mapping):
        return {}
    sanitized: dict[str, Any] = {}
    for raw_key, value in details.items():
        key = str(raw_key)
        if _is_secret_key(key):
            sanitized[key] = "<redacted>"
            continue
        # Allow primitives and short strings through; long opaque tokens
        # already redacted above by key-name.
        if value is None or isinstance(value, (bool, int, float)):
            sanitized[key] = value
        elif isinstance(value, str):
            sanitized[key] = value
        elif isinstance(value, (list, tuple)):
            sanitized[key] = list(value)
        elif isinstance(value, Mapping):
            sanitized[key] = dict(value)
        else:
            sanitized[key] = repr(value)
    return sanitized


def build_error_response(
    *,
    error_id: str,
    message: str,
    operator_action: str,
    severity: str = "error",
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Standard error envelope.

    Parameters
    ----------
    error_id : str
        Stable identifier (e.g. ``"db_open_failed"``). Used by tests and
        dashboards to match on a class of error rather than its message.
    message : str
        Short human-readable description. Do NOT include secrets here.
    operator_action : str
        One-line description of what the operator should do now. Required.
    severity : str
        One of ``error`` / ``warning`` / ``info`` / ``fatal``. Defaults to
        ``error``.
    details : Mapping | None
        Additional context. Values under secret-shaped keys are redacted.

    The response always includes the canonical safety stamps and never
    grants execution permission, regardless of input.
    """
    if not isinstance(error_id, str) or not error_id.strip():
        error_id = "unspecified_error"
    if not isinstance(message, str):
        message = str(message)
    if not isinstance(operator_action, str) or not operator_action.strip():
        operator_action = (
            "Inspect logs and re-run the failing check. If the error "
            "persists, escalate to manual review."
        )
    sev = severity if severity in VALID_SEVERITIES else "error"

    out: dict[str, Any] = {
        "ok": False,
        "envelope": "error_response",
        "error_id": error_id.strip(),
        "message": message,
        "operator_action": operator_action.strip(),
        "severity": sev,
        "details": _sanitize_details(details),
        "generated_at": _now_iso(),
    }
    out.update(_SAFETY_STAMPS)
    return out


def build_warning_response(
    *,
    warning_id: str,
    message: str,
    operator_action: str,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """A warning envelope. Same shape as ``build_error_response`` but ``ok=True``.

    Use this for non-fatal conditions where the operator should be informed
    but the check is still passing.
    """
    if not isinstance(warning_id, str) or not warning_id.strip():
        warning_id = "unspecified_warning"
    if not isinstance(message, str):
        message = str(message)
    if not isinstance(operator_action, str) or not operator_action.strip():
        operator_action = "Review the warning and decide whether to act."

    out: dict[str, Any] = {
        "ok": True,
        "envelope": "warning_response",
        "warning_id": warning_id.strip(),
        "message": message,
        "operator_action": operator_action.strip(),
        "severity": "warning",
        "details": _sanitize_details(details),
        "generated_at": _now_iso(),
    }
    out.update(_SAFETY_STAMPS)
    return out


def build_check_result(
    *,
    name: str,
    status: str,
    detail: str = "",
) -> dict[str, Any]:
    """One row in a ``check_results`` list.

    ``status`` must be one of PASS / FAIL / WARN / INFO.  Anything else
    is coerced to ``INFO`` so the caller cannot accidentally invent a
    new severity level.
    """
    valid = {"PASS", "FAIL", "WARN", "INFO"}
    s = status if status in valid else "INFO"
    return {
        "name": str(name or "unspecified"),
        "status": s,
        "detail": str(detail or ""),
    }


__all__ = [
    "ADVISORY_STATUS",
    "EXECUTION_GATE_LOCKED",
    "VALID_SEVERITIES",
    "build_error_response",
    "build_warning_response",
    "build_check_result",
]
