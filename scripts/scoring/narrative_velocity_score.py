"""Narrative-velocity score skeleton.

Real implementation would compare current mention rate to a rolling baseline.
For the MVP we expose a deterministic helper that callers seed with counts.
"""
from __future__ import annotations


def narrative_velocity_score(current_mentions: float, baseline_mentions: float) -> float:
    if baseline_mentions <= 0:
        return 0.0
    ratio = current_mentions / baseline_mentions
    # Squash to [0, 1] with a soft cap at 5x baseline.
    return max(0.0, min(1.0, (ratio - 1.0) / 4.0))
