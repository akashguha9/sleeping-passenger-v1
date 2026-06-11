"""Shared evidence extraction and score contract for the consent engine.

Complaint/review texts are scanned against deterministic phrase lexicons
(one lexicon per harm category). Extraction is counting, not inference:
the engine never claims intent, only that evidence phrases occur.

Every module in this package returns a ``LayerScore`` carrying score
(0–10), label, evidence terms, rationale, confidence, and explicit
missing-data warnings — no naked numbers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from src.utils.math_utils import clamp01, clip

# ---------------------------------------------------------------------------
# Evidence lexicons. Phrases are matched case-insensitively as substrings.
# Categories mirror the structural patterns in the reflection: easy signup /
# hard cancellation, automatic payment / manual refund, bot-only support,
# language burden, monetized delay, claims non-payment, premium failure.
# ---------------------------------------------------------------------------

EVIDENCE_LEXICONS: dict[str, tuple[str, ...]] = {
    "charged_after_cancellation": (
        "charged after cancel", "cancelled but billed", "canceled but billed",
        "billed after cancellation", "app says cancelled",
        "store says not cancelled", "kept charging", "payment after cancellation",
    ),
    "cannot_cancel": (
        "cannot cancel", "can't cancel", "couldn't cancel", "could not cancel",
        "no cancellation option", "hard to cancel", "written notice required",
        "cancellation deadline", "auto-renew", "auto renewal",
    ),
    "email_only_relief": (
        "email only", "had to email", "write an email", "only by email",
        "by post", "letter required", "in writing only",
    ),
    "bot_only_support": (
        "bot only", "automated bot", "no human", "support unreachable",
        "please email", "no response", "never replied", "no escalation",
        "call queue", "hotline loop",
    ),
    "language_burden": (
        "german only", "only in german", "had to translate", "no english",
        "foreign language letter", "not in english",
    ),
    "processing_delay": (
        "took a week", "took weeks", "still charged", "waiting for response",
        "processing delay", "refund pending", "processed once per week",
        "slow reply", "weeks for refund", "still waiting",
    ),
    "hidden_fees": (
        "hidden fee", "unexpected charge", "admin fee", "interest charged",
        "late fee", "mahnung", "collection letter", "sent to collections",
        "debt collection", "default interest", "reminder fee",
    ),
    "claims_non_payment": (
        "claim denied", "no reimbursement", "never reimbursed",
        "not reimbursed", "claim ignored", "documents missing",
        "no formal rejection", "no payout", "claim rejected without",
        "never paid a claim",
    ),
    "premium_failure": (
        "stolen", "theft", "no support", "poor service", "restricted access",
        "not all equipment", "trainer required", "upfront fee", "no refund",
        "front desk did not help", "incident ignored",
    ),
    "lock_in": (
        "lock-in", "locked in", "minimum term", "trainer contract",
        "cannot pause", "add-on contract", "bundled contract",
    ),
    "pause_friction": (
        "cannot pause in app", "pause requires", "freeze requires",
        "pause by email", "freeze by email", "still charged while waiting",
        "pause took", "suspend membership",
    ),
    "enforcement_speed": (
        "debited immediately", "instant debit", "direct debit failed",
        "fine", "penalty letter", "fast to charge", "debt letter",
        "enforcement",
    ),
    "backend_mismatch": (
        "app says cancelled", "store says not cancelled", "different department",
        "wrong department", "not synchronized", "office did not know",
        "local store was not informed",
    ),
    "positive_relief": (
        "easy to cancel", "cancelled in app", "refunded quickly",
        "quick refund", "responsive support", "no problem cancelling",
        "claim paid", "reimbursed promptly", "instant refund",
        "human answered",
    ),
}

# Confidence: how many independent evidence texts are enough to trust the
# qualitative extraction. Below the floor, scores carry explicit warnings.
EVIDENCE_FULL_CONFIDENCE_TEXTS = 8
EVIDENCE_MIN_TEXTS = 3


@dataclass(slots=True)
class EvidenceHit:
    """All matches for one harm category across the supplied texts."""

    category: str
    count: int
    matched_terms: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class LayerScore:
    """Mandatory score contract for every consent-engine module.

    ``score`` is 0–10. For risk modules 10 = worst risk; for quality
    modules 10 = best quality — ``higher_is_worse`` says which.
    """

    name: str
    score: float
    label: str
    higher_is_worse: bool
    confidence: float
    evidence_terms: list[str] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)
    missing_data_warnings: list[str] = field(default_factory=list)
    raw_components: dict[str, float] = field(default_factory=dict)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def extract_evidence(texts: list[str]) -> dict[str, EvidenceHit]:
    """Deterministic phrase extraction over complaint/review texts."""
    hits: dict[str, EvidenceHit] = {}
    lowered = [str(t).lower() for t in texts or []]
    for category, phrases in EVIDENCE_LEXICONS.items():
        matched: list[str] = []
        count = 0
        for text in lowered:
            for phrase in phrases:
                if phrase in text:
                    count += 1
                    if phrase not in matched:
                        matched.append(phrase)
        hits[category] = EvidenceHit(
            category=category, count=count, matched_terms=matched
        )
    return hits


def evidence_intensity(hit: EvidenceHit, text_count: int) -> float:
    """Category intensity in [0, 1] with a saturating denominator.

    A pattern present in ~40% of the texts (denominator capped at 8) is
    treated as fully established — large complaint sets don't need dozens
    of repeats, and small sets aren't diluted into invisibility. The
    confidence channel (``evidence_confidence``) separately reports how
    much the sample size is worth.
    """
    if text_count <= 0:
        return 0.0
    denominator = clip(text_count * 0.4, 1.0, 8.0)
    return clamp01(hit.count / denominator)


def evidence_confidence(text_count: int) -> float:
    """Extraction confidence in [0, 1] from evidence volume alone."""
    return clamp01(text_count / EVIDENCE_FULL_CONFIDENCE_TEXTS)


def confidence_warnings(text_count: int) -> list[str]:
    """Standard missing-data warnings for thin evidence bases."""
    warnings: list[str] = []
    if text_count == 0:
        warnings.append(
            "no complaint/review texts supplied — evidence-based components "
            "are inactive and structured inputs dominate"
        )
    elif text_count < EVIDENCE_MIN_TEXTS:
        warnings.append(
            f"only {text_count} evidence text(s) — anecdotes are not "
            "statistical proof; treat evidence components as provisional"
        )
    return warnings


def matched_terms(hits: dict[str, EvidenceHit], categories: list[str]) -> list[str]:
    """Flatten matched terms across the given categories (deduplicated)."""
    terms: list[str] = []
    for category in categories:
        hit = hits.get(category)
        if hit:
            for term in hit.matched_terms:
                if term not in terms:
                    terms.append(term)
    return terms


def scale_to_ten(value01: float) -> float:
    """Map a [0, 1] internal value onto the 0–10 reporting scale."""
    return clip(value01 * 10.0, 0.0, 10.0)


def quality_label(score: float) -> str:
    """Label bands for quality scores (10 = best)."""
    if score >= 8.0:
        return "strong"
    if score >= 6.0:
        return "adequate"
    if score >= 4.0:
        return "weak"
    if score >= 2.0:
        return "poor"
    return "critical"


def risk_label(score: float) -> str:
    """Label bands for risk scores (10 = worst)."""
    if score >= 8.0:
        return "severe"
    if score >= 6.0:
        return "high"
    if score >= 4.0:
        return "elevated"
    if score >= 2.0:
        return "moderate"
    return "low"
