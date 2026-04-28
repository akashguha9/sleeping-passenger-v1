from __future__ import annotations

from .utils import clamp01


def compute_conversion_probability(
    trigger_presence_score: float,
    timing_window_score: float,
    opponent_weakness_score: float,
) -> float:
    """ConversionScore = TriggerPresence × TimingWindow × OpponentWeakness."""
    return clamp01(
        clamp01(trigger_presence_score)
        * clamp01(timing_window_score)
        * clamp01(opponent_weakness_score)
    )


def compute_executable_edge(
    signal_strength: float,
    conversion_trigger_score: float,
    timing_window_score: float,
    exit_clarity_score: float,
) -> float:
    """ExecutableEdge = SignalStrength × ConversionTrigger × TimingWindow × ExitClarity."""
    return clamp01(
        clamp01(signal_strength)
        * clamp01(conversion_trigger_score)
        * clamp01(timing_window_score)
        * clamp01(exit_clarity_score)
    )
