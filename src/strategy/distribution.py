"""Distribution Intelligence Engine: raw numbers are meaningless without
distribution context.

Every metric is placed inside a node-validated peer universe before being
judged. Bell curves locate normality; fat-tail logic locates breakouts;
fake outliers (one-off data, wrong peers) are flagged, not celebrated.

    z = (company_metric − peer_mean) / peer_std
    Fat_Tail_Potential = Nonlinear_Adoption × Promotion_Path
                         × Distribution_Unlock × Upside_Asymmetry
"""

from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass, field

from src.utils.math_utils import clamp01, clip
from src.utils.validation_utils import normalized_score

DISTRIBUTION_ARCHETYPES: tuple[str, ...] = (
    "middle_mass",
    "right_tail_quality",
    "right_tail_narrative_weak_fundamentals",
    "left_tail_fragility",
    "hidden_right_tail",
    "barbell",
    "fake_outlier",
    "fat_tail_breakout_candidate",
)

MIN_PEER_COUNT = 5


def percentile_band(percentile: float) -> str:
    p = clip(percentile, 0.0, 100.0)
    if p < 20:
        return "weak"
    if p < 40:
        return "below_average"
    if p < 60:
        return "average"
    if p < 80:
        return "above_average"
    if p < 95:
        return "strong"
    if p < 99:
        return "rare"
    return "extreme_outlier"


def z_to_percentile(z: float) -> float:
    """Normal CDF percentile from a z-score."""
    return clip(50.0 * (1.0 + math.erf(z / math.sqrt(2.0))), 0.0, 100.0)


@dataclass(slots=True)
class MetricPlacement:
    """One metric inside its peer distribution."""

    metric: str
    value: float
    peer_mean: float
    peer_std: float
    z_score: float
    percentile: float
    band: str
    fake_outlier: bool
    fake_outlier_reason: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class DistributionAssessment:
    """Full distribution verdict for one company."""

    peer_universe_node: str
    peer_count: int
    peer_universe_quality: float
    confidence_penalty: float
    placements: list[MetricPlacement] = field(default_factory=list)
    right_tail_signals: list[str] = field(default_factory=list)
    left_tail_risks: list[str] = field(default_factory=list)
    fake_outlier_flags: list[str] = field(default_factory=list)
    archetype: str = "middle_mass"
    fat_tail_potential: float = 0.0
    distribution_intelligence_score: float = 0.0
    rationale: list[str] = field(default_factory=list)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def place_metric(
    *,
    metric: str,
    value: float,
    peer_values: list[float],
    one_off_distortion: bool = False,
) -> MetricPlacement:
    """z-score + percentile placement with fake-outlier detection."""
    peers = [float(v) for v in peer_values]
    mean = statistics.mean(peers) if peers else 0.0
    std = statistics.pstdev(peers) if len(peers) >= 2 else 0.0
    z = (float(value) - mean) / std if std > 1e-12 else 0.0
    percentile = z_to_percentile(z)

    fake = False
    reason = ""
    if one_off_distortion and abs(z) >= 1.5:
        fake = True
        reason = "extreme value driven by one-off data / accounting distortion"
    elif abs(z) >= 3.5 and len(peers) < MIN_PEER_COUNT:
        fake = True
        reason = "extreme z-score from an undersized peer sample"

    return MetricPlacement(
        metric=str(metric),
        value=float(value),
        peer_mean=mean,
        peer_std=std,
        z_score=z,
        percentile=percentile,
        band=percentile_band(percentile),
        fake_outlier=fake,
        fake_outlier_reason=reason,
    )


def _classify_archetype(
    *,
    quality_percentile: float,
    fragility_percentile: float,
    narrative_percentile: float,
    visibility: float,
    catalyst: float,
    fake_flags: int,
    fat_tail: float,
) -> str:
    if fake_flags > 0:
        return "fake_outlier"
    if fat_tail >= 0.5:
        return "fat_tail_breakout_candidate"
    high_quality = quality_percentile >= 80
    fragile = fragility_percentile >= 80
    hot_narrative = narrative_percentile >= 80
    if high_quality and fragile:
        return "barbell"
    if fragile:
        return "left_tail_fragility"
    if hot_narrative and quality_percentile < 50:
        return "right_tail_narrative_weak_fundamentals"
    if high_quality and visibility < 0.4 and catalyst >= 0.5:
        return "hidden_right_tail"
    if high_quality:
        return "right_tail_quality"
    return "middle_mass"


