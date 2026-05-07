from src.models.market import MarketSnapshot
from src.models.signal import SignalScore
from src.paper.paper_trade_engine import build_paper_trade


def make_market() -> MarketSnapshot:
    return MarketSnapshot(
        market_id="m1",
        event_id="e1",
        question="q",
        description="d",
        category="c",
        outcomes=["YES", "NO"],
        yes_price=0.40,
        no_price=0.60,
        implied_probability=0.30,
        volume=1000,
        liquidity=1000,
        best_bid=0.39,
        best_ask=0.41,
        spread=0.02,
        end_date="2026",
        active=True,
        closed=False,
        source_url="u",
        fetched_at="t",
    )


def make_score(state: str, model_probability: float) -> SignalScore:
    return SignalScore(
        market_id="m1",
        engagement_manipulation_score=0.1,
        evidence_quality_score=0.8,
        durability_score=0.8,
        liquidity_score=0.8,
        execution_friction_score=0.1,
        market_mispricing_estimate=0.15,
        model_probability=model_probability,
        net_signal_value=0.2,
        admission_priority_score=0.8,
        state=state,
        reason_codes=["PAPER_EDGE_DETECTED"],
        explanation="ok",
        scored_at="t",
    )


def test_only_creates_trades_for_paper_trade_state() -> None:
    trade = build_paper_trade(snapshot=make_market(), signal_score=make_score("PAPER_TRADE", 0.45))
    assert trade is not None
    assert trade.expected_edge > 0
    assert trade.thesis
    no_trade = build_paper_trade(snapshot=make_market(), signal_score=make_score("WATCH", 0.45))
    assert no_trade is None
