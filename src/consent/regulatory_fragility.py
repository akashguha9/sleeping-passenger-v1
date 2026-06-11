"""Regulatory Fragility: will these practices attract regulatory scrutiny?

    Regulatory Fragility =
        complaint_severity × vulnerable_user_exposure × legal_ambiguity

A company that makes exit hard is borrowing from future regulatory risk.
Vulnerable-user exposure (students, migrants, non-native speakers facing
foreign-language legal letters) is a multiplier, not an add-on: consumer
protection regulators weight harm to vulnerable users heavily.
"""

from __future__ import annotations

from src.consent.evidence import (
    LayerScore,
    confidence_warnings,
    evidence_confidence,
    evidence_intensity,
    extract_evidence,
    matched_terms,
    risk_label,
    scale_to_ten,
)
from src.utils.math_utils import clamp01
from src.utils.validation_utils import normalized_score

# Evidence categories regulators care about most, with severity weights.
_REGULATORY_EVIDENCE_WEIGHTS: dict[str, float] = {
    "charged_after_cancellation": 1.0,
    "cannot_cancel": 0.9,
    "claims_non_payment": 1.0,
    "hidden_fees": 0.8,
    "language_burden": 0.7,
    "backend_mismatch": 0.6,
    "bot_only_support": 0.5,
}


def score_regulatory_fragility(
    *,
    complaint_severity: float = 0.0,
    vulnerable_user_exposure: float = 0.0,
    legal_ambiguity: float = 0.0,
    complaint_texts: list[str] | None = None,
) -> LayerScore:
    """Regulatory fragility (0–10, higher = more exposed)."""
    texts = list(complaint_texts or [])
    hits = extract_evidence(texts)

    severity = normalized_score(complaint_severity)
    vulnerable = normalized_score(vulnerable_user_exposure)
    ambiguity = normalized_score(legal_ambiguity)

    rationale: list[str] = []
    weighted = [
        weight * evidence_intensity(hits[category], len(texts))
        for category, weight in _REGULATORY_EVIDENCE_WEIGHTS.items()
    ]
    evidence_severity = clamp01(
        sum(weighted) / sum(_REGULATORY_EVIDENCE_WEIGHTS.values()) * 2.0
    )
    if evidence_severity > severity:
        rationale.append(
            f"complaint evidence raised severity to {evidence_severity:.2f}"
        )
        severity = evidence_severity
    language_evidence = evidence_intensity(hits["language_burden"], len(texts))
    if language_evidence > vulnerable:
        rationale.append(
            "foreign-language burden evidence implies vulnerable-user "
            f"exposure {language_evidence:.2f}"
        )
        vulnerable = language_evidence

    # Multiplicative with floors: severity drives, the multipliers shape.
    fragility01 = clamp01(
        severity * (0.4 + 0.6 * vulnerable) * (0.5 + 0.5 * ambiguity) * 1.6
    )
    score = scale_to_ten(fragility01)

    rationale.insert(
        0,
        f"severity {severity:.2f} × vulnerable exposure {vulnerable:.2f} × "
        f"legal ambiguity {ambiguity:.2f}",
    )
    if score >= 6.0:
        rationale.append(
            "high complaint density around cancellation/claims/fees with "
            "vulnerable users — the pattern regulators move on"
        )
    rationale.append(
        "detects regulatory risk patterns, not legal guilt or intent"
    )

    return LayerScore(
        name="regulatory_fragility",
        score=score,
        label=risk_label(score),
        higher_is_worse=True,
        confidence=clamp01(
            0.4 * (1.0 if complaint_severity or legal_ambiguity else 0.0)
            + 0.6 * evidence_confidence(len(texts))
        ),
        evidence_terms=matched_terms(hits, list(_REGULATORY_EVIDENCE_WEIGHTS)),
        rationale=rationale,
        missing_data_warnings=confidence_warnings(len(texts)),
        raw_components={
            "complaint_severity": severity,
            "vulnerable_user_exposure": vulnerable,
            "legal_ambiguity": ambiguity,
        },
    )
