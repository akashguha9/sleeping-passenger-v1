"""
Reconciliation → Moltbook learning bridge (Sprint J).

Turns ANY learning-worthy terminal or partial reconciliation event into
exactly ONE advisory-only Moltbook learning entry — mistakes AND
successes.  This is the generalised replacement for the loss-only
``moltbook_reconciliation_bridge``: that module still works for the
backfill-style "scan + insert losses" command, but the live API path
calls THIS module so every reconciliation save (stop-hits, partial
take-profits, closes, good/bad process outcomes) lands in Moltbook.

Contract
--------
- SQLite (``moltbook_entries``) is canonical.  JSONL is an audit mirror.
- Idempotency key = ``trade_id|event_type|exit_price|exit_quantity``.
  Re-saving the same reconciliation updates the existing row; it never
  creates a duplicate.
- Every entry preserves the advisory invariants:
    advisory_status      = ADVISORY_ONLY
    execution_mode       = HUMAN_ONLY
    human_review_required = True
    ai_execution_count   = 0
    broker_api_called    = False
- This module NEVER places, modifies, or cancels a broker order.

Event types produced
--------------------
  STOP_LOSS_HIT          stop hit / STOPPED_OUT post_trade_outcome
  PARTIAL_TP_HIT         partial TP with actual_exit_price + qty > 0
  PARTIAL_TP_LOGGED      partial TP logged as plan only (no fill yet)
  CLOSED                 any CLOSED_WIN / CLOSED_LOSS / BREAKEVEN /
                         MANUAL_EXIT / TIMEOUT_EXIT
  GOOD_PROCESS_WIN       caller-set outcome_quality
  GOOD_PROCESS_LOSS      caller-set outcome_quality
  BAD_PROCESS_WIN        caller-set outcome_quality
  BAD_PROCESS_LOSS       caller-set outcome_quality
"""
from __future__ import annotations

import hashlib
import uuid
from typing import Any

try:
    from scripts.runtime_common import utc_timestamp, append_jsonl
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from runtime_common import utc_timestamp, append_jsonl  # type: ignore[no-redef]

try:
    import scripts.persistence as _persistence
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import persistence as _persistence  # type: ignore[no-redef]

try:
    import scripts.moltbook_api as _moltbook_api
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import moltbook_api as _moltbook_api  # type: ignore[no-redef]


# ---------------------------------------------------------------------------
# Event-type vocabulary
# ---------------------------------------------------------------------------

EVENT_STOP_LOSS_HIT = "STOP_LOSS_HIT"
EVENT_PARTIAL_TP_HIT = "PARTIAL_TP_HIT"
EVENT_PARTIAL_TP_LOGGED = "PARTIAL_TP_LOGGED"
EVENT_CLOSED = "CLOSED"

LEARNING_WORTHY_EVENT_TYPES: frozenset[str] = frozenset(
    {
        EVENT_STOP_LOSS_HIT,
        EVENT_PARTIAL_TP_HIT,
        EVENT_PARTIAL_TP_LOGGED,
        EVENT_CLOSED,
        # Synonyms / explicit operator labels — accepted on the input side.
        "STOP_HIT",
        "STOPPED_OUT",
        "GOOD_PROCESS_WIN",
        "GOOD_PROCESS_LOSS",
        "BAD_PROCESS_WIN",
        "BAD_PROCESS_LOSS",
    }
)

LEARNING_DIRECTION_MISTAKE = "MISTAKE_OR_INVALIDATION"
LEARNING_DIRECTION_SUCCESS = "SUCCESS_PATTERN"
LEARNING_DIRECTION_NEUTRAL = "NEUTRAL"

# Mistake tags that should bump a stop-hit from GOOD_PROCESS_LOSS down to
# BAD_PROCESS_LOSS unless the operator explicitly chose otherwise.
BAD_PROCESS_MISTAKE_TAGS: frozenset[str] = frozenset(
    {
        "oversized",
        "late_entry",
        "fomo",
        "ignored_stop",
        "moved_stop",
        "revenge_entry",
    }
)

