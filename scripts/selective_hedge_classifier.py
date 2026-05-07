from __future__ import annotations

from scripts.hedge_trade_entry_common import SignalStrength, TimingQuality, TradeMode


def classify_selective_hedge(
    *,
    signal_strength: str,
    timing_quality: str,
    chaos_score: float,
    drawdown_state: str,
    volatility_state: str,
) -> dict:
    strength = SignalStrength(signal_strength if signal_strength in SignalStrength._value2member_map_ else SignalStrength.UNKNOWN.value)
    timing = TimingQuality(timing_quality if timing_quality in TimingQuality._value2member_map_ else TimingQuality.UNKNOWN.value)
    low, high = 0.0, 0.2
    reason = "strong signal can keep room for upside"
    if strength == SignalStrength.MEDIUM:
        low, high = 0.3, 0.5
        reason = "medium signal deserves moderate protection"
    elif strength == SignalStrength.WEAK:
        low, high = 0.5, 0.7
        reason = "weak signal needs stronger protection"
    elif strength == SignalStrength.CHAOS or chaos_score >= 0.72:
        low, high = 0.7, 1.0
        reason = "chaos regime demands heavy hedge or no trade"
    if timing == TimingQuality.LATE:
        low, high = min(1.0, low + 0.1), min(1.0, high + 0.15)
        reason += "; late timing increases hedge need"
    if str(drawdown_state).upper() == "HIGH_DRAWDOWN":
        low, high = max(low, 0.7), 1.0
        reason += "; drawdown forces survival hedging"
    if str(volatility_state).upper() == "HIGH_VOLATILITY":
        low, high = max(low, 0.3), max(high, 0.5)
    selected_mode = (
        TradeMode.NO_NEW_RISK_MODE.value
        if chaos_score >= 0.85
        else TradeMode.SURVIVAL_MODE.value
        if high >= 0.7
        else TradeMode.BALANCED_MODE.value
        if high >= 0.3
        else TradeMode.GROWTH_MODE.value
    )
    return {
        "recommended_hedge_range": [round(low, 4), round(high, 4)],
        "selected_mode": selected_mode,
        "no_trade": strength == SignalStrength.CHAOS or chaos_score >= 0.85,
        "explanation": reason,
    }
