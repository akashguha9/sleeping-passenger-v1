from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from scripts.action_engine import build_action_report
    from scripts.archetype_registry import load_archetype_registry
    from scripts.blocker_cost_engine import build_blocker_cost_report
    from scripts.closure_deficit_monitor import build_closure_deficit_report
    from scripts.governance_feedback_report import build_governance_feedback_report
    from scripts.operator_control import build_operator_control_report
    from scripts.runtime_common import (
        ACTION_REPORT_PATH,
        ARCHETYPE_PROFILE_REPORT_PATH,
        GOVERNANCE_FEEDBACK_REPORT_PATH,
        HEALTH_REPORT_PATH,
        OPERATOR_OVERRIDE_LEDGER_PATH,
        build_deployment_permissions,
        load_current_pipeline_state,
        load_json_file,
        load_open_positions,
        repo_relative,
        stamp_payload,
        write_json_atomic,
    )
    from scripts.signal_refinery import build_signal_refinery_report
    from scripts.trend_engine import build_trend_report
except ModuleNotFoundError:
    from action_engine import build_action_report
    from archetype_registry import load_archetype_registry
    from blocker_cost_engine import build_blocker_cost_report
    from closure_deficit_monitor import build_closure_deficit_report
    from governance_feedback_report import build_governance_feedback_report
    from operator_control import build_operator_control_report
    from runtime_common import (
        ACTION_REPORT_PATH,
        ARCHETYPE_PROFILE_REPORT_PATH,
        GOVERNANCE_FEEDBACK_REPORT_PATH,
        HEALTH_REPORT_PATH,
        OPERATOR_OVERRIDE_LEDGER_PATH,
        build_deployment_permissions,
        load_current_pipeline_state,
        load_json_file,
        load_open_positions,
        repo_relative,
        stamp_payload,
        write_json_atomic,
    )
    from signal_refinery import build_signal_refinery_report
    from trend_engine import build_trend_report


_FRICTION_BAND_BASE = {
    "LOW_FRICTION": 0.25,
    "MEDIUM_FRICTION": 0.55,
    "HIGH_FRICTION": 0.85,
}
_PRE_ENTRY_STATE_RANK = {
    "NONE": 0,
    "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE": 1,
    "CLEAN_READY_PENDING_TRIGGER": 2,
    "CLEAN_ENTRY_ELIGIBLE": 3,
}
_OBJECTIVE_BY_ACTION = {
    "EXIT_NOW": "protect_capital",
    "REDUCE": "harvest_or_de_risk",
    "HOLD": "maintain_existing_edge",
    "MONITOR": "preserve_optionality",
    "BLOCK_ENTRY": "prevent_low_quality_risk",
    "REVIEW_FOR_ENTRY": "capture_validated_upside",
}


def _load_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _coerce_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _ticker_key(value: Any) -> str:
    return str(value or "").upper().strip()


def _reason_text(action_row: dict[str, Any]) -> str:
    reasons = action_row.get("reasons", [])
    if not isinstance(reasons, list):
        return ""
    return " | ".join(str(item) for item in reasons if str(item).strip()).lower()


def _by_ticker(rows: list[dict[str, Any]], key: str = "ticker") -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = _ticker_key(row.get(key))
        if ticker:
            mapping[ticker] = row
    return mapping


def _health_context_from_runtime() -> dict[str, Any]:
    payload = load_json_file(HEALTH_REPORT_PATH, default={}) or {}
    return payload if isinstance(payload, dict) else {}


def _override_count_by_ticker(path: Path | None = None) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in _load_jsonl_rows(path or OPERATOR_OVERRIDE_LEDGER_PATH):
        ticker = _ticker_key(row.get("ticker"))
        if not ticker:
            continue
        counts[ticker] = counts.get(ticker, 0) + 1
    return counts


