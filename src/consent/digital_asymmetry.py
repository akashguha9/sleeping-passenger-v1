"""Digital Collection vs Digital Relief engine, plus pause/freeze friction.

The structural red flag: a system digitally optimized to collect money but
manually obstructive when the customer wants relief.

    Digital Relief Gap = digital_collection_score - digital_relief_score
    (0–10 each; a high positive gap is extraction risk)

Pause friction is scored separately from cancellation friction — temporary
suspension is its own relief action and its own dark pattern:

    Pause Friction Risk = manual_pause_burden + language_burden
        + processing_delay_cost + continued_billing_during_delay
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

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

# Collection-side actions: how easy it is for money to flow IN.
COLLECTION_ACTIONS: tuple[str, ...] = (
    "digital_signup",
    "digital_payment",
    "stored_payment_method",
    "auto_renewal",
    "instant_billing",
)

# Relief-side actions: how easy it is for the CUSTOMER to act.
RELIEF_ACTIONS: tuple[str, ...] = (
    "cancel_in_app",
    "pause_in_app",
    "refund_in_app",
    "dispute_in_app",
    "update_billing_in_app",
    "view_billing_period",
    "reach_human_support",
)

ASYMMETRY_RISK_THRESHOLD = 4.0


@dataclass(slots=True)
class DigitalAsymmetryReport:
    """Collection vs relief surface comparison."""

    digital_collection_score: float
    digital_relief_score: float
    digital_relief_gap: float
    digital_asymmetry_risk: float
    label: str
    confidence: float
    collection_actions_present: list[str] = field(default_factory=list)
    relief_actions_present: list[str] = field(default_factory=list)
    relief_actions_missing: list[str] = field(default_factory=list)
    evidence_terms: list[str] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)
    missing_data_warnings: list[str] = field(default_factory=list)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def score_digital_asymmetry(
    *,
    collection_capabilities: dict[str, bool] | None = None,
    relief_capabilities: dict[str, bool] | None = None,
    complaint_texts: list[str] | None = None,
) -> DigitalAsymmetryReport:
    """Compare payment ease against relief ease (both 0–10)."""
    collection = {k: bool((collection_capabilities or {}).get(k)) for k in COLLECTION_ACTIONS}
    relief = {k: bool((relief_capabilities or {}).get(k)) for k in RELIEF_ACTIONS}
    texts = list(complaint_texts or [])
    hits = extract_evidence(texts)

    collection01 = sum(collection.values()) / len(COLLECTION_ACTIONS)
    relief01 = sum(relief.values()) / len(RELIEF_ACTIONS)

    # Complaint evidence about manual relief reduces the relief score even
    # when the capability matrix claims otherwise — experienced output wins.
    rationale: list[str] = []
    relief_evidence = max(
        evidence_intensity(hits["email_only_relief"], len(texts)),
        evidence_intensity(hits["cannot_cancel"], len(texts)),
        evidence_intensity(hits["pause_friction"], len(texts)),
    )
    if relief_evidence > 0:
        reduced = clamp01(relief01 * (1.0 - relief_evidence))
        rationale.append(
            f"complaint evidence (intensity {relief_evidence:.2f}) reduced "
            f"relief score from {relief01:.2f} to {reduced:.2f} — the user "
            "experiences relief, not the capability matrix"
        )
        relief01 = reduced

    collection_score = scale_to_ten(collection01)
    relief_score = scale_to_ten(relief01)
    gap = collection_score - relief_score
    risk = clamp01(max(gap, 0.0) / 10.0) * 10.0

    missing = [k for k, present in relief.items() if not present]
    rationale.insert(
        0,
        f"collection surface {collection_score:.1f}/10 vs relief surface "
        f"{relief_score:.1f}/10 (gap {gap:+.1f})",
    )
    if risk >= ASYMMETRY_RISK_THRESHOLD:
        rationale.append(
            "digital collection outruns digital relief — money in is "
            "automated while money out / exit is manual"
        )

    warnings = confidence_warnings(len(texts))
    if collection_capabilities is None and relief_capabilities is None:
        warnings.append(
            "no capability matrix supplied — asymmetry derived from "
            "complaint evidence only"
        )

    structured = 1.0 if (collection_capabilities or relief_capabilities) else 0.0
    confidence = clamp01(0.5 * structured + 0.5 * evidence_confidence(len(texts)))

    return DigitalAsymmetryReport(
        digital_collection_score=collection_score,
        digital_relief_score=relief_score,
        digital_relief_gap=gap,
        digital_asymmetry_risk=risk,
        label=risk_label(risk),
        confidence=confidence,
        collection_actions_present=[k for k, v in collection.items() if v],
        relief_actions_present=[k for k, v in relief.items() if v],
        relief_actions_missing=missing,
        evidence_terms=matched_terms(
            hits, ["email_only_relief", "cannot_cancel", "pause_friction"]
        ),
        rationale=rationale,
        missing_data_warnings=warnings,
    )


def score_pause_friction(
    *,
    manual_pause_burden: float = 0.0,
    language_burden: float = 0.0,
    processing_delay_days: float = 0.0,
    billing_continues_during_delay: bool = False,
    charge_per_week: float = 0.0,
    complaint_texts: list[str] | None = None,
) -> LayerScore:
    """Pause/freeze friction risk (0–10, higher = worse).

    Distinct from cancellation friction: this is the cost of temporary
    suspension. The gym case: pause by German email, ~1 week processing,
    billing continues — €7.50 of monetized delay per cycle.
    """
    texts = list(complaint_texts or [])
    hits = extract_evidence(texts)

    manual = normalized_score(manual_pause_burden)
    language = normalized_score(language_burden)
    delay_days = max(float(processing_delay_days), 0.0)
    # A two-week pending pause is fully bad on this axis.
    delay01 = clamp01(delay_days / 14.0)

    evidence_pause = evidence_intensity(hits["pause_friction"], len(texts))
    evidence_delay = evidence_intensity(hits["processing_delay"], len(texts))
    manual = max(manual, evidence_pause)
    delay01 = max(delay01, evidence_delay)
    language = max(language, evidence_intensity(hits["language_burden"], len(texts)))

    continued = 1.0 if billing_continues_during_delay else 0.0
    if continued == 0.0 and evidence_intensity(hits["processing_delay"], len(texts)) > 0:
        # "still charged" phrases imply billing continued.
        still_charged = any(
            "still charged" in term for term in hits["processing_delay"].matched_terms
        )
        if still_charged:
            continued = 1.0

    risk01 = clamp01(
        0.30 * manual + 0.20 * language + 0.25 * delay01 + 0.25 * continued
    )
    score = scale_to_ten(risk01)

    delay_cost = (delay_days / 7.0) * max(float(charge_per_week), 0.0)
    rationale = [
        f"manual burden {manual:.2f}, language burden {language:.2f}, "
        f"delay {delay_days:.1f}d, billing continues: {bool(continued)}",
    ]
    if delay_cost > 0 and continued:
        rationale.append(
            f"estimated monetized pause delay ≈ €{delay_cost:.2f} per request "
            "(delay × weekly charge while billing continues)"
        )

    warnings = confidence_warnings(len(texts))
    if charge_per_week <= 0:
        warnings.append("no charge rate supplied — delay cost not estimated")

    return LayerScore(
        name="pause_friction_risk",
        score=score,
        label=risk_label(score),
        higher_is_worse=True,
        confidence=clamp01(
            0.5 * (1.0 if (manual_pause_burden or processing_delay_days) else 0.0)
            + 0.5 * evidence_confidence(len(texts))
        ),
        evidence_terms=matched_terms(
            hits, ["pause_friction", "processing_delay", "language_burden"]
        ),
        rationale=rationale,
        missing_data_warnings=warnings,
        raw_components={
            "manual_pause_burden": manual,
            "language_burden": language,
            "processing_delay_days": delay_days,
            "continued_billing_during_delay": continued,
            "estimated_delay_cost_eur": delay_cost,
        },
    )
