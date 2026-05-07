"""Net signal value and admission-priority scoring."""

from __future__ import annotations

from src.models.scores import ScoreResult
from src.utils.math_utils import clip


def compute_model_probability(eqs: float, ds: float, ems: float, efs: float) -> float:
    """Compute the placeholder model probability used for paper-only scoring."""
    return clip(
        0.50 + 0.25 * (eqs - 0.50) + 0.20 * (ds - 0.50) - 0.15 * ems - 0.10 * efs,
        0.01,
        0.99,
    )


def score_net_signal_value(
    *,
    evidence_quality_score: float,
    durability_score: float,
    liquidity_score: float,
    engagement_manipulation_score: float,
    execution_friction_score: float,
    market_implied_probability: float,
) -> dict[str, ScoreResult | float]:
    """Compute model probability, market mispricing, NSV, and APS."""
    eqs = float(evidence_quality_score)
    ds = float(durability_score)
    ls = float(liquidity_score)
    ems = float(engagement_manipulation_score)
    efs = float(execution_friction_score)
    market_probability = float(market_implied_probability)
    model_probability = compute_model_probability(eqs, ds, ems, efs)
    mispricing = abs(model_probability - market_probability)
    net_signal_value = clip(
        mispricing * eqs * ds * ls - 0.35 * ems - 0.25 * efs,
        -1.0,
        1.0,
    )
    aps = clip(
        0.30 * eqs
        + 0.25 * ds
        + 0.20 * ls
        + 0.15 * mispricing
        - 0.20 * ems
        - 0.15 * efs,
        0.0,
        1.0,
    )
    reasons: list[str] = []
    if mispricing >= 0.08:
        reasons.append("HIGH_MISPRICING_ESTIMATE")
    if net_signal_value > 0:
        reasons.append("PAPER_EDGE_DETECTED")
    if net_signal_value < 0:
        reasons.append("NEGATIVE_NET_SIGNAL_VALUE")
    return {
        "model_probability": model_probability,
        "market_mispricing_estimate": mispricing,
        "net_signal_value": ScoreResult(
            score=net_signal_value,
            explanation=f"NSV={net_signal_value:.3f} after attention and friction penalties.",
            reason_codes=reasons,
            raw_components={
                "market_mispricing_estimate": mispricing,
                "evidence_quality_score": eqs,
                "durability_score": ds,
                "liquidity_score": ls,
                "engagement_manipulation_score": ems,
                "execution_friction_score": efs,
            },
        ),
        "admission_priority_score": ScoreResult(
            score=aps,
            explanation=f"APS={aps:.3f} from evidence, durability, liquidity, mispricing, and penalties.",
            reason_codes=reasons,
            raw_components={
                "evidence_quality_score": eqs,
                "durability_score": ds,
                "liquidity_score": ls,
                "market_mispricing_estimate": mispricing,
                "engagement_manipulation_score": ems,
                "execution_friction_score": efs,
            },
        ),
    }
