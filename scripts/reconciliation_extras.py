"""
Reconciliation extras — pure-Python helpers for the Reconciliation tab.

Extends :mod:`scripts.signal_inbox_api`'s thin reconcile_trade with a
richer outcome model (partial TP / runner / stop-hit / cancel) without
introducing any execution behaviour.

Hard rules (locked by tests):

* No broker API call.
* No order placement / cancellation.
* No AI execution path.
* Every produced payload carries advisory_status=ADVISORY_ONLY,
  execution_gate=LOCKED, broker_api_called=False, ai_execution_count=0.
* P/L is computed locally from operator-entered fill prices ONLY — never
  from a chart structure response, never from any "current price" lookup.

Public surface:

* OUTCOME_TO_LEGACY_STATUS  — mapping from new post_trade_outcome enum to
                              legacy WIN/LOSS/BREAKEVEN/UNKNOWN status.
* split_quantity_70_30      — 70/30 default partial-TP / runner split with
                              precision-safe runner = total - tp.
* compute_realized_pnl_long — long-side realized P/L formula.
* normalize_post_trade_outcome / normalize_reconciliation_status / …
                              — enum normalizers (tolerant of bad input).
* build_outcome_payload     — produces the structured outcome dict that
                              reconcile_trade serialises into outcome_notes
                              and surfaces back to the API caller.

This module is dependency-free (no FastAPI, no SQLite, no pandas) so the
unit tests can run without any framework available.
"""
from __future__ import annotations

import json
from typing import Any

# ---------------------------------------------------------------------------
# Status / outcome enums (kept as frozensets so callers can do `in` checks).
# ---------------------------------------------------------------------------

POST_TRADE_OUTCOMES: frozenset[str] = frozenset(
    {
        "OPEN",
        "PARTIAL_TP",
        "CLOSED_WIN",
        "CLOSED_LOSS",
        "BREAKEVEN",
        "STOPPED_OUT",
        "MANUAL_EXIT",
        "TIMEOUT_EXIT",
        "CANCELLED_DUPLICATE",
    }
)

RECONCILIATION_STATUSES: frozenset[str] = frozenset(
    {
        "AWAITING_RECONCILIATION",
        "PARTIAL_RECONCILED",
        "RECONCILED",
        "CANCELLED_LOG",
        "CANCELLED_DUPLICATE",
    }
)

OUTCOME_QUALITIES: frozenset[str] = frozenset(
    {
        "GOOD_PROCESS_WIN",
        "GOOD_PROCESS_LOSS",
        "BAD_PROCESS_WIN",
        "BAD_PROCESS_LOSS",
        "UNDETERMINED",
    }
)

RUNNER_STATUSES: frozenset[str] = frozenset(
    {
        "NO_RUNNER",
        "RUNNER_OPEN",
        "RUNNER_CLOSED",
        "RUNNER_STOPPED",
    }
)

# Mapping from richer post_trade_outcome → legacy WIN/LOSS/BREAKEVEN/UNKNOWN
# accepted by the existing reconciliation_results.outcome_status column.  This
# preserves the existing schema + downstream learning aggregations without
# requiring a destructive migration.
OUTCOME_TO_LEGACY_STATUS: dict[str, str] = {
    "CLOSED_WIN": "WIN",
    "CLOSED_LOSS": "LOSS",
    "STOPPED_OUT": "LOSS",
    "BREAKEVEN": "BREAKEVEN",
    "MANUAL_EXIT": "UNKNOWN",
    "TIMEOUT_EXIT": "UNKNOWN",
    "PARTIAL_TP": "UNKNOWN",
    "OPEN": "UNKNOWN",
    "CANCELLED_DUPLICATE": "UNKNOWN",
}

# Reconciliation statuses that should remove a row from "Awaiting" because
# the operator already cancelled it (record-keeping only).
CANCELLED_RECONCILIATION_STATUSES: frozenset[str] = frozenset(
    {"CANCELLED_LOG", "CANCELLED_DUPLICATE"}
)

