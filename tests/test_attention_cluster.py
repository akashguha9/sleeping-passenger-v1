from src.scoring.attention_cluster import maybe_build_attention_cluster, score_attention_cluster


def test_high_ems_low_eqs_high_acs_routes_to_attention_cluster_only() -> None:
    attention = score_attention_cluster(
        {
            "virality_proxy": 1.0,
            "emotional_intensity": 0.9,
            "narrative_recycling": 0.9,
            "topic_frequency": 0.9,
            "spread_velocity": 0.8,
        }
    )
    cluster = maybe_build_attention_cluster(
        market_id="m1",
        topic="topic",
        entities=["a"],
        narrative_type="viral",
        emotional_category="fear",
        source="test",
        engagement_manipulation_score=0.8,
        evidence_quality_score=0.3,
        attention_score=attention,
    )
    assert cluster is not None
    assert "ATTENTION_CLUSTER_ONLY" in cluster.reason_codes
