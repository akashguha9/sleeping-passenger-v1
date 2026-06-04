"""Discovery v2 — a transparent, reusable candidate-eligibility scorer.

Purpose: improve *which* names enter the book (the real lever on win-rate;
exit management only moves realized P/L, not the count of winners). It scores a
candidate on factors knowable BEFORE entry and returns a 0-1 score and a tier:

    TRADE  >= 0.60     WATCH 0.40-0.60     SKIP < 0.40

Factors (weights sum to 1.0):
  * liquidity      0.40  - can you reliably price/size/exit it? Thin names you
                          cannot even get a clean quote for are uninvestable.
                          (data-confidence tier is the operational proxy.)
  * momentum       0.25  - pre-entry trend/relative strength (forward factor;
                          neutral 0.5 when no pre-entry history is supplied —
                          never imputed from the outcome).
  * regime         0.20  - market/regime backdrop (developed-market large cap
                          vs thin emerging names), a coarse PRIOR, not fitted.
  * risk_room      0.15  - distance from the -5% stop at entry; more room = less
                          chance of an immediate noise stop-out.

Read-only, advisory. No execution, no broker, no live fetch. The in-sample
evaluation on the 2026 book uses ONLY leak-free factors (liquidity, regime,
risk_room); momentum is held neutral there so no look-ahead enters the result.
"""
from __future__ import annotations

from typing import Any

_LIQUIDITY = {"high": 1.0, "med": 0.6, "low": 0.2, "unpriceable": 0.0}
# Coarse regime prior by ISO country/region — set ex-ante, not fitted to the book.
_REGIME = {
    "US": 1.0, "DE": 0.9, "FR": 0.9, "GB": 0.85, "CA": 0.85, "JP": 0.8,
    "IN": 0.7, "KR": 0.65,
}
_W = {"liquidity": 0.40, "momentum": 0.25, "regime": 0.20, "risk_room": 0.15}

TRADE, WATCH, SKIP = "TRADE", "WATCH", "SKIP"


def _clip(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def score_candidate(
    *,
    liquidity_tier: str = "low",
    region: str | None = None,
    momentum: float | None = None,
    entry_price: float | None = None,
    recent_low: float | None = None,
    stop_pct: float = 0.05,
) -> dict[str, Any]:
    """Score one candidate. Missing inputs degrade to conservative neutrals."""
    liq = _LIQUIDITY.get(str(liquidity_tier).lower(), 0.2)
    reg = _REGIME.get(str(region or "").upper(), 0.7)
    mom = 0.5 if momentum is None else _clip(momentum)

    # risk_room: how far above the stop did entry sit relative to recent support?
    # If the recent low is already near/through the stop, there's little room.
    if entry_price and recent_low and entry_price > 0:
        stop_px = entry_price * (1 - stop_pct)
        # 1.0 when recent low is comfortably (>=1 stop-width) above the stop.
        room = (recent_low - stop_px) / (entry_price * stop_pct)
        risk_room = _clip(room)
    else:
        risk_room = 0.5

    score = (_W["liquidity"] * liq + _W["momentum"] * mom
             + _W["regime"] * reg + _W["risk_room"] * risk_room)
    # Hard gate: a name you cannot get a clean, current quote for is uninvestable
    # for real money no matter how attractive the other factors look. This is the
    # 'liquidity' factor expressed as a discipline, not a weighting.
    if str(liquidity_tier).lower() == "unpriceable":
        tier = SKIP
    else:
        tier = TRADE if score >= 0.60 else WATCH if score >= 0.40 else SKIP
    return {
        "score": round(score, 4),
        "tier": tier,
        "factors": {"liquidity": liq, "momentum": mom, "regime": reg,
                    "risk_room": round(risk_room, 3)},
        "advisory_status": "ADVISORY_ONLY",
        "human_execution_required": True,
        "broker_api_called": False,
    }


def rank(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Score and sort candidates best-first."""
    out = []
    for c in candidates:
        s = score_candidate(
            liquidity_tier=c.get("liquidity_tier", "low"),
            region=c.get("region"),
            momentum=c.get("momentum"),
            entry_price=c.get("entry_price"),
            recent_low=c.get("recent_low"),
        )
        out.append({**c, **s})
    return sorted(out, key=lambda r: r["score"], reverse=True)


__all__ = ["score_candidate", "rank", "TRADE", "WATCH", "SKIP"]
