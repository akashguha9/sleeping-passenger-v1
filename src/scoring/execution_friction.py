"""Execution-friction scoring for paper-safe market entry."""

from __future__ import annotations

from src.models.market import MarketSnapshot
from src.models.scores import ScoreResult
from src.utils.math_utils import clip
from src.utils.validation_utils import normalized_score


def score_execution_friction(
    snapshot: MarketSnapshot | dict[str, object],
    liquidity_score: float | None = None,
) -> ScoreResult:
    """Compute EFS.

    EFS = clip(
        0.25 * SpreadPenalty
      + 0.25 * LowLiquidityPenalty
      + 0.20 * VolatilityPenalty
      + 0.20 * TimingRisk
      + 0.10 * APIUncertaintyPenalty,
      0, 1
    )
    """
    payload = snapshot.to_dict() if isinstance(snapshot, MarketSnapshot) else dict(snapshot)
    spread_penalty = normalized_score(payload.get("spread_penalty", payload.get("spread", 0.0) / 0.15))
    low_liquidity_penalty = 1.0 - normalized_score(liquidity_score if liquidity_score is not None else payload.get("liquidity_score", 0.0))
    volatility_penalty = normalized_score(payload.get("volatility_penalty", 0.0))
    timing_risk = normalized_score(payload.get("timing_risk", 0.0))
    api_uncertainty_penalty = normalized_score(payload.get("api_uncertainty_penalty", 0.0))
    score = clip(
        0.25 * spread_penalty
        + 0.25 * low_liquidity_penalty
        + 0.20 * volatility_penalty
        + 0.20 * timing_risk
        + 0.10 * api_uncertainty_penalty,
        0.0,
        1.0,
    )
    reasons: list[str] = []
    if score >= 0.60:
        reasons.append("HIGH_EXECUTION_FRICTION")
    if spread_penalty >= 0.60:
        reasons.append("WIDE_SPREAD")
    if api_uncertainty_penalty >= 0.40:
        reasons.append("API_DATA_INCOMPLETE")
    return ScoreResult(
        score=score,
        explanation=f"EFS={score:.3f} from spread, liquidity, volatility, timing, and API certainty.",
        reason_codes=reasons,
        raw_components={
            "spread_penalty": spread_penalty,
            "low_liquidity_penalty": low_liquidity_penalty,
            "volatility_penalty": volatility_penalty,
            "timing_risk": timing_risk,
            "api_uncertainty_penalty": api_uncertainty_penalty,
        },
    )
