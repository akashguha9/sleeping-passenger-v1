"""Probability-shift score for prediction-market events."""
from __future__ import annotations


def probability_shift_score(prev_p: float | None, curr_p: float | None) -> float:
    if prev_p is None or curr_p is None:
        return 0.0
    delta = abs(float(curr_p) - float(prev_p))
    return max(0.0, min(1.0, delta * 2.0))  # 50pp move → 1.0
