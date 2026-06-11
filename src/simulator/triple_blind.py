"""Triple-blind review: hide identity, hide the human thesis, replay reality.

Stage 1 (identity-blind): score the candidate from anonymized metrics only.
Stage 2 (thesis-blind): the model writes its own thesis BEFORE seeing the
user thesis, then agreement is measured.
Stage 3 (reality-blind): outcome review is deferred until reality resolves.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from src.utils.math_utils import clamp01
from src.utils.validation_utils import normalized_score

REALITY_REVIEW_PENDING = "pending"
REALITY_REVIEW_CONFIRMED = "confirmed"
REALITY_REVIEW_REFUTED = "refuted"

_AGREEMENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "valuation": ("valuation", "cheap", "expensive", "multiple", "p/e", "pe"),
    "growth": ("growth", "revenue", "expand", "backlog", "demand"),
    "margin": ("margin", "profitability", "cost", "pricing"),
    "balance_sheet": ("debt", "cash", "balance sheet", "leverage", "fcf"),
    "catalyst": ("catalyst", "earnings", "contract", "policy", "approval"),
    "risk": ("risk", "crash", "downside", "invalidation", "competition"),
}


@dataclass(slots=True)
class TripleBlindReview:
    """Serializable three-stage bias-protection record."""

    identity_blind_score: float
    model_thesis: str
    model_thesis_written_before_user_thesis: bool
    user_thesis_seen: bool
    human_model_agreement: float
    risks_model_found: list[str] = field(default_factory=list)
    optionality_human_found: list[str] = field(default_factory=list)
    reality_review_status: str = REALITY_REVIEW_PENDING
    reason_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def identity_blind_score(metrics: dict[str, float]) -> float:
    """Score a candidate from anonymized metrics only (no name/ticker/brand).

    Inputs are normalized fundamentals: growth_quality, margin_trend,
    balance_sheet_strength, valuation_discount, evidence_strength.
    """
    growth = normalized_score(metrics.get("growth_quality", 0.0))
    margin = normalized_score(metrics.get("margin_trend", 0.0))
    balance = normalized_score(metrics.get("balance_sheet_strength", 0.0))
    discount = normalized_score(metrics.get("valuation_discount", 0.0))
    evidence = normalized_score(metrics.get("evidence_strength", 0.0))
    return clamp01(
        0.25 * growth + 0.20 * margin + 0.20 * balance + 0.15 * discount + 0.20 * evidence
    )


def write_model_thesis(metrics: dict[str, float]) -> tuple[str, list[str]]:
    """Deterministic model thesis from blinded metrics — written before the
    user thesis is revealed. Returns (thesis_text, risks_found)."""
    score = identity_blind_score(metrics)
    growth = normalized_score(metrics.get("growth_quality", 0.0))
    margin = normalized_score(metrics.get("margin_trend", 0.0))
    balance = normalized_score(metrics.get("balance_sheet_strength", 0.0))
    discount = normalized_score(metrics.get("valuation_discount", 0.0))
    evidence = normalized_score(metrics.get("evidence_strength", 0.0))

    drivers: list[str] = []
    risks: list[str] = []
    if growth >= 0.6:
        drivers.append("durable revenue growth")
    elif growth < 0.3:
        risks.append("weak growth trajectory")
    if margin >= 0.6:
        drivers.append("improving margins")
    elif margin < 0.3:
        risks.append("margin compression risk")
    if balance >= 0.6:
        drivers.append("a resilient balance sheet")
    elif balance < 0.3:
        risks.append("balance sheet fragility")
    if discount >= 0.6:
        drivers.append("a valuation discount")
    elif discount < 0.3:
        risks.append("valuation heat")
    if evidence < 0.4:
        risks.append("thin primary evidence")

    driver_text = ", ".join(drivers) if drivers else "no dominant fundamental driver"
    risk_text = "; ".join(risks) if risks else "no outsized blinded risk detected"
    thesis = (
        f"Identity-blind thesis (score {score:.2f}): the anonymized company "
        f"shows {driver_text}. Key blinded risks: {risk_text}. "
        "ADVISORY_ONLY — written before the human thesis was revealed."
    )
    return thesis, risks


def measure_agreement(model_thesis: str, user_thesis: str) -> float:
    """Topic-overlap agreement in [0, 1] across thesis dimensions."""
    model_lower = model_thesis.lower()
    user_lower = user_thesis.lower()
    model_topics = {
        topic
        for topic, words in _AGREEMENT_KEYWORDS.items()
        if any(w in model_lower for w in words)
    }
    user_topics = {
        topic
        for topic, words in _AGREEMENT_KEYWORDS.items()
        if any(w in user_lower for w in words)
    }
    if not model_topics and not user_topics:
        return 0.0
    union = model_topics | user_topics
    return clamp01(len(model_topics & user_topics) / len(union))


def build_triple_blind_review(
    *,
    blinded_metrics: dict[str, float],
    user_thesis: str | None = None,
    optionality_human_found: list[str] | None = None,
) -> TripleBlindReview:
    """Run stages 1 and 2; stage 3 stays pending until reality resolves."""
    score = identity_blind_score(blinded_metrics)
    model_thesis, risks_found = write_model_thesis(blinded_metrics)
    user_seen = bool(user_thesis and user_thesis.strip())
    agreement = (
        measure_agreement(model_thesis, user_thesis) if user_seen else 0.0
    )

    reasons: list[str] = ["MODEL_THESIS_FIRST"]
    if user_seen:
        if agreement >= 0.6:
            reasons.append("HIGH_HUMAN_MODEL_AGREEMENT")
        elif agreement < 0.3:
            reasons.append("HUMAN_MODEL_DISAGREEMENT")
    else:
        reasons.append("USER_THESIS_NOT_PROVIDED")
    if score < 0.35:
        reasons.append("IDENTITY_BLIND_WEAKNESS")

    return TripleBlindReview(
        identity_blind_score=score,
        model_thesis=model_thesis,
        model_thesis_written_before_user_thesis=True,
        user_thesis_seen=user_seen,
        human_model_agreement=agreement,
        risks_model_found=risks_found,
        optionality_human_found=list(optionality_human_found or []),
        reality_review_status=REALITY_REVIEW_PENDING,
        reason_codes=reasons,
    )
