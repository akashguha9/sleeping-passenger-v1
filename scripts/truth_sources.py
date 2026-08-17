"""Replay-ready truth source interface.

Three concrete sources are defined:

    * ``SeedTruthSource``      — seeded fixtures only.
    * ``ReplayTruthSource``    — replay records that may or may not
                                  carry outcome labels.
    * ``ExternalTruthSourceStub`` — placeholder for a real external
                                     adapter; honestly returns
                                     NOT_CONFIGURED until wired up.

Each source produces ``TruthRecord`` objects whose ``truth_origin`` is
correctly typed: a SeedTruthSource cannot upgrade itself to LIVE_EXTERNAL
just because someone re-wraps it. ``OutcomeLabel`` is the single typed
container for the (instrument, observed_outcome, observed_at) triple
that allows replay records to be promoted from REPLAY to REPLAY_LABELED.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

try:
    from scripts.runtime_contracts import (
        EvidenceRecord,
        TruthOrigin,
        ValidationStatus,
    )
except ModuleNotFoundError:  # pragma: no cover
    from runtime_contracts import (  # type: ignore[no-redef]
        EvidenceRecord,
        TruthOrigin,
        ValidationStatus,
    )


@dataclass(frozen=True)
class OutcomeLabel:
    """Typed outcome label attached to a replay record."""

    record_id: str
    instrument: str
    observed_outcome: str
    observed_at: str
    source: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "instrument": self.instrument,
            "observed_outcome": self.observed_outcome,
            "observed_at": self.observed_at,
            "source": self.source,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class TruthRecord:
    """A typed record emitted by a truth source."""

    record_id: str
    truth_origin: TruthOrigin
    instrument: str
    timestamp: str
    payload: dict[str, Any] = field(default_factory=dict)
    label: OutcomeLabel | None = None
    source: str = ""

    @property
    def is_externally_checkable(self) -> bool:
        if self.truth_origin == TruthOrigin.LIVE_EXTERNAL:
            return True
        if self.truth_origin == TruthOrigin.REPLAY_LABELED and self.label is not None:
            return True
        return False

    def to_evidence(
        self,
        *,
        confidence: float = 0.0,
        validation_status: ValidationStatus | None = None,
        labels: Iterable[str] = (),
    ) -> EvidenceRecord:
        if validation_status is None:
            if self.truth_origin == TruthOrigin.LIVE_EXTERNAL:
                validation_status = ValidationStatus.EXTERNALLY_CHECKED
            elif self.truth_origin == TruthOrigin.REPLAY_LABELED:
                validation_status = ValidationStatus.OUTCOME_LABELED
            elif self.truth_origin == TruthOrigin.REPLAY:
                validation_status = ValidationStatus.REPLAY_REPRODUCED
            elif self.truth_origin == TruthOrigin.SEEDED:
                validation_status = ValidationStatus.SEED_ONLY
            else:
                validation_status = ValidationStatus.UNVALIDATED
        return EvidenceRecord(
            record_id=self.record_id,
            truth_origin=self.truth_origin,
            source=self.source or self.truth_origin.value,
            timestamp=self.timestamp,
            confidence=float(confidence),
            validation_status=validation_status,
            labels=tuple(labels),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "truth_origin": self.truth_origin.value,
            "instrument": self.instrument,
            "timestamp": self.timestamp,
            "payload": dict(self.payload),
            "label": self.label.to_dict() if self.label is not None else None,
            "source": self.source,
            "is_externally_checkable": self.is_externally_checkable,
        }


class TruthSource(abc.ABC):
    """Abstract base class for typed truth sources."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        ...

    @property
    @abc.abstractmethod
    def declared_truth_origin(self) -> TruthOrigin:
        ...

    @abc.abstractmethod
    def status(self) -> dict[str, Any]:
        ...

    @abc.abstractmethod
    def fetch(self) -> Sequence[TruthRecord]:
        ...


