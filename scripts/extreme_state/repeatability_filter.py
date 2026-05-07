from __future__ import annotations

from .models import ExtremeStateSignal
from .utils import clamp01


def compute_repeatability(signal: ExtremeStateSignal, alpha: float = 1.0) -> float:
    """Repeatability = SuccessfulRepetitions / max(TotalAttempts, 1)."""
    del alpha
    return clamp01(signal.successful_repetitions / max(signal.total_attempts, 1))


def compute_stress_adjusted_repeatability(
    repeatability: float,
    stress_survival_score: float,
) -> float:
    return clamp01(repeatability * clamp01(stress_survival_score))


def compute_usable_edge(structural_advantage_score: float, repeatability_score: float) -> float:
    """UsableEdge = StructuralAdvantage × Repeatability."""
    return clamp01(structural_advantage_score * repeatability_score)


def compute_true_edge(
    persistence_score: float,
    conversion_probability: float,
    exit_clarity_score: float,
) -> float:
    """TrueEdge = Persistence × ConversionProbability × ExitClarity."""
    return clamp01(
        clamp01(persistence_score)
        * clamp01(conversion_probability)
        * clamp01(exit_clarity_score)
    )
