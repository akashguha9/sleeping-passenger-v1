from __future__ import annotations

from .models import ExtremeStateSignal
from .utils import weighted_sum


def compute_performance_ceiling(signal: ExtremeStateSignal) -> float:
    """PerformanceCeiling = 0.30T + 0.25S + 0.20Ti + 0.25R."""
    repeatability_seed = (
        0.0
        if signal.total_attempts <= 0
        else min(1.0, max(0.0, signal.successful_repetitions / max(signal.total_attempts, 1)))
    )
    return weighted_sum(
        {
            "technique": (signal.technique_score, 0.30),
            "structure": (signal.structure_score, 0.25),
            "timing": (signal.timing_score, 0.20),
            "repeatability": (repeatability_seed, 0.25),
        }
    )


def compute_execution_efficiency(signal: ExtremeStateSignal) -> float:
    """ServeOutput = sequence_quality × timing_precision × transfer_efficiency × contact_quality."""
    return (
        signal.sequence_quality
        * signal.timing_precision
        * signal.transfer_efficiency
        * signal.contact_quality
    )


def compute_structural_advantage(signal: ExtremeStateSignal) -> float:
    """StructuralAdvantage = 0.30A + 0.25G + 0.20T + 0.25C."""
    return weighted_sum(
        {
            "access": (signal.access_score, 0.30),
            "angle": (signal.angle_score, 0.25),
            "timing_access": (signal.timing_access_score, 0.20),
            "constraint_reduction": (signal.constraint_reduction_score, 0.25),
        }
    )
