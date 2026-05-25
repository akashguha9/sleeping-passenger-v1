"""Central operator-permission guard for every mutation-capable script.

Kanté Defensive Sprint — Task 2.  Before this module each ``--apply`` / write
script hand-rolled its own role check, dry-run convention, and audit stamp.
This is the *one* boundary they share:

* role authorization is delegated to :mod:`scripts.operator_auth` (the existing
  VIEWER < OPERATOR < ADMIN floor) — this module does **not** reinvent it;
* it adds the operation-class taxonomy, the dry-run-receipt requirement, the
  runtime-DB-path safety check, and the advisory safety-invariant gate;
* every decision — allowed *and* denied — is written to an audit-only JSONL
  log; no secrets and no raw sensitive paths are recorded (the DB path is
  hashed).

Hard ceiling — advisory-only
----------------------------
No role, not even ADMIN, can authorize a broker / order / execution operation.
``FORBIDDEN_EXECUTION`` is rejected for every role, and every decision carries
the locked execution invariants.  This module performs **no** DB writes, **no**
broker calls, and **no** AI execution.  Its only side effects are appending one
JSONL audit line and (for dry-runs) writing a small receipt file — both
audit-only, never canonical truth.
"""
from __future__ import annotations

import argparse
import contextlib
import functools
import hashlib
import json
import os
import re
import sys
import tempfile
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
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
_RUNTIME_DIR = _REPO_ROOT / "runtime"
DEFAULT_AUDIT_PATH = _RUNTIME_DIR / "operator_audit_log.jsonl"
RECEIPT_DIR = _RUNTIME_DIR / "operator_dry_run_receipts"
DEFAULT_RECEIPT_MAX_AGE_MINUTES = 30

# Role env var (same one operator_audit_log uses) — default fails safe to VIEWER.
ROLE_ENV_VAR = "MVP_OPERATOR_ROLE"
# Test/deployment override for the audit log location.
AUDIT_PATH_ENV_VAR = "MVP_OPERATOR_GUARD_AUDIT_PATH"
# Test/deployment override for the dry-run receipt directory.
RECEIPT_DIR_ENV_VAR = "MVP_OPERATOR_RECEIPT_DIR"

# A reason marker a caller may set to declare a mutation legitimately needs no
# dry-run (e.g. an idempotent narrow-signature delete).  Must be accompanied by
# a human-readable justification (the rest of ``reason``).
NO_DRY_RUN_NEEDED = "no_dry_run_needed"


class OperationClass(Enum):
    READ_ONLY = "READ_ONLY"
    AUDIT_ONLY_WRITE = "AUDIT_ONLY_WRITE"
    REPAIR_WRITE = "REPAIR_WRITE"
    RESTORE_WRITE = "RESTORE_WRITE"
    MIGRATION_WRITE = "MIGRATION_WRITE"
    FORBIDDEN_EXECUTION = "FORBIDDEN_EXECUTION"


class OperatorRole(Enum):
    VIEWER = "VIEWER"
    OPERATOR = "OPERATOR"
    ADMIN = "ADMIN"


# Which operation classes each role may perform.  Least-privilege; the default
# (VIEWER) can only read.  No class grants FORBIDDEN_EXECUTION to anyone.
ALLOWED_OPERATIONS: dict[OperatorRole, frozenset[OperationClass]] = {
    OperatorRole.VIEWER: frozenset({OperationClass.READ_ONLY}),
    OperatorRole.OPERATOR: frozenset({
        OperationClass.READ_ONLY,
        OperationClass.AUDIT_ONLY_WRITE,
        OperationClass.REPAIR_WRITE,
    }),
    OperatorRole.ADMIN: frozenset({
        OperationClass.READ_ONLY,
        OperationClass.AUDIT_ONLY_WRITE,
        OperationClass.REPAIR_WRITE,
        OperationClass.RESTORE_WRITE,
        OperationClass.MIGRATION_WRITE,
    }),
}

# Mutation classes — those that change DB state and therefore require an
# explicit --apply and (with the AUDIT_ONLY_WRITE exception) a dry-run receipt.
_MUTATION_CLASSES: frozenset[OperationClass] = frozenset({
    OperationClass.AUDIT_ONLY_WRITE,
    OperationClass.REPAIR_WRITE,
    OperationClass.RESTORE_WRITE,
    OperationClass.MIGRATION_WRITE,
})

# Secret-like tokens scrubbed from any free text before it reaches the audit
# log.  Mirrors operator_audit_log so the guard can never become a leak surface.
_SECRET_RE: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(api[_-]?key|secret|token|bearer|password)\s*[=:]\s*\S{6,}"),
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"xai-[A-Za-z0-9]{16,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


@dataclass
class PermissionRequest:
    operation_name: str
    operation_class: OperationClass
    operator_role: OperatorRole
    apply_requested: bool
    dry_run_completed: bool
    db_path: str | None
    safety_stamps: dict
    reason: str | None = None


