from __future__ import annotations

from .utils import clamp01


def compute_net_signal(
    own_signal_strength: float,
    opponent_counter_signal_strength: float,
) -> float:
    return float(own_signal_strength) - float(opponent_counter_signal_strength)


def compute_symmetry_risk(
    own_signal_strength: float,
    opponent_counter_signal_strength: float,
) -> float:
    """symmetry_risk = 1 - abs(own - opponent)."""
    delta = abs(clamp01(own_signal_strength) - clamp01(opponent_counter_signal_strength))
    return clamp01(1.0 - delta)


def compute_equilibrium_score(
    persistence_score: float,
    stability_score: float,
    conversion_probability: float,
    transition_rate: float,
) -> float:
    """NonConvertingEquilibrium = HighPersistence + HighStability + LowConversion + LowTransition."""
    return clamp01(
        (0.30 * clamp01(persistence_score))
        + (0.25 * clamp01(stability_score))
        + (0.25 * (1.0 - clamp01(conversion_probability)))
        + (0.20 * (1.0 - clamp01(transition_rate)))
    )


def detect_non_converting_equilibrium(
    symmetry_risk: float,
    conversion_probability: float,
    equilibrium_score: float,
    *,
    high_symmetry_threshold: float = 0.75,
    equilibrium_threshold: float = 0.70,
) -> bool:
    return (
        clamp01(symmetry_risk) >= high_symmetry_threshold
        and clamp01(conversion_probability) <= 0.35
    ) or clamp01(equilibrium_score) >= equilibrium_threshold
