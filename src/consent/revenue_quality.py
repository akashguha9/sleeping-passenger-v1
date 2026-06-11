"""Adjusted Revenue Quality: stress-test reported revenue against consent.

    Adjusted Revenue Quality =
        reported_revenue_quality
        × consent_multiplier × service_fulfilment
        × retention_authenticity × regulatory_safety
        - friction_penalty - complaint_severity_penalty - narrative_gap_penalty

The final question this layer asks: does the company earn money because
customers love the product, or because the system makes exit painful?

``evaluate_consent_profile`` is the one-payload orchestrator running every
module in this package, and ``to_simulator_risk_factors`` bridges the
result into the crash-case simulator so business-model fragility becomes
a first-class crash vector. ADVISORY_ONLY throughout.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from src.consent import CONSENT_ADVISORY_NOTE, CONSENT_DOCTRINE
from src.consent.claims_non_payment import score_claims_non_payment
from src.consent.customer_consent import score_consent_quality
from src.consent.digital_asymmetry import (
    score_digital_asymmetry,
    score_pause_friction,
)
from src.consent.enforcement_asymmetry import score_enforcement_asymmetry
from src.consent.evidence import LayerScore, extract_evidence
from src.consent.friction_revenue import score_delay_revenue, score_friction_tax
from src.consent.narrative_gap import score_narrative_gap
from src.consent.premium_promise import score_premium_promise_failure
from src.consent.regulatory_fragility import score_regulatory_fragility
from src.consent.segment_fit import score_segment_fit
from src.consent.subscription_extraction import score_subscription_extraction
from src.utils.math_utils import clamp01, clip
from src.utils.validation_utils import coerce_float, normalized_score

REVENUE_QUALITY_LABELS: tuple[str, ...] = (
    "clean",
    "mostly_clean",
    "mixed",
    "fragile",
    "extractive_risk",
    # Honest zero-information outcome: the engine refuses to classify a
    # company it knows nothing about. Ignorance is not evidence of harm —
    # and it is definitely not evidence of cleanliness.
    "insufficient_data",
)


def revenue_quality_label(score: float) -> str:
    if score >= 8.0:
        return "clean"
    if score >= 6.5:
        return "mostly_clean"
    if score >= 4.5:
        return "mixed"
    if score >= 2.5:
        return "fragile"
    return "extractive_risk"


@dataclass(slots=True)
class AdjustedRevenueQuality:
    """Composite revenue-quality verdict (0–10, higher = cleaner revenue)."""

    score: float
    label: str
    confidence: float
    base_revenue_quality: float
    consent_multiplier: float
    service_fulfilment_multiplier: float
    retention_authenticity_multiplier: float
    regulatory_safety_multiplier: float
    friction_penalty: float
    complaint_severity_penalty: float
    narrative_gap_penalty: float
    rationale: list[str] = field(default_factory=list)
    missing_data_warnings: list[str] = field(default_factory=list)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def score_adjusted_revenue_quality(
    *,
    consent_quality: LayerScore,
    subscription_extraction: LayerScore,
    regulatory_fragility: LayerScore,
    friction_tax: LayerScore,
    narrative_gap: LayerScore,
    claims_non_payment: LayerScore,
    service_fulfilment: float = 0.5,
    reported_revenue_quality: float | None = None,
    any_information_supplied: bool = True,
) -> AdjustedRevenueQuality:
    """Stress-test revenue quality through the consent layers.

    ``reported_revenue_quality`` is 0–10 (e.g. from fundamental analysis);
    when unavailable the neutral midpoint 5.0 is used with a warning, so
    the output is a pure consent-side classification.
    """
    warnings: list[str] = []
    if reported_revenue_quality is None:
        base = 5.0
        warnings.append(
            "no reported revenue quality supplied — using neutral midpoint "
            "5.0; output is a qualitative consent-side classification"
        )
    else:
        base = clip(float(reported_revenue_quality), 0.0, 10.0)

    consent_mult = clamp01(consent_quality.score / 10.0)
    fulfilment_mult = normalized_score(service_fulfilment)
    retention_mult = clamp01(1.0 - subscription_extraction.score / 10.0)
    regulatory_mult = clamp01(1.0 - regulatory_fragility.score / 10.0)

    friction_penalty = friction_tax.score / 10.0 * 1.5
    severity_penalty = claims_non_payment.score / 10.0 * 1.5
    gap_penalty = narrative_gap.score / 10.0 * 1.0

    # Multiplicative core with soft floors (0.3) so a single unknown layer
    # cannot zero the composite, then explicit penalties.
    core = base
    for multiplier in (consent_mult, fulfilment_mult, retention_mult, regulatory_mult):
        core *= 0.3 + 0.7 * multiplier
    score = clip(core - friction_penalty - severity_penalty - gap_penalty, 0.0, 10.0)
    label = revenue_quality_label(score)
    if not any_information_supplied:
        label = "insufficient_data"
        warnings.append(
            "no complaint evidence and no structured inputs supplied — "
            "refusing to classify; ignorance is not evidence of harm or "
            "of cleanliness"
        )

    rationale = [
        f"base {base:.1f} × consent {consent_mult:.2f} × fulfilment "
        f"{fulfilment_mult:.2f} × retention authenticity {retention_mult:.2f} "
        f"× regulatory safety {regulatory_mult:.2f} (soft-floored) = {core:.2f}",
        f"penalties: friction {friction_penalty:.2f}, claims severity "
        f"{severity_penalty:.2f}, narrative gap {gap_penalty:.2f}",
        f"verdict: {label} — "
        + (
            "revenue earned through satisfied customers"
            if label in ("clean", "mostly_clean")
            else "revenue may be inflated by friction, lock-in, or weak fulfilment"
        ),
    ]
    warnings.extend(consent_quality.missing_data_warnings)

    confidence = clamp01(
        0.4 * consent_quality.confidence
        + 0.3 * subscription_extraction.confidence
        + 0.3 * regulatory_fragility.confidence
    )

    return AdjustedRevenueQuality(
        score=score,
        label=label,
        confidence=confidence,
        base_revenue_quality=base,
        consent_multiplier=consent_mult,
        service_fulfilment_multiplier=fulfilment_mult,
        retention_authenticity_multiplier=retention_mult,
        regulatory_safety_multiplier=regulatory_mult,
        friction_penalty=friction_penalty,
        complaint_severity_penalty=severity_penalty,
        narrative_gap_penalty=gap_penalty,
        rationale=rationale,
        missing_data_warnings=warnings,
    )


def _section(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return dict(value) if isinstance(value, dict) else {}


def evaluate_consent_profile(payload: dict[str, Any]) -> dict[str, Any]:
    """Run the full Customer Consent & Regulatory Fragility Engine.

    Payload sections (all optional; conservative defaults):
        company, segment, complaint_texts, official_promises,
        consent, capabilities (collection/relief), pause, delay,
        subscription, claims, premium, segment_fit, enforcement,
        friction, fragility, service_fulfilment, reported_revenue_quality

    Returns a JSON-friendly profile with every layer's full score object
    plus the adjusted revenue quality verdict. ADVISORY_ONLY.
    """
    texts = [str(t) for t in payload.get("complaint_texts", []) or []]

    consent = score_consent_quality(
        **{
            k: coerce_float(v)
            for k, v in _section(payload, "consent").items()
            if k in score_consent_quality.__kwdefaults__ and k != "complaint_texts"
        },
        complaint_texts=texts,
    )
    capabilities = _section(payload, "capabilities")
    asymmetry = score_digital_asymmetry(
        collection_capabilities=capabilities.get("collection"),
        relief_capabilities=capabilities.get("relief"),
        complaint_texts=texts,
    )
    pause_section = _section(payload, "pause")
    pause = score_pause_friction(
        manual_pause_burden=coerce_float(pause_section.get("manual_pause_burden")),
        language_burden=coerce_float(pause_section.get("language_burden")),
        processing_delay_days=coerce_float(pause_section.get("processing_delay_days")),
        billing_continues_during_delay=bool(
            pause_section.get("billing_continues_during_delay", False)
        ),
        charge_per_week=coerce_float(pause_section.get("charge_per_week")),
        complaint_texts=texts,
    )
    delay_section = _section(payload, "delay")
    delay = score_delay_revenue(
        processing_delay_days=coerce_float(delay_section.get("processing_delay_days")),
        charge_rate_per_week=coerce_float(delay_section.get("charge_rate_per_week")),
        complaint_frequency=coerce_float(delay_section.get("complaint_frequency")),
        complaint_texts=texts,
    )
    subscription_section = _section(payload, "subscription")
    subscription = score_subscription_extraction(
        recurring_billing_dependency=coerce_float(
            subscription_section.get("recurring_billing_dependency")
        ),
        exit_friction=coerce_float(subscription_section.get("exit_friction")),
        billing_ambiguity=coerce_float(subscription_section.get("billing_ambiguity")),
        penalty_escalation=coerce_float(subscription_section.get("penalty_escalation")),
        complaint_texts=texts,
    )
    claims_section = _section(payload, "claims")
    claims = score_claims_non_payment(
        claims_submitted=(
            int(claims_section["claims_submitted"])
            if claims_section.get("claims_submitted") is not None
            else None
        ),
        claims_paid=(
            int(claims_section["claims_paid"])
            if claims_section.get("claims_paid") is not None
            else None
        ),
        formal_decisions_issued=(
            int(claims_section["formal_decisions_issued"])
            if claims_section.get("formal_decisions_issued") is not None
            else None
        ),
        complaint_texts=texts,
    )
    narrative = score_narrative_gap(
        official_promises=list(payload.get("official_promises", []) or []),
        complaint_texts=texts,
    )
    premium_section = _section(payload, "premium")
    premium = score_premium_promise_failure(
        price_premium=coerce_float(premium_section.get("price_premium")),
        service_failure_rate=coerce_float(premium_section.get("service_failure_rate")),
        narrative_experience_gap=narrative.score,
        complaint_texts=texts,
    )
    segment_section = _section(payload, "segment_fit")
    segment = score_segment_fit(
        segment=str(payload.get("segment", "general")),
        **{
            k: coerce_float(v)
            for k, v in segment_section.items()
            if k in score_segment_fit.__kwdefaults__
            and k not in ("segment", "complaint_texts")
        },
        complaint_texts=texts,
    )
    enforcement_section = _section(payload, "enforcement")
    enforcement = score_enforcement_asymmetry(
        **{
            k: coerce_float(v)
            for k, v in enforcement_section.items()
            if k in score_enforcement_asymmetry.__kwdefaults__
            and k != "complaint_texts"
        },
        complaint_texts=texts,
    )
    friction_section = _section(payload, "friction")
    friction = score_friction_tax(
        **{
            k: coerce_float(v)
            for k, v in friction_section.items()
            if k in score_friction_tax.__kwdefaults__ and k != "complaint_texts"
        },
        complaint_texts=texts,
    )
    fragility_section = _section(payload, "fragility")
    fragility = score_regulatory_fragility(
        complaint_severity=coerce_float(fragility_section.get("complaint_severity")),
        vulnerable_user_exposure=coerce_float(
            fragility_section.get("vulnerable_user_exposure")
        ),
        legal_ambiguity=coerce_float(fragility_section.get("legal_ambiguity")),
        complaint_texts=texts,
    )

    informational_sections = (
        "consent", "capabilities", "pause", "delay", "subscription",
        "claims", "premium", "segment_fit", "enforcement", "friction",
        "fragility",
    )
    any_information = bool(texts) or bool(
        payload.get("official_promises")
    ) or any(_section(payload, key) for key in informational_sections)

    adjusted = score_adjusted_revenue_quality(
        consent_quality=consent,
        subscription_extraction=subscription,
        regulatory_fragility=fragility,
        friction_tax=friction,
        narrative_gap=narrative,
        claims_non_payment=claims,
        service_fulfilment=coerce_float(payload.get("service_fulfilment"), 0.5),
        reported_revenue_quality=(
            coerce_float(payload["reported_revenue_quality"])
            if payload.get("reported_revenue_quality") is not None
            else None
        ),
        any_information_supplied=any_information,
    )

    all_evidence = extract_evidence(texts)
    evidence_terms = sorted(
        {
            term
            for hit in all_evidence.values()
            for term in hit.matched_terms
            if hit.category != "positive_relief"
        }
    )

    return {
        "company": str(payload.get("company", "UNKNOWN")),
        "segment": str(payload.get("segment", "general")),
        "advisory_note": CONSENT_ADVISORY_NOTE,
        "doctrine": list(CONSENT_DOCTRINE),
        "evidence_text_count": len(texts),
        "evidence_terms": evidence_terms,
        "consent_quality": consent.to_dict(),
        "digital_asymmetry": asymmetry.to_dict(),
        "pause_friction": pause.to_dict(),
        "delay_revenue": delay.to_dict(),
        "subscription_extraction": subscription.to_dict(),
        "claims_non_payment": claims.to_dict(),
        "premium_promise_failure": premium.to_dict(),
        "segment_fit": segment.to_dict(),
        "enforcement_asymmetry": enforcement.to_dict(),
        "friction_tax": friction.to_dict(),
        "narrative_experience_gap": narrative.to_dict(),
        "regulatory_fragility": fragility.to_dict(),
        "adjusted_revenue_quality": adjusted.to_dict(),
        "revenue_quality_label": adjusted.label,
    }


def to_simulator_risk_factors(profile: dict[str, Any]) -> dict[str, float]:
    """Bridge a consent profile into crash-simulator risk factors.

    Business-model fragility becomes a first-class crash vector: the
    cherry-pick pipeline can merge these into its ``risk_factors`` payload
    so an extractive revenue base interacts with valuation/macro risks.
    """
    def _risk(key: str) -> float:
        layer = profile.get(key) or {}
        return clamp01(coerce_float(layer.get("score")) / 10.0)

    factors = {
        "extractive_revenue": _risk("subscription_extraction"),
        "regulatory_fragility": _risk("regulatory_fragility"),
        "claims_non_payment": _risk("claims_non_payment"),
        "customer_churn_pressure": max(
            _risk("friction_tax"), _risk("enforcement_asymmetry")
        ),
        "narrative_experience_gap": _risk("narrative_experience_gap"),
    }
    return {name: value for name, value in factors.items() if value > 0.0}