@dataclass
class PermissionDecision:
    allowed: bool
    denial_reasons: list[str]
    operation_name: str
    operation_class: str
    operator_role: str
    audit_event_id: str
    advisory_only: bool = True
    human_execution_required: bool = True
    execution_gate: str = _contract.EXECUTION_GATE_LOCKED
    broker_api_called: bool = False
    ai_execution_count: int = _contract.AI_EXECUTION_COUNT
    db_path_hash: str | None = None
    apply_requested: bool = False
    dry_run_completed: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _redact(text: Any) -> str:
    s = str(text or "")
    for pattern in _SECRET_RE:
        s = pattern.sub("[REDACTED]", s)
    return s


def db_path_hash(db_path: str | None) -> str:
    """Stable, non-reversible hash of the resolved DB path (audit-safe)."""
    if not db_path:
        return ""
    try:
        resolved = str(Path(db_path).resolve())
    except (OSError, ValueError):
        resolved = str(db_path)
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:16]


def load_operator_role_from_env(default: str = "VIEWER") -> OperatorRole:
    """Resolve the operator role from ``MVP_OPERATOR_ROLE`` (fails safe to VIEWER).

    Unknown / missing values normalize to VIEWER via :mod:`operator_auth`.
    """
    raw = os.environ.get(ROLE_ENV_VAR)
    if raw is None or not str(raw).strip():
        raw = default
    normalized = _auth.normalize_role(raw)  # VIEWER for anything unknown
    return OperatorRole(normalized)


# POSIX system directories never hold a runtime DB — denied on every platform.
_POSIX_SYSTEM_PREFIXES: tuple[str, ...] = (
    "/etc/", "/root/", "/var/", "/usr/", "/bin/",
    "/sbin/", "/proc/", "/sys/", "/dev/",
)
# URL-like targets are never a local file DB.
_URL_PREFIXES: tuple[str, ...] = ("http://", "https://", "file://")
# A Windows drive-letter absolute path, e.g. ``C:\`` or ``C:/``.
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")


def classify_db_path(db_path: str | None) -> str | None:
    """Return a denial-reason code for an unsafe ``db_path``, or ``None`` if allowed.

    Cross-platform by string pattern, NOT by :class:`pathlib.Path` semantics:
    on Linux CI a Windows path such as ``C:\\Windows\\System32\\evil.db`` is
    otherwise mis-parsed as a *relative* filename and resolved under the repo
    (cwd), which would wrongly allow it.  We therefore detect Windows-drive,
    UNC, system-directory, traversal and URL patterns explicitly before any
    ``resolve()`` is attempted.

    Reason codes: ``missing_db_path``, ``windows_system_path``,
    ``path_traversal``, ``external_db_path``, ``unsafe_db_path``.
    """
    if db_path is None:
        return "missing_db_path"
    raw = str(db_path)
    if not raw.strip():
        return "missing_db_path"

    lowered = raw.strip().lower()

    # URL-like targets are never a local runtime DB.
    if lowered.startswith(_URL_PREFIXES):
        return "external_db_path"

    # Windows system path, detected on any platform (both slash styles).
    norm_slashes = raw.replace("\\", "/").lower()
    if "/windows/system32" in norm_slashes:
        return "windows_system_path"

    # UNC network path (\\host\share or //host/share).
    if raw.startswith("\\\\") or raw.startswith("//"):
        return "external_db_path"

    # Parent-directory traversal in any path segment (checked on the RAW string
    # so ``../../evil.db`` is rejected before resolution can hide it).
    if ".." in re.split(r"[\\/]+", raw):
        return "path_traversal"

    # POSIX system directories — rejected on every platform.
    if any(raw.startswith(prefix) for prefix in _POSIX_SYSTEM_PREFIXES):
        return "external_db_path"

    # On a non-Windows platform a drive-letter path or any backslash signals a
    # foreign Windows path that pathlib would mis-resolve as relative.
    if os.name != "nt":
        if _WINDOWS_DRIVE_RE.match(raw):
            return "windows_system_path"
        if "\\" in raw:
            return "external_db_path"

    # Finally, the path must resolve inside the repo root or the system temp dir.
    try:
        target = Path(raw).resolve()
    except (OSError, ValueError):
        return "unsafe_db_path"
    allowed_roots = [_REPO_ROOT.resolve()]
    try:
        allowed_roots.append(Path(tempfile.gettempdir()).resolve())
    except (OSError, ValueError):  # pragma: no cover - defensive
        pass
    for root in allowed_roots:
        try:
            target.relative_to(root)
            return None
        except ValueError:
            continue
    return "external_db_path"


def safe_db_path_allowed(db_path: str | None) -> bool:
    """True iff ``db_path`` is a concrete file path inside an allowed location.

    Allowed: anywhere under the repo root, or under the system temp dir (which
    covers pytest ``tmp_path`` fixtures).  Denied: ``None``/empty/whitespace,
    Windows system paths (even on Linux CI), UNC/URL paths, POSIX system
    directories, ``..`` traversal, and any external arbitrary path.  Delegates
    to :func:`classify_db_path` so both share one cross-platform deny list.
    """
    return classify_db_path(db_path) is None


