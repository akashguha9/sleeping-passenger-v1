"""Evidence reliability: one angry anecdote is not a regulator action.

    Evidence Reliability =
        source_quality + corroboration + recency + specificity + severity
        − anecdote_penalty − duplicate_penalty − vague_language_penalty

Normalized 0–10. Reliability gates how hard consent findings may hit a
candidate: severe risk with low reliability is a warning, not a verdict.

Anti-inflation rules built in:
  * duplicate / near-duplicate texts are collapsed before counting,
  * corroboration counts distinct independent sources, not echoes,
  * specificity requires concrete details (amounts, dates, category
    phrases), vague rants are penalized,
  * source weights: regulator action > lawsuit > official disclosure >
    verified review > app store review > forum post > anonymous text.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.consent.evidence import extract_evidence, normalize_text
from src.utils.math_utils import clamp01, clip

SOURCE_WEIGHTS: dict[str, float] = {
    "regulator_action": 1.00,
    "lawsuit": 0.95,
    "official_disclosure": 0.85,
    "verified_review": 0.70,
    "app_store_review": 0.55,
    "forum_post": 0.40,
    "anonymous": 0.25,
    "unknown": 0.25,
}

# Jaccard similarity at or above this marks a near-duplicate. 0.75 catches
# filler-word paraphrases of the same sentence ("i was charged ... and a
# ... was added") while genuinely independent complaints — different
# amounts, dates, and phrasing — sit far below it.
NEAR_DUPLICATE_JACCARD = 0.75

_VAGUE_MARKERS = (
    "terrible", "awful", "worst ever", "scam", "horrible", "never again",
    "stay away", "do not recommend", "schrecklich", "abzocke", "nie wieder",
)
_SPECIFICITY_PATTERN = re.compile(r"\d")  # amounts, dates, durations

RELIABILITY_HIGH = 6.5
RELIABILITY_LOW = 3.5


@dataclass(slots=True)
class EvidenceRecord:
    """One normalized piece of complaint/review evidence."""

    text: str
    source: str = ""
    source_type: str = "unknown"
    date: str = ""
    language: str = ""
    rating: float | None = None
    jurisdiction: str = ""
    category: str = ""
    url: str = ""
    company_response: str = ""
    resolved: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class ReliabilityReport:
    """Reliability verdict over a deduplicated evidence set."""

    score: float
    band: str
    record_count: int
    unique_count: int
    duplicate_count: int
    independent_sources: int
    best_source_type: str
    rationale: list[str] = field(default_factory=list)
    missing_data_warnings: list[str] = field(default_factory=list)
    raw_components: dict[str, float] = field(default_factory=dict)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def coerce_records(
    evidence: list[EvidenceRecord | dict[str, Any] | str],
) -> list[EvidenceRecord]:
    """Accept records, dicts, or raw strings."""
    records: list[EvidenceRecord] = []
    for item in evidence or []:
        if isinstance(item, EvidenceRecord):
            records.append(item)
        elif isinstance(item, dict):
            known = {f for f in EvidenceRecord.__dataclass_fields__}
            records.append(
                EvidenceRecord(**{k: v for k, v in item.items() if k in known})
            )
        else:
            records.append(EvidenceRecord(text=str(item)))
    return [r for r in records if r.text.strip()]


def _token_set(text: str) -> frozenset[str]:
    return frozenset(normalize_text(text).split())


def deduplicate_records(
    records: list[EvidenceRecord],
) -> tuple[list[EvidenceRecord], int]:
    """Collapse exact and near-duplicate texts (first occurrence wins)."""
    unique: list[EvidenceRecord] = []
    kept_tokens: list[frozenset[str]] = []
    duplicates = 0
    for record in records:
        tokens = _token_set(record.text)
        is_duplicate = False
        for existing in kept_tokens:
            union = tokens | existing
            if union and len(tokens & existing) / len(union) >= NEAR_DUPLICATE_JACCARD:
                is_duplicate = True
                break
        if is_duplicate:
            duplicates += 1
        else:
            unique.append(record)
            kept_tokens.append(tokens)
    return unique, duplicates


def _recency_score(record: EvidenceRecord, as_of: datetime) -> float:
    if not record.date:
        return 0.4  # unknown age: mild credit, not full
    try:
        parsed = datetime.fromisoformat(record.date)
    except ValueError:
        return 0.4
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    age_days = max((as_of - parsed).days, 0)
    # Two-year half-life on evidence freshness.
    return clamp01(0.5 ** (age_days / 730.0))


def _specificity_score(record: EvidenceRecord) -> float:
    """Concrete details earn specificity; vague outrage does not."""
    text = record.text
    score = 0.0
    if _SPECIFICITY_PATTERN.search(text):
        score += 0.4  # amounts / dates / durations
    hits = extract_evidence([text])
    category_hits = sum(
        1 for c, h in hits.items() if h.count > 0 and c != "positive_relief"
    )
    score += min(category_hits, 3) * 0.2
    return clamp01(score)


def _vagueness(record: EvidenceRecord) -> float:
    normalized = normalize_text(record.text)
    markers = sum(1 for m in _VAGUE_MARKERS if normalize_text(m) in normalized)
    specific = _specificity_score(record)
    return clamp01(markers * 0.3) * (1.0 - specific)


def score_evidence_reliability(
    evidence: list[EvidenceRecord | dict[str, Any] | str],
    *,
    as_of: datetime | None = None,
) -> ReliabilityReport:
    """Score reliability of a complaint-evidence set (0–10)."""
    now = as_of or datetime.now(timezone.utc)
    records = coerce_records(evidence)
    unique, duplicates = deduplicate_records(records)

    if not unique:
        return ReliabilityReport(
            score=0.0,
            band="none",
            record_count=len(records),
            unique_count=0,
            duplicate_count=duplicates,
            independent_sources=0,
            best_source_type="none",
            missing_data_warnings=["no usable evidence supplied"],
        )

    weights = [
        SOURCE_WEIGHTS.get(r.source_type, SOURCE_WEIGHTS["unknown"])
        for r in unique
    ]
    source_quality = max(weights)
    best_source = max(
        unique,
        key=lambda r: SOURCE_WEIGHTS.get(r.source_type, 0.25),
    ).source_type

    sources = {
        (r.source or f"_anon_{i}", r.source_type) for i, r in enumerate(unique)
    }
    independent = len(sources)
    corroboration = clamp01((independent - 1) / 4.0)  # 5 sources = full

    recency = sum(_recency_score(r, now) for r in unique) / len(unique)
    specificity = sum(_specificity_score(r) for r in unique) / len(unique)
    severity = clamp01(
        sum(
            1
            for r in unique
            if _specificity_score(r) >= 0.4
        )
        / max(len(unique), 1)
    )

    anecdote_penalty = 0.30 if len(unique) == 1 else (0.15 if len(unique) == 2 else 0.0)
    duplicate_penalty = clamp01(duplicates / max(len(records), 1)) * 0.20
    vague_penalty = sum(_vagueness(r) for r in unique) / len(unique) * 0.30

    reliability01 = clamp01(
        0.35 * source_quality
        + 0.25 * corroboration
        + 0.10 * recency
        + 0.20 * specificity
        + 0.10 * severity
        - anecdote_penalty
        - duplicate_penalty
        - vague_penalty
    )
    score = clip(reliability01 * 10.0, 0.0, 10.0)
    band = (
        "high" if score >= RELIABILITY_HIGH
        else ("medium" if score >= RELIABILITY_LOW else "low")
    )

    rationale = [
        f"{len(unique)} unique record(s) from {independent} independent "
        f"source(s); {duplicates} duplicate(s) collapsed",
        f"best source type: {best_source} "
        f"(weight {SOURCE_WEIGHTS.get(best_source, 0.25):.2f})",
        f"specificity {specificity:.2f}, recency {recency:.2f}, "
        f"corroboration {corroboration:.2f}",
    ]
    warnings: list[str] = []
    if len(unique) == 1:
        warnings.append(
            "single anecdote — a warning signal, never a verdict; "
            "anecdote penalty applied"
        )
    if duplicates:
        rationale.append(
            f"duplicate penalty {duplicate_penalty:.2f} — copied text does "
            "not corroborate itself"
        )
    if all(r.source_type in ("unknown", "anonymous") for r in unique):
        warnings.append("all evidence is anonymous/unattributed")

    return ReliabilityReport(
        score=score,
        band=band,
        record_count=len(records),
        unique_count=len(unique),
        duplicate_count=duplicates,
        independent_sources=independent,
        best_source_type=best_source,
        rationale=rationale,
        missing_data_warnings=warnings,
        raw_components={
            "source_quality": source_quality,
            "corroboration": corroboration,
            "recency": recency,
            "specificity": specificity,
            "severity": severity,
            "anecdote_penalty": anecdote_penalty,
            "duplicate_penalty": duplicate_penalty,
            "vague_language_penalty": vague_penalty,
        },
    )
