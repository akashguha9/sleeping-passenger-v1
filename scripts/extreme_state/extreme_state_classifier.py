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
    compute_symmetry_risk,
    detect_non_converting_equilibrium,
)
from .repeatability_filter import (
    compute_repeatability,
    compute_stress_adjusted_repeatability,
    compute_true_edge,
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
REPEATABLE_EDGE = "REPEATABLE_EDGE"
VALID_BUT_NON_EXECUTABLE = "VALID_BUT_NON_EXECUTABLE"
NON_CONVERTING_EQUILIBRIUM = "NON_CONVERTING_EQUILIBRIUM"
SILENT_CHAOS = "SILENT_CHAOS"
TERMINATE_OR_RECLASSIFY = "TERMINATE_OR_RECLASSIFY"
DO_NOT_DEPLOY = "DO_NOT_DEPLOY"


def _derive_runtime_proxy_signal(row: dict[str, Any] | None) -> dict[str, Any]:
    """Map sparse SCM rows into conservative extreme-state inputs.

    Current seeded SCM rows only expose CE score, status, conversion state,
    and blocker attribution. This proxy keeps the layer honest: it emits a
    usable diagnostic packet while clearly warning that the numbers are
    derived from sparse local runtime state rather than rich market data.
    """
    payload = dict(row or {})
    ce_score = clamp01(payload.get("ce_score", 0.0))
    status = str(payload.get("status") or "").upper()
    conversion_state = str(payload.get("conversion_state") or "").upper()
    blocker = str(payload.get("blocker_attribution") or "").upper()
    executed_clean = status == "EXECUTED_CLEAN"
    executed_chaos = status == "EXECUTED_CHAOS"
    watchlist = status == "WATCHLIST"

    payload.setdefault("signal_strength_score", ce_score)
    payload.setdefault("signal_validity_score", ce_score if ce_score > 0.4 else ce_score * 0.8)
    payload.setdefault("technique_score", 0.60 if executed_clean else 0.50 if watchlist else 0.35)
    payload.setdefault("structure_score", 0.68 if executed_clean else 0.58 if watchlist else 0.40)
    payload.setdefault("timing_score", 0.62 if executed_clean else 0.45)
    payload.setdefault("sequence_quality", 0.70 if executed_clean else 0.45)
    payload.setdefault("timing_precision", 0.68 if conversion_state == "CLEAN_ENTRY" else 0.42)
    payload.setdefault("transfer_efficiency", 0.70 if executed_clean else 0.44)
    payload.setdefault("contact_quality", 0.70 if executed_clean else 0.48)
    payload.setdefault("access_score", 0.72 if executed_clean else ce_score)
    payload.setdefault("angle_score", 0.60 if executed_clean else 0.48)
    payload.setdefault("timing_access_score", 0.66 if executed_clean else 0.38)
    payload.setdefault("constraint_reduction_score", 0.62 if blocker == "NONE" else 0.28)
    payload.setdefault("successful_repetitions", 3 if executed_clean else 1 if watchlist else 0)
    payload.setdefault("total_attempts", 4 if executed_clean else 3 if watchlist else 1)
    payload.setdefault("stress_survival_score", 0.72 if executed_clean else 0.35 if watchlist else 0.20)
    payload.setdefault("persistence_score", 0.70 if executed_clean else 0.52 if watchlist else 0.20)
    payload.setdefault("conversion_trigger_score", 0.76 if executed_clean else 0.30 if watchlist else 0.15)
    payload.setdefault("trigger_presence_score", 0.74 if executed_clean else 0.28 if watchlist else 0.15)
    payload.setdefault("timing_window_score", 0.70 if executed_clean else 0.33 if watchlist else 0.20)
    payload.setdefault("opponent_weakness_score", 0.60 if executed_clean else 0.32)
    payload.setdefault("opponent_counter_signal_strength", 0.45 if executed_clean else 0.58 if watchlist else 0.40)
    payload.setdefault("exit_clarity_score", 0.78 if status.startswith("EXECUTED") else 0.26)
    payload.setdefault("stability_score", 0.76 if executed_clean else 0.62 if watchlist else 0.30)
    payload.setdefault("duration_zscore_normalized", 0.32 if executed_clean else 0.58 if watchlist else 0.10)
    payload.setdefault("transition_count", 1 if status.startswith("EXECUTED") else 0)
    payload.setdefault("transition_rate", 0.80 if executed_clean else 0.08 if watchlist else 0.0)
    payload.setdefault("visible_volatility_score", 0.58 if executed_chaos else 0.40 if watchlist else 0.30)
    payload.setdefault("hold_probability", 0.30 if executed_clean else 0.74 if watchlist else 0.20)
    payload.setdefault("forced_exit_presence", 1.0 if status.startswith("EXECUTED") else 0.0)
    payload.setdefault("time_cost", 0.18 if executed_clean else 0.48 if watchlist else 0.10)
    payload.setdefault("mental_cost", 0.14 if executed_clean else 0.42 if watchlist else 0.12)
    payload.setdefault("opportunity_cost", 0.22 if executed_clean else 0.58 if watchlist else 0.10)
    payload.setdefault("risk_cost", 0.26 if executed_chaos else 0.34 if watchlist else 0.15)
    previous_cost = 0.18 if executed_clean else 0.20 if watchlist else 0.10
    current_cost = 0.24 if executed_clean else 0.52 if watchlist else 0.15
    payload.setdefault("cost_increase_score", compute_cost_increase_score(current_cost, previous_cost))
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

    performance_ceiling = compute_performance_ceiling(row)
    execution_efficiency = compute_execution_efficiency(row)
    structural_advantage = compute_structural_advantage(row)
    repeatability = compute_repeatability(row)
    stress_adjusted_repeatability = compute_stress_adjusted_repeatability(
        repeatability,
        row.stress_survival_score,
    )
    usable_edge = compute_usable_edge(structural_advantage, repeatability)
    conversion_probability = compute_conversion_probability(
        row.trigger_presence_score,
        row.timing_window_score,
        row.opponent_weakness_score,
    )
    executable_edge = compute_executable_edge(
        row.signal_strength_score,
        row.conversion_trigger_score,
        row.timing_window_score,
        row.exit_clarity_score,
    )
    net_signal = compute_net_signal(
        row.signal_strength_score,
        row.opponent_counter_signal_strength,
    )
    symmetry_risk = compute_symmetry_risk(
        row.signal_strength_score,
        row.opponent_counter_signal_strength,
    )
    equilibrium_score = compute_equilibrium_score(
        row.persistence_score,
        row.stability_score,
        conversion_probability,
        row.transition_rate,
    )
    non_converting_equilibrium = detect_non_converting_equilibrium(
        symmetry_risk,
        conversion_probability,
        equilibrium_score,
        high_symmetry_threshold=active.high_symmetry_threshold,
        equilibrium_threshold=active.equilibrium_threshold,
    )
    holding_cost = compute_holding_cost(
        row.time_cost,
        row.mental_cost,
        row.opportunity_cost,
        row.risk_cost,
    )
    silent_chaos_score = compute_silent_chaos_score(
        row.duration_zscore_normalized,
        row.transition_rate,
        row.cost_increase_score,
        row.visible_volatility_score,
    )
    silent_chaos_flag = detect_silent_chaos(
        silent_chaos_score,
        row.transition_rate,
        row.cost_increase_score,
        threshold=active.silent_chaos_threshold,
    )
    true_edge = compute_true_edge(
        row.persistence_score,
        conversion_probability,
        row.exit_clarity_score,
    )
    progress_score = compute_progress_score(
        row.persistence_score,
        row.transition_rate,
    )
    loop_risk = compute_loop_risk(
        row.stability_score,
        conversion_probability,
        row.exit_clarity_score,
        symmetry_risk,
    )
    termination = evaluate_termination_gate(
        duration_zscore_normalized=row.duration_zscore_normalized,
        transition_count=row.transition_count,
        holding_cost_score=holding_cost,
        conversion_probability=conversion_probability,
        silent_chaos_flag=silent_chaos_flag,
        loop_risk=loop_risk,
        duration_threshold=active.duration_threshold,
        loop_risk_threshold=active.loop_risk_threshold,
    )
    executable_gate = evaluate_executable_edge_gate(
        row,
        executable_edge=executable_edge,
        conversion_probability=conversion_probability,
        exit_clarity_score=row.exit_clarity_score,
        silent_chaos_flag=silent_chaos_flag,
        thresholds=active,
    )

    warnings = list(row.warnings)
    if row.total_attempts <= 0:
        warnings.append("missing_repeatability_history")
    if row.exit_clarity_score <= 0:
        warnings.append("missing_exit_clarity")

    if row.policy_state.upper() in DO_NOT_DEPLOY_POLICY_STATES:
        extreme_state = DO_NOT_DEPLOY
        action = "BLOCK"
        reason = "Policy state forbids deployment; extreme-state logic cannot override governance."
    elif silent_chaos_flag:
        extreme_state = SILENT_CHAOS
        action = "TERMINATE"
        reason = "High duration, low transition, rising cost, and muted visible volatility indicate silent chaos."
    elif bool(termination["termination_required"]):
        extreme_state = TERMINATE_OR_RECLASSIFY
        action = "TERMINATE"
        reason = "Termination gate fired because duration/cost/loop conditions breached the allowed envelope."
    elif non_converting_equilibrium:
        extreme_state = NON_CONVERTING_EQUILIBRIUM
        action = "DOWNGRADE"
        reason = "Signal strength is being neutralized by symmetry and weak conversion; persistence is not progress."
    elif structural_advantage >= 0.70 and stress_adjusted_repeatability >= 0.65:
        extreme_state = REPEATABLE_EDGE
        action = "PROMOTE" if executable_gate["executable"] else "WAIT"
        reason = "Structural advantage is repeatable and stress-adjusted, making the edge usable rather than one-off."
    elif structural_advantage >= 0.70:
        extreme_state = STRUCTURAL_ADVANTAGE_EDGE
        action = "WAIT"
        reason = "Structural advantage is visible, but repeatability has not yet proved the edge usable."
    elif execution_efficiency >= 0.70:
        extreme_state = HIGH_EFFICIENCY_EDGE
        action = "WAIT"
        reason = "Mechanical execution efficiency is high, but structure/repeatability still need confirmation."
    elif clamp01(row.signal_validity_score) >= 0.60 and clamp01(executable_edge) < active.theta_executable:
        extreme_state = VALID_BUT_NON_EXECUTABLE
        action = "DOWNGRADE"
        reason = "Signal validity is present, but executable edge collapsed under timing, trigger, or exit weakness."
    else:
        extreme_state = NORMAL
        action = "REJECT" if clamp01(row.signal_validity_score) < 0.40 else "WAIT"
        reason = "No extreme-state edge dominates; stay conservative until structure, conversion, and exits improve."

    decision = {
        "action": action,
        "reason": reason,
        "next_required_check": (
            "define_exit_clarity"
            if row.exit_clarity_score < 0.65
            else "confirm_conversion_path"
            if conversion_probability < 0.50
            else "maintain_policy_discipline"
        ),
    }
    scores = {
        "performance_ceiling": round(performance_ceiling, 3),
        "execution_efficiency": round(execution_efficiency, 3),
        "structural_advantage": round(structural_advantage, 3),
        "repeatability": round(repeatability, 3),
        "stress_adjusted_repeatability": round(stress_adjusted_repeatability, 3),
        "usable_edge": round(usable_edge, 3),
        "conversion_probability": round(conversion_probability, 3),
        "exit_clarity": round(clamp01(row.exit_clarity_score), 3),
        "true_edge": round(true_edge, 3),
        "executable_edge": round(executable_edge, 3),
        "net_signal": round(net_signal, 3),
        "symmetry_risk": round(symmetry_risk, 3),
        "equilibrium_score": round(equilibrium_score, 3),
        "silent_chaos_score": round(silent_chaos_score, 3),
        "loop_risk": round(loop_risk, 3),
        "holding_cost": round(holding_cost, 3),
        "progress_score": round(progress_score, 3),
    }
    flags = {
        "policy_veto": row.policy_state.upper() in DO_NOT_DEPLOY_POLICY_STATES,
        "can_execute": bool(executable_gate["executable"]),
        "termination_required": bool(termination["termination_required"]),
        "silent_chaos_flag": silent_chaos_flag,
        "valid_but_non_executable": extreme_state == VALID_BUT_NON_EXECUTABLE,
        "non_converting_equilibrium": non_converting_equilibrium,
    }
    return ExtremeStateEvaluation(
        signal_id=row.signal_id,
        symbol=row.symbol,
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