def build_friction_detector(
    *,
    action_report: dict[str, Any],
    friction_report: dict[str, Any],
    governance_feedback_report: dict[str, Any],
    operator_control_report: dict[str, Any],
    closure_deficit_report: dict[str, Any],
    blocked_promotable_candidate_queue: list[dict[str, Any]],
    entry_review_packets: list[dict[str, Any]],
    transition_review_packets: list[dict[str, Any]],
) -> dict[str, Any]:
    total_actions = len(action_report.get("actions", []))
    governance_summary = action_report.get("execution_governance_summary", {})
    fpeg_counts = governance_summary.get("fpeg_state_counts", {})
    reasoning_gap_rate = (
        float(fpeg_counts.get("insufficient_reasoning", 0)) / total_actions if total_actions else 0.0
    )

    override_summary = governance_feedback_report.get("override_summary", {})
    total_override_count = int(override_summary.get("total_override_count") or 0)
    override_rate = min(total_override_count / total_actions, 1.0) if total_actions else 0.0
    aggressive_override_count = int(
        override_summary.get("override_classification_counts", {}).get("escalate_risk", 0)
        or 0
    )
    aggressive_override_rate = (
        aggressive_override_count / max(total_override_count, 1) if total_override_count else 0.0
    )

    blocked_count = len(blocked_promotable_candidate_queue)
    max_persistent = max(
        (
            int(item.get("persistent_block_count", 0))
            for item in blocked_promotable_candidate_queue
            if isinstance(item, dict)
        ),
        default=0,
    )
    queue_pressure = _clamp((0.5 * min(blocked_count / 3.0, 1.0)) + (0.5 * min(max_persistent / 4.0, 1.0)))

    packets = [
        packet
        for packet in [*entry_review_packets, *transition_review_packets]
        if isinstance(packet, dict)
    ]
    blocked_conflicts = sum(
        1 for packet in packets if str(packet.get("operator_decision_state") or "") == "BLOCKED_BY_CONFLICT"
    )
    packet_conflict_rate = blocked_conflicts / len(packets) if packets else 0.0

    drift_monitor = operator_control_report.get("drift_monitor", {})
    unfinished_closure_rate = _coerce_float(
        closure_deficit_report.get("ratios", {}).get("operator_unfinished_ratio")
    )
    if unfinished_closure_rate is None:
        total_execution_blocks = int(drift_monitor.get("total_execution_blocks") or 0)
        unfinished_count = int(drift_monitor.get("unfinished_closure_count") or 0)
        unfinished_closure_rate = (
            unfinished_count / total_execution_blocks if total_execution_blocks else 0.0
        )

    evidence_gap = _coerce_float(
        next(
            (
                component.get("gap_value")
                for component in closure_deficit_report.get("gap_components", [])
                if component.get("name") == "evidence_sufficiency_gap"
            ),
            None,
        )
    )
    if evidence_gap is None:
        evidence_gap = 0.0

    blocker_pressure = _FRICTION_BAND_BASE.get(
        str(friction_report.get("friction_band") or "HIGH_FRICTION").upper(),
        0.85,
    )
    friction_score = round(
        _clamp(
            (0.30 * blocker_pressure)
            + (0.20 * reasoning_gap_rate)
            + (0.15 * queue_pressure)
            + (0.10 * override_rate)
            + (0.05 * aggressive_override_rate)
            + (0.10 * packet_conflict_rate)
            + (0.05 * unfinished_closure_rate)
            + (0.05 * evidence_gap)
        ),
        4,
    )
    if friction_score >= 0.7:
        friction_band = "HIGH_FRICTION"
    elif friction_score >= 0.4:
        friction_band = "MEDIUM_FRICTION"
    else:
        friction_band = "LOW_FRICTION"

    return {
        "friction_score": friction_score,
        "friction_band": friction_band,
        "components": [
            {"name": "blocker_pressure", "score": round(blocker_pressure, 4)},
            {"name": "reasoning_gap_rate", "score": round(reasoning_gap_rate, 4)},
            {"name": "queue_pressure", "score": round(queue_pressure, 4)},
            {"name": "override_rate", "score": round(override_rate, 4)},
            {"name": "aggressive_override_rate", "score": round(aggressive_override_rate, 4)},
            {"name": "packet_conflict_rate", "score": round(packet_conflict_rate, 4)},
            {"name": "unfinished_closure_rate", "score": round(unfinished_closure_rate, 4)},
            {"name": "evidence_gap", "score": round(evidence_gap, 4)},
        ],
        "unobserved_proxies": [
            "approval_latency",
            "live_execution_slippage",
            "broker_fill_contradictions",
        ],
        "note": (
            "Friction extends the blocker-cost view with governance, override, packet-conflict, and closure backlog proxies. "
            "No live slippage or approval-latency proxy is inferred when it is not logged."
        ),
    }


def _classify_regime_flags(
    *,
    action_report: dict[str, Any],
    signal_refinery_report: dict[str, Any],
    friction_detector: dict[str, Any],
    closure_deficit_report: dict[str, Any],
    blocked_promotable_candidate_queue: list[dict[str, Any]],
    trend_report: dict[str, Any],
) -> dict[str, bool]:
    launch_control = signal_refinery_report.get("launch_control", {})
    thermal = signal_refinery_report.get("thermal_battery_manager", {})
    transition_state = str(trend_report.get("transition_pressure_state") or "")
    return {
        "high_friction": str(friction_detector.get("friction_band") or "") == "HIGH_FRICTION",
        "transition_pressure": bool(blocked_promotable_candidate_queue)
        or transition_state in {"STUCK_BLOCKED", "TRANSITIONING", "READY_BUT_UNTRIGGERED"},
        "entry_window": int(launch_control.get("review_ready_count") or 0) > 0
        or int(action_report.get("summary_by_action", {}).get("REVIEW_FOR_ENTRY", 0) or 0) > 0,
        "crowded_or_chaotic": int(launch_control.get("blocked_crowding_count") or 0) > 0
        or int(thermal.get("chaos_open_position_count") or 0) > 0,
        "sparse_evidence": str(closure_deficit_report.get("closure_deficit_state") or "") == "SPARSE"
        or int(
            closure_deficit_report.get("counts", {}).get(
                "actions_reconciled_with_sufficient_evidence", 0
            )
            or 0
        )
        == 0,
    }


