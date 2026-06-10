"""Module G — compatibility / sequencing / portfolio fit engine.

Two apex assets can clash (vanilla ice cream on Margherita pizza;
Nvidia + TSMC + ASML as one concentrated supply-chain bet).  Quality is
local; composition is global:

    Portfolio Value = sum(w_i * Q_i) + sum(w_i * w_j * C_ij)

with pairwise compatibility C_ij in [-1, 1]: > 0 synergy, 0 independent,
< 0 interference / concentration risk.
"""

from __future__ import annotations

from src.utils.math_utils import clamp01, clip

SEQUENCING_RECOMMENDATIONS = (
    "core_now",
    "watch_later",
    "hedge",
    "avoid_stack",
    "event_only",
)


def _pair_key(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def assess_portfolio_fit(
    assets: list[dict[str, object]],
    compatibility: dict[tuple[str, str], float] | None = None,
) -> dict[str, object]:
    """Assess composition quality for assets with name/weight/quality.

    ``assets``: each dict needs ``name``, ``weight`` (fraction, weights
    are renormalized), and ``quality`` (0-100).  ``compatibility`` maps
    unordered name pairs to C_ij in [-1, 1]; missing pairs default to 0
    (independent) and are reported in ``missing_inputs``.
    """
    compatibility = compatibility or {}
    missing_inputs: list[str] = []
    names = [str(a["name"]) for a in assets]
    raw_weights = [max(0.0, float(a.get("weight", 0.0))) for a in assets]
    total_weight = sum(raw_weights) or 1.0
    weights = [w / total_weight for w in raw_weights]
    qualities = [clip(float(a.get("quality", 50.0)), 0.0, 100.0) for a in assets]

    base_value = sum(w * q for w, q in zip(weights, qualities))
    interaction = 0.0
    negative_interaction = 0.0
    matrix: list[dict[str, object]] = []
    for i in range(len(assets)):
        for j in range(i + 1, len(assets)):
            key = _pair_key(names[i], names[j])
            if key in compatibility:
                c_ij = clip(float(compatibility[key]), -1.0, 1.0)
            else:
                c_ij = 0.0
                missing_inputs.append(f"compatibility[{key[0]},{key[1]}]")
            # C_ij scaled to the 0-100 quality space; the factor 2 keeps a
            # fully synergistic/clashing 50/50 pair worth +/-25 points.
            contribution = 2.0 * weights[i] * weights[j] * c_ij * 100.0
            interaction += contribution
            if c_ij < 0:
                negative_interaction += -contribution
            matrix.append(
                {"pair": [key[0], key[1]], "c_ij": c_ij, "contribution": contribution}
            )

    portfolio_fit_score = clip(base_value + interaction, 0.0, 100.0)
    overlap_risk = clip(negative_interaction * 4.0, 0.0, 100.0)

    if overlap_risk >= 50.0:
        sequencing = "avoid_stack"
    elif portfolio_fit_score >= 70.0 and overlap_risk < 25.0:
        sequencing = "core_now"
    elif any(c["c_ij"] < -0.5 for c in matrix):
        sequencing = "hedge"
    elif portfolio_fit_score >= 50.0:
        sequencing = "watch_later"
    else:
        sequencing = "event_only"

    return {
        "portfolio_fit_score": portfolio_fit_score,
        "overlap_risk": overlap_risk,
        "compatibility_matrix": matrix,
        "sequencing_recommendation": sequencing,
        "missing_inputs": missing_inputs,
        "explanation": [
            f"Weighted standalone quality {base_value:.1f}/100; interaction "
            f"term {interaction:+.1f} from {len(matrix)} pair(s).",
            f"Overlap risk {overlap_risk:.1f}/100 from negative C_ij pairs "
            "(interference / concentration).",
            f"Sequencing: {sequencing}. Excellence is local; composition is global.",
        ],
    }


def pairwise_compatibility(
    quality_a: float, quality_b: float, correlation: float
) -> float:
    """Heuristic C_ij from factor correlation: high correlation between two
    good assets is concentration (negative), low/negative correlation is
    diversification (positive)."""
    rho = clip(correlation, -1.0, 1.0)
    strength = clamp01((quality_a + quality_b) / 200.0)
    return clip(-rho * strength, -1.0, 1.0)
