"""Theme / policy / event mapper: narrative -> investable theme + track condition.

    Track Condition =
        macro_support + sector_momentum + policy_tailwind
        + liquidity_environment + risk_appetite
        - regulatory_friction - crowding - valuation_heat

All components are normalized [0, 1]; the raw sum lives in [-3, +5] and is
also exposed normalized to [0, 1] for downstream multipliers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from src.utils.math_utils import clamp01
from src.utils.validation_utils import normalized_score

TRACK_GREEN_THRESHOLD = 0.60
TRACK_RED_THRESHOLD = 0.40


@dataclass(slots=True)
class ThemeAssessment:
    """One narrative mapped onto an investable theme with track condition."""

    theme: str
    source_narrative: str
    policy_fit: float
    macro_fit: float
    sector_momentum: float
    liquidity_support: float
    risk_appetite: float
    valuation_heat: float
    crowding: float
    regulatory_friction: float
    track_condition_raw: float
    track_condition_score: float
    candidate_sectors: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def score_track_condition(
    *,
    macro_support: float,
    sector_momentum: float,
    policy_tailwind: float,
    liquidity_environment: float,
    risk_appetite: float,
    regulatory_friction: float,
    crowding: float,
    valuation_heat: float,
) -> tuple[float, float]:
    """Return (raw, normalized) track condition.

    raw in [-3, +5]; normalized = (raw + 3) / 8 in [0, 1].
    """
    raw = (
        normalized_score(macro_support)
        + normalized_score(sector_momentum)
        + normalized_score(policy_tailwind)
        + normalized_score(liquidity_environment)
        + normalized_score(risk_appetite)
        - normalized_score(regulatory_friction)
        - normalized_score(crowding)
        - normalized_score(valuation_heat)
    )
    return raw, clamp01((raw + 3.0) / 8.0)


def map_theme(
    *,
    theme: str,
    source_narrative: str = "",
    policy_fit: float,
    macro_fit: float,
    sector_momentum: float,
    liquidity_support: float,
    risk_appetite: float = 0.5,
    valuation_heat: float,
    crowding: float,
    regulatory_friction: float,
    candidate_sectors: list[str] | None = None,
) -> ThemeAssessment:
    """Convert a narrative into a scored investable theme."""
    raw, normalized = score_track_condition(
        macro_support=macro_fit,
        sector_momentum=sector_momentum,
        policy_tailwind=policy_fit,
        liquidity_environment=liquidity_support,
        risk_appetite=risk_appetite,
        regulatory_friction=regulatory_friction,
        crowding=crowding,
        valuation_heat=valuation_heat,
    )

    reasons: list[str] = []
    if normalized >= TRACK_GREEN_THRESHOLD:
        reasons.append("TRACK_CONDITION_SUPPORTIVE")
    elif normalized < TRACK_RED_THRESHOLD:
        reasons.append("TRACK_CONDITION_HOSTILE")
    else:
        reasons.append("TRACK_CONDITION_NEUTRAL")
    if normalized_score(valuation_heat) >= 0.7:
        reasons.append("VALUATION_HEAT_WARNING")
    if normalized_score(crowding) >= 0.7:
        reasons.append("CROWDED_THEME")

    return ThemeAssessment(
        theme=str(theme),
        source_narrative=str(source_narrative),
        policy_fit=normalized_score(policy_fit),
        macro_fit=normalized_score(macro_fit),
        sector_momentum=normalized_score(sector_momentum),
        liquidity_support=normalized_score(liquidity_support),
        risk_appetite=normalized_score(risk_appetite),
        valuation_heat=normalized_score(valuation_heat),
        crowding=normalized_score(crowding),
        regulatory_friction=normalized_score(regulatory_friction),
        track_condition_raw=raw,
        track_condition_score=normalized,
        candidate_sectors=list(candidate_sectors or []),
        reason_codes=reasons,
    )
