from src.models.market import MarketSnapshot
from src.scoring.evidence_quality_layer import score_evidence_quality


def test_strong_primary_source_returns_high_eqs() -> None:
    snapshot = MarketSnapshot(
        market_id="m1",
        event_id="e1",
        question="q",
        description="d",
        category="c",
        outcomes=["YES", "NO"],
        yes_price=0.5,
        no_price=0.5,
        implied_probability=0.5,
        volume=0,
        liquidity=0,
        best_bid=0.49,
        best_ask=0.51,
        spread=0.02,
        end_date="2026",
        active=True,
        closed=False,
        source_url="u",
        fetched_at="t",
        primary_source_weight=0.9,
        source_credibility=0.8,
        confirmation_count_norm=0.8,
        recency_score=0.8,
        cross_source_diversity=0.7,
        contradiction_penalty=0.1,
    )
    result = score_evidence_quality(snapshot)
    assert result.score >= 0.65
    assert "STRONG_EVIDENCE" in result.reason_codes


def test_weak_source_returns_low_eqs() -> None:
    result = score_evidence_quality(
        {
            "primary_source_weight": 0.1,
            "source_credibility": 0.2,
            "confirmation_count_norm": 0.1,
            "recency_score": 0.2,
            "cross_source_diversity": 0.2,
            "contradiction_penalty": 0.5,
        }
    )
    assert result.score < 0.45
    assert "LOW_EVIDENCE_QUALITY" in result.reason_codes


def test_contradiction_penalty_reduces_eqs() -> None:
    low_penalty = score_evidence_quality(
        {
            "primary_source_weight": 0.7,
            "source_credibility": 0.7,
            "confirmation_count_norm": 0.7,
            "recency_score": 0.7,
            "cross_source_diversity": 0.7,
            "contradiction_penalty": 0.0,
        }
    )
    high_penalty = score_evidence_quality(
        {
            "primary_source_weight": 0.7,
            "source_credibility": 0.7,
            "confirmation_count_norm": 0.7,
            "recency_score": 0.7,
            "cross_source_diversity": 0.7,
            "contradiction_penalty": 0.8,
        }
    )
    assert high_penalty.score < low_penalty.score
