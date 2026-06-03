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
MANUAL_TRADE_CANCELLATIONS_LOG: Path = LOG_DIR / "manual_trade_cancellations.jsonl"

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

# Soft-cancel statuses for the manual trade log.  Used by the
# Reconciliation tab's "Cancel Log" action.  These are NOT trading outcomes
# — they mark a row as a record-keeping mistake (e.g. a duplicate log) so
# the reconciliation queue can ignore it without losing the audit trail.
# Cancellation NEVER calls a broker, NEVER cancels a real order, and NEVER
# increments ai_execution_count.
VALID_LOG_CANCEL_STATUSES: frozenset[str] = frozenset(
    {"CANCELLED_DUPLICATE", "CANCELLED_LOG"}
)
DEFAULT_LOG_CANCEL_REASON: str = (
    "duplicate manual log; broker API not called; AI executions = 0; "
    "exclude from P/L and exposure"
)

# Provenance marker stamped on every manual_trades row created through the
# Manual Trade Log UI/API.  The Reconciliation queue, Learning Completeness
# report, and Cancel Log guard all gate on this exact value to keep
# seed/demo/sample/import rows out of the live operator surfaces.  Unknown
# (empty) provenance is excluded by default — see docs in
# reconciliation_queue.py and learning_completeness_report.py.
MANUAL_TRADE_LOG_PROVENANCE: str = "manual_trade_log"

# Synthetic test-fixture markers that have no legitimate workflow at the
# manual-trade endpoint.  Used both by ``log_manual_trade`` (defence in
# depth) and by the api_server POST boundary (S9), which rejects an
# explicit synthetic-identity claim BEFORE server-stamping logged_by.
# ``paper_ledger_import`` is intentionally NOT here — paper imports are a
# legitimate non-UI workflow.
SYNTHETIC_LOGGED_BY_MARKERS: frozenset[str] = frozenset(
    {"seed", "demo", "smoke_test", "smoke", "fixture", "mock", "sample", "calibration_seed"}
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
    # Reactor-at-decision snapshot (Sprint 7B). Optional record-only fields
    # capturing what the Signal Reactor reported when the operator decided.
    # None / "" means "no snapshot captured" — calibration code distinguishes
    # this from a captured-but-zero value.  Never grants execution permission.
    reactor_state_at_decision: str = ""
    decision_grade_energy_at_decision: float | None = None
    echo_risk_score_at_decision: float | None = None
    meltdown_risk_at_decision: float | None = None
    fusion_validity_at_decision: str = ""
    fission_branch_clarity_at_decision: float | None = None
    operator_heat_at_decision: float | None = None
    gallardo_block_at_decision: bool = False
    preflight_state_at_decision: str = ""
    # Sprint 7B.2 — Paper-trade ledger support.  trade_mode classifies a
    # row as 'PAPER' (rehearsal/simulation), 'REAL_MANUAL' (operator-entered
    # real trade — record-keeping only), or 'UNKNOWN'.  Storing this NEVER
    # implies broker execution.  Paper rows carry the same advisory stamps
    # (broker_api_called=False, ai_execution_count=0, execution_gate=LOCKED).
    trade_mode: str = "REAL_MANUAL"
    # Provenance marker for the Reconciliation queue contract.  The Manual
    # Trade Log creation path stamps this with 'manual_trade_log'.  Anything
    # else (smoke seeds, demo fixtures, JSONL imports, unknown legacy rows)
    # leaves it empty and is excluded from the live Reconciliation queue.
    # Storing this NEVER grants execution permission.
    created_via: str = ""
    # Sprint I — Native currency for the trade.  The dropdown writes
    # ISO codes (USD/INR/EUR/JPY/…); legacy rows default to '' which
    # reads back as UNKNOWN.  Storing the currency NEVER grants execution.
    currency: str = ""
    # Free-text label the operator types to record which AI / model /
    # source produced the signal they acted on (e.g. "GPT-5.5",
    # "Claude Code", "Grok", "Gemini", "DeepSeek", "Perplexity",
    # "Copilot", "Human-only", "Multi-model consensus").  Optional;
    # legacy rows default to '' and the UI renders "—".  This field is a
    # journal annotation only — storing it NEVER grants execution
    # permission, never calls a broker, and never alters the safety
    # stamps.
    ai_model_used: str = ""

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


_REACTOR_DEFAULT_FIELDS: dict[str, Any] = {
    "reactor_state": "INSUFFICIENT_DATA",
    "decision_grade_energy": None,
    "echo_risk_score": None,
    "meltdown_risk_score": None,
    "fusion_validity": "insufficient_data",
    "fission_branch_clarity": None,
    "operator_heat_score": None,
    "gallardo_block": False,
    "reactor_recommendation": "observe",
    "reactor_available": False,
}


def _inbox_item_to_reactor_signal(item: dict[str, Any]) -> dict[str, Any]:
    """Adapt an inbox-item dict to the shape ``evaluate_signal_reactor``
    expects in its cluster argument.

    Only fields already present on the inbox item are mapped over; nothing
    is invented.  Missing inputs let the reactor degrade to
    ``insufficient_data`` rather than fabricating numbers.
    """
    out: dict[str, Any] = {}
    priority = item.get("priority_score")
    if isinstance(priority, (int, float)) and not isinstance(priority, bool):
        out["intensity"] = float(priority)
        out["initial_strength"] = float(priority)
    persistence = item.get("persistence_score")
    if isinstance(persistence, (int, float)) and not isinstance(persistence, bool):
        out["evidence_strength"] = float(persistence)
        out["durability_score"] = float(persistence)
    contamination = item.get("contamination_score")
    if isinstance(contamination, (int, float)) and not isinstance(contamination, bool):
        out["echo_risk_score"] = float(contamination)
    kill = item.get("kill_rate_score")
    if isinstance(kill, (int, float)) and not isinstance(kill, bool):
        # High kill rate -> low reliability/independence.  Cap to [0, 1].
        out["reliability"] = max(0.0, min(1.0, 1.0 - float(kill)))
        out["independence_score"] = max(0.0, min(1.0, 1.0 - float(kill)))
    signal_type = item.get("entry_type")
    if isinstance(signal_type, str) and signal_type:
        out["signal_type"] = signal_type
    return out


def _decorate_with_reactor_diagnostics(item: dict[str, Any]) -> dict[str, Any]:
    """Attach signal-reactor advisory fields to an inbox item.

    Pure, defensive: any import or evaluation failure leaves the item with
    the documented default fields rather than raising.  The reactor output
    is advisory-only; this function re-stamps the canonical safety
    invariants after enrichment.
    """
    annotated = dict(item)
    for key, default in _REACTOR_DEFAULT_FIELDS.items():
        annotated.setdefault(key, default)

    def _stamp_safety(d: dict[str, Any]) -> dict[str, Any]:
        d["advisory_status"] = _ADVISORY_STATUS
        d["execution_gate"] = _EXECUTION_GATE
        d["broker_api_called"] = False
        d["ai_execution_count"] = _AI_EXECUTION_COUNT
        d["execution_permission"] = False
        d["can_execute"] = False
        return d

    try:
        try:
            from scripts.signal_reactor import evaluate_signal_reactor
        except ModuleNotFoundError:
            from signal_reactor import evaluate_signal_reactor  # type: ignore[no-redef]
    except Exception:
        return _stamp_safety(annotated)

    try:
        reactor_input = _inbox_item_to_reactor_signal(item)
        payload = evaluate_signal_reactor([reactor_input])
        if not isinstance(payload, dict):
            return _stamp_safety(annotated)
    except Exception:
        return _stamp_safety(annotated)

    state = payload.get("signal_reactor_state") or "INSUFFICIENT_DATA"
    annotated["reactor_state"] = str(state)
    annotated["decision_grade_energy"] = payload.get("decision_grade_energy")
    annotated["echo_risk_score"] = payload.get("echo_risk_score")
    annotated["meltdown_risk_score"] = payload.get("meltdown_risk_score")
    annotated["fusion_validity"] = payload.get("fusion_validity", "insufficient_data")
    annotated["fission_branch_clarity"] = payload.get("fission_branch_clarity")
    annotated["operator_heat_score"] = payload.get("operator_heat_score")
    annotated["gallardo_block"] = bool(payload.get("gallardo_block", False))
    annotated["reactor_recommendation"] = str(payload.get("recommendation") or "observe")
    annotated["reactor_available"] = True

    # Re-stamp canonical safety invariants — reactor enrichment must NEVER
    # grant execution permission, regardless of state.
    return _stamp_safety(annotated)


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

    # Signal-reactor enrichment is layered on top of the sensitivity /
    # quarantine diagnostics so the reactor sees both the raw priority and
    # the contamination score derived just above.
    annotated = _decorate_with_reactor_diagnostics(annotated)
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

    # Reactor-state aggregate counts so the inbox surface can show
    # "3 ECHO_SUPPRESSED, 2 OPERATOR_CONTROL_RODS" at a glance.  Failure
    # to compute leaves the counts at zero rather than crashing.
    reactor_state_counts: dict[str, int] = {}
    reactor_gallardo_block_count = 0
    reactor_unavailable_count = 0
    for it in items:
        state = str(it.get("reactor_state") or "INSUFFICIENT_DATA")
        reactor_state_counts[state] = reactor_state_counts.get(state, 0) + 1
        if it.get("gallardo_block"):
            reactor_gallardo_block_count += 1
        if it.get("reactor_available") is False:
            reactor_unavailable_count += 1

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
        "reactor_state_counts": reactor_state_counts,
        "reactor_gallardo_block_count": reactor_gallardo_block_count,
        "reactor_unavailable_count": reactor_unavailable_count,
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


def _safe_unit_score(value: Any) -> float | None:
    """API-boundary normaliser for reactor scores in [0, 1].

    Accepts None or a numeric in [0, 1].  Anything else returns None so a
    bad client payload cannot corrupt the calibration snapshot.
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
    if n < 0.0 or n > 1.0:
        return None
    return n


def _safe_bool(value: Any) -> bool:
    """Coerce any truthy/falsy payload to a strict bool. None -> False."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y", "on"}
    return False


