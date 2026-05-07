"""Validation and normalization helpers for scoring inputs."""

from __future__ import annotations

from typing import Any

from .math_utils import clamp01


def coerce_float(value: Any, default: float = 0.0) -> float:
    """Best-effort float coercion with a conservative default."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def normalized_score(value: Any, default: float = 0.0) -> float:
    """Coerce and clamp a numeric value into the normalized ``[0, 1]`` range."""
    return clamp01(coerce_float(value, default))


def listify(value: Any) -> list[Any]:
    """Return ``value`` as a list without mutating caller-owned objects."""
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    return [value]
