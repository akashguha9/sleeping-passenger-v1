"""Temporal belief revision — an append-only belief timeline.

Markets evolve after the initial signal. A Decision Twin's ORIGINAL prediction is
immutable, but new evidence can arrive; each arrival produces an append-only
`BeliefRevision` (never an overwrite). This lets the system detect overreaction,
underreaction, excessive churn, and failure-to-update — learning about its own
belief dynamics, not just prices.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

try:
    from scripts.advisory_contract import advisory_safety_stamps
except ModuleNotFoundError:  # pragma: no cover
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]


def _hash(payload: Any) -> str:
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class BeliefRevision:
    revision_id: str
    twin_id: str
    seq: int                       # monotonic within a twin (append-only order)
    prior_state: str
    revised_state: str
    prior_confidence: float
    revised_confidence: float
    evidence_arrival: str          # what new evidence triggered this
    reason: str
    days_since_signal: float
    information_gain: float         # 0..1 magnitude of belief change
    expected: bool                 # was the change anticipated?
    contradicts_thesis: bool
    revision_class: str            # CORRECT_UPDATE / OVERREACTION / UNDERREACTION / CHURN / NO_UPDATE
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__slots__}


def revise(
    twin_id: str,
    seq: int,
    prior_state: str,
    revised_state: str,
    prior_conf: float,
    revised_conf: float,
    *,
    evidence_arrival: str,
    days_since_signal: float,
    expected: bool = False,
    contradicts_thesis: bool = False,
    reason: str = "",
) -> BeliefRevision:
    conf_change = abs(revised_conf - prior_conf)
    state_changed = prior_state != revised_state
    info_gain = min(1.0, conf_change + (0.4 if state_changed else 0.0))

    # Classify the revision dynamics.
    if not state_changed and conf_change < 0.05:
        rclass = "NO_UPDATE"
    elif conf_change >= 0.5 or (state_changed and conf_change >= 0.35):
        rclass = "OVERREACTION" if not expected else "CORRECT_UPDATE"
    elif contradicts_thesis and conf_change < 0.1:
        rclass = "UNDERREACTION"
    elif state_changed and conf_change < 0.15:
        rclass = "CHURN"
    else:
        rclass = "CORRECT_UPDATE"

    core = {"twin_id": twin_id, "seq": seq, "prior": prior_state,
            "revised": revised_state, "evidence": evidence_arrival}
    rid = "REV_" + hashlib.sha256(f"{twin_id}|{seq}".encode()).hexdigest()[:12]
    return BeliefRevision(
        revision_id=rid, twin_id=twin_id, seq=seq, prior_state=prior_state,
        revised_state=revised_state, prior_confidence=round(prior_conf, 4),
        revised_confidence=round(revised_conf, 4), evidence_arrival=evidence_arrival,
        reason=reason or f"evidence: {evidence_arrival}",
        days_since_signal=round(days_since_signal, 2),
        information_gain=round(info_gain, 4), expected=expected,
        contradicts_thesis=contradicts_thesis, revision_class=rclass,
        content_hash=_hash(core))


def analyse_timeline(revisions: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarise belief dynamics over an append-only timeline (read-only)."""
    if not revisions:
        return {"report": "belief_timeline", "n": 0, "churn": 0.0,
                "overreactions": 0, "underreactions": 0, "no_updates": 0,
                **advisory_safety_stamps()}
    classes = [r.get("revision_class") for r in revisions]
    total_gain = sum(float(r.get("information_gain", 0) or 0) for r in revisions)
    state_changes = sum(1 for r in revisions if r.get("prior_state") != r.get("revised_state"))
    out = {
        "report": "belief_timeline", "n": len(revisions),
        "churn": round(state_changes / len(revisions), 4),
        "total_information_gain": round(total_gain, 4),
        "overreactions": classes.count("OVERREACTION"),
        "underreactions": classes.count("UNDERREACTION"),
        "no_updates": classes.count("NO_UPDATE"),
        "correct_updates": classes.count("CORRECT_UPDATE"),
    }
    out.update(advisory_safety_stamps())
    return out


__all__ = ["BeliefRevision", "revise", "analyse_timeline"]
