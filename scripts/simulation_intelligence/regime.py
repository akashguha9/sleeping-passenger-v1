"""Regime-state contract — the market context a Decision Twin is frozen in.

A model that works in one regime may fail in another. Every twin stores the
regime state at prediction time so calibration can later be reported *by regime*
(with minimum-sample requirements and low-sample labels, never tiny-cohort
overconfidence). Pure/deterministic: derived from the observation only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

try:
    from scripts.simulation_intelligence.contracts import MarketObservation
except ModuleNotFoundError:  # pragma: no cover
    from simulation_intelligence.contracts import MarketObservation  # type: ignore[no-redef]


def _stdev(xs: list[float]) -> float:
    xs = [float(x) for x in xs if x == x]
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5


@dataclass(frozen=True, slots=True)
class RegimeState:
    volatility_regime: str        # LOW / NORMAL / HIGH / EXTREME
    trend_regime: str             # UP / SIDEWAYS / DOWN
    liquidity_regime: str         # DEEP / NORMAL / THIN / UNKNOWN
    dispersion_regime: str        # CALM / CHOPPY (recent return sign flips)
    data_quality_regime: str      # CLEAN / DEGRADED / SPARSE
    freshness_regime: str         # FRESH / AGING / STALE / UNKNOWN
    regime_key: str               # compact composite key for cohorting

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__slots__}


def classify_regime(obs: MarketObservation) -> RegimeState:
    rets = [float(x) for x in (obs.returns or []) if x == x]
    vol = obs.volatility if obs.volatility is not None else _stdev(rets)
    if vol is None:
        vol = 0.0
    if vol < 0.012:
        vol_r = "LOW"
    elif vol < 0.025:
        vol_r = "NORMAL"
    elif vol < 0.045:
        vol_r = "HIGH"
    else:
        vol_r = "EXTREME"

    cum = 1.0
    for r in rets:
        cum *= (1.0 + r)
    drift = cum - 1.0
    trend_r = "UP" if drift > 0.03 else ("DOWN" if drift < -0.03 else "SIDEWAYS")

    adv = obs.adv_usd
    if adv is None:
        liq_r = "UNKNOWN"
    elif adv >= 5e7:
        liq_r = "DEEP"
    elif adv >= 5e6:
        liq_r = "NORMAL"
    else:
        liq_r = "THIN"

    flips = sum(1 for i in range(1, len(rets)) if (rets[i] > 0) != (rets[i - 1] > 0))
    disp_r = "CHOPPY" if (rets and flips / max(1, len(rets) - 1) > 0.5) else "CALM"

    missing = len(obs.missing_fields or [])
    if missing == 0 and len(rets) >= 5:
        dq_r = "CLEAN"
    elif missing <= 2 and len(rets) >= 2:
        dq_r = "DEGRADED"
    else:
        dq_r = "SPARSE"

    fresh_r = (obs.freshness_status or "UNKNOWN").upper()
    if fresh_r not in ("FRESH", "AGING", "STALE"):
        fresh_r = "UNKNOWN"

    key = f"{vol_r}|{trend_r}|{liq_r}|{fresh_r}"
    return RegimeState(
        volatility_regime=vol_r, trend_regime=trend_r, liquidity_regime=liq_r,
        dispersion_regime=disp_r, data_quality_regime=dq_r,
        freshness_regime=fresh_r, regime_key=key)


__all__ = ["RegimeState", "classify_regime"]
