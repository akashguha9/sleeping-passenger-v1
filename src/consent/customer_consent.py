"""Consent Quality Score: was the revenue cleanly consented to?

    Consent Quality =
        clarity_of_terms + billing_predictability + cancellation_clarity
        + refund_accessibility + dispute_fairness + human_escalation
        - cancellation_friction - hidden_fee_risk
        - billing_after_cancellation_risk - lock_in_risk - language_burden

Structured components are caller-supplied fractions in [0, 1]; complaint
evidence (if supplied) tightens the negative components. Score is 0–10,
10 = clean, voluntary, reversible consent.
"""

from __future__ import annotations

from src.consent.evidence import (
    LayerScore,
    confidence_warnings,
    evidence_confidence,
    evidence_intensity,
    extract_evidence,
    matched_terms,
    quality_label,
    scale_to_ten,
)
from src.utils.math_utils import clamp01
from src.utils.validation_utils import normalized_score

POSITIVE_COMPONENTS: tuple[str, ...] = (
    "clarity_of_terms",
    "billing_predictability",
    "cancellation_clarity",
    "refund_accessibility",
    "dispute_fairness",
    "human_escalation",
)
NEGATIVE_COMPONENTS: tuple[str, ...] = (
    "cancellation_friction",
    "hidden_fee_risk",
    "billing_after_cancellation_risk",
    "lock_in_risk",
    "language_burden",
)

# Evidence category -> negative component it reinforces.
_EVIDENCE_TO_NEGATIVE: dict[str, str] = {
    "cannot_cancel": "cancellation_friction",
    "email_only_relief": "cancellation_friction",
    "hidden_fees": "hidden_fee_risk",
    "charged_after_cancellation": "billing_after_cancellation_risk",
    "backend_mismatch": "billing_after_cancellation_risk",
    "lock_in": "lock_in_risk",
    "language_burden": "language_burden",
}


def score_consent_quality(
    *,
    clarity_of_terms: float = 0.0,
    billing_predictability: float = 0.0,
    cancellation_clarity: float = 0.0,
    refund_accessibility: float = 0.0,
    dispute_fairness: float = 0.0,
    human_escalation: float = 0.0,
    cancellation_friction: float = 0.0,
    hidden_fee_risk: float = 0.0,
    billing_after_cancellation_risk: float = 0.0,
    lock_in_risk: float = 0.0,
    language_burden: float = 0.0,
    complaint_texts: list[str] | None = None,
) -> LayerScore:
    """Score consent quality (0–10, higher = cleaner consent)."""
    texts = list(complaint_texts or [])
    hits = extract_evidence(texts)

    positives = {
        "clarity_of_terms": normalized_score(clarity_of_terms),
        "billing_predictability": normalized_score(billing_predictability),
        "cancellation_clarity": normalized_score(cancellation_clarity),
        "refund_accessibility": normalized_score(refund_accessibility),
        "dispute_fairness": normalized_score(dispute_fairness),
        "human_escalation": normalized_score(human_escalation),
    }
    negatives = {
        "cancellation_friction": normalized_score(cancellation_friction),
        "hidden_fee_risk": normalized_score(hidden_fee_risk),
        "billing_after_cancellation_risk": normalized_score(
            billing_after_cancellation_risk
        ),
        "lock_in_risk": normalized_score(lock_in_risk),
        "language_burden": normalized_score(language_burden),
    }

    # Complaint evidence can only worsen negatives, never improve positives:
    # praise is cheap, complaints are costly to fake at volume.
    rationale: list[str] = []
    for category, component in _EVIDENCE_TO_NEGATIVE.items():
        intensity = evidence_intensity(hits[category], len(texts))
        if intensity > negatives[component]:
            rationale.append(
                f"evidence raised {component} to {intensity:.2f} "
                f"({hits[category].count} match(es) for {category})"
            )
            negatives[component] = intensity

    positive_mean = sum(positives.values()) / len(positives)
    negative_mean = sum(negatives.values()) / len(negatives)
    quality01 = clamp01(positive_mean - negative_mean + 0.0)
    # Map the [-1, 1] spread onto [0, 1] so an all-zero payload scores the
    # midpoint of ignorance rather than fake cleanliness... no: an unknown
    # company must NOT look clean. Positive evidence must be earned, so the
    # raw clamped difference stands and zero inputs score zero.
    score = scale_to_ten(quality01)

    if positive_mean > 0:
        rationale.insert(
            0,
            f"positive consent components average {positive_mean:.2f}; "
            f"negative components average {negative_mean:.2f}",
        )
    else:
        rationale.insert(0, "no positive consent evidence supplied — unproven consent scores low")

    warnings = confidence_warnings(len(texts))
    if positive_mean == 0.0:
        warnings.append(
            "no structured positive components supplied — score reflects "
            "absence of proof, not proof of harm"
        )

    structured_supplied = sum(
        1 for v in (*positives.values(), *negatives.values()) if v > 0
    )
    confidence = clamp01(
        0.5 * evidence_confidence(len(texts))
        + 0.5 * min(structured_supplied / 6.0, 1.0)
    )

    return LayerScore(
        name="consent_quality",
        score=score,
        label=quality_label(score),
        higher_is_worse=False,
        confidence=confidence,
        evidence_terms=matched_terms(hits, list(_EVIDENCE_TO_NEGATIVE)),
        rationale=rationale,
        missing_data_warnings=warnings,
        raw_components={**positives, **negatives},
    )
