"""Canonical decision ledger.

Decisions written here are the *final*, *honest* record of what the
pipeline concluded — including every veto, the policy state, the
position integrity state, the evidence snapshot hash, and the canonical
action permission.

This ledger is intentionally easy to audit:

    * Every record serialises to a deterministic JSON object.
    * Records can be persisted as JSONL for replay or simply held in
      memory for tests.
    * No record can be silently mutated; updates require a new record.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from scripts.runtime_contracts import (
        ActionPermission,
        DecisionRecord,
        EvidenceLedgerSummary,
        PolicyState,
        PositionIntegrityState,
        SystemMode,
        TruthOrigin,
        VetoReason,
        coerce_policy_state,
        coerce_position_state,
        coerce_system_mode,
        coerce_truth_origin,
    )
except ModuleNotFoundError:  # pragma: no cover
    from runtime_contracts import (  # type: ignore[no-redef]
        ActionPermission,
        DecisionRecord,
        EvidenceLedgerSummary,
        PolicyState,
        PositionIntegrityState,
        SystemMode,
        TruthOrigin,
        VetoReason,
        coerce_policy_state,
        coerce_position_state,
        coerce_system_mode,
        coerce_truth_origin,
    )


def _coerce_action_permission(value: Any) -> ActionPermission:
    if isinstance(value, ActionPermission):
        return value
    text = str(value or "").strip().upper()
    try:
        return ActionPermission(text)
    except ValueError:
        return ActionPermission.BLOCK_CAPITAL


def _coerce_veto_reason(value: Any) -> VetoReason | None:
    if isinstance(value, VetoReason):
        return value
    text = str(value or "").strip().upper()
    if not text:
        return None
    try:
        return VetoReason(text)
    except ValueError:
        return None


def _coerce_veto_reasons(values: Iterable[Any]) -> tuple[VetoReason, ...]:
    seen: list[VetoReason] = []
    for value in values:
        reason = _coerce_veto_reason(value)
        if reason and reason not in seen:
            seen.append(reason)
    return tuple(seen)


def _hash_evidence_snapshot(snapshot: Any) -> str:
    if snapshot is None:
        return ""
    if isinstance(snapshot, EvidenceLedgerSummary):
        snapshot = snapshot.to_dict()
    payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def build_decision_record(
    *,
    decision_id: str,
    canonical_action_permission: ActionPermission | str,
    veto_reasons: Iterable[VetoReason | str],
    policy_state: PolicyState | str,
    position_integrity_state: PositionIntegrityState | str,
    truth_origin: TruthOrigin | str,
    system_mode: SystemMode | str = SystemMode.UNKNOWN,
    state_archetype: str = "UNKNOWN",
    explanation: str = "",
    evidence_snapshot: Any = None,
    evidence_ledger_summary: EvidenceLedgerSummary | None = None,
    timestamp: str | None = None,
    extra: dict[str, Any] | None = None,
) -> DecisionRecord:
    """Construct a typed, deterministic DecisionRecord.

    The ``evidence_snapshot`` is hashed deterministically; the raw value
    is not retained in the record so seeded fixtures cannot leak through
    a decision-ledger entry.
    """

    if timestamp is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    snapshot_for_hash: Any
    if evidence_snapshot is None and evidence_ledger_summary is not None:
        snapshot_for_hash = evidence_ledger_summary.to_dict()
    else:
        snapshot_for_hash = evidence_snapshot
    return DecisionRecord(
        decision_id=str(decision_id),
        timestamp=str(timestamp),
        canonical_action_permission=_coerce_action_permission(canonical_action_permission),
        veto_reasons=_coerce_veto_reasons(veto_reasons),
        policy_state=coerce_policy_state(policy_state),
        position_integrity_state=coerce_position_state(position_integrity_state),
        truth_origin=coerce_truth_origin(truth_origin),
        system_mode=coerce_system_mode(system_mode),
        state_archetype=str(state_archetype or "UNKNOWN"),
        explanation=str(explanation or ""),
        evidence_snapshot_hash=_hash_evidence_snapshot(snapshot_for_hash),
        evidence_ledger_summary=evidence_ledger_summary,
        extra=dict(extra or {}),
    )


class DecisionLedger:
    """In-memory canonical decision ledger with JSONL serialisation."""

    def __init__(self) -> None:
        self._records: list[DecisionRecord] = []

    def __len__(self) -> int:  # pragma: no cover - trivial
        return len(self._records)

    @property
    def records(self) -> tuple[DecisionRecord, ...]:
        return tuple(self._records)

    def append(self, record: DecisionRecord) -> DecisionRecord:
        if not isinstance(record, DecisionRecord):
            raise TypeError("DecisionLedger.append expects a DecisionRecord")
        self._records.append(record)
        return record

    def record(
        self,
        *,
        decision_id: str,
        canonical_action_permission: ActionPermission | str,
        veto_reasons: Iterable[VetoReason | str],
        policy_state: PolicyState | str,
        position_integrity_state: PositionIntegrityState | str,
        truth_origin: TruthOrigin | str,
        system_mode: SystemMode | str = SystemMode.UNKNOWN,
        state_archetype: str = "UNKNOWN",
        explanation: str = "",
        evidence_snapshot: Any = None,
        evidence_ledger_summary: EvidenceLedgerSummary | None = None,
        timestamp: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> DecisionRecord:
        return self.append(
            build_decision_record(
                decision_id=decision_id,
                canonical_action_permission=canonical_action_permission,
                veto_reasons=veto_reasons,
                policy_state=policy_state,
                position_integrity_state=position_integrity_state,
                truth_origin=truth_origin,
                system_mode=system_mode,
                state_archetype=state_archetype,
                explanation=explanation,
                evidence_snapshot=evidence_snapshot,
                evidence_ledger_summary=evidence_ledger_summary,
                timestamp=timestamp,
                extra=extra,
            )
        )

    def serialize(self) -> list[dict[str, Any]]:
        return [record.to_dict() for record in self._records]

    def serialize_jsonl(self) -> str:
        return "\n".join(
            json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":"))
            for record in self._records
        )

    def to_jsonl_path(self, path: Path | str) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        text = self.serialize_jsonl()
        if text:
            path.write_text(text + "\n", encoding="utf-8")
        else:
            path.write_text("", encoding="utf-8")
        return path

    def latest(self) -> DecisionRecord | None:
        if not self._records:
            return None
        return self._records[-1]

    def status(self) -> dict[str, Any]:
        latest = self.latest()
        return {
            "decision_count": len(self._records),
            "latest_decision_id": latest.decision_id if latest else None,
            "latest_action_permission": (
                latest.canonical_action_permission.value if latest else None
            ),
            "latest_veto_reasons": (
                [reason.value for reason in latest.veto_reasons] if latest else []
            ),
            "latest_evidence_snapshot_hash": (
                latest.evidence_snapshot_hash if latest else ""
            ),
        }


__all__ = [
    "DecisionLedger",
    "build_decision_record",
]
