from __future__ import annotations

from typing import Iterable


def clamp01(value: float | int | None) -> float:
    """Clamp a numeric value into the normalized [0, 1] range."""
    try:
        numeric = float(value or 0.0)
    except (TypeError, ValueError):
        numeric = 0.0
    return max(0.0, min(1.0, numeric))


def safe_div(numerator: float | int, denominator: float | int, default: float = 0.0) -> float:
    try:
        den = float(denominator)
        if abs(den) <= 1e-12:
            return float(default)
        return float(numerator) / den
    except (TypeError, ValueError, ZeroDivisionError):
        return float(default)


def weighted_sum(parts: dict[str, tuple[float, float]]) -> float:
    total = 0.0
    for _, (value, weight) in parts.items():
        total += clamp01(value) * max(0.0, float(weight))
    return clamp01(total)


def mean(values: Iterable[float]) -> float:
    rows = [float(value) for value in values]
    if not rows:
        return 0.0
    return sum(rows) / len(rows)
