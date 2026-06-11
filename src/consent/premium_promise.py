"""Premium Promise Failure: a premium price creates a premium
accountability contract.

    Premium Promise Failure =
        price_premium × service_failure_rate × narrative_experience_gap

Ryanair coherence rule: a low price with a narrow promise is coherent and
scores low here even with spartan service; a high price with a broad
promise and weak delivery is betrayal and scores high.
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


def score_premium_promise_failure(
    *,
    price_premium: float = 0.0,
    service_failure_rate: float = 0.0,
    narrative_experience_gap: float = 0.0,
    complaint_texts: list[str] | None = None,
) -> LayerScore:
    """Premium promise failure (0–10, higher = worse).

    ``price_premium`` in [0, 1]: 0 = budget positioning, 1 = full premium.
    ``narrative_experience_gap`` accepts either [0, 1] or the 0–10 output
    of the narrative-gap module (auto-normalized).
    """
    texts = list(complaint_texts or [])
    hits = extract_evidence(texts)

    premium = normalized_score(price_premium)
    failure = normalized_score(service_failure_rate)
    gap_raw = float(narrative_experience_gap)
    gap = clamp01(gap_raw / 10.0) if gap_raw > 1.0 else clamp01(gap_raw)

    rationale: list[str] = []
    failure_evidence = evidence_intensity(hits["premium_failure"], len(texts))
    if failure_evidence > failure:
        rationale.append(
            f"evidence raised service_failure_rate to {failure_evidence:.2f} "
            f"({hits['premium_failure'].count} premium-failure match(es))"
        )
        failure = failure_evidence

    # Multiplicative: budget pricing (low premium) keeps the score low even
    # with weak service — cheap and clear beats expensive and evasive.
    # When no narrative-gap measurement exists, the evidenced failure rate
    # itself stands in for the gap: under premium positioning, experienced
    # failure IS the broken promise.
    effective_gap = max(gap, failure if premium >= 0.5 else 0.0)
    score = scale_to_ten(clamp01(premium * failure * (0.4 + 0.6 * effective_gap)))

    rationale.insert(
        0,
        f"price premium {premium:.2f} × service failure {failure:.2f} × "
        f"narrative gap {gap:.2f}",
    )
    if premium >= 0.6 and failure >= 0.5:
        rationale.append(
            "premium positioning with weak delivery — the price promised a "
            "service standard the experience did not honor"
        )
    if premium < 0.3 and failure > 0.5:
        rationale.append(
            "budget positioning keeps promise coherence despite weak "
            "service (Ryanair rule: narrow promise, low price)"
        )

    warnings = confidence_warnings(len(texts))
    if price_premium == 0.0:
        warnings.append(
            "no price positioning supplied — premium failure cannot exceed "
            "zero without a premium claim"
        )

    return LayerScore(
        name="premium_promise_failure",
        score=score,
        label=risk_label(score),
        higher_is_worse=True,
        confidence=clamp01(
            0.5 * (1.0 if price_premium else 0.0)
            + 0.5 * evidence_confidence(len(texts))
        ),
        evidence_terms=matched_terms(hits, ["premium_failure"]),
        rationale=rationale,
        missing_data_warnings=warnings,
        raw_components={
            "price_premium": premium,
            "service_failure_rate": failure,
            "narrative_experience_gap": gap,
        },
    )
