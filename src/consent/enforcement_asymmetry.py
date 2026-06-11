"""Enforcement-Service Asymmetry: precise when collecting, vague when serving.

    Asymmetry =
        (collection_speed + penalty_strength + debit_precision)
        - (resolution_speed + refund_speed + human_accountability)

A system that can debit precisely owes the customer equally precise
explanation and correction. High asymmetry is a fairness, churn, and
regulatory-risk indicator.
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


def score_enforcement_asymmetry(
    *,
    collection_speed: float = 0.0,
    penalty_strength: float = 0.0,
    debit_precision: float = 0.0,
    resolution_speed: float = 0.0,
    refund_speed: float = 0.0,
    human_accountability: float = 0.0,
    complaint_texts: list[str] | None = None,
) -> LayerScore:
    """Enforcement-service asymmetry risk (0–10, higher = worse)."""
    texts = list(complaint_texts or [])
    hits = extract_evidence(texts)

    enforcement = {
        "collection_speed": normalized_score(collection_speed),
        "penalty_strength": normalized_score(penalty_strength),
        "debit_precision": normalized_score(debit_precision),
    }
    service = {
        "resolution_speed": normalized_score(resolution_speed),
        "refund_speed": normalized_score(refund_speed),
        "human_accountability": normalized_score(human_accountability),
    }

    rationale: list[str] = []
    enforcement_evidence = max(
        evidence_intensity(hits["enforcement_speed"], len(texts)),
        evidence_intensity(hits["hidden_fees"], len(texts)),
    )
    if enforcement_evidence > enforcement["penalty_strength"]:
        enforcement["penalty_strength"] = enforcement_evidence
        rationale.append(
            f"evidence raised penalty_strength to {enforcement_evidence:.2f}"
        )
    service_evidence = max(
        evidence_intensity(hits["bot_only_support"], len(texts)),
        evidence_intensity(hits["processing_delay"], len(texts)),
    )
    if service_evidence > 0:
        reduced = clamp01(
            service["human_accountability"] * (1.0 - service_evidence)
        )
        rationale.append(
            f"bot/delay evidence cut human_accountability to {reduced:.2f}"
        )
        service["human_accountability"] = reduced

    enforcement_mean = sum(enforcement.values()) / len(enforcement)
    service_mean = sum(service.values()) / len(service)
    asymmetry01 = clamp01(enforcement_mean - service_mean)
    score = scale_to_ten(asymmetry01)

    rationale.insert(
        0,
        f"enforcement side {enforcement_mean:.2f} vs service side "
        f"{service_mean:.2f} (asymmetry {asymmetry01:+.2f})",
    )
    if score >= 6.0:
        rationale.append(
            "the system tracks money better than outcomes — collection is "
            "automated while correction is manual and slow"
        )

    return LayerScore(
        name="enforcement_service_asymmetry",
        score=score,
        label=risk_label(score),
        higher_is_worse=True,
        confidence=clamp01(
            0.5 * (1.0 if collection_speed or resolution_speed else 0.0)
            + 0.5 * evidence_confidence(len(texts))
        ),
        evidence_terms=matched_terms(
            hits,
            ["enforcement_speed", "hidden_fees", "bot_only_support", "processing_delay"],
        ),
        rationale=rationale,
        missing_data_warnings=confidence_warnings(len(texts)),
        raw_components={**enforcement, **service},
    )