def build_archetype_weighting_layer(
    registry: dict[str, Any],
    regime_flags: dict[str, bool],
) -> dict[str, Any]:
    weights: dict[str, float] = {}
    for key, entry in registry.get("archetypes", {}).items():
        weight = float(entry.get("default_weight", 1.0))
        multipliers = entry.get("regime_multipliers", {})
        if isinstance(multipliers, dict):
            for flag, active in regime_flags.items():
                if active:
                    weight *= float(multipliers.get(flag, 1.0))
        weights[key] = weight
    total = sum(weights.values()) or 1.0
    normalized = {
        key: round(value / total, 4) for key, value in sorted(weights.items())
    }
    ordered = sorted(normalized.items(), key=lambda item: (-item[1], item[0]))
    return {
        "regime_flags": regime_flags,
        "normalized_weights": normalized,
        "ordered_emphasis": [
            {"archetype": key, "weight": value} for key, value in ordered
        ],
    }


def _purity_score(validation_row: dict[str, Any], admitted: bool) -> float:
    validation_score = _coerce_float(validation_row.get("validation_score")) or 0.0
    blocker_clearance = _coerce_float(validation_row.get("blocker_clearance_score")) or 0.0
    cross_source = _coerce_float(validation_row.get("cross_source_confirmation_score")) or 0.0
    source_quality = _coerce_float(validation_row.get("source_quality_score")) or 0.0
    score = (
        (0.35 * validation_score)
        + (0.25 * blocker_clearance)
        + (0.2 * cross_source)
        + (0.1 * source_quality)
        + (0.1 * (1.0 if admitted else 0.0))
    )
    return round(_clamp(score), 4)


def _pressure_score(
    action_row: dict[str, Any],
    queue_row: dict[str, Any] | None,
    live_candidate: dict[str, Any] | None,
    gsce_candidate: dict[str, Any] | None,
    all_clear_candidate: dict[str, Any] | None,
) -> float:
    current_rank = _PRE_ENTRY_STATE_RANK.get(
        str((live_candidate or {}).get("current_pre_entry_state") or "NONE").upper(),
        _PRE_ENTRY_STATE_RANK.get(
            str((live_candidate or {}).get("simulated_pre_entry_state") or "NONE").upper(),
            0,
        ),
    )
    scenario_ranks = [
        _PRE_ENTRY_STATE_RANK.get(
            str((candidate or {}).get("simulated_pre_entry_state") or "NONE").upper(),
            0,
        )
        for candidate in (gsce_candidate, all_clear_candidate)
        if isinstance(candidate, dict) and candidate
    ]
    improvement_depth = 0.0
    if scenario_ranks:
        improvement_depth = max(0.0, (max(scenario_ranks) - current_rank) / 3.0)
    scenario_branch_count = sum(
        1 for candidate in (gsce_candidate, all_clear_candidate) if isinstance(candidate, dict) and candidate
    )
    scenario_branch_score = min(scenario_branch_count / 2.0, 1.0)
    queue_force = min(
        int((queue_row or {}).get("persistent_block_count", 0) or 0) / 4.0,
        1.0,
    )
    forced_reason = any(
        token in _reason_text(action_row)
        for token in ("breached", "reached", "already marked", "chaos position is live")
    )
    force_score = max(queue_force, 1.0 if forced_reason else 0.0)
    score = (0.45 * improvement_depth) + (0.35 * scenario_branch_score) + (0.2 * force_score)
    return round(_clamp(score), 4)


def _error_extraction_score(
    action_row: dict[str, Any],
    signal_refinery_report: dict[str, Any],
    closure_deficit_report: dict[str, Any],
) -> float:
    repeatability = signal_refinery_report.get("repeatability_tracker", {})
    trade_close_count = int(repeatability.get("trade_close_count") or 0)
    expectancy_observed = 1.0 if trade_close_count > 0 else 0.0
    lineage_count = int(
        closure_deficit_report.get("counts", {}).get("actions_reconciled_with_complete_lineage", 0)
        or 0
    )
    sufficient_count = int(
        closure_deficit_report.get("counts", {}).get(
            "actions_reconciled_with_sufficient_evidence", 0
        )
        or 0
    )
    system_base = (
        (0.35 * min(trade_close_count / 5.0, 1.0))
        + (0.35 * min(lineage_count / 5.0, 1.0))
        + (0.2 * min(sufficient_count / 5.0, 1.0))
        + (0.1 * expectancy_observed)
    )
    action_modifier = 0.0
    if bool(action_row.get("has_open_position")):
        action_modifier += 0.2
    if _ticker_key(action_row.get("signal_id")):
        action_modifier += 0.1
    if str(action_row.get("action") or "").upper() in {"MONITOR", "HOLD", "REDUCE", "EXIT_NOW"}:
        action_modifier += 0.1
    return round(_clamp((0.6 * system_base) + action_modifier), 4)


