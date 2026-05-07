from __future__ import annotations

from scripts.hedge_trade_entry_common import HedgeClass


def calculate_hedge_ratio(spot_notional: float, futures_hedge_notional: float) -> float:
    """HedgeRatio = FuturesHedgeNotional / SpotNotional."""
    if spot_notional <= 0:
        raise ValueError("spot_notional must be > 0")
    if futures_hedge_notional < 0:
        raise ValueError("futures_hedge_notional must be >= 0")
    return float(futures_hedge_notional) / float(spot_notional)


def calculate_hedge_notional(spot_notional: float, hedge_ratio: float) -> float:
    if spot_notional <= 0:
        raise ValueError("spot_notional must be > 0")
    if hedge_ratio < 0:
        raise ValueError("hedge_ratio must be >= 0")
    return float(spot_notional) * float(hedge_ratio)


def classify_hedge_ratio(hedge_ratio: float) -> HedgeClass:
    if hedge_ratio == 0:
        return HedgeClass.UNHEDGED
    if 0 < hedge_ratio <= 0.2:
        return HedgeClass.LIGHT_HEDGE
    if 0.2 < hedge_ratio <= 0.5:
        return HedgeClass.MODERATE_HEDGE
    if 0.5 < hedge_ratio < 1.0:
        return HedgeClass.HEAVY_HEDGE
    if hedge_ratio == 1.0:
        return HedgeClass.FULL_HEDGE
    return HedgeClass.OVER_HEDGED
