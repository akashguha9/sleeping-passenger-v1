from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .conversion_probability_tracker import (
    compute_conversion_probability,
    compute_executable_edge,
)
from .energy_cost_monitor import compute_cost_increase_score, compute_holding_cost
from .executable_edge_gate import evaluate_executable_edge_gate
from .models import (
    DO_NOT_DEPLOY_POLICY_STATES,
    ExtremeStateEvaluation,
    ExtremeStateSignal,
    ExtremeStateThresholds,
)
from .opponent_symmetry_layer import (
    compute_equilibrium_score,
    compute_net_signal,
    compute_symmetry_score,
    detect_non_converting_equilibrium,
)
from .repeatability_filter import (
    compute_repeatability,
    compute_stress_adjusted_repeatability,
    compute_usable_edge,
)
from .silent_chaos_detector import (
    compute_progress_score,
    compute_silent_chaos_score,
    detect_silent_chaos,
)
from .structural_advantage_detector import (
    compute_execution_efficiency,
    compute_performance_ceiling,
    compute_structural_advantage,
)
from .termination_gate import compute_loop_risk, evaluate_termination_gate
from .utils import clamp01


NORMAL = "NORMAL"
HIGH_EFFICIENCY_EDGE = "HIGH_EFFICIENCY_EDGE"
STRUCTURAL_ADVANTAGE_EDGE = "STRUCTURAL_ADVANTAGE_EDGE"
REPEATABLE_STRUCTURAL_EDGE = "REPEATABLE_STRUCTURAL_EDGE"
VALID_BUT_NON_EXECUTABLE = "VALID_BUT_NON_EXECUTABLE"
NON_CONVERTING_EQUILIBRIUM = "NON_CONVERTING_EQUILIBRIUM"
SILENT_CHAOS = "SILENT_CHAOS"
INFINITE_LOOP_RISK = "INFINITE_LOOP_RISK"
TERMINATION_REQUIRED = "TERMINATION_REQUIRED"
DOWNGRADED_SIGNAL = "DOWNGRADED_SIGNAL"

DO_NOT_DEPLOY = "DO_NOT_DEPLOY"
REPEATABLE_EDGE = REPEATABLE_STRUCTURAL_EDGE
TERMINATE_OR_RECLASSIFY = TERMINATION_REQUIRED