def forbid_execution_operation(
    operation_name: str, operation_class: OperationClass
) -> bool:
    """True if this operation is a forbidden broker/order/execution action.

    Forbidden by class (``FORBIDDEN_EXECUTION``) or by name (any token from the
    shared forbidden-action / forbidden-execution registries).
    """
    if operation_class == OperationClass.FORBIDDEN_EXECUTION:
        return True
    name = str(operation_name or "").strip().lower()
    if name in _auth.FORBIDDEN_ACTIONS:
        return True
    forbidden_tokens = set(_contract.FORBIDDEN_EXECUTION_TOKENS) | {
        "broker", "place_order", "submit_order", "execute_trade",
        "unlock_execution_gate", "enable_auto_trading", "order_placement",
        "trade_execution", "ai_execution",
    }
    return any(tok.replace(" ", "_") in name or tok in name
               for tok in forbidden_tokens)


def _safety_invariant_clean(stamps: dict | None) -> tuple[bool, list[str]]:
    """Validate the advisory safety invariants in ``stamps``.

    Clean iff advisory_only/ADVISORY_ONLY, human review required, execution
    gate LOCKED, broker_api_called False, ai_execution_count 0.
    """
    problems: list[str] = []
    s = stamps if isinstance(stamps, dict) else {}

    advisory = str(s.get("advisory_status", "")).strip().upper()
    if advisory != _contract.ADVISORY_STATUS and s.get("advisory_only") is not True:
        problems.append("advisory_only invariant not asserted")
    if s.get("human_review_required") is False or s.get(
        "human_execution_required"
    ) is False:
        problems.append("human_execution_required invariant violated")
    gate = str(s.get("execution_gate", _contract.EXECUTION_GATE_LOCKED)).upper()
    if gate != _contract.EXECUTION_GATE_LOCKED:
        problems.append(f"execution_gate not LOCKED ({gate})")
    if s.get("broker_api_called") not in (False, None, 0):
        problems.append("broker_api_called is truthy")
    aic = s.get("ai_execution_count", 0)
    if aic not in (0, None):
        problems.append(f"ai_execution_count != 0 ({aic})")
    return (not problems), problems


# ---------------------------------------------------------------------------
# Core decision
# ---------------------------------------------------------------------------


def evaluate_permission(request: PermissionRequest) -> PermissionDecision:
    """Evaluate a permission request into an allow/deny decision with reasons.

    Pure (no side effects): builds the decision; the caller persists the audit
    event with :func:`write_operator_audit_event`.
    """
    denial: list[str] = []
    op_class = request.operation_class
    role = request.operator_role
    is_mutation = op_class in _MUTATION_CLASSES

    # NotBrokerOperation — hard, unconditional.
    if forbid_execution_operation(request.operation_name, op_class):
        denial.append(
            "forbidden_execution: no role can authorize a broker / order / "
            "execution operation — this MVP is advisory-only."
        )

    # RoleAllowed / OperationClassAllowed.
    allowed_classes = ALLOWED_OPERATIONS.get(role, frozenset())
    if op_class not in allowed_classes:
        denial.append(
            f"role_not_allowed: {role.value} may not perform {op_class.value} "
            f"(allowed: {sorted(c.value for c in allowed_classes)})."
        )

    # ExplicitApply — every mutation needs an explicit --apply.
    if is_mutation and not request.apply_requested:
        denial.append(
            "explicit_apply_required: mutation operations require an explicit "
            "--apply (dry-run is the default)."
        )

    # DryRunCompleted — receipt, or AUDIT_ONLY_WRITE, or explicit no_dry_run_needed.
    if is_mutation and op_class != OperationClass.AUDIT_ONLY_WRITE:
        marked_no_dry_run = (
            request.reason is not None
            and NO_DRY_RUN_NEEDED in str(request.reason).lower()
            and len(str(request.reason).strip()) > len(NO_DRY_RUN_NEEDED) + 1
        )
        if not request.dry_run_completed and not marked_no_dry_run:
            denial.append(
                "dry_run_required: a valid recent dry-run receipt (or an "
                "explicit no_dry_run_needed reason) is required before --apply."
            )

    # DBPathAllowed — mutations must target an allowed runtime/repo/temp path.
    if is_mutation:
        path_reason = classify_db_path(request.db_path)
        if path_reason is not None:
            denial.append(
                f"db_path_not_allowed ({path_reason}): target DB path is "
                "missing, foreign, or outside the allowed runtime/repo/temp "
                "location."
            )

    # SafetyInvariantClean.
    clean, problems = _safety_invariant_clean(request.safety_stamps)
    if not clean:
        denial.append("safety_invariant_dirty: " + "; ".join(problems))

    decision = PermissionDecision(
        allowed=not denial,
        denial_reasons=denial,
        operation_name=str(request.operation_name),
        operation_class=op_class.value,
        operator_role=role.value,
        audit_event_id="evt_" + uuid.uuid4().hex[:16],
        db_path_hash=db_path_hash(request.db_path),
        apply_requested=bool(request.apply_requested),
        dry_run_completed=bool(request.dry_run_completed),
    )
    return decision