# Statuses that mean the trade is fully reconciled (Moltbook-eligible).
FULLY_RECONCILED_STATUSES: frozenset[str] = frozenset({"RECONCILED"})

# Default canned text + plan literals.
DEFAULT_TAKE_PROFIT_PLAN: str = "70% TP / 30% runner"
DEFAULT_CANCEL_NOTE: str = (
    "Duplicate manual log; broker API not called; "
    "AI executions = 0; exclude from P/L and exposure."
)

# Quantity precision used by the rest of the codebase (4 d.p. matches
# the `qty=2.5830` fixtures the spec calls out).
QUANTITY_PRECISION: int = 4

# Locked safety stamps surfaced on every outcome payload.
SAFETY_STAMPS: dict[str, Any] = {
    "advisory_status": "ADVISORY_ONLY",
    "execution_gate": "LOCKED",
    "execution_mode": "HUMAN_ONLY",
    "broker_api_called": False,
    "broker_order_id": "NONE",
    "ai_execution_count": 0,
    "human_review_required": True,
    "execution_permission": False,
    "can_execute": False,
    "record_keeping_only": True,
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if out != out or out in (float("inf"), float("-inf")):  # NaN / inf
        return default
    return out


# ---------------------------------------------------------------------------
# Enum normalisers
# ---------------------------------------------------------------------------


def _normalize_to_enum(value: Any, allowed: frozenset[str], default: str) -> str:
    if value is None:
        return default
    text = str(value).strip().upper()
    if not text:
        return default
    return text if text in allowed else default


def normalize_post_trade_outcome(value: Any) -> str:
    return _normalize_to_enum(value, POST_TRADE_OUTCOMES, "OPEN")


def normalize_reconciliation_status(value: Any) -> str:
    return _normalize_to_enum(
        value, RECONCILIATION_STATUSES, "AWAITING_RECONCILIATION"
    )


def normalize_outcome_quality(value: Any) -> str:
    return _normalize_to_enum(value, OUTCOME_QUALITIES, "")


def normalize_runner_status(value: Any) -> str:
    return _normalize_to_enum(value, RUNNER_STATUSES, "NO_RUNNER")


# ---------------------------------------------------------------------------
# 70 / 30 partial-TP default split
# ---------------------------------------------------------------------------


def split_quantity_70_30(
    total_quantity: float,
    *,
    tp_fraction: float = 0.70,
    precision: int = QUANTITY_PRECISION,
) -> dict[str, float]:
    """Default 70/30 partial-TP / runner split.

    To avoid rounding drift the runner is computed as ``Q - tp`` rather
    than ``Q * (1 - tp_fraction)`` — this guarantees ``tp + runner == Q``
    at the configured precision, matching the project quantity formatting.
    """
    qty = max(0.0, _safe_float(total_quantity))
    tp = round(qty * tp_fraction, precision)
    if tp > qty:  # fraction > 1, defensive
        tp = qty
    runner = round(qty - tp, precision)
    if runner < 0:
        runner = 0.0
    return {
        "total_quantity": round(qty, precision),
        "partial_take_profit_quantity": tp,
        "runner_quantity": runner,
        "tp_fraction": tp_fraction,
    }


# ---------------------------------------------------------------------------
# Realized P/L (long-only by design — matches the current MVP scope)
# ---------------------------------------------------------------------------


def compute_realized_pnl_long(
    *,
    entry_price: float,
    exit_price: float,
    exit_quantity: float,
    leverage: float | None = 1.0,
    apply_leverage_multiplier: bool = False,
) -> float:
    """Long-side realized P/L.

        realized_pnl = (exit_price - entry_price) * exit_quantity

    ``apply_leverage_multiplier`` is False by default: in this MVP the
    logged ``quantity`` already represents the leveraged notional
    exposure, so applying leverage again would double-count.  The flag
    exists only so callers that store base (un-leveraged) quantity can
    opt in explicitly.
    """
    entry = _safe_float(entry_price)
    exit_p = _safe_float(exit_price)
    qty = _safe_float(exit_quantity)
    if qty <= 0:
        return 0.0
    pnl = (exit_p - entry) * qty
    if apply_leverage_multiplier:
        lev = max(1.0, _safe_float(leverage, default=1.0))
        pnl = pnl * lev
    return round(pnl, 4)


# ---------------------------------------------------------------------------
# Structured outcome payload
# ---------------------------------------------------------------------------


def build_outcome_payload(
    *,
    trade_id: str,
    post_trade_outcome: str,
    actual_exit_price: float,
    exit_quantity: float,
    entry_price: float,
    entry_quantity: float,
    leverage: float | None = 1.0,
    reconciliation_status: str | None = None,
    outcome_quality: str = "",
    mistake_tags: str = "",
    lesson_takeaway: str = "",
    notes: str = "",
    invalidation_level: str = "",
    stop_loss_price: float | None = None,
    stop_loss_hit: bool = False,
    exit_reason: str = "",
    partial_take_profit_price: float | None = None,
    partial_take_profit_quantity: float | None = None,
    runner_quantity: float | None = None,
    runner_status: str | None = None,
    take_profit_plan: str = DEFAULT_TAKE_PROFIT_PLAN,
    apply_leverage_multiplier: bool = False,
) -> dict[str, Any]:
    """Build a structured reconciliation outcome dict.

    The returned dict is what reconcile_trade in signal_inbox_api.py
    serialises into ``outcome_notes`` (so the existing schema does not
    need to grow per-field columns) AND surfaces back to the API caller
    so the frontend can display realized P/L without parsing JSON itself.
    """
    outcome = normalize_post_trade_outcome(post_trade_outcome)

    # Auto-derive reconciliation_status if the caller did not specify one.
    if reconciliation_status is None:
        if outcome == "PARTIAL_TP":
            reconciliation_status = "PARTIAL_RECONCILED"
        elif outcome in {
            "CLOSED_WIN", "CLOSED_LOSS", "BREAKEVEN", "STOPPED_OUT",
            "MANUAL_EXIT", "TIMEOUT_EXIT",
        }:
            reconciliation_status = "RECONCILED"
        elif outcome == "CANCELLED_DUPLICATE":
            reconciliation_status = "CANCELLED_DUPLICATE"
        else:
            reconciliation_status = "AWAITING_RECONCILIATION"
    recon_status = normalize_reconciliation_status(reconciliation_status)

    qty = _safe_float(exit_quantity)
    realized = compute_realized_pnl_long(
        entry_price=entry_price,
        exit_price=actual_exit_price,
        exit_quantity=qty,
        leverage=leverage,
        apply_leverage_multiplier=apply_leverage_multiplier,
    )

    entry_q = max(0.0, _safe_float(entry_quantity))
    remaining = max(0.0, round(entry_q - qty, QUANTITY_PRECISION))

    runner_q: float
    if runner_quantity is None:
        if outcome == "PARTIAL_TP" and qty > 0 and entry_q > 0:
            runner_q = max(0.0, round(entry_q - qty, QUANTITY_PRECISION))
        else:
            runner_q = 0.0
    else:
        runner_q = max(0.0, round(_safe_float(runner_quantity), QUANTITY_PRECISION))

    if runner_status is None:
        if outcome == "PARTIAL_TP" and runner_q > 0:
            normalized_runner_status = "RUNNER_OPEN"
        elif outcome == "STOPPED_OUT" and runner_q > 0:
            normalized_runner_status = "RUNNER_STOPPED"
        elif outcome in {"CLOSED_WIN", "CLOSED_LOSS", "BREAKEVEN", "MANUAL_EXIT", "TIMEOUT_EXIT"}:
            normalized_runner_status = "RUNNER_CLOSED" if runner_q > 0 else "NO_RUNNER"
        else:
            normalized_runner_status = "NO_RUNNER"
    else:
        normalized_runner_status = normalize_runner_status(runner_status)

    payload: dict[str, Any] = {
        "trade_id": trade_id,
        "post_trade_outcome": outcome,
        "reconciliation_status": recon_status,
        "outcome_quality": normalize_outcome_quality(outcome_quality),
        "actual_exit_price": round(_safe_float(actual_exit_price), 6),
        "fill_price": round(_safe_float(actual_exit_price), 6),
        "exit_quantity": round(qty, QUANTITY_PRECISION),
        "remaining_quantity": remaining,
        "entry_price": round(_safe_float(entry_price), 6),
        "entry_quantity": round(entry_q, QUANTITY_PRECISION),
        "leverage": max(1.0, _safe_float(leverage, default=1.0)),
        "realized_pnl": realized,
        "partial_take_profit_price": (
            None if partial_take_profit_price is None
            else round(_safe_float(partial_take_profit_price), 6)
        ),
        "partial_take_profit_quantity": (
            None if partial_take_profit_quantity is None
            else round(_safe_float(partial_take_profit_quantity), QUANTITY_PRECISION)
        ),
        "runner_quantity": runner_q,
        "runner_status": normalized_runner_status,
        "take_profit_plan": str(take_profit_plan or DEFAULT_TAKE_PROFIT_PLAN),
        "stop_loss_price": (
            None if stop_loss_price is None
            else round(_safe_float(stop_loss_price), 6)
        ),
        "stop_loss_hit": bool(stop_loss_hit),
        "exit_reason": str(exit_reason or ""),
        "invalidation_level": str(invalidation_level or ""),
        "mistake_tags": str(mistake_tags or ""),
        "lesson_takeaway": str(lesson_takeaway or ""),
        "notes": str(notes or ""),
    }
    payload.update(SAFETY_STAMPS)
    return payload


def serialize_outcome_for_notes(outcome: dict[str, Any], operator_notes: str = "") -> str:
    """Produce the string written into reconciliation_results.outcome_notes.

    Format: ``operator_notes`` then a tagged JSON tail
    ``[reconciliation_extras=<json>]`` so downstream tools can recover the
    structured outcome without another schema migration.  The tag is
    deliberately ASCII / single-line so JSONL aggregation stays clean.
    """
    sanitised = {k: v for k, v in outcome.items() if not k.startswith("_")}
    encoded = json.dumps(sanitised, separators=(",", ":"), default=str)
    head = (operator_notes or "").rstrip()
    if head:
        return f"{head}\n[reconciliation_extras={encoded}]"
    return f"[reconciliation_extras={encoded}]"


def parse_outcome_from_notes(notes: str) -> dict[str, Any] | None:
    """Inverse of serialize_outcome_for_notes.  Returns None when the tag
    is absent or malformed.  Never raises."""
    if not notes:
        return None
    try:
        marker = "[reconciliation_extras="
        idx = notes.find(marker)
        if idx == -1:
            return None
        end = notes.rfind("]")
        if end <= idx + len(marker):
            return None
        encoded = notes[idx + len(marker):end]
        parsed = json.loads(encoded)
        if isinstance(parsed, dict):
            return parsed
        return None
    except (ValueError, TypeError):
        return None


__all__ = [
    "POST_TRADE_OUTCOMES",
    "RECONCILIATION_STATUSES",
    "OUTCOME_QUALITIES",
    "RUNNER_STATUSES",
    "OUTCOME_TO_LEGACY_STATUS",
    "CANCELLED_RECONCILIATION_STATUSES",
    "FULLY_RECONCILED_STATUSES",
    "DEFAULT_TAKE_PROFIT_PLAN",
    "DEFAULT_CANCEL_NOTE",
    "QUANTITY_PRECISION",
    "SAFETY_STAMPS",
    "split_quantity_70_30",
    "compute_realized_pnl_long",
    "normalize_post_trade_outcome",
    "normalize_reconciliation_status",
    "normalize_outcome_quality",
    "normalize_runner_status",
    "build_outcome_payload",
    "serialize_outcome_for_notes",
    "parse_outcome_from_notes",
]
