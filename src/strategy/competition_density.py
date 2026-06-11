"""Competition Density Engine: greatness is pressure-adjusted.

Nadal's achievements weigh more because of who he had to beat. A company
growing moderately in a brutal field may be stronger than one growing
fast against weak opponents.

    Competition_Adjusted_Strength =
        Performance × Era_Difficulty_Multiplier × Opponent_Quality_Multiplier
        × Evidence_Confidence − Fragility_Penalty
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from src.utils.math_utils import clamp01, clip
from src.utils.validation_utils import normalized_score


@dataclass(slots=True)
class CompetitionAssessment:
    """Pressure-adjusted strength verdict."""

    raw_performance: float
    era_difficulty: float
    opponent_quality: float
    era_multiplier: float
    opponent_multiplier: float
    win_quality_score: float
    competition_adjusted_strength: float
    main_competitors: list[str] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def assess_competition_density(
    *,
    raw_performance: float,
    era_difficulty: float = 0.5,
    opponent_quality: float = 0.5,
    evidence_confidence: float = 0.5,
    fragility: float = 0.0,
    main_competitors: list[str] | None = None,
) -> CompetitionAssessment:
    """Adjust raw performance by competitive pressure (all inputs 0–1).

    Multipliers are centered at 1.0 for a neutral (0.5) field: a brutal
    era amplifies performance up to ×1.4; an easy era discounts it down
    to ×0.6. Winning where nobody fights back proves little.
    """
    performance = normalized_score(raw_performance)
    era = normalized_score(era_difficulty)
    opponents = normalized_score(opponent_quality)
    confidence = normalized_score(evidence_confidence)
    fragility_penalty = normalized_score(fragility) * 0.3

    era_multiplier = 0.6 + 0.8 * era          # [0.6, 1.4]
    opponent_multiplier = 0.6 + 0.8 * opponents
    win_quality = clamp01(performance * opponents)

    adjusted = clip(
        performance * era_multiplier * opponent_multiplier
        * (0.5 + 0.5 * confidence)
        - fragility_penalty,
        0.0,
        1.0,
    )

    rationale = [
        f"performance {performance:.2f} × era ×{era_multiplier:.2f} × "
        f"opponents ×{opponent_multiplier:.2f} × confidence factor "
        f"{0.5 + 0.5 * confidence:.2f} − fragility {fragility_penalty:.2f} "
        f"= {adjusted:.2f}",
    ]
    if era < 0.35 and performance > 0.7:
        rationale.append(
            "strong raw numbers in an easy field — pressure-adjusted "
            "strength discounted (winning unopposed proves little)"
        )
    if era > 0.65 and performance >= 0.4:
        rationale.append(
            "respectable performance under brutal competition — "
            "pressure-adjusted strength boosted"
        )

    return CompetitionAssessment(
        raw_performance=performance,
        era_difficulty=era,
        opponent_quality=opponents,
        era_multiplier=era_multiplier,
        opponent_multiplier=opponent_multiplier,
        win_quality_score=win_quality,
        competition_adjusted_strength=adjusted,
        main_competitors=list(main_competitors or []),
        rationale=rationale,
    )
