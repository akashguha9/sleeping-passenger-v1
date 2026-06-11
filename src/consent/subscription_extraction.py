"""Subscription Extraction Risk: is recurring revenue trapped or earned?

    Subscription Extraction Risk =
        recurring_billing_dependency × exit_friction
        × billing_ambiguity × penalty_escalation

Multiplicative on purpose: extraction needs all four — recurring billing
to extract through, friction to prevent exit, ambiguity to hide behind,
and escalation to enforce. A company missing any leg is structurally less
able to extract.
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

_EXIT_EVIDENCE = ("cannot_cancel", "charged_after_cancellation", "lock_in")
_AMBIGUITY_EVIDENCE = ("backend_mismatch", "hidden_fees")
_ESCALATION_EVIDENCE = ("hidden_fees", "enforcement_speed")


def score_subscription_extraction(
    *,
    recurring_billing_dependency: float = 0.0,
    exit_friction: float = 0.0,
    billing_ambiguity: float = 0.0,
    penalty_escalation: float = 0.0,
    complaint_texts: list[str] | None = None,
) -> LayerScore:
    """Subscription extraction risk (0–10, higher = worse)."""
    texts = list(complaint_texts or [])
    hits = extract_evidence(texts)

    recurring = normalized_score(recurring_billing_dependency)
    exit_f = normalized_score(exit_friction)
    ambiguity = normalized_score(billing_ambiguity)
    escalation = normalized_score(penalty_escalation)

    rationale: list[str] = []

    exit_evidence = max(
        evidence_intensity(hits[c], len(texts)) for c in _EXIT_EVIDENCE
    )
    if exit_evidence > exit_f:
        rationale.append(f"evidence raised exit_friction to {exit_evidence:.2f}")
        exit_f = exit_evidence

    ambiguity_evidence = max(
        evidence_intensity(hits[c], len(texts)) for c in _AMBIGUITY_EVIDENCE
    )
    if ambiguity_evidence > ambiguity:
        rationale.append(
            f"evidence raised billing_ambiguity to {ambiguity_evidence:.2f}"
        )
        ambiguity = ambiguity_evidence

    escalation_evidence = max(
        evidence_intensity(hits[c], len(texts)) for c in _ESCALATION_EVIDENCE
    )
    if escalation_evidence > escalation:
        rationale.append(
            f"evidence raised penalty_escalation to {escalation_evidence:.2f}"
        )
        escalation = escalation_evidence

    # Recurring billing is implied when extraction evidence exists at all.
    if recurring == 0.0 and (exit_f > 0 or ambiguity > 0):
        recurring = 0.5
        rationale.append(
            "recurring_billing_dependency defaulted to 0.50 — exit/billing "
            "evidence implies a recurring relationship"
        )

    # Geometric-style composition with a soft floor so one strong leg plus
    # moderate legs still registers (pure product would vanish too easily).
    product = recurring * exit_f * max(ambiguity, 0.25) * max(escalation, 0.25)
    risk01 = clamp01(product ** 0.5)
    score = scale_to_ten(risk01)

    rationale.insert(
        0,
        f"recurring {recurring:.2f} × exit friction {exit_f:.2f} × "
        f"ambiguity {ambiguity:.2f} × escalation {escalation:.2f}",
    )

    return LayerScore(
        name="subscription_extraction_risk",
        score=score,
        label=risk_label(score),
        higher_is_worse=True,
        confidence=clamp01(
            0.4 * (1.0 if exit_friction or recurring_billing_dependency else 0.0)
            + 0.6 * evidence_confidence(len(texts))
        ),
        evidence_terms=matched_terms(
            hits, list({*_EXIT_EVIDENCE, *_AMBIGUITY_EVIDENCE, *_ESCALATION_EVIDENCE})
        ),
        rationale=rationale,
        missing_data_warnings=confidence_warnings(len(texts)),
        raw_components={
            "recurring_billing_dependency": recurring,
            "exit_friction": exit_f,
            "billing_ambiguity": ambiguity,
            "penalty_escalation": escalation,
        },
    )