def _optionality_score(
    action_row: dict[str, Any],
    watchlist_row: dict[str, Any] | None,
    queue_row: dict[str, Any] | None,
    gsce_candidate: dict[str, Any] | None,
    all_clear_candidate: dict[str, Any] | None,
    packet: dict[str, Any] | None,
) -> float:
    current_state = str((watchlist_row or {}).get("pre_entry_state") or "NONE").upper()
    tracked_branch = any(
        item
        for item in (
            queue_row,
            gsce_candidate,
            all_clear_candidate,
        )
    ) or _PRE_ENTRY_STATE_RANK.get(current_state, 0) > 0
    scenario_breadth = sum(
        1 for candidate in (gsce_candidate, all_clear_candidate) if isinstance(candidate, dict) and candidate
    )
    scenario_breadth_score = min(scenario_breadth / 2.0, 1.0)
    current_rank = _PRE_ENTRY_STATE_RANK.get(current_state, 0)
    future_rank = max(
        _PRE_ENTRY_STATE_RANK.get(
            str((gsce_candidate or {}).get("simulated_pre_entry_state") or "NONE").upper(),
            0,
        ),
        _PRE_ENTRY_STATE_RANK.get(
            str((all_clear_candidate or {}).get("simulated_pre_entry_state") or "NONE").upper(),
            0,
        ),
        current_rank,
    )
    improvement_depth = max(0.0, (future_rank - current_rank) / 3.0)
    packet_bonus = 1.0 if isinstance(packet, dict) and packet else 0.0
    early_narrowing_penalty = 0.15 if str(action_row.get("action") or "").upper() == "BLOCK_ENTRY" and current_rank > 0 else 0.0
    score = (
        (0.35 * (1.0 if tracked_branch else 0.0))
        + (0.3 * scenario_breadth_score)
        + (0.25 * improvement_depth)
        + (0.1 * packet_bonus)
        - early_narrowing_penalty
    )
    return round(_clamp(score), 4)


def _objective_function_view(
    action_row: dict[str, Any],
    validation_row: dict[str, Any],
    launch_row: dict[str, Any],
) -> dict[str, Any]:
    action = str(action_row.get("action") or "MONITOR").upper()
    priority = _clamp(_coerce_float(action_row.get("priority_score")) or 0.0)
    fpeg_score = _coerce_float(
        action_row.get("execution_governance", {}).get("fpeg", {}).get("fpeg_score")
    )
    if fpeg_score is None:
        fpeg_score = 0.0
    base_score = 0.45
    reason_text = _reason_text(action_row)
    validation_state = str(validation_row.get("validation_state") or "").upper()
    launch_state = str(launch_row.get("launch_state") or "").upper()
    if action == "REVIEW_FOR_ENTRY" and launch_state == "REVIEW_READY":
        base_score = 0.95
    elif action == "EXIT_NOW" and any(token in reason_text for token in ("breached", "chaos position is live", "exit_pending")):
        base_score = 0.92
    elif action == "REDUCE" and any(token in reason_text for token in ("reached", "policy is blocked")):
        base_score = 0.88
    elif action == "BLOCK_ENTRY" and (
        launch_state.startswith("BLOCKED_") or "phase_lock" in reason_text
    ):
        base_score = 0.84
    elif action == "MONITOR" and (
        validation_state in {"VALIDATED", "NEEDS_CONFIRMATION"} or "policy" in reason_text
    ):
        base_score = 0.76
    elif action == "HOLD" and bool(action_row.get("has_open_position")):
        base_score = 0.74
    score = round(_clamp((0.6 * base_score) + (0.2 * priority) + (0.2 * fpeg_score)), 4)
    return {
        "objective_type": _OBJECTIVE_BY_ACTION.get(action, "preserve_optionality"),
        "objective_alignment_score": score,
        "output_failure_risk": round(1.0 - score, 4),
    }


def _geometry_fit_score(
    action_row: dict[str, Any],
    position_row: dict[str, Any] | None,
    packet: dict[str, Any] | None,
    thermal_manager: dict[str, Any],
) -> float:
    max_positions = max(int(thermal_manager.get("max_open_positions") or 0), 1)
    position_headroom = int(thermal_manager.get("position_headroom") or 0)
    headroom_ratio = _clamp(position_headroom / max_positions)
    chaos_open_positions = int(thermal_manager.get("chaos_open_position_count") or 0)
    chaos_clearance = 1.0 if chaos_open_positions <= 0 else 0.0
    max_cluster = max(int(thermal_manager.get("max_positions_per_cluster") or 1), 1)
    cluster_peak = max(
        (
            int(item.get("open_count", 0))
            for item in thermal_manager.get("cluster_concentration", [])
            if isinstance(item, dict)
        ),
        default=0,
    )
    cluster_clearance = _clamp(1.0 - max(0.0, (cluster_peak - max_cluster) / max_cluster))
    score = (0.4 * headroom_ratio) + (0.35 * chaos_clearance) + (0.25 * cluster_clearance)

    action = str(action_row.get("action") or "").upper()
    entry_type = str((position_row or action_row).get("entry_type") or "").upper()
    open_conflict = bool((packet or {}).get("open_position_conflict"))
    if action == "REVIEW_FOR_ENTRY":
        if bool(thermal_manager.get("deployment_allowed")) and not open_conflict:
            score += 0.15
        else:
            score -= 0.2
    if action in {"EXIT_NOW", "REDUCE"} and entry_type == "CHAOS":
        score += 0.2
    if action == "HOLD" and entry_type == "CHAOS":
        score -= 0.2
    return round(_clamp(score), 4)


