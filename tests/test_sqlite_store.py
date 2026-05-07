from pathlib import Path

from src.models.market import MarketSnapshot
from src.models.paper_trade import PaperTrade
from src.models.signal import SignalScore
from src.storage.sqlite_store import SQLiteStore


def test_can_write_and_read_core_entities() -> None:
    db_path = Path("runtime/test_signal_refinery.sqlite")
    if db_path.exists():
        db_path.unlink()
    store = SQLiteStore(db_path)
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
        volume=1000,
        liquidity=1000,
        best_bid=0.49,
        best_ask=0.51,
        spread=0.02,
        end_date="2026",
        active=True,
        closed=False,
        source_url="u",
        fetched_at="t",
    )
    score = SignalScore(
        market_id="m1",
        engagement_manipulation_score=0.2,
        evidence_quality_score=0.7,
        durability_score=0.7,
        liquidity_score=0.7,
        execution_friction_score=0.2,
        market_mispricing_estimate=0.1,
        model_probability=0.6,
        net_signal_value=0.1,
        admission_priority_score=0.7,
        state="PAPER_TRADE",
        reason_codes=["ok"],
        explanation="ok",
        scored_at="t",
    )
    trade = PaperTrade(
        trade_id="p1",
        market_id="m1",
        side="YES",
        entry_price=0.5,
        entry_time="t",
        thesis="thesis",
        state_at_entry="PAPER_TRADE",
        expected_edge=0.1,
        exit_rule="rule",
        stake=100.0,
        status="OPEN",
    )
    store.write_market_snapshots([snapshot])
    store.write_signal_scores([score])
    store.write_paper_trade(trade)
    assert store.read_latest_market_snapshots()[0]["market_id"] == "m1"
    assert store.read_latest_signal_scores()[0]["state"] == "PAPER_TRADE"
    assert store.read_paper_trades()[0]["trade_id"] == "p1"
    store.connection.close()
    if db_path.exists():
        db_path.unlink()
