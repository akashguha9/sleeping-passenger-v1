"""Derived Score Ledger — every model output, chained and evidence-linked.

Pass 5 ledgered the INPUTS; this ledgers the OUTPUTS. Every derived
score is an append-only, hash-chained record that links back to the
evidence ids it was computed from — or is forced to say
``NO_EVIDENCE_ABSTAIN`` and stored as an abstain/research note.

Chain (same construction as the audit log, test-pinned)::

    event_hash_n = SHA256(canonical_json(record minus event_hash)
                          || previous_hash_n)
    previous_hash_0 = "0" * 64

Rules (test-pinned):
  * execution/order/broker-shaped fields are REFUSED outright;
  * a score with no evidence ids becomes ``NO_EVIDENCE_ABSTAIN`` —
    abstention forced, stored as a research note;
  * missing/invalid temporal validity caps confidence at 0.4;
  * missing grounding status is recorded as ``ungrounded_legacy``;
  * advisory_only and human_review_required are always true;
  * no raw secrets, no copyrighted bodies (claims live in the evidence
    ledger; this ledger stores ids and numbers).

Path: ``runtime/derived_score_ledger.jsonl``
(``MVP_DERIVED_SCORE_LEDGER_PATH`` override; gitignored).
Verifier: ``scripts/verify_derived_score_ledger.py`` (readiness-gated).
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import threading
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
GENESIS_HASH = "0" * 64
_LOCK = threading.Lock()

NO_EVIDENCE_ABSTAIN = "NO_EVIDENCE_ABSTAIN"
_FORBIDDEN_FIELDS = (
    "order_id", "order", "broker", "broker_id", "execution_status",
    "fill_price", "filled_quantity", "order_type", "venue", "account_id",
    "executed", "execution_id",
)
_TEMPORAL_CONFIDENCE_CAP = 0.4


class ScoreLedgerError(ValueError):
    """Raised when a record violates the ledger contract."""


def ledger_path() -> Path:
    raw = os.environ.get("MVP_DERIVED_SCORE_LEDGER_PATH", "").strip()
    return Path(raw) if raw else _REPO_ROOT / "runtime" / "derived_score_ledger.jsonl"


def canonical_json(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def compute_hash(record_without_hash: dict, previous_hash: str) -> str:
    return hashlib.sha256(
        (canonical_json(record_without_hash) + previous_hash).encode("utf-8")
    ).hexdigest()


def _last_hash(path: Path) -> str:
    try:
        last = b""
        with path.open("rb") as fh:
            for line in fh:
                if line.strip():
                    last = line
        if not last:
            return GENESIS_HASH
        return json.loads(last.decode("utf-8")).get("event_hash", GENESIS_HASH)
    except (FileNotFoundError, OSError, json.JSONDecodeError, UnicodeDecodeError):
        return GENESIS_HASH


def append_score(
    *,
    model_name: str,
    model_version: str,
    symbol: str,
    raw_score: float,
    decision_time_utc: str,
    input_evidence_ids: list[str] | None = None,
    feature_values: dict | None = None,
    feature_weights: dict | None = None,
    calibrated_probability: float | None = None,
    confidence: float = 0.5,
    abstain: bool = False,
    temporal_validity: str = "unknown",
    grounding_status: str = "ungrounded_legacy",
    sensitivity_warning: str = "",
    score_explanation_path: str = "",
    decision_memo_path: str = "",
    path: Path | None = None,
    **extra,
) -> dict:
    """Validate + append one derived score record; returns it."""
    for key in list(extra) + list((feature_values or {})):
        lk = str(key).lower()
        if any(f == lk or f in lk for f in _FORBIDDEN_FIELDS):
            raise ScoreLedgerError(
                f"field {key!r} is execution/order/broker-shaped — the score "
                "ledger records advisory analysis, never anything an order "
                "could be built from"
            )
    if extra:
        raise ScoreLedgerError(f"unknown fields refused: {sorted(extra)}")

    evidence_ids = [str(e) for e in (input_evidence_ids or []) if str(e).strip()]
    if not evidence_ids:
        # No evidence → forced abstention, stored as a research note.
        abstain = True
        grounding_status = NO_EVIDENCE_ABSTAIN
    if not (0.0 <= float(confidence) <= 1.0):
        raise ScoreLedgerError(f"confidence {confidence} outside [0,1]")
    if calibrated_probability is not None and not (0.0 <= calibrated_probability <= 1.0):
        raise ScoreLedgerError(f"calibrated_probability outside [0,1]")
    if temporal_validity not in ("valid", "overridden"):
        confidence = min(float(confidence), _TEMPORAL_CONFIDENCE_CAP)

    with _LOCK:
        target = path or ledger_path()
        previous_hash = _last_hash(target)
        record = {
            "generated_at_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "model_name": str(model_name),
            "model_version": str(model_version),
            "symbol": str(symbol).upper(),
            "decision_time_utc": str(decision_time_utc),
            "input_evidence_ids": sorted(evidence_ids),
            "feature_values": feature_values or {},
            "feature_weights": feature_weights or {},
            "raw_score": float(raw_score),
            "calibrated_probability": calibrated_probability,
            "confidence": round(float(confidence), 6),
            "abstain": bool(abstain),
            "temporal_validity": str(temporal_validity),
            "grounding_status": str(grounding_status),
            "sensitivity_warning": str(sensitivity_warning)[:200],
            "score_explanation_path": str(score_explanation_path),
            "decision_memo_path": str(decision_memo_path),
            "advisory_only": True,
            "human_review_required": True,
            "previous_hash": previous_hash,
        }
        record["score_id"] = "DS-" + hashlib.sha256(
            f"{record['model_name']}|{record['symbol']}|"
            f"{record['decision_time_utc']}|{record['raw_score']}".encode("utf-8")
        ).hexdigest()[:20]
        record["event_hash"] = compute_hash(
            {k: v for k, v in record.items() if k != "event_hash"}, previous_hash
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(canonical_json(record) + "\n")
        return record


def read_ledger(path: Path | None = None) -> list[dict]:
    target = path or ledger_path()
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    return [json.loads(line) for line in lines if line.strip()]


def verify_chain(path: Path | None = None) -> dict:
    """Same contract as the audit-log verifier: errors = tamper/contract."""
    target = path or ledger_path()
    errors: list[str] = []
    expected_previous = GENESIS_HASH
    count = 0
    try:
        raw_lines = [l for l in target.read_text(encoding="utf-8").splitlines()
                     if l.strip()]
    except FileNotFoundError:
        raw_lines = []
    records = []
    for lineno, line in enumerate(raw_lines, start=1):
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            errors.append(f"line {lineno}: invalid JSON — record corrupted")
            records.append(None)
    for lineno, record in enumerate(records, start=1):
        if record is None:
            expected_previous = ""  # chain unverifiable past corruption
            continue
        count += 1
        if record.get("advisory_only") is not True:
            errors.append(f"line {lineno}: advisory_only not true")
        if record.get("human_review_required") is not True:
            errors.append(f"line {lineno}: human_review_required not true")
        if not record.get("input_evidence_ids") and (
            not record.get("abstain")
            or record.get("grounding_status") != NO_EVIDENCE_ABSTAIN
        ):
            errors.append(f"line {lineno}: evidence-free score not marked "
                          f"{NO_EVIDENCE_ABSTAIN}/abstain")
        for key in record:
            lk = str(key).lower()
            if any(f == lk or f in lk for f in _FORBIDDEN_FIELDS):
                errors.append(f"line {lineno}: execution-shaped field {key!r}")
        if record.get("previous_hash") != expected_previous:
            errors.append(f"line {lineno}: broken chain")
        recomputed = compute_hash(
            {k: v for k, v in record.items() if k != "event_hash"},
            record.get("previous_hash", ""),
        )
        if recomputed != record.get("event_hash"):
            errors.append(f"line {lineno}: event_hash mismatch — record modified")
        expected_previous = record.get("event_hash", "")
    return {"valid": not errors, "records": count, "errors": errors}
