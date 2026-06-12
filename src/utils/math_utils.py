"""Math helpers for bounded scoring and safe arithmetic."""

from __future__ import annotations


def clip(value: float, minimum: float, maximum: float) -> float:
    """Clamp ``value`` to the inclusive ``[minimum, maximum]`` range.

    NaN clamps to the MINIMUM (the conservative bound): NaN defeats
    comparisons, so the naive ``max(lo, min(hi, x))`` resolves it to
    the maximum — turning a poisoned input into maximal optimism.
    """
    number = float(value)
    if number != number:  # NaN is the only value unequal to itself
        return float(minimum)
    return max(minimum, min(maximum, number))


def clamp01(value: float) -> float:
    """Clamp a value to the inclusive ``[0.0, 1.0]`` range."""
    return clip(value, 0.0, 1.0)


def safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Return a safe division result without raising on zero denominators."""
    if abs(float(denominator)) < 1e-12:
        return float(default)
    return float(numerator) / float(denominator)