class SeedTruthSource(TruthSource):
    """Seed/demo truth source. Records are tagged ``SEEDED``."""

    def __init__(
        self,
        records: Iterable[dict[str, Any]] | None = None,
        *,
        name: str = "seed_truth_source",
        is_demo: bool = False,
    ) -> None:
        self._raw = list(records or [])
        self._name = name
        self._origin = TruthOrigin.DEMO if is_demo else TruthOrigin.SEEDED

    @property
    def name(self) -> str:
        return self._name

    @property
    def declared_truth_origin(self) -> TruthOrigin:
        return self._origin

    def status(self) -> dict[str, Any]:
        return {
            "name": self._name,
            "truth_origin": self._origin.value,
            "configured": True,
            "record_count": len(self._raw),
            "supports_capital_permission": False,
            "warning": (
                "seed/demo truth source: records cannot be treated as external truth"
            ),
        }

    def fetch(self) -> Sequence[TruthRecord]:
        records: list[TruthRecord] = []
        for index, raw in enumerate(self._raw):
            records.append(
                TruthRecord(
                    record_id=str(raw.get("record_id") or f"seed-{index}"),
                    truth_origin=self._origin,
                    instrument=str(raw.get("instrument") or raw.get("ticker") or ""),
                    timestamp=str(raw.get("timestamp") or ""),
                    payload={k: v for k, v in raw.items() if k != "record_id"},
                    source=self._name,
                )
            )
        return records


class ReplayTruthSource(TruthSource):
    """Replay truth source.

    Without outcome labels, records are tagged ``REPLAY``. With labels,
    they are promoted to ``REPLAY_LABELED`` and may count as external.
    """

    def __init__(
        self,
        records: Iterable[dict[str, Any]] | None = None,
        *,
        labels: Iterable[OutcomeLabel] | None = None,
        name: str = "replay_truth_source",
    ) -> None:
        self._raw = list(records or [])
        self._labels = {label.record_id: label for label in (labels or [])}
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def declared_truth_origin(self) -> TruthOrigin:
        return (
            TruthOrigin.REPLAY_LABELED if self._labels else TruthOrigin.REPLAY
        )

    def status(self) -> dict[str, Any]:
        labeled = sum(1 for raw in self._raw if str(raw.get("record_id") or "") in self._labels)
        return {
            "name": self._name,
            "truth_origin": self.declared_truth_origin.value,
            "configured": True,
            "record_count": len(self._raw),
            "labeled_record_count": labeled,
            "supports_capital_permission": labeled > 0,
            "warning": (
                "replay records without outcome labels cannot validate outcomes"
                if labeled < len(self._raw)
                else None
            ),
        }

    def attach_label(self, label: OutcomeLabel) -> None:
        self._labels[label.record_id] = label

    def fetch(self) -> Sequence[TruthRecord]:
        records: list[TruthRecord] = []
        for index, raw in enumerate(self._raw):
            record_id = str(raw.get("record_id") or f"replay-{index}")
            label = self._labels.get(record_id)
            origin = TruthOrigin.REPLAY_LABELED if label else TruthOrigin.REPLAY
            records.append(
                TruthRecord(
                    record_id=record_id,
                    truth_origin=origin,
                    instrument=str(raw.get("instrument") or raw.get("ticker") or ""),
                    timestamp=str(raw.get("timestamp") or ""),
                    payload={k: v for k, v in raw.items() if k != "record_id"},
                    label=label,
                    source=self._name,
                )
            )
        return records


class ExternalTruthSourceStub(TruthSource):
    """Honest stub for a not-yet-configured external truth source.

    This will *not* pretend to have live data. ``status()`` always
    reports ``NOT_CONFIGURED`` and ``fetch()`` returns an empty
    sequence. Wiring up a real adapter requires constructing a new
    subclass; this stub is the default to make missing configuration
    visible in diagnostics.
    """

    def __init__(self, name: str = "external_truth_source_stub") -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def declared_truth_origin(self) -> TruthOrigin:
        return TruthOrigin.UNKNOWN

    def status(self) -> dict[str, Any]:
        return {
            "name": self._name,
            "truth_origin": "NOT_CONFIGURED",
            "configured": False,
            "record_count": 0,
            "supports_capital_permission": False,
            "warning": (
                "external truth source not configured: do not interpret missing"
                " external evidence as agreement with seeded data."
            ),
        }

    def fetch(self) -> Sequence[TruthRecord]:
        return ()


__all__ = [
    "ExternalTruthSourceStub",
    "OutcomeLabel",
    "ReplayTruthSource",
    "SeedTruthSource",
    "TruthRecord",
    "TruthSource",
]
