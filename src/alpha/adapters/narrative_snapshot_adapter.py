"""Offline narrative-snapshot adapter.

Ingests narrative mention snapshots from CSV/JSON-shaped rows or manual
dicts — no network I/O — and computes a bounded narrative-velocity score
with a source-diversity-aware confidence:

    mention_velocity = (mentions_current − mentions_previous)
                       / max(1, mentions_previous)
    source_diversity_score = 100 × min(1, unique_sources / diversity_cap)
    narrative_velocity_score = bounded weighted mean of velocity,
                               sentiment intensity, source quality,
                               source diversity

Row shape:
    {"theme", "source", "timestamp" (ISO), "mention_count",
     "sentiment_score" (−1..1), "source_quality" (0-100),
     "unique_sources" (optional)}
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from src.utils.math_utils import clamp01, clip

DIVERSITY_CAP = 8

_WEIGHTS = {
    "velocity": 0.40,
    "sentiment": 0.20,
    "source_quality": 0.20,
    "diversity": 0.20,
}


def compute_mention_velocity(current: float, previous: float) -> float:
    """(current − previous) / max(1, previous)."""
    return (float(current) - float(previous)) / max(1.0, float(previous))


def _velocity_to_score(velocity: float) -> float:
    """Map an unbounded growth ratio onto 0-100 with 0 growth = 50.

    Saturating transform x/(1+|x|) keeps a 10x spike inside bounds while
    preserving sign and monotonicity.
    """
    return clip(50.0 + 50.0 * (velocity / (1.0 + abs(velocity))), 0.0, 100.0)


def _parse_timestamp(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def summarize_narrative_snapshots(
    rows: list[dict[str, Any]] | None,
    *,
    as_of: str,
    window_days: int = 7,
) -> dict[str, Any]:
    """Summarize snapshot rows into a narrative-velocity signal.

    Rows are split into the current window ``[as_of − window, as_of]`` and
    the previous window before it.  Determinism requires the caller to
    pass ``as_of`` explicitly (ISO timestamp); rows outside both windows
    are ignored.
    """
    missing_inputs: list[str] = []
    anchor = _parse_timestamp(as_of)
    if anchor is None:
        raise ValueError("as_of must be an ISO timestamp")
    window = timedelta(days=int(window_days))

    theme = ""
    current_mentions = 0.0
    previous_mentions = 0.0
    weighted_sentiment = 0.0
    weighted_quality = 0.0
    quality_weight = 0.0
    sources: set[str] = set()
    unique_source_hint = 0
    parsed_rows = 0

    for row in rows or []:
        stamp = _parse_timestamp(row.get("timestamp"))
        if stamp is None:
            continue
        mentions = float(row.get("mention_count") or 0.0)
        if anchor - window <= stamp <= anchor:
            parsed_rows += 1
            theme = theme or str(row.get("theme") or "")
            current_mentions += mentions
            weighted_sentiment += mentions * float(row.get("sentiment_score") or 0.0)
            quality = row.get("source_quality")
            if quality is not None:
                weighted_quality += mentions * clip(float(quality), 0.0, 100.0)
                quality_weight += mentions
            source = str(row.get("source") or "").strip()
            if source:
                sources.add(source)
            unique_source_hint = max(
                unique_source_hint, int(row.get("unique_sources") or 0)
            )
        elif anchor - 2 * window <= stamp < anchor - window:
            previous_mentions += mentions

    if parsed_rows == 0:
        missing_inputs.append("current_window_rows")
    if previous_mentions == 0.0:
        missing_inputs.append("previous_window_mentions")

    mention_velocity = compute_mention_velocity(current_mentions, previous_mentions)
    velocity_score = _velocity_to_score(mention_velocity)
    # Mention-weighted sentiment in [-1, 1] -> intensity 0-100.
    sentiment_intensity = (
        100.0 * clamp01(abs(weighted_sentiment / current_mentions))
        if current_mentions > 0
        else 0.0
    )
    source_quality = (
        weighted_quality / quality_weight if quality_weight > 0 else 50.0
    )
    if quality_weight == 0:
        missing_inputs.append("source_quality")
    unique_sources = max(len(sources), unique_source_hint)
    source_diversity_score = clip(
        100.0 * min(1.0, unique_sources / DIVERSITY_CAP), 0.0, 100.0
    )

    narrative_velocity_score = clip(
        _WEIGHTS["velocity"] * velocity_score
        + _WEIGHTS["sentiment"] * sentiment_intensity
        + _WEIGHTS["source_quality"] * source_quality
        + _WEIGHTS["diversity"] * source_diversity_score,
        0.0,
        100.0,
    )
    # Single-source hype is low-confidence regardless of volume.
    confidence = clip(
        source_diversity_score * (0.5 + 0.5 * source_quality / 100.0), 0.0, 100.0
    )
    return {
        "theme": theme,
        "as_of": as_of,
        "window_days": int(window_days),
        "current_window_mentions": current_mentions,
        "previous_window_mentions": previous_mentions,
        "mention_velocity": mention_velocity,
        "velocity_score": velocity_score,
        "sentiment_intensity": sentiment_intensity,
        "source_quality": source_quality,
        "unique_sources": unique_sources,
        "source_diversity_score": source_diversity_score,
        "narrative_velocity_score": narrative_velocity_score,
        "confidence": confidence,
        "missing_inputs": missing_inputs,
        "explanation": [
            f"Mentions {previous_mentions:.0f} -> {current_mentions:.0f} "
            f"(velocity {mention_velocity:+.2f}) over {window_days}-day windows.",
            f"{unique_sources} unique source(s): diversity "
            f"{source_diversity_score:.0f}/100; single-source hype is "
            "low-confidence regardless of volume.",
            f"Narrative velocity score {narrative_velocity_score:.1f}/100, "
            f"confidence {confidence:.1f}/100.",
        ],
    }
