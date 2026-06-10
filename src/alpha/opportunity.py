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


# ---------------------------------------------------------------------------
# v2 — evidence-weighted aggregation with trap flags and confidence
# ---------------------------------------------------------------------------

TRAP_FLAGS = (
    "high_casino_low_food_chain",
    "high_narrative_low_proof",
    "short_half_life_high_valuation",
    "strong_theme_weak_node_capture",
    "high_probability_edge_low_liquidity",
    "filing_claim_without_hard_evidence",
    "risk_disclosure_overhang",
    "overconcentrated_portfolio_exposure",
)

# Penalty weights for the v2 penalty core (sum to 1.0).
_PENALTY_WEIGHTS: dict[str, float] = {
    "valuation_risk": 0.20,
    "regulatory_risk": 0.15,
    "commoditization_risk": 0.15,
    "casino_distortion": 0.20,
    "evidence_gap_risk": 0.15,
    "filing_risk_disclosure_score": 0.15,
}

# Confidence weights (sum to 1.0).  calibration_support stays 0 until an
# outcome-backed calibration map exists — an honest, visible gap.
_CONFIDENCE_WEIGHTS: dict[str, float] = {
    "evidence_quality": 0.30,
    "input_completeness": 0.25,
    "source_quality": 0.20,
    "calibration_support": 0.15,
    "deterministic_replayability": 0.10,
}

_VERDICT_LADDER = (
    "ignore",
    "watchlist",
    "deep_research",
    "small_position_candidate",
    "core_candidate",
)


def _cap_verdict(verdict: str, ceiling: str) -> str:
    if verdict not in _VERDICT_LADDER or ceiling not in _VERDICT_LADDER:
        return verdict
    if _VERDICT_LADDER.index(verdict) > _VERDICT_LADDER.index(ceiling):
        return ceiling
    return verdict


