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
    from scripts.signal_inbox_bridge import (
        DEFAULT_HOURS as _BRIDGE_DEFAULT_HOURS,
        DEFAULT_LIMIT as _BRIDGE_DEFAULT_LIMIT,
        build_inbox_diagnostics,
        compute_action_counts,
        promote_signal_events_to_inbox,
    )
    from scripts.ai_output_schema import (
        redact_secret_patterns,
        validate_ai_interpretation_payload,
    )
except ModuleNotFoundError:
    from runtime_common import LOG_DIR, append_jsonl, utc_timestamp  # type: ignore[no-redef]
    from global_signal_fabric import build_global_signal_fabric_report  # type: ignore[no-redef]
    from signal_inbox_bridge import (  # type: ignore[no-redef]
        DEFAULT_HOURS as _BRIDGE_DEFAULT_HOURS,
        DEFAULT_LIMIT as _BRIDGE_DEFAULT_LIMIT,
        build_inbox_diagnostics,
        compute_action_counts,
        promote_signal_events_to_inbox,
    )
    from ai_output_schema import (  # type: ignore[no-redef]
        redact_secret_patterns,
        validate_ai_interpretation_payload,
    )

# Optional SQLite persistence — falls back gracefully to JSONL if unavailable
_DB_AVAILABLE = False
_persistence = None
try:
    try:
        import scripts.persistence as _persistence
    except ModuleNotFoundError:
        import persistence as _persistence  # type: ignore[no-redef]
    _DB_AVAILABLE = True
except Exception:
    pass

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
    leverage: float = 1.0
    execution_mode: str = _EXECUTION_MODE
    ai_execution_count: int = _AI_EXECUTION_COUNT
    advisory_status: str = _ADVISORY_STATUS
    human_review_required: bool = True
    broker_order_id: str = "NONE"
    broker_api_called: bool = False
    # Operator-discipline / journal-quality fields. All optional, all
    # record-only — never grant execution permission.
    invalidation_level: str = ""
    expected_horizon: str = ""
    risk_reason: str = ""
    entry_reason: str = ""
    exit_plan: str = ""
    confidence_before: float | None = None
    emotional_state: str = ""
    mistake_tags: str = ""
    lesson: str = ""

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
    # Skill-vs-luck / skill-vs-process attribution fields. All optional.
    outcome_quality: str = ""
    process_error: str = ""
    process_error_notes: str = ""
    mistake_tags: str = ""
    lesson: str = ""

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
    if _DB_AVAILABLE and _persistence is not None:
        try:
            decisions = _persistence.get_all_signal_decisions()
            if decisions:
                return {eid: {"user_status": status} for eid, status in decisions.items()}
        except Exception:
            pass
    overlay: dict[str, dict[str, Any]] = {}
    for row in _load_jsonl(INBOX_STATES_LOG):
        eid = str(row.get("event_id", ""))
        if eid:
            overlay[eid] = row
    return overlay


def _has_reflection(event_id: str) -> bool:
    if _DB_AVAILABLE and _persistence is not None:
        try:
            return _persistence.has_reflection(event_id)
        except Exception:
            pass
    return any(r.get("event_id") == event_id for r in _load_jsonl(REFLECTIONS_LOG))


def _has_ai_summary(event_id: str) -> bool:
    if _DB_AVAILABLE and _persistence is not None:
        try:
            return _persistence.has_ai_summary(event_id)
        except Exception:
            pass
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