# ---------------------------------------------------------------------------
# Audit log (audit-only JSONL; never canonical)
# ---------------------------------------------------------------------------


def _audit_path(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return Path(explicit)
    env = os.environ.get(AUDIT_PATH_ENV_VAR)
    if env:
        return Path(env)
    return DEFAULT_AUDIT_PATH


def write_operator_audit_event(
    decision: PermissionDecision,
    path: str | Path | None = None,
) -> None:
    """Append one audit-only JSONL event for ``decision`` (best-effort).

    Records allow *and* deny.  No secrets; the DB path is hashed, never raw.
    A write failure never raises (it must not block the security decision).
    ``path=None`` resolves to ``MVP_OPERATOR_GUARD_AUDIT_PATH`` env override,
    else ``runtime/operator_audit_log.jsonl``.
    """
    target = _audit_path(Path(path) if path is not None else None)
    event = {
        "timestamp_utc": _utc_now_iso(),
        "audit_event_id": decision.audit_event_id,
        "operation_name": _redact(decision.operation_name),
        "operation_class": decision.operation_class,
        "operator_role": decision.operator_role,
        "allowed": bool(decision.allowed),
        "denial_reasons": [_redact(r) for r in decision.denial_reasons],
        "apply_requested": bool(decision.apply_requested),
        "dry_run_completed": bool(decision.dry_run_completed),
        "db_path_hash": decision.db_path_hash,
        "advisory_only": decision.advisory_only,
        "human_execution_required": decision.human_execution_required,
        "execution_gate": decision.execution_gate,
        "broker_api_called": decision.broker_api_called,
        "ai_execution_count": decision.ai_execution_count,
        "audit_only": True,
        "canonical_store": _contract.CANONICAL_STORE,
    }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(event, separators=(",", ":"), sort_keys=True) + "\n")
    except OSError:  # pragma: no cover - defensive
        return


def read_recent_audit_events(
    path: str | Path | None = None, *, limit: int = 20
) -> list[dict[str, Any]]:
    """Read the last ``limit`` audit events (tolerant of malformed lines)."""
    target = _audit_path(Path(path) if path is not None else None)
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


# ---------------------------------------------------------------------------
# Enforcement entrypoint
# ---------------------------------------------------------------------------


def assert_permission_decision_allowed(
    decision: PermissionDecision | None,
    expected_operation_class: OperationClass | None = None,
) -> None:
    """Fail closed at the *write boundary* — raise unless ``decision`` is a clean allow.

    This is the function-level guard the actual mutation functions call so a
    future caller cannot bypass the CLI ``main`` by importing the write function
    directly.  It re-validates the decision object itself (it does not re-run
    role logic) and raises :class:`PermissionError` when ANY of the following
    hold:

    * ``decision`` is missing (``None``);
    * ``decision.allowed`` is false;
    * ``expected_operation_class`` is given and does not match the decision;
    * the operation class is ``FORBIDDEN_EXECUTION``;
    * the locked advisory invariants are violated — ``execution_gate`` is not
      ``LOCKED``, ``advisory_only`` is not true, ``human_execution_required`` is
      not true, ``broker_api_called`` is truthy, or ``ai_execution_count`` != 0.

    Returns ``None`` on success.
    """
    if decision is None:
        raise PermissionError(
            "permission_decision_required: write boundary reached without a "
            "PermissionDecision — the operator_permission_guard was bypassed."
        )
    if not isinstance(decision, PermissionDecision):
        raise PermissionError(
            "permission_decision_invalid: expected a PermissionDecision, got "
            f"{type(decision).__name__}."
        )
    problems: list[str] = []
    if not decision.allowed:
        problems.append(
            "decision_not_allowed: "
            + ("; ".join(decision.denial_reasons) or "denied")
        )
    if expected_operation_class is not None:
        expected = expected_operation_class.value
        if str(decision.operation_class) != expected:
            problems.append(
                f"operation_class_mismatch: decision is "
                f"{decision.operation_class!r}, expected {expected!r}."
            )
    if str(decision.operation_class) == OperationClass.FORBIDDEN_EXECUTION.value:
        problems.append("forbidden_execution: broker/order/execution is never allowed.")
    if str(decision.execution_gate).upper() != _contract.EXECUTION_GATE_LOCKED:
        problems.append(f"execution_gate_not_locked: {decision.execution_gate!r}.")
    if decision.advisory_only is not True:
        problems.append("advisory_only_not_asserted.")
    if decision.human_execution_required is not True:
        problems.append("human_execution_required_not_asserted.")
    if decision.broker_api_called not in (False, None, 0):
        problems.append("broker_api_called_truthy.")
    if decision.ai_execution_count not in (0, None):
        problems.append(f"ai_execution_count_nonzero: {decision.ai_execution_count}.")
    if problems:
        raise PermissionError(
            "operator_permission_guard ASSERT DENY: " + " | ".join(problems)
        )


