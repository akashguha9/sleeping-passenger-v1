"""Module B — residual utility engine.

Residual utility is what remains after stripping narrative, logo,
aesthetics, status, and speculative excitement:

    U_residual = U_total - U_narrative - U_aesthetic - U_status - U_speculative
    alpha_proxy ~= U_residual - market_price_expectation

The questions the score encodes: does this solve a recurring,
non-optional problem; would customers stay without the hype; is it
cheaper/faster/safer/more necessary; does demand repeat without
promotion; does failure create urgency; is it underpriced because it
looks boring?
"""

from __future__ import annotations

from src.utils.math_utils import clamp01, clip

# Utility inputs (fractions in [0, 1]) that survive narrative stripping.
RESIDUAL_WEIGHTS: dict[str, float] = {
    "recurring_need": 0.22,
    "non_optional": 0.20,
    "retention_without_hype": 0.18,
    "cost_or_safety_advantage": 0.14,
    "unprompted_repeat_demand": 0.14,
    "failure_urgency": 0.12,
}

# Inputs (fractions in [0, 1]) that measure dependence on story.
NARRATIVE_WEIGHTS: dict[str, float] = {
    "brand_dependence": 0.30,
    "promotion_dependence": 0.25,
    "status_premium": 0.20,
    "speculative_interest": 0.25,
}

DEFAULT_STRIPPED_LAYERS = ["logo", "hype", "aesthetic", "status", "embedded_proof"]

_NEUTRAL = 0.5


def _weighted_average(
    inputs: dict[str, float] | None,
    weights: dict[str, float],
    missing_inputs: list[str],
    prefix: str,
) -> float:
    provided = inputs or {}
    total = 0.0
    for key, weight in weights.items():
        if key in provided:
            value = clamp01(provided[key])
        else:
            value = _NEUTRAL
            missing_inputs.append(f"{prefix}.{key}")
        total += weight * value
    return total / sum(weights.values())


def score_residual_utility(
    utility_inputs: dict[str, float] | None = None,
    narrative_inputs: dict[str, float] | None = None,
    *,
    market_price_expectation: float = 50.0,
    core_job_to_be_done: str = "unspecified",
) -> dict[str, object]:
    """Score residual utility and narrative dependency, both 0-100.

    ``market_price_expectation`` is 0-100: how richly the market already
    prices the asset (100 = priced for perfection).  The alpha proxy is
    residual utility minus that expectation, in [-100, 100].
    """
    missing_inputs: list[str] = []
    residual_fraction = _weighted_average(
        utility_inputs, RESIDUAL_WEIGHTS, missing_inputs, "utility"
    )
    narrative_fraction = _weighted_average(
        narrative_inputs, NARRATIVE_WEIGHTS, missing_inputs, "narrative"
    )
    # Heavy narrative dependence erodes the utility that survives
    # stripping: a score built mostly on story shrinks once the story dies.
    residual_utility_score = clip(
        100.0 * residual_fraction * (1.0 - 0.5 * narrative_fraction), 0.0, 100.0
    )
    narrative_dependency_score = clip(100.0 * narrative_fraction, 0.0, 100.0)
    price_expectation = clip(market_price_expectation, 0.0, 100.0)
    residual_alpha_proxy = clip(
        residual_utility_score - price_expectation, -100.0, 100.0
    )
    explanation = [
        f"Core job to be done: {core_job_to_be_done}.",
        f"Residual utility {residual_utility_score:.1f}/100 after stripping "
        f"{', '.join(DEFAULT_STRIPPED_LAYERS)}.",
        f"Narrative dependency {narrative_dependency_score:.1f}/100 "
        "(higher = value evaporates when the story dies).",
        f"Alpha proxy = residual utility - market price expectation "
        f"({price_expectation:.1f}) = {residual_alpha_proxy:+.1f}.",
    ]
    if missing_inputs:
        explanation.append(
            f"{len(missing_inputs)} input(s) defaulted to neutral 0.5."
        )
    return {
        "residual_utility_score": residual_utility_score,
        "narrative_dependency_score": narrative_dependency_score,
        "residual_alpha_proxy": residual_alpha_proxy,
        "core_job_to_be_done": core_job_to_be_done,
        "stripped_layers": list(DEFAULT_STRIPPED_LAYERS),
        "missing_inputs": missing_inputs,
        "explanation": explanation,
    }
