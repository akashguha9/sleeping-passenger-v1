"""Tests for the typed truth sources."""
from __future__ import annotations

import pytest

from scripts.runtime_contracts import TruthOrigin, ValidationStatus
from scripts.truth_sources import (
    ExternalTruthSourceStub,
    OutcomeLabel,
    ReplayTruthSource,
    SeedTruthSource,
)


class TestSeedTruthSource:
    def test_seed_records_are_seeded_truth_origin(self):
        src = SeedTruthSource([{"record_id": "s1", "ticker": "ABC"}])
        records = src.fetch()
        assert records[0].truth_origin == TruthOrigin.SEEDED
        assert records[0].is_externally_checkable is False

    def test_demo_flag_emits_demo_origin(self):
        src = SeedTruthSource([{"record_id": "d1"}], is_demo=True)
        records = src.fetch()
        assert records[0].truth_origin == TruthOrigin.DEMO

    def test_seed_status_signals_no_capital_permission(self):
        src = SeedTruthSource([{"record_id": "s1"}])
        status = src.status()
        assert status["supports_capital_permission"] is False
        assert status["truth_origin"] == TruthOrigin.SEEDED.value


class TestReplayTruthSource:
    def test_replay_without_labels_is_replay_origin(self):
        src = ReplayTruthSource([{"record_id": "r1"}])
        records = src.fetch()
        assert records[0].truth_origin == TruthOrigin.REPLAY
        assert records[0].is_externally_checkable is False

    def test_replay_with_label_is_replay_labeled(self):
        label = OutcomeLabel(
            record_id="r1",
            instrument="ABC",
            observed_outcome="WIN",
            observed_at="2026-05-08T00:00:00Z",
        )
        src = ReplayTruthSource(
            [{"record_id": "r1", "ticker": "ABC"}],
            labels=[label],
        )
        records = src.fetch()
        assert records[0].truth_origin == TruthOrigin.REPLAY_LABELED
        assert records[0].is_externally_checkable is True

    def test_replay_status_warns_when_unlabeled(self):
        src = ReplayTruthSource([{"record_id": "r1"}, {"record_id": "r2"}])
        status = src.status()
        assert status["supports_capital_permission"] is False
        assert "outcome labels" in status.get("warning") or ""

    def test_attach_label_promotes_to_external(self):
        src = ReplayTruthSource([{"record_id": "r1"}])
        assert src.fetch()[0].truth_origin == TruthOrigin.REPLAY
        src.attach_label(
            OutcomeLabel(
                record_id="r1",
                instrument="X",
                observed_outcome="LOSE",
                observed_at="2026-05-08T00:00:00Z",
            )
        )
        assert src.fetch()[0].truth_origin == TruthOrigin.REPLAY_LABELED


class TestExternalStub:
    def test_external_stub_is_not_configured(self):
        src = ExternalTruthSourceStub()
        status = src.status()
        assert status["configured"] is False
        assert status["truth_origin"] == "NOT_CONFIGURED"
        assert status["record_count"] == 0
        assert src.fetch() == ()

    def test_external_stub_warns_explicitly(self):
        src = ExternalTruthSourceStub()
        status = src.status()
        assert "not configured" in status.get("warning", "")


class TestEvidenceConversion:
    def test_seed_record_to_evidence_is_seed_only(self):
        src = SeedTruthSource([{"record_id": "s1"}])
        record = src.fetch()[0]
        evidence = record.to_evidence(confidence=0.5)
        assert evidence.truth_origin == TruthOrigin.SEEDED
        assert evidence.validation_status == ValidationStatus.SEED_ONLY
        assert evidence.is_external_truth() is False

    def test_replay_labeled_to_evidence_is_outcome_labeled(self):
        label = OutcomeLabel(
            record_id="r1",
            instrument="X",
            observed_outcome="WIN",
            observed_at="2026-05-08T00:00:00Z",
        )
        src = ReplayTruthSource([{"record_id": "r1"}], labels=[label])
        record = src.fetch()[0]
        evidence = record.to_evidence(confidence=0.6)
        assert evidence.validation_status == ValidationStatus.OUTCOME_LABELED
        assert evidence.is_external_truth() is True
