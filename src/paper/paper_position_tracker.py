"""Helpers for updating paper-trade status without any live execution path."""

from __future__ import annotations

from src.models.paper_trade import PaperTrade
from src.paper.paper_trade_engine import compute_paper_pnl
from src.utils.time_utils import utc_now_iso


def close_paper_trade(trade: PaperTrade, exit_price: float, simulated_friction: float = 0.0) -> PaperTrade:
    """Return a closed copy of a paper trade with simulated PnL."""
    trade.exit_price = exit_price
    trade.exit_time = utc_now_iso()
    trade.status = "CLOSED"
    trade.simulated_pnl = compute_paper_pnl(
        side=trade.side,
        stake=trade.stake,
        entry_price=trade.entry_price,
        exit_price=exit_price,
        simulated_friction=simulated_friction,
    )
    return trade
