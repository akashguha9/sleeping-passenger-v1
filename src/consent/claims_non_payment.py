"""Claims Non-Payment Risk: insurance value is claim handling, not
premium collection.

Hard-data mode:

    risk = 1 - (claims_paid + formal_decisions_issued) / claims_submitted

Formal rejection counts as fulfilment of the *decision* duty (it enables
appeal); silence does not. When hard claim data is unavailable, the score
falls back to complaint-evidence intensity.
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
from src.utils.math_utils import clamp01, safe_div


def score_claims_non_payment(
    *,
    claims_submitted: int | None = None,
    claims_paid: int | None = None,
    formal_decisions_issued: int | None = None,
    complaint_texts: list[str] | None = None,
) -> LayerScore:
    """Claims non-payment risk (0–10, higher = worse)."""
    texts = list(complaint_texts or [])
    hits = extract_evidence(texts)
    evidence01 = evidence_intensity(hits["claims_non_payment"], len(texts))
    bot01 = evidence_intensity(hits["bot_only_support"], len(texts))

    hard_data = (
        claims_submitted is not None
        and claims_submitted > 0
        and claims_paid is not None
    )
    rationale: list[str] = []
    warnings = confidence_warnings(len(texts))

    if hard_data:
        paid = max(int(claims_paid or 0), 0)
        decided = max(int(formal_decisions_issued or 0), 0)
        submitted = max(int(claims_submitted or 0), 1)
        fulfilment = clamp01(safe_div(paid + decided, submitted))
        risk01 = 1.0 - fulfilment
        rationale.append(
            f"hard-data mode: ({paid} paid + {decided} formal decisions) / "
            f"{submitted} submitted -> fulfilment {fulfilment:.2f}"
        )
        mode_confidence = 0.7
    else:
        # Evidence mode: claims complaints plus bot-loop support (the
        # "please email" abandonment pattern) drive the risk.
        risk01 = clamp01(0.75 * evidence01 + 0.25 * bot01)
        rationale.append(
            f"evidence mode: claims-complaint intensity {evidence01:.2f}, "
            f"bot-loop intensity {bot01:.2f}"
        )
        warnings.append(
            "no hard claim counts supplied — NLP evidence mode only; "
            "claim-by-claim records would be stronger proof"
        )
        mode_confidence = 0.0

    score = scale_to_ten(risk01)
    if score >= 6.0:
        rationale.append(
            "premium collected with weak claim fulfilment — insurance value "
            "approaches zero when claims are neither paid nor formally decided"
        )

    return LayerScore(
        name="claims_non_payment_risk",
        score=score,
        label=risk_label(score),
        higher_is_worse=True,
        confidence=clamp01(mode_confidence + 0.3 * evidence_confidence(len(texts))),
        evidence_terms=matched_terms(
            hits, ["claims_non_payment", "bot_only_support"]
        ),
        rationale=rationale,
        missing_data_warnings=warnings,
        raw_components={
            "claims_submitted": float(claims_submitted or 0),
            "claims_paid": float(claims_paid or 0),
            "formal_decisions_issued": float(formal_decisions_issued or 0),
            "evidence_intensity": evidence01,
            "bot_loop_intensity": bot01,
        },
    )
