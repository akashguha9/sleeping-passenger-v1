"""Quant hackathon — append-only research ledger (mission 48).

Every experiment is recorded with hypothesis, data range, config, result,
sample size, and conclusion so results cannot be hindsight-rewritten.
Entries are content-hashed and chained (each entry stores the previous
entry's hash) — editing history breaks the chain verifiably.

Ledger path: data/calibration_corpus/research_ledger.jsonl
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

LEDGER_DEFAULT = Path("data/calibration_corpus/research_ledger.jsonl")

ACCEPTED = "ACCEPTED"
REJECTED = "REJECTED"
INCONCLUSIVE = "INCONCLUSIVE"
BLOCKED_BY_DATA = "BLOCKED_BY_DATA"
_VALID = (ACCEPTED, REJECTED, INCONCLUSIVE, BLOCKED_BY_DATA)


def _hash(obj: Any) -> str:
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def record_experiment(*, experiment_id: str, hypothesis: str,
                      data_range: str, features: list[str], target: str,
                      config: dict[str, Any], result: dict[str, Any],
                      n: int, conclusion: str, verdict: str,
                      run_date: str,
                      ledger_path: Path = LEDGER_DEFAULT) -> dict[str, Any]:
    """Append one experiment.  Verdict must be one of the four honest states."""
    if verdict not in _VALID:
        raise ValueError(f"verdict must be one of {_VALID}, got {verdict!r}")
    prev_hash = None
    if ledger_path.exists():
        lines = [l for l in
                 ledger_path.read_text(encoding="utf-8").splitlines()
                 if l.strip()]
        if lines:
            prev_hash = json.loads(lines[-1]).get("entry_hash")
    entry = {
        "experiment_id": experiment_id, "run_date": run_date,
        "hypothesis": hypothesis, "data_range": data_range,
        "features": features, "target": target, "config": config,
        "n": n, "result_summary": result, "conclusion": conclusion,
        "verdict": verdict, "prev_hash": prev_hash,
    }
    entry["entry_hash"] = _hash(entry)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, default=str) + "\n")
    return entry


def verify_ledger(ledger_path: Path = LEDGER_DEFAULT) -> dict[str, Any]:
    """Verify the hash chain; a broken chain means history was edited."""
    if not ledger_path.exists():
        return {"status": "EMPTY", "entries": 0}
    entries = [json.loads(l) for l in
               ledger_path.read_text(encoding="utf-8").splitlines()
               if l.strip()]
    prev = None
    for i, e in enumerate(entries):
        stored = e.get("entry_hash")
        body = {k: v for k, v in e.items() if k != "entry_hash"}
        if _hash(body) != stored:
            return {"status": "CHAIN_BROKEN", "at_index": i,
                    "entries": len(entries)}
        if e.get("prev_hash") != prev:
            return {"status": "CHAIN_BROKEN", "at_index": i,
                    "entries": len(entries), "reason": "prev_hash mismatch"}
        prev = stored
    return {"status": "INTACT", "entries": len(entries)}
