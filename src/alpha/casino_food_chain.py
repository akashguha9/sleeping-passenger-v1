"""Module A — casino vs food-chain classifier.

Casino layer: hype, speculation, social attention, aesthetics, price
momentum, meme energy, influencer narrative, options/volume spikes.

Food-chain layer: revenue, cash flow, customer demand, suppliers,
regulation, operating leverage, repeat need, economic necessity.

Both scores are deterministic 0-100 sigmoids over weighted, bounded
inputs.  Missing inputs default to a neutral 0.5 and are reported in
``missing_inputs`` — they never crash the classifier.
"""

from __future__ import annotations

import math

from src.utils.math_utils import clamp01

# Positive-direction casino inputs (all fractions in [0, 1]).
CASINO_WEIGHTS: dict[str, float] = {
    "mention_velocity": 0.22,
    "sentiment_intensity": 0.16,
    "volume_spike": 0.18,
    "options_activity": 0.16,
    "influencer_density": 0.14,
    "headline_intensity": 0.14,
}

# Food-chain inputs: positive weights strengthen the score, negative
# weights (leverage, commoditization) weaken it.
FOOD_CHAIN_WEIGHTS: dict[str, float] = {
    "revenue_quality": 0.20,
    "fcf_quality": 0.20,
    "gross_margin_quality": 0.14,
    "demand_recurrence": 0.16,
    "pricing_power": 0.14,
    "balance_sheet_strength": 0.16,
    "leverage_risk": -0.18,
    "commoditization_risk": -0.16,
}

_NEUTRAL = 0.5
# Sigmoid steepness: neutral inputs land at exactly 50; fully saturated
# inputs approach (but stay inside) the [0, 100] bounds.
_STEEPNESS = 6.0

CLASSIFICATIONS = ("casino_heavy", "food_chain_heavy", "balanced", "weak_signal")
_GAP_THRESHOLD = 20.0
_WEAK_THRESHOLD = 35.0


def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z))


def _weighted_layer_score(
    inputs: dict[str, float] | None,
    weights: dict[str, float],
    missing_inputs: list[str],
    prefix: str,
) -> float:
    """Weighted sigmoid score over [0, 1] inputs, centred so neutral = 50."""
    provided = inputs or {}
    z = 0.0
    abs_weight = sum(abs(w) for w in weights.values())
    for key, weight in weights.items():
        if key in provided:
            value = clamp01(provided[key])
        else:
            value = _NEUTRAL
            missing_inputs.append(f"{prefix}.{key}")
        # Negative weights invert direction: a high leverage_risk pushes
        # the food-chain score down by the same magnitude a high
        # fcf_quality pushes it up.
        z += weight * (value - _NEUTRAL)
    return 100.0 * _sigmoid(_STEEPNESS * z / abs_weight)


def classify_casino_food_chain(
    casino_inputs: dict[str, float] | None = None,
    food_chain_inputs: dict[str, float] | None = None,
) -> dict[str, object]:
    """Score the casino and food-chain layers and classify the gap."""
    missing_inputs: list[str] = []
    casino_score = _weighted_layer_score(
        casino_inputs, CASINO_WEIGHTS, missing_inputs, "casino"
    )
    food_chain_score = _weighted_layer_score(
        food_chain_inputs, FOOD_CHAIN_WEIGHTS, missing_inputs, "food_chain"
    )
    gap = casino_score - food_chain_score

    if casino_score < _WEAK_THRESHOLD and food_chain_score < _WEAK_THRESHOLD:
        classification = "weak_signal"
    elif gap >= _GAP_THRESHOLD:
        classification = "casino_heavy"
    elif gap <= -_GAP_THRESHOLD:
        classification = "food_chain_heavy"
    else:
        classification = "balanced"

    explanation = [
        f"Casino layer score {casino_score:.1f}/100 (hype, attention, speculation).",
        f"Food-chain layer score {food_chain_score:.1f}/100 (cash flow, demand, necessity).",
        f"Gap (casino - food_chain) = {gap:+.1f} -> {classification}.",
    ]
    if missing_inputs:
        explanation.append(
            f"{len(missing_inputs)} input(s) defaulted to neutral 0.5; "
            "scores lean toward 50 until real inputs arrive."
        )
    return {
        "casino_score": casino_score,
        "food_chain_score": food_chain_score,
        "casino_food_chain_gap": gap,
        "classification": classification,
        "missing_inputs": missing_inputs,
        "explanation": explanation,
    }
