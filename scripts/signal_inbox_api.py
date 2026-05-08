"""
Signal Inbox and Reflection Desk — frontend-facing API contract (backend layer).

Design contract
---------------
- ALL outputs carry advisory_status="ADVISORY_ONLY" and human_review_required=True.
- execution_mode="HUMAN_ONLY" on every trade-related response.
- ai_execution_count is always 0.  Never increment it.
- No broker order placement.  No broker API connections.
- Manual trade log only.
- This module never modifies SCM policy, paper-execution ledgers, or any
  execution-path artifacts.

Public API (8 operations)
--------------------------
1.  list_inbox_items()                  -> dict  (list of inbox items)
2.  get_signal_detail(event_id)         -> dict
3.  run_validation(event_id)            -> dict
4.  add_user_reflection(...)            -> dict
5.  add_ai_discussion_summary(...)      -> dict
6.  mark_signal(event_id, status)       -> dict  (rejected/watchlist/human_review)
7.  log_manual_trade(...)               -> dict  (HUMAN_ONLY; no broker call)
8.  reconcile_trade(trade_id, ...)      -> dict
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    from scripts.runtime_common import LOG_DIR, append_jsonl, utc_timestamp
    from scripts.global_signal_fabric import build_global_signal_fabric_report
except ModuleNotFoundError:
    from runtime_common import LOG_DIR, append_jsonl, utc_timestamp  # type: ignore[no-redef]
    from global_signal_fabric import build_global_signal_fabric_report  # type: ignore[no-redef]

# ---------------------------------------------------------------------------
# Storage paths — append-only JSONL logs
# ---------------------------------------------------------------------------

INBOX_STATES_LOG: Path = LOG_DIR / "signal_inbox_states.jsonl"
REFLECTIONS_LOG: Path = LOG_DIR / "user_reflections.jsonl"
AI_SUMMARIES_LOG: Path = LOG_DIR / "ai_discussion_summaries.jsonl"
MANUAL_TRADE_LOG: Path = LOG_DIR / "manual_trade_log.jsonl"
RECONCILIATIONS_LOG: Path = LOG_DIR / "trade_reconciliations.jsonl"

# ---------------------------------------------------------------------------
# Advisory stamp constants — never change these
# ---------------------------------------------------------------------------

_ADVISORY_STATUS = "ADVISORY_ONLY"
_EXECUTION_GATE = "LOCKED"
_EXECUTION_MODE = "HUMAN_ONLY"
_AI_EXECUTION_COUNT = 0

VALID_USER_STATUSES: frozenset[str] = frozenset(
    {"pending", "watchlist", "human_review", "rejected"}
)
VALID_RECONCILIATION_STATUSES: frozenset[str] = frozenset(
    {"WIN", "LOSS", "BREAKEVEN", "UNKNOWN"}
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class InboxItem:
    event_id: str
    ticker: str
    signal_state: str
    entry_type: str
    priority_score: float
    observed_at: str
    source_file: str
    rejection_dimensions: list[str]
    rejection_reason: str
    persistence_score: float
    blocker_pressure_score: float
    kill_rate_score: float
    blocker_attribution: str
    user_status: str = "pending"
    has_reflection: bool = False
    has_ai_summary: bool = False
    advisory_status: str = _ADVISORY_STATUS
    human_review_required: bool = True
    execution_mode: str = _EXECUTION_MODE
    ai_execution_count: int = _AI_EXECUTION_COUNT

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ValidationResult:
    event_id: str
    validated_at: str
    validation_checks: dict[str, bool]
    validation_passed: bool
    validation_notes: list[str]
    advisory_status: str = _ADVISORY_STATUS
    human_review_required: bool = True
    execution_gate: str = _EXECUTION_GATE

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ManualTradeLog:
    trade_id: str
    event_id: str
    ticker: str
    side: str
    quantity: float
    price: float
    executed_at: str
    thesis: str
    notes: str
    logged_by: str
    execution_mode: str = _EXECUTION_MODE
    ai_execution_count: int = _AI_EXECUTION_COUNT
    advisory_status: str = _ADVISORY_STATUS
    human_review_required: bool = True
    broker_order_id: str = "NONE"
    broker_api_called: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TradeReconciliation:
    reconciliation_id: str
    trade_id: str
    event_id: str
    reconciled_at: str
    actual_fill_price: float
    actual_quantity: float
    outcome_notes: str
    pnl_estimate: float
    outcome_status: str
    execution_mode: str = _EXECUTION_MODE
    ai_execution_count: int = _AI_EXECUTION_COUNT
    advisory_status: str = _ADVISORY_STATUS
    human_review_required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                rows.append(parsed)
        except json.JSONDecodeError:
            continue
    return rows


def _build_inbox_overlay() -> dict[str, dict[str, Any]]:
    overlay: dict[str, dict[str, Any]] = {}
    for row in _load_jsonl(INBOX_STATES_LOG):
        eid = str(row.get("event_id", ""))
        if eid:
            overlay[eid] = row
    return overlay


def _has_reflection(event_id: str) -> bool:
    return any(r.get("event_id") == event_id for r in _load_jsonl(REFLECTIONS_LOG))


def _has_ai_summary(event_id: str) -> bool:
    return any(r.get("event_id") == event_id for r in _load_jsonl(AI_SUMMARIES_LOG))


def _build_item_from_event(
    event_dict: dict[str, Any],
    overlay: dict[str, dict[str, Any]],
) -> InboxItem:
    event_id = str(event_dict.get("signal_id", ""))
    state = overlay.get(event_id, {})
    return InboxItem(
        event_id=event_id,
        ticker=str(event_dict.get("ticker", "")),
        signal_state=str(event_dict.get("signal_state", "UNKNOWN")),
        entry_type=str(event_dict.get("entry_type", "UNKNOWN")),
        priority_score=float(event_dict.get("priority_score", 0.0)),
        observed_at=str(event_dict.get("observed_at", "")),
        source_file=str(event_dict.get("source_file", "")),
        rejection_dimensions=list(event_dict.get("rejection_dimensions", [])),
        rejection_reason=str(event_dict.get("rejection_reason", "")),
        persistence_score=float(event_dict.get("persistence_score", 0.0)),
        blocker_pressure_score=float(event_dict.get("blocker_pressure_score", 0.0)),
        kill_rate_score=float(event_dict.get("kill_rate_score", 0.0)),
        blocker_attribution=str(event_dict.get("blocker_attribution", "NONE")),
        user_status=str(state.get("user_status", "pending")),
        has_reflection=_has_reflection(event_id),
        has_ai_summary=_has_ai_summary(event_id),
    )


def _error_response(operation: str, message: str) -> dict[str, Any]:
    return {
        "operation": operation,
        "error": message,
        "advisory_status": _ADVISORY_STATUS,
        "human_review_required": True,
        "execution_mode": _EXECUTION_MODE,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "generated_at": utc_timestamp(),
    }


def _ticker_summary_to_event_dict(ts: dict[str, Any]) -> dict[str, Any]:
    return {
        "signal_id": f"FABRIC_{ts['ticker']}",
        "ticker": ts["ticker"],
        "signal_state": ts.get("latest_signal_state", "UNKNOWN"),
        "entry_type": "UNKNOWN",
        "priority_score": ts.get("persistence_score", 0.0),
        "observed_at": ts.get("latest_observed_at", ""),
        "source_file": ",".join(sorted(ts.get("source_files", []))),
        "rejection_dimensions": [],
        "rejection_reason": "",
        "persistence_score": ts.get("persistence_score", 0.0),
        "blocker_pressure_score": ts.get("blocker_pressure_score", 0.0),
        "kill_rate_score": ts.get("kill_rate_score", 0.0),
        "blocker_attribution": ts.get("latest_blocker", "NONE"),
    }


# ---------------------------------------------------------------------------
# Public API: 8 operations
# ---------------------------------------------------------------------------


def list_inbox_items(*, write_runtime: bool = False) -> dict[str, Any]:
    """1. List all signal inbox items with advisory metadata.

    Reads from the global signal fabric (read-only) and overlays persisted
    user state. Returns a JSON-serializable dict for a Next.js frontend.
    advisory_status="ADVISORY_ONLY" and ai_execution_count=0 on every item.
    """
    report = build_global_signal_fabric_report(write_runtime=write_runtime)
    overlay = _build_inbox_overlay()
    items = [
        _build_item_from_event(_ticker_summary_to_event_dict(ts), overlay).to_dict()
        for ts in report.get("ticker_summaries", [])
    ]
    return {
        "operation": "list_inbox_items",
        "item_count": len(items),
        "items": items,
        "fabric_bull_state": (
            report.get("fabric_bull_state_context", {}).get("fabric_bull_state", "UNKNOWN")
        ),
        "fabric_stats": report.get("fabric_stats", {}),
        "advisory_status": _ADVISORY_STATUS,
        "human_review_required": True,
        "execution_mode": _EXECUTION_MODE,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "generated_at": utc_timestamp(),
    }


def get_signal_detail(event_id: str) -> dict[str, Any]:
    """2. Get full signal detail by event_id."""
    if not event_id or not isinstance(event_id, str):
        return _error_response("get_signal_detail", "event_id must be a non-empty string")

    report = build_global_signal_fabric_report(write_runtime=False)
    ticker = event_id.removeprefix("FABRIC_") if event_id.startswith("FABRIC_") else event_id

    ticker_summary: dict[str, Any] = next(
        (ts for ts in report.get("ticker_summaries", []) if ts.get("ticker") == ticker),
        {},
    )
    event_dict = _ticker_summary_to_event_dict(
        ticker_summary if ticker_summary else {"ticker": ticker}
    )
    event_dict["signal_id"] = event_id

    overlay = _build_inbox_overlay()
    item = _build_item_from_event(event_dict, overlay)
    reflections = [r for r in _load_jsonl(REFLECTIONS_LOG) if r.get("event_id") == event_id]
    ai_summaries = [s for s in _load_jsonl(AI_SUMMARIES_LOG) if s.get("event_id") == event_id]
    manual_trades = [t for t in _load_jsonl(MANUAL_TRADE_LOG) if t.get("event_id") == event_id]

    return {
        "operation": "get_signal_detail",
        "event_id": event_id,
        "signal": item.to_dict(),
        "ticker_summary": ticker_summary,
        "reflections": reflections,
        "ai_summaries": ai_summaries,
        "manual_trades": manual_trades,
        "advisory_status": _ADVISORY_STATUS,
        "human_review_required": True,
        "execution_mode": _EXECUTION_MODE,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "generated_at": utc_timestamp(),
    }


def run_validation(event_id: str) -> dict[str, Any]:
    """3. Run advisory validation checks for a signal.

    Returns a ValidationResult dict.  A passing result does NOT authorize
    execution — it is observational context only.
    """
    if not event_id or not isinstance(event_id, str):
        return _error_response("run_validation", "event_id must be a non-empty string")

    report = build_global_signal_fabric_report(write_runtime=False)
    ticker = event_id.removeprefix("FABRIC_") if event_id.startswith("FABRIC_") else event_id

    ticker_summary: dict[str, Any] = next(
        (ts for ts in report.get("ticker_summaries", []) if ts.get("ticker") == ticker),
        {},
    )

    checks: dict[str, bool] = {
        "has_ticker": bool(ticker),
        "found_in_fabric": bool(ticker_summary),
        "has_priority_score": float(ticker_summary.get("persistence_score", 0.0)) > 0,
        "state_not_rejected": ticker_summary.get("latest_signal_state") != "REJECTED",
        "kill_rate_below_threshold": float(ticker_summary.get("kill_rate_score", 1.0)) < 0.8,
        "blocker_pressure_manageable": (
            float(ticker_summary.get("blocker_pressure_score", 1.0)) < 0.9
        ),
    }

    notes: list[str] = []
    if not checks["found_in_fabric"]:
        notes.append(f"Ticker {ticker!r} not found in current fabric window")
    if not checks["state_not_rejected"]:
        notes.append("Signal is in REJECTED state — human review required before any action")
    if not checks["kill_rate_below_threshold"]:
        notes.append("Kill rate >= 0.8 — high rejection history; proceed with extra caution")
    if not checks["blocker_pressure_manageable"]:
        notes.append("Blocker pressure >= 0.9 — multiple active blockers observed")
    if not notes:
        notes.append(
            "All advisory checks passed — human decision and manual logging still required"
        )

    result = ValidationResult(
        event_id=event_id,
        validated_at=utc_timestamp(),
        validation_checks=checks,
        validation_passed=all(checks.values()),
        validation_notes=notes,
    )
    return {
        "operation": "run_validation",
        "validation": result.to_dict(),
        "advisory_note": (
            "Validation is advisory only. A passing result does NOT authorize execution. "
            "All trades require a human decision and manual logging."
        ),
        "advisory_status": _ADVISORY_STATUS,
        "human_review_required": True,
        "execution_mode": _EXECUTION_MODE,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "generated_at": utc_timestamp(),
    }


def add_user_reflection(
    event_id: str,
    reflection_text: str,
    *,
    author: str = "human",
    conviction_level: str = "MODERATE",
) -> dict[str, Any]:
    """4. Add a human reflection/note to a signal."""
    if not event_id or not isinstance(event_id, str):
        return _error_response("add_user_reflection", "event_id must be a non-empty string")
    if not reflection_text or not isinstance(reflection_text, str):
        return _error_response(
            "add_user_reflection", "reflection_text must be a non-empty string"
        )

    entry: dict[str, Any] = {
        "reflection_id": f"REF_{uuid.uuid4().hex[:10]}",
        "event_id": event_id,
        "author": str(author),
        "conviction_level": str(conviction_level).upper(),
        "reflection_text": str(reflection_text),
        "reflected_at": utc_timestamp(),
        "advisory_status": _ADVISORY_STATUS,
        "human_review_required": True,
        "execution_mode": _EXECUTION_MODE,
        "ai_execution_count": _AI_EXECUTION_COUNT,
    }
    append_jsonl(REFLECTIONS_LOG, entry, stamp=False)

    return {
        "operation": "add_user_reflection",
        "reflection_id": entry["reflection_id"],
        "event_id": event_id,
        "status": "logged",
        "advisory_status": _ADVISORY_STATUS,
        "human_review_required": True,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "generated_at": utc_timestamp(),
    }


def add_ai_discussion_summary(
    event_id: str,
    summary_text: str,
    *,
    model_label: str = "AI_ADVISORY",
) -> dict[str, Any]:
    """5. Add an AI discussion summary to a signal (advisory, not a recommendation)."""
    if not event_id or not isinstance(event_id, str):
        return _error_response(
            "add_ai_discussion_summary", "event_id must be a non-empty string"
        )
    if not summary_text or not isinstance(summary_text, str):
        return _error_response(
            "add_ai_discussion_summary", "summary_text must be a non-empty string"
        )

    entry: dict[str, Any] = {
        "summary_id": f"SUM_{uuid.uuid4().hex[:10]}",
        "event_id": event_id,
        "model_label": str(model_label),
        "summary_text": str(summary_text),
        "summarized_at": utc_timestamp(),
        "advisory_status": _ADVISORY_STATUS,
        "human_review_required": True,
        "execution_mode": _EXECUTION_MODE,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "advisory_note": (
            "AI-generated discussion context only — not a trade recommendation "
            "and does not authorize any execution."
        ),
    }
    append_jsonl(AI_SUMMARIES_LOG, entry, stamp=False)

    return {
        "operation": "add_ai_discussion_summary",
        "summary_id": entry["summary_id"],
        "event_id": event_id,
        "status": "logged",
        "advisory_status": _ADVISORY_STATUS,
        "human_review_required": True,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "generated_at": utc_timestamp(),
    }


def mark_signal(event_id: str, status: str) -> dict[str, Any]:
    """6. Mark a signal as rejected / watchlist / human_review / pending."""
    if not event_id or not isinstance(event_id, str):
        return _error_response("mark_signal", "event_id must be a non-empty string")
    normalized = str(status).lower().strip()
    if normalized not in VALID_USER_STATUSES:
        return _error_response(
            "mark_signal",
            f"status must be one of {sorted(VALID_USER_STATUSES)}, got {status!r}",
        )

    entry: dict[str, Any] = {
        "event_id": event_id,
        "user_status": normalized,
        "marked_at": utc_timestamp(),
        "advisory_status": _ADVISORY_STATUS,
        "human_review_required": True,
    }
    append_jsonl(INBOX_STATES_LOG, entry, stamp=False)

    return {
        "operation": "mark_signal",
        "event_id": event_id,
        "user_status": normalized,
        "status": "logged",
        "advisory_status": _ADVISORY_STATUS,
        "human_review_required": True,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "generated_at": utc_timestamp(),
    }


def log_manual_trade(
    *,
    event_id: str,
    ticker: str,
    side: str,
    quantity: float,
    price: float,
    thesis: str,
    notes: str = "",
    logged_by: str = "human",
) -> dict[str, Any]:
    """7. Log a manual trade execution (HUMAN_ONLY; no broker API called).

    This is a record-keeping function only.  It does NOT place, route, or
    submit any order to any broker or exchange.  broker_api_called is always
    False.  ai_execution_count is always 0.
    """
    if not event_id or not isinstance(event_id, str):
        return _error_response("log_manual_trade", "event_id must be a non-empty string")
    if not ticker or not isinstance(ticker, str):
        return _error_response("log_manual_trade", "ticker must be a non-empty string")
    if str(side).upper() not in {"BUY", "SELL"}:
        return _error_response("log_manual_trade", "side must be BUY or SELL")
    if isinstance(quantity, bool) or not isinstance(quantity, (int, float)) or quantity <= 0:
        return _error_response("log_manual_trade", "quantity must be a positive number")
    if isinstance(price, bool) or not isinstance(price, (int, float)) or price <= 0:
        return _error_response("log_manual_trade", "price must be a positive number")

    trade = ManualTradeLog(
        trade_id=f"MT_{uuid.uuid4().hex[:12]}",
        event_id=str(event_id),
        ticker=str(ticker).upper(),
        side=str(side).upper(),
        quantity=float(quantity),
        price=float(price),
        executed_at=utc_timestamp(),
        thesis=str(thesis),
        notes=str(notes),
        logged_by=str(logged_by),
    )
    append_jsonl(MANUAL_TRADE_LOG, trade.to_dict(), stamp=False)

    return {
        "operation": "log_manual_trade",
        "trade_id": trade.trade_id,
        "event_id": event_id,
        "ticker": trade.ticker,
        "side": trade.side,
        "quantity": trade.quantity,
        "price": trade.price,
        "status": "logged",
        "execution_mode": _EXECUTION_MODE,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "broker_api_called": False,
        "broker_order_id": "NONE",
        "advisory_status": _ADVISORY_STATUS,
        "human_review_required": True,
        "generated_at": utc_timestamp(),
    }


def reconcile_trade(
    trade_id: str,
    *,
    actual_fill_price: float,
    actual_quantity: float,
    outcome_notes: str = "",
    pnl_estimate: float = 0.0,
    outcome_status: str = "UNKNOWN",
) -> dict[str, Any]:
    """8. Reconcile a previously logged manual trade with its actual outcome."""
    if not trade_id or not isinstance(trade_id, str):
        return _error_response("reconcile_trade", "trade_id must be a non-empty string")

    event_id = next(
        (str(r.get("event_id", "")) for r in _load_jsonl(MANUAL_TRADE_LOG)
         if r.get("trade_id") == trade_id),
        "",
    )

    normalized_status = str(outcome_status).upper().strip()
    if normalized_status not in VALID_RECONCILIATION_STATUSES:
        normalized_status = "UNKNOWN"

    rec = TradeReconciliation(
        reconciliation_id=f"REC_{uuid.uuid4().hex[:12]}",
        trade_id=trade_id,
        event_id=event_id,
        reconciled_at=utc_timestamp(),
        actual_fill_price=float(actual_fill_price),
        actual_quantity=float(actual_quantity),
        outcome_notes=str(outcome_notes),
        pnl_estimate=float(pnl_estimate),
        outcome_status=normalized_status,
    )
    append_jsonl(RECONCILIATIONS_LOG, rec.to_dict(), stamp=False)

    return {
        "operation": "reconcile_trade",
        "reconciliation_id": rec.reconciliation_id,
        "trade_id": trade_id,
        "event_id": event_id,
        "outcome_status": normalized_status,
        "pnl_estimate": pnl_estimate,
        "status": "logged",
        "execution_mode": _EXECUTION_MODE,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "advisory_status": _ADVISORY_STATUS,
        "human_review_required": True,
        "generated_at": utc_timestamp(),
    }


__all__ = [
    "INBOX_STATES_LOG",
    "REFLECTIONS_LOG",
    "AI_SUMMARIES_LOG",
    "MANUAL_TRADE_LOG",
    "RECONCILIATIONS_LOG",
    "VALID_USER_STATUSES",
    "VALID_RECONCILIATION_STATUSES",
    "InboxItem",
    "ValidationResult",
    "ManualTradeLog",
    "TradeReconciliation",
    "list_inbox_items",
    "get_signal_detail",
    "run_validation",
    "add_user_reflection",
    "add_ai_discussion_summary",
    "mark_signal",
    "log_manual_trade",
    "reconcile_trade",
]
