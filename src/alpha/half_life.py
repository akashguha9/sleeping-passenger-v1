"""Module C — half-life signal decay engine.

Every signal decays:  S(t) = S0 * e^(-lambda * t),  t_1/2 = ln(2) / lambda.

A viral post must not be weighted like a regulatory approval or a
human-necessity demand cycle, so each signal type carries a baseline
half-life that source quality, proof strength, and recurrence can stretch
or shrink within a bounded multiplier.
"""

from __future__ import annotations

import math

from src.utils.math_utils import clamp01, clip

# Baseline half-life per signal type, in days.  Ranges from the framework:
# viral posts decay in hours-days; human necessity decays on a
# civilizational clock.
SIGNAL_HALF_LIFE_DAYS: dict[str, float] = {
    "viral_social_post": 2.0,
    "newspaper_article": 10.0,
    "earnings_surprise": 45.0,
    "new_contract": 120.0,
    "regulatory_approval": 540.0,
    "infrastructure_cycle": 1825.0,
    "human_necessity": 18250.0,
}

_DEFAULT_SIGNAL_TYPE = "newspaper_article"

# Calibration multiplier bounds: strong sourcing/proof/recurrence can at
# most halve the decay rate (1.5x half-life); weak ones at most double it
# (0.5x half-life).  TODO: calibrate empirically once outcome data exists.
_MIN_MULTIPLIER = 0.5
_MAX_MULTIPLIER = 1.5


def half_life_to_lambda(half_life_days: float) -> float:
    """lambda = ln(2) / t_1/2.  Half-life must be positive."""
    if half_life_days <= 0:
        raise ValueError("half_life_days must be positive")
    return math.log(2.0) / float(half_life_days)


def decay_signal_strength(
    initial_strength: float,
    elapsed_days: float,
    half_life_days: float,
    *,
    signal_type: str = "unspecified",
) -> dict[str, object]:
    """Decay ``initial_strength`` over ``elapsed_days``: S(t) = S0·e^(−λt)."""
    if elapsed_days < 0:
        raise ValueError("elapsed_days must be non-negative")
    lam = half_life_to_lambda(half_life_days)
    current = float(initial_strength) * math.exp(-lam * float(elapsed_days))
    return {
        "initial_strength": float(initial_strength),
        "current_strength": current,
        "elapsed_days": float(elapsed_days),
        "half_life_days": float(half_life_days),
        "lambda": lam,
        "signal_type": signal_type,
        "decay_explanation": (
            f"S(t)=S0*e^(-lambda*t) with t_1/2={half_life_days:.1f}d "
            f"(lambda={lam:.6f}/day): strength {float(initial_strength):.3f} "
            f"-> {current:.3f} after {float(elapsed_days):.1f} days."
        ),
    }


def estimate_half_life(
    signal_type: str,
    *,
    source_quality: float = 0.5,
    proof_strength: float = 0.5,
    recurrence: float = 0.5,
) -> dict[str, object]:
    """Estimate a half-life for a signal from its type and qualifiers.

    ``source_quality``, ``proof_strength``, and ``recurrence`` are fractions
    in [0, 1]; 0.5 is neutral (baseline half-life for the type).  Unknown
    signal types fall back to the newspaper-article baseline and are
    reported in ``missing_inputs``.
    """
    missing_inputs: list[str] = []
    base = SIGNAL_HALF_LIFE_DAYS.get(signal_type)
    if base is None:
        missing_inputs.append(f"unknown signal_type '{signal_type}'")
        base = SIGNAL_HALF_LIFE_DAYS[_DEFAULT_SIGNAL_TYPE]
    sq = clamp01(source_quality)
    ps = clamp01(proof_strength)
    rc = clamp01(recurrence)
    # Neutral inputs (all 0.5) give multiplier 1.0.
    multiplier = clip(
        _MIN_MULTIPLIER
        + (_MAX_MULTIPLIER - _MIN_MULTIPLIER) * (sq + ps + rc) / 3.0,
        _MIN_MULTIPLIER,
        _MAX_MULTIPLIER,
    )
    half_life_days = base * multiplier
    return {
        "signal_type": signal_type,
        "base_half_life_days": base,
        "half_life_days": half_life_days,
        "lambda": half_life_to_lambda(half_life_days),
        "multiplier": multiplier,
        "missing_inputs": missing_inputs,
        "decay_explanation": (
            f"Baseline t_1/2={base:.1f}d for '{signal_type}' scaled by "
            f"{multiplier:.2f} from source quality {sq:.2f}, proof {ps:.2f}, "
            f"recurrence {rc:.2f}."
        ),
    }