def _entropy_profile(validation_row: dict[str, Any]) -> dict[str, Any]:
    validation_state = str(validation_row.get("validation_state") or "").upper()
    novelty = _coerce_float(validation_row.get("novelty_score")) or 0.0
    crowding = _coerce_float(validation_row.get("crowding_score")) or 0.0
    shadow = _coerce_float(validation_row.get("shadow_score")) or 0.0
    edge_context = _coerce_float(validation_row.get("edge_context_score")) or 0.0
    asymmetry_window = bool(validation_row.get("asymmetry_window_flag"))
    late_obviousness = bool(validation_row.get("late_obviousness_flag"))
    full_moon_trap = bool(validation_row.get("full_moon_trap_flag"))

    if validation_state != "VALIDATED" or late_obviousness or full_moon_trap or crowding >= 0.7 or edge_context < 0.45:
        state = "UNSTABLE_NOISE"
        score = 0.25 + (0.1 * min(edge_context, 1.0))
    elif asymmetry_window and novelty >= 0.45 and crowding < 0.6 and 0.25 <= shadow <= 0.65:
        state = "BOUNDED_ENTROPY_OPPORTUNITY"
        score = 0.65 + (0.1 * min(novelty, 1.0))
    elif asymmetry_window and novelty < 0.45 and crowding < 0.45 and shadow < 0.45:
        state = "CLEAN_OPPORTUNITY"
        score = 0.82 + (0.08 * min(edge_context, 1.0))
    else:
        state = "UNSTABLE_NOISE"
        score = 0.4
    return {
        "entropy_state": state,
        "entropy_boundedness_score": round(_clamp(score), 4),
    }


def _action_friction_cost(
    action_row: dict[str, Any],
    packet: dict[str, Any] | None,
    queue_row: dict[str, Any] | None,
    override_count: int,
) -> float:
    active_blocker_burden = min(len(action_row.get("active_blockers", [])) / 2.0, 1.0)
    fpeg_state = str(
        action_row.get("execution_governance", {}).get("fpeg", {}).get("fpeg_state") or ""
    )
    if fpeg_state == "insufficient_reasoning":
        reasoning_gap = 1.0
    elif fpeg_state == "review_only":
        reasoning_gap = 0.4
    else:
        reasoning_gap = 0.0
    queue_burden = min(
        int((queue_row or {}).get("persistent_block_count", 0) or 0) / 4.0,
        1.0,
    )
    conflict_burden = 1.0 if bool((packet or {}).get("open_position_conflict")) or str((packet or {}).get("operator_decision_state") or "") == "BLOCKED_BY_CONFLICT" else 0.0
    policy_wait = 1.0 if "policy" in _reason_text(action_row) else 0.0
    override_burden = min(override_count / 2.0, 1.0)
    score = (
        (0.25 * active_blocker_burden)
        + (0.25 * reasoning_gap)
        + (0.2 * queue_burden)
        + (0.15 * conflict_burden)
        + (0.1 * policy_wait)
        + (0.05 * override_burden)
    )
    return round(_clamp(score), 4)


def _closure_confidence_score(
    action_row: dict[str, Any],
    closure_deficit_report: dict[str, Any],
) -> float:
    signal_traceable = 1.0 if _ticker_key(action_row.get("signal_id")) else 0.0
    reason_traceable = 1.0 if _reason_text(action_row) else 0.0
    fpeg_score = _coerce_float(
        action_row.get("execution_governance", {}).get("fpeg", {}).get("fpeg_score")
    )
    if fpeg_score is None:
        fpeg_score = 0.0
    decision_capture_ratio = _coerce_float(
        closure_deficit_report.get("ratios", {}).get("decision_capture_ratio")
    )
    if decision_capture_ratio is None:
        decision_capture_ratio = 0.0
    score = (
        (0.25 * signal_traceable)
        + (0.25 * reason_traceable)
        + (0.25 * fpeg_score)
        + (0.25 * decision_capture_ratio)
    )
    return round(_clamp(score), 4)


def _profile_confidence(
    validation_row: dict[str, Any] | None,
    launch_row: dict[str, Any] | None,
    packet: dict[str, Any] | None,
    queue_row: dict[str, Any] | None,
    governance: dict[str, Any] | None,
) -> dict[str, Any]:
    observed = sum(
        1
        for item in (validation_row, launch_row, packet, queue_row, governance)
        if isinstance(item, dict) and item
    )
    coverage_ratio = round(observed / 5.0, 4)
    state = "OBSERVED" if coverage_ratio >= 0.6 else "SPARSE"
    return {
        "coverage_ratio": coverage_ratio,
        "observed_source_count": observed,
        "state": state,
    }


