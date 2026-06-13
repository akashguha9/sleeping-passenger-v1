"""Layer 9 — Provenance Ledger (verifiable memory).

Not crypto — the blockchain *concept*: an append-only, hash-chained record of
a thesis's life so scoring can never be rewritten by hindsight.  Each event
links to the previous via a content hash, so any tampering with an earlier
event breaks the chain.

Tracked: first appearance, source/platform, token clusters, threshold
breaches, score changes, interpretation changes, reality confirmations, thesis
breaks, and the final decision.  This supports honest pre/post score deltas and
a *freshness* score that decays as a signal migrates to late beholders / gets
crowded (the hindsight-bias guard).

Determinism: callers pass an integer ``day`` index rather than wall-clock time,
so the ledger is fully reproducible in tests.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .util import clamp, r3

GENESIS_HASH = "0" * 16


def _hash(prev: str, payload: dict[str, Any]) -> str:
    body = prev + json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class ProvenanceEvent:
    seq: int
    day: int
    kind: str
    detail: dict[str, Any]
    prev_hash: str
    hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProvenanceLedger:
    """Append-only hash-chained event log for one signal/thesis."""

    def __init__(self, signal_id: str) -> None:
        self.signal_id = signal_id
        self._events: list[ProvenanceEvent] = []

    def record(self, day: int, kind: str, detail: dict[str, Any] | None = None) -> ProvenanceEvent:
        prev = self._events[-1].hash if self._events else GENESIS_HASH
        seq = len(self._events)
        payload = {"signal_id": self.signal_id, "seq": seq, "day": day,
                   "kind": kind, "detail": detail or {}}
        h = _hash(prev, payload)
        ev = ProvenanceEvent(seq=seq, day=day, kind=kind, detail=detail or {},
                             prev_hash=prev, hash=h)
        self._events.append(ev)
        return ev

    @property
    def events(self) -> list[ProvenanceEvent]:
        return list(self._events)

    def verify_chain(self) -> bool:
        """Recompute the hash chain; any tamper breaks it."""
        prev = GENESIS_HASH
        for ev in self._events:
            payload = {"signal_id": self.signal_id, "seq": ev.seq, "day": ev.day,
                       "kind": ev.kind, "detail": ev.detail}
            if ev.prev_hash != prev or ev.hash != _hash(prev, payload):
                return False
            prev = ev.hash
        return True

    def score_deltas(self) -> list[dict[str, Any]]:
        """Pre/post deltas across every recorded SCORE event."""
        scores = [e for e in self._events if e.kind == "SCORE"]
        out: list[dict[str, Any]] = []
        for a, b in zip(scores, scores[1:]):
            va, vb = a.detail.get("value", 0.0), b.detail.get("value", 0.0)
            out.append({"from_day": a.day, "to_day": b.day,
                        "from": r3(va), "to": r3(vb), "delta": r3(vb - va)})
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "n_events": len(self._events),
            "chain_valid": self.verify_chain(),
            "events": [e.to_dict() for e in self._events],
            "score_deltas": self.score_deltas(),
        }


def freshness_score(
    *,
    age_days: float,
    half_life_days: float,
    interpretation_migration: float,
    price_recognition: float,
    crowding: float,
) -> dict[str, Any]:
    """Provenance freshness — the hindsight-bias / "is it still early?" guard.

    A signal is fresh when it is young relative to its half-life, has migrated
    to few beholder groups, and is neither priced in nor crowded.  Freshness
    decays multiplicatively across those axes.
    """
    half_life_days = max(0.1, half_life_days)
    age_factor = clamp(0.5 ** (age_days / half_life_days))
    spread_factor = clamp(1.0 - interpretation_migration)
    recognition_factor = clamp(1.0 - price_recognition)
    crowd_factor = clamp(1.0 - crowding)
    fresh = clamp(age_factor * (0.4 + 0.6 * spread_factor)
                  * (0.3 + 0.7 * recognition_factor) * (0.5 + 0.5 * crowd_factor))
    reasons: list[str] = []
    if fresh >= 0.6:
        reasons.append("FRESH_EARLY")
    if price_recognition >= 0.7:
        reasons.append("ALREADY_RECOGNIZED")
    if interpretation_migration >= 0.6:
        reasons.append("MEANING_WIDELY_MIGRATED")
    if crowding >= 0.7:
        reasons.append("CROWDED")
    return {
        "score": r3(fresh),
        "age_factor": r3(age_factor),
        "spread_factor": r3(spread_factor),
        "recognition_factor": r3(recognition_factor),
        "crowd_factor": r3(crowd_factor),
        "reason_codes": reasons,
    }


__all__ = [
    "ProvenanceEvent",
    "ProvenanceLedger",
    "freshness_score",
    "GENESIS_HASH",
]
