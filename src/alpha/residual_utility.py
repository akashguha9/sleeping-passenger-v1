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


# ---------------------------------------------------------------------------
# v2 — structured job-to-be-done / failure-cost / substitution model
# ---------------------------------------------------------------------------

NECESSITY_TYPES = (
    "survival",
    "compliance",
    "productivity",
    "convenience",
    "status",
    "entertainment",
    "speculation",
)

# How non-optional each necessity type is (0-100): you cannot opt out of
# water; you can opt out of a badge.
_NECESSITY_TYPE_SCORE: dict[str, float] = {
    "survival": 100.0,
    "compliance": 85.0,
    "productivity": 70.0,
    "convenience": 50.0,
    "status": 35.0,
    "entertainment": 30.0,
    "speculation": 10.0,
}

RESIDUAL_UTILITY_CLASSES = (
    "apex_necessity",
    "durable_utility",
    "convenience_utility",
    "status_utility",
    "speculative_utility",
    "weak_utility",
)

_V2_POSITIVE_FACTORS = (
    "necessity",
    "failure_cost_score",
    "frequency_score",
    "switching_cost_score",
    "willingness_to_pay_score",
    "boring_but_essential_score",
)


def score_residual_utility_v2(
    *,
    job_to_be_done: str,
    necessity_type: str,
    failure_cost_score: float = 50.0,
    substitution_risk_score: float = 50.0,
    frequency_score: float = 50.0,
    switching_cost_score: float = 50.0,
    willingness_to_pay_score: float = 50.0,
    boring_but_essential_score: float = 50.0,
    narrative_dependency_score: float = 50.0,
) -> dict[str, object]:
    """Structured residual utility: JTBD × failure cost × substitution.

        Residual Utility = normalize(
            Necessity × FailureCost × Frequency × SwitchingCost
            × WillingnessToPay × BoringButEssential
            / (1 + SubstitutionRisk + NarrativeDependency)
        )

    implemented as a geometric mean of the six positive factors over the
    risk denominator (one dead factor collapses the job).  All inputs are
    0-100; unknown ``necessity_type`` degrades to convenience and is
    reported in ``missing_inputs``.
    """
    missing_inputs: list[str] = []
    necessity = _NECESSITY_TYPE_SCORE.get(necessity_type)
    if necessity is None:
        missing_inputs.append(f"unknown necessity_type '{necessity_type}'")
        necessity_type = "convenience"
        necessity = _NECESSITY_TYPE_SCORE[necessity_type]

    factors = {
        "necessity": necessity,
        "failure_cost_score": clip(failure_cost_score, 0.0, 100.0),
        "frequency_score": clip(frequency_score, 0.0, 100.0),
        "switching_cost_score": clip(switching_cost_score, 0.0, 100.0),
        "willingness_to_pay_score": clip(willingness_to_pay_score, 0.0, 100.0),
        "boring_but_essential_score": clip(boring_but_essential_score, 0.0, 100.0),
    }
    substitution = clip(substitution_risk_score, 0.0, 100.0)
    narrative = clip(narrative_dependency_score, 0.0, 100.0)

    product = 1.0
    for key in _V2_POSITIVE_FACTORS:
        product *= factors[key] / 100.0
    geometric_mean = product ** (1.0 / len(_V2_POSITIVE_FACTORS))
    denominator = 1.0 + substitution / 100.0 + narrative / 100.0
    residual_utility_score = clip(100.0 * geometric_mean / denominator, 0.0, 100.0)

    # Classification: necessity type sets the family, score sets the rank.
    if necessity_type == "speculation":
        utility_class = "speculative_utility"
    elif necessity_type == "status":
        utility_class = "status_utility" if residual_utility_score >= 15.0 else "weak_utility"
    elif (
        residual_utility_score >= 40.0
        and necessity_type in ("survival", "compliance")
        and factors["failure_cost_score"] >= 70.0
    ):
        utility_class = "apex_necessity"
    elif residual_utility_score >= 30.0 and necessity_type in (
        "survival",
        "compliance",
        "productivity",
    ):
        utility_class = "durable_utility"
    elif necessity_type == "convenience" and residual_utility_score >= 20.0:
        utility_class = "convenience_utility"
    else:
        utility_class = "weak_utility"

    return {
        "job_to_be_done": job_to_be_done,
        "necessity_type": necessity_type,
        "failure_cost_score": factors["failure_cost_score"],
        "substitution_risk_score": substitution,
        "frequency_score": factors["frequency_score"],
        "switching_cost_score": factors["switching_cost_score"],
        "willingness_to_pay_score": factors["willingness_to_pay_score"],
        "boring_but_essential_score": factors["boring_but_essential_score"],
        "narrative_dependency_score": narrative,
        "residual_utility_score": residual_utility_score,
        "residual_utility_class": utility_class,
        "missing_inputs": missing_inputs,
        "explanation": [
            f"Job: {job_to_be_done} (necessity type '{necessity_type}' -> "
            f"{necessity:.0f}/100).",
            f"Geometric mean of six positive factors "
            f"{100.0 * geometric_mean:.1f}/100 over denominator "
            f"{denominator:.2f} (substitution + narrative dependency).",
            f"Residual utility {residual_utility_score:.1f}/100 -> "
            f"{utility_class}.",
        ],
    }
