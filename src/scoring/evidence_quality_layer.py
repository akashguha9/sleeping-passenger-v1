"""Evidence quality scoring for durable public-data signals."""

from __future__ import annotations

from src.models.market import MarketSnapshot
from src.models.scores import ScoreResult
from src.utils.math_utils import clip
from src.utils.validation_utils import normalized_score


def score_evidence_quality(snapshot: MarketSnapshot | dict[str, object]) -> ScoreResult:
    """Compute EQS.

    EQS = clip(
        0.25 * PrimarySourceWeight
      + 0.20 * SourceCredibility
      + 0.20 * ConfirmationCountNorm
      + 0.15 * RecencyScore
      + 0.10 * CrossSourceDiversity
      - 0.10 * ContradictionPenalty,
      0, 1
    )
    """
    payload = snapshot.to_dict() if isinstance(snapshot, MarketSnapshot) else dict(snapshot)
    primary = normalized_score(payload.get("primary_source_weight", 0.0))
    credibility = normalized_score(payload.get("source_credibility", 0.0))
    confirmations = normalized_score(payload.get("confirmation_count_norm", 0.0))
    recency = normalized_score(payload.get("recency_score", 0.0))
    diversity = normalized_score(payload.get("cross_source_diversity", 0.0))
    contradiction = normalized_score(payload.get("contradiction_penalty", 0.0))
    score = clip(
        0.25 * primary
        + 0.20 * credibility
        + 0.20 * confirmations
        + 0.15 * recency
        + 0.10 * diversity
        - 0.10 * contradiction,
        0.0,
        1.0,
    )
    reasons: list[str] = []
    if score >= 0.65:
        reasons.append("STRONG_EVIDENCE")
    if score < 0.45:
        reasons.append("LOW_EVIDENCE_QUALITY")
    if contradiction > 0.20:
        reasons.append("CONTRADICTION_PENALTY")
    return ScoreResult(
        score=score,
        explanation=f"EQS={score:.3f} from source quality, confirmations, recency, and contradiction balance.",
        reason_codes=reasons,
        raw_components={
            "primary_source_weight": primary,
            "source_credibility": credibility,
            "confirmation_count_norm": confirmations,
            "recency_score": recency,
            "cross_source_diversity": diversity,
            "contradiction_penalty": contradiction,
        },
    )
