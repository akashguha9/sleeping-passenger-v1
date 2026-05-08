"""Canonical runtime contracts for the pipeline spine.

This module defines the typed enums and dataclasses that downstream
modules (evidence ledger, decision ledger, action permission resolver,
calibration honesty layer, state machine, position reconciliation,
truth sources, and the health report) reference as a single source
of truth.

The intent is honesty, not hype. The contracts here are deliberately
strict so it is harder to confuse seeded/demo data with externally
checked truth, harder to claim decision-readiness without calibration,
and harder to deploy capital while position state is divergent or a
chaos veto is active.

These contracts are pure data: no I/O, no global mutation, and they are
deterministic and serialisable so they can be replayed in tests and
audits.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Iterable


class TruthOrigin(str, Enum):
    """Where a piece of evidence or runtime signal actually comes from.

    Rules enforced elsewhere:
        * SEEDED and DEMO never count as external truth.
        * REPLAY counts as external only if outcome labels are attached.
        * LIVE_EXTERNAL is the only origin that unconditionally counts as
          external for capital-permission purposes.
    """

    SEEDED = "SEEDED"
    DEMO = "DEMO"
    REPLAY = "REPLAY"
    REPLAY_LABELED = "REPLAY_LABELED"
    LIVE_EXTERNAL = "LIVE_EXTERNAL"
    UNKNOWN = "UNKNOWN"


class SystemMode(str, Enum):
    """Coarse runtime operating mode."""

    SEEDED = "SEEDED"
    DEMO = "DEMO"
    REPLAY = "REPLAY"
    LIVE = "LIVE"
    UNKNOWN = "UNKNOWN"


class ValidationStatus(str, Enum):
    """How well an evidence record / claim has been validated."""

    UNVALIDATED = "UNVALIDATED"
    SEED_ONLY = "SEED_ONLY"
    REPLAY_REPRODUCED = "REPLAY_REPRODUCED"
    EXTERNALLY_CHECKED = "EXTERNALLY_CHECKED"
    OUTCOME_LABELED = "OUTCOME_LABELED"
    CONTRADICTED = "CONTRADICTED"


class PositionIntegrityState(str, Enum):
    """Canonical state for the position reconciliation contract."""

    UNKNOWN = "UNKNOWN"
    MATCHED = "MATCHED"
    MISSING_SOURCE = "MISSING_SOURCE"
    STALE_SOURCE = "STALE_SOURCE"
    QUANTITY_MISMATCH = "QUANTITY_MISMATCH"
    PRICE_MISMATCH = "PRICE_MISMATCH"
    DIVERGED = "DIVERGED"
    RECONCILED = "RECONCILED"


class PolicyState(str, Enum):
    """Canonical execution-policy state."""

    UNKNOWN = "UNKNOWN"
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    BLOCKED = "BLOCKED"
    DO_NOT_DEPLOY = "DO_NOT_DEPLOY"


class ActionPermission(str, Enum):
    """Canonical action permission output.

    BLOCK_CAPITAL is the strongest negative outcome and is the default
    whenever any blocking veto fires. The system never silently upgrades
    from a weaker permission to a stronger one — every upgrade requires
    an explicit veto-free state plus calibration coverage.
    """

    BLOCK_CAPITAL = "BLOCK_CAPITAL"
    QUARANTINE = "QUARANTINE"
    DEMO_ONLY = "DEMO_ONLY"
    RESEARCH_ONLY = "RESEARCH_ONLY"
    PAPER_TRADING_ONLY = "PAPER_TRADING_ONLY"
    DECISION_SUPPORT_ADVISORY = "DECISION_SUPPORT_ADVISORY"
    DEPLOY_CAPITAL = "DEPLOY_CAPITAL"


class VetoReason(str, Enum):
    """Enumerated, deterministic veto reasons.

    Adding a new reason is a contract change — never reuse an existing
    label for a different meaning.
    """

    NO_EXTERNAL_TRUTH = "NO_EXTERNAL_TRUTH"
    SEEDED_TRUTH_ONLY = "SEEDED_TRUTH_ONLY"
    DEMO_TRUTH_ONLY = "DEMO_TRUTH_ONLY"
    POSITION_DIVERGED = "POSITION_DIVERGED"
    POSITION_UNKNOWN = "POSITION_UNKNOWN"
    POLICY_RESTRICTED = "POLICY_RESTRICTED"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    CHAOS_VETO = "CHAOS_VETO"
    CALIBRATION_MISSING = "CALIBRATION_MISSING"
    CALIBRATION_HEURISTIC = "CALIBRATION_HEURISTIC"
    ARBITRARY_THRESHOLD = "ARBITRARY_THRESHOLD"
    INSUFFICIENT_SAMPLES = "INSUFFICIENT_SAMPLES"
    INTERPRETATION_DISABLED = "INTERPRETATION_DISABLED"
    JAIL_MODE_ACTIVE = "JAIL_MODE_ACTIVE"
    EVIDENCE_CONTAMINATION = "EVIDENCE_CONTAMINATION"


_EXTERNAL_TRUTH_ORIGINS: frozenset[TruthOrigin] = frozenset(
    {TruthOrigin.LIVE_EXTERNAL, TruthOrigin.REPLAY_LABELED}
)


def is_external_truth_origin(origin: TruthOrigin | str) -> bool:
    """Return True iff origin counts as external for capital permission.

    SEEDED, DEMO, REPLAY (without labels), UNKNOWN — all return False.
    Robust to cross-module enum instances: comparison is on .value.
    """

    if isinstance(origin, TruthOrigin):
        return origin in _EXTERNAL_TRUTH_ORIGINS
    if isinstance(origin, Enum):
        text = str(origin.value).strip().upper()
    else:
        text = str(origin or "").strip().upper()
    try:
        coerced = TruthOrigin(text)
    except ValueError:
        return False
    return coerced in _EXTERNAL_TRUTH_ORIGINS


@dataclass(frozen=True)
class EvidenceRecord:
    """A single typed evidence record consumed by the evidence ledger."""

    record_id: str
    truth_origin: TruthOrigin
    source: str
    timestamp: str
    confidence: float
    validation_status: ValidationStatus
    payload_hash: str = ""
    labels: tuple[str, ...] = field(default_factory=tuple)
    notes: str = ""

    def is_external_truth(self) -> bool:
        return is_external_truth_origin(self.truth_origin)

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "truth_origin": self.truth_origin.value,
            "source": self.source,
            "timestamp": self.timestamp,
            "confidence": float(self.confidence),
            "validation_status": self.validation_status.value,
            "payload_hash": self.payload_hash,
            "labels": list(self.labels),
            "notes": self.notes,
        }


@dataclass(frozen=True)
class EvidenceLedgerSummary:
    """Aggregated, deterministic view over an evidence ledger."""

    record_count: int
    external_signal_count: int
    seeded_signal_count: int
    demo_signal_count: int
    replay_signal_count: int
    replay_labeled_signal_count: int
    unknown_signal_count: int
    truth_origin_breakdown: dict[str, int]
    validation_breakdown: dict[str, int]
    source_count: int
    has_external_truth: bool
    warnings: tuple[str, ...]
    payload_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_count": int(self.record_count),
            "external_signal_count": int(self.external_signal_count),
            "seeded_signal_count": int(self.seeded_signal_count),
            "demo_signal_count": int(self.demo_signal_count),
            "replay_signal_count": int(self.replay_signal_count),
            "replay_labeled_signal_count": int(self.replay_labeled_signal_count),
            "unknown_signal_count": int(self.unknown_signal_count),
            "truth_origin_breakdown": dict(self.truth_origin_breakdown),
            "validation_breakdown": dict(self.validation_breakdown),
            "source_count": int(self.source_count),
            "has_external_truth": bool(self.has_external_truth),
            "warnings": list(self.warnings),
            "payload_hash": self.payload_hash,
        }


@dataclass(frozen=True)
class ActionPermissionResult:
    """Output of resolve_action_permission()."""

    canonical_action_permission: ActionPermission
    veto_reasons: tuple[VetoReason, ...]
    warnings: tuple[str, ...]
    allowed_use: tuple[str, ...]
    forbidden_use: tuple[str, ...]
    explanation: str
    confidence_downgrade: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_action_permission": self.canonical_action_permission.value,
            "veto_reasons": [reason.value for reason in self.veto_reasons],
            "warnings": list(self.warnings),
            "allowed_use": list(self.allowed_use),
            "forbidden_use": list(self.forbidden_use),
            "explanation": self.explanation,
            "confidence_downgrade": bool(self.confidence_downgrade),
        }


@dataclass(frozen=True)
class DecisionRecord:
    """A single decision-ledger entry, deterministic and serialisable."""

    decision_id: str
    timestamp: str
    canonical_action_permission: ActionPermission
    veto_reasons: tuple[VetoReason, ...]
    policy_state: PolicyState
    position_integrity_state: PositionIntegrityState
    truth_origin: TruthOrigin
    system_mode: SystemMode
    state_archetype: str
    explanation: str
    evidence_snapshot_hash: str
    evidence_ledger_summary: EvidenceLedgerSummary | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "decision_id": self.decision_id,
            "timestamp": self.timestamp,
            "canonical_action_permission": self.canonical_action_permission.value,
            "veto_reasons": [reason.value for reason in self.veto_reasons],
            "policy_state": self.policy_state.value,
            "position_integrity_state": self.position_integrity_state.value,
            "truth_origin": self.truth_origin.value,
            "system_mode": self.system_mode.value,
            "state_archetype": self.state_archetype,
            "explanation": self.explanation,
            "evidence_snapshot_hash": self.evidence_snapshot_hash,
            "evidence_ledger_summary": (
                self.evidence_ledger_summary.to_dict()
                if self.evidence_ledger_summary is not None
                else None
            ),
            "extra": dict(self.extra),
        }
        return payload


def _enum_text(value: Any) -> str:
    """Extract a comparable text token from a value that may be an Enum
    instance from any module (cross-module enum identity is not safe).
    """

    if isinstance(value, Enum):
        # Use the .value, which for our (str, Enum) members is a str.
        return str(value.value).strip().upper()
    return str(value).strip().upper()


def coerce_truth_origin(value: Any, default: TruthOrigin = TruthOrigin.UNKNOWN) -> TruthOrigin:
    if isinstance(value, TruthOrigin):
        return value
    if value is None:
        return default
    text = _enum_text(value)
    if not text:
        return default
    try:
        return TruthOrigin(text)
    except ValueError:
        # Map a few permissive aliases used by older modules.
        aliases = {
            "SEED": TruthOrigin.SEEDED,
            "SEEDED_RUNTIME": TruthOrigin.SEEDED,
            "EXTERNAL": TruthOrigin.LIVE_EXTERNAL,
            "EXTERNALLY_CHECKED": TruthOrigin.LIVE_EXTERNAL,
            "LIVE": TruthOrigin.LIVE_EXTERNAL,
        }
        return aliases.get(text, default)


def coerce_policy_state(value: Any, default: PolicyState = PolicyState.UNKNOWN) -> PolicyState:
    if isinstance(value, PolicyState):
        return value
    if isinstance(value, Enum):
        try:
            return PolicyState(str(value.value).strip().upper())
        except ValueError:
            pass
    if value is None:
        return default
    text = _enum_text(value)
    if not text:
        return default
    try:
        return PolicyState(text)
    except ValueError:
        aliases = {
            "NOT_READY": PolicyState.RESTRICTED,
            "DENY": PolicyState.BLOCKED,
            "ALLOW": PolicyState.OPEN,
        }
        return aliases.get(text, default)


def coerce_position_state(
    value: Any, default: PositionIntegrityState = PositionIntegrityState.UNKNOWN
) -> PositionIntegrityState:
    if isinstance(value, PositionIntegrityState):
        return value
    if isinstance(value, Enum):
        try:
            return PositionIntegrityState(str(value.value).strip().upper())
        except ValueError:
            pass
    if value is None:
        return default
    text = _enum_text(value)
    if not text:
        return default
    try:
        return PositionIntegrityState(text)
    except ValueError:
        aliases = {
            "CLEAN": PositionIntegrityState.MATCHED,
            "MISSING_CANONICAL": PositionIntegrityState.MISSING_SOURCE,
        }
        return aliases.get(text, default)


def coerce_system_mode(value: Any, default: SystemMode = SystemMode.UNKNOWN) -> SystemMode:
    if isinstance(value, SystemMode):
        return value
    if isinstance(value, Enum):
        try:
            return SystemMode(str(value.value).strip().upper())
        except ValueError:
            pass
    if value is None:
        return default
    text = _enum_text(value)
    if not text:
        return default
    try:
        return SystemMode(text)
    except ValueError:
        aliases = {
            "SEEDED_RUNTIME": SystemMode.SEEDED,
            "PAPER": SystemMode.SEEDED,
        }
        return aliases.get(text, default)


__all__ = [
    "ActionPermission",
    "ActionPermissionResult",
    "DecisionRecord",
    "EvidenceLedgerSummary",
    "EvidenceRecord",
    "PolicyState",
    "PositionIntegrityState",
    "SystemMode",
    "TruthOrigin",
    "ValidationStatus",
    "VetoReason",
    "coerce_policy_state",
    "coerce_position_state",
    "coerce_system_mode",
    "coerce_truth_origin",
    "is_external_truth_origin",
]
