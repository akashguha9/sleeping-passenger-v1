from src.scoring.liquidity_score import score_liquidity


def test_high_liquidity_low_spread_gets_high_ls() -> None:
    result = score_liquidity({"liquidity": 90000, "volume": 95000, "order_book_depth": 9000, "spread": 0.01})
    assert result.score >= 0.60


def test_low_liquidity_wide_spread_gets_low_ls() -> None:
    result = score_liquidity({"liquidity": 1000, "volume": 500, "order_book_depth": 200, "spread": 0.20})
    assert result.score < 0.40
    assert "LOW_LIQUIDITY" in result.reason_codes
