"""Jurisdiction-aware regulatory risk map (pattern classification only).

Maps detected evidence categories onto named regulatory risk domains,
weighted by jurisdiction context (Germany/EU consumer-subscription rules
are the founding context). This classifies RISK PATTERNS for research —
it is not legal advice, infers no guilt, and infers no intent.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from src.consent.evidence import (
    EvidenceHit,
    detect_topics,
    evidence_intensity,
    extract_evidence,
)
from src.utils.math_utils import clamp01

RISK_DOMAINS: tuple[str, ...] = (
    "consumer_subscription_risk",
    "insurance_claims_risk",
    "direct_debit_billing_risk",
    "language_accessibility_risk",
    "dark_pattern_risk",
    "vulnerable_user_risk",
    "claims_handling_risk",
    "refund_friction_risk",
)

# Domain -> (evidence categories, base weight). Weights express how
# directly the evidence pattern maps onto the regulatory domain.
_DOMAIN_EVIDENCE: dict[str, tuple[tuple[str, ...], float]] = {
    "consumer_subscription_risk": (
        ("cannot_cancel", "charged_after_cancellation", "lock_in"), 1.0,
    ),
    "insurance_claims_risk": (("claims_non_payment",), 1.0),
    "direct_debit_billing_risk": (
        ("enforcement_speed", "hidden_fees", "charged_after_cancellation"), 0.9,
    ),
    "language_accessibility_risk": (("language_burden",), 1.0),
    "dark_pattern_risk": (
        ("email_only_relief", "pause_friction", "cannot_cancel",
         "backend_mismatch"), 0.8,
    ),
    "vulnerable_user_risk": (("language_burden", "hidden_fees"), 0.8),
    "claims_handling_risk": (("claims_non_payment", "bot_only_support"), 0.9),
    "refund_friction_risk": (("processing_delay", "email_only_relief"), 0.9),
}

# Jurisdictions where these consumer-protection patterns carry recognized
# regulatory weight (DE/EU consumer subscription + SEPA context).
_EU_JURISDICTIONS = {"de", "germany", "eu", "at", "austria", "european_union"}

VULNERABLE_SEGMENTS_FOR_JURISDICTION = {
    "international_students", "students", "migrants", "temporary_residents",
    "low_income", "elderly", "non_native_speakers",
}


@dataclass(slots=True)
class JurisdictionRiskMap:
    """Named regulatory risk domains with intensities and provenance."""

    jurisdiction: str
    jurisdiction_recognized: bool
    domains: dict[str, float] = field(default_factory=dict)
    active_domains: list[str] = field(default_factory=list)
    topics_detected: dict[str, list[str]] = field(default_factory=dict)
    rationale: list[str] = field(default_factory=list)
    disclaimer: str = (
        "Risk-pattern classification only — not legal advice, no inference "
        "of guilt or intent. ADVISORY_ONLY."
    )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_jurisdiction_risk_map(
    *,
    complaint_texts: list[str],
    jurisdiction: str = "",
    segment: str = "general",
    hits: dict[str, EvidenceHit] | None = None,
) -> JurisdictionRiskMap:
    """Map complaint evidence onto jurisdiction-aware risk domains."""
    texts = list(complaint_texts or [])
    evidence = hits if hits is not None else extract_evidence(texts)
    topics = detect_topics(texts)

    jurisdiction_norm = str(jurisdiction).strip().lower()
    recognized = jurisdiction_norm in _EU_JURISDICTIONS or bool(
        topics.get("mobility") or topics.get("arrears")
    )
    # EU context sharpens consumer-protection weights slightly; absence of
    # jurisdiction info never zeroes a pattern, it only softens it.
    jurisdiction_factor = 1.0 if recognized else 0.85

    vulnerable = str(segment).strip().lower() in (
        VULNERABLE_SEGMENTS_FOR_JURISDICTION
    )

    domains: dict[str, float] = {}
    rationale: list[str] = []
    for domain, (categories, weight) in _DOMAIN_EVIDENCE.items():
        intensity = max(
            (evidence_intensity(evidence[c], len(texts)) for c in categories),
            default=0.0,
        )
        value = clamp01(intensity * weight * jurisdiction_factor)
        if domain == "vulnerable_user_risk" and vulnerable and value < intensity:
            value = clamp01(intensity)  # vulnerable segment removes softening
        if domain == "vulnerable_user_risk" and vulnerable and value > 0:
            rationale.append(
                f"vulnerable segment '{segment}' holds {domain} at full "
                "intensity"
            )
        domains[domain] = value

    active = sorted(
        (d for d, v in domains.items() if v >= 0.25),
        key=lambda d: -domains[d],
    )
    if active:
        rationale.insert(
            0,
            "active regulatory risk domains: "
            + ", ".join(f"{d} ({domains[d]:.2f})" for d in active),
        )
    else:
        rationale.insert(0, "no regulatory risk domain crossed 0.25 intensity")
    if recognized and jurisdiction_norm:
        rationale.append(
            f"jurisdiction '{jurisdiction_norm}' recognized: DE/EU consumer-"
            "subscription and SEPA billing patterns weighted fully"
        )

    return JurisdictionRiskMap(
        jurisdiction=jurisdiction_norm or "unspecified",
        jurisdiction_recognized=recognized,
        domains=domains,
        active_domains=active,
        topics_detected=topics,
        rationale=rationale,
    )
