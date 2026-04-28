from __future__ import annotations

from .utils import clamp01


def compute_holding_cost(
    time_cost: float,
    mental_cost: float,
    opportunity_cost: float,
    risk_cost: float,
) -> float:
    """HoldingCost = 0.25T + 0.15M + 0.35O + 0.25R."""
    return clamp01(
        (0.25 * clamp01(time_cost))
        + (0.15 * clamp01(mental_cost))
        + (0.35 * clamp01(opportunity_cost))
        + (0.25 * clamp01(risk_cost))
    )


def compute_cost_increase_score(
    current_holding_cost: float,
    previous_holding_cost: float,
) -> float:
    if previous_holding_cost <= 0:
        return clamp01(current_holding_cost)
    ratio = current_holding_cost / previous_holding_cost
    return clamp01(min(ratio, 2.0) / 2.0)
