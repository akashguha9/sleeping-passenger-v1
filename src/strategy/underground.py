"""Underground Breakout Engine: hidden is not automatically valuable.

Undercovered ≠ mispriced. A buried signal must prove originality, cult
traction, a solvable distribution constraint, a breakout catalyst, and a
monetization path — otherwise it is buried for a reason.

    Buried_Gem_Score = Originality + Cult_Traction + Solvable_Distribution
                       + Breakout_Catalyst + Monetization_Path
                       − Buried_Noise_Risk
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from src.utils.math_utils import clamp01, clip
from src.utils.validation_utils import normalized_score

UNDERGROUND_VERDICTS: tuple[str, ...] = (
    "RISING_UNDERGROUND",
    "BURIED_GEM_WATCHLIST",
    "CULT_SIGNAL_NEEDS_DISTRIBUTION",
    "ONE_HIT_NOISE",
    "BURIED_FOR_REASON",
    "GATEKEEPER_BLOCKED",
    "BREAKOUT_READY",
    "NOT_UNDERGROUND",
)

# Attention half-life below this (days) marks a viral one-hit candidate.
VIRAL_HALF_LIFE_DAYS = 30.0


@dataclass(slots=True)
class UndergroundAssessment:
    """Rise-or-bury verdict for an undercovered candidate."""

    underground_status: bool
    verdict: str
    buried_gem_score: float
    buried_noise_risk: float
    originality_score: float
    cult_traction_score: float
    distribution_solvable: float
    breakout_catalyst_score: float
    monetization_path_score: float
    attention_half_life_days: float
    viral_decay_risk: float
    gatekeeper_risk: float
    attention_to_revenue_conversion: float
    temporary_pavilion: bool
    rationale: list[str] = field(default_factory=list)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def assess_underground(
    *,
    visibility: float = 0.5,
    originality: float = 0.0,
    cult_traction: float = 0.0,
    repeat_usage: float = 0.0,
    distribution_constraint_solvable: float = 0.0,
    breakout_catalyst: float = 0.0,
    monetization_path: float = 0.0,
    attention_half_life_days: float = 365.0,
    gatekeeper_risk: float = 0.0,
    attention_to_revenue_conversion: float = 0.0,
) -> UndergroundAssessment:
    """Classify an undercovered signal (inputs 0–1 unless noted).

    ``visibility`` above 0.6 means the name is not underground at all and
    this engine abstains.
    """
    vis = normalized_score(visibility, 0.5)
    if vis > 0.6:
        return UndergroundAssessment(
            underground_status=False,
            verdict="NOT_UNDERGROUND",
            buried_gem_score=0.0,
            buried_noise_risk=0.0,
            originality_score=normalized_score(originality),
            cult_traction_score=normalized_score(cult_traction),
            distribution_solvable=normalized_score(distribution_constraint_solvable),
            breakout_catalyst_score=normalized_score(breakout_catalyst),
            monetization_path_score=normalized_score(monetization_path),
            attention_half_life_days=max(float(attention_half_life_days), 0.0),
            viral_decay_risk=0.0,
            gatekeeper_risk=normalized_score(gatekeeper_risk),
            attention_to_revenue_conversion=normalized_score(
                attention_to_revenue_conversion
            ),
            temporary_pavilion=False,
            rationale=["visibility too high — not an underground candidate"],
        )

    orig = normalized_score(originality)
    cult = clamp01(
        0.6 * normalized_score(cult_traction) + 0.4 * normalized_score(repeat_usage)
    )
    distribution = normalized_score(distribution_constraint_solvable)
    catalyst = normalized_score(breakout_catalyst)
    monetization = clamp01(
        0.6 * normalized_score(monetization_path)
        + 0.4 * normalized_score(attention_to_revenue_conversion)
    )
    gatekeeper = normalized_score(gatekeeper_risk)
    half_life = max(float(attention_half_life_days), 0.0)
    viral_decay = clamp01(
        1.0 - half_life / VIRAL_HALF_LIFE_DAYS
    ) if half_life < VIRAL_HALF_LIFE_DAYS else 0.0

    noise_risk = clamp01(
        0.4 * (1.0 - cult) + 0.3 * (1.0 - monetization) + 0.3 * viral_decay
    )
    gem = clip(
        (orig + cult + distribution + catalyst + monetization) / 5.0
        - 0.5 * noise_risk,
        0.0,
        1.0,
    ) * 10.0

    temporary_pavilion = viral_decay > 0.5

    rationale: list[str] = []
    if temporary_pavilion:
        rationale.append(
            f"attention half-life {half_life:.0f}d < {VIRAL_HALF_LIFE_DAYS:.0f}d "
            "— Temporary Pavilion, not a durable thesis"
        )

    # Deterministic verdict ladder (most specific condition first).
    if temporary_pavilion and repeat_usage < 0.3:
        verdict = "ONE_HIT_NOISE"
        rationale.append("viral spike without repeat usage — one-hit noise")
    elif gatekeeper >= 0.7:
        verdict = "GATEKEEPER_BLOCKED"
        rationale.append("gatekeeper risk dominates — breakout path is controlled")
    elif cult < 0.3 and catalyst < 0.3 and monetization < 0.3:
        verdict = "BURIED_FOR_REASON"
        rationale.append(
            "weak traction, no catalyst, no monetization — buried noise, "
            "not buried genius"
        )
    elif cult >= 0.5 and distribution < 0.35:
        verdict = "CULT_SIGNAL_NEEDS_DISTRIBUTION"
        rationale.append("real cult traction but the distribution constraint is unsolved")
    elif gem >= 7.2 and catalyst >= 0.6 and distribution >= 0.5:
        verdict = "BREAKOUT_READY"
        rationale.append("originality + traction + solvable distribution + catalyst align")
    elif gem >= 5.5:
        verdict = "RISING_UNDERGROUND"
    else:
        verdict = "BURIED_GEM_WATCHLIST"
        rationale.append("credible quality but incomplete breakout path — watchlist")

    rationale.append(
        f"buried_gem {gem:.1f}/10 from originality {orig:.2f}, cult {cult:.2f}, "
        f"distribution {distribution:.2f}, catalyst {catalyst:.2f}, "
        f"monetization {monetization:.2f}, noise risk {noise_risk:.2f}"
    )
    rationale.append("attention is not value until it converts")

    return UndergroundAssessment(
        underground_status=True,
        verdict=verdict,
        buried_gem_score=gem,
        buried_noise_risk=noise_risk,
        originality_score=orig,
        cult_traction_score=cult,
        distribution_solvable=distribution,
        breakout_catalyst_score=catalyst,
        monetization_path_score=monetization,
        attention_half_life_days=half_life,
        viral_decay_risk=viral_decay,
        gatekeeper_risk=gatekeeper,
        attention_to_revenue_conversion=normalized_score(
            attention_to_revenue_conversion
        ),
        temporary_pavilion=temporary_pavilion,
        rationale=rationale,
    )
