"""Persistent Mythos reality-check ledger.

Closes the loop's memory: Mythos interprets -> Fable scores -> *ledger
remembers* -> reality checks update confidence across runs.

Each claim is durable JSON on disk and carries a hash-chained
``ProvenanceLedger`` (reused verbatim) for integrity.  The chain is
reconstructed by *replaying* the stored (day, kind, detail) inputs — since
``ProvenanceLedger.record`` recomputes hashes deterministically, a replay
reproduces identical hashes, so we reuse the existing ledger without modifying
it and still get tamper-evidence.

Determinism: callers pass integer ``day`` values (no wall clock).  The store
only touches disk through the explicit ``path`` it is given.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .util import clamp, r3
from .provenance import ProvenanceLedger
from .mythos import apply_trust, derive_claim_status

_DEFAULT_WINDOW = 30


def claim_id_for(entity: str, claim: str) -> str:
    """Stable id for a thesis (entity + claim text)."""
    h = hashlib.sha256(f"{entity}::{claim}".encode("utf-8")).hexdigest()[:12]
    return f"{entity}:{h}"


@dataclass
class MythosClaim:
    claim_id: str
    entity: str
    claim: str
    interpretation: str
    governance: str
    prior_confidence: float
    confidence: float
    status: str
    survival_count: int
    contradiction_count: int
    first_seen_day: int
    expected_check_day: int          # validation window deadline
    last_update_day: int
    validation_window: int = _DEFAULT_WINDOW
    # input events replayed to rebuild the hash chain (no hashes stored here)
    events: list[dict[str, Any]] = field(default_factory=list)
    # ids of evidence already applied — guards against double-counting on rerun
    applied_event_ids: list[str] = field(default_factory=list)

    # ---- hash-chain integrity (reuse ProvenanceLedger) ----
    def ledger(self) -> ProvenanceLedger:
        led = ProvenanceLedger(self.claim_id)
        for ev in self.events:
            led.record(ev["day"], ev["kind"], ev.get("detail", {}))
        return led

    def chain_valid(self) -> bool:
        return self.ledger().verify_chain()

    def head_hash(self) -> str:
        led = self.ledger()
        return led.events[-1].hash if led.events else "0" * 16

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id, "entity": self.entity, "claim": self.claim,
            "interpretation": self.interpretation, "governance": self.governance,
            "prior_confidence": r3(self.prior_confidence),
            "confidence": r3(self.confidence), "status": self.status,
            "survival_count": self.survival_count,
            "contradiction_count": self.contradiction_count,
            "first_seen_day": self.first_seen_day,
            "expected_check_day": self.expected_check_day,
            "next_reality_check": self.expected_check_day,
            "last_update_day": self.last_update_day,
            "validation_window": self.validation_window,
            "events": self.events,
            "applied_event_ids": self.applied_event_ids,
            "chain_valid": self.chain_valid(),
            "head_hash": self.head_hash(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MythosClaim":
        return cls(
            claim_id=d["claim_id"], entity=d["entity"], claim=d["claim"],
            interpretation=d["interpretation"], governance=d["governance"],
            prior_confidence=d["prior_confidence"], confidence=d["confidence"],
            status=d["status"], survival_count=d["survival_count"],
            contradiction_count=d["contradiction_count"],
            first_seen_day=d["first_seen_day"],
            expected_check_day=d["expected_check_day"],
            last_update_day=d.get("last_update_day", d["first_seen_day"]),
            validation_window=d.get("validation_window", _DEFAULT_WINDOW),
            events=list(d.get("events", [])),
            applied_event_ids=list(d.get("applied_event_ids", [])),
        )


class MythosLedgerStore:
    """Durable, hash-chained claim store keyed by claim_id."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._claims: dict[str, MythosClaim] = {}
        if self.path is not None and self.path.exists():
            self.load()

    # ---- persistence ----
    def load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding="utf-8") or "{}")
        self._claims = {cid: MythosClaim.from_dict(c) for cid, c in data.items()}

    def save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {cid: c.to_dict() for cid, c in self._claims.items()}
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    # ---- claim lifecycle ----
    def get(self, claim_id: str) -> MythosClaim | None:
        return self._claims.get(claim_id)

    def all_claims(self) -> list[MythosClaim]:
        return [self._claims[k] for k in sorted(self._claims)]

    def upsert_claim(self, *, entity: str, claim: str, interpretation: str,
                     governance: str, prior_confidence: float, day: int,
                     validation_window: int = _DEFAULT_WINDOW) -> MythosClaim:
        """Create a claim on first sighting, or return the persisted one.

        First sighting records FIRST_SEEN + SCORE provenance events and opens a
        validation window.  A re-sighting does NOT reset accumulated evidence —
        it only refreshes the interpretation snapshot.
        """
        cid = claim_id_for(entity, claim)
        existing = self._claims.get(cid)
        if existing is not None:
            existing.interpretation = interpretation
            existing.last_update_day = day
            return existing
        rec = MythosClaim(
            claim_id=cid, entity=entity, claim=claim, interpretation=interpretation,
            governance=governance, prior_confidence=clamp(prior_confidence),
            confidence=clamp(prior_confidence),
            status=derive_claim_status(survival=0, contradiction=0,
                                       prior_conf=prior_confidence,
                                       governance_type=governance),
            survival_count=0, contradiction_count=0, first_seen_day=day,
            expected_check_day=day + validation_window, last_update_day=day,
            validation_window=validation_window,
        )
        rec.events.append({"day": day, "kind": "FIRST_SEEN",
                           "detail": {"governance": governance,
                                      "interpretation": interpretation}})
        rec.events.append({"day": day, "kind": "SCORE",
                           "detail": {"value": r3(rec.confidence), "status": rec.status}})
        self._claims[cid] = rec
        return rec

    def apply_evidence(self, claim_id: str, *, day: int, supports: bool,
                       weight: float = 0.5, independent: float = 0.5,
                       note: str = "", event_id: str | None = None) -> MythosClaim:
        """Apply a confirming/contradicting reality-check event across runs.

        If ``event_id`` is supplied and already applied to this claim, the call
        is a no-op — so replaying the same feed on a rerun never double-counts.
        """
        rec = self._claims[claim_id]
        if event_id is not None and event_id in rec.applied_event_ids:
            return rec
        if event_id is not None:
            rec.applied_event_ids.append(event_id)
        rec.confidence = apply_trust(rec.confidence, supports, weight, independent)
        if supports:
            rec.survival_count += 1
        else:
            rec.contradiction_count += 1
        window_overdue = day > rec.expected_check_day and rec.survival_count == 0
        rec.status = derive_claim_status(
            survival=rec.survival_count, contradiction=rec.contradiction_count,
            prior_conf=rec.prior_confidence, governance_type=rec.governance,
            window_overdue=window_overdue)
        rec.last_update_day = day
        # A confirming check extends the window; a contradiction keeps it.
        if supports:
            rec.expected_check_day = day + _DEFAULT_WINDOW
        rec.events.append({"day": day, "kind": "EVIDENCE",
                           "detail": {"supports": supports, "weight": r3(clamp(weight)),
                                      "independent": r3(clamp(independent)), "note": note}})
        rec.events.append({"day": day, "kind": "SCORE",
                           "detail": {"value": r3(rec.confidence), "status": rec.status}})
        return rec

    def check_windows(self, current_day: int) -> list[MythosClaim]:
        """Sweep all claims; mark overdue-unconfirmed ones STALE/CONTESTED.

        Returns the claims whose status changed."""
        changed: list[MythosClaim] = []
        for rec in self._claims.values():
            if rec.status in ("HIGH_CONFIDENCE", "SUPPORTED", "DISCONFIRMED"):
                continue
            if current_day > rec.expected_check_day and rec.survival_count == 0:
                new_status = derive_claim_status(
                    survival=rec.survival_count, contradiction=rec.contradiction_count,
                    prior_conf=rec.prior_confidence, governance_type=rec.governance,
                    window_overdue=True)
                if new_status != rec.status:
                    rec.status = new_status
                    rec.confidence = clamp(rec.confidence - 0.1)
                    rec.last_update_day = current_day
                    rec.events.append({"day": current_day, "kind": "WINDOW_MISSED",
                                       "detail": {"status": new_status}})
                    changed.append(rec)
        return changed


__all__ = ["MythosClaim", "MythosLedgerStore", "claim_id_for"]
