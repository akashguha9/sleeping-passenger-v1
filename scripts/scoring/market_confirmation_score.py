"""Market-confirmation score skeleton.

Given a directional hypothesis (+1 / -1) and an observed price-change, return
a value in [0, 1] indicating whether the market moved with the signal.
"""
from __future__ import annotations


def market_confirmation_score(direction: int, price_change: float | None) -> float:
    if price_change is None or direction == 0:
        return 0.0
    aligned = price_change * direction
    if aligned <= 0:
        return 0.0
    return max(0.0, min(1.0, aligned * 20.0))  # 5% aligned move → 1.0
