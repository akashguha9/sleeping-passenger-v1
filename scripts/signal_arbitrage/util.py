"""Shared pure helpers for the signal_arbitrage package.

No I/O, no network, no DB. Deterministic. Everything here is a small,
side-effect-free numeric or string helper reused across the layers.
"""
from __future__ import annotations

from typing import Iterable


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp ``x`` into ``[lo, hi]``."""
    return max(lo, min(hi, x))


def r3(x: float) -> float:
    """Round to 3 dp (the package-wide score precision)."""
    return round(float(x), 3)


def safe_ratio(num: float, den: float, default: float = 0.0) -> float:
    """``num/den`` with a zero-denominator fallback."""
    if den == 0:
        return default
    return num / den


def mean(xs: Iterable[float], default: float = 0.0) -> float:
    xs = list(xs)
    if not xs:
        return default
    return sum(xs) / len(xs)


def weighted(components: dict[str, float], weights: dict[str, float]) -> float:
    """Weighted sum over the keys present in ``weights`` (missing → 0)."""
    return sum(weights[k] * components.get(k, 0.0) for k in weights)
