from src.scoring.execution_friction import score_execution_friction


def test_wide_spread_increases_efs() -> None:
    low = score_execution_friction({"spread_penalty": 0.1, "volatility_penalty": 0.1, "timing_risk": 0.1}, liquidity_score=0.8)
    high = score_execution_friction({"spread_penalty": 0.9, "volatility_penalty": 0.1, "timing_risk": 0.1}, liquidity_score=0.8)
    assert high.score > low.score


def test_api_uncertainty_increases_efs() -> None:
    result = score_execution_friction({"spread_penalty": 0.1, "api_uncertainty_penalty": 0.8}, liquidity_score=0.8)
    assert "API_DATA_INCOMPLETE" in result.reason_codes