def aggregate_opportunity_score_v2(
    components: dict[str, float] | None = None,
    *,
    half_life_days: float | None = None,
    filing_risk_disclosure_score: float | None = None,
    evidence_quality: float | None = None,
    source_quality: float | None = None,
    calibration_support: float | None = None,
    probability_edge: float | None = None,
    liquidity_score: float | None = None,
    portfolio_overlap_risk: float | None = None,
    filing_claims_present: bool = False,
) -> dict[str, object]:
    """Evidence-weighted opportunity aggregation.

        positive_core    = geometric mean of the 7 positive components
        penalty_core     = weighted mean of 6 risk terms (incl. evidence gap
                           and filing risk disclosures)
        opportunity      = clamp(positive_core × (1 − penalty_core/100), 0, 100)

    Hard evidence lifts confidence; risk disclosures and evidence gaps
    penalize the score; missing proof caps the verdict at deep_research;
    casino-heavy/low-proof shapes raise trap flags.  The probability edge
    moves only the event/confirmation component (already inside
    ``components``), never residual utility.
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

    if evidence_quality is None:
        evidence_quality_score = resolved["embedded_proof"]
    else:
        evidence_quality_score = clip(float(evidence_quality), 0.0, 100.0)
    evidence_gap_risk = 100.0 - evidence_quality_score

    if filing_risk_disclosure_score is None:
        filing_risk = 0.0
        missing_inputs.append("filing_risk_disclosure_score")
    else:
        filing_risk = clip(float(filing_risk_disclosure_score), 0.0, 100.0)

    product = 1.0
    for key in POSITIVE_COMPONENTS:
        product *= resolved[key] / 100.0
    positive_core = 100.0 * product ** (1.0 / len(POSITIVE_COMPONENTS))

    penalty_terms = {
        "valuation_risk": resolved["valuation_risk"],
        "regulatory_risk": resolved["regulatory_risk"],
        "commoditization_risk": resolved["commoditization_risk"],
        "casino_distortion": resolved["casino_distortion"],
        "evidence_gap_risk": evidence_gap_risk,
        "filing_risk_disclosure_score": filing_risk,
    }
    penalty_core = sum(
        _PENALTY_WEIGHTS[key] * value for key, value in penalty_terms.items()
    )
    opportunity_score = clip(
        positive_core * (1.0 - penalty_core / 100.0), 0.0, 100.0
    )

    # ----- trap flags (deterministic thresholds) -----
    trap_flags: list[str] = []
    if resolved["casino_distortion"] >= 70.0 and resolved["food_chain"] < 40.0:
        trap_flags.append("high_casino_low_food_chain")
    if resolved["narrative_velocity"] >= 70.0 and evidence_quality_score < 35.0:
        trap_flags.append("high_narrative_low_proof")
    short_half_life = (
        half_life_days is not None and half_life_days < 30.0
    ) or resolved["half_life"] < 35.0
    if short_half_life and resolved["valuation_risk"] >= 60.0:
        trap_flags.append("short_half_life_high_valuation")
    if resolved["residual_utility"] >= 65.0 and resolved["node_strength"] < 35.0:
        trap_flags.append("strong_theme_weak_node_capture")
    if (
        probability_edge is not None
        and liquidity_score is not None
        and abs(probability_edge) >= 0.15
        and liquidity_score < 35.0
    ):
        trap_flags.append("high_probability_edge_low_liquidity")
    if filing_claims_present and evidence_quality_score < 30.0:
        trap_flags.append("filing_claim_without_hard_evidence")
    if filing_risk >= 60.0:
        trap_flags.append("risk_disclosure_overhang")
    if portfolio_overlap_risk is not None and portfolio_overlap_risk >= 60.0:
        trap_flags.append("overconcentrated_portfolio_exposure")

    # ----- confidence -----
    total_keys = len(POSITIVE_COMPONENTS) + len(RISK_COMPONENTS)
    input_completeness = 100.0 * (
        sum(1 for key in POSITIVE_COMPONENTS + RISK_COMPONENTS if key in provided)
        / total_keys
    )
    confidence_terms = {
        "evidence_quality": evidence_quality_score,
        "input_completeness": input_completeness,
        "source_quality": clip(
            float(source_quality) if source_quality is not None else 50.0, 0.0, 100.0
        ),
        # 0 until outcome-backed calibration exists; see replay harness.
        "calibration_support": clip(
            float(calibration_support) if calibration_support is not None else 0.0,
            0.0,
            100.0,
        ),
        # Pure deterministic function of inputs — fully replayable.
        "deterministic_replayability": 100.0,
    }
    confidence = clip(
        sum(_CONFIDENCE_WEIGHTS[key] * value for key, value in confidence_terms.items()),
        0.0,
        100.0,
    )

    # ----- verdict -----
    if "high_casino_low_food_chain" in trap_flags or (
        "high_narrative_low_proof" in trap_flags
    ):
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
    # Missing proof keeps the verdict conservative regardless of score.
    if evidence_quality_score < 40.0:
        verdict = _cap_verdict(verdict, "deep_research")
    # No attention catalyst yet: real-but-unnoticed stays research, not a
    # position call ("where the world *starts noticing* something real").
    if resolved["narrative_velocity"] < 30.0:
        verdict = _cap_verdict(verdict, "deep_research")
    # Position-candidate verdicts require outcome-backed calibration from
    # the replay harness; an uncalibrated engine may research, not size.
    if confidence_terms["calibration_support"] < 10.0:
        verdict = _cap_verdict(verdict, "deep_research")
    if input_completeness < 50.0:
        verdict = _cap_verdict(verdict, "watchlist")

    # ----- why-not explanations -----
    why_not_higher: list[str] = []
    why_not_lower: list[str] = []
    for key in missing_inputs:
        why_not_higher.append(f"missing input '{key}' defaulted conservatively")
    for key, value in penalty_terms.items():
        if value >= 60.0:
            why_not_higher.append(f"{key} is elevated ({value:.0f}/100)")
    for key in POSITIVE_COMPONENTS:
        if resolved[key] < 40.0:
            why_not_higher.append(f"{key} is weak ({resolved[key]:.0f}/100)")
    if confidence_terms["calibration_support"] == 0.0:
        why_not_higher.append(
            "no outcome-backed calibration support yet (replay harness has no history)"
        )
    for key in POSITIVE_COMPONENTS:
        if resolved[key] >= 70.0:
            why_not_lower.append(f"{key} is strong ({resolved[key]:.0f}/100)")
    if evidence_quality_score >= 70.0:
        why_not_lower.append(
            f"hard evidence quality {evidence_quality_score:.0f}/100 supports the claims"
        )
    for key, value in penalty_terms.items():
        if value <= 20.0:
            why_not_lower.append(f"{key} is low ({value:.0f}/100)")

    ranked_positive = sorted(
        POSITIVE_COMPONENTS, key=lambda key: resolved[key], reverse=True
    )
    ranked_penalty = sorted(
        penalty_terms, key=lambda key: penalty_terms[key], reverse=True
    )
    return {
        "opportunity_score": opportunity_score,
        "confidence": confidence,
        "advisory_verdict": verdict,
        "evidence_quality_score": evidence_quality_score,
        "evidence_gap_risk": evidence_gap_risk,
        "filing_risk_disclosure_score": filing_risk,
        "positive_core": positive_core,
        "penalty_core": penalty_core,
        "score_components": resolved,
        "penalty_components": penalty_terms,
        "confidence_components": confidence_terms,
        "trap_flags": trap_flags,
        "why_not_higher": why_not_higher,
        "why_not_lower": why_not_lower,
        "top_positive_drivers": [
            f"{key}={resolved[key]:.0f}" for key in ranked_positive[:3]
        ],
        "top_negative_drivers": [
            f"{key}={penalty_terms[key]:.0f}" for key in ranked_penalty[:3]
        ],
        "missing_inputs": missing_inputs,
        "explanation": [
            f"Positive core (geometric mean) {positive_core:.1f}/100.",
            f"Penalty core (weighted risks incl. evidence gap and filing "
            f"disclosures) {penalty_core:.1f}/100.",
            f"Opportunity {opportunity_score:.1f}/100, confidence "
            f"{confidence:.1f}/100 -> {verdict}.",
        ],
        "disclaimer": ADVISORY_DISCLAIMER,
    }
