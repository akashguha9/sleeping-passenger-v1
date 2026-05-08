"""Cross-source contradiction score skeleton.

Given a set of source -> direction observations, return how much they disagree
in [0, 1]. 0 = unanimous, 1 = perfectly split.
"""
from __future__ import annotations

from collections.abc import Iterable


def contradiction_score(directions: Iterable[int]) -> float:
    dirs = [d for d in directions if d in (-1, 0, 1)]
    if not dirs:
        return 0.0
    pos = sum(1 for d in dirs if d > 0)
    neg = sum(1 for d in dirs if d < 0)
    if pos == 0 or neg == 0:
        return 0.0
    minority = min(pos, neg)
    return max(0.0, min(1.0, (2.0 * minority) / (pos + neg)))
