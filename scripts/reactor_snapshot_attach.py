"""Auto-attach Signal Reactor snapshot at manual/paper write time.

Ceiling-push fix.  The Outcome-Calibration gate has a multiplicative term
``Rows_With_Reactor_Snapshot``; before this helper, that count was zero
because operators almost never hand-fill the nine reactor-at-decision
fields on the manual-trade form.  This helper captures the reactor
state the system *can already compute* for the same event and writes it
alongside the row.

Invariants (these MUST NOT regress):

* Never overwrites an explicit value the caller supplied.
* Never fabricates data — if no inbox/reactor context is available for
  the event, returns ``("unavailable", {})`` and the row stays empty.
* Never grants execution permission.  The advisory/safety stamps on the
  ``log_manual_trade`` and paper-import responses are unchanged; this
  helper only fills journal-quality columns.
* Never mutates historical rows.
* Pure / defensive — any import or evaluation failure degrades to
  ``("unavailable", {})``.

Returned attach-source labels (advisory-only, for the response payload
and for tests):

* ``"provided_explicitly"`` — the caller supplied at least one reactor
  field; the helper made no changes.
* ``"attached_from_signal"`` — the helper filled at least one reactor
  field from a live inbox/reactor evaluation.
* ``"unavailable"`` — no usable reactor context; row stays empty.
"""
from __future__ import annotations

from typing import Any

# The nine reactor-at-decision columns log_manual_trade accepts.  These
# names match the manual_trades schema and the API/CSV contract; do not
# rename without updating callers + tests.
REACTOR_AT_DECISION_FIELDS: tuple[str, ...] = (
    "reactor_state_at_decision",
    "decision_grade_energy_at_decision",
    "echo_risk_score_at_decision",
    "meltdown_risk_at_decision",
    "fusion_validity_at_decision",
    "fission_branch_clarity_at_decision",
    "operator_heat_at_decision",
    "gallardo_block_at_decision",
    "preflight_state_at_decision",
)

ATTACH_PROVIDED = "provided_explicitly"
ATTACH_FROM_SIGNAL = "attached_from_signal"
ATTACH_UNAVAILABLE = "unavailable"


def _is_explicit_text(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return False
    text = str(value).strip()
    return bool(text)


def _is_explicit_number(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return False
    return isinstance(value, (int, float))


def _is_explicit_bool(value: Any) -> bool:
    # An explicit False is a real choice, so we treat any bool that was
    # actually passed as explicit.  Only ``None`` counts as "not provided".
    return isinstance(value, bool)


def has_explicit_reactor_fields(explicit: dict[str, Any]) -> bool:
    """Return True if the caller passed any non-default reactor field.

    A caller-supplied value — even a deliberate ``False`` for
    ``gallardo_block_at_decision`` — is honored as-is and prevents
    auto-attach.  This keeps the helper a strict additive layer.
    """
    if _is_explicit_text(explicit.get("reactor_state_at_decision")):
        return True
    if _is_explicit_text(explicit.get("fusion_validity_at_decision")):
        return True
    if _is_explicit_text(explicit.get("preflight_state_at_decision")):
        return True
    for key in (
        "decision_grade_energy_at_decision",
        "echo_risk_score_at_decision",
        "meltdown_risk_at_decision",
        "fission_branch_clarity_at_decision",
        "operator_heat_at_decision",
    ):
        if _is_explicit_number(explicit.get(key)):
            return True
    if _is_explicit_bool(explicit.get("gallardo_block_at_decision")):
        return True
    return False


def _lookup_reactor_payload(event_id: str) -> dict[str, Any] | None:
    """Best-effort lookup of the decorated inbox item for ``event_id``.

    Returns None on any failure (missing module, missing signal, network
    issue) — callers treat None as ``ATTACH_UNAVAILABLE``.
    """
    if not event_id or not isinstance(event_id, str):
        return None
    try:
        try:
            from scripts.signal_inbox_api import get_signal_detail
        except ModuleNotFoundError:  # pragma: no cover - script-style fallback
            from signal_inbox_api import get_signal_detail  # type: ignore[no-redef]
    except Exception:
        return None
    try:
        detail = get_signal_detail(event_id)
    except Exception:
        return None
    if not isinstance(detail, dict):
        return None
    signal = detail.get("signal")
    if not isinstance(signal, dict):
        return None
    if not signal.get("reactor_available"):
        return None
    state = str(signal.get("reactor_state") or "").strip()
    if not state or state.upper() == "INSUFFICIENT_DATA":
        # No real reactor verdict — refuse to fabricate.
        return None
    return signal


def _map_signal_to_snapshot(signal: dict[str, Any]) -> dict[str, Any]:
    """Translate the decorated inbox-item field names into the
    manual_trades reactor_at_decision column names."""
    snapshot: dict[str, Any] = {}
    state = signal.get("reactor_state")
    if _is_explicit_text(state):
        snapshot["reactor_state_at_decision"] = str(state)
    for src, dst in (
        ("decision_grade_energy", "decision_grade_energy_at_decision"),
        ("echo_risk_score", "echo_risk_score_at_decision"),
        ("meltdown_risk_score", "meltdown_risk_at_decision"),
        ("fission_branch_clarity", "fission_branch_clarity_at_decision"),
        ("operator_heat_score", "operator_heat_at_decision"),
    ):
        val = signal.get(src)
        if _is_explicit_number(val):
            snapshot[dst] = float(val)
    fusion = signal.get("fusion_validity")
    if _is_explicit_text(fusion):
        snapshot["fusion_validity_at_decision"] = str(fusion)
    gallardo = signal.get("gallardo_block")
    if isinstance(gallardo, bool):
        snapshot["gallardo_block_at_decision"] = gallardo
    # preflight_state_at_decision is intentionally not derived here; the
    # preflight subsystem is separate and a stale guess would be worse
    # than leaving the column empty.
    return snapshot


def maybe_attach_reactor_snapshot(
    explicit: dict[str, Any],
    *,
    event_id: str = "",
    source_signal_id: str = "",
) -> tuple[str, dict[str, Any]]:
    """Return ``(attach_source, snapshot)``.

    Behaviour
    ---------
    * If ``explicit`` already contains any reactor field, returns
      ``(ATTACH_PROVIDED, {})`` — caller keeps their values untouched.
    * Otherwise, looks up the live reactor advisory for ``event_id``
      (falling back to ``source_signal_id``) and returns its mapped
      snapshot under ``ATTACH_FROM_SIGNAL``.
    * If no usable reactor context exists, returns
      ``(ATTACH_UNAVAILABLE, {})`` and the row stays empty.
    """
    if has_explicit_reactor_fields(explicit):
        return ATTACH_PROVIDED, {}

    for candidate in (event_id, source_signal_id):
        signal = _lookup_reactor_payload(candidate)
        if signal is None:
            continue
        snapshot = _map_signal_to_snapshot(signal)
        if snapshot:
            return ATTACH_FROM_SIGNAL, snapshot
    return ATTACH_UNAVAILABLE, {}


__all__ = [
    "REACTOR_AT_DECISION_FIELDS",
    "ATTACH_PROVIDED",
    "ATTACH_FROM_SIGNAL",
    "ATTACH_UNAVAILABLE",
    "has_explicit_reactor_fields",
    "maybe_attach_reactor_snapshot",
]