def require_permission_or_exit(
    request: PermissionRequest,
    *,
    audit_path: str | Path | None = None,
) -> PermissionDecision:
    """Evaluate, audit, and fail closed.

    Always writes an audit event (allow or deny).  Raises
    :class:`PermissionError` when the request is denied so the caller never
    reaches the mutation.  Returns the decision on allow.
    """
    decision = evaluate_permission(request)
    write_operator_audit_event(decision, path=audit_path)
    if not decision.allowed:
        raise PermissionError(
            f"operator_permission_guard DENY: role={decision.operator_role} "
            f"op={decision.operation_name} class={decision.operation_class} :: "
            + " | ".join(decision.denial_reasons)
        )
    return decision


# ---------------------------------------------------------------------------
# Guarded-mutation decorator / context manager (Kanté Defensive Sprint — Task B)
#
# Before this, every mutation function hand-wrote the same write-boundary
# preamble (``assert_permission_decision_allowed(decision, expected_class=...)``)
# and every CLI hand-built the same PermissionRequest → require_permission_or_exit
# dance.  This collapses both into one declarative surface so the guard can never
# drift between scripts.  Neither helper mutates anything: they only enforce.
# ---------------------------------------------------------------------------

# Least-privilege ordering for the optional write-boundary role floor.
_ROLE_RANK: dict[OperatorRole, int] = {
    OperatorRole.VIEWER: 0,
    OperatorRole.OPERATOR: 1,
    OperatorRole.ADMIN: 2,
}


def _role_meets_floor(role_value: Any, floor: OperatorRole) -> bool:
    """True iff ``role_value`` (a role enum or its string) is >= ``floor``."""
    if isinstance(role_value, OperatorRole):
        role = role_value
    else:
        try:
            role = OperatorRole(_auth.normalize_role(str(role_value)))
        except (ValueError, KeyError):
            return False
    return _ROLE_RANK.get(role, -1) >= _ROLE_RANK.get(floor, 99)


def assert_guarded_mutation(
    decision: PermissionDecision | None,
    *,
    operation_class: OperationClass,
    operation_name: str = "",
    expected_role_floor: OperatorRole | None = None,
    require_dry_run: bool = True,
) -> PermissionDecision:
    """Shared write-boundary enforcement for the decorator, context manager, and
    dual-mode (scan-then-write) functions whose control flow doesn't fit a single
    ``with`` block.

    Re-runs :func:`assert_permission_decision_allowed` (decision present, allowed,
    correct class, not FORBIDDEN_EXECUTION, clean locked invariants) and adds two
    defence-in-depth checks: a missing dry-run when ``require_dry_run`` is set,
    and a sub-floor role when ``expected_role_floor`` is given.  Raises
    :class:`PermissionError` before the wrapped write can run.  Performs no IO.
    """
    assert_permission_decision_allowed(
        decision, expected_operation_class=operation_class
    )
    # decision is a valid, allowed PermissionDecision past the assert above.
    problems: list[str] = []
    if require_dry_run and not getattr(decision, "dry_run_completed", False):
        problems.append("dry_run_required_at_write_boundary")
    if expected_role_floor is not None and not _role_meets_floor(
        getattr(decision, "operator_role", None), expected_role_floor
    ):
        problems.append(
            f"role_below_floor: {getattr(decision, 'operator_role', None)} "
            f"< {expected_role_floor.value}"
        )
    if problems:
        label = operation_name or operation_class.value
        raise PermissionError(
            f"guarded_mutation[{label}] DENY: " + " | ".join(problems)
        )
    return decision  # type: ignore[return-value]


def guarded_mutation(
    *,
    operation_class: OperationClass,
    operation_name: str = "",
    expected_role_floor: OperatorRole | None = None,
    require_dry_run: bool = True,
    decision_arg: str = "permission_decision",
):
    """Decorator that enforces the permission guard at a write function's boundary.

    The wrapped function MUST receive a guard-validated :class:`PermissionDecision`
    via the ``permission_decision`` keyword (or ``decision_arg``).  Before the
    body runs the decorator calls :func:`assert_guarded_mutation`, so a caller that
    imports the write function directly — bypassing the CLI ``main`` — still
    cannot reach the mutation without a clean, allowed, correctly-classed
    decision.  ``FORBIDDEN_EXECUTION`` can never be wrapped (advisory-only ceiling).

    The decorator itself performs no IO and no mutation; it only raises
    :class:`PermissionError` or delegates to the wrapped function.  CLI-layer
    ``--apply`` + dry-run-receipt enforcement is unchanged and still required.
    """
    if operation_class == OperationClass.FORBIDDEN_EXECUTION:
        raise ValueError(
            "guarded_mutation cannot wrap a FORBIDDEN_EXECUTION operation — "
            "this MVP is advisory-only and no decorator may authorize execution."
        )

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            decision = kwargs.get(decision_arg)
            assert_guarded_mutation(
                decision,
                operation_class=operation_class,
                operation_name=operation_name or getattr(func, "__name__", ""),
                expected_role_floor=expected_role_floor,
                require_dry_run=require_dry_run,
            )
            return func(*args, **kwargs)

        wrapper.__guarded_mutation__ = {
            "operation_name": operation_name or getattr(func, "__name__", ""),
            "operation_class": operation_class.value,
            "expected_role_floor": (
                expected_role_floor.value if expected_role_floor else None
            ),
            "require_dry_run": bool(require_dry_run),
            "decision_arg": decision_arg,
        }
        return wrapper

    return decorator


