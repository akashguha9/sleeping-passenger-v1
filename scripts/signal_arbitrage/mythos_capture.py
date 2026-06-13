"""Forward-logging decision capture — manufacture the calibration corpus.

The engine was calibration-READY but the history was feature-less, so it could
never be calibration-PRODUCING.  This module closes that gap: every live / paper
/ advisory decision is captured at decision time as a feature-bearing snapshot
with an unresolved outcome, and resolved later when the realized return is known.

    decision time   -> capture Mythos + Aggregator + Fable + Ledger features
    outcome time    -> attach realized return / thesis result
    calibration time-> run_real_calibration learns from real labelled outcomes

A Decision Snapshot is NOT a competing format: it is a CalibrationRecord
(canonical schema from mythos_corpus) plus metadata/source groups, so
``run_real_calibration`` consumes forward-logged snapshots directly.  Unresolved
snapshots carry ``outcome_label = INCONCLUSIVE`` and are therefore excluded from
calibration until honestly resolved.

Pure + deterministic (integer/string timestamps in; no wall clock).  No network.
Dry-run by default; writes only on ``mode="write"``.  ADVISORY_ONLY; outcomes
are never fabricated; real-money execution is impossible here.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .util import clamp, r3
from .mythos import (
    MythosObservation, observation_quality, classify_governance,
)
from .mythos_aggregator import run_aggregated_pipeline, dedup_observations
from .mythos_corpus import (
    CalibrationRecord, build_calibration_record, SCHEMA,
    PAPER_TRADE, SYNTHETIC_FIXTURE, ELIGIBLE_SOURCE_TYPES,
    WIN, LOSS, BREAKEVEN, AVOIDED_TRAP, MISSED_WINNER, FALSE_POSITIVE,
    FALSE_NEGATIVE, INCONCLUSIVE, _RESOLVED,
)

SCHEMA_VERSION = "1.0"
OPEN_OR_UNRESOLVED = "OPEN_OR_UNRESOLVED"

# Outcome-resolution thresholds (overridable per call; tested as constants).
DEFAULT_TARGET = 0.001    # realized_return above this counts as a winner
DEFAULT_STOP = -0.001     # realized_return below this counts as a loser

_ACT_ACTIONS = frozenset({"ACT_NOW"})
_ALLOWED_LABELS = frozenset({WIN, LOSS, BREAKEVEN, AVOIDED_TRAP, MISSED_WINNER,
                             FALSE_POSITIVE, FALSE_NEGATIVE, INCONCLUSIVE})

# Capture statuses.
CAPTURED_DRY_RUN = "CAPTURED_DRY_RUN"
CAPTURED_WRITTEN = "CAPTURED_WRITTEN"
DUPLICATE_SKIPPED = "DUPLICATE_SKIPPED"
NO_OBSERVATIONS = "NO_OBSERVATIONS"

# Resolution statuses.
RESOLVED = "RESOLVED"
CONFLICT_REJECTED = "CONFLICT_REJECTED"
DECISION_NOT_FOUND = "DECISION_NOT_FOUND"
RESOLUTION_DRY_RUN = "RESOLUTION_DRY_RUN"


# ==========================================================================
# Decision ID
# ==========================================================================
def decision_id_for(observations: list[MythosObservation]) -> str:
    """Stable id: same evidence cluster -> same id; new evidence -> new id.

    decision_id = hash(entity + claim + thesis_id + claim_type
                       + sorted(source_event_ids))   (timestamp-independent)
    """
    deduped = dedup_observations(observations)
    if not deduped:
        return "decision::empty"
    entity = deduped[0].entity
    claim = deduped[0].resolved_claim()
    claim_type = deduped[0].claim_type
    thesis_id = f"{entity}:{claim}"
    event_ids = sorted(f"{o.source.strip().lower()}:{o.day}" for o in deduped)
    blob = "|".join([entity, claim, thesis_id, claim_type, *event_ids])
    h = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
    return f"dec-{h}"


# ==========================================================================
# Capture report
# ==========================================================================
@dataclass
class DecisionCaptureReport:
    status: str
    decision_id: str
    routed_to_fable: bool
    pre_scoring_decision: str
    calibration_eligible: bool
    written: bool
    output_path: str | None
    snapshot: dict[str, Any]
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in (
            "status", "decision_id", "routed_to_fable", "pre_scoring_decision",
            "calibration_eligible", "written", "output_path", "snapshot",
            "advisory_status")}


def _build_snapshot(observations: list[MythosObservation], *,
                    source_type: str, created_at: str,
                    decision_context: dict[str, Any] | None) -> dict[str, Any]:
    deduped = dedup_observations(observations)
    did = decision_id_for(observations)
    pipe = run_aggregated_pipeline(observations)

    # Canonical calibration record (outcome INCONCLUSIVE — never fabricated).
    cr = build_calibration_record(
        cluster=observations, record_id=did,
        ticker=(decision_context or {}).get("ticker", deduped[0].entity if deduped else ""),
        source_type=source_type, realized_return=None,
        opened_at=created_at,
        horizon_days=(decision_context or {}).get("horizon_days", 0))
    snap = cr.to_dict()

    # --- metadata group ---
    snap["schema_version"] = SCHEMA_VERSION
    snap["decision_id"] = did
    snap["record_id"] = did
    snap["created_at"] = created_at
    snap["metadata"] = {
        "schema_version": SCHEMA_VERSION, "decision_id": did, "created_at": created_at,
        "entity": cr.identity["entity"], "ticker": cr.identity["ticker"],
        "claim": cr.identity["claim"], "thesis_id": cr.identity["thesis_id"],
        "claim_type": cr.identity["claim_type"], "source_type": source_type,
        "decision_context": decision_context or {},
        "advisory_status": "ADVISORY_ONLY", "real_money_execution": "PROHIBITED",
    }

    # --- source / observation group ---
    snap["source_observation"] = {
        "n_observations": len(deduped),
        "source_records": [f"{o.source}:{o.day}" for o in deduped],
        "sources": [o.source for o in deduped],
        "source_types": [classify_governance(o)["governance_type"] for o in deduped],
        "timestamps": [o.day for o in deduped],
        "claim_texts": [o.resolved_claim() for o in deduped],
        "governance_types": [classify_governance(o)["governance_type"] for o in deduped],
        "observation_quality_scores": [observation_quality(o)["observation_quality_score"]
                                       for o in deduped],
    }

    # --- routing / Fable presence ---
    snap["routed_to_fable"] = pipe["routed_to_fable"]
    snap["pre_scoring_decision"] = pipe["pre_scoring_decision"]
    snap["mythos"]["route_recommendation"] = pipe["pre_scoring_decision"]
    snap["mythos"]["strategy_eligibility"] = pipe["pre_scoring_decision"]
    snap["aggregation"]["corroboration_adjusted"] = cr.aggregation.get("corroboration_score")
    snap["aggregation"]["aggregation_route"] = pipe["pre_scoring_decision"]

    captured_confidence = None
    if pipe["routed_to_fable"] and pipe.get("capped_confidence") is not None:
        captured_confidence = pipe["capped_confidence"]
    else:
        # null-safe Fable group + block reason
        snap["fable"].setdefault("routed_to_fable", False)
        snap["fable"]["block_reason"] = pipe["pre_scoring_decision"]
        snap["fable"]["recommended_next_module"] = pipe.get("recommended_next_module")
    snap["captured_confidence"] = captured_confidence
    snap["mythos_confidence_cap"] = pipe["mythos_confidence_cap"]

    # --- outcome placeholder (unresolved) ---
    snap["outcome"]["final_outcome_status"] = OPEN_OR_UNRESOLVED
    snap["outcome"]["resolved_at"] = None
    snap["outcome_audit"] = []
    snap["calibratable"] = False  # never eligible until resolved
    return snap


def append_decision_snapshot(path: str | Path, snapshot: dict[str, Any], *,
                             dedup: bool = True, mode: str = "write") -> bool:
    """Append one snapshot as a JSONL line.  Returns True if written.

    dedup skips a snapshot whose ``decision_id`` already exists.  dry_run never
    writes.  Old records remain readable (append-only)."""
    p = Path(path)
    if dedup and p.exists():
        existing = set()
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                existing.add(json.loads(line).get("decision_id"))
            except Exception:
                continue
        if snapshot.get("decision_id") in existing:
            return False
    if mode != "write":
        return False
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(snapshot, sort_keys=True) + "\n")
    return True


def capture_decision_snapshot(
    observations: list[MythosObservation], output_path: str | None = None,
    mode: str = "dry_run", decision_context: dict[str, Any] | None = None, *,
    source_type: str = PAPER_TRADE, created_at: str = "",
) -> DecisionCaptureReport:
    """Capture a feature-bearing decision snapshot (unresolved outcome).

    dry_run (default) returns the snapshot without writing.  write mode appends
    to a JSONL corpus, deduped by decision_id."""
    if not observations:
        return DecisionCaptureReport(
            status=NO_OBSERVATIONS, decision_id="decision::empty", routed_to_fable=False,
            pre_scoring_decision="NONE", calibration_eligible=False, written=False,
            output_path=None, snapshot={})

    snap = _build_snapshot(observations, source_type=source_type,
                           created_at=created_at, decision_context=decision_context)
    did = snap["decision_id"]

    written = False
    status = CAPTURED_DRY_RUN
    if mode == "write" and output_path is not None:
        written = append_decision_snapshot(output_path, snap, dedup=True, mode="write")
        status = CAPTURED_WRITTEN if written else DUPLICATE_SKIPPED

    return DecisionCaptureReport(
        status=status, decision_id=did, routed_to_fable=snap["routed_to_fable"],
        pre_scoring_decision=snap["pre_scoring_decision"],
        calibration_eligible=False,  # unresolved
        written=written, output_path=(output_path if written else None), snapshot=snap)


# ==========================================================================
# Outcome resolution
# ==========================================================================
@dataclass
class OutcomeResolutionReport:
    status: str
    decision_id: str
    prior_label: str
    new_label: str
    calibration_eligible: bool
    written: bool
    output_path: str | None
    audit: list[dict[str, Any]] = field(default_factory=list)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in (
            "status", "decision_id", "prior_label", "new_label",
            "calibration_eligible", "written", "output_path", "audit",
            "advisory_status")}


def derive_outcome_label(snapshot: dict[str, Any], outcome_update: dict[str, Any], *,
                         target: float = DEFAULT_TARGET, stop: float = DEFAULT_STOP) -> str:
    """Derive an outcome label — NEVER guessed.  Unknown -> INCONCLUSIVE.

    The label depends on whether the system ENGAGED (routed to Fable) or
    AVOIDED: a negative return after an avoid is an AVOIDED_TRAP (correct), a
    positive return after an avoid is a MISSED_WINNER (wrong)."""
    explicit = outcome_update.get("outcome_label")
    if explicit in _ALLOWED_LABELS:
        return explicit
    rr = outcome_update.get("realized_return")
    if rr is None:
        # thesis flags alone can confirm/disconfirm without a return number
        if outcome_update.get("thesis_confirmed"):
            return WIN
        if outcome_update.get("thesis_disconfirmed"):
            return LOSS
        return INCONCLUSIVE

    engaged = bool(snapshot.get("routed_to_fable"))
    action = (snapshot.get("fable", {}) or {}).get("recommended_action")
    if engaged:
        if rr >= target:
            return WIN
        if rr <= stop:
            return FALSE_POSITIVE if action in _ACT_ACTIONS else LOSS
        return BREAKEVEN
    # avoided / blocked before scoring
    if rr <= stop:
        return AVOIDED_TRAP
    if rr >= target:
        return MISSED_WINNER
    return INCONCLUSIVE


def _load_snapshots(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def resolve_decision_outcome(
    decisions_path: str, decision_id: str, outcome_update: dict[str, Any],
    output_path: str | None = None, mode: str = "dry_run", *,
    allow_conflict: bool = False, resolved_at: str = "",
) -> OutcomeResolutionReport:
    """Attach a realized outcome to a captured decision snapshot.

    Preserves the original feature snapshot; mutates only the outcome group and
    appends an audit entry.  Conflicting re-resolution is rejected unless
    ``allow_conflict``.  dry_run never writes."""
    path = Path(decisions_path)
    snaps = _load_snapshots(path)
    idx = next((i for i, s in enumerate(snaps) if s.get("decision_id") == decision_id), None)
    if idx is None:
        return OutcomeResolutionReport(
            status=DECISION_NOT_FOUND, decision_id=decision_id, prior_label="",
            new_label="", calibration_eligible=False, written=False, output_path=None)

    snap = snaps[idx]
    prior_label = snap.get("outcome", {}).get("outcome_label", INCONCLUSIVE)
    new_label = derive_outcome_label(
        snap, outcome_update,
        target=outcome_update.get("target_threshold", DEFAULT_TARGET),
        stop=outcome_update.get("stop_threshold", DEFAULT_STOP))

    # Conflict guard: an already-resolved snapshot may not be silently changed.
    if (prior_label in _RESOLVED and prior_label != new_label and not allow_conflict):
        return OutcomeResolutionReport(
            status=CONFLICT_REJECTED, decision_id=decision_id, prior_label=prior_label,
            new_label=new_label, calibration_eligible=False, written=False,
            output_path=None, audit=snap.get("outcome_audit", []))

    # Apply: mutate only the outcome group, preserve features.
    rr = outcome_update.get("realized_return")
    outcome = snap.setdefault("outcome", {})
    outcome["outcome_label"] = new_label
    outcome["realized_return"] = rr
    for k in ("max_drawdown", "max_runup", "hit_target", "hit_stop",
              "thesis_confirmed", "thesis_disconfirmed", "time_to_confirmation",
              "time_to_failure"):
        if k in outcome_update:
            outcome[k] = outcome_update[k]
    outcome["final_outcome_status"] = new_label
    outcome["resolved_at"] = resolved_at or None

    audit = snap.setdefault("outcome_audit", [])
    audit.append({"resolved_at": resolved_at or None, "prior_label": prior_label,
                  "new_label": new_label, "realized_return": rr})

    eligible = bool(snap.get("feature_bearing")
                    and new_label in _RESOLVED
                    and snap.get("source_type") in ELIGIBLE_SOURCE_TYPES)
    snap["calibratable"] = eligible

    written = False
    out_path = output_path or decisions_path
    if mode == "write":
        snaps[idx] = snap
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as fh:
            for s in snaps:
                fh.write(json.dumps(s, sort_keys=True) + "\n")
        written = True
        status = RESOLVED
    else:
        status = RESOLUTION_DRY_RUN

    return OutcomeResolutionReport(
        status=status, decision_id=decision_id, prior_label=prior_label,
        new_label=new_label, calibration_eligible=eligible, written=written,
        output_path=(out_path if written else None), audit=audit)


__all__ = [
    "capture_decision_snapshot", "append_decision_snapshot",
    "resolve_decision_outcome", "derive_outcome_label", "decision_id_for",
    "DecisionCaptureReport", "OutcomeResolutionReport",
    "SCHEMA_VERSION", "OPEN_OR_UNRESOLVED", "DEFAULT_TARGET", "DEFAULT_STOP",
    "CAPTURED_DRY_RUN", "CAPTURED_WRITTEN", "DUPLICATE_SKIPPED", "NO_OBSERVATIONS",
    "RESOLVED", "CONFLICT_REJECTED", "DECISION_NOT_FOUND", "RESOLUTION_DRY_RUN",
]
