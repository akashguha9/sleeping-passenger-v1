"""Narrative tracking engine: spread, origin diversity, dirty air, state.

Narratives are weather. Echo chambers are dirty air:

    Dirty Air Score = 1 - (independent_origin_count / total_source_count)

Count origins, not echoes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from src.utils.math_utils import clamp01, safe_div
from src.utils.validation_utils import normalized_score

NARRATIVE_STATES: tuple[str, ...] = (
    "ignored",
    "early_stir",
    "emerging",
    "accelerating",
    "crowded",
    "overheated",
    "decaying",
    "broken",
)

DIRTY_AIR_WARNING_THRESHOLD = 0.70
CONTRADICTION_BREAK_RATIO = 0.40
CROWDED_MENTION_COUNT = 100


@dataclass(slots=True)
class NarrativeStatus:
    """Tracked state of one narrative."""

    narrative: str
    mention_count: int
    origin_count: int
    independent_origin_count: int
    source_quality: float
    narrative_velocity: float
    narrative_acceleration: float
    contradiction_count: int
    contradiction_ratio: float
    dirty_air_score: float
    independent_confirmation_ratio: float
    narrative_state: str
    reason_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def dirty_air_score(independent_origin_count: int, total_source_count: int) -> float:
    """1 - origins/mentions; 37 copied articles from 2 origins -> 0.946."""
    mentions = max(int(total_source_count), 0)
    origins = max(min(int(independent_origin_count), mentions), 0)
    if mentions == 0:
        return 0.0
    return clamp01(1.0 - origins / mentions)


def _classify_state(
    *,
    mention_count: int,
    velocity: float,
    acceleration: float,
    contradiction_ratio: float,
    dirty_air: float,
) -> str:
    if contradiction_ratio >= CONTRADICTION_BREAK_RATIO:
        return "broken"
    if mention_count < 3:
        return "ignored"
    if velocity < -0.05:
        return "decaying"
    if mention_count >= CROWDED_MENTION_COUNT and velocity >= 0.3 and dirty_air >= DIRTY_AIR_WARNING_THRESHOLD:
        return "overheated"
    if mention_count >= CROWDED_MENTION_COUNT:
        return "crowded"
    if velocity >= 0.2 and acceleration > 0.05:
        return "accelerating"
    if mention_count < 10:
        return "early_stir"
    return "emerging"


def track_narrative(
    *,
    narrative: str,
    mention_count: int,
    origin_count: int,
    independent_origin_count: int,
    source_quality: float,
    narrative_velocity: float,
    narrative_acceleration: float,
    contradiction_count: int = 0,
) -> NarrativeStatus:
    """Score one narrative's spread quality and lifecycle state.

    ``narrative_velocity``/``narrative_acceleration`` are normalized rates
    in [-1, 1]; counts are raw integers.
    """
    mentions = max(int(mention_count), 0)
    origins = max(min(int(origin_count), mentions if mentions else int(origin_count)), 0)
    independent = max(min(int(independent_origin_count), origins if origins else 0), 0)
    contradictions = max(int(contradiction_count), 0)
    velocity = max(-1.0, min(1.0, float(narrative_velocity)))
    acceleration = max(-1.0, min(1.0, float(narrative_acceleration)))
    quality = normalized_score(source_quality)

    dirty_air = dirty_air_score(independent, mentions)
    confirmation_ratio = clamp01(safe_div(independent, mentions)) if mentions else 0.0
    contradiction_ratio = clamp01(safe_div(contradictions, mentions)) if mentions else 0.0

    state = _classify_state(
        mention_count=mentions,
        velocity=velocity,
        acceleration=acceleration,
        contradiction_ratio=contradiction_ratio,
        dirty_air=dirty_air,
    )

    reasons: list[str] = [f"NARRATIVE_{state.upper()}"]
    if dirty_air >= DIRTY_AIR_WARNING_THRESHOLD and mentions >= 5:
        reasons.append("DIRTY_AIR_WARNING")
    if independent >= 3 and quality >= 0.6:
        reasons.append("INDEPENDENTLY_CONFIRMED")
    if contradiction_ratio >= CONTRADICTION_BREAK_RATIO:
        reasons.append("CONTRADICTION_PRESSURE")

    return NarrativeStatus(
        narrative=str(narrative),
        mention_count=mentions,
        origin_count=origins,
        independent_origin_count=independent,
        source_quality=quality,
        narrative_velocity=velocity,
        narrative_acceleration=acceleration,
        contradiction_count=contradictions,
        contradiction_ratio=contradiction_ratio,
        dirty_air_score=dirty_air,
        independent_confirmation_ratio=confirmation_ratio,
        narrative_state=state,
        reason_codes=reasons,
    )