def build_archetype_profile_report(
    runtime_state: dict[str, Any] | None = None,
    action_report: dict[str, Any] | None = None,
    signal_refinery_report: dict[str, Any] | None = None,
    friction_report: dict[str, Any] | None = None,
    trend_report: dict[str, Any] | None = None,
    governance_feedback_report: dict[str, Any] | None = None,
    closure_deficit_report: dict[str, Any] | None = None,
    operator_control_report: dict[str, Any] | None = None,
    blocked_promotable_candidate_queue: list[dict[str, Any]] | None = None,
    gate_resolution_preview: dict[str, Any] | None = None,
    entry_review_packets: list[dict[str, Any]] | None = None,
    transition_review_packets: list[dict[str, Any]] | None = None,
    packet_summary: dict[str, Any] | None = None,
    open_positions_path: Path | None = None,
    output_path: Path | None = None,
    write_runtime: bool = True,
) -> dict[str, Any]:
    state = runtime_state or load_current_pipeline_state()
    trend = trend_report or build_trend_report(write_runtime=False)
    refinery = signal_refinery_report or build_signal_refinery_report(
        runtime_state=state,
        trend_report=trend,
        write_runtime=False,
    )
    actions = action_report or build_action_report(
        runtime_state=state,
        signal_refinery_report=refinery,
        write_runtime=False,
    )
    governance_feedback = governance_feedback_report or build_governance_feedback_report(
        runtime_state=state,
        action_report=actions,
        write_runtime=False,
    )
    operator_report = operator_control_report or build_operator_control_report(
        write_runtime=False
    )
    closure_report = closure_deficit_report or build_closure_deficit_report(
        runtime_state=state,
        action_report=actions,
        signal_refinery_report=refinery,
        packet_summary=packet_summary,
        operator_control_report=operator_report,
        write_runtime=False,
    )
    blocker_friction = (
        friction_report
        if isinstance(friction_report, dict)
        else build_blocker_cost_report(runtime_state=state, write_runtime=False)
    )

    health_context = _health_context_from_runtime()
    queue = blocked_promotable_candidate_queue
    if queue is None:
        value = health_context.get("blocked_promotable_candidate_queue", [])
        queue = value if isinstance(value, list) else []
    preview = gate_resolution_preview
    if preview is None:
        value = health_context.get("gate_resolution_preview", {})
        preview = value if isinstance(value, dict) else {}
    entry_packets = entry_review_packets
    if entry_packets is None:
        value = health_context.get("entry_review_packets", [])
        entry_packets = value if isinstance(value, list) else []
    transition_packets = transition_review_packets
    if transition_packets is None:
        value = health_context.get("transition_review_packets", [])
        transition_packets = value if isinstance(value, list) else []
    packets = packet_summary
    if packets is None:
        value = health_context.get("packet_summary", {})
        packets = value if isinstance(value, dict) else {}

    friction_detector = build_friction_detector(
        action_report=actions,
        friction_report=blocker_friction,
        governance_feedback_report=governance_feedback,
        operator_control_report=operator_report,
        closure_deficit_report=closure_report,
        blocked_promotable_candidate_queue=queue,
        entry_review_packets=entry_packets,
        transition_review_packets=transition_packets,
    )
    registry = load_archetype_registry()
    regime_flags = _classify_regime_flags(
        action_report=actions,
        signal_refinery_report=refinery,
        friction_detector=friction_detector,
        closure_deficit_report=closure_report,
        blocked_promotable_candidate_queue=queue,
        trend_report=trend,
    )
    weighting_layer = build_archetype_weighting_layer(registry, regime_flags)

    validation_by_ticker = _by_ticker(
        refinery.get("validation_engine", {}).get("signals", []),
    )
    launch_by_ticker = _by_ticker(refinery.get("launch_control", {}).get("launch_rows", []))
    watchlist_by_ticker = _by_ticker(
        state.get("watchlist_diagnostics", {}).get("watchlist_signals", [])
    )
    queue_by_ticker = _by_ticker(queue)
    entry_packet_by_ticker = _by_ticker(entry_packets)
    transition_packet_by_ticker = _by_ticker(transition_packets)
    live_candidates = _by_ticker(preview.get("live", {}).get("candidates", []))
    gsce_candidates = _by_ticker(preview.get("gsce_clear", {}).get("candidates", []))
    all_clear_candidates = _by_ticker(preview.get("all_clear", {}).get("candidates", []))
    override_counts = _override_count_by_ticker()
    open_positions, _ = load_open_positions(open_positions_path)
    positions_by_ticker = _by_ticker(open_positions)
    thermal_manager = refinery.get("thermal_battery_manager", {})
    admission_rows = {
        _ticker_key(row.get("ticker")): row
        for row in refinery.get("signal_admission_gate", {}).get("signal_rows", [])
        if isinstance(row, dict) and _ticker_key(row.get("ticker"))
    }

    action_profiles: list[dict[str, Any]] = []
    top_archetype_counts: dict[str, int] = {}
    entropy_distribution: dict[str, int] = {}
    objective_distribution: dict[str, int] = {}

    for action_row in actions.get("actions", []):
        ticker = _ticker_key(action_row.get("ticker"))
        validation_row = validation_by_ticker.get(ticker, {})
        launch_row = launch_by_ticker.get(ticker, {})
        watchlist_row = watchlist_by_ticker.get(ticker, {})
        queue_row = queue_by_ticker.get(ticker, {})
        packet = entry_packet_by_ticker.get(ticker) or transition_packet_by_ticker.get(ticker) or {}
        position_row = positions_by_ticker.get(ticker, {})
        admission_row = admission_rows.get(ticker, {})
        admitted = bool(admission_row.get("admitted")) if admission_row else False

        purity_score = _purity_score(validation_row, admitted=admitted)
        pressure_score = _pressure_score(
            action_row=action_row,
            queue_row=queue_row,
            live_candidate=live_candidates.get(ticker),
            gsce_candidate=gsce_candidates.get(ticker),
            all_clear_candidate=all_clear_candidates.get(ticker),
        )
        error_extraction_score = _error_extraction_score(
            action_row,
            signal_refinery_report=refinery,
            closure_deficit_report=closure_report,
        )
        optionality_score = _optionality_score(
            action_row=action_row,
            watchlist_row=watchlist_row,
            queue_row=queue_row,
            gsce_candidate=gsce_candidates.get(ticker),
            all_clear_candidate=all_clear_candidates.get(ticker),
            packet=packet,
        )
        objective_view = _objective_function_view(action_row, validation_row, launch_row)
        geometry_fit_score = _geometry_fit_score(
            action_row=action_row,
            position_row=position_row,
            packet=packet,
            thermal_manager=thermal_manager,
        )
        entropy_profile = _entropy_profile(validation_row)
        friction_cost_score = _action_friction_cost(
            action_row=action_row,
            packet=packet,
            queue_row=queue_row,
            override_count=override_counts.get(ticker, 0),
        )
        closure_confidence_score = _closure_confidence_score(
            action_row=action_row,
            closure_deficit_report=closure_report,
        )

        module_scores = {
            "fischer": purity_score,
            "kasparov": pressure_score,
            "carlsen": error_extraction_score,
            "messi": optionality_score,
            "cristiano": objective_view["objective_alignment_score"],
            "neuer": geometry_fit_score,
            "neymar": entropy_profile["entropy_boundedness_score"],
            "hazard": round(1.0 - friction_cost_score, 4),
        }
        weighted_contributions = {
            key: round(
                float(module_scores.get(key, 0.0))
                * float(weighting_layer.get("normalized_weights", {}).get(key, 0.0)),
                4,
            )
            for key in module_scores
        }
        composite_score = round(sum(weighted_contributions.values()), 4)
        dominant_archetypes = sorted(
            weighted_contributions.items(),
            key=lambda item: (-item[1], item[0]),
        )[:3]
        profile_confidence = _profile_confidence(
            validation_row=validation_row,
            launch_row=launch_row,
            packet=packet,
            queue_row=queue_row,
            governance=action_row.get("execution_governance", {}),
        )

        top_archetype = dominant_archetypes[0][0]
        top_archetype_counts[top_archetype] = top_archetype_counts.get(top_archetype, 0) + 1
        entropy_state = entropy_profile["entropy_state"]
        entropy_distribution[entropy_state] = entropy_distribution.get(entropy_state, 0) + 1
        objective_type = objective_view["objective_type"]
        objective_distribution[objective_type] = objective_distribution.get(objective_type, 0) + 1

        action_profiles.append(
            {
                "ticker": ticker,
                "signal_id": action_row.get("signal_id"),
                "action": action_row.get("action"),
                "profile_confidence": profile_confidence,
                "dimension_scores": {
                    "purity_score": purity_score,
                    "pressure_score": pressure_score,
                    "error_extraction_score": error_extraction_score,
                    "optionality_score": optionality_score,
                    "objective_alignment_score": objective_view["objective_alignment_score"],
                    "geometry_fit_score": geometry_fit_score,
                    "entropy_boundedness_score": entropy_profile["entropy_boundedness_score"],
                    "friction_cost_score": friction_cost_score,
                    "closure_confidence_score": closure_confidence_score,
                },
                "objective_function_view": objective_view,
                **entropy_profile,
                "friction_flow_score": round(1.0 - friction_cost_score, 4),
                "module_scores": module_scores,
                "weighted_contributions": weighted_contributions,
                "composite_archetype_score": composite_score,
                "dominant_archetypes": [
                    {"archetype": key, "weighted_score": value}
                    for key, value in dominant_archetypes
                ],
                "paper_mode_boundary": {
                    "advisory_only": True,
                    "human_execution_required": True,
                },
            }
        )

    action_profiles.sort(
        key=lambda item: (-float(item.get("composite_archetype_score", 0.0)), item["ticker"])
    )
    objective_scores = [
        float(item["objective_function_view"]["objective_alignment_score"])
        for item in action_profiles
    ]
    optionality_scores = [float(item["dimension_scores"]["optionality_score"]) for item in action_profiles]
    entropy_scores = [
        float(item["dimension_scores"]["entropy_boundedness_score"]) for item in action_profiles
    ]

    deployment = build_deployment_permissions(state)
    payload = stamp_payload(
        {
            "artifact_kind": "archetype_profile_report",
            "registry_path": registry.get("path"),
            "archetype_weighting_layer": weighting_layer,
            "friction_detector": friction_detector,
            "closure_deficit_summary": {
                "closure_deficit_state": closure_report.get("closure_deficit_state"),
                "closure_deficit_score": closure_report.get("closure_deficit_score"),
                "actions_reconciled_with_sufficient_evidence": closure_report.get(
                    "counts",
                    {},
                ).get("actions_reconciled_with_sufficient_evidence"),
            },
            "summary": {
                "action_profile_count": len(action_profiles),
                "average_objective_alignment_score": _mean(objective_scores),
                "average_optionality_score": _mean(optionality_scores),
                "average_entropy_boundedness_score": _mean(entropy_scores),
                "entropy_distribution": dict(sorted(entropy_distribution.items())),
                "objective_type_distribution": dict(sorted(objective_distribution.items())),
                "dominant_archetype_distribution": dict(sorted(top_archetype_counts.items())),
            },
            "geometry_controller": {
                "thermal_state": thermal_manager.get("thermal_state"),
                "position_headroom": thermal_manager.get("position_headroom"),
                "deployment_allowed": thermal_manager.get("deployment_allowed"),
                "cluster_concentration": thermal_manager.get("cluster_concentration", []),
            },
            "optionality_preserver": {
                "blocked_promotable_candidate_count": len(queue),
                "entry_review_candidate_count": packets.get("entry_review_candidate_count"),
                "transition_review_candidate_count": packets.get(
                    "transition_review_candidate_count"
                ),
                "note": (
                    "Optionality is measured from current watchlist states and deterministic scenario previews. "
                    "The repo does not yet run a full scenario tree."
                ),
            },
            "objective_function_view": {
                "average_objective_alignment_score": _mean(objective_scores),
                "objective_type_distribution": dict(sorted(objective_distribution.items())),
                "output_first_gap_flags": [
                    "review_ready_but_no_human_approval"
                    if int(actions.get("summary_by_action", {}).get("REVIEW_FOR_ENTRY", 0) or 0) > 0
                    and int(
                        closure_report.get("counts", {}).get("actions_approved", 0) or 0
                    )
                    == 0
                    else None,
                    "closed_positions_not_yet_supported_by_evidence"
                    if int(
                        closure_report.get("counts", {}).get(
                            "actions_reconciled_with_sufficient_evidence",
                            0,
                        )
                        or 0
                    )
                    == 0
                    else None,
                ],
            },
            "governance_boundary": {
                "suggestion_only": True,
                "human_execution_required": True,
                "paper_execution_enabled": bool(deployment.get("paper_execution_enabled", False)),
                "live_execution_enabled": bool(deployment.get("live_execution_enabled", False)),
                "note": (
                    "Archetype scoring is advisory in the current MVP. It does not change action selection or paper-execution approval requirements."
                ),
            },
            "action_profiles": action_profiles,
        },
        runtime_state=state,
    )
    payload["objective_function_view"]["output_first_gap_flags"] = [
        item
        for item in payload["objective_function_view"]["output_first_gap_flags"]
        if item is not None
    ]
    if write_runtime:
        write_json_atomic(output_path or ARCHETYPE_PROFILE_REPORT_PATH, payload, stamp=False)
    return payload


def format_archetype_profile_summary(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    weighting = report.get("archetype_weighting_layer", {})
    ordered = weighting.get("ordered_emphasis", [])
    top_emphasis = ", ".join(
        f"{item['archetype']}={item['weight']}"
        for item in ordered[:3]
        if isinstance(item, dict)
    )
    return "\n".join(
        [
            "Archetype Profile",
            f"action_profile_count={summary.get('action_profile_count', 0)}",
            "average_objective_alignment_score="
            f"{summary.get('average_objective_alignment_score')}",
            f"friction_band={report.get('friction_detector', {}).get('friction_band')}",
            f"closure_deficit_state={report.get('closure_deficit_summary', {}).get('closure_deficit_state')}",
            f"top_emphasis={top_emphasis}",
        ]
    )


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build an advisory archetype profile over the current paper-mode pipeline state."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    mode.add_argument("--summary", action="store_true", help="Emit a compact human-readable summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    report = build_archetype_profile_report(write_runtime=True)
    if args.summary:
        print(format_archetype_profile_summary(report))
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
