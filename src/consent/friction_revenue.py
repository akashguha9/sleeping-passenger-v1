"""Friction-revenue detection: delay revenue and the friction tax.

    Delay Revenue Risk =
        processing_delay × charge_rate_during_delay × complaint_frequency

    Friction Tax = time + translation + proof + call-queue + email
        + delay + payment + stress burdens

Delay is economic: when billing continues, slow processing has monetary
value to the company. Friction is the hidden, non-monetary price the
customer pays.
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

DELAY_COST_LEVELS: tuple[str, ...] = ("low", "medium", "high")

FRICTION_BURDENS: tuple[str, ...] = (
    "time_burden",
    "translation_burden",
    "proof_burden",
    "call_queue_burden",
    "email_burden",
    "delay_burden",
    "payment_burden",
    "stress_burden",
)

# Evidence category -> friction burden it reinforces.
_EVIDENCE_TO_BURDEN: dict[str, str] = {
    "language_burden": "translation_burden",
    "bot_only_support": "call_queue_burden",
    "email_only_relief": "email_burden",
    "processing_delay": "delay_burden",
    "hidden_fees": "payment_burden",
}


def score_delay_revenue(
    *,
    processing_delay_days: float = 0.0,
    charge_rate_per_week: float = 0.0,
    complaint_frequency: float = 0.0,
    complaint_texts: list[str] | None = None,
) -> LayerScore:
    """Delay revenue risk (0–10, higher = worse).

    Quantitative when delay/charge/frequency are supplied; falls back to
    qualitative complaint-evidence intensity when they are not.
    """
    texts = list(complaint_texts or [])
    hits = extract_evidence(texts)

    delay_days = max(float(processing_delay_days), 0.0)
    rate = max(float(charge_rate_per_week), 0.0)
    frequency = normalized_score(complaint_frequency)

    evidence01 = evidence_intensity(hits["processing_delay"], len(texts))
    quantitative = delay_days > 0 and rate > 0

    if quantitative:
        delay01 = clamp01(delay_days / 14.0)
        freq = max(frequency, evidence01, 0.25 if evidence01 == 0 else evidence01)
        risk01 = clamp01(delay01 * freq + 0.3 * delay01)
        per_user_cost = (delay_days / 7.0) * rate
    else:
        risk01 = evidence01
        per_user_cost = 0.0

    score = scale_to_ten(risk01)
    if score >= 6.0:
        cost_level = "high"
    elif score >= 3.0:
        cost_level = "medium"
    else:
        cost_level = "low"

    rationale = []
    if quantitative:
        rationale.append(
            f"delay {delay_days:.1f}d × €{rate:.2f}/week ≈ €{per_user_cost:.2f} "
            "charged per user while a relief request is pending"
        )
    elif evidence01 > 0:
        rationale.append(
            f"qualitative mode: {hits['processing_delay'].count} delay-pattern "
            f"match(es) across {len(texts)} texts"
        )
    else:
        rationale.append("no delay evidence detected")

    warnings = confidence_warnings(len(texts))
    if not quantitative:
        warnings.append(
            "no delay duration / charge rate supplied — qualitative "
            "evidence mode only"
        )

    return LayerScore(
        name="delay_revenue_risk",
        score=score,
        label=risk_label(score),
        higher_is_worse=True,
        confidence=clamp01(
            (0.6 if quantitative else 0.0) + 0.4 * evidence_confidence(len(texts))
        ),
        evidence_terms=matched_terms(hits, ["processing_delay"]),
        rationale=rationale,
        missing_data_warnings=warnings,
        raw_components={
            "processing_delay_days": delay_days,
            "charge_rate_per_week": rate,
            "complaint_frequency": frequency,
            "evidence_intensity": evidence01,
            "estimated_delay_cost_per_user_eur": per_user_cost,
            "estimated_delay_cost_level": float(
                DELAY_COST_LEVELS.index(cost_level)
            ),
        },
    )


def score_friction_tax(
    *,
    time_burden: float = 0.0,
    translation_burden: float = 0.0,
    proof_burden: float = 0.0,
    call_queue_burden: float = 0.0,
    email_burden: float = 0.0,
    delay_burden: float = 0.0,
    payment_burden: float = 0.0,
    stress_burden: float = 0.0,
    complaint_texts: list[str] | None = None,
) -> LayerScore:
    """Friction Tax Index (0–10, higher = heavier hidden customer burden)."""
    texts = list(complaint_texts or [])
    hits = extract_evidence(texts)

    burdens = {
        "time_burden": normalized_score(time_burden),
        "translation_burden": normalized_score(translation_burden),
        "proof_burden": normalized_score(proof_burden),
        "call_queue_burden": normalized_score(call_queue_burden),
        "email_burden": normalized_score(email_burden),
        "delay_burden": normalized_score(delay_burden),
        "payment_burden": normalized_score(payment_burden),
        "stress_burden": normalized_score(stress_burden),
    }

    rationale: list[str] = []
    for category, burden in _EVIDENCE_TO_BURDEN.items():
        intensity = evidence_intensity(hits[category], len(texts))
        if intensity > burdens[burden]:
            burdens[burden] = intensity
            rationale.append(
                f"evidence raised {burden} to {intensity:.2f} ({category})"
            )

    tax01 = clamp01(sum(burdens.values()) / len(burdens))
    score = scale_to_ten(tax01)
    active = [k for k, v in burdens.items() if v > 0]
    rationale.insert(
        0,
        f"{len(active)}/{len(burdens)} burden channels active; mean burden "
        f"{tax01:.2f}",
    )

    return LayerScore(
        name="friction_tax_index",
        score=score,
        label=risk_label(score),
        higher_is_worse=True,
        confidence=clamp01(
            0.5 * min(len(active) / 4.0, 1.0)
            + 0.5 * evidence_confidence(len(texts))
        ),
        evidence_terms=matched_terms(hits, list(_EVIDENCE_TO_BURDEN)),
        rationale=rationale,
        missing_data_warnings=confidence_warnings(len(texts)),
        raw_components=burdens,
    )
