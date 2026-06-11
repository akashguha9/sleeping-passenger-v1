"""Prediction-market narrative radar.

Prediction markets are radar, not the trade: a probability shock flags a
belief shift upstream of equities. The shock score is the literal product

    Narrative Shock =
        |probability_delta| * velocity * market_importance
        * market_liquidity * cross_source_confirmation

with every term normalized to [0, 1], so the score is also in [0, 1] and
thresholds are calibrated low.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from src.utils.math_utils import clamp01
from src.utils.validation_utils import normalized_score

# Product-of-five-fractions thresholds (deliberately small magnitudes).
SHOCK_RADAR_THRESHOLD = 0.02
SHOCK_STRONG_THRESHOLD = 0.08


@dataclass(slots=True)
class NarrativeShock:
    """One scored prediction-market belief shift."""

    market_name: str
    probability_before: float
    probability_after: float
    probability_delta: float
    velocity: float
    market_importance: float
    market_liquidity: float
    cross_source_confirmation: float
    narrative_shock_score: float
    direction: str
    affected_themes: list[str] = field(default_factory=list)
    affected_sectors: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def score_narrative_shock(
    *,
    market_name: str,
    probability_before: float,
    probability_after: float,
    velocity: float,
    market_importance: float,
    market_liquidity: float,
    cross_source_confirmation: float,
    affected_themes: list[str] | None = None,
    affected_sectors: list[str] | None = None,
) -> NarrativeShock:
    """Score a prediction-market probability move as a narrative shock.

    Probabilities are fractions in [0, 1] (e.g. 0.27 -> 0.54).
    """
    before = clamp01(probability_before)
    after = clamp01(probability_after)
    delta = after - before
    vel = normalized_score(velocity)
    importance = normalized_score(market_importance)
    liquidity = normalized_score(market_liquidity)
    confirmation = normalized_score(cross_source_confirmation)

    shock = abs(delta) * vel * importance * liquidity * confirmation

    reasons: list[str] = []
    if shock >= SHOCK_STRONG_THRESHOLD:
        reasons.append("STRONG_NARRATIVE_SHOCK")
    elif shock >= SHOCK_RADAR_THRESHOLD:
        reasons.append("RADAR_CONTACT")
    else:
        reasons.append("BELOW_RADAR_THRESHOLD")
    if liquidity < 0.2:
        reasons.append("THIN_PREDICTION_MARKET")
    if confirmation < 0.3:
        reasons.append("UNCONFIRMED_BELIEF_SHIFT")
    reasons.append("RADAR_NOT_TRADE")

    return NarrativeShock(
        market_name=str(market_name),
        probability_before=before,
        probability_after=after,
        probability_delta=delta,
        velocity=vel,
        market_importance=importance,
        market_liquidity=liquidity,
        cross_source_confirmation=confirmation,
        narrative_shock_score=shock,
        direction="rising" if delta > 0 else ("falling" if delta < 0 else "flat"),
        affected_themes=list(affected_themes or []),
        affected_sectors=list(affected_sectors or []),
        reason_codes=reasons,
    )
