"""Narrative-Experience Gap: official promises vs customer evidence.

Each official promise tag maps to the complaint-evidence categories that
contradict it. The gap is the promise-weighted mean contradiction:

    Narrative-Experience Gap = |promise vector - experience vector|

A company that promises nothing scores near zero here (no promise, no
gap — coherence is judged by ``premium_promise`` instead). A company that
promises "seamless, flexible, student-friendly" while complaints show
email-only cancellation and German-only letters scores high.
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

# Promise tag -> evidence categories that contradict it.
PROMISE_CONTRADICTIONS: dict[str, tuple[str, ...]] = {
    "customer_centric": ("bot_only_support", "premium_failure"),
    "seamless": ("backend_mismatch", "processing_delay"),
    "digital_first": ("email_only_relief", "pause_friction"),
    "flexible": ("cannot_cancel", "lock_in"),
    "student_friendly": ("language_burden", "lock_in", "hidden_fees"),
    "premium": ("premium_failure",),
    "transparent": ("hidden_fees", "backend_mismatch"),
    "safe": ("premium_failure",),
    "reimbursed": ("claims_non_payment",),
    "easy_cancellation": ("cannot_cancel", "charged_after_cancellation"),
    "fast_claims": ("claims_non_payment", "processing_delay"),
}

KNOWN_PROMISES: tuple[str, ...] = tuple(PROMISE_CONTRADICTIONS)


def score_narrative_gap(
    *,
    official_promises: list[str] | None = None,
    complaint_texts: list[str] | None = None,
) -> LayerScore:
    """Narrative-experience gap (0–10, higher = bigger contradiction)."""
    promises = [
        str(p).strip().lower().replace(" ", "_").replace("-", "_")
        for p in (official_promises or [])
    ]
    recognized = [p for p in promises if p in PROMISE_CONTRADICTIONS]
    unknown = [p for p in promises if p not in PROMISE_CONTRADICTIONS]
    texts = list(complaint_texts or [])
    hits = extract_evidence(texts)

    rationale: list[str] = []
    warnings = confidence_warnings(len(texts))
    if unknown:
        warnings.append(
            f"unrecognized promise tag(s) ignored: {', '.join(sorted(unknown))}"
        )

    if not recognized:
        rationale.append(
            "no recognized official promises supplied — no narrative to "
            "contradict (coherence judged by premium_promise instead)"
        )
        return LayerScore(
            name="narrative_experience_gap",
            score=0.0,
            label=risk_label(0.0),
            higher_is_worse=True,
            confidence=clamp01(0.3 * evidence_confidence(len(texts))),
            evidence_terms=[],
            rationale=rationale,
            missing_data_warnings=warnings
            + ["no official promise vector supplied"],
            raw_components={},
        )

    contradicted: dict[str, float] = {}
    contradiction_categories: list[str] = []
    for promise in recognized:
        categories = PROMISE_CONTRADICTIONS[promise]
        contradiction = max(
            evidence_intensity(hits[c], len(texts)) for c in categories
        )
        contradicted[promise] = contradiction
        if contradiction > 0:
            contradiction_categories.extend(
                c for c in categories if hits[c].count > 0
            )
            rationale.append(
                f"promise '{promise}' contradicted at intensity "
                f"{contradiction:.2f}"
            )

    gap01 = clamp01(sum(contradicted.values()) / len(contradicted))
    score = scale_to_ten(gap01)
    rationale.insert(
        0,
        f"{sum(1 for v in contradicted.values() if v > 0)}/{len(recognized)} "
        f"promises contradicted by customer evidence (mean gap {gap01:.2f})",
    )

    return LayerScore(
        name="narrative_experience_gap",
        score=score,
        label=risk_label(score),
        higher_is_worse=True,
        confidence=clamp01(
            0.4 * min(len(recognized) / 3.0, 1.0)
            + 0.6 * evidence_confidence(len(texts))
        ),
        evidence_terms=matched_terms(hits, sorted(set(contradiction_categories))),
        rationale=rationale,
        missing_data_warnings=warnings,
        raw_components={f"promise_{k}": v for k, v in contradicted.items()},
    )
