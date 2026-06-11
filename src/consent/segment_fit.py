"""Segment Fit Score: does the product design fit the actual customer?

    Segment Fit =
        pricing_fit + flexibility_fit + language_fit
        + digital_self_service_fit + cancellation_pause_fit
        + payment_predictability
        - contract_rigidity - processing_delay
        - third_party_dependency - support_friction

Vulnerable segments (international students, migrants, temporary
residents, elderly, non-native speakers) raise the weight of language and
flexibility misfit — the university-town gym case.
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

VULNERABLE_SEGMENTS: tuple[str, ...] = (
    "international_students",
    "students",
    "migrants",
    "temporary_residents",
    "low_income",
    "elderly",
    "non_native_speakers",
)


def score_segment_fit(
    *,
    segment: str = "general",
    pricing_fit: float = 0.0,
    flexibility_fit: float = 0.0,
    language_fit: float = 0.0,
    digital_self_service_fit: float = 0.0,
    cancellation_pause_fit: float = 0.0,
    payment_predictability: float = 0.0,
    contract_rigidity: float = 0.0,
    processing_delay: float = 0.0,
    third_party_dependency: float = 0.0,
    support_friction: float = 0.0,
    complaint_texts: list[str] | None = None,
) -> LayerScore:
    """Segment fit (0–10, higher = better fit). Low = service-market mismatch."""
    texts = list(complaint_texts or [])
    hits = extract_evidence(texts)
    vulnerable = str(segment).strip().lower() in VULNERABLE_SEGMENTS

    positives = {
        "pricing_fit": normalized_score(pricing_fit),
        "flexibility_fit": normalized_score(flexibility_fit),
        "language_fit": normalized_score(language_fit),
        "digital_self_service_fit": normalized_score(digital_self_service_fit),
        "cancellation_pause_fit": normalized_score(cancellation_pause_fit),
        "payment_predictability": normalized_score(payment_predictability),
    }
    negatives = {
        "contract_rigidity": normalized_score(contract_rigidity),
        "processing_delay": normalized_score(processing_delay),
        "third_party_dependency": normalized_score(third_party_dependency),
        "support_friction": normalized_score(support_friction),
    }

    rationale: list[str] = []
    language_evidence = evidence_intensity(hits["language_burden"], len(texts))
    if language_evidence > 0:
        reduced = clamp01(positives["language_fit"] * (1.0 - language_evidence))
        rationale.append(
            f"language-burden evidence cut language_fit to {reduced:.2f}"
        )
        positives["language_fit"] = reduced
    delay_evidence = evidence_intensity(hits["processing_delay"], len(texts))
    if delay_evidence > negatives["processing_delay"]:
        negatives["processing_delay"] = delay_evidence
        rationale.append(
            f"evidence raised processing_delay to {delay_evidence:.2f}"
        )

    positive_mean = sum(positives.values()) / len(positives)
    negative_mean = sum(negatives.values()) / len(negatives)

    # Vulnerable segments amplify the cost of misfit: the same rigidity
    # hurts an international student more than a settled local.
    misfit_multiplier = 1.3 if vulnerable else 1.0
    fit01 = clamp01(positive_mean - negative_mean * misfit_multiplier)
    score = scale_to_ten(fit01)

    rationale.insert(
        0,
        f"segment '{segment}' ({'vulnerable' if vulnerable else 'general'}): "
        f"fit components {positive_mean:.2f} vs misfit {negative_mean:.2f}"
        f"×{misfit_multiplier}",
    )
    if vulnerable and (
        positives["language_fit"] < 0.4 or positives["flexibility_fit"] < 0.4
    ):
        rationale.append(
            "vulnerable segment with weak language/flexibility fit — "
            "structural product-market mismatch"
        )

    return LayerScore(
        name="segment_fit",
        score=score,
        label=quality_label(score),
        higher_is_worse=False,
        confidence=clamp01(
            0.5 * min(sum(1 for v in positives.values() if v > 0) / 4.0, 1.0)
            + 0.5 * evidence_confidence(len(texts))
        ),
        evidence_terms=matched_terms(
            hits, ["language_burden", "processing_delay"]
        ),
        rationale=rationale,
        missing_data_warnings=confidence_warnings(len(texts)),
        raw_components={**positives, **negatives, "vulnerable_segment": float(vulnerable)},
    )
