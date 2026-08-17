"""Tests for the position reconciliation contract."""
from __future__ import annotations

import pytest

from scripts.position_truth_resolver import resolve_position_integrity_contract
from scripts.runtime_contracts import PositionIntegrityState, TruthOrigin


class TestPositionContract:
    def test_diverged_state_passes_through(self):
        out = resolve_position_integrity_contract(
            {"position_integrity_state": "DIVERGED"},
            truth_origin=TruthOrigin.SEEDED,
        )
        assert out["canonical_position_integrity_state"] == "DIVERGED"
        assert out["blocks_capital"] is True
        assert out["is_clean"] is False

    def test_matched_with_seeded_downgrades_to_unknown(self):
        out = resolve_position_integrity_contract(
            {"position_integrity_state": "CLEAN"},
            truth_origin=TruthOrigin.SEEDED,
        )
        assert out["canonical_position_integrity_state"] == "UNKNOWN"
        assert out["blocks_capital"] is True
        assert "MATCHED downgraded" in out["rationale"]

    def test_matched_with_demo_downgrades(self):
        out = resolve_position_integrity_contract(
            {"position_integrity_state": "CLEAN"},
            truth_origin=TruthOrigin.DEMO,
        )
        assert out["canonical_position_integrity_state"] == "UNKNOWN"

    def test_matched_with_external_truth_remains_matched(self):
        out = resolve_position_integrity_contract(
            {"position_integrity_state": "CLEAN"},
            truth_origin=TruthOrigin.LIVE_EXTERNAL,
        )
        assert out["canonical_position_integrity_state"] == "MATCHED"
        assert out["is_clean"] is True

    def test_reconciled_requires_explicit_evidence(self):
        out = resolve_position_integrity_contract(
            {
                "position_integrity_state": "CLEAN",
                "reconciliation_evidence": True,
            },
            truth_origin=TruthOrigin.LIVE_EXTERNAL,
        )
        assert out["canonical_position_integrity_state"] == "RECONCILED"

    def test_high_severity_forces_diverged(self):
        out = resolve_position_integrity_contract(
            {
                "position_integrity_state": "UNKNOWN",
                "divergence_severity": "HIGH",
            },
            truth_origin=TruthOrigin.LIVE_EXTERNAL,
        )
        assert out["canonical_position_integrity_state"] == "DIVERGED"

    def test_missing_canonical_maps_to_missing_source(self):
        out = resolve_position_integrity_contract(
            {"position_integrity_state": "MISSING_CANONICAL"},
            truth_origin=TruthOrigin.SEEDED,
        )
        assert (
            out["canonical_position_integrity_state"]
            == PositionIntegrityState.MISSING_SOURCE.value
        )
        assert out["blocks_capital"] is True

    def test_unknown_is_not_clean(self):
        out = resolve_position_integrity_contract(
            {"position_integrity_state": "UNKNOWN"},
            truth_origin=TruthOrigin.UNKNOWN,
        )
        assert out["is_clean"] is False