_TRADE_MODE_ALLOWED: frozenset[str] = frozenset({"PAPER", "REAL_MANUAL", "UNKNOWN"})


def _safe_trade_mode(value: Any) -> str:
    """Normalise trade_mode at the API boundary.

    'PAPER'       — rehearsal / simulation (no real capital, no broker)
    'REAL_MANUAL' — operator-entered real trade (record-keeping only)
    'UNKNOWN'     — explicit unknown (rare; preferred for legacy backfills)

    Anything else (None, empty, typo, hostile payload) falls through to
    'REAL_MANUAL' — the historical default that matches every row logged
    before Sprint 7B.2.  This means paper trades MUST be explicitly opted
    into; you cannot accidentally label a real trade as paper.
    """
    if value is None:
        return "REAL_MANUAL"
    text = str(value).strip().upper()
    if text in _TRADE_MODE_ALLOWED:
        return text
    return "REAL_MANUAL"


def _safe_currency(value: Any) -> str:
    """Normalise currency at the API boundary.

    Returns one of the codes in supported_currencies.SUPPORTED_CURRENCY_CODES
    (USD/INR/EUR/JPY/...) or '' for the empty/unknown case.  Anything
    unsupported degrades to '' so legacy rows and hostile inputs share
    one safe representation rather than a hardcoded USD default.
    """
    try:
        try:
            from scripts.supported_currencies import normalise_currency
        except ModuleNotFoundError:  # pragma: no cover - script-style fallback
            from supported_currencies import normalise_currency  # type: ignore[no-redef]
    except Exception:  # pragma: no cover - defensive
        return ""
    code = normalise_currency(value)
    return "" if code == "UNKNOWN" else code