def _derive_runtime_proxy_signal(row: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(row or {})
    ce_score = clamp01(payload.get("ce_score", 0.0))
    status = str(payload.get("status") or "").upper()
    conversion_state = str(payload.get("conversion_state") or "").upper()
    blocker = str(payload.get("blocker_attribution") or "").upper()
    executed_clean = status == "EXECUTED_CLEAN"
    watchlist = status == "WATCHLIST"
    executed_chaos = status == "EXECUTED_CHAOS"

    payload.setdefault("signal_strength_score", ce_score)
    payload.setdefault("signal_validity_score", ce_score if ce_score > 0.4 else ce_score * 0.8)
    payload.setdefault("technique_score", 0.70 if executed_clean else 0.52 if watchlist else 0.35)
    payload.setdefault("structure_score", 0.68 if executed_clean else 0.60 if watchlist else 0.40)
    payload.setdefault("timing_score", 0.64 if executed_clean else 0.48 if watchlist else 0.20)
    payload.setdefault("sequence_quality", 0.72 if executed_clean else 0.48 if watchlist else 0.25)
    payload.setdefault("timing_precision", 0.70 if conversion_state == "CLEAN_ENTRY" else 0.42)
    payload.setdefault("transfer_efficiency", 0.70 if executed_clean else 0.45)
    payload.setdefault("contact_quality", 0.72 if executed_clean else 0.46)
    payload.setdefault("access_score", 0.74 if executed_clean else ce_score)
    payload.setdefault("angle_score", 0.62 if executed_clean else 0.48)
    payload.setdefault("timing_access_score", 0.68 if executed_clean else 0.38)
    payload.setdefault("constraint_reduction_score", 0.64 if blocker == "NONE" else 0.28)
    payload.setdefault("successful_repetitions", 3 if executed_clean else 1 if watchlist else 0)
    payload.setdefault("total_attempts", 4 if executed_clean else 3 if watchlist else 1)
    payload.setdefault("stress_survival_score", 0.74 if executed_clean else 0.40 if watchlist else 0.20)
    payload.setdefault("trigger_presence_score", 0.76 if executed_clean else 0.28 if watchlist else 0.12)
    payload.setdefault("conversion_trigger_score", 0.74 if executed_clean else 0.28 if watchlist else 0.12)
    payload.setdefault("timing_window_score", 0.72 if executed_clean else 0.35 if watchlist else 0.18)
    payload.setdefault("opponent_weakness_score", 0.62 if executed_clean else 0.32)
    payload.setdefault("opponent_counter_signal_strength", 0.44 if executed_clean else 0.58 if watchlist else 0.40)
    payload.setdefault("exit_clarity_score", 0.80 if status.startswith("EXECUTED") else 0.26)
    payload.setdefault("stability_score", 0.78 if executed_clean else 0.64 if watchlist else 0.30)
    payload.setdefault("duration_zscore_normalized", 0.30 if executed_clean else 0.60 if watchlist else 0.10)
    payload.setdefault("transition_count", 1 if status.startswith("EXECUTED") else 0)
    payload.setdefault("transition_rate", 0.82 if executed_clean else 0.08 if watchlist else 0.0)
    payload.setdefault("visible_volatility_score", 0.58 if executed_chaos else 0.38 if watchlist else 0.25)
    payload.setdefault("time_cost", 0.18 if executed_clean else 0.48 if watchlist else 0.10)
    payload.setdefault("mental_cost", 0.18 if executed_clean else 0.44 if watchlist else 0.10)
    payload.setdefault("opportunity_cost", 0.22 if executed_clean else 0.58 if watchlist else 0.12)
    payload.setdefault("risk_cost", 0.26 if executed_chaos else 0.34 if watchlist else 0.15)
    payload.setdefault("cost_increase_score", compute_cost_increase_score(0.52 if watchlist else 0.24, 0.20))
    warnings = list(payload.get("warnings") or [])
    warnings.append("proxy_derived_from_sparse_runtime_state")
    payload["warnings"] = warnings
    return payload


def evaluate_extreme_state_signal(
    signal: dict[str, Any] | ExtremeStateSignal | None,
    *,
    thresholds: ExtremeStateThresholds | None = None,
) -> ExtremeStateEvaluation:
    active = thresholds or ExtremeStateThresholds()
    if isinstance(signal, ExtremeStateSignal):
        row = signal
    else:
        prepared = _derive_runtime_proxy_signal(signal) if isinstance(signal, dict) else {}
        row = ExtremeStateSignal.from_mapping(prepared)

    performance_ceiling_score = compute_performance_ceiling(row)
    execution_efficiency_score = compute_execution_efficiency(row)
    structural_advantage_score = compute_structural_advantage(row)
    repeatability_score = compute_repeatability(row)
    stress_adjusted_repeatability = compute_stress_adjusted_repeatability(
        repeatability_score,
        row.stress_survival_score,
    )
    usable_edge_score = compute_usable_edge(structural_advantage_score, repeatability_score)
    conversion_probability_score = compute_conversion_probability(
        row.trigger_presence_score,
        row.timing_window_score,
        row.opponent_weakness_score,
    )
    executable_edge_score = compute_executable_edge(
        row.signal_strength_score,
        row.conversion_trigger_score,
        row.timing_window_score,
        row.exit_clarity_score,
    )
    net_signal_score = compute_net_signal(
        row.signal_strength_score,
        row.opponent_counter_signal_strength,
    )
    symmetry_score = compute_symmetry_score(
        row.signal_strength_score,
        row.opponent_counter_signal_strength,
    )
    no_transition_score = 1.0 if int(row.transition_count) <= 0 else 1.0 - clamp01(row.transition_rate)
    equilibrium_score = compute_equilibrium_score(
        row.signal_strength_score,
        row.stability_score,
        conversion_probability_score,
        row.transition_rate,
    )
    non_converting_equilibrium = detect_non_converting_equilibrium(
        symmetry_score,
        conversion_probability_score,
        equilibrium_score,
        high_symmetry_threshold=active.high_symmetry_threshold,
        equilibrium_threshold=active.equilibrium_threshold,
    )
    holding_cost_score = compute_holding_cost(
        row.time_cost,
        row.mental_cost,
        row.opportunity_cost,
        row.risk_cost,
    )
    silent_chaos_score = compute_silent_chaos_score(
        row.duration_zscore_normalized,
        no_transition_score,
        row.cost_increase_score,
        row.visible_volatility_score,
    )
    if holding_cost_score >= active.holding_cost_threshold and no_transition_score >= 0.75:
        silent_chaos_score = clamp01(silent_chaos_score + 0.10)
    silent_chaos_flag = detect_silent_chaos(
        silent_chaos_score,
        no_transition_score,
        row.cost_increase_score,
        threshold=active.silent_chaos_threshold,
    )
    loop_risk_score = compute_loop_risk(
        row.stability_score,
        1.0 - clamp01(row.exit_clarity_score),
        no_transition_score,
    )
    if (
        clamp01(row.stability_score) >= 0.75
        and conversion_probability_score <= active.low_conversion_threshold
        and clamp01(row.exit_clarity_score) <= 0.40
    ):
        loop_risk_score = clamp01(max(loop_risk_score, active.loop_risk_threshold))
    termination = evaluate_termination_gate(
        duration_zscore_normalized=row.duration_zscore_normalized,
        transition_count=row.transition_count,
        holding_cost_score=holding_cost_score,
        conversion_probability=conversion_probability_score,
        silent_chaos_flag=silent_chaos_flag,
        loop_risk=loop_risk_score,
        duration_threshold=active.duration_threshold,
        conversion_low_threshold=active.low_conversion_threshold,
        holding_cost_threshold=active.holding_cost_threshold,
        loop_risk_threshold=active.loop_risk_threshold,
    )
    executable_gate = evaluate_executable_edge_gate(
        row,
        executable_edge=executable_edge_score,
        conversion_probability=conversion_probability_score,
        exit_clarity_score=row.exit_clarity_score,
        silent_chaos_flag=silent_chaos_flag,
        termination_required=bool(termination["termination_required"]),
        thresholds=active,
    )
    progress_score = compute_progress_score(repeatability_score, row.transition_rate)

    warnings = list(row.warnings)
    for field_name in (
        "signal_validity_score",
        "sequence_quality",
        "access_score",
        "successful_repetitions",
        "total_attempts",
        "exit_clarity_score",
    ):
        if f"missing:{field_name}" in warnings:
            continue
    if row.total_attempts <= 0:
        warnings.append("missing_repeatability_history")
    if row.exit_clarity_score <= 0.0:
        warnings.append("missing_exit_clarity")

    valid_but_non_executable = (
        clamp01(row.signal_validity_score) >= active.theta_validity
        and (
            conversion_probability_score < active.theta_conversion
            or clamp01(row.exit_clarity_score) < active.theta_exit
        )
    )

    if row.policy_state.upper() in DO_NOT_DEPLOY_POLICY_STATES:
        extreme_state = DO_NOT_DEPLOY
        action = "REJECT"
        reason = "Policy veto remains highest priority and blocks deployment."
    elif loop_risk_score >= active.loop_risk_threshold:
        extreme_state = INFINITE_LOOP_RISK
        action = "TERMINATE"
        reason = "Stable no-exit, no-transition behavior created infinite-loop risk."
    elif bool(termination["termination_required"]):
        extreme_state = TERMINATION_REQUIRED if not silent_chaos_flag else SILENT_CHAOS
        action = "TERMINATE"
        reason = "Termination gate fired because duration, cost, silent chaos, or loop conditions breached limits."
    elif silent_chaos_flag:
        extreme_state = SILENT_CHAOS
        action = "TERMINATE"
        reason = "Silent chaos detected: long duration, rising cost, low transition, and muted volatility."
    elif non_converting_equilibrium:
        extreme_state = NON_CONVERTING_EQUILIBRIUM
        action = "DOWNGRADE"
        reason = "Own edge is being canceled by symmetry while conversion remains weak."
    elif (
        structural_advantage_score >= 0.75
        and repeatability_score >= active.minimum_repeatability_for_promotion
    ):
        extreme_state = REPEATABLE_STRUCTURAL_EDGE
        action = "PROMOTE" if executable_gate["executable"] else "HOLD"
        reason = "Structural advantage is proven repeatable, making the edge usable."
    elif structural_advantage_score >= 0.75:
        extreme_state = STRUCTURAL_ADVANTAGE_EDGE
        action = "HOLD"
        reason = "Structural advantage exists, but repeatability is not yet proven enough for promotion."
    elif execution_efficiency_score >= 0.70 and structural_advantage_score < 0.75:
        extreme_state = HIGH_EFFICIENCY_EDGE
        action = "HOLD"
        reason = "Execution efficiency is high, but structure or repeatability is not yet strong enough."
    elif valid_but_non_executable:
        extreme_state = VALID_BUT_NON_EXECUTABLE
        action = "HOLD" if holding_cost_score < 0.60 and not silent_chaos_flag else "DOWNGRADE"
        reason = "Signal remains valid, but conversion trigger or exit clarity is too weak to execute."
    elif clamp01(row.signal_validity_score) < 0.40:
        extreme_state = DOWNGRADED_SIGNAL
        action = "REJECT"
        reason = "Signal validity is too weak to justify further attention."
    else:
        extreme_state = NORMAL
        action = "HOLD"
        reason = "No extreme-state pattern dominates; remain conservative."

    if (
        extreme_state == NORMAL
        and clamp01(row.signal_validity_score) >= active.theta_validity
        and (
            conversion_probability_score < active.low_conversion_threshold
            or symmetry_score >= active.high_symmetry_threshold
            or holding_cost_score >= 0.60
        )
    ):
        extreme_state = DOWNGRADED_SIGNAL
        action = "DOWNGRADE"
        reason = "Signal remains valid but has lost executable quality through cost, symmetry, or weak conversion."

    decision = {
        "action": action,
        "reason": reason,
        "next_required_check": (
            "define_exit_clarity"
            if clamp01(row.exit_clarity_score) < active.theta_exit
            else "confirm_conversion_path"
            if conversion_probability_score < active.theta_conversion
            else "monitor_cost_and_transition"
            if holding_cost_score >= 0.60 or no_transition_score >= 0.75
            else "maintain_policy_discipline"
        ),
    }

    scores = {
        "performance_ceiling_score": round(performance_ceiling_score, 3),
        "execution_efficiency_score": round(execution_efficiency_score, 3),
        "structural_advantage_score": round(structural_advantage_score, 3),
        "repeatability_score": round(repeatability_score, 3),
        "stress_adjusted_repeatability": round(stress_adjusted_repeatability, 3),
        "usable_edge_score": round(usable_edge_score, 3),
        "conversion_probability_score": round(conversion_probability_score, 3),
        "executable_edge_score": round(executable_edge_score, 3),
        "net_signal_score": round(net_signal_score, 3),
        "symmetry_score": round(symmetry_score, 3),
        "silent_chaos_score": round(silent_chaos_score, 3),
        "loop_risk_score": round(loop_risk_score, 3),
        "holding_cost_score": round(holding_cost_score, 3),
        "progress_score": round(progress_score, 3),
    }
    flags = {
        "policy_veto": row.policy_state.upper() in DO_NOT_DEPLOY_POLICY_STATES,
        "executable": bool(executable_gate["executable"]),
        "silent_chaos_flag": silent_chaos_flag,
        "termination_required": bool(termination["termination_required"]),
        "valid_but_non_executable": valid_but_non_executable,
        "non_converting_equilibrium": non_converting_equilibrium,
    }

    return ExtremeStateEvaluation(
        signal_id=row.signal_id,
        symbol=row.symbol,
        timestamp=row.timestamp,
        extreme_state=extreme_state,
        scores=scores,
        flags=flags,
        decision=decision,
        warnings=warnings,
    )


def summarize_extreme_state_counts(evaluations: list[ExtremeStateEvaluation]) -> dict[str, int]:
    summary = {
        "signals_evaluated": len(evaluations),
        "termination_required_count": 0,
        "silent_chaos_count": 0,
        "valid_but_non_executable_count": 0,
        "non_converting_equilibrium_count": 0,
        "promoted_count": 0,
        "downgraded_count": 0,
    }
    for row in evaluations:
        if row.flags.get("termination_required"):
            summary["termination_required_count"] += 1
        if row.flags.get("silent_chaos_flag"):
            summary["silent_chaos_count"] += 1
        if row.flags.get("valid_but_non_executable"):
            summary["valid_but_non_executable_count"] += 1
        if row.flags.get("non_converting_equilibrium"):
            summary["non_converting_equilibrium_count"] += 1
        if row.decision.get("action") == "PROMOTE":
            summary["promoted_count"] += 1
        if row.decision.get("action") == "DOWNGRADE":
            summary["downgraded_count"] += 1
    return summary


def evaluation_to_dict(evaluation: ExtremeStateEvaluation) -> dict[str, Any]:
    return asdict(evaluation)