def assess_distribution(
    *,
    peer_universe_node: str,
    company_node: str,
    metrics: dict[str, dict[str, object]],
    quality_percentile: float = 50.0,
    fragility_percentile: float = 50.0,
    narrative_percentile: float = 50.0,
    visibility: float = 0.5,
    catalyst: float = 0.0,
    nonlinear_adoption: float = 0.0,
    promotion_path: float = 0.0,
    distribution_unlock: float = 0.0,
    upside_asymmetry: float = 0.0,
) -> DistributionAssessment:
    """Place all metrics; validate the peer universe; classify archetype.

    ``metrics`` maps metric name -> {"value", "peer_values",
    "one_off_distortion"?}. A peer universe whose node differs from the
    company's node is a category error: a crocodile compared to bluefin
    peers earns a confidence penalty, not a percentile.
    """
    placements: list[MetricPlacement] = []
    for name, spec in (metrics or {}).items():
        placements.append(
            place_metric(
                metric=name,
                value=float(spec.get("value", 0.0)),  # type: ignore[arg-type]
                peer_values=list(spec.get("peer_values", []) or []),  # type: ignore[arg-type]
                one_off_distortion=bool(spec.get("one_off_distortion", False)),
            )
        )

    peer_counts = [
        len(list(spec.get("peer_values", []) or []))
        for spec in (metrics or {}).values()
    ]
    peer_count = min(peer_counts) if peer_counts else 0

    node_match = (
        str(peer_universe_node).strip().lower()
        == str(company_node).strip().lower()
    )
    size_quality = clamp01(peer_count / 10.0)
    universe_quality = clamp01((1.0 if node_match else 0.2) * (0.4 + 0.6 * size_quality))
    confidence_penalty = clamp01(1.0 - universe_quality)

    rationale: list[str] = []
    if not node_match:
        rationale.append(
            f"PEER UNIVERSE INVALID: company node '{company_node}' compared "
            f"against '{peer_universe_node}' peers — crocodiles are not "
            "bluefin; percentiles carry a confidence penalty of "
            f"{confidence_penalty:.2f}"
        )
    if peer_count < MIN_PEER_COUNT:
        rationale.append(
            f"peer sample of {peer_count} is undersized — percentile "
            "confidence reduced"
        )

    fake_flags = [p.metric for p in placements if p.fake_outlier]
    right_tail = [
        p.metric for p in placements
        if p.percentile >= 80 and not p.fake_outlier
    ]
    left_tail = [p.metric for p in placements if p.percentile <= 20]

    fat_tail = (
        normalized_score(nonlinear_adoption)
        * normalized_score(promotion_path)
        * normalized_score(distribution_unlock)
        * normalized_score(upside_asymmetry)
    ) ** 0.5  # geometric-style: all four legs required, soft scale

    archetype = _classify_archetype(
        quality_percentile=clip(quality_percentile, 0, 100),
        fragility_percentile=clip(fragility_percentile, 0, 100),
        narrative_percentile=clip(narrative_percentile, 0, 100),
        visibility=normalized_score(visibility, 0.5),
        catalyst=normalized_score(catalyst),
        fake_flags=len(fake_flags),
        fat_tail=fat_tail,
    )

    # Intelligence score: tail quality, penalized by fakes and bad universe.
    base = clamp01(
        0.4 * clip(quality_percentile, 0, 100) / 100.0
        + 0.2 * (len(right_tail) / max(len(placements), 1))
        - 0.3 * (len(fake_flags) / max(len(placements), 1))
        - 0.2 * clip(fragility_percentile, 0, 100) / 100.0
        + 0.2 * fat_tail
    )
    score = clip(base * (1.0 - 0.6 * confidence_penalty), 0.0, 1.0) * 10.0

    rationale.append(
        f"archetype '{archetype}'; {len(right_tail)} right-tail signal(s), "
        f"{len(left_tail)} left-tail risk(s), {len(fake_flags)} fake "
        f"outlier(s); fat-tail potential {fat_tail:.2f}"
    )
    if archetype == "right_tail_narrative_weak_fundamentals":
        rationale.append("a right-tail narrative is not a buy — hype risk")
    if fake_flags:
        rationale.append("fake outliers are penalized, never celebrated")

    return DistributionAssessment(
        peer_universe_node=str(peer_universe_node).lower(),
        peer_count=peer_count,
        peer_universe_quality=universe_quality,
        confidence_penalty=confidence_penalty,
        placements=placements,
        right_tail_signals=right_tail,
        left_tail_risks=left_tail,
        fake_outlier_flags=fake_flags,
        archetype=archetype,
        fat_tail_potential=fat_tail,
        distribution_intelligence_score=score,
        rationale=rationale,
    )
