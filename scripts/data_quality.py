"""Data-quality layer + evidence ledger for the advisory MVP (Pass 4).

Every ingested data point becomes a typed :class:`EvidenceItem` with
source, dual timestamps (published vs observed), provenance, a hash of
the raw evidence, and a bounded confidence. Items are persisted to an
append-only JSONL evidence ledger (``runtime/evidence_ledger.jsonl``,
gitignored) so every advisory claim can later answer "based on what?".

Hard rules (test-pinned):
  * confidence ∈ [0, 1];
  * source and observed timestamp are mandatory;
  * observed_at >= published_at when a published timestamp exists;
  * raw_hash = SHA256(raw evidence) — changes iff the raw evidence does;
  * evidence IDs are deterministic over (source, symbol, claim, raw_hash)
    so re-ingesting identical evidence cannot fork identities;
  * secret-shaped values are refused, full article bodies are not stored
    (claims are truncated; raw bodies live only as hashes);
  * ``advisory_only`` is always true — evidence supports human judgment,
    never execution (there is nothing to execute).
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
import hashlib
import json
import os
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

SOURCE_TYPES = ("manual", "api", "file", "web", "llm", "derived")
_MAX_CLAIM_CHARS = 280  # claims are summaries, never article bodies
_MAX_VALUE_CHARS = 200

_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9]{16,}"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9_\-.]{16,}"),
    re.compile(r"BEGIN [A-Z ]*PRIVATE KEY"),
    re.compile(r"(?i)(api_key|password|secret|token)\s*[=:]\s*\S{8,}"),
)


class EvidenceError(ValueError):
    """Raised when an evidence item violates the quality contract."""


def evidence_ledger_path() -> Path:
    raw = os.environ.get("MVP_EVIDENCE_LEDGER_PATH", "").strip()
    return Path(raw) if raw else _REPO_ROOT / "runtime" / "evidence_ledger.jsonl"


def _parse_utc(value: str | _dt.datetime | None, field: str) -> _dt.datetime | None:
    if value is None:
        return None
    if isinstance(value, _dt.datetime):
        dt = value
    else:
        try:
            dt = _dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise EvidenceError(f"{field}: unparsable timestamp {value!r}") from exc
    if dt.tzinfo is None:
        raise EvidenceError(
            f"{field}: naive timestamp {value!r} — timezone is mandatory "
            "(India/Germany/UTC confusion is exactly how leakage happens)"
        )
    return dt.astimezone(_dt.timezone.utc)


def hash_raw(raw: bytes | str) -> str:
    data = raw.encode("utf-8") if isinstance(raw, str) else raw
    return hashlib.sha256(data).hexdigest()


def looks_secret(text: str) -> bool:
    return any(p.search(text) for p in _SECRET_PATTERNS)


def redact_text(text: str, limit: int) -> str:
    """Refuse secrets outright; truncate long bodies to summary length."""
    if looks_secret(text):
        raise EvidenceError(
            "evidence text matches a secret pattern — secrets never enter "
            "the evidence ledger"
        )
    text = text.strip()
    return text[:limit] + "…" if len(text) > limit else text


@dataclasses.dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    observed_at_utc: str
    published_at_utc: str | None
    source_type: str
    source_name: str
    symbol: str
    market: str
    currency: str
    claim: str
    value: str
    normalized_value: float | None
    confidence: float
    freshness_days: float | None
    provenance: str
    extraction_method: str
    raw_hash: str
    advisory_only: bool = True

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


def build_evidence(
    *,
    source_type: str,
    source_name: str,
    claim: str,
    raw_evidence: bytes | str,
    observed_at: str | _dt.datetime,
    published_at: str | _dt.datetime | None = None,
    symbol: str = "",
    market: str = "",
    currency: str = "",
    value: str = "",
    normalized_value: float | None = None,
    confidence: float = 0.5,
    provenance: str = "",
    extraction_method: str = "manual",
) -> EvidenceItem:
    """Validate + normalize one evidence item (raises EvidenceError)."""
    if source_type not in SOURCE_TYPES:
        raise EvidenceError(f"source_type must be one of {SOURCE_TYPES}")
    if not source_name or not str(source_name).strip():
        raise EvidenceError("source_name is mandatory — anonymous evidence is not evidence")
    observed = _parse_utc(observed_at, "observed_at")
    if observed is None:
        raise EvidenceError("observed_at is mandatory")
    published = _parse_utc(published_at, "published_at")
    if published is not None and observed < published:
        raise EvidenceError(
            f"observed_at ({observed.isoformat()}) earlier than published_at "
            f"({published.isoformat()}) — impossible unless time travel; "
            "check timezone handling"
        )
    try:
        confidence = float(confidence)
    except (TypeError, ValueError) as exc:
        raise EvidenceError(f"confidence not numeric: {confidence!r}") from exc
    if not (0.0 <= confidence <= 1.0):
        raise EvidenceError(f"confidence {confidence} outside [0, 1]")
    if normalized_value is not None:
        normalized_value = float(normalized_value)
        if normalized_value != normalized_value:  # NaN
            raise EvidenceError("normalized_value is NaN — handle missing data explicitly")

    claim = redact_text(str(claim), _MAX_CLAIM_CHARS)
    if not claim:
        raise EvidenceError("claim is mandatory")
    value = redact_text(str(value), _MAX_VALUE_CHARS) if value else ""
    provenance = redact_text(str(provenance), 300) if provenance else ""

    raw_hash = hash_raw(raw_evidence)
    identity = "|".join((source_type, source_name, symbol, claim, raw_hash))
    evidence_id = "EV-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]

    now = _dt.datetime.now(_dt.timezone.utc)
    freshness_days = (
        round((now - published).total_seconds() / 86400.0, 3)
        if published is not None
        else None
    )
    return EvidenceItem(
        evidence_id=evidence_id,
        observed_at_utc=observed.isoformat(),
        published_at_utc=published.isoformat() if published else None,
        source_type=source_type,
        source_name=str(source_name).strip(),
        symbol=str(symbol).strip().upper(),
        market=str(market).strip(),
        currency=str(currency).strip().upper(),
        claim=claim,
        value=value,
        normalized_value=normalized_value,
        confidence=confidence,
        freshness_days=freshness_days,
        provenance=provenance,
        extraction_method=str(extraction_method),
        raw_hash=raw_hash,
        advisory_only=True,
    )


def append_evidence(item: EvidenceItem, path: Path | None = None) -> Path:
    """Append one validated item to the JSONL evidence ledger."""
    ledger = path or evidence_ledger_path()
    ledger.parent.mkdir(parents=True, exist_ok=True)
    record = item.to_dict()
    record["advisory_only"] = True  # belt and braces: never persisted false
    with ledger.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True, ensure_ascii=True) + "\n")
    return ledger


def read_ledger(path: Path | None = None) -> list[dict]:
    ledger = path or evidence_ledger_path()
    try:
        lines = ledger.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    return [json.loads(line) for line in lines if line.strip()]


def verify_ledger(path: Path | None = None) -> list[str]:
    """Re-validate every persisted item; returns violations (empty = clean)."""
    violations: list[str] = []
    for idx, record in enumerate(read_ledger(path), start=1):
        if record.get("advisory_only") is not True:
            violations.append(f"item {idx}: advisory_only is not true")
        conf = record.get("confidence")
        if not isinstance(conf, (int, float)) or not (0 <= conf <= 1):
            violations.append(f"item {idx}: confidence {conf!r} outside [0,1]")
        if not record.get("source_name"):
            violations.append(f"item {idx}: missing source")
        if not record.get("observed_at_utc"):
            violations.append(f"item {idx}: missing observed timestamp")
        pub, obs = record.get("published_at_utc"), record.get("observed_at_utc")
        if pub and obs and obs < pub:
            violations.append(f"item {idx}: observed before published")
        for field in ("claim", "value", "provenance"):
            if looks_secret(str(record.get(field, ""))):
                violations.append(f"item {idx}: secret-shaped {field}")
    return violations