def _decorate_inbox_diagnostics(item: dict[str, Any]) -> dict[str, Any]:
    """Attach signal-sensitivity and toxic-quarantine diagnostics to an inbox item.

    All helpers are pure, deterministic, and never call live APIs.  If a
    helper raises or imports fail, the item is returned unchanged so the
    /signals endpoint never crashes because a diagnostic helper had a bad
    day.  No broker call, no execution permission added by this annotation.
    """
    try:
        try:
            from scripts.signal_sensitivity_diagnostics import (
                diagnose_signal_sensitivity,
            )
        except ModuleNotFoundError:
            from signal_sensitivity_diagnostics import (  # type: ignore[no-redef]
                diagnose_signal_sensitivity,
            )
        try:
            from scripts.toxic_signal_quarantine import classify_toxic_signal
        except ModuleNotFoundError:
            from toxic_signal_quarantine import classify_toxic_signal  # type: ignore[no-redef]
    except Exception:
        return item

    annotated = dict(item)

    try:
        sens = diagnose_signal_sensitivity(item)
        annotated["chaos_sensitivity_score"] = sens.get("chaos_sensitivity_score")
        annotated["classification_stability_score"] = sens.get(
            "classification_stability_score"
        )
        annotated["fragile"] = bool(sens.get("fragile", False))
        annotated["sensitivity_recommendation"] = sens.get("recommendation")
        annotated["baseline_classification"] = sens.get("baseline_classification")
    except Exception:
        annotated.setdefault("chaos_sensitivity_score", None)
        annotated.setdefault("classification_stability_score", None)
        annotated.setdefault("fragile", False)
        annotated.setdefault("sensitivity_recommendation", "not_applicable")

    try:
        tox = classify_toxic_signal(item)
        annotated["contamination_score"] = tox.get("contamination_score")
        annotated["toxic_quarantine_state"] = tox.get("toxic_quarantine_state")
        annotated["quarantine_reasons"] = list(tox.get("quarantine_reasons", []))
        annotated["promotion_allowed"] = bool(tox.get("promotion_allowed", True))
    except Exception:
        annotated.setdefault("contamination_score", None)
        annotated.setdefault("toxic_quarantine_state", "clean")
        annotated.setdefault("quarantine_reasons", [])
        annotated.setdefault("promotion_allowed", True)

    # AI validation status passthrough (already populated by the bridge in
    # some flows). We default to "not_applicable" so the badge layer has
    # a stable string to switch on.
    annotated.setdefault("ai_validation_status", item.get("ai_validation_status") or "not_applicable")

    # Re-stamp the canonical safety invariants. Diagnostic enrichment must
    # NEVER grant execution permission; we re-write the keys defensively in
    # case a helper returned something different.
    annotated["advisory_status"] = _ADVISORY_STATUS
    annotated["execution_gate"] = _EXECUTION_GATE
    annotated["broker_api_called"] = False
    annotated["ai_execution_count"] = _AI_EXECUTION_COUNT
    annotated["execution_permission"] = False
    annotated["can_execute"] = False
    return annotated


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


def list_inbox_items(
    *,
    write_runtime: bool = False,
    hours: int = _BRIDGE_DEFAULT_HOURS,
    limit: int = _BRIDGE_DEFAULT_LIMIT,
) -> dict[str, Any]:
    """1. List all signal inbox items with advisory metadata.

    Behaviour:
      1. First, promote fresh `signal_events` rows from SQLite (the table the
         Live Signals page reads) into InboxItem candidates via the bridge.
      2. If the bridge returns at least one candidate, those are the inbox.
         `signal_source = "live_events"`.
      3. Otherwise fall back to the legacy `global_signal_fabric` report so the
         inbox doesn't go blank in older environments.
         `signal_source = "legacy_fabric"`.

    advisory_status="ADVISORY_ONLY" and ai_execution_count=0 on every item.
    """
    overlay = _build_inbox_overlay()
    items: list[dict[str, Any]] = []
    signal_source = "legacy_fabric"

    if _DB_AVAILABLE and _persistence is not None:
        try:
            bridge_items = promote_signal_events_to_inbox(
                hours=hours,
                limit=limit,
                overlay=overlay,
                has_reflection_fn=_has_reflection,
                has_ai_summary_fn=_has_ai_summary,
            )
            if bridge_items:
                items = bridge_items
                signal_source = "live_events"
        except Exception:
            items = []

    fabric_bull_state = "UNKNOWN"
    fabric_stats: dict[str, Any] = {}
    if not items:
        report = build_global_signal_fabric_report(write_runtime=write_runtime)
        items = [
            _build_item_from_event(_ticker_summary_to_event_dict(ts), overlay).to_dict()
            for ts in report.get("ticker_summaries", [])
        ]
        fabric_bull_state = (
            report.get("fabric_bull_state_context", {}).get("fabric_bull_state", "UNKNOWN")
        )
        fabric_stats = dict(report.get("fabric_stats", {}))
    else:
        suppressed = sum(int(it.get("duplicate_suppressed_count", 0) or 0) for it in items)
        fabric_stats = {
            "promoted_candidate_count": len(items),
            "duplicate_suppressed_count": suppressed,
            "freshness_window_hours": int(hours),
            "limit": int(limit),
        }

    action_counts = compute_action_counts(items)

    # Decorate each inbox item with fragility + quarantine diagnostics so the
    # UI can render badges without re-fetching.  Pure helpers; never grant
    # execution permission.
    items = [_decorate_inbox_diagnostics(it) for it in items]

    # Per-list summary counts so a dashboard panel can show "5 fragile,
    # 2 quarantined" without re-scanning the list on the frontend.
    fragile_count = sum(1 for it in items if it.get("fragile"))
    quarantined_count = sum(
        1
        for it in items
        if it.get("toxic_quarantine_state") in {"quarantine", "block_from_promotion"}
    )

    # Persistence truth model (see docs/PERSISTENCE_MODEL.md):
    #   sqlite     -> canonical
    #   anything else -> not canonical; UI should surface a cue
    truth_source = "sqlite" if signal_source == "live_events" else "legacy_fabric"
    fallback_used = truth_source != "sqlite"
    canonical = truth_source == "sqlite"

    return {
        "operation": "list_inbox_items",
        "item_count": len(items),
        "items": items,
        "action_counts": action_counts,
        "fabric_bull_state": fabric_bull_state,
        "fabric_stats": fabric_stats,
        "signal_source": signal_source,
        "freshness_window_hours": int(hours),
        "mock_fallback": False,
        "truth_source": truth_source,
        "fallback_used": fallback_used,
        "canonical": canonical,
        "fragile_signal_count": fragile_count,
        "quarantined_signal_count": quarantined_count,
        "advisory_status": _ADVISORY_STATUS,
        "human_review_required": True,
        "execution_mode": _EXECUTION_MODE,
        "execution_gate": _EXECUTION_GATE,
        "execution_permission": False,
        "can_execute": False,
        "broker_api_called": False,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "generated_at": utc_timestamp(),
    }


