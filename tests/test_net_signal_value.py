from src.scoring.net_signal_value import score_net_signal_value


def test_high_eqs_high_ds_low_ems_creates_positive_nsv() -> None:
    result = score_net_signal_value(
        evidence_quality_score=0.8,
        durability_score=0.8,
        liquidity_score=0.8,
        engagement_manipulation_score=0.1,
        execution_friction_score=0.1,
        market_implied_probability=0.4,
    )
    assert result["net_signal_value"].score > 0


def test_high_ems_weak_eqs_creates_poor_nsv() -> None:
    result = score_net_signal_value(
        evidence_quality_score=0.3,
        durability_score=0.3,
        liquidity_score=0.4,
        engagement_manipulation_score=0.9,
        execution_friction_score=0.6,
        market_implied_probability=0.5,
    )
    assert result["net_signal_value"].score < 0
