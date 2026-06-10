"""Module H — container / interface recommendation engine.

The same signal needs the right container: a cup is a controlled
experiment, a cone is commitment, a cup with a cone biscuit is stable
core plus optional upside.  Translated into advisory action containers:

    ignore | watchlist | deep_research | event_trade_only |
    small_position_candidate | core_candidate | avoid_trap | hedge_candidate

Advisory classification only.  No broker execution, no order placement.
"""

from __future__ import annotations

from src.alpha import ADVISORY_DISCLAIMER
from src.utils.math_utils import clip

CONTAINERS = (
    "ignore",
    "watchlist",
    "deep_research",
    "event_trade_only",
    "small_position_candidate",
    "core_candidate",
    "avoid_trap",
    "hedge_candidate",
)

_SHORT_HALF_LIFE_DAYS = 30.0
_LONG_HALF_LIFE_DAYS = 180.0


def recommend_container(
    *,
    conviction: float,
    volatility: float = 50.0,
    half_life_days: float = 90.0,
    proof_score: float = 50.0,
    valuation_risk: float = 50.0,
    hedge_intent: bool = False,
) -> dict[str, object]:
    """Deterministically assign an advisory container.

    All scores are 0-100; ``half_life_days`` is the estimated signal
    half-life.  ``hedge_intent`` marks signals evaluated as portfolio
    hedges rather than standalone opportunities.
    """
    conviction = clip(conviction, 0.0, 100.0)
    volatility = clip(volatility, 0.0, 100.0)
    proof_score = clip(proof_score, 0.0, 100.0)
    valuation_risk = clip(valuation_risk, 0.0, 100.0)
    half_life_days = max(0.0, float(half_life_days))

    risk_controls: list[str] = []
    if hedge_intent:
        container = "hedge_candidate"
        reason = "Evaluated as a hedge: judged on offset quality, not standalone return."
        risk_controls.append("Size against the exposure being hedged, not conviction.")
    elif valuation_risk >= 75.0 and proof_score < 40.0:
        container = "avoid_trap"
        reason = (
            "Rich valuation with weak embedded proof: the badge cannot save "
            "the shoe."
        )
        risk_controls.append("Do not anchor on the narrative price path.")
    elif proof_score < 25.0 and conviction < 40.0:
        container = "ignore"
        reason = "Neither proof nor conviction clears the noise floor."
    elif half_life_days < _SHORT_HALF_LIFE_DAYS:
        container = "event_trade_only"
        reason = (
            f"Signal half-life ~{half_life_days:.0f}d is too short for a "
            "durable position; only the dated event is tradable."
        )
        risk_controls.append("Signal expires fast: re-score before the event resolves.")
    elif (
        conviction >= 70.0
        and proof_score >= 60.0
        and half_life_days >= _LONG_HALF_LIFE_DAYS
        and valuation_risk < 50.0
    ):
        container = "core_candidate"
        reason = (
            "High conviction, hard proof, long half-life, and tolerable "
            "valuation: cup with a cone biscuit."
        )
    elif conviction >= 55.0 and proof_score >= 50.0:
        container = "small_position_candidate"
        reason = "Decent conviction and proof, but not yet core-grade durability."
        risk_controls.append("Keep sizing small until proof or half-life improves.")
    elif conviction >= 40.0:
        container = "deep_research"
        reason = "Interesting but unproven: research before any container upgrade."
    else:
        container = "watchlist"
        reason = "Below research thresholds; watch for proof or velocity changes."

    if volatility >= 70.0 and container not in ("ignore", "avoid_trap"):
        risk_controls.append("High volatility: expect wide drawdowns in any container.")
    if valuation_risk >= 60.0 and container not in ("ignore", "avoid_trap"):
        risk_controls.append("Valuation risk elevated: edge depends on entry price.")

    if half_life_days >= _LONG_HALF_LIFE_DAYS:
        time_horizon = "long"
    elif half_life_days >= _SHORT_HALF_LIFE_DAYS:
        time_horizon = "medium"
    else:
        time_horizon = "short"

    # Confidence rises with proof and conviction, falls with volatility.
    confidence = clip(
        0.45 * proof_score + 0.35 * conviction + 0.20 * (100.0 - volatility),
        0.0,
        100.0,
    )
    return {
        "recommended_container": container,
        "reason": reason,
        "risk_controls": risk_controls,
        "time_horizon": time_horizon,
        "confidence": confidence,
        "disclaimer": ADVISORY_DISCLAIMER,
    }
