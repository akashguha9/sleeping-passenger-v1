"""Prediction-market normalization adapter.

Converts already-fetched market data — ``KalshiMarketSnapshot`` /
``MarketSnapshot`` objects, their ``to_dict()`` forms, or manual dicts —
into ``PredictionMarketSignal`` objects with bounded probabilities and a
spread-aware confidence.  Performs NO network I/O: fetching stays in
``src/ingestion``; this module only normalizes.

Probability math
----------------
    p_mid = (bid + ask) / 2          (bid derived as 1 − no_ask when absent)
    spread = ask − bid
    edge = p_model − p_market
    confidence = 100 × (1 − min(1, spread / spread_cap)) × source_quality

Fallback ladder: bid/ask midpoint → implied probability → last price →
neutral 0.5 with zero confidence and an explicit ``missing_inputs`` entry.
"""

from __future__ import annotations

from typing import Any

from src.alpha.signals import PredictionMarketSignal
from src.utils.math_utils import clamp01, clip

# Fraction of probability space at which a quoted spread makes the quote
# worthless for confirmation purposes.
DEFAULT_SPREAD_CAP = 0.10

# Source quality fractions [0, 1]: regulated exchange quotes are harder
# to fake than manually-entered stubs.
SOURCE_QUALITY: dict[str, float] = {
    "kalshi": 0.90,
    "polymarket": 0.80,
    "manual_stub": 0.50,
}
_DEFAULT_SOURCE_QUALITY = 0.50

# Confidence multipliers for weaker derivation methods (no two-sided quote).
_METHOD_CONFIDENCE_FACTOR: dict[str, float] = {
    "bid_ask_mid": 1.0,
    "implied_probability": 0.70,
    "last_price": 0.55,
    "neutral_fallback": 0.0,
}


def normalize_probability(value: Any) -> float | None:
    """Coerce a raw quote into a probability in [0, 1].

    Accepts fractions (0.42) and percent/cent quotes (42 → 0.42).
    Returns ``None`` for unparseable input rather than guessing.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    if number < 0.0:
        return 0.0
    if number > 1.0:
        # Percent/cent quote space: 42 means 42 cents on a 0-100 contract.
        number = number / 100.0
    return clamp01(number)


def derive_market_probability(
    raw_market: dict[str, Any],
    *,
    spread_cap: float = DEFAULT_SPREAD_CAP,
) -> dict[str, Any]:
    """Derive a market probability estimate from one raw market dict.

    Recognized keys (Kalshi/Polymarket snapshot conventions): ``yes_bid``,
    ``yes_ask`` / ``yes_price``, ``no_ask`` / ``no_price``,
    ``implied_probability``, ``last_price``, ``source``.
    """
    missing_inputs: list[str] = []
    source = str(raw_market.get("source") or "manual_stub").strip().lower()
    source_quality = SOURCE_QUALITY.get(source, _DEFAULT_SOURCE_QUALITY)

    yes_ask = normalize_probability(
        raw_market.get("yes_ask", raw_market.get("yes_price"))
    )
    yes_bid = normalize_probability(raw_market.get("yes_bid"))
    no_ask = normalize_probability(
        raw_market.get("no_ask", raw_market.get("no_price"))
    )
    if yes_bid is None and no_ask is not None:
        # A NO ask at q implies a YES bid at 1 − q on a binary contract.
        yes_bid = clamp01(1.0 - no_ask)
    implied = normalize_probability(raw_market.get("implied_probability"))
    last = normalize_probability(raw_market.get("last_price"))

    spread: float | None = None
    if yes_bid is not None and yes_ask is not None:
        spread = max(0.0, yes_ask - yes_bid)
        probability = clamp01((yes_bid + yes_ask) / 2.0)
        method = "bid_ask_mid"
        method_factor = _METHOD_CONFIDENCE_FACTOR[method] * (
            1.0 - min(1.0, spread / max(1e-9, spread_cap))
        )
    elif implied is not None:
        probability = implied
        method = "implied_probability"
        method_factor = _METHOD_CONFIDENCE_FACTOR[method]
        missing_inputs.append("bid_ask_quote")
    elif last is not None:
        probability = last
        method = "last_price"
        method_factor = _METHOD_CONFIDENCE_FACTOR[method]
        missing_inputs.append("bid_ask_quote")
    else:
        probability = 0.5
        method = "neutral_fallback"
        method_factor = _METHOD_CONFIDENCE_FACTOR[method]
        missing_inputs.append("market_probability")

    confidence = clip(100.0 * method_factor * source_quality, 0.0, 100.0)
    return {
        "probability": probability,
        "method": method,
        "spread": spread,
        "source": source,
        "source_quality": source_quality,
        "confidence": confidence,
        "missing_inputs": missing_inputs,
    }


def compute_probability_edge(
    model_probability: float, market_probability: float
) -> float:
    """edge = p_model − p_market, both clamped to [0, 1] first."""
    return clamp01(model_probability) - clamp01(market_probability)


def convert_to_prediction_market_signal(
    raw_event: dict[str, Any] | Any,
    model_probability: float | None = None,
    *,
    spread_cap: float = DEFAULT_SPREAD_CAP,
) -> PredictionMarketSignal:
    """Convert one raw market/event into a ``PredictionMarketSignal``.

    Accepts a snapshot object with ``to_dict()`` (e.g.
    ``KalshiMarketSnapshot``) or a plain dict.  When
    ``model_probability`` is ``None`` the market's own probability is
    used (edge 0): the signal then records the priced probability
    without asserting a model view.
    """
    if hasattr(raw_event, "to_dict"):
        payload = dict(raw_event.to_dict())
    else:
        payload = dict(raw_event)
    estimate = derive_market_probability(payload, spread_cap=spread_cap)
    market_probability = float(estimate["probability"])
    if model_probability is None:
        model_value = market_probability
        estimate["missing_inputs"] = list(estimate["missing_inputs"]) + [
            "model_probability"
        ]
    else:
        model_value = clamp01(model_probability)
    event_name = str(
        payload.get("event_name")
        or payload.get("title")
        or payload.get("question")
        or payload.get("source_market_id")
        or "unnamed_event"
    ).strip()
    resolution_date = str(
        payload.get("resolution_date")
        or payload.get("close_time_utc")
        or payload.get("close_time")
        or ""
    ).strip()
    return PredictionMarketSignal(
        event_name=event_name,
        market_probability=market_probability,
        model_probability=model_value,
        resolution_date=resolution_date,
        source=str(estimate["source"]),
        confidence=float(estimate["confidence"]),
        derivation_method=str(estimate["method"]),
        missing_inputs=list(estimate["missing_inputs"]),
    )


def probability_confirmation_score(
    edge: float, confidence: float
) -> float:
    """Map a probability edge into the 0-100 confirmation component.

    Neutral (no edge or no confidence) is 50.  A fully confident +0.5
    edge saturates at 100; −0.5 at 0.  Confidence scales the edge so a
    wide-spread or stub-sourced quote cannot move the component much.
    """
    scaled = clip(edge, -1.0, 1.0) * clamp01(confidence / 100.0)
    return clip(50.0 + 100.0 * scaled, 0.0, 100.0)
