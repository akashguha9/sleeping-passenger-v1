"""Liquidity scoring for paper-safe signal admission."""

from __future__ import annotations

from src.models.market import MarketSnapshot
from src.models.scores import ScoreResult
from src.utils.math_utils import clip, safe_div
from src.utils.validation_utils import normalized_score

MAX_ALLOWED_SPREAD = 0.15
MAX_VOLUME = 100_000.0
MAX_LIQUIDITY = 100_000.0
MAX_DEPTH = 10_000.0


def score_liquidity(snapshot: MarketSnapshot | dict[str, object]) -> ScoreResult:
    """Compute LS.

    LS = clip(
        0.35 * LiquidityNorm
      + 0.30 * VolumeNorm
      + 0.20 * OrderBookDepthNorm
      - 0.15 * SpreadPenalty,
      0, 1
    )
    """
    payload = snapshot.to_dict() if isinstance(snapshot, MarketSnapshot) else dict(snapshot)
    liquidity = clip(safe_div(float(payload.get("liquidity", 0.0)), MAX_LIQUIDITY), 0.0, 1.0)
    volume = clip(safe_div(float(payload.get("volume", 0.0)), MAX_VOLUME), 0.0, 1.0)
    depth = clip(safe_div(float(payload.get("order_book_depth", 0.0)), MAX_DEPTH), 0.0, 1.0)
    spread_penalty = clip(safe_div(float(payload.get("spread", 0.0)), MAX_ALLOWED_SPREAD), 0.0, 1.0)
    score = clip(
        0.35 * liquidity + 0.30 * volume + 0.20 * depth - 0.15 * spread_penalty,
        0.0,
        1.0,
    )
    reasons: list[str] = []
    if score >= 0.50:
        reasons.append("SUFFICIENT_LIQUIDITY")
    if score < 0.40:
        reasons.append("LOW_LIQUIDITY")
    if spread_penalty >= 0.60:
        reasons.append("WIDE_SPREAD")
    return ScoreResult(
        score=score,
        explanation=f"LS={score:.3f} from liquidity {liquidity:.2f}, volume {volume:.2f}, and spread penalty {spread_penalty:.2f}.",
        reason_codes=reasons,
        raw_components={
            "liquidity_norm": liquidity,
            "volume_norm": volume,
            "order_book_depth_norm": depth,
            "spread_penalty": spread_penalty,
        },
    )
