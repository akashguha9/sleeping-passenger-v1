"""Engagement manipulation scoring for attention-heavy claims.

Signal Problem = Durable Evidence vs Engineered Attention
"""

from __future__ import annotations

from src.models.market import MarketSnapshot
from src.models.scores import ScoreResult
from src.utils.math_utils import clip
from src.utils.validation_utils import normalized_score

EMOTIONAL_WORDS = {
    "shocking",
    "explosive",
    "massive",
    "panic",
    "urgent",
    "must",
    "guaranteed",
    "collapse",
    "surge",
    "destroyed",
}
CURIOUS_PATTERNS = {"what happens if", "you won't believe", "why everyone is"}


def _text_flag_score(text: str, keywords: set[str]) -> float:
    lowered = text.lower()
    hits = sum(1 for word in keywords if word in lowered)
    return clip(hits / max(len(keywords) * 0.2, 1), 0.0, 1.0)


def score_engagement_manipulation(snapshot: MarketSnapshot | dict[str, object]) -> ScoreResult:
    """Compute EMS.

    EMS = clip(
        0.20 * EmotionalIntensity
      + 0.15 * HeadlineExtremity
      + 0.15 * NarrativeRecycling
      + 0.15 * ViralitySpike
      + 0.15 * CuriosityGap
      - 0.10 * EvidenceDensity
      - 0.10 * SourceCredibility,
      0, 1
    )
    """
    payload = snapshot.to_dict() if isinstance(snapshot, MarketSnapshot) else dict(snapshot)
    text = f"{payload.get('question', '')} {payload.get('description', '')}".strip()
    emotional_intensity = max(
        normalized_score(payload.get("emotional_intensity", 0.0)),
        _text_flag_score(text, EMOTIONAL_WORDS),
    )
    curiosity_gap = max(
        normalized_score(payload.get("curiosity_gap", 0.0)),
        _text_flag_score(text, CURIOUS_PATTERNS),
    )
    headline_extremity = normalized_score(payload.get("headline_extremity", 0.0))
    narrative_recycling = normalized_score(payload.get("narrative_recycling", 0.0))
    virality_spike = normalized_score(payload.get("virality_spike", 0.0))
    evidence_density = normalized_score(payload.get("evidence_density", 0.0))
    source_credibility = normalized_score(payload.get("source_credibility", 0.0))

    score = clip(
        0.20 * emotional_intensity
        + 0.15 * headline_extremity
        + 0.15 * narrative_recycling
        + 0.15 * virality_spike
        + 0.15 * curiosity_gap
        - 0.10 * evidence_density
        - 0.10 * source_credibility,
        0.0,
        1.0,
    )
    reasons: list[str] = []
    if score >= 0.70:
        reasons.append("HIGH_ENGAGEMENT_MANIPULATION")
    if emotional_intensity >= 0.70 and evidence_density <= 0.35:
        reasons.append("LOW_EVIDENCE_HIGH_EMOTION")
    if curiosity_gap >= 0.60 and source_credibility <= 0.40:
        reasons.append("REJECTED_BAIT_PATTERN")
    explanation = (
        f"EMS={score:.3f} from emotional intensity {emotional_intensity:.2f}, "
        f"curiosity gap {curiosity_gap:.2f}, evidence density {evidence_density:.2f}, "
        f"and source credibility {source_credibility:.2f}."
    )
    return ScoreResult(
        score=score,
        explanation=explanation,
        reason_codes=reasons,
        raw_components={
            "emotional_intensity": emotional_intensity,
            "headline_extremity": headline_extremity,
            "narrative_recycling": narrative_recycling,
            "virality_spike": virality_spike,
            "curiosity_gap": curiosity_gap,
            "evidence_density": evidence_density,
            "source_credibility": source_credibility,
        },
    )
