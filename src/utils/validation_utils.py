"""Validation and normalization helpers for scoring inputs."""

from __future__ import annotations

import math
from typing import Any

from .math_utils import clamp01


def coerce_float(value: Any, default: float = 0.0) -> float:
    """Best-effort float coercion with a conservative default.

    Non-finite values (NaN, ±Inf) coerce to the DEFAULT, never pass
    through: NaN defeats comparisons, so a downstream clamp would
    resolve it to the OPTIMISTIC bound — a single NaN in a payload
    could walk past every conservative-wins gate. Garbage is treated
    as missing, and absence of evidence is not evidence.
    """
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    if not math.isfinite(result):
        return float(default)
    return result


def normalized_score(value: Any, default: float = 0.0) -> float:
    """Coerce and clamp a numeric value into the normalized ``[0, 1]`` range."""
    return clamp01(coerce_float(value, default))


def section_dict(value: Any) -> dict:
    """Return ``value`` if it is a dict, else an empty dict.

    Payload sections are caller-controlled: a string or list where a
    dict belongs must degrade to "section absent" (conservative), never
    crash an engine mid-pipeline.
    """
    return value if isinstance(value, dict) else {}


def listify(value: Any) -> list[Any]:
    """Return ``value`` as a list without mutating caller-owned objects."""
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    return [value]
