from __future__ import annotations

from .utils import clamp01


def compute_silent_chaos_score(
    duration_zscore_normalized: float,
    no_transition_score: float,
    cost_increase_score: float,
    volatility_score: float,
) -> float:
    """SilentChaos = 0.35*HighDuration + 0.25*NoTransition + 0.25*RisingCost + 0.15*LowVolatility."""
    return clamp01(
        (0.35 * clamp01(duration_zscore_normalized))
        + (0.25 * clamp01(no_transition_score))
        + (0.25 * clamp01(cost_increase_score))
        + (0.15 * (1.0 - clamp01(volatility_score)))
    )


def detect_silent_chaos(
    silent_chaos_score: float,
    no_transition_score: float,
    cost_increase_score: float,
    *,
    threshold: float = 0.70,
) -> bool:
    return (
        clamp01(silent_chaos_score) >= threshold
        and clamp01(no_transition_score) >= 0.75
        and clamp01(cost_increase_score) >= 0.50
    )


def compute_progress_score(persistence_score: float, state_change_score: float) -> float:
    """Progress = Persistence × StateChange."""
    return clamp01(clamp01(persistence_score) * clamp01(state_change_score))
