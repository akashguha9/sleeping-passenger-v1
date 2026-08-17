"""Tests for the canonical evidence ledger."""
from __future__ import annotations

import pytest

from scripts.evidence_ledger import EvidenceLedger, summarise_evidence
from scripts.runtime_contracts import (
    EvidenceRecord,
    TruthOrigin,
    ValidationStatus,
)


def _seeded(record_id: str = "s1") -> EvidenceRecord:
    return EvidenceRecord(
        record_id=record_id,
        truth_origin=TruthOrigin.SEEDED,
        source="seed_fixture",
        timestamp="2026-05-08T00:00:00Z",
        confidence=0.9,
        validation_status=ValidationStatus.SEED_ONLY,
    )


def _external(record_id: str = "e1") -> EvidenceRecord:
    return EvidenceRecord(
        record_id=record_id,
        truth_origin=TruthOrigin.LIVE_EXTERNAL,
        source="live_adapter",
        timestamp="2026-05-08T01:00:00Z",
        confidence=0.7,
        validation_status=ValidationStatus.EXTERNALLY_CHECKED,
    )


class TestEvidenceLedger:
    def test_seeded_records_are_not_external(self):
        ledger = EvidenceLedger()
        ledger.add(_seeded())
        ledger.add(_seeded("s2"))
        assert ledger.external_signal_count() == 0
        assert ledger.has_external_truth() is False

    def test_demo_records_are_not_external(self):
        ledger = EvidenceLedger()
        ledger.add_raw(
            record_id="d1",
            truth_origin="DEMO",
            source="demo",
            timestamp="2026-05-08T00:00:00Z",
            confidence=0.5,
            validation_status="UNVALIDATED",
        )
        assert ledger.external_signal_count() == 0

    def test_live_external_counts_as_external(self):
        ledger = EvidenceLedger()
        ledger.add(_external())
        assert ledger.external_signal_count() == 1
        assert ledger.has_external_truth() is True

    def test_replay_without_labels_is_not_external(self):
        ledger = EvidenceLedger()
        ledger.add_raw(
            record_id="r1",
            truth_origin="REPLAY",
            source="replay",
            timestamp="2026-05-08T00:00:00Z",
            confidence=0.8,
            validation_status="REPLAY_REPRODUCED",
        )
        assert ledger.external_signal_count() == 0

    def test_replay_labeled_is_external(self):
        ledger = EvidenceLedger()
        ledger.add_raw(
            record_id="rl1",
            truth_origin="REPLAY_LABELED",
            source="replay_labeled",
            timestamp="2026-05-08T00:00:00Z",
            confidence=0.8,
            validation_status="OUTCOME_LABELED",
        )
        assert ledger.external_signal_count() == 1

    def test_summary_is_deterministic(self):
        ledger_a = EvidenceLedger()
        ledger_b = EvidenceLedger()
        for r in [_seeded("s1"), _external("e1"), _seeded("s2")]:
            ledger_a.add(r)
            ledger_b.add(r)
        assert ledger_a.summary().to_dict() == ledger_b.summary().to_dict()

    def test_summary_includes_breakdown(self):
        ledger = EvidenceLedger()
        ledger.add(_seeded("s1"))
        ledger.add(_seeded("s2"))
        ledger.add(_external("e1"))
        summary = ledger.summary()
        assert summary.external_signal_count == 1
        assert summary.seeded_signal_count == 2
        assert summary.has_external_truth is True
        assert "SEEDED" in summary.truth_origin_breakdown

    def test_warnings_when_no_external(self):
        ledger = EvidenceLedger()
        ledger.add(_seeded("s1"))
        warnings = ledger.warnings()
        assert any("no_external_truth" in w for w in warnings)

    def test_summarise_helper(self):
        summary = summarise_evidence([_external("e1")])
        assert summary.external_signal_count == 1
