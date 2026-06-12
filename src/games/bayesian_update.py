"""Tempered Bayesian posterior engine: belief moves only as far as the
evidence deserves.

Classical Bayes lets any likelihood ratio move the posterior at full
force. Here every evidence item's likelihood ratio is TEMPERED by how
much it can be trusted:

    trust  = reliability × reality_anchor × dice_confidence
             × (1 − manipulation_risk)            (each 0–1)
    LR_eff = LR ^ trust          (power posterior / tempered update)
    posterior_odds = prior_odds × Π LR_eff

Properties that make this gaming-resistant and honest:
  * trust = 0  →  LR_eff = 1  →  the evidence moves NOTHING;
  * trust = 1  →  full Bayesian update;
  * a hyperreal, manipulated, low-reliability source is mathematically
    incapable of dragging the posterior, no matter how loud its LR.

Deterministic, explainable per item, ADVISORY_ONLY.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from src.utils.math_utils import clamp01, clip
from src.utils.validation_utils import normalized_score

# Likelihood ratios are clamped so one item can never be infinitely loud.
MAX_LIKELIHOOD_RATIO = 20.0
MIN_LIKELIHOOD_RATIO = 1.0 / MAX_LIKELIHOOD_RATIO


@dataclass(slots=True)
class EvidenceUpdate:
    """One evidence item's tempered contribution."""

    name: str
    likelihood_ratio: float
    trust: float
    effective_ratio: float
    posterior_after: float
    explanation: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class BayesianUpdateResult:
    """Full posterior trace: prior -> each tempered update -> posterior."""

    prior: float
    posterior: float
    total_effective_ratio: float
    updates: list[EvidenceUpdate] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["updates"] = [u.to_dict() for u in self.updates]
        return payload


def likelihood_to_ratio(p_given_h: float, p_given_not_h: float) -> float:
    """LR = P(evidence | H) / P(evidence | ¬H), clamped to sane bounds."""
    numerator = max(normalized_score(p_given_h), 1e-6)
    denominator = max(normalized_score(p_given_not_h), 1e-6)
    return clip(numerator / denominator, MIN_LIKELIHOOD_RATIO,
                MAX_LIKELIHOOD_RATIO)


def evidence_trust(
    *,
    reliability: float = 1.0,
    reality_anchor: float = 1.0,
    dice_confidence: float = 1.0,
    manipulation_risk: float = 0.0,
) -> float:
    """How much of the likelihood ratio this evidence has earned."""
    return clamp01(
        normalized_score(reliability, 1.0)
        * normalized_score(reality_anchor, 1.0)
        * normalized_score(dice_confidence, 1.0)
        * (1.0 - normalized_score(manipulation_risk))
    )


def bayesian_update(
    *,
    prior: float,
    evidence: list[dict[str, float | str]] | None = None,
) -> BayesianUpdateResult:
    """Sequential tempered update from a prior over evidence items.

    Each item: ``{"name", "likelihood_ratio" (or "p_given_h" +
    "p_given_not_h"), "reliability", "reality_anchor",
    "dice_confidence", "manipulation_risk"}``. The prior is typically a
    prediction-market probability — tradable belief used as a PRIOR,
    never as truth.
    """
    p = clip(float(prior), 0.01, 0.99)
    odds = p / (1.0 - p)
    updates: list[EvidenceUpdate] = []
    total_ratio = 1.0

    for item in evidence or []:
        if "likelihood_ratio" in item:
            ratio = clip(float(item["likelihood_ratio"]),
                         MIN_LIKELIHOOD_RATIO, MAX_LIKELIHOOD_RATIO)
        else:
            ratio = likelihood_to_ratio(
                float(item.get("p_given_h", 0.5)),
                float(item.get("p_given_not_h", 0.5)),
            )
        trust = evidence_trust(
            reliability=float(item.get("reliability", 1.0)),
            reality_anchor=float(item.get("reality_anchor", 1.0)),
            dice_confidence=float(item.get("dice_confidence", 1.0)),
            manipulation_risk=float(item.get("manipulation_risk", 0.0)),
        )
        effective = ratio ** trust  # tempered: trust=0 -> 1 (no movement)
        odds *= effective
        total_ratio *= effective
        posterior_now = odds / (1.0 + odds)
        direction = (
            "supports" if ratio > 1.0 else
            ("opposes" if ratio < 1.0 else "neutral on")
        )
        updates.append(EvidenceUpdate(
            name=str(item.get("name", "unnamed evidence")),
            likelihood_ratio=ratio,
            trust=trust,
            effective_ratio=effective,
            posterior_after=posterior_now,
            explanation=(
                f"{direction} H with LR {ratio:.2f}, tempered by trust "
                f"{trust:.2f} -> effective {effective:.2f}"
            ),
        ))

    posterior = clip(odds / (1.0 + odds), 0.001, 0.999)
    rationale = [
        f"prior {p:.3f} -> posterior {posterior:.3f} over "
        f"{len(updates)} tempered update(s)",
        "trust = reliability × reality anchor × dice confidence × "
        "(1 − manipulation); zero-trust evidence moves nothing",
    ]
    muted = [u.name for u in updates if u.trust < 0.25 and u.likelihood_ratio != 1.0]
    if muted:
        rationale.append(
            f"muted by low trust: {', '.join(muted)} — loud but unearned "
            "evidence cannot drag belief"
        )

    return BayesianUpdateResult(
        prior=p,
        posterior=posterior,
        total_effective_ratio=total_ratio,
        updates=updates,
        rationale=rationale,
    )
