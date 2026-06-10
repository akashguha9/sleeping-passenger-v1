"""Module I — opportunity score aggregator.

Top-level advisory score:

    Opportunity Score = (N x P x E x B x H x R_u x F) / (1 + V + R + C + D)

N  narrative velocity            V  valuation risk
P  probability confirmation      R  regulatory/operational risk
E  embedded proof                C  commoditization risk
B  value-chain node strength     D  casino distortion risk
H  half-life score
R_u residual utility
F  food-chain score

All inputs 0-100.  The multiplicative numerator is folded with a
geometric mean (one dead factor still sinks the score; the scale stays
0-100), and the risk denominator uses 0-1 fractions so a fully risky
signal divides the score by 5.
"""

from __future__ import annotations

from src.alpha import ADVISORY_DISCLAIMER
from src.utils.math_utils import clip

ADVISORY_VERDICTS = (
    "ignore",
    "watchlist",
    "deep_research",
    "event_trade_only",
    "small_position_candidate",
    "core_candidate",
    "avoid_trap",
)

POSITIVE_COMPONENTS = (
    "narrative_velocity",
    "probability_confirmation",
    "embedded_proof",
    "node_strength",
    "half_life",
    "residual_utility",
    "food_chain",
)
RISK_COMPONENTS = (
    "valuation_risk",
    "regulatory_risk",
    "commoditization_risk",
    "casino_distortion",
)

_NEUTRAL = 50.0


def aggregate_opportunity_score(
    components: dict[str, float] | None = None,
    *,
    half_life_days: float | None = None,
) -> dict[str, object]:
    """Aggregate framework component scores (0-100) into one verdict.

    Missing components default to a neutral 50 and are listed in
    ``missing_inputs``.  ``half_life_days``, if given, can force the
    ``event_trade_only`` verdict for fast-decaying signals.
    """
    provided = components or {}
    missing_inputs: list[str] = []
    resolved: dict[str, float] = {}
    for key in POSITIVE_COMPONENTS + RISK_COMPONENTS:
        if key in provided:
            resolved[key] = clip(float(provided[key]), 0.0, 100.0)
        else:
            resolved[key] = _NEUTRAL
            missing_inputs.append(key)

    product = 1.0
    for key in POSITIVE_COMPONENTS:
        product *= resolved[key] / 100.0
    geometric_mean = product ** (1.0 / len(POSITIVE_COMPONENTS))
    risk_load = sum(resolved[key] / 100.0 for key in RISK_COMPONENTS)
    opportunity_score = clip(100.0 * geometric_mean / (1.0 + risk_load), 0.0, 100.0)

    ranked_positive = sorted(
        POSITIVE_COMPONENTS, key=lambda key: resolved[key], reverse=True
    )
    ranked_risk = sorted(
        RISK_COMPONENTS, key=lambda key: resolved[key], reverse=True
    )
    top_positive_drivers = [
        f"{key}={resolved[key]:.0f}" for key in ranked_positive[:3]
    ]
    top_negative_drivers = [
        f"{key}={resolved[key]:.0f}" for key in ranked_risk[:3]
    ]

    if resolved["casino_distortion"] >= 75.0 and resolved["embedded_proof"] < 40.0:
        verdict = "avoid_trap"
    elif half_life_days is not None and half_life_days < 30.0:
        verdict = "event_trade_only"
    elif opportunity_score >= 45.0:
        verdict = "core_candidate"
    elif opportunity_score >= 35.0:
        verdict = "small_position_candidate"
    elif opportunity_score >= 25.0:
        verdict = "deep_research"
    elif opportunity_score >= 12.0:
        verdict = "watchlist"
    else:
        verdict = "ignore"

    return {
        "opportunity_score": opportunity_score,
        "advisory_verdict": verdict,
        "score_components": resolved,
        "top_positive_drivers": top_positive_drivers,
        "top_negative_drivers": top_negative_drivers,
        "missing_inputs": missing_inputs,
        "explanation": [
            f"Geometric mean of {len(POSITIVE_COMPONENTS)} positive "
            f"components = {100.0 * geometric_mean:.1f}/100.",
            f"Risk denominator 1 + {risk_load:.2f} (valuation, regulatory, "
            "commoditization, casino distortion).",
            f"Opportunity score {opportunity_score:.1f}/100 -> {verdict}.",
        ],
        "disclaimer": ADVISORY_DISCLAIMER,
    }
