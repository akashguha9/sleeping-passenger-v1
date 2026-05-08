"""Tests for the canonical decision ledger."""
from __future__ import annotations

import json

import pytest

from scripts.decision_ledger import DecisionLedger, build_decision_record
from scripts.evidence_ledger import EvidenceLedger
from scripts.runtime_contracts import (
    ActionPermission,
    PolicyState,
    PositionIntegrityState,
    SystemMode,
    TruthOrigin,
    VetoReason,
)


class TestDecisionLedger:
    def test_record_serialises_with_veto_reasons(self):
        record = build_decision_record(
            decision_id="dec-1",
            canonical_action_permission=ActionPermission.BLOCK_CAPITAL,
            veto_reasons=[VetoReason.NO_EXTERNAL_TRUTH, "POSITION_DIVERGED"],
            policy_state=PolicyState.RESTRICTED,
            position_integrity_state=PositionIntegrityState.DIVERGED,
            truth_origin=TruthOrigin.SEEDED,
            system_mode=SystemMode.SEEDED,
            state_archetype="MIURA",
            explanation="seeded only",
        )
        out = record.to_dict()
        assert out["canonical_action_permission"] == "BLOCK_CAPITAL"
        assert "NO_EXTERNAL_TRUTH" in out["veto_reasons"]
        assert "POSITION_DIVERGED" in out["veto_reasons"]
        assert out["truth_origin"] == "SEEDED"

    def test_evidence_snapshot_hash_is_deterministic(self):
        snap = {"a": 1, "b": [2, 3]}
        a = build_decision_record(
            decision_id="d1",
            canonical_action_permission="BLOCK_CAPITAL",
            veto_reasons=[],
            policy_state="RESTRICTED",
            position_integrity_state="DIVERGED",
            truth_origin="SEEDED",
            evidence_snapshot=snap,
            timestamp="2026-05-08T00:00:00Z",
        )
        b = build_decision_record(
            decision_id="d1",
            canonical_action_permission="BLOCK_CAPITAL",
            veto_reasons=[],
            policy_state="RESTRICTED",
            position_integrity_state="DIVERGED",
            truth_origin="SEEDED",
            evidence_snapshot=snap,
            timestamp="2026-05-08T00:00:00Z",
        )
        assert a.evidence_snapshot_hash == b.evidence_snapshot_hash
        assert a.evidence_snapshot_hash != ""

    def test_ledger_records_and_serializes_jsonl(self):
        ledger = DecisionLedger()
        ledger.record(
            decision_id="dec-1",
            canonical_action_permission="BLOCK_CAPITAL",
            veto_reasons=["NO_EXTERNAL_TRUTH"],
            policy_state="RESTRICTED",
            position_integrity_state="DIVERGED",
            truth_origin="SEEDED",
            timestamp="2026-05-08T00:00:00Z",
        )
        ledger.record(
            decision_id="dec-2",
            canonical_action_permission="DEMO_ONLY",
            veto_reasons=["SEEDED_TRUTH_ONLY"],
            policy_state="OPEN",
            position_integrity_state="MATCHED",
            truth_origin="SEEDED",
            timestamp="2026-05-08T01:00:00Z",
        )
        text = ledger.serialize_jsonl()
        lines = text.strip().split("\n")
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert first["canonical_action_permission"] == "BLOCK_CAPITAL"
        assert "NO_EXTERNAL_TRUTH" in first["veto_reasons"]

    def test_ledger_writes_jsonl_to_path(self, scratch_path):
        ledger = DecisionLedger()
        ledger.record(
            decision_id="d-1",
            canonical_action_permission="BLOCK_CAPITAL",
            veto_reasons=["POLICY_RESTRICTED"],
            policy_state="RESTRICTED",
            position_integrity_state="DIVERGED",
            truth_origin="SEEDED",
            timestamp="2026-05-08T00:00:00Z",
        )
        out_path = scratch_path / "decisions.jsonl"
        ledger.to_jsonl_path(out_path)
        assert out_path.exists()
        line = out_path.read_text(encoding="utf-8").strip()
        assert "BLOCK_CAPITAL" in line

    def test_status_reports_latest(self):
        ledger = DecisionLedger()
        assert ledger.status()["decision_count"] == 0
        ledger.record(
            decision_id="d-1",
            canonical_action_permission="BLOCK_CAPITAL",
            veto_reasons=["NO_EXTERNAL_TRUTH"],
            policy_state="RESTRICTED",
            position_integrity_state="DIVERGED",
            truth_origin="SEEDED",
            timestamp="2026-05-08T00:00:00Z",
        )
        status = ledger.status()
        assert status["decision_count"] == 1
        assert status["latest_action_permission"] == "BLOCK_CAPITAL"

    def test_evidence_summary_attaches_to_record(self):
        ev = EvidenceLedger()
        ev.add_raw(
            record_id="seed-1",
            truth_origin="SEEDED",
            source="seed",
            timestamp="2026-05-08T00:00:00Z",
            confidence=0.5,
            validation_status="SEED_ONLY",
        )
        summary = ev.summary()
        record = build_decision_record(
            decision_id="d-1",
            canonical_action_permission="BLOCK_CAPITAL",
            veto_reasons=["NO_EXTERNAL_TRUTH"],
            policy_state="RESTRICTED",
            position_integrity_state="DIVERGED",
            truth_origin="SEEDED",
            evidence_ledger_summary=summary,
            timestamp="2026-05-08T00:00:00Z",
        )
        out = record.to_dict()
        assert out["evidence_ledger_summary"]["external_signal_count"] == 0
        assert out["evidence_snapshot_hash"]
