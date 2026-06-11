"""Offline complaint ingestion adapter — no network, ever.

Accepts raw complaint strings, JSON files, CSV files, or structured
record dicts, and produces one normalized evidence bundle:

    deduplicated records + language guess + detected categories
    + evidence reliability + warnings

The bundle is the single input shape the consent engine and the pipeline
bridge consume, so callers never hand-assemble evidence again. Offline
ingestion is not live monitoring — sourcing data (and respecting source
ToS) remains the operator's job.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from src.consent.evidence import detect_topics, extract_evidence
from src.consent.evidence_reliability import (
    EvidenceRecord,
    ReliabilityReport,
    coerce_records,
    deduplicate_records,
    score_evidence_reliability,
)

_GERMAN_HINTS = (
    "kundigung", "vertrag", "beitrag", "erstattung", "mahnung", "lastschrift",
    "schriftlich", "versicherung", "abgebucht", "gekundigt", "nicht", "wurde",
)


@dataclass(slots=True)
class EvidenceBundle:
    """Normalized, deduplicated, reliability-scored complaint evidence."""

    records: list[EvidenceRecord] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    record_count: int = 0
    unique_count: int = 0
    duplicate_count: int = 0
    languages_detected: list[str] = field(default_factory=list)
    categories_detected: list[str] = field(default_factory=list)
    topics_detected: dict[str, list[str]] = field(default_factory=dict)
    reliability: ReliabilityReport | None = None
    sources: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["records"] = [r.to_dict() for r in self.records]
        payload["reliability"] = (
            self.reliability.to_dict() if self.reliability else None
        )
        return payload


def _guess_language(text: str) -> str:
    from src.consent.evidence import normalize_text

    normalized = normalize_text(text)
    german_hits = sum(1 for hint in _GERMAN_HINTS if hint in normalized)
    if german_hits >= 2:
        return "de"
    if german_hits == 1:
        return "mixed"
    return "en"


def build_evidence_bundle(
    evidence: list[EvidenceRecord | dict[str, Any] | str],
) -> EvidenceBundle:
    """Normalize any accepted evidence shape into one scored bundle."""
    records = coerce_records(evidence)
    unique, duplicates = deduplicate_records(records)

    for record in unique:
        if not record.language:
            record.language = _guess_language(record.text)

    texts = [r.text for r in unique]
    hits = extract_evidence(texts)
    categories = sorted(
        c for c, h in hits.items() if h.count > 0 and c != "positive_relief"
    )
    reliability = score_evidence_reliability(list(unique))

    warnings: list[str] = list(reliability.missing_data_warnings)
    if not records:
        warnings.append("no evidence supplied")
    if duplicates:
        warnings.append(
            f"{duplicates} duplicate/near-duplicate record(s) collapsed "
            "before scoring"
        )

    return EvidenceBundle(
        records=unique,
        texts=texts,
        record_count=len(records),
        unique_count=len(unique),
        duplicate_count=duplicates,
        languages_detected=sorted({r.language for r in unique if r.language}),
        categories_detected=categories,
        topics_detected=detect_topics(texts),
        reliability=reliability,
        sources=sorted({r.source for r in unique if r.source}),
        warnings=warnings,
    )


def ingest_json_file(path: str | Path) -> EvidenceBundle:
    """Load evidence from a local JSON file (list of records or strings,
    or an object with a ``complaints``/``records``/``reviews`` list)."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        for key in ("complaints", "records", "reviews", "evidence"):
            if isinstance(raw.get(key), list):
                raw = raw[key]
                break
        else:
            raw = []
    if not isinstance(raw, list):
        raw = []
    return build_evidence_bundle(raw)


def ingest_csv_file(path: str | Path) -> EvidenceBundle:
    """Load evidence from a local CSV file with a ``text`` column and any
    subset of the EvidenceRecord columns."""
    records: list[dict[str, Any]] = []
    with Path(path).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            cleaned: dict[str, Any] = {
                k.strip(): (v.strip() if isinstance(v, str) else v)
                for k, v in row.items()
                if k
            }
            if cleaned.get("resolved") is not None:
                cleaned["resolved"] = str(cleaned["resolved"]).lower() in (
                    "true", "1", "yes", "ja",
                )
            if cleaned.get("rating"):
                try:
                    cleaned["rating"] = float(cleaned["rating"])
                except ValueError:
                    cleaned["rating"] = None
            records.append(cleaned)
    return build_evidence_bundle(records)


def ingest_raw_texts(texts: list[str]) -> EvidenceBundle:
    """Wrap a plain list of complaint strings."""
    return build_evidence_bundle(list(texts or []))
