from __future__ import annotations

from scripts.hedge_trade_entry_common import safe_div


def calculate_net_exposure(spot_long: float, futures_long: float, futures_short: float) -> float:
    """NetExposure = SpotLongNotional + FuturesLongNotional - FuturesShortNotional."""
    return float(spot_long) + float(futures_long) - float(futures_short)


def calculate_net_exposure_ratio(net_exposure: float, spot_notional: float) -> float:
    ratio = safe_div(net_exposure, spot_notional, default=0.0)
    return float(ratio or 0.0)


def classify_directional_exposure(net_exposure_ratio: float) -> str:
    if net_exposure_ratio > 1.0:
        return "OVEREXPOSED_LONG"
    if net_exposure_ratio > 0:
        return "NET_LONG"
    if net_exposure_ratio == 0:
        return "NEUTRAL"
    if net_exposure_ratio < -1.0:
        return "OVEREXPOSED_SHORT"
    return "NET_SHORT"