def get_inbox_diagnostics(
    *,
    hours: int = _BRIDGE_DEFAULT_HOURS,
) -> dict[str, Any]:
    """Return a freshness + source-count diagnostic for the Signal Inbox.

    Exposed as GET /signals/diagnostics so operators can see at a glance
    whether the inbox has fresh data, what sources are contributing, and
    whether mock fallback is active (always False on the backend; the
    frontend may flip this when it can't reach the API).
    """
    return build_inbox_diagnostics(hours=hours)


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
    item_dict = _decorate_inbox_diagnostics(item.to_dict())

    reflections: list[dict[str, Any]] = []
    ai_summaries: list[dict[str, Any]] = []
    manual_trades: list[dict[str, Any]] = []
    if _DB_AVAILABLE and _persistence is not None:
        try:
            reflections = _persistence.get_reflections_for_event(event_id)
            ai_summaries = _persistence.get_ai_summaries_for_event(event_id)
            manual_trades = _persistence.get_trades_for_event(event_id)
        except Exception:
            pass
    if not reflections:
        reflections = [r for r in _load_jsonl(REFLECTIONS_LOG) if r.get("event_id") == event_id]
    if not ai_summaries:
        ai_summaries = [s for s in _load_jsonl(AI_SUMMARIES_LOG) if s.get("event_id") == event_id]
    if not manual_trades:
        manual_trades = [t for t in _load_jsonl(MANUAL_TRADE_LOG) if t.get("event_id") == event_id]

    return {
        "operation": "get_signal_detail",
        "event_id": event_id,
        "signal": item_dict,
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
    if _DB_AVAILABLE and _persistence is not None:
        try:
            _persistence.insert_reflection(
                entry["reflection_id"], event_id, str(author),
                str(conviction_level).upper(), str(reflection_text),
                entry["reflected_at"],
            )
        except Exception:
            pass

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
    ai_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """5. Add an AI discussion summary to a signal (advisory, not a recommendation).

    Every AI-originating string this function persists is first routed through
    :func:`scripts.ai_output_schema.validate_ai_interpretation_payload` so that:

    - the canonical safety stamps are locked (no broker call, no execution
      permission, ai_execution_count=0);
    - any secret-looking pattern in summary_text or raw_response is redacted
      *before* it lands on disk;
    - a ``validation_status`` is returned to the caller and persisted as part
      of the JSONL log entry so future readers can tell whether the summary
      was structurally clean, partially recovered, or invalid.

    ``ai_payload`` is an optional structured override. When supplied it is
    validated and ``summary_text`` is reconciled with the validated payload's
    summary field. Backwards-compatible: callers that only pass
    ``summary_text`` still work.
    """
    if not event_id or not isinstance(event_id, str):
        return _error_response(
            "add_ai_discussion_summary", "event_id must be a non-empty string"
        )
    if not summary_text or not isinstance(summary_text, str):
        return _error_response(
            "add_ai_discussion_summary", "summary_text must be a non-empty string"
        )

    base_payload: dict[str, Any] = {
        "model_name": None,
        "provider": None,
        "summary": str(summary_text),
        "raw_response": None,
    }
    if isinstance(ai_payload, dict):
        merged: dict[str, Any] = dict(ai_payload)
        # Caller-supplied summary takes precedence only if it is a non-empty
        # string; otherwise we keep the positional argument.
        candidate = merged.get("summary")
        if not isinstance(candidate, str) or not candidate.strip():
            merged["summary"] = str(summary_text)
        base_payload = merged
    elif ai_payload is not None:
        # Caller handed us something other than a dict — treat the whole
        # thing as raw_response so it still goes through redaction, and
        # record an explicit validation note.
        base_payload = {
            "summary": str(summary_text),
            "raw_response": ai_payload,
            "validation_status": "partial",
            "validation_errors": ["ai_payload_type_invalid"],
        }

    validated = validate_ai_interpretation_payload(base_payload)
    # The schema validator strips type/shape problems but does NOT redact
    # secret patterns from the summary field (only from raw_response and
    # validation_errors). Apply the same redaction at the persistence boundary
    # so a model that hallucinates an API key into prose cannot leak it.
    raw_clean = redact_secret_patterns(validated.get("summary") or str(summary_text))
    clean_summary = raw_clean or "<redacted-secret>"

    entry: dict[str, Any] = {
        "summary_id": f"SUM_{uuid.uuid4().hex[:10]}",
        "event_id": event_id,
        "model_label": redact_secret_patterns(str(model_label)) or "AI_ADVISORY",
        "summary_text": clean_summary,
        "summarized_at": utc_timestamp(),
        "advisory_status": _ADVISORY_STATUS,
        "human_review_required": True,
        "execution_mode": _EXECUTION_MODE,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "broker_api_called": False,
        "execution_permission": False,
        "can_execute": False,
        "validation_status": validated.get("validation_status", "valid"),
        "validation_errors": list(validated.get("validation_errors") or []),
        "prompt_version": validated.get("prompt_version"),
        "advisory_note": (
            "AI-generated discussion context only — not a trade recommendation "
            "and does not authorize any execution."
        ),
    }
    append_jsonl(AI_SUMMARIES_LOG, entry, stamp=False)
    if _DB_AVAILABLE and _persistence is not None:
        try:
            _persistence.insert_ai_summary(
                entry["summary_id"], event_id, entry["model_label"],
                clean_summary, entry["summarized_at"],
            )
        except Exception:
            pass

    return {
        "operation": "add_ai_discussion_summary",
        "summary_id": entry["summary_id"],
        "event_id": event_id,
        "status": "logged",
        "validation_status": entry["validation_status"],
        "validation_errors": entry["validation_errors"],
        "advisory_status": _ADVISORY_STATUS,
        "human_review_required": True,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "broker_api_called": False,
        "execution_permission": False,
        "can_execute": False,
        "execution_gate": _EXECUTION_GATE,
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
    if _DB_AVAILABLE and _persistence is not None:
        try:
            _persistence.insert_signal_decision(event_id, normalized, entry["marked_at"])
        except Exception:
            pass

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


_LEVERAGE_MIN = 1.0
_LEVERAGE_MAX = 25.0

# Cap on freeform text fields so a hostile or careless client can't fill the
# DB.  This is the same intent as the existing thesis/notes upper bound the
# frontend implicitly enforces — applied at the persistence boundary as belt-
# and-braces.  The numbers are deliberately generous; the goal is "no abuse",
# not "trim user prose".
_JOURNAL_TEXT_MAX = 2000


def _safe_journal_text(value: Any) -> str:
    """Coerce arbitrary journal-text input to a bounded safe string.

    None / non-string -> empty string.  Strings are stripped and truncated to
    ``_JOURNAL_TEXT_MAX``.  No HTML / SQL escaping (SQLite parametrisation
    handles the latter; the former is the frontend's responsibility).
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        try:
            value = str(value)
        except Exception:
            return ""
    cleaned = value.strip()
    if len(cleaned) > _JOURNAL_TEXT_MAX:
        cleaned = cleaned[:_JOURNAL_TEXT_MAX]
    return cleaned


def _safe_confidence_before(value: Any) -> float | None:
    """Mirror the persistence-layer normaliser at the API boundary.

    Accepts None, fraction in [0, 1], or percentage in [0, 100].  Anything
    else returns None.  Never raises.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if n != n:
        return None
    if n < 0.0 or n > 100.0:
        return None
    return n


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
    leverage: float = 1.0,
    invalidation_level: str = "",
    expected_horizon: str = "",
    risk_reason: str = "",
    entry_reason: str = "",
    exit_plan: str = "",
    confidence_before: float | None = None,
    emotional_state: str = "",
    mistake_tags: str = "",
    lesson: str = "",
) -> dict[str, Any]:
    """7. Log a manual trade execution (HUMAN_ONLY; no broker API called).

    This is a record-keeping function only.  It does NOT place, route, or
    submit any order to any broker or exchange.  broker_api_called is always
    False.  ai_execution_count is always 0.

    leverage is a numeric record-only field (e.g. 1.0x, 2.5x).  It must be
    >= 1.0 and <= 25.0.  Missing / null defaults to 1.0.  Storing leverage
    here does NOT enable any broker margin behaviour — this remains pure
    record-keeping.

    The operator-discipline keyword args
    (invalidation_level, expected_horizon, risk_reason, entry_reason,
    exit_plan, confidence_before, emotional_state, mistake_tags, lesson)
    are optional journal-quality fields.  Bad / unknown payloads degrade
    silently to empty strings or NULL — they never reject the log.
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

    if leverage is None:
        leverage_val = 1.0
    elif isinstance(leverage, bool) or not isinstance(leverage, (int, float)):
        return _error_response(
            "log_manual_trade", "leverage must be a number (e.g. 1.0, 2.5)"
        )
    else:
        leverage_val = float(leverage)
    if leverage_val < _LEVERAGE_MIN or leverage_val > _LEVERAGE_MAX:
        return _error_response(
            "log_manual_trade",
            f"leverage must be between {_LEVERAGE_MIN} and {_LEVERAGE_MAX}",
        )

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
        leverage=leverage_val,
        invalidation_level=_safe_journal_text(invalidation_level),
        expected_horizon=_safe_journal_text(expected_horizon),
        risk_reason=_safe_journal_text(risk_reason),
        entry_reason=_safe_journal_text(entry_reason),
        exit_plan=_safe_journal_text(exit_plan),
        confidence_before=_safe_confidence_before(confidence_before),
        emotional_state=_safe_journal_text(emotional_state),
        mistake_tags=_safe_journal_text(mistake_tags),
        lesson=_safe_journal_text(lesson),
    )
    append_jsonl(MANUAL_TRADE_LOG, trade.to_dict(), stamp=False)
    if _DB_AVAILABLE and _persistence is not None:
        try:
            _persistence.insert_manual_trade(
                trade.trade_id, trade.event_id, trade.ticker, trade.side,
                trade.quantity, trade.price, trade.executed_at,
                trade.thesis, trade.notes, trade.logged_by,
                leverage=trade.leverage,
                invalidation_level=trade.invalidation_level,
                expected_horizon=trade.expected_horizon,
                risk_reason=trade.risk_reason,
                entry_reason=trade.entry_reason,
                exit_plan=trade.exit_plan,
                confidence_before=trade.confidence_before,
                emotional_state=trade.emotional_state,
                mistake_tags=trade.mistake_tags,
                lesson=trade.lesson,
            )
        except Exception:
            pass

    return {
        "operation": "log_manual_trade",
        "trade_id": trade.trade_id,
        "event_id": event_id,
        "ticker": trade.ticker,
        "side": trade.side,
        "quantity": trade.quantity,
        "price": trade.price,
        "leverage": trade.leverage,
        "invalidation_level": trade.invalidation_level,
        "expected_horizon": trade.expected_horizon,
        "risk_reason": trade.risk_reason,
        "entry_reason": trade.entry_reason,
        "exit_plan": trade.exit_plan,
        "confidence_before": trade.confidence_before,
        "emotional_state": trade.emotional_state,
        "mistake_tags": trade.mistake_tags,
        "lesson": trade.lesson,
        "status": "logged",
        "execution_mode": _EXECUTION_MODE,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "broker_api_called": False,
        "broker_order_id": "NONE",
        "execution_gate": _EXECUTION_GATE,
        "execution_permission": False,
        "can_execute": False,
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
    outcome_quality: str = "",
    process_error: str = "",
    process_error_notes: str = "",
    mistake_tags: str = "",
    lesson: str = "",
) -> dict[str, Any]:
    """8. Reconcile a previously logged manual trade with its actual outcome.

    The keyword-only attribution fields (outcome_quality, process_error,
    process_error_notes, mistake_tags, lesson) let the operator separate
    market noise from process errors.  All optional, all record-only.
    """
    if not trade_id or not isinstance(trade_id, str):
        return _error_response("reconcile_trade", "trade_id must be a non-empty string")

    event_id = ""
    if _DB_AVAILABLE and _persistence is not None:
        try:
            event_id = _persistence.get_event_id_for_trade(trade_id)
        except Exception:
            pass
    if not event_id:
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
        outcome_quality=_safe_journal_text(outcome_quality),
        process_error=_safe_journal_text(process_error),
        process_error_notes=_safe_journal_text(process_error_notes),
        mistake_tags=_safe_journal_text(mistake_tags),
        lesson=_safe_journal_text(lesson),
    )
    append_jsonl(RECONCILIATIONS_LOG, rec.to_dict(), stamp=False)
    if _DB_AVAILABLE and _persistence is not None:
        try:
            _persistence.insert_reconciliation(
                rec.reconciliation_id, rec.trade_id, rec.event_id,
                rec.reconciled_at, rec.actual_fill_price, rec.actual_quantity,
                rec.outcome_notes, rec.pnl_estimate, rec.outcome_status,
                outcome_quality=rec.outcome_quality,
                process_error=rec.process_error,
                process_error_notes=rec.process_error_notes,
                mistake_tags=rec.mistake_tags,
                lesson=rec.lesson,
            )
        except Exception:
            pass

    return {
        "operation": "reconcile_trade",
        "reconciliation_id": rec.reconciliation_id,
        "trade_id": trade_id,
        "event_id": event_id,
        "outcome_status": normalized_status,
        "pnl_estimate": pnl_estimate,
        "outcome_quality": rec.outcome_quality,
        "process_error": rec.process_error,
        "process_error_notes": rec.process_error_notes,
        "mistake_tags": rec.mistake_tags,
        "lesson": rec.lesson,
        "status": "logged",
        "execution_mode": _EXECUTION_MODE,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "execution_gate": _EXECUTION_GATE,
        "execution_permission": False,
        "can_execute": False,
        "broker_api_called": False,
        "advisory_status": _ADVISORY_STATUS,
        "human_review_required": True,
        "generated_at": utc_timestamp(),
    }


def _annotate_journal_quality(trade: dict[str, Any]) -> dict[str, Any]:
    """Attach journal-quality metadata to a manual-trade dict.

    Calls into :mod:`scripts.self_test_journal_quality` to compute
    completeness / learning-ready / missing-field flags.  Always tolerant —
    if the helper isn't importable or the trade dict is malformed, returns
    the trade unchanged.  Never mutates the original dict.
    """
    try:
        try:
            from scripts.self_test_journal_quality import score_journal_entry
        except ModuleNotFoundError:
            from self_test_journal_quality import score_journal_entry  # type: ignore[no-redef]
    except Exception:
        return trade

    # Map manual-trade row fields onto the journal-quality scorer's expected
    # field names.  signal_id mirrors event_id; position_size mirrors
    # quantity so the risk_rationale factor lights up when the operator
    # captured size.
    annotated = dict(trade)
    scorer_input = {
        "signal_id": trade.get("event_id", ""),
        "thesis": trade.get("thesis", ""),
        "invalidation_level": trade.get("invalidation_level", ""),
        "expected_horizon": trade.get("expected_horizon", ""),
        "position_size": trade.get("quantity", 0),
        "risk_reason": trade.get("risk_reason", ""),
        "entry_reason": trade.get("entry_reason", ""),
        "exit_plan": trade.get("exit_plan", ""),
        "confidence_before": trade.get("confidence_before"),
        "emotional_state": trade.get("emotional_state", ""),
        "post_trade_outcome": "",  # filled at reconciliation time
        "reconciliation_status": "",
        "mistake_tags": trade.get("mistake_tags", ""),
        "lesson": trade.get("lesson", ""),
    }
    try:
        result = score_journal_entry(scorer_input)
        annotated["journal_completeness_score"] = result.get(
            "journal_completeness_score", 0.0
        )
        annotated["learning_readiness_score"] = result.get(
            "learning_readiness_score", 0.0
        )
        annotated["learning_ready"] = result.get("learning_ready", False)
        annotated["missing_journal_fields"] = list(result.get("missing_fields", []))
        annotated["decision_quality_flags"] = list(
            result.get("decision_quality_flags", [])
        )
    except Exception:
        # Diagnostic failure must never break the list endpoint.
        return trade
    return annotated


def list_manual_trades(*, include_journal_quality: bool = True) -> dict[str, Any]:
    """List all logged manual trades.

    SQLite is canonical (truth_source="sqlite").  Falls back to JSONL only
    when SQLite is unavailable; that response is marked
    truth_source="jsonl_fallback", fallback_used=True, canonical=False.
    See docs/PERSISTENCE_MODEL.md.

    When ``include_journal_quality`` is True (default), each trade is
    annotated with ``journal_completeness_score``, ``learning_readiness_score``,
    ``learning_ready``, ``missing_journal_fields``, and
    ``decision_quality_flags`` so the dashboard can surface "am I learning?"
    without a second round trip.  Set False if the caller wants raw rows
    (e.g. CSV export).
    """
    trades: list[dict[str, Any]] = []
    truth_source = "jsonl_fallback"
    if _DB_AVAILABLE and _persistence is not None:
        try:
            trades = _persistence.get_all_manual_trades()
            truth_source = "sqlite"  # even an empty SQLite result is canonical
        except Exception:
            trades = []
            truth_source = "jsonl_fallback"
    if truth_source != "sqlite":
        trades = _load_jsonl(MANUAL_TRADE_LOG)
        truth_source = "jsonl_fallback"

    canonical = truth_source == "sqlite"
    fallback_used = not canonical

    annotated_trades = trades
    aggregate_quality: dict[str, Any] | None = None
    if include_journal_quality and trades:
        annotated_trades = [_annotate_journal_quality(t) for t in trades]
        try:
            try:
                from scripts.self_test_journal_quality import score_journal_entries
            except ModuleNotFoundError:
                from self_test_journal_quality import score_journal_entries  # type: ignore[no-redef]
            scorer_inputs = [
                {
                    "signal_id": t.get("event_id", ""),
                    "thesis": t.get("thesis", ""),
                    "invalidation_level": t.get("invalidation_level", ""),
                    "expected_horizon": t.get("expected_horizon", ""),
                    "position_size": t.get("quantity", 0),
                    "risk_reason": t.get("risk_reason", ""),
                    "entry_reason": t.get("entry_reason", ""),
                    "exit_plan": t.get("exit_plan", ""),
                    "confidence_before": t.get("confidence_before"),
                    "emotional_state": t.get("emotional_state", ""),
                    "mistake_tags": t.get("mistake_tags", ""),
                    "lesson": t.get("lesson", ""),
                }
                for t in trades
            ]
            aggregate_quality = score_journal_entries(scorer_inputs)
        except Exception:
            aggregate_quality = None

    return {
        "operation": "list_manual_trades",
        "trade_count": len(annotated_trades),
        "trades": annotated_trades,
        "truth_source": truth_source,
        "fallback_used": fallback_used,
        "canonical": canonical,
        "journal_quality_aggregate": aggregate_quality,
        "advisory_status": _ADVISORY_STATUS,
        "execution_mode": _EXECUTION_MODE,
        "execution_gate": _EXECUTION_GATE,
        "execution_permission": False,
        "can_execute": False,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "human_review_required": True,
        "broker_api_called": False,
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
    "get_inbox_diagnostics",
    "get_signal_detail",
    "run_validation",
    "add_user_reflection",
    "add_ai_discussion_summary",
    "mark_signal",
    "log_manual_trade",
    "reconcile_trade",
    "list_manual_trades",
]
