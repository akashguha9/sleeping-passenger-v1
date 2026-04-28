from __future__ import annotations

from .utils import clamp01


def compute_silent_chaos_score(
    duration_zscore_normalized: float,
    transition_rate: float,
    cost_increase_score: float,
    visible_volatility_score: float,
) -> float:
    """SilentChaos = HighDuration + LowTransition + RisingCost - VisibleVolatility."""
    return clamp01(
        (0.30 * clamp01(duration_zscore_normalized))
        + (0.25 * (1.0 - clamp01(transition_rate)))
        + (0.25 * clamp01(cost_increase_score))
        + (0.20 * (1.0 - clamp01(visible_volatility_score)))
    )


def detect_silent_chaos(
    silent_chaos_score: float,
    transition_rate: float,
    cost_increase_score: float,
    *,
    threshold: float = 0.70,
) -> bool:
    return (
        clamp01(silent_chaos_score) >= threshold
        and clamp01(transition_rate) <= 0.25
        and clamp01(cost_increase_score) >= 0.50
    )


def compute_progress_score(persistence_score: float, state_change_score: float) -> float:
    """Progress = Persistence × StateChange."""
    return clamp01(clamp01(persistence_score) * clamp01(state_change_score))
