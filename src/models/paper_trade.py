"""Paper-trade dataclass for the read-only MVP layer."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(slots=True)
class PaperTrade:
    trade_id: str
    market_id: str
    side: str
    entry_price: float
    entry_time: str
    thesis: str
    state_at_entry: str
    expected_edge: float
    exit_rule: str
    stake: float
    status: str
    exit_price: float | None = None
    exit_time: str | None = None
    simulated_pnl: float | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
