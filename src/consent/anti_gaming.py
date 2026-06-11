"""Anti-gaming evidence rules: praise is cheap, refutation is specific.

Rules enforced here:
  1. Generic praise ("friendly staff") cannot offset specific complaints.
  2. Marketing language is flagged and never counts as customer proof.
  3. Positive evidence helps ONLY when it directly refutes the same risk
     category ("refund received within 24 hours" vs refund friction).
  4. Resolution evidence (company fixed it) reduces severity.
  5. Each refutation reduces only its own category — "great equipment"
     does not unsay "claim never reimbursed".
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from src.consent.evidence import normalize_text
from src.utils.math_utils import clamp01

# Category-specific refutation lexicons: positive phrases that directly
# contradict a harm category. Anything not in these lists is either
# generic praise (ignored) or marketing (flagged).
REFUTATION_LEXICONS: dict[str, tuple[str, ...]] = {
    "cannot_cancel": (
        "cancelled in app with confirmation", "cancellation completed in app",
        "easy to cancel", "cancelled online without problems",
        "no problem cancelling", "problemlos gekundigt",
        "kundigung sofort bestatigt",
    ),
    "charged_after_cancellation": (
        "no charges after cancellation", "billing stopped immediately",
        "final bill was correct", "keine abbuchung nach kundigung",
    ),
    "processing_delay": (
        "refund received within 24 hours", "refunded within a day",
        "instant refund", "reply within hours", "same day response",
        "sofort erstattet", "schnell erstattet",
    ),
    "email_only_relief": (
        "cancelled in app with confirmation", "managed everything in the app",
        "self service worked",
    ),
    "pause_friction": (
        "paused in the app instantly", "pause confirmed immediately",
        "mitgliedschaft in der app pausiert",
    ),
    "claims_non_payment": (
        "claim paid in full", "claim approved within", "reimbursed promptly",
        "clear written decision", "erstattung erhalten",
        "antrag schnell genehmigt",
    ),
    "bot_only_support": (
        "human answered", "reached a person immediately",
        "support resolved it on the phone",
    ),
    "hidden_fees": (
        "no hidden fees", "all fees explained upfront",
        "transparent pricing, exactly as quoted",
    ),
}

# Marketing/self-promotional language: flagged, never counted as proof.
MARKETING_MARKERS: tuple[str, ...] = (
    "award-winning", "best-in-class", "world-class", "premium experience",
    "we offer", "we provide", "we pride ourselves", "our mission",
    "industry-leading", "state of the art", "join today", "sign up now",
    "exclusive offer", "testsieger",
)

# Resolution markers: the company demonstrably fixed a raised problem.
RESOLUTION_MARKERS: tuple[str, ...] = (
    "company responded and refunded", "issue was resolved", "they fixed it",
    "resolved after complaint", "refunded after i complained",
    "problem wurde gelost", "nach beschwerde erstattet",
)

# How much one full-strength refutation can reduce a category's severity.
MAX_REFUTATION_RELIEF = 0.5
MAX_RESOLUTION_RELIEF = 0.3


@dataclass(slots=True)
class AntiGamingReport:
    """What positive/marketing evidence was allowed to do, and why."""

    refutations_by_category: dict[str, float] = field(default_factory=dict)
    refutation_terms: dict[str, list[str]] = field(default_factory=dict)
    resolution_relief: float = 0.0
    resolution_terms: list[str] = field(default_factory=list)
    marketing_flagged: int = 0
    marketing_terms: list[str] = field(default_factory=list)
    generic_praise_ignored: int = 0
    rationale: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


_NORMALIZED_REFUTATIONS = {
    category: tuple((normalize_text(p), p) for p in phrases)
    for category, phrases in REFUTATION_LEXICONS.items()
}
_NORMALIZED_MARKETING = tuple(
    (normalize_text(m), m) for m in MARKETING_MARKERS
)
_NORMALIZED_RESOLUTIONS = tuple(
    (normalize_text(m), m) for m in RESOLUTION_MARKERS
)
_GENERIC_PRAISE = tuple(
    normalize_text(p)
    for p in (
        "friendly staff", "great gym", "great equipment", "nice atmosphere",
        "love this place", "clean facility", "good music", "great location",
        "tolles studio", "nette mitarbeiter",
    )
)


def analyze_positive_evidence(texts: list[str]) -> AntiGamingReport:
    """Classify positive/marketing content into refutation, resolution,
    marketing, or ignored generic praise."""
    normalized = [normalize_text(t) for t in texts or []]
    text_count = max(len(normalized), 1)

    refutation_counts: dict[str, int] = {}
    refutation_terms: dict[str, list[str]] = {}
    for category, phrases in _NORMALIZED_REFUTATIONS.items():
        for text in normalized:
            for folded, original in phrases:
                if folded in text:
                    refutation_counts[category] = (
                        refutation_counts.get(category, 0) + 1
                    )
                    refutation_terms.setdefault(category, [])
                    if original not in refutation_terms[category]:
                        refutation_terms[category].append(original)

    # Saturating relief per category (mirrors evidence intensity scaling).
    denominator = max(min(text_count * 0.4, 8.0), 1.0)
    refutations = {
        category: clamp01(count / denominator) * MAX_REFUTATION_RELIEF
        for category, count in refutation_counts.items()
    }

    resolution_hits = 0
    resolution_terms: list[str] = []
    for text in normalized:
        for folded, original in _NORMALIZED_RESOLUTIONS:
            if folded in text:
                resolution_hits += 1
                if original not in resolution_terms:
                    resolution_terms.append(original)
    resolution_relief = clamp01(resolution_hits / denominator) * (
        MAX_RESOLUTION_RELIEF
    )

    marketing_terms: list[str] = []
    marketing_flagged = 0
    for text in normalized:
        for folded, original in _NORMALIZED_MARKETING:
            if folded in text:
                marketing_flagged += 1
                if original not in marketing_terms:
                    marketing_terms.append(original)

    generic_ignored = sum(
        1
        for text in normalized
        if any(p in text for p in _GENERIC_PRAISE)
        and not any(
            folded in text
            for phrases in _NORMALIZED_REFUTATIONS.values()
            for folded, _ in phrases
        )
    )

    rationale: list[str] = []
    if refutations:
        rationale.append(
            "category-specific refutations accepted for: "
            + ", ".join(sorted(refutations))
        )
    if resolution_relief > 0:
        rationale.append(
            f"resolution evidence grants {resolution_relief:.2f} severity "
            "relief across risk layers"
        )
    if marketing_flagged:
        rationale.append(
            f"{marketing_flagged} marketing-language text(s) flagged — "
            "company self-description is not customer proof"
        )
    if generic_ignored:
        rationale.append(
            f"{generic_ignored} generic-praise text(s) ignored — friendly "
            "staff cannot offset charged-after-cancellation"
        )

    return AntiGamingReport(
        refutations_by_category=refutations,
        refutation_terms=refutation_terms,
        resolution_relief=resolution_relief,
        resolution_terms=resolution_terms,
        marketing_flagged=marketing_flagged,
        marketing_terms=marketing_terms,
        generic_praise_ignored=generic_ignored,
        rationale=rationale,
    )


def apply_refutations(
    layer_scores: dict[str, float],
    category_map: dict[str, list[str]],
    report: AntiGamingReport,
) -> dict[str, float]:
    """Reduce layer risk scores using only same-category refutations.

    ``layer_scores`` maps layer name -> 0–10 risk score;
    ``category_map`` maps layer name -> the evidence categories it rests
    on. Relief = max refutation among those categories + resolution
    relief, multiplicatively applied.
    """
    adjusted: dict[str, float] = {}
    for layer, score in layer_scores.items():
        categories = category_map.get(layer, [])
        relief = max(
            (report.refutations_by_category.get(c, 0.0) for c in categories),
            default=0.0,
        )
        total_relief = clamp01(relief + report.resolution_relief)
        adjusted[layer] = score * (1.0 - total_relief)
    return adjusted
