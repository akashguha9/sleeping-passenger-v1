"""Layer 6 — Vitality Funnel (transfer-gated).

Traction asks "did it catch?"  Vitality asks "did it keep living?"

A signal must survive an 11-stage funnel from narrative birth to market
repricing.  The eureka here is **transfer gating**: a signal earns vitality
credit only for the stages it has *actually reached in order*.  You cannot sum
your way past a broken stage — a video viral on TikTok (stage 2) that never
converts (stage 6) has its vitality capped at the conversion bottleneck, no
matter how high later stages might score in isolation.

    stages = [birth, attention, semantic_density, migration, trust,
              conversion, retention, reproduction, business_confirmation,
              financial_confirmation, market_recognition]

The bottleneck stage is the first stage whose score falls below the transfer
threshold; ``next_required_confirmation`` names what the signal must do next.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .util import clamp, r3

STAGES: tuple[str, ...] = (
    "narrative_birth",
    "platform_attention",
    "semantic_density",
    "cross_platform_migration",
    "trust_formation",
    "conversion",
    "retention",
    "reproduction",
    "business_confirmation",
    "financial_confirmation",
    "market_recognition",
)

# A stage is considered "transferred" if it clears this score.
TRANSFER_THRESHOLD = 0.4

# What the signal must demonstrate to clear each bottleneck.
_NEXT_CONFIRMATION: dict[str, str] = {
    "narrative_birth": "establish a first credible source/timestamp",
    "platform_attention": "attract measurable attention on a real ecology",
    "semantic_density": "produce specific, dense language (not vague hype)",
    "cross_platform_migration": "migrate to a 2nd/3rd distinct platform ecology",
    "trust_formation": "convert attention into durable trust (saves/subs/return)",
    "conversion": "convert trust into action (purchase/signup/adoption)",
    "retention": "show repeat behavior / renewal",
    "reproduction": "show referral / imitation / organic spread",
    "business_confirmation": "confirm in business metrics (users/orders/churn)",
    "financial_confirmation": "confirm in financial statements (rev/margin/FCF)",
    "market_recognition": "already recognized — check if priced in",
}


@dataclass(frozen=True)
class VitalityResult:
    stage_scores: dict[str, float]
    transferred_stages: int          # contiguous stages cleared from birth
    bottleneck_stage: str
    next_required_confirmation: str
    raw_vitality: float              # mean of all stage scores (ungated)
    vitality_score: float            # transfer-gated vitality (the real one)
    transfer_integrity: float        # transferred / total stages, the cap
    reason_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["stage_scores"] = {k: r3(v) for k, v in self.stage_scores.items()}
        for k in ("raw_vitality", "vitality_score", "transfer_integrity"):
            d[k] = r3(d[k])
        return d


def compute_vitality(stage_scores: dict[str, float]) -> VitalityResult:
    """Transfer-gate the per-stage scores into a single vitality figure.

    ``stage_scores`` maps any subset of ``STAGES`` to [0,1]; absent stages
    default to 0 (the signal has not demonstrated them).
    """
    scores = {s: clamp(stage_scores.get(s, 0.0)) for s in STAGES}

    # Walk the funnel in order; stop at the first stage below threshold.
    transferred = 0
    bottleneck = STAGES[0]
    for stage in STAGES:
        if scores[stage] >= TRANSFER_THRESHOLD:
            transferred += 1
        else:
            bottleneck = stage
            break
    else:
        bottleneck = STAGES[-1]  # cleared the whole funnel

    raw_vitality = sum(scores.values()) / len(STAGES)
    transfer_integrity = transferred / len(STAGES)

    # Transfer-gated vitality: credit only the contiguous cleared prefix, plus
    # a *fractional* peek at the bottleneck stage itself (it is in progress).
    cleared = [scores[s] for s in STAGES[:transferred]]
    cleared_mean = (sum(cleared) / len(cleared)) if cleared else 0.0
    bottleneck_partial = scores[bottleneck] * 0.5 if transferred < len(STAGES) else 0.0
    vitality = clamp(transfer_integrity * cleared_mean + (bottleneck_partial / len(STAGES)))

    reasons = [
        f"TRANSFERRED:{transferred}/{len(STAGES)}",
        f"BOTTLENECK:{bottleneck}",
    ]
    if transferred >= 8:
        reasons.append("DEEP_FUNNEL_SURVIVAL")
    if transferred <= 2:
        reasons.append("SHALLOW_TRACTION_NOT_VITALITY")
    if raw_vitality - vitality >= 0.2:
        reasons.append("LATE_STAGE_SCORES_UNREACHABLE_BY_TRANSFER")

    return VitalityResult(
        stage_scores=scores,
        transferred_stages=transferred,
        bottleneck_stage=bottleneck,
        next_required_confirmation=_NEXT_CONFIRMATION[bottleneck],
        raw_vitality=raw_vitality,
        vitality_score=vitality,
        transfer_integrity=transfer_integrity,
        reason_codes=reasons,
    )


__all__ = [
    "STAGES",
    "TRANSFER_THRESHOLD",
    "VitalityResult",
    "compute_vitality",
]