@contextlib.contextmanager
def guarded_mutation_context(
    decision: PermissionDecision | None,
    *,
    operation_class: OperationClass,
    operation_name: str = "",
    expected_role_floor: OperatorRole | None = None,
    require_dry_run: bool = True,
) -> Iterator[PermissionDecision]:
    """Context-manager form of :func:`guarded_mutation` for dual-mode functions.

    A function that both *scans* (read-only) and optionally *writes* cannot be a
    pure decorated write target, so it wraps only its write block::

        with guarded_mutation_context(decision, operation_class=REPAIR_WRITE):
            conn.execute("UPDATE ...")

    Enforcement happens on ``__enter__`` (before the block); the body never runs
    when the decision is missing/denied/mis-classed.  No IO of its own.
    """
    validated = assert_guarded_mutation(
        decision,
        operation_class=operation_class,
        operation_name=operation_name,
        expected_role_floor=expected_role_floor,
        require_dry_run=require_dry_run,
    )
    yield validated


def build_apply_decision(
    operation_name: str,
    operation_class: OperationClass,
    db_path: str | None,
    *,
    operator_role: str | None = None,
    reason: str | None = None,
    audit_path: str | Path | None = None,
) -> PermissionDecision:
    """Collapse the per-CLI ``--apply`` authorization boilerplate into one call.

    Resolves the role (explicit ``--operator-role`` arg, else ``MVP_OPERATOR_ROLE``
    env, else VIEWER), checks for a recent dry-run receipt, builds the
    :class:`PermissionRequest` with the canonical advisory safety stamps, and
    runs :func:`require_permission_or_exit` (which audits allow *and* deny and
    raises :class:`PermissionError` on deny).  The caller wraps this in
    ``try/except PermissionError`` and returns its CLI deny code (2).
    """
    role = (
        OperatorRole(_auth.normalize_role(operator_role))
        if operator_role
        else load_operator_role_from_env()
    )
    request = PermissionRequest(
        operation_name=operation_name,
        operation_class=operation_class,
        operator_role=role,
        apply_requested=True,
        dry_run_completed=validate_dry_run_receipt(operation_name, db_path),
        db_path=db_path,
        safety_stamps=caller_safety_stamps(),
        reason=reason,
    )
    return require_permission_or_exit(request, audit_path=audit_path)


# ---------------------------------------------------------------------------
# Dry-run receipts (audit-only)
# ---------------------------------------------------------------------------


def receipt_dir() -> Path:
    """Resolve the receipt directory (env override → repo default)."""
    env = os.environ.get(RECEIPT_DIR_ENV_VAR)
    return Path(env) if env else RECEIPT_DIR


def _receipt_path(operation_name: str, db_path: str | None) -> Path:
    safe_op = re.sub(r"[^A-Za-z0-9_.-]", "_", str(operation_name or "op"))
    return receipt_dir() / f"{safe_op}__{db_path_hash(db_path)}.json"


def write_dry_run_receipt(
    operation_name: str,
    target_count: int,
    db_path: str | None,
) -> Path:
    """Write a dry-run receipt (audit-only, never canonical) and return its path."""
    receipt_dir().mkdir(parents=True, exist_ok=True)
    receipt = {
        "operation_name": str(operation_name),
        "target_count": int(target_count),
        "db_path_hash": db_path_hash(db_path),
        "timestamp_utc": _utc_now_iso(),
        "advisory_only": True,
        "human_execution_required": True,
        "execution_gate": _contract.EXECUTION_GATE_LOCKED,
        "broker_api_called": False,
        "ai_execution_count": _contract.AI_EXECUTION_COUNT,
        "audit_only": True,
    }
    path = _receipt_path(operation_name, db_path)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    return path