# Outcome qualities accepted on the input side.
ACCEPTED_OUTCOME_QUALITIES: frozenset[str] = frozenset(
    {
        "GOOD_PROCESS_WIN",
        "GOOD_PROCESS_LOSS",
        "BAD_PROCESS_WIN",
        "BAD_PROCESS_LOSS",
        "UNDETERMINED",
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _split_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip().lower() for v in value if str(v).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [tag.strip().lower() for tag in text.replace(";", ",").split(",") if tag.strip()]


def classify_event_type(
    *,
    post_trade_outcome: str,
    stop_loss_hit: bool,
    actual_exit_price: float | None,
    exit_quantity: float | None,
    partial_take_profit_price: float | None,
    partial_take_profit_quantity: float | None,
    explicit_event_type: str = "",
) -> str:
    """Decide which Moltbook event_type a reconciliation maps to.

    An explicit ``explicit_event_type`` from the caller wins as long as
    it's in the accepted vocabulary — operators can force PARTIAL_TP_LOGGED
    on a planning save, or BAD_PROCESS_WIN on a lucky scratch.
    """
    explicit = (explicit_event_type or "").strip().upper()
    if explicit in LEARNING_WORTHY_EVENT_TYPES:
        # Normalise STOP_HIT / STOPPED_OUT → canonical STOP_LOSS_HIT.
        if explicit in {"STOP_HIT", "STOPPED_OUT"}:
            return EVENT_STOP_LOSS_HIT
        return explicit

    pto = (post_trade_outcome or "").strip().upper()
    if stop_loss_hit or pto in {"STOPPED_OUT", "STOP_HIT", "STOP_LOSS"}:
        return EVENT_STOP_LOSS_HIT
    if pto == "PARTIAL_TP":
        # Distinguish "actually filled a partial TP" vs "logged a partial
        # TP plan but the fill hasn't happened yet".  A real fill has an
        # actual_exit_price and a non-zero exit_quantity.
        has_actual_fill = (
            actual_exit_price is not None
            and actual_exit_price > 0
            and exit_quantity is not None
            and exit_quantity > 0
        )
        if has_actual_fill:
            return EVENT_PARTIAL_TP_HIT
        # Plan-only logged TP — recorded so the moltbook can learn from
        # what was *planned* even before the fill arrives.
        if (
            partial_take_profit_price is not None and partial_take_profit_price > 0
        ) or (
            partial_take_profit_quantity is not None and partial_take_profit_quantity > 0
        ):
            return EVENT_PARTIAL_TP_LOGGED
        return EVENT_PARTIAL_TP_HIT
    if pto in {
        "CLOSED_WIN",
        "CLOSED_LOSS",
        "BREAKEVEN",
        "MANUAL_EXIT",
        "TIMEOUT_EXIT",
    }:
        return EVENT_CLOSED
    return ""


def classify_outcome_quality(
    *,
    event_type: str,
    explicit_outcome_quality: str,
    mistake_tags: list[str],
    realized_pl: float | None,
    post_trade_outcome: str,
) -> str:
    """Derive outcome_quality respecting operator override and mistake tags.

    Rules (in priority order):
      1. Operator-supplied outcome_quality wins.
      2. STOP_LOSS_HIT: BAD_PROCESS_LOSS if any mistake tag is in
         BAD_PROCESS_MISTAKE_TAGS, else GOOD_PROCESS_LOSS.
      3. PARTIAL_TP_HIT / PARTIAL_TP_LOGGED: GOOD_PROCESS_WIN (the
         operator booked profit per plan).
      4. CLOSED with realized_pl > 0: GOOD_PROCESS_WIN.
         CLOSED with realized_pl < 0: GOOD_PROCESS_LOSS (process was
         valid — exit discipline worked), unless mistake tags flag bad
         process → BAD_PROCESS_LOSS.
         CLOSED with realized_pl == 0 or unknown: UNDETERMINED.
    """
    eq = (explicit_outcome_quality or "").strip().upper()
    if eq in ACCEPTED_OUTCOME_QUALITIES:
        return eq

    bad_process = bool(set(mistake_tags) & BAD_PROCESS_MISTAKE_TAGS)
    if event_type == EVENT_STOP_LOSS_HIT:
        return "BAD_PROCESS_LOSS" if bad_process else "GOOD_PROCESS_LOSS"
    if event_type in {EVENT_PARTIAL_TP_HIT, EVENT_PARTIAL_TP_LOGGED}:
        # Booking partial profit per plan is a success pattern.
        return "BAD_PROCESS_WIN" if bad_process else "GOOD_PROCESS_WIN"
    if event_type == EVENT_CLOSED:
        if realized_pl is None or realized_pl == 0.0:
            return "UNDETERMINED"
        if realized_pl > 0:
            return "BAD_PROCESS_WIN" if bad_process else "GOOD_PROCESS_WIN"
        return "BAD_PROCESS_LOSS" if bad_process else "GOOD_PROCESS_LOSS"
    return "UNDETERMINED"


def classify_learning_direction(event_type: str, outcome_quality: str) -> str:
    """Map (event_type, outcome_quality) to a learning_direction.

    Stop-hits and losing closes are MISTAKE_OR_INVALIDATION (the original
    thesis got invalidated).  Wins and partial-TPs are SUCCESS_PATTERN.
    Everything else is NEUTRAL — recorded but not steered.
    """
    eq = (outcome_quality or "").strip().upper()
    if event_type == EVENT_STOP_LOSS_HIT:
        return LEARNING_DIRECTION_MISTAKE
    if event_type in {EVENT_PARTIAL_TP_HIT, EVENT_PARTIAL_TP_LOGGED}:
        return LEARNING_DIRECTION_SUCCESS
    if eq in {"GOOD_PROCESS_WIN", "BAD_PROCESS_WIN"}:
        return LEARNING_DIRECTION_SUCCESS
    if eq in {"GOOD_PROCESS_LOSS", "BAD_PROCESS_LOSS"}:
        return LEARNING_DIRECTION_MISTAKE
    return LEARNING_DIRECTION_NEUTRAL


def _map_to_legacy_mistake_type(
    event_type: str, outcome_quality: str, stop_loss_hit: bool
) -> str:
    """Map the new event_type to the legacy mistake_type column.

    The legacy column is constrained to ACCEPTED_MISTAKE_TYPES so the
    existing aggregations / dashboards keep working.  We pick the closest
    semantic match.
    """
    if event_type == EVENT_STOP_LOSS_HIT:
        return "stop_loss_breach"
    if event_type in {EVENT_PARTIAL_TP_HIT, EVENT_PARTIAL_TP_LOGGED}:
        return "good_signal_good_execution"
    if event_type == EVENT_CLOSED:
        eq = (outcome_quality or "").upper()
        if eq == "GOOD_PROCESS_WIN":
            return "good_signal_good_execution"
        if eq == "BAD_PROCESS_WIN":
            return "bad_signal_lucky_profit"
        if eq == "GOOD_PROCESS_LOSS":
            return "manual_exit_loss" if not stop_loss_hit else "stop_loss_breach"
        if eq == "BAD_PROCESS_LOSS":
            return "stop_loss_breach" if stop_loss_hit else "trade_loss"
        return "trade_loss"
    return "trade_loss"


def compute_idempotency_key(
    *,
    trade_id: str,
    event_type: str,
    exit_price: float | None,
    exit_quantity: float | None,
) -> str:
    """Stable hash of (trade_id, event_type, exit_price, exit_quantity).

    Round prices/quantities to 6 d.p. before hashing so floating-point
    noise (e.g. 411.5 vs 411.500000001) never produces a fresh key.
    Missing values are encoded as the literal "NA" so a partial save and
    a fully-filled save remain distinguishable.
    """
    parts = [
        str(trade_id or "").strip(),
        str(event_type or "").strip().upper(),
        ("%.6f" % round(exit_price, 6)) if exit_price is not None else "NA",
        ("%.6f" % round(exit_quantity, 6)) if exit_quantity is not None else "NA",
    ]
    raw = "|".join(parts).encode("utf-8")
    digest = hashlib.sha1(raw, usedforsecurity=False).hexdigest()  # advisory hash
    return f"MBK_{digest[:24]}"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def record_reconciliation_learning(
    *,
    trade_id: str,
    event_id: str,
    ticker: str,
    side: str = "",
    post_trade_outcome: str = "",
    reconciliation_status: str = "",
    actual_exit_price: float | None = None,
    exit_quantity: float | None = None,
    entry_price: float | None = None,
    entry_quantity: float | None = None,
    stop_loss_price: float | None = None,
    stop_loss_hit: bool = False,
    partial_take_profit_price: float | None = None,
    partial_take_profit_quantity: float | None = None,
    runner_quantity: float | None = None,
    take_profit_plan: str = "",
    realized_pl: float | None = None,
    outcome_quality: str = "",
    mistake_tags: Any = "",
    success_tags: Any = "",
    lesson: str = "",
    notes: str = "",
    exit_reason: str = "",
    thesis: str = "",
    invalidation_level: str = "",
    explicit_event_type: str = "",
    db_path: Any = None,
    jsonl_path: Any = None,
) -> dict[str, Any]:
    """Create or update a Moltbook learning entry from a reconciliation save.

    Returns a status dict the API layer surfaces back to the UI:

        {
          "status": "created" | "updated" | "skipped",
          "event_type": "...",
          "outcome_quality": "...",
          "learning_direction": "...",
          "entry_id": "...",
          "idempotency_key": "...",
          "message": "Moltbook learning entry created" | "...",
          "advisory_status": "ADVISORY_ONLY",
          "broker_api_called": False,
          ...safety stamps...
        }

    ``status="skipped"`` when the reconciliation is not learning-worthy
    (e.g. an OPEN save) — the operator still sees a clean response.
    """
    if not trade_id:
        return _safety_stamped(
            {"status": "skipped", "reason": "trade_id required",
             "message": "Reconciliation saved (no Moltbook entry — missing trade_id)"}
        )

    exit_price_f = _coerce_float(actual_exit_price)
    exit_qty_f = _coerce_float(exit_quantity)
    entry_price_f = _coerce_float(entry_price)
    entry_qty_f = _coerce_float(entry_quantity)
    stop_price_f = _coerce_float(stop_loss_price)
    tp_price_f = _coerce_float(partial_take_profit_price)
    tp_qty_f = _coerce_float(partial_take_profit_quantity)
    runner_qty_f = _coerce_float(runner_quantity)
    realized_pl_f = _coerce_float(realized_pl)

    event_type = classify_event_type(
        post_trade_outcome=post_trade_outcome,
        stop_loss_hit=bool(stop_loss_hit),
        actual_exit_price=exit_price_f,
        exit_quantity=exit_qty_f,
        partial_take_profit_price=tp_price_f,
        partial_take_profit_quantity=tp_qty_f,
        explicit_event_type=explicit_event_type,
    )
    if not event_type:
        return _safety_stamped(
            {"status": "skipped",
             "reason": "not_learning_worthy",
             "post_trade_outcome": post_trade_outcome,
             "message": "Reconciliation saved (no Moltbook entry — open / not terminal)"}
        )

    mistake_list = _split_tags(mistake_tags)
    success_list = _split_tags(success_tags)

    eq = classify_outcome_quality(
        event_type=event_type,
        explicit_outcome_quality=outcome_quality,
        mistake_tags=mistake_list,
        realized_pl=realized_pl_f,
        post_trade_outcome=post_trade_outcome,
    )
    direction = classify_learning_direction(event_type, eq)
    legacy_mistake_type = _map_to_legacy_mistake_type(
        event_type, eq, bool(stop_loss_hit)
    )

    # Booked / ride percentages: only meaningful when we have both the
    # entry quantity and either the partial-TP fill or the runner.  Never
    # invent these — leave None when the data is absent.
    booked_pct: float | None = None
    ride_pct: float | None = None
    if entry_qty_f and entry_qty_f > 0:
        if event_type in {EVENT_PARTIAL_TP_HIT, EVENT_PARTIAL_TP_LOGGED}:
            booked_qty = exit_qty_f if exit_qty_f is not None else tp_qty_f
            if booked_qty is not None:
                booked_pct = round(min(100.0, max(0.0, booked_qty / entry_qty_f * 100.0)), 4)
                ride_pct = round(max(0.0, 100.0 - booked_pct), 4)
        elif event_type == EVENT_CLOSED:
            if exit_qty_f is not None:
                booked_pct = round(min(100.0, max(0.0, exit_qty_f / entry_qty_f * 100.0)), 4)
                ride_pct = round(max(0.0, 100.0 - booked_pct), 4)

    idempotency_key = compute_idempotency_key(
        trade_id=trade_id,
        event_type=event_type,
        exit_price=exit_price_f,
        exit_quantity=exit_qty_f,
    )

    thesis_text = (thesis or "").strip() or "Reconciliation-derived learning entry."
    final_decision = _build_final_decision(event_type, eq, post_trade_outcome)
    outcome_text = _build_outcome_text(
        event_type=event_type,
        realized_pl=realized_pl_f,
        entry_price=entry_price_f,
        exit_price=exit_price_f,
        exit_quantity=exit_qty_f,
        side=side,
    )
    ai_interpretation = (
        "Advisory-only review of a reconciliation event. The Moltbook "
        "learns from both mistakes and successes; this entry records the "
        "operator's exit data and authorizes no execution."
    )
    if exit_reason:
        ai_interpretation += f" Operator-entered exit reason: {exit_reason}"
    user_reflection = (
        "Reconciliation save — no separate reflection captured; human "
        "review required."
    )
    lesson_text = (lesson or "").strip() or _default_lesson_for(event_type, eq)
    recalibration_note = (
        "Correction candidate only — not auto-applied. Requires human "
        "confirmation before any rule or threshold change."
    )

    now = utc_timestamp()
    entry_id = f"MB_{uuid.uuid4().hex[:12]}"
    result = _persistence.upsert_moltbook_learning_entry(
        entry_id=entry_id,
        idempotency_key=idempotency_key,
        trade_id=trade_id,
        event_id=event_id or "",
        ticker=ticker,
        source_trade_state=(post_trade_outcome or "").strip().upper(),
        event_type=event_type,
        outcome_quality=eq,
        learning_direction=direction,
        entry_price=entry_price_f,
        exit_price=exit_price_f,
        exit_quantity=exit_qty_f,
        stop_loss_price=stop_price_f,
        take_profit_price=tp_price_f,
        realized_pl=realized_pl_f,
        booked_percent=booked_pct,
        ride_percent=ride_pct,
        mistake_tags=",".join(sorted(set(mistake_list))),
        success_tags=",".join(sorted(set(success_list))),
        lesson=lesson_text,
        notes=(notes or "").strip(),
        original_signal_thesis=thesis_text,
        ai_interpretation=ai_interpretation,
        user_reflection=user_reflection,
        final_human_decision=final_decision,
        outcome=outcome_text,
        mistake_type=legacy_mistake_type,
        lesson_learned=lesson_text,
        bias_detected="",
        recalibration_note=recalibration_note,
        future_rule_update="",
        created_at=now,
        updated_at=now,
        db_path=db_path,
    )

    # Audit-only JSONL mirror.  Best-effort; never canonical.
    try:
        target_jsonl = jsonl_path if jsonl_path is not None else _moltbook_api.MOLTBOOK_LOG
        append_jsonl(
            target_jsonl,
            {
                "entry_id": result["entry_id"],
                "trade_id": trade_id,
                "event_id": event_id or "",
                "ticker": str(ticker).upper(),
                "event_type": event_type,
                "outcome_quality": eq,
                "learning_direction": direction,
                "idempotency_key": idempotency_key,
                "realized_pl": realized_pl_f,
                "exit_price": exit_price_f,
                "exit_quantity": exit_qty_f,
                "created_at": now,
                "updated_at": now,
                "mistake_type": legacy_mistake_type,
                "advisory_status": "ADVISORY_ONLY",
                "execution_mode": "HUMAN_ONLY",
                "broker_api_called": False,
                "ai_execution_count": 0,
                "operation": (
                    "moltbook_learning_updated" if result.get("updated")
                    else "moltbook_learning_created"
                ),
            },
            stamp=False,
        )
    except Exception:
        pass

    status = "updated" if result.get("updated") else "created"
    if result.get("updated"):
        message = "Moltbook learning entry already existed, updated safely"
    else:
        message = "Moltbook learning entry created"
    return _safety_stamped({
        "status": status,
        "event_type": event_type,
        "outcome_quality": eq,
        "learning_direction": direction,
        "entry_id": result["entry_id"],
        "idempotency_key": idempotency_key,
        "trade_id": trade_id,
        "ticker": str(ticker).upper(),
        "realized_pl": realized_pl_f,
        "booked_percent": booked_pct,
        "ride_percent": ride_pct,
        "mistake_tags": mistake_list,
        "success_tags": success_list,
        "lesson": lesson_text,
        "message": message,
    })


def _build_final_decision(
    event_type: str, outcome_quality: str, post_trade_outcome: str
) -> str:
    pto = (post_trade_outcome or "").strip().upper()
    suffix = f" ({pto})" if pto else ""
    if event_type == EVENT_STOP_LOSS_HIT:
        return f"Stop-loss hit — position closed{suffix}"
    if event_type == EVENT_PARTIAL_TP_HIT:
        return f"Partial take-profit booked{suffix}"
    if event_type == EVENT_PARTIAL_TP_LOGGED:
        return f"Partial take-profit logged{suffix}"
    if event_type == EVENT_CLOSED:
        eq = (outcome_quality or "").upper()
        if eq.endswith("_WIN"):
            return f"Closed at a win{suffix}"
        if eq.endswith("_LOSS"):
            return f"Closed at a loss{suffix}"
        return f"Closed{suffix}"
    return f"Reconciliation recorded{suffix}"


def _build_outcome_text(
    *,
    event_type: str,
    realized_pl: float | None,
    entry_price: float | None,
    exit_price: float | None,
    exit_quantity: float | None,
    side: str,
) -> str:
    parts: list[str] = [event_type]
    if realized_pl is not None:
        parts.append(f"Realized P/L {realized_pl:g}")
    if entry_price is not None and exit_price is not None:
        pct: float | None = None
        if entry_price:
            raw = (exit_price - entry_price) / entry_price * 100.0
            pct = -raw if str(side).upper() in {"SELL", "SHORT"} else raw
        seg = f"entry {entry_price:g} -> exit {exit_price:g}"
        if pct is not None:
            seg += f" ({pct:+.2f}%)"
        parts.append(seg)
    if exit_quantity is not None:
        parts.append(f"qty {exit_quantity:g}")
    return "; ".join(parts)


def _default_lesson_for(event_type: str, outcome_quality: str) -> str:
    eq = (outcome_quality or "").upper()
    if event_type == EVENT_STOP_LOSS_HIT:
        if eq == "BAD_PROCESS_LOSS":
            return (
                "Stop hit on a bad-process trade. Review sizing, entry "
                "timing, and stop discipline before the next setup."
            )
        return (
            "Stop hit on a valid-process trade. Confirm invalidation "
            "level was honoured; preserve exit discipline."
        )
    if event_type == EVENT_PARTIAL_TP_HIT:
        return (
            "Partial take-profit booked. Confirm the runner plan and "
            "trailing-stop logic for the remaining position."
        )
    if event_type == EVENT_PARTIAL_TP_LOGGED:
        return (
            "Partial take-profit plan logged. Watch the price action vs "
            "the planned TP price and update on fill."
        )
    if event_type == EVENT_CLOSED:
        if eq.endswith("_WIN"):
            return (
                "Trade closed at a win. Capture what worked: setup "
                "quality, timing, and stop placement."
            )
        if eq.endswith("_LOSS"):
            return (
                "Trade closed at a loss. Review whether thesis was "
                "invalidated and whether exit discipline held."
            )
    return "Reconciliation recorded; human review required."


def _safety_stamped(payload: dict[str, Any]) -> dict[str, Any]:
    payload.setdefault("advisory_status", "ADVISORY_ONLY")
    payload.setdefault("execution_mode", "HUMAN_ONLY")
    payload.setdefault("execution_gate", "LOCKED")
    payload.setdefault("broker_api_called", False)
    payload.setdefault("broker_order_id", "NONE")
    payload.setdefault("ai_execution_count", 0)
    payload.setdefault("human_review_required", True)
    payload.setdefault("execution_permission", False)
    payload.setdefault("can_execute", False)
    payload.setdefault("record_keeping_only", True)
    payload.setdefault("generated_at", utc_timestamp())
    return payload


__all__ = [
    "EVENT_STOP_LOSS_HIT",
    "EVENT_PARTIAL_TP_HIT",
    "EVENT_PARTIAL_TP_LOGGED",
    "EVENT_CLOSED",
    "LEARNING_WORTHY_EVENT_TYPES",
    "LEARNING_DIRECTION_MISTAKE",
    "LEARNING_DIRECTION_SUCCESS",
    "LEARNING_DIRECTION_NEUTRAL",
    "BAD_PROCESS_MISTAKE_TAGS",
    "ACCEPTED_OUTCOME_QUALITIES",
    "classify_event_type",
    "classify_outcome_quality",
    "classify_learning_direction",
    "compute_idempotency_key",
    "record_reconciliation_learning",
]
