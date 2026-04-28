from __future__ import annotations

from .utils import clamp01


def compute_loop_risk(
    stability_score: float,
    conversion_probability: float,
    exit_clarity_score: float,
    symmetry_risk: float,
) -> float:
    """LoopRisk = Stability × NoExit × LowTransition proxy via symmetry."""
    return clamp01(
        clamp01(stability_score)
        * (1.0 - clamp01(conversion_probability))
        * (1.0 - clamp01(exit_clarity_score))
        * clamp01(symmetry_risk)
    )


def evaluate_termination_gate(
    *,
    duration_zscore_normalized: float,
    transition_count: int,
    holding_cost_score: float,
    conversion_probability: float,
    silent_chaos_flag: bool,
    loop_risk: float,
    duration_threshold: float = 0.80,
    conversion_low_threshold: float = 0.30,
    holding_cost_threshold: float = 0.70,
    loop_risk_threshold: float = 0.65,
) -> dict[str, object]:
    duration_trigger = (
        clamp01(duration_zscore_normalized) >= duration_threshold and int(transition_count) <= 0
    )
    cost_trigger = (
        clamp01(holding_cost_score) >= holding_cost_threshold
        and clamp01(conversion_probability) <= conversion_low_threshold
    )
    loop_trigger = clamp01(loop_risk) >= loop_risk_threshold
    triggered = bool(silent_chaos_flag or duration_trigger or cost_trigger or loop_trigger)
    return {
        "termination_required": triggered,
        "duration_trigger": duration_trigger,
        "cost_trigger": cost_trigger,
        "loop_trigger": loop_trigger,
    }
