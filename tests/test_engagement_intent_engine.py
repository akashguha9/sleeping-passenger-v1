from src.models.market import MarketSnapshot
from src.scoring.engagement_intent_engine import score_engagement_manipulation


def make_snapshot(**overrides: object) -> MarketSnapshot:
    base = {
        "market_id": "m1",
        "event_id": "e1",
        "question": "Will the policy decision happen?",
        "description": "Neutral factual description.",
        "category": "macro",
        "outcomes": ["YES", "NO"],
        "yes_price": 0.5,
        "no_price": 0.5,
        "implied_probability": 0.5,
        "volume": 10000.0,
        "liquidity": 12000.0,
        "best_bid": 0.49,
        "best_ask": 0.51,
        "spread": 0.02,
        "end_date": "2026-12-31",
        "active": True,
        "closed": False,
        "source_url": "https://example.test/m1",
        "fetched_at": "2026-05-07T00:00:00+00:00",
    }
    base.update(overrides)
    return MarketSnapshot(**base)


def test_high_emotional_low_evidence_claim_returns_high_ems() -> None:
    result = score_engagement_manipulation(
        make_snapshot(
            question="SHOCKING: you won't believe this collapse",
            emotional_intensity=0.95,
            headline_extremity=0.9,
            narrative_recycling=0.9,
            virality_spike=0.8,
            curiosity_gap=0.9,
            evidence_density=0.1,
            source_credibility=0.2,
        )
    )
    assert result.score >= 0.70
    assert "HIGH_ENGAGEMENT_MANIPULATION" in result.reason_codes


def test_neutral_factual_claim_returns_low_ems() -> None:
    result = score_engagement_manipulation(
        make_snapshot(
            question="Will inflation print above target next month?",
            emotional_intensity=0.1,
            headline_extremity=0.1,
            narrative_recycling=0.1,
            virality_spike=0.1,
            curiosity_gap=0.05,
            evidence_density=0.8,
            source_credibility=0.8,
        )
    )
    assert result.score < 0.20


def test_engagement_scores_are_clipped() -> None:
    result = score_engagement_manipulation(make_snapshot(emotional_intensity=5.0, evidence_density=-2.0))
    assert 0.0 <= result.score <= 1.0
