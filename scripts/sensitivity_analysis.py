"""Robustness / sensitivity analysis for weighted advisory scores (Pass 4).

For a linear advisory score S = Σ_j w_j·x_j, answer: which features
dominate, which are fragile, what happens when data is missing or noisy,
and — most importantly — when should the model ABSTAIN instead of
pretending it knows.

Methods (test-pinned on synthetic models with known answers):
  * one-at-a-time feature perturbation  ΔS_j = S(x_j+ε) − S(x_j) = w_j·ε
  * weight perturbation                 ΔS_wj = x_j·ε
  * missing-feature decision-flip check (x_j → 0)
  * Monte Carlo noise  S_m = Σ_j (w_j+η_j)(x_j+ε_j), η,ε ~ U(−σ, σ)

Hard rules: weights that should sum to 1 are validated; NaN/None feature
values are an explicit error (missingness is modeled by the flip check,
never by silent coercion); an unstable score yields an ABSTAIN
recommendation. Advisory-only throughout.
"""
from __future__ import annotations

import math
import random
import statistics

ABSTAIN = "ABSTAIN"
PROCEED = "PROCEED_WITH_HUMAN_REVIEW"


class SensitivityError(ValueError):
    """Raised on malformed model input (NaN features, bad weights)."""


def _validate(weights: dict[str, float], features: dict[str, float],
              require_weight_sum_1: bool) -> None:
    if set(weights) != set(features):
        raise SensitivityError(
            f"weight/feature key mismatch: {sorted(set(weights) ^ set(features))}"
        )
    if not weights:
        raise SensitivityError("empty model")
    for name, x in features.items():
        if x is None or (isinstance(x, float) and math.isnan(x)):
            raise SensitivityError(
                f"feature {name!r} is missing/NaN — model missingness "
                "explicitly (flip check), never by silent coercion"
            )
    for name, w in weights.items():
        if w is None or (isinstance(w, float) and math.isnan(w)):
            raise SensitivityError(f"weight {name!r} is NaN/None")
    if require_weight_sum_1:
        total = sum(weights.values())
        if abs(total - 1.0) > 1e-6:
            raise SensitivityError(
                f"weights sum to {total:.6f}, expected 1.0 — renormalize "
                "deliberately, not implicitly"
            )


def base_score(weights: dict[str, float], features: dict[str, float]) -> float:
    return sum(weights[k] * features[k] for k in weights)


def feature_perturbations(
    weights: dict[str, float], features: dict[str, float], epsilon: float = 0.1
) -> dict[str, float]:
    """ΔS_j for x_j → x_j + ε (linear model: exactly w_j·ε)."""
    return {k: weights[k] * epsilon for k in weights}


def weight_perturbations(
    weights: dict[str, float], features: dict[str, float], epsilon: float = 0.1
) -> dict[str, float]:
    """ΔS_wj for w_j → w_j + ε (linear model: exactly x_j·ε)."""
    return {k: features[k] * epsilon for k in weights}


def missing_feature_flips(
    weights: dict[str, float], features: dict[str, float],
    decision_threshold: float,
) -> list[str]:
    """Features whose absence (x_j → 0) flips the decision."""
    s0 = base_score(weights, features)
    side0 = s0 >= decision_threshold
    flips = []
    for k in weights:
        without = dict(features)
        without[k] = 0.0
        if (base_score(weights, without) >= decision_threshold) != side0:
            flips.append(k)
    return flips


def monte_carlo_stability(
    weights: dict[str, float], features: dict[str, float],
    *, sigma: float = 0.05, n_draws: int = 500,
    decision_threshold: float | None = None, seed: int = 7,
) -> dict:
    """Noise both weights and features; how often does the decision hold?"""
    rng = random.Random(seed)
    scores = []
    for _ in range(n_draws):
        s = sum(
            (weights[k] + rng.uniform(-sigma, sigma))
            * (features[k] + rng.uniform(-sigma, sigma))
            for k in weights
        )
        scores.append(s)
    out = {
        "mean": statistics.fmean(scores),
        "std": statistics.pstdev(scores),
        "p05": sorted(scores)[int(0.05 * n_draws)],
        "p95": sorted(scores)[int(0.95 * n_draws)],
        "n_draws": n_draws,
        "sigma": sigma,
    }
    if decision_threshold is not None:
        agree = sum(1 for s in scores
                    if (s >= decision_threshold)
                    == (base_score(weights, features) >= decision_threshold))
        out["decision_agreement"] = agree / n_draws
    return out


def analyze(
    weights: dict[str, float],
    features: dict[str, float],
    *,
    decision_threshold: float = 0.5,
    epsilon: float = 0.1,
    sigma: float = 0.05,
    require_weight_sum_1: bool = True,
    stability_floor: float = 0.8,
) -> dict:
    """Full sensitivity report with an explicit abstain recommendation."""
    _validate(weights, features, require_weight_sum_1)
    s0 = base_score(weights, features)
    dphi = feature_perturbations(weights, features, epsilon)
    dw = weight_perturbations(weights, features, epsilon)
    flips = missing_feature_flips(weights, features, decision_threshold)
    mc = monte_carlo_stability(
        weights, features, sigma=sigma, decision_threshold=decision_threshold
    )
    # Dominance: contribution share of |w_j x_j|.
    contributions = {k: abs(weights[k] * features[k]) for k in weights}
    total_contrib = sum(contributions.values()) or 1.0
    dominance = {k: v / total_contrib for k, v in contributions.items()}
    dominant = max(dominance, key=dominance.get)

    unstable = (
        mc.get("decision_agreement", 1.0) < stability_floor
        or len(flips) >= max(1, len(weights) // 2)
    )
    recommendation = ABSTAIN if unstable else PROCEED
    reasons = []
    if mc.get("decision_agreement", 1.0) < stability_floor:
        reasons.append(
            f"decision agreement {mc['decision_agreement']:.2f} under noise "
            f"σ={sigma} is below the {stability_floor} floor"
        )
    if flips:
        reasons.append(f"decision flips if any of {flips} is missing")
    if dominance[dominant] > 0.6:
        reasons.append(
            f"single feature {dominant!r} carries {dominance[dominant]:.0%} "
            "of the score — fragile by construction"
        )
    return {
        "base_score": s0,
        "decision_threshold": decision_threshold,
        "feature_sensitivity": dphi,
        "weight_sensitivity": dw,
        "dominance": dominance,
        "dominant_feature": dominant,
        "missing_data_flips": flips,
        "monte_carlo": mc,
        "recommendation": recommendation,
        "recommendation_reasons": reasons,
        "advisory_only": True,
        "human_required": True,
    }
