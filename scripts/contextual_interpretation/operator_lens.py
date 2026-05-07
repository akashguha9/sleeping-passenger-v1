from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class OperatorLens:
    lens_name: str
    participant_type: str
    incentive_structure: str
    timeframe: str
    information_access: str
    risk_tolerance: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_operator_lenses() -> list[OperatorLens]:
    return [
        OperatorLens("Retail", "RETAIL", "BREAKOUT_CAPTURE", "INTRADAY", "PUBLIC", "MEDIUM"),
        OperatorLens("Institution", "INSTITUTION", "LIQUIDITY_ACCESS", "MULTI_DAY", "DEEP", "LOW"),
        OperatorLens("Momentum", "MOMENTUM", "TREND_CAPTURE", "FAST", "PUBLIC", "HIGH"),
        OperatorLens("MarketMaker", "MARKET_MAKER", "INVENTORY_CONTROL", "VERY_FAST", "MICROSTRUCTURE", "LOW"),
        OperatorLens("Contrarian", "CONTRARIAN", "MEAN_REVERSION", "SWING", "PUBLIC", "MEDIUM"),
        OperatorLens("Whale", "WHALE", "STEALTH_ACCUMULATION", "MULTI_WEEK", "PRIVATE_FLOW", "HIGH"),
    ]
