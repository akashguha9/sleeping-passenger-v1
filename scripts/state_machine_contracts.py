"""Canonical state-machine contracts.

The pipeline already references many archetype/bull states (MIURA,
GALLARDO, DIABLO, ISLERO, HURACAN, AVENTADOR, JAIL, etc.). This module
adds a single typed contract that:

    * names the legal states,
    * names the legal transitions and reasons,
    * forbids unsafe shortcuts (e.g. MIURA → GALLARDO without a
      validation step), and
    * gives transitions an honesty-preserving log.

Nothing here mutates legacy modules; downstream code can opt in by
constructing a ``StateMachine`` and recording transitions through it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable


class Archetype(str, Enum):
    """Canonical archetype/bull-state enum used by the spine."""

    UNKNOWN = "UNKNOWN"
    MIURA = "MIURA"
    HURACAN = "HURACAN"
    GALLARDO = "GALLARDO"
    AVENTADOR = "AVENTADOR"
    ISLERO = "ISLERO"
    DIABLO = "DIABLO"
    MURCIELAGO = "MURCIELAGO"
    JAIL = "JAIL"
    DEPLOY = "DEPLOY"


class TransitionReason(str, Enum):
    """Reasons a transition can occur."""

    VALIDATION_PASSED = "VALIDATION_PASSED"
    PROMOTION = "PROMOTION"
    RECLASSIFICATION = "RECLASSIFICATION"
    CHAOS_DETECTED = "CHAOS_DETECTED"
    QUARANTINE = "QUARANTINE"
    FAST_TRACK_QUALIFIED = "FAST_TRACK_QUALIFIED"
    CALIBRATION_GATE_CLEARED = "CALIBRATION_GATE_CLEARED"
    POSITION_RECONCILED = "POSITION_RECONCILED"
    TRUTH_PROMOTION = "TRUTH_PROMOTION"
    OPERATOR_OVERRIDE = "OPERATOR_OVERRIDE"
    UNKNOWN = "UNKNOWN"


# Forbidden direct transitions — a legal step would require an
# intermediate state. Each tuple is (from, to).
FORBIDDEN_TRANSITIONS: frozenset[tuple[Archetype, Archetype]] = frozenset(
    {
        # MIURA cannot jump straight to GALLARDO without HURACAN
        # validation/promotion.
        (Archetype.MIURA, Archetype.GALLARDO),
        # MIURA cannot bypass validation and DEPLOY directly.
        (Archetype.MIURA, Archetype.DEPLOY),
        (Archetype.MIURA, Archetype.AVENTADOR),
        # JAIL cannot deploy without leaving JAIL first.
        (Archetype.JAIL, Archetype.DEPLOY),
        (Archetype.JAIL, Archetype.AVENTADOR),
        (Archetype.JAIL, Archetype.GALLARDO),
        # DIABLO must be quarantined / reclassified before deployment.
        (Archetype.DIABLO, Archetype.DEPLOY),
        (Archetype.DIABLO, Archetype.AVENTADOR),
        (Archetype.DIABLO, Archetype.GALLARDO),
        # HURACAN cannot fast-track straight to DEPLOY.
        (Archetype.HURACAN, Archetype.DEPLOY),
    }
)


# Hard rules attached to specific archetypes.
DIABLO_FORCES_VETO: bool = True
ISLERO_FORCES_RECLASSIFICATION: bool = True


@dataclass(frozen=True)
class TransitionRecord:
    """A single recorded archetype transition."""

    from_state: Archetype
    to_state: Archetype
    reason: TransitionReason
    confidence: float
    notes: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    consequence: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_state": self.from_state.value,
            "to_state": self.to_state.value,
            "reason": self.reason.value,
            "confidence": float(self.confidence),
            "notes": self.notes,
            "metadata": dict(self.metadata),
            "consequence": self.consequence,
        }


def _coerce_archetype(value: Any) -> Archetype:
    if isinstance(value, Archetype):
        return value
    text = str(value or "").strip().upper()
    try:
        return Archetype(text)
    except ValueError:
        aliases = {
            "MIURA_BULL": Archetype.MIURA,
            "GALLARDO_BULL": Archetype.GALLARDO,
            "AVENTADOR_BULL": Archetype.AVENTADOR,
            "DIABLO_CHAOS_SURFACE_VETO": Archetype.DIABLO,
        }
        return aliases.get(text, Archetype.UNKNOWN)


class StateMachineError(Exception):
    """Raised when a forbidden transition is attempted."""


class StateMachine:
    """Canonical archetype state machine."""

    def __init__(
        self,
        initial_state: Archetype | str = Archetype.UNKNOWN,
        *,
        huracan_validation_floor: float = 0.6,
    ) -> None:
        self._current = _coerce_archetype(initial_state)
        self._transitions: list[TransitionRecord] = []
        self._huracan_validation_floor = float(huracan_validation_floor)

    @property
    def current_state(self) -> Archetype:
        return self._current

    @property
    def transition_log(self) -> tuple[TransitionRecord, ...]:
        return tuple(self._transitions)

    def is_forbidden(self, from_state: Archetype, to_state: Archetype) -> bool:
        return (from_state, to_state) in FORBIDDEN_TRANSITIONS

    def transition(
        self,
        to_state: Archetype | str,
        *,
        reason: TransitionReason | str = TransitionReason.UNKNOWN,
        confidence: float = 0.0,
        notes: str = "",
        metadata: dict[str, Any] | None = None,
        validation_score: float | None = None,
    ) -> TransitionRecord:
        target = _coerce_archetype(to_state)
        reason_enum = (
            reason
            if isinstance(reason, TransitionReason)
            else _coerce_reason(reason)
        )
        if self.is_forbidden(self._current, target):
            raise StateMachineError(
                f"Forbidden transition: {self._current.value} -> {target.value} "
                f"(reason={reason_enum.value}). Use an intermediate validation/"
                "quarantine step before promoting."
            )

        # Special rules
        if (
            self._current == Archetype.HURACAN
            and target in {Archetype.GALLARDO, Archetype.AVENTADOR, Archetype.DEPLOY}
        ):
            score = (
                float(validation_score)
                if validation_score is not None
                else float(confidence)
            )
            if score < self._huracan_validation_floor:
                raise StateMachineError(
                    f"HURACAN cannot fast-track to {target.value}: "
                    f"validation_score={score:.3f} below floor "
                    f"{self._huracan_validation_floor:.3f}"
                )

        consequence = _consequence_for(target, reason_enum)
        record = TransitionRecord(
            from_state=self._current,
            to_state=target,
            reason=reason_enum,
            confidence=float(confidence),
            notes=str(notes),
            metadata=dict(metadata or {}),
            consequence=consequence,
        )
        self._transitions.append(record)
        self._current = target
        return record

    def serialize_log(self) -> list[dict[str, Any]]:
        return [record.to_dict() for record in self._transitions]


def _coerce_reason(value: Any) -> TransitionReason:
    text = str(value or "").strip().upper()
    try:
        return TransitionReason(text)
    except ValueError:
        return TransitionReason.UNKNOWN


def _consequence_for(target: Archetype, reason: TransitionReason) -> str:
    if target == Archetype.DIABLO:
        return "veto: chaos surface detected; new-risk capital deployment is blocked"
    if target == Archetype.ISLERO:
        return "reclassification: signal must be re-evaluated before promotion"
    if target == Archetype.JAIL:
        return "block: no new-risk deployment while in JAIL"
    if target == Archetype.DEPLOY:
        return (
            "deploy: requires external truth, calibration, position reconciliation,"
            " and no blocking veto"
        )
    if target == Archetype.AVENTADOR:
        return "promotion: full validation must already be complete"
    if reason == TransitionReason.QUARANTINE:
        return "quarantine: signal isolated until reclassification"
    return "advance"


def explain_forbidden_transitions() -> list[str]:
    """Return a human-readable list of forbidden direct transitions."""

    return [
        f"{from_state.value} -> {to_state.value}"
        for from_state, to_state in sorted(
            FORBIDDEN_TRANSITIONS, key=lambda pair: (pair[0].value, pair[1].value)
        )
    ]


__all__ = [
    "Archetype",
    "DIABLO_FORCES_VETO",
    "FORBIDDEN_TRANSITIONS",
    "ISLERO_FORCES_RECLASSIFICATION",
    "StateMachine",
    "StateMachineError",
    "TransitionReason",
    "TransitionRecord",
    "explain_forbidden_transitions",
]