def validate_dry_run_receipt(
    operation_name: str,
    db_path: str | None,
    *,
    max_age_minutes: int = DEFAULT_RECEIPT_MAX_AGE_MINUTES,
) -> bool:
    """True iff a matching, recent dry-run receipt exists.

    Valid iff operation_name + db_path_hash match, target_count >= 0, and the
    receipt is no older than ``max_age_minutes``.
    """
    path = _receipt_path(operation_name, db_path)
    if not path.exists():
        return False
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if str(receipt.get("operation_name")) != str(operation_name):
        return False
    if str(receipt.get("db_path_hash")) != db_path_hash(db_path):
        return False
    try:
        if int(receipt.get("target_count", -1)) < 0:
            return False
    except (TypeError, ValueError):
        return False
    ts = receipt.get("timestamp_utc")
    try:
        when = datetime.fromisoformat(str(ts))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return False
    age_seconds = (datetime.now(timezone.utc) - when).total_seconds()
    return 0 <= age_seconds <= max_age_minutes * 60


# ---------------------------------------------------------------------------
# Convenience: build the canonical advisory safety stamps a caller should pass.
# ---------------------------------------------------------------------------


def caller_safety_stamps() -> dict[str, Any]:
    """The advisory safety stamps a guarded caller should pass through.

    A thin pass-through of :func:`advisory_contract.advisory_safety_stamps` so
    callers do not hand-roll the dict (which is what the guard validates).
    """
    return _contract.advisory_safety_stamps()


# ---------------------------------------------------------------------------
# Self-test CLI
# ---------------------------------------------------------------------------


