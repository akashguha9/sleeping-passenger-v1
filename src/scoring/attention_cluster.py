"""Attention-cluster detection that stays separate from validated signal flow."""

from __future__ import annotations

from src.models.signal import AttentionCluster
from src.models.scores import ScoreResult
from src.utils.math_utils import clip
from src.utils.time_utils import utc_now_iso
from src.utils.validation_utils import normalized_score


def score_attention_cluster(payload: dict[str, object]) -> ScoreResult:
    """Compute ACS.

    ACS = clip(
        ViralityProxy
      * EmotionalIntensity
      * NarrativeRecycling
      * TopicFrequency
      * SpreadVelocity,
      0,
      1
    )
    """
    virality_proxy = normalized_score(payload.get("virality_proxy", payload.get("virality_spike", 0.0)))
    emotional_intensity = normalized_score(payload.get("emotional_intensity", 0.0))
    narrative_recycling = normalized_score(payload.get("narrative_recycling", 0.0))
    topic_frequency = normalized_score(payload.get("topic_frequency", 0.0))
    spread_velocity = normalized_score(payload.get("spread_velocity", 0.0))
    score = clip(
        virality_proxy * emotional_intensity * narrative_recycling * topic_frequency * spread_velocity,
        0.0,
        1.0,
    )
    reasons = ["ATTENTION_CLUSTER_ONLY"] if score >= 0.50 else []
    return ScoreResult(
        score=score,
        explanation=f"ACS={score:.3f} from virality, emotion, narrative recycling, topic frequency, and spread velocity.",
        reason_codes=reasons,
        raw_components={
            "virality_proxy": virality_proxy,
            "emotional_intensity": emotional_intensity,
            "narrative_recycling": narrative_recycling,
            "topic_frequency": topic_frequency,
            "spread_velocity": spread_velocity,
        },
    )


def maybe_build_attention_cluster(
    *,
    market_id: str,
    topic: str,
    entities: list[str],
    narrative_type: str,
    emotional_category: str,
    source: str,
    engagement_manipulation_score: float,
    evidence_quality_score: float,
    attention_score: ScoreResult,
) -> AttentionCluster | None:
    """Return an attention-only cluster when bait intensity exceeds evidence."""
    if (
        engagement_manipulation_score >= 0.70
        and evidence_quality_score < 0.45
        and attention_score.score >= 0.50
    ):
        return AttentionCluster(
            market_id=market_id,
            topic=topic,
            entities=entities,
            narrative_type=narrative_type,
            emotional_category=emotional_category,
            source=source,
            timestamp=utc_now_iso(),
            attention_cluster_score=attention_score.score,
            engagement_manipulation_score=engagement_manipulation_score,
            evidence_quality_score=evidence_quality_score,
            reason_codes=["ATTENTION_CLUSTER_ONLY", *attention_score.reason_codes],
        )
    return None
