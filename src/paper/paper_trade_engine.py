"""Paper-trade creation for PAPER_TRADE-only signals."""

from __future__ import annotations

import uuid

from src.models.market import MarketSnapshot
from src.models.paper_trade import PaperTrade
from src.models.signal import SignalScore
from src.utils.time_utils import utc_now_iso


def build_paper_trade(
    *,
    snapshot: MarketSnapshot,
    signal_score: SignalScore,
    edge_threshold: float = 0.08,
    simulated_stake: float = 100.0,
) -> PaperTrade | None:
    """Create a paper trade only when deterministic PAPER_TRADE gates pass."""
    if signal_score.state != "PAPER_TRADE":
        return None
    model_probability = signal_score.model_probability
    implied_probability = snapshot.implied_probability
    edge = model_probability - implied_probability
    if edge > edge_threshold:
        side = "YES"
        entry_price = snapshot.yes_price
    elif edge < -edge_threshold:
        side = "NO"
        entry_price = snapshot.no_price
    else:
        return None
    thesis = (
        f"Paper-only {side} thesis because model probability {model_probability:.2f} "
        f"diverges from market implied probability {implied_probability:.2f} by {abs(edge):.2f}."
    )
    return PaperTrade(
        trade_id=f"paper-{uuid.uuid4().hex[:12]}",
        market_id=snapshot.market_id,
        side=side,
        entry_price=entry_price,
        entry_time=utc_now_iso(),
        thesis=thesis,
        state_at_entry=signal_score.state,
        expected_edge=abs(edge),
        exit_rule="Resolve, max holding period, EQS drop >0.20, DS <0.40, EMS >0.75, or EFS >0.75.",
        stake=simulated_stake,
        status="OPEN",
    )


def compute_paper_pnl(
    *,
    side: str,
    stake: float,
    entry_price: float,
    exit_price: float,
    simulated_friction: float = 0.0,
) -> float:
    """Compute transparent paper PnL for YES or NO positions."""
    if side == "YES":
        return stake * ((exit_price - entry_price) / max(entry_price, 1e-9)) - simulated_friction
    inverse_entry = 1.0 - entry_price
    inverse_exit = 1.0 - exit_price
    return stake * ((inverse_exit - inverse_entry) / max(inverse_entry, 1e-9)) - simulated_friction