def _safe_ai_model_used(value: Any) -> str:
    """Normalise the operator's AI-model label at the API boundary.

    Free-text journal field — accepts anything the operator types
    (e.g. "GPT-5.5", "Claude Code", "Grok 4", "Gemini 2.5 Pro",
    "DeepSeek R1", "Perplexity", "Copilot", "Human-only",
    "Multi-model consensus").  Trimmed and length-capped at 120 chars so
    a runaway paste cannot bloat a row.  Empty input falls through to ''
    which the UI renders as the explicit "—" placeholder.  Storing this
    NEVER grants execution permission and never reaches a broker.
    """
    if value is None:
        return ""
    text = str(value).strip()
    if len(text) > 120:
        text = text[:120]
    return text


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
    reactor_state_at_decision: str = "",
    decision_grade_energy_at_decision: float | None = None,
    echo_risk_score_at_decision: float | None = None,
    meltdown_risk_at_decision: float | None = None,
    fusion_validity_at_decision: str = "",
    fission_branch_clarity_at_decision: float | None = None,
    operator_heat_at_decision: float | None = None,
    gallardo_block_at_decision: bool | None = None,
    preflight_state_at_decision: str = "",
    trade_mode: str = "REAL_MANUAL",
    currency: str = "",
    ai_model_used: str = "",
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

    # Seed/demo/probe rejection.  This entry point is what stamps a row
    # with created_via='manual_trade_log', which is what makes the row
    # appear in the user's Manual Trade Log.  Probe-thesis / seed
    # event_id / synthetic logged_by values are exactly what produced
    # the leaked AAPL/SPY/QQQ rows the operator saw, so reject them here
    # rather than let them through with a user-manual stamp.  Internal
    # callers that genuinely need seed rows must use
    # persistence.insert_manual_trade directly with created_via='' so the
    # row stays excluded from the live operator surface.
    #
    # Note on paper-ledger imports: ``logged_by='paper_ledger_import'`` is
    # a LEGITIMATE non-UI workflow (CSV imports into the paper journal).
    # Those rows are already filtered out of the live Manual Trade Log by
    # the read-side classifier (``is_user_manual_trade`` excludes any
    # ``logged_by`` in ``EXCLUDED_LOGGED_BY``), so we don't reject them
    # at the POST boundary.  Only the truly synthetic test/fixture
    # markers are blocked here.
    try:
        try:
            from scripts.manual_trade_origin import (
                PROBE_EVENT_ID_PREFIXES,
                PROBE_THESIS_VALUES,
            )
        except ModuleNotFoundError:  # pragma: no cover - script-style fallback
            from manual_trade_origin import (  # type: ignore[no-redef]
                PROBE_EVENT_ID_PREFIXES,
                PROBE_THESIS_VALUES,
            )
    except Exception:  # pragma: no cover - defensive
        PROBE_EVENT_ID_PREFIXES = ()  # type: ignore[assignment]
        PROBE_THESIS_VALUES = frozenset()  # type: ignore[assignment]

    # Synthetic test-fixture markers that have no legitimate workflow.
    # (paper_ledger_import is intentionally absent — see note above.)
    # Promoted to module-level SYNTHETIC_LOGGED_BY_MARKERS so the HTTP
    # boundary (S9 server-stamping in api_server) can reject these BEFORE
    # it overwrites logged_by, keeping a single source of truth.
    _LOGGED_BY_HARD_REJECT = SYNTHETIC_LOGGED_BY_MARKERS

    _thesis_norm = str(thesis or "").strip().lower()
    if _thesis_norm in PROBE_THESIS_VALUES:
        return _error_response(
            "log_manual_trade",
            "thesis looks like a seed/probe placeholder; please describe the trade",
        )
    _event_id_norm = str(event_id or "").strip()
    if _event_id_norm.startswith(PROBE_EVENT_ID_PREFIXES):
        return _error_response(
            "log_manual_trade",
            "event_id uses a seed/demo/fixture prefix; not a real manual trade",
        )
    _logged_by_norm = str(logged_by or "").strip().lower()
    if _logged_by_norm in _LOGGED_BY_HARD_REJECT:
        return _error_response(
            "log_manual_trade",
            "logged_by names a test/fixture source; not an explicit user action",
        )

    # Stricter fake-marker rejection (Sprint-recovery 2026-05-18).  The
    # canonical classifier above rejects exact-match probe theses and
    # known seed event_id prefixes; ``fake_manual_trade_reason`` adds the
    # substring + AAPL-fingerprint + EV_AAPL + empty-AI-model rules so
    # fabrications like ``thesis="no currency given"`` can never reach
    # the DB carrying a ``manual_trade_log`` stamp.  Returns a structured
    # error response identified by REJECT_REASON_NON_USER_MARKER which
    # the HTTP layer surfaces as a 400 with the same safety stamps.
    try:
        try:
            from scripts.manual_trade_origin import (
                REJECT_REASON_NON_USER_MARKER,
                fake_manual_trade_reason,
            )
        except ModuleNotFoundError:  # pragma: no cover - script-style fallback
            from manual_trade_origin import (  # type: ignore[no-redef]
                REJECT_REASON_NON_USER_MARKER,
                fake_manual_trade_reason,
            )
    except Exception:  # pragma: no cover - defensive
        REJECT_REASON_NON_USER_MARKER = "rejected_non_user_manual_trade_marker"
        fake_manual_trade_reason = None  # type: ignore[assignment]

    if fake_manual_trade_reason is not None:
        candidate = {
            "trade_id": "",  # not yet assigned; trade_id rule never fires here
            "event_id": str(event_id or ""),
            "ticker": str(ticker or ""),
            "side": str(side or ""),
            "quantity": quantity,
            "price": price,
            "thesis": str(thesis or ""),
            "notes": str(notes or ""),
            "risk_reason": str(risk_reason or ""),
            "logged_by": str(logged_by or ""),
            "ai_model_used": str(ai_model_used or ""),
        }
        _marker_reason = fake_manual_trade_reason(candidate)
        if _marker_reason:
            resp = _error_response(
                "log_manual_trade",
                f"rejected: row matches fake-manual-trade marker ({_marker_reason})",
            )
            # Tag with the stable reason code the HTTP layer surfaces.
            resp["reason"] = REJECT_REASON_NON_USER_MARKER
            resp["marker_reason"] = _marker_reason
            return resp

    # Auto-attach reactor-at-decision snapshot when the caller did not
    # supply one.  This is the fix for reactor_snapshot_count=0 in the
    # calibration gate — without it the multiplicative Empirical_Validity
    # term stays at zero forever.  The helper NEVER overwrites explicit
    # operator values, NEVER fabricates data, and NEVER grants execution
    # permission.  See scripts/reactor_snapshot_attach.py for invariants.
    _explicit_reactor_kwargs = {
        "reactor_state_at_decision": reactor_state_at_decision,
        "decision_grade_energy_at_decision": decision_grade_energy_at_decision,
        "echo_risk_score_at_decision": echo_risk_score_at_decision,
        "meltdown_risk_at_decision": meltdown_risk_at_decision,
        "fusion_validity_at_decision": fusion_validity_at_decision,
        "fission_branch_clarity_at_decision": fission_branch_clarity_at_decision,
        "operator_heat_at_decision": operator_heat_at_decision,
        "gallardo_block_at_decision": gallardo_block_at_decision,
        "preflight_state_at_decision": preflight_state_at_decision,
    }
    try:
        try:
            from scripts.reactor_snapshot_attach import (
                ATTACH_FROM_SIGNAL,
                ATTACH_PROVIDED,
                ATTACH_UNAVAILABLE,
                maybe_attach_reactor_snapshot,
            )
        except ModuleNotFoundError:  # pragma: no cover - script-style fallback
            from reactor_snapshot_attach import (  # type: ignore[no-redef]
                ATTACH_FROM_SIGNAL,
                ATTACH_PROVIDED,
                ATTACH_UNAVAILABLE,
                maybe_attach_reactor_snapshot,
            )
        attach_source, _attached = maybe_attach_reactor_snapshot(
            _explicit_reactor_kwargs, event_id=str(event_id)
        )
    except Exception:
        attach_source = "unavailable"
        _attached = {}

    if attach_source == ATTACH_FROM_SIGNAL:
        reactor_state_at_decision = _attached.get(
            "reactor_state_at_decision", reactor_state_at_decision
        )
        decision_grade_energy_at_decision = _attached.get(
            "decision_grade_energy_at_decision", decision_grade_energy_at_decision
        )
        echo_risk_score_at_decision = _attached.get(
            "echo_risk_score_at_decision", echo_risk_score_at_decision
        )
        meltdown_risk_at_decision = _attached.get(
            "meltdown_risk_at_decision", meltdown_risk_at_decision
        )
        fusion_validity_at_decision = _attached.get(
            "fusion_validity_at_decision", fusion_validity_at_decision
        )
        fission_branch_clarity_at_decision = _attached.get(
            "fission_branch_clarity_at_decision", fission_branch_clarity_at_decision
        )
        operator_heat_at_decision = _attached.get(
            "operator_heat_at_decision", operator_heat_at_decision
        )
        if "gallardo_block_at_decision" in _attached:
            gallardo_block_at_decision = _attached["gallardo_block_at_decision"]

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
        reactor_state_at_decision=_safe_journal_text(reactor_state_at_decision),
        decision_grade_energy_at_decision=_safe_unit_score(
            decision_grade_energy_at_decision
        ),
        echo_risk_score_at_decision=_safe_unit_score(echo_risk_score_at_decision),
        meltdown_risk_at_decision=_safe_unit_score(meltdown_risk_at_decision),
        fusion_validity_at_decision=_safe_journal_text(fusion_validity_at_decision),
        fission_branch_clarity_at_decision=_safe_unit_score(
            fission_branch_clarity_at_decision
        ),
        operator_heat_at_decision=_safe_unit_score(operator_heat_at_decision),
        gallardo_block_at_decision=_safe_bool(gallardo_block_at_decision),
        preflight_state_at_decision=_safe_journal_text(preflight_state_at_decision),
        trade_mode=_safe_trade_mode(trade_mode),
        # Stamp Manual Trade Log provenance on every row created through
        # this API path.  This is what scopes the Reconciliation queue and
        # Learning Completeness report to operator-entered trades only.
        # Seed/demo/import scripts that call persistence.insert_manual_trade
        # directly do NOT receive this stamp — they remain '' (unknown
        # provenance) and are excluded from the live queue.
        created_via=MANUAL_TRADE_LOG_PROVENANCE,
        currency=_safe_currency(currency),
        ai_model_used=_safe_ai_model_used(ai_model_used),
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
                reactor_state_at_decision=trade.reactor_state_at_decision,
                decision_grade_energy_at_decision=trade.decision_grade_energy_at_decision,
                echo_risk_score_at_decision=trade.echo_risk_score_at_decision,
                meltdown_risk_at_decision=trade.meltdown_risk_at_decision,
                fusion_validity_at_decision=trade.fusion_validity_at_decision,
                fission_branch_clarity_at_decision=trade.fission_branch_clarity_at_decision,
                operator_heat_at_decision=trade.operator_heat_at_decision,
                gallardo_block_at_decision=trade.gallardo_block_at_decision,
                preflight_state_at_decision=trade.preflight_state_at_decision,
                trade_mode=trade.trade_mode,
                created_via=trade.created_via,
                currency=trade.currency,
                ai_model_used=trade.ai_model_used,
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
        "reactor_state_at_decision": trade.reactor_state_at_decision,
        "decision_grade_energy_at_decision": trade.decision_grade_energy_at_decision,
        "echo_risk_score_at_decision": trade.echo_risk_score_at_decision,
        "meltdown_risk_at_decision": trade.meltdown_risk_at_decision,
        "fusion_validity_at_decision": trade.fusion_validity_at_decision,
        "fission_branch_clarity_at_decision": trade.fission_branch_clarity_at_decision,
        "operator_heat_at_decision": trade.operator_heat_at_decision,
        "gallardo_block_at_decision": trade.gallardo_block_at_decision,
        "preflight_state_at_decision": trade.preflight_state_at_decision,
        # Where the reactor-at-decision snapshot came from on this row:
        # provided_explicitly | attached_from_signal | unavailable.
        # Advisory-only — never affects execution permission.
        "reactor_snapshot_source": attach_source,
        "trade_mode": trade.trade_mode,
        "ai_model_used": trade.ai_model_used,
        # Paper-trade safety stamps. For PAPER rows: paper_trade_only=True,
        # real_capital_at_risk=False. For REAL_MANUAL rows: paper_trade_only=
        # False, real_capital_at_risk only reflects that the operator says
        # they hand-entered a real trade — the system NEVER places it.
        "paper_trade_only": trade.trade_mode == "PAPER",
        "real_capital_at_risk": False if trade.trade_mode == "PAPER" else (
            trade.trade_mode == "REAL_MANUAL"
        ),
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
    # Sprint H — Reconciliation productisation.  All optional + tolerant
    # of bad input so legacy clients still work.  Record-keeping only:
    # broker_api_called stays False, ai_execution_count stays 0,
    # execution_gate stays LOCKED.  See scripts/reconciliation_extras.py.
    post_trade_outcome: str = "",
    reconciliation_status: str = "",
    runner_quantity: float | None = None,
    runner_status: str = "",
    partial_take_profit_price: float | None = None,
    partial_take_profit_quantity: float | None = None,
    take_profit_plan: str = "",
    stop_loss_price: float | None = None,
    stop_loss_hit: bool = False,
    exit_reason: str = "",
    invalidation_level: str = "",
    lesson_takeaway: str = "",
    operator_notes_extra: str = "",
) -> dict[str, Any]:
    """8. Reconcile a previously logged manual trade with its actual outcome.

    The keyword-only attribution fields (outcome_quality, process_error,
    process_error_notes, mistake_tags, lesson) let the operator separate
    market noise from process errors.  All optional, all record-only.

    The Sprint H block (post_trade_outcome, runner_quantity, …) feeds
    :func:`scripts.reconciliation_extras.build_outcome_payload` to compute
    realized P/L and serialise a structured outcome into outcome_notes.
    """
    if not trade_id or not isinstance(trade_id, str):
        return _error_response("reconcile_trade", "trade_id must be a non-empty string")

    try:
        try:
            from scripts.reconciliation_extras import (
                OUTCOME_TO_LEGACY_STATUS,
                build_outcome_payload,
                serialize_outcome_for_notes,
            )
        except ModuleNotFoundError:
            from reconciliation_extras import (  # type: ignore[no-redef]
                OUTCOME_TO_LEGACY_STATUS,
                build_outcome_payload,
                serialize_outcome_for_notes,
            )
    except Exception:
        OUTCOME_TO_LEGACY_STATUS = {}  # type: ignore[assignment]
        build_outcome_payload = None  # type: ignore[assignment]
        serialize_outcome_for_notes = None  # type: ignore[assignment]

    event_id = ""
    entry_price: float | None = None
    entry_quantity: float | None = None
    leverage: float = 1.0
    if _DB_AVAILABLE and _persistence is not None:
        try:
            event_id = _persistence.get_event_id_for_trade(trade_id)
        except Exception:
            pass
        try:
            row = _persistence.get_manual_trade(trade_id)
            if row:
                entry_price = float(row.get("price") or 0.0)
                entry_quantity = float(row.get("quantity") or 0.0)
                lev_raw = row.get("leverage")
                if lev_raw is not None:
                    try:
                        leverage = float(lev_raw)
                    except (TypeError, ValueError):
                        leverage = 1.0
        except Exception:
            pass
    if not event_id or entry_price is None:
        for r in _load_jsonl(MANUAL_TRADE_LOG):
            if r.get("trade_id") == trade_id:
                if not event_id:
                    event_id = str(r.get("event_id", ""))
                if entry_price is None:
                    try:
                        entry_price = float(r.get("price") or 0.0)
                    except (TypeError, ValueError):
                        entry_price = 0.0
                if entry_quantity is None:
                    try:
                        entry_quantity = float(r.get("quantity") or 0.0)
                    except (TypeError, ValueError):
                        entry_quantity = 0.0
                lev_raw = r.get("leverage")
                if lev_raw is not None:
                    try:
                        leverage = float(lev_raw)
                    except (TypeError, ValueError):
                        leverage = 1.0
                break
    if entry_price is None:
        entry_price = 0.0
    if entry_quantity is None:
        entry_quantity = 0.0

    # If the caller supplied a richer post_trade_outcome, derive the legacy
    # WIN/LOSS/BREAKEVEN/UNKNOWN status from it (so the existing schema +
    # downstream learning aggregations keep working).  An *explicit* legacy
    # status of WIN/LOSS/BREAKEVEN can still override the derived value
    # (it lets the operator say "this was a STOPPED_OUT but the
    # outcome_status I want recorded is BREAKEVEN, e.g. for a -0.1% nip").
    legacy_status_input = str(outcome_status).upper().strip()
    legacy_status = legacy_status_input
    structured_outcome: dict[str, Any] | None = None
    if post_trade_outcome and build_outcome_payload is not None:
        structured_outcome = build_outcome_payload(
            trade_id=trade_id,
            post_trade_outcome=post_trade_outcome,
            actual_exit_price=actual_fill_price,
            exit_quantity=actual_quantity,
            entry_price=entry_price,
            entry_quantity=entry_quantity,
            leverage=leverage,
            reconciliation_status=reconciliation_status or None,
            outcome_quality=outcome_quality,
            mistake_tags=mistake_tags,
            lesson_takeaway=lesson_takeaway or lesson,
            notes=operator_notes_extra or outcome_notes,
            invalidation_level=invalidation_level,
            stop_loss_price=stop_loss_price,
            stop_loss_hit=stop_loss_hit,
            exit_reason=exit_reason,
            partial_take_profit_price=partial_take_profit_price,
            partial_take_profit_quantity=partial_take_profit_quantity,
            runner_quantity=runner_quantity,
            runner_status=runner_status or None,
            take_profit_plan=take_profit_plan or "70% TP / 30% runner",
        )
        derived_legacy = OUTCOME_TO_LEGACY_STATUS.get(
            structured_outcome["post_trade_outcome"], "UNKNOWN"
        )
        # Default-only outcome_status ('UNKNOWN' / '') means the caller
        # didn't pick a legacy bucket; use the derived one.  An explicit
        # WIN/LOSS/BREAKEVEN sticks.
        operator_specified_legacy = (
            legacy_status_input
            in {"WIN", "LOSS", "BREAKEVEN"}
        )
        if not operator_specified_legacy:
            legacy_status = derived_legacy
    if legacy_status not in VALID_RECONCILIATION_STATUSES:
        legacy_status = "UNKNOWN"

    # Build the outcome_notes string.  When the structured payload is
    # present we tag it onto the end so downstream tools can recover the
    # full record without a schema migration.  When absent we fall back to
    # the operator's free-text notes.
    base_notes = str(operator_notes_extra or outcome_notes or "")
    if structured_outcome is not None and serialize_outcome_for_notes is not None:
        notes_to_persist = serialize_outcome_for_notes(structured_outcome, base_notes)
    else:
        notes_to_persist = base_notes

    # Pick the final pnl_estimate.  When the structured outcome computed a
    # realized P/L locally, prefer that — it is the canonical local value.
    final_pnl = (
        structured_outcome["realized_pnl"]
        if structured_outcome is not None
        else float(pnl_estimate)
    )

    rec = TradeReconciliation(
        reconciliation_id=f"REC_{uuid.uuid4().hex[:12]}",
        trade_id=trade_id,
        event_id=event_id,
        reconciled_at=utc_timestamp(),
        actual_fill_price=float(actual_fill_price),
        actual_quantity=float(actual_quantity),
        outcome_notes=notes_to_persist,
        pnl_estimate=float(final_pnl),
        outcome_status=legacy_status,
        outcome_quality=_safe_journal_text(outcome_quality),
        process_error=_safe_journal_text(process_error),
        process_error_notes=_safe_journal_text(process_error_notes),
        mistake_tags=_safe_journal_text(mistake_tags),
        lesson=_safe_journal_text(lesson_takeaway or lesson),
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

    response: dict[str, Any] = {
        "operation": "reconcile_trade",
        "reconciliation_id": rec.reconciliation_id,
        "trade_id": trade_id,
        "event_id": event_id,
        "outcome_status": legacy_status,
        "pnl_estimate": rec.pnl_estimate,
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
    if structured_outcome is not None:
        # Surface the new fields directly on the response so the frontend
        # can render realized_pnl / runner_quantity / post_trade_outcome
        # without parsing outcome_notes.  The structured outcome already
        # carries the safety stamps; we re-stamp the response below.
        response["post_trade_outcome"] = structured_outcome["post_trade_outcome"]
        response["reconciliation_status"] = structured_outcome["reconciliation_status"]
        response["realized_pnl"] = structured_outcome["realized_pnl"]
        response["actual_exit_price"] = structured_outcome["actual_exit_price"]
        response["exit_quantity"] = structured_outcome["exit_quantity"]
        response["remaining_quantity"] = structured_outcome["remaining_quantity"]
        response["runner_quantity"] = structured_outcome["runner_quantity"]
        response["runner_status"] = structured_outcome["runner_status"]
        response["partial_take_profit_price"] = structured_outcome.get(
            "partial_take_profit_price"
        )
        response["partial_take_profit_quantity"] = structured_outcome.get(
            "partial_take_profit_quantity"
        )
        response["take_profit_plan"] = structured_outcome.get("take_profit_plan")
        response["stop_loss_price"] = structured_outcome.get("stop_loss_price")
        response["stop_loss_hit"] = structured_outcome.get("stop_loss_hit")
        response["exit_reason"] = structured_outcome.get("exit_reason")
        response["invalidation_level"] = structured_outcome.get("invalidation_level")
        response["lesson_takeaway"] = structured_outcome.get("lesson_takeaway")
        response["notes"] = structured_outcome.get("notes")
        response["leverage"] = structured_outcome.get("leverage")
    return response


def cancel_manual_trade_log(
    trade_id: str,
    *,
    reason: str = "",
    status: str = "CANCELLED_DUPLICATE",
) -> dict[str, Any]:
    """Soft-cancel a manual trade log row (record-keeping only).

    Use this when the operator logged the same manual trade twice (or
    otherwise mis-logged) and wants the duplicate to stop showing up in
    "Awaiting Reconciliation".  This is the inverse of
    :func:`log_manual_trade` from the operator's point of view, BUT it is
    NOT a trade-cancellation.  It never calls a broker, never sends a
    cancel to any exchange, and never mutates ``ai_execution_count``.

    Behaviour
    ---------
    * SQLite is canonical.  The row's ``reconciliation_status`` is set to
      ``status`` (default ``CANCELLED_DUPLICATE``), ``cancel_reason`` is
      recorded, and ``cancelled_at`` is stamped.
    * A cancellation record is also appended to
      ``MANUAL_TRADE_CANCELLATIONS_LOG`` as an audit trail.  The original
      log row is preserved; the cancellation is overlaid, never deleted.
    * If the row has already been reconciled (a
      ``reconciliation_results`` row exists for it), the cancel is
      refused — reconciled trades represent learned outcomes and must not
      vanish from the journal.
    * If the row's ``broker_api_called`` flag is set (which should be
      impossible in this app, but defended in depth) the cancel is
      refused.
    """
    if not trade_id or not isinstance(trade_id, str):
        return _error_response(
            "cancel_manual_trade_log", "trade_id must be a non-empty string"
        )
    normalized_status = str(status or "CANCELLED_DUPLICATE").upper().strip()
    if normalized_status not in VALID_LOG_CANCEL_STATUSES:
        normalized_status = "CANCELLED_DUPLICATE"
    cancel_reason = str(reason or DEFAULT_LOG_CANCEL_REASON).strip()
    cancelled_at = utc_timestamp()

    trade_row: dict[str, Any] | None = None
    already_reconciled = False
    if _DB_AVAILABLE and _persistence is not None:
        try:
            trade_row = _persistence.get_manual_trade(trade_id)
        except Exception:
            trade_row = None
        if trade_row is not None:
            try:
                existing = _persistence.get_reconciliations_for_trade(trade_id)
                already_reconciled = bool(existing)
            except Exception:
                already_reconciled = False
    if trade_row is None:
        # JSONL fallback — defensive.  When SQLite is unavailable we still
        # let the operator audit-cancel the log; the queue endpoint reads
        # SQLite anyway, so this branch is mostly belt-and-braces.
        for raw in _load_jsonl(MANUAL_TRADE_LOG):
            if raw.get("trade_id") == trade_id:
                trade_row = dict(raw)
                break
    if trade_row is None:
        resp = _error_response(
            "cancel_manual_trade_log",
            f"manual trade log {trade_id!r} not found",
        )
        resp["status"] = "not_found"
        resp["reason"] = "not_found"
        return resp

    # Provenance guard: Cancel Log is a Reconciliation-tab affordance for
    # the operator's own duplicate / mis-logged Manual Trade Log rows.
    # Refuse it for seed/demo/import/unknown-provenance rows so the
    # operator can never accidentally rewrite the history of rows they
    # did not enter through this UI.  No broker call; ai_execution_count
    # stays 0.
    row_provenance = str(trade_row.get("created_via") or "").strip()
    if row_provenance != MANUAL_TRADE_LOG_PROVENANCE:
        resp = _error_response(
            "cancel_manual_trade_log",
            "Only human manual log records can be cancelled from Reconciliation.",
        )
        resp["status"] = "refused"
        resp["reason"] = "non_manual_trade_log_origin"
        resp["created_via"] = row_provenance
        resp["broker_api_called"] = False
        resp["ai_execution_count"] = _AI_EXECUTION_COUNT
        return resp

    # Defence in depth: this app never sets broker_api_called=True, but
    # ``_to_dict`` always rewrites the read value to False to lock the
    # invariant.  So we check the *raw* SQLite column directly here: if a
    # corrupt/imported row claims a broker call ever happened, refuse to
    # silently soft-cancel it.
    raw_broker_flag = 0
    if _DB_AVAILABLE and _persistence is not None:
        try:
            raw_flag = _persistence.get_manual_trade_raw_broker_flag(trade_id)
        except Exception:
            raw_flag = None
        if raw_flag is None:
            # No DB row — fall back to the JSONL-sourced value.
            raw_broker_flag = int(trade_row.get("broker_api_called", 0) or 0)
        else:
            raw_broker_flag = int(raw_flag)
    else:
        raw_broker_flag = int(trade_row.get("broker_api_called", 0) or 0)
    if raw_broker_flag != 0:
        resp = _error_response(
            "cancel_manual_trade_log",
            "refusing to cancel a log marked broker_api_called=True",
        )
        resp["status"] = "refused"
        resp["reason"] = "broker_api_called_true"
        resp["broker_api_called"] = True
        return resp

    if already_reconciled:
        resp = _error_response(
            "cancel_manual_trade_log",
            (
                "This trade has been reconciled. Edit or void the "
                "reconciliation row before cancelling the manual log."
            ),
        )
        resp["status"] = "refused"
        resp["reason"] = "already_reconciled"
        resp["reconciled"] = True
        resp["broker_api_called"] = False
        return resp

    existing_status = str(trade_row.get("reconciliation_status") or "").upper()
    if existing_status in VALID_LOG_CANCEL_STATUSES:
        # Idempotent: already cancelled.  Return success without writing
        # a second audit row.
        return {
            "operation": "cancel_manual_trade_log",
            "trade_id": trade_id,
            "reconciliation_status": existing_status,
            "cancel_reason": str(trade_row.get("cancel_reason") or ""),
            "cancelled_at": str(trade_row.get("cancelled_at") or ""),
            "status": "already_cancelled",
            "execution_mode": _EXECUTION_MODE,
            "ai_execution_count": _AI_EXECUTION_COUNT,
            "execution_gate": _EXECUTION_GATE,
            "execution_permission": False,
            "can_execute": False,
            "broker_api_called": False,
            "advisory_status": _ADVISORY_STATUS,
            "human_review_required": True,
            "record_keeping_only": True,
            "generated_at": utc_timestamp(),
        }

    sqlite_updated = False
    if _DB_AVAILABLE and _persistence is not None:
        try:
            sqlite_updated = _persistence.cancel_manual_trade(
                trade_id,
                cancelled_at,
                cancel_reason=cancel_reason,
                status=normalized_status,
            )
        except Exception:
            sqlite_updated = False

    audit_record = {
        "trade_id": trade_id,
        "event_id": str(trade_row.get("event_id") or ""),
        "ticker": str(trade_row.get("ticker") or ""),
        "reconciliation_status": normalized_status,
        "cancel_reason": cancel_reason,
        "cancelled_at": cancelled_at,
        "broker_api_called": False,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "execution_mode": _EXECUTION_MODE,
        "advisory_status": _ADVISORY_STATUS,
        "record_keeping_only": True,
    }
    append_jsonl(MANUAL_TRADE_CANCELLATIONS_LOG, audit_record, stamp=False)

    return {
        "operation": "cancel_manual_trade_log",
        "trade_id": trade_id,
        "reconciliation_status": normalized_status,
        "cancel_reason": cancel_reason,
        "cancelled_at": cancelled_at,
        "sqlite_updated": sqlite_updated,
        "status": "cancelled",
        "execution_mode": _EXECUTION_MODE,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "execution_gate": _EXECUTION_GATE,
        "execution_permission": False,
        "can_execute": False,
        "broker_api_called": False,
        "advisory_status": _ADVISORY_STATUS,
        "human_review_required": True,
        "record_keeping_only": True,
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


def list_manual_trades(
    *,
    include_journal_quality: bool = True,
    origin: str | None = None,
) -> dict[str, Any]:
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

    Parameters
    ----------
    origin : str | None
        Optional provenance filter.  When set to ``"manual_trade_log"`` the
        response contains only rows the operator entered through the Manual
        Trade Log UI/API (rows whose ``created_via`` column equals
        ``"manual_trade_log"``).  Used by the Reconciliation tab to keep
        seed/demo/import rows out of the live operator surface.  ``None``
        (default) returns every row for audit on the Manual Trade Log page.
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
        # Overlay JSONL cancellations so the JSONL fallback agrees with
        # SQLite: a cancelled log shows reconciliation_status=CANCELLED_*
        # and is filtered out of the active-unreconciled view by the
        # frontend.  Cancellation NEVER deletes the original log line.
        cancellations: dict[str, dict[str, Any]] = {}
        for rec in _load_jsonl(MANUAL_TRADE_CANCELLATIONS_LOG):
            tid = str(rec.get("trade_id") or "")
            if tid:
                cancellations[tid] = rec
        if cancellations:
            for t in trades:
                tid = str(t.get("trade_id") or "")
                rec = cancellations.get(tid)
                if rec is not None:
                    t["reconciliation_status"] = str(
                        rec.get("reconciliation_status") or "CANCELLED_DUPLICATE"
                    )
                    t["cancel_reason"] = str(rec.get("cancel_reason") or "")
                    t["cancelled_at"] = str(rec.get("cancelled_at") or "")
        truth_source = "jsonl_fallback"

    canonical = truth_source == "sqlite"
    fallback_used = not canonical

    # Optional provenance filter for the Reconciliation tab.  When the
    # caller asks for origin="manual_trade_log" we apply the canonical
    # user-manual predicate (see scripts/manual_trade_origin) so probe
    # theses, test event_ids, automation logged_by values, and rows with
    # broker/AI flags set are excluded as well as bare-provenance rows.
    # Other origin values fall back to the simple created_via match for
    # legacy callers.
    if origin is not None:
        wanted = str(origin or "").strip()
        if wanted == MANUAL_TRADE_LOG_PROVENANCE:
            try:
                try:
                    from scripts.manual_trade_origin import (
                        is_visible_manual_trade,
                    )
                except ModuleNotFoundError:
                    from manual_trade_origin import (  # type: ignore[no-redef]
                        is_visible_manual_trade,
                    )
                # ``is_visible_manual_trade`` applies the canonical
                # user-manual predicate AND the stricter fake-marker
                # veto.  Origin alone is not enough — the leaked AAPL
                # row was stamped ``manual_trade_log`` yet was synthetic
                # (incident 2026-05-18).  See scripts/manual_trade_origin.
                trades = [t for t in trades if is_visible_manual_trade(t)]
            except Exception:
                trades = [
                    t for t in trades
                    if str(t.get("created_via") or "").strip() == wanted
                ]
        else:
            trades = [
                t for t in trades
                if str(t.get("created_via") or "").strip() == wanted
            ]

    # Annotate every returned row with its origin label and duplicate
    # group metadata so the UI can show "USER_MANUAL" / "EXCLUDED_PROBE_*"
    # chips and surface duplicate-group counts without re-deriving them.
    try:
        try:
            from scripts.manual_trade_origin import (
                classify_manual_trade_origin,
                duplicate_group_key,
            )
        except ModuleNotFoundError:
            from manual_trade_origin import (  # type: ignore[no-redef]
                classify_manual_trade_origin,
                duplicate_group_key,
            )
    except Exception:
        classify_manual_trade_origin = None  # type: ignore[assignment]
        duplicate_group_key = None  # type: ignore[assignment]
    if trades and classify_manual_trade_origin is not None:
        dup_counts: dict[str, int] = {}
        if duplicate_group_key is not None:
            for t in trades:
                k = duplicate_group_key(t)
                dup_counts[k] = dup_counts.get(k, 0) + 1
        for t in trades:
            t["origin_label"] = classify_manual_trade_origin(t)
            if duplicate_group_key is not None:
                k = duplicate_group_key(t)
                t["duplicate_group_key"] = k
                t["duplicate_count"] = dup_counts.get(k, 1)
                t["possible_duplicate"] = dup_counts.get(k, 1) > 1

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
    "MANUAL_TRADE_CANCELLATIONS_LOG",
    "VALID_USER_STATUSES",
    "VALID_RECONCILIATION_STATUSES",
    "VALID_LOG_CANCEL_STATUSES",
    "DEFAULT_LOG_CANCEL_REASON",
    "MANUAL_TRADE_LOG_PROVENANCE",
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
    "cancel_manual_trade_log",
    "list_manual_trades",
]
