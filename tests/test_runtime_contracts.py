"""Tests for the canonical runtime contracts."""
from __future__ import annotations

import pytest

from scripts.runtime_contracts import (
    ActionPermission,
    PolicyState,
    PositionIntegrityState,
    SystemMode,
    TruthOrigin,
    ValidationStatus,
    VetoReason,
    coerce_policy_state,
    coerce_position_state,
    coerce_system_mode,
    coerce_truth_origin,
    is_external_truth_origin,
)


class TestTruthOrigin:
    def test_seeded_is_not_external(self):
        assert is_external_truth_origin(TruthOrigin.SEEDED) is False

    def test_demo_is_not_external(self):
        assert is_external_truth_origin(TruthOrigin.DEMO) is False

    def test_replay_is_not_external_without_labels(self):
        assert is_external_truth_origin(TruthOrigin.REPLAY) is False

    def test_replay_labeled_is_external(self):
        assert is_external_truth_origin(TruthOrigin.REPLAY_LABELED) is True

    def test_live_external_is_external(self):
        assert is_external_truth_origin(TruthOrigin.LIVE_EXTERNAL) is True

    def test_unknown_is_not_external(self):
        assert is_external_truth_origin(TruthOrigin.UNKNOWN) is False

    def test_string_seeded_is_not_external(self):
        assert is_external_truth_origin("seeded") is False
        assert is_external_truth_origin("SEEDED") is False

    def test_string_live_external_is_external(self):
        assert is_external_truth_origin("live_external") is True


class TestCoerce:
    def test_coerce_truth_origin_string(self):
        assert coerce_truth_origin("seeded") == TruthOrigin.SEEDED
        assert coerce_truth_origin("LIVE_EXTERNAL") == TruthOrigin.LIVE_EXTERNAL
        assert coerce_truth_origin("nope") == TruthOrigin.UNKNOWN

    def test_coerce_truth_origin_enum(self):
        assert coerce_truth_origin(TruthOrigin.DEMO) == TruthOrigin.DEMO

    def test_coerce_truth_origin_alias(self):
        assert coerce_truth_origin("external") == TruthOrigin.LIVE_EXTERNAL

    def test_coerce_position_state(self):
        assert (
            coerce_position_state("DIVERGED")
            == PositionIntegrityState.DIVERGED
        )
        assert (
            coerce_position_state("CLEAN") == PositionIntegrityState.MATCHED
        )
        assert (
            coerce_position_state("MISSING_CANONICAL")
            == PositionIntegrityState.MISSING_SOURCE
        )
        assert coerce_position_state(None) == PositionIntegrityState.UNKNOWN

    def test_coerce_policy_state(self):
        assert coerce_policy_state("RESTRICTED") == PolicyState.RESTRICTED
        assert coerce_policy_state("not_ready") == PolicyState.RESTRICTED
        assert coerce_policy_state("OPEN") == PolicyState.OPEN

    def test_coerce_system_mode(self):
        assert coerce_system_mode("seeded") == SystemMode.SEEDED
        assert coerce_system_mode("PAPER") == SystemMode.SEEDED
        assert coerce_system_mode("LIVE") == SystemMode.LIVE


class TestEnumCompleteness:
    def test_all_action_permissions_have_unique_values(self):
        values = [p.value for p in ActionPermission]
        assert len(values) == len(set(values))

    def test_all_veto_reasons_have_unique_values(self):
        values = [v.value for v in VetoReason]
        assert len(values) == len(set(values))

    def test_validation_status_has_required_members(self):
        names = {s.name for s in ValidationStatus}
        assert "EXTERNALLY_CHECKED" in names
        assert "OUTCOME_LABELED" in names
        assert "SEED_ONLY" in names
