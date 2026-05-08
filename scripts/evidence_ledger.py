"""Canonical evidence ledger.

The evidence ledger is the single canonical place that aggregates
typed evidence records and reports — honestly — how much of that
evidence is actually external truth.

The single rule that matters most:

    ``external_signal_count`` only counts records whose ``truth_origin``
    is LIVE_EXTERNAL or REPLAY_LABELED (i.e. replay records that have
    been externally checked via outcome labels).

Seeded and demo records are never re-classified as external truth, no
matter how many of them exist or how confident their internal scores
are. That is the whole point of the ledger: to make hand-waving
evidence harder.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any, Iterable, Sequence

try:
    from scripts.runtime_contracts import (
        EvidenceLedgerSummary,
        EvidenceRecord,
        TruthOrigin,
        ValidationStatus,
        coerce_truth_origin,
        is_external_truth_origin,
    )
except ModuleNotFoundError:  # pragma: no cover
    from runtime_contracts import (  # type: ignore[no-redef]
        EvidenceLedgerSummary,
        EvidenceRecord,
        TruthOrigin,
        ValidationStatus,
        coerce_truth_origin,
        is_external_truth_origin,
    )


def _coerce_validation(value: Any) -> ValidationStatus:
    if isinstance(value, ValidationStatus):
        return value
    if value is None:
        return ValidationStatus.UNVALIDATED
    text = str(value).strip().upper()
    try:
        return ValidationStatus(text)
    except ValueError:
        aliases = {
            "VALID": ValidationStatus.REPLAY_REPRODUCED,
            "VALIDATED": ValidationStatus.REPLAY_REPRODUCED,
            "EXTERNAL": ValidationStatus.EXTERNALLY_CHECKED,
            "LABELED": ValidationStatus.OUTCOME_LABELED,
            "LABELLED": ValidationStatus.OUTCOME_LABELED,
        }
        return aliases.get(text, ValidationStatus.UNVALIDATED)


class EvidenceLedger:
    """Canonical typed evidence ledger.

    Records are appended in arrival order. Summary aggregation is
    deterministic given the same input sequence.
    """

    def __init__(self) -> None:
        self._records: list[EvidenceRecord] = []

    def __len__(self) -> int:  # pragma: no cover - trivial
        return len(self._records)

    @property
    def records(self) -> tuple[EvidenceRecord, ...]:
        return tuple(self._records)

    def add(self, record: EvidenceRecord) -> EvidenceRecord:
        if not isinstance(record, EvidenceRecord):
            raise TypeError("EvidenceLedger.add expects an EvidenceRecord")
        self._records.append(record)
        return record

    def add_raw(
        self,
        *,
        record_id: str,
        truth_origin: TruthOrigin | str,
        source: str,
        timestamp: str,
        confidence: float,
        validation_status: ValidationStatus | str,
        payload_hash: str = "",
        labels: Iterable[str] = (),
        notes: str = "",
    ) -> EvidenceRecord:
        record = EvidenceRecord(
            record_id=str(record_id),
            truth_origin=coerce_truth_origin(truth_origin),
            source=str(source),
            timestamp=str(timestamp),
            confidence=float(confidence),
            validation_status=_coerce_validation(validation_status),
            payload_hash=str(payload_hash),
            labels=tuple(str(label) for label in labels),
            notes=str(notes),
        )
        return self.add(record)

    def extend(self, records: Iterable[EvidenceRecord]) -> None:
        for record in records:
            self.add(record)

    def external_signal_count(self) -> int:
        return sum(1 for record in self._records if record.is_external_truth())

    def truth_origin_breakdown(self) -> dict[str, int]:
        counter: Counter[str] = Counter()
        for record in self._records:
            counter[record.truth_origin.value] += 1
        return dict(sorted(counter.items()))

    def validation_breakdown(self) -> dict[str, int]:
        counter: Counter[str] = Counter()
        for record in self._records:
            counter[record.validation_status.value] += 1
        return dict(sorted(counter.items()))

    def has_external_truth(self) -> bool:
        return self.external_signal_count() > 0

    def warnings(self) -> tuple[str, ...]:
        notes: list[str] = []
        if not self._records:
            notes.append("evidence_ledger_empty: no evidence records collected.")
            return tuple(notes)
        if not self.has_external_truth():
            notes.append(
                "no_external_truth: ledger contains zero LIVE_EXTERNAL or "
                "REPLAY_LABELED records; do not treat any score as externally "
                "validated."
            )
        breakdown = self.truth_origin_breakdown()
        seeded = breakdown.get(TruthOrigin.SEEDED.value, 0)
        demo = breakdown.get(TruthOrigin.DEMO.value, 0)
        if seeded and not self.has_external_truth():
            notes.append(
                f"seeded_only_evidence: {seeded} seeded records are not "
                "external truth and cannot support capital permission."
            )
        if demo and not self.has_external_truth():
            notes.append(
                f"demo_only_evidence: {demo} demo records are not external "
                "truth and cannot support capital permission."
            )
        unknown = breakdown.get(TruthOrigin.UNKNOWN.value, 0)
        if unknown:
            notes.append(
                f"unknown_truth_origin: {unknown} records lack a typed "
                "truth_origin tag and are excluded from external counts."
            )
        return tuple(notes)

    def payload_hash(self) -> str:
        payload = json.dumps(
            [record.to_dict() for record in self._records],
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def summary(self) -> EvidenceLedgerSummary:
        breakdown = self.truth_origin_breakdown()
        return EvidenceLedgerSummary(
            record_count=len(self._records),
            external_signal_count=self.external_signal_count(),
            seeded_signal_count=breakdown.get(TruthOrigin.SEEDED.value, 0),
            demo_signal_count=breakdown.get(TruthOrigin.DEMO.value, 0),
            replay_signal_count=breakdown.get(TruthOrigin.REPLAY.value, 0),
            replay_labeled_signal_count=breakdown.get(
                TruthOrigin.REPLAY_LABELED.value, 0
            ),
            unknown_signal_count=breakdown.get(TruthOrigin.UNKNOWN.value, 0),
            truth_origin_breakdown=breakdown,
            validation_breakdown=self.validation_breakdown(),
            source_count=len({record.source for record in self._records}),
            has_external_truth=self.has_external_truth(),
            warnings=self.warnings(),
            payload_hash=self.payload_hash(),
        )


def summarise_evidence(records: Sequence[EvidenceRecord]) -> EvidenceLedgerSummary:
    """Convenience helper: build an EvidenceLedgerSummary from a sequence."""

    ledger = EvidenceLedger()
    ledger.extend(records)
    return ledger.summary()


__all__ = [
    "EvidenceLedger",
    "summarise_evidence",
]