def _self_test() -> int:
    """Exercise the guard's core invariants in-memory; print PASS/FAIL."""
    import tempfile as _tf

    failures: list[str] = []

    def check(name: str, cond: bool) -> None:
        if not cond:
            failures.append(name)

    clean = _contract.advisory_safety_stamps()
    with _tf.TemporaryDirectory() as td:
        db = str(Path(td) / "mvp_local.db")

        # 1. VIEWER cannot REPAIR_WRITE --apply.
        d = evaluate_permission(PermissionRequest(
            "quarantine", OperationClass.REPAIR_WRITE, OperatorRole.VIEWER,
            apply_requested=True, dry_run_completed=True, db_path=db,
            safety_stamps=clean))
        check("viewer_denied_repair_apply", not d.allowed)

        # 2. OPERATOR REPAIR_WRITE without dry-run denied; with dry-run allowed.
        d = evaluate_permission(PermissionRequest(
            "quarantine", OperationClass.REPAIR_WRITE, OperatorRole.OPERATOR,
            apply_requested=True, dry_run_completed=False, db_path=db,
            safety_stamps=clean))
        check("operator_repair_needs_dryrun", not d.allowed)
        d = evaluate_permission(PermissionRequest(
            "quarantine", OperationClass.REPAIR_WRITE, OperatorRole.OPERATOR,
            apply_requested=True, dry_run_completed=True, db_path=db,
            safety_stamps=clean))
        check("operator_repair_with_dryrun_ok", d.allowed)

        # 3. OPERATOR cannot RESTORE_WRITE; ADMIN can (with dry-run).
        d = evaluate_permission(PermissionRequest(
            "restore", OperationClass.RESTORE_WRITE, OperatorRole.OPERATOR,
            apply_requested=True, dry_run_completed=True, db_path=db,
            safety_stamps=clean))
        check("operator_denied_restore", not d.allowed)
        d = evaluate_permission(PermissionRequest(
            "restore", OperationClass.RESTORE_WRITE, OperatorRole.ADMIN,
            apply_requested=True, dry_run_completed=True, db_path=db,
            safety_stamps=clean))
        check("admin_restore_with_dryrun_ok", d.allowed)

        # 4. Every role denied FORBIDDEN_EXECUTION.
        for role in OperatorRole:
            d = evaluate_permission(PermissionRequest(
                "place_order", OperationClass.FORBIDDEN_EXECUTION, role,
                apply_requested=True, dry_run_completed=True, db_path=db,
                safety_stamps=clean))
            check(f"{role.value}_denied_execution", not d.allowed)

        # 5. Dirty safety stamps deny.
        dirty = dict(clean)
        dirty["execution_gate"] = "UNLOCKED"
        d = evaluate_permission(PermissionRequest(
            "quarantine", OperationClass.REPAIR_WRITE, OperatorRole.ADMIN,
            apply_requested=True, dry_run_completed=True, db_path=db,
            safety_stamps=dirty))
        check("dirty_stamps_denied", not d.allowed)

        # 6. Unsafe DB path denies.
        d = evaluate_permission(PermissionRequest(
            "quarantine", OperationClass.REPAIR_WRITE, OperatorRole.OPERATOR,
            apply_requested=True, dry_run_completed=True,
            db_path="/etc/shadow", safety_stamps=clean))
        check("unsafe_db_path_denied", not d.allowed)

        # 6b. assert_permission_decision_allowed: write-boundary guard.
        allow = evaluate_permission(PermissionRequest(
            "quarantine", OperationClass.REPAIR_WRITE, OperatorRole.OPERATOR,
            apply_requested=True, dry_run_completed=True, db_path=db,
            safety_stamps=clean))
        try:
            assert_permission_decision_allowed(
                allow, expected_operation_class=OperationClass.REPAIR_WRITE)
            check("assert_allows_clean_decision", True)
        except PermissionError:
            check("assert_allows_clean_decision", False)
        # None decision must raise.
        try:
            assert_permission_decision_allowed(None)
            check("assert_rejects_missing_decision", False)
        except PermissionError:
            check("assert_rejects_missing_decision", True)
        # Operation-class mismatch must raise.
        try:
            assert_permission_decision_allowed(
                allow, expected_operation_class=OperationClass.RESTORE_WRITE)
            check("assert_rejects_class_mismatch", False)
        except PermissionError:
            check("assert_rejects_class_mismatch", True)
        # Denied decision must raise.
        denied = evaluate_permission(PermissionRequest(
            "quarantine", OperationClass.REPAIR_WRITE, OperatorRole.VIEWER,
            apply_requested=True, dry_run_completed=True, db_path=db,
            safety_stamps=clean))
        try:
            assert_permission_decision_allowed(denied)
            check("assert_rejects_denied_decision", False)
        except PermissionError:
            check("assert_rejects_denied_decision", True)

        # 7. Receipt round-trip + staleness.
        write_dry_run_receipt("quarantine_selftest", 3, db)
        check("receipt_valid", validate_dry_run_receipt("quarantine_selftest", db))
        check("receipt_stale_denied",
              not validate_dry_run_receipt("quarantine_selftest", db,
                                           max_age_minutes=0))
        check("receipt_mismatch_denied",
              not validate_dry_run_receipt("other_op", db))

    if failures:
        print("operator_permission_guard self-test: FAIL")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("operator_permission_guard self-test: PASS (all invariants hold)")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="operator_permission_guard.py",
        description=(
            "Central operator-permission guard for mutation-capable scripts. "
            "Advisory-only; no role can unlock broker execution.\n\n"
            "PowerShell usage in a guarded script:\n"
            '  $env:MVP_OPERATOR_ROLE=\"OPERATOR\"\n'
            "  python scripts\\quarantine_fake_manual_trades.py --dry-run\n"
            "  python scripts\\quarantine_fake_manual_trades.py --apply"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--self-test", action="store_true",
                   help="Run the in-memory guard invariant self-test.")
    p.add_argument("--tail", type=int, default=0,
                   help="Print the last N audit events.")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.self_test:
        return _self_test()
    if args.tail:
        events = read_recent_audit_events(limit=args.tail)
        if args.json:
            print(json.dumps(events, indent=2, default=str))
        else:
            print(f"Operator permission guard audit ({len(events)} recent)")
            for e in events:
                verdict = "ALLOW" if e.get("allowed") else "DENY"
                print(f"  [{verdict}] {e.get('timestamp_utc')} "
                      f"{e.get('operator_role')} {e.get('operation_class')} "
                      f"{e.get('operation_name')}")
        return 0
    # Default: print the role/class matrix.
    matrix = {
        role.value: sorted(c.value for c in ALLOWED_OPERATIONS[role])
        for role in OperatorRole
    }
    payload = {
        "report": "operator_permission_guard",
        "roles": [r.value for r in OperatorRole],
        "operation_classes": [c.value for c in OperationClass],
        "allowed_operations_by_role": matrix,
        "default_role": load_operator_role_from_env().value,
        "receipt_max_age_minutes": DEFAULT_RECEIPT_MAX_AGE_MINUTES,
        **_contract.advisory_safety_stamps(),
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("Operator Permission Guard (advisory-only)")
        for role in OperatorRole:
            print(f"  {role.value:<9}: {', '.join(matrix[role.value]) or '(none)'}")
        print("  forbidden (any role): FORBIDDEN_EXECUTION (broker/order/execute)")
        print(f"  default role (env)  : {payload['default_role']}")
    return 0


__all__ = [
    "OperationClass",
    "OperatorRole",
    "PermissionRequest",
    "PermissionDecision",
    "ALLOWED_OPERATIONS",
    "DEFAULT_AUDIT_PATH",
    "RECEIPT_DIR",
    "DEFAULT_RECEIPT_MAX_AGE_MINUTES",
    "RECEIPT_DIR_ENV_VAR",
    "receipt_dir",
    "ROLE_ENV_VAR",
    "NO_DRY_RUN_NEEDED",
    "evaluate_permission",
    "assert_permission_decision_allowed",
    "require_permission_or_exit",
    "assert_guarded_mutation",
    "guarded_mutation",
    "guarded_mutation_context",
    "build_apply_decision",
    "write_operator_audit_event",
    "read_recent_audit_events",
    "load_operator_role_from_env",
    "safe_db_path_allowed",
    "classify_db_path",
    "forbid_execution_operation",
    "db_path_hash",
    "write_dry_run_receipt",
    "validate_dry_run_receipt",
    "caller_safety_stamps",
]


if __name__ == "__main__":
    raise SystemExit(main())
