from __future__ import annotations

from scripts.hedge_trade_entry_common import LeverageSafetyState, clamp01


REGIME_SAFETY_CAPS = {
    "NORMAL": 3.0,
    "HIGH_VOLATILITY": 2.0,
    "CHAOS": 1.0,
    "SHOCK": 0.0,
}


def evaluate_leverage_safety(*, futures_notional: float, leverage: float, user_max_leverage: float, regime: str) -> dict:
    """MarginRequired = FuturesNotional / Leverage; ApproxLiquidationSensitivity ∝ 1 / Leverage."""
    normalized_regime = str(regime or "NORMAL").upper()
    regime_cap = REGIME_SAFETY_CAPS.get(normalized_regime, 2.0)
    allowed_leverage = min(float(user_max_leverage), float(regime_cap))
    margin_required = None if leverage <= 0 else float(futures_notional) / float(leverage)
    liquidation_sensitivity = None if leverage <= 0 else 1.0 / float(leverage)
    if normalized_regime == "SHOCK" or regime_cap == 0.0:
        state = LeverageSafetyState.REJECTED
    elif leverage <= allowed_leverage:
        state = LeverageSafetyState.SAFE if leverage <= max(1.0, allowed_leverage - 0.5) else LeverageSafetyState.CAUTION
    elif normalized_regime == "CHAOS":
        state = LeverageSafetyState.REJECTED
    elif leverage <= allowed_leverage + 1.0:
        state = LeverageSafetyState.UNSAFE
    else:
        state = LeverageSafetyState.REJECTED
    return {
        "state": state.value,
        "allowed_leverage": allowed_leverage,
        "margin_required": margin_required,
        "approx_liquidation_sensitivity": liquidation_sensitivity,
        "regime_safety_cap": regime_cap,
        "safety_score": clamp01((allowed_leverage / leverage) if leverage > 0 else 0.0),
    }
