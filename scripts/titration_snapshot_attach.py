"""Auto-attach Market Titration snapshot at manual/paper trade log time.

Mirror of ``scripts/reactor_snapshot_attach.py`` for the Market Titration
Engine.  Recording the titration state the system could already compute at
the moment the operator logged a trade is what makes the titration layer
outcome-calibratable later: reconciled outcomes can be joined against
``titration_state_at_decision`` exactly as they are joined against
``reactor_state_at_decision`` today.

Invariants (these MUST NOT regress):

* Never overwrites an explicit value the caller supplied.
* Never fabricates data — if no inbox/titration context is available for
  the event, or the state is INSUFFICIENT_DATA, returns
  ``("unavailable", {})`` and the row stays empty.
* Never grants execution permission; journal-quality columns only.
* Pure / defensive — any import or evaluation failure degrades to
  ``("unavailable", {})``.

Attach-source labels:

* ``"provided_explicitly"`` — caller supplied at least one titration field.
* ``"attached_from_signal"`` — helper filled fields from a live evaluation.
* ``"unavailable"`` — no usable titration context; row stays empty.
"""
from __future__ import annotations

from typing import Any

TITRATION_AT_DECISION_FIELDS: tuple[str, ...] = (
    "titration_state_at_decision",
    "titration_pre_alpha_gap_at_decision",
    "titration_lrr_at_decision",
)

ATTACH_PROVIDED = "provided_explicitly"
ATTACH_FROM_SIGNAL = "attached_from_signal"
ATTACH_UNAVAILABLE = "unavailable"


def _is_explicit_text(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    return bool(str(value).strip())


def _is_explicit_number(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    return isinstance(value, (int, float))


def has_explicit_titration_fields(explicit: dict[str, Any]) -> bool:
    if _is_explicit_text(explicit.get("titration_state_at_decision")):
        return True
    for key in (
        "titration_pre_alpha_gap_at_decision",
        "titration_lrr_at_decision",
    ):
        if _is_explicit_number(explicit.get(key)):
            return True
    return False


def _lookup_titration_signal(event_id: str) -> dict[str, Any] | None:
    """Best-effort lookup of the decorated inbox item for ``event_id``.

    Returns None on any failure or when the titration layer reported
    INSUFFICIENT_DATA — absence of evidence is never turned into a row.
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
    if not signal.get("titration_available"):
        return None
    state = str(signal.get("titration_state") or "").strip()
    if not state or state.upper() == "INSUFFICIENT_DATA":
        return None
    return signal


def _map_signal_to_snapshot(signal: dict[str, Any]) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    state = signal.get("titration_state")
    if _is_explicit_text(state):
        snapshot["titration_state_at_decision"] = str(state)
    titration = signal.get("titration")
    if isinstance(titration, dict):
        pag = titration.get("pre_alpha_gap")
        if _is_explicit_number(pag):
            snapshot["titration_pre_alpha_gap_at_decision"] = float(pag)
        lrr = titration.get("lrr")
        if _is_explicit_number(lrr):
            snapshot["titration_lrr_at_decision"] = float(lrr)
    return snapshot


def maybe_attach_titration_snapshot(
    explicit: dict[str, Any], *, event_id: str
) -> tuple[str, dict[str, Any]]:
    """Return (attach_source, fields_to_fill).

    ``fields_to_fill`` is non-empty only when attach_source is
    ``attached_from_signal``.  Explicit caller values always win.
    """
    try:
        if has_explicit_titration_fields(explicit or {}):
            return ATTACH_PROVIDED, {}
        signal = _lookup_titration_signal(event_id)
        if signal is None:
            return ATTACH_UNAVAILABLE, {}
        snapshot = _map_signal_to_snapshot(signal)
        if not snapshot.get("titration_state_at_decision"):
            return ATTACH_UNAVAILABLE, {}
        return ATTACH_FROM_SIGNAL, snapshot
    except Exception:
        return ATTACH_UNAVAILABLE, {}


__all__ = [
    "TITRATION_AT_DECISION_FIELDS",
    "ATTACH_PROVIDED",
    "ATTACH_FROM_SIGNAL",
    "ATTACH_UNAVAILABLE",
    "has_explicit_titration_fields",
    "maybe_attach_titration_snapshot",
]
