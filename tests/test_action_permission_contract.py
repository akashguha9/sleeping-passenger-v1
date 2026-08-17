"""Tests for the canonical action-permission resolver contract."""
from __future__ import annotations

import pytest

from scripts.action_permission import (
    format_action_permission_summary,
    resolve_action_permission,
)
from scripts.runtime_contracts import (
    ActionPermission,
    PolicyState,
    PositionIntegrityState,
    TruthOrigin,
    VetoReason,
)


def _baseline_kwargs(**overrides):
    """Return a kwargs baseline that represents the seeded MVP runtime."""

    base = dict(
        truth_origin=TruthOrigin.SEEDED,
        external_signal_count=0,
        position_integrity_state=PositionIntegrityState.DIVERGED,
        policy_state=PolicyState.RESTRICTED,
        chaos_veto_active=True,
        chaos_veto_quarantine=False,
        calibration_missing=True,
        calibration_heuristic_only=True,
        contextual_interpretation_enabled=False,
    )
    base.update(overrides)
    return base


class TestActionPermission:
    def test_seeded_no_external_blocks_capital(self):
        result = resolve_action_permission(**_baseline_kwargs())
        assert (
            result.canonical_action_permission == ActionPermission.BLOCK_CAPITAL
        )
        assert VetoReason.NO_EXTERNAL_TRUTH in result.veto_reasons
        assert VetoReason.SEEDED_TRUTH_ONLY in result.veto_reasons

    def test_no_external_truth_blocks_capital(self):
        result = resolve_action_permission(
            **_baseline_kwargs(
                truth_origin=TruthOrigin.LIVE_EXTERNAL,
                external_signal_count=0,
            )
        )
        assert VetoReason.NO_EXTERNAL_TRUTH in result.veto_reasons
        assert (
            result.canonical_action_permission == ActionPermission.BLOCK_CAPITAL
        )

    def test_position_diverged_blocks_capital(self):
        result = resolve_action_permission(
            **_baseline_kwargs(
                truth_origin=TruthOrigin.LIVE_EXTERNAL,
                external_signal_count=10,
                position_integrity_state=PositionIntegrityState.DIVERGED,
                policy_state=PolicyState.OPEN,
                chaos_veto_active=False,
                calibration_missing=False,
                calibration_heuristic_only=False,
                contextual_interpretation_enabled=True,
            )
        )
        assert VetoReason.POSITION_DIVERGED in result.veto_reasons
        assert (
            result.canonical_action_permission == ActionPermission.BLOCK_CAPITAL
        )

    def test_policy_restricted_blocks_capital(self):
        result = resolve_action_permission(
            **_baseline_kwargs(
                truth_origin=TruthOrigin.LIVE_EXTERNAL,
                external_signal_count=10,
                position_integrity_state=PositionIntegrityState.RECONCILED,
                policy_state=PolicyState.RESTRICTED,
                chaos_veto_active=False,
                calibration_missing=False,
                calibration_heuristic_only=False,
                contextual_interpretation_enabled=True,
            )
        )
        assert VetoReason.POLICY_RESTRICTED in result.veto_reasons
        assert (
            result.canonical_action_permission == ActionPermission.BLOCK_CAPITAL
        )

    def test_chaos_veto_quarantines_when_supported(self):
        result = resolve_action_permission(
            **_baseline_kwargs(
                truth_origin=TruthOrigin.LIVE_EXTERNAL,
                external_signal_count=10,
                position_integrity_state=PositionIntegrityState.RECONCILED,
                policy_state=PolicyState.OPEN,
                chaos_veto_active=True,
                chaos_veto_quarantine=True,
                calibration_missing=False,
                calibration_heuristic_only=False,
                contextual_interpretation_enabled=True,
            )
        )
        assert VetoReason.CHAOS_VETO in result.veto_reasons
        assert result.canonical_action_permission == ActionPermission.QUARANTINE

    def test_chaos_veto_blocks_when_not_quarantine(self):
        result = resolve_action_permission(
            **_baseline_kwargs(
                truth_origin=TruthOrigin.LIVE_EXTERNAL,
                external_signal_count=10,
                position_integrity_state=PositionIntegrityState.RECONCILED,
                policy_state=PolicyState.OPEN,
                chaos_veto_active=True,
                chaos_veto_quarantine=False,
                calibration_missing=False,
                calibration_heuristic_only=False,
                contextual_interpretation_enabled=True,
            )
        )
        assert (
            result.canonical_action_permission == ActionPermission.BLOCK_CAPITAL
        )

    def test_missing_calibration_blocks_decision_ready(self):
        result = resolve_action_permission(
            **_baseline_kwargs(
                truth_origin=TruthOrigin.LIVE_EXTERNAL,
                external_signal_count=10,
                position_integrity_state=PositionIntegrityState.RECONCILED,
                policy_state=PolicyState.OPEN,
                chaos_veto_active=False,
                calibration_missing=True,
                calibration_heuristic_only=True,
                contextual_interpretation_enabled=True,
            )
        )
        assert VetoReason.CALIBRATION_MISSING in result.veto_reasons
        assert result.canonical_action_permission != ActionPermission.DEPLOY_CAPITAL

    def test_interpretation_disabled_downgrades_confidence(self):
        result = resolve_action_permission(
            **_baseline_kwargs(
                truth_origin=TruthOrigin.LIVE_EXTERNAL,
                external_signal_count=10,
                position_integrity_state=PositionIntegrityState.RECONCILED,
                policy_state=PolicyState.OPEN,
                chaos_veto_active=False,
                calibration_missing=False,
                calibration_heuristic_only=False,
                contextual_interpretation_enabled=False,
            )
        )
        assert VetoReason.INTERPRETATION_DISABLED in result.veto_reasons
        assert result.confidence_downgrade is True

    def test_seeded_truth_demo_use_only(self):
        result = resolve_action_permission(
            **_baseline_kwargs(
                # Even with everything else clean, seeded truth caps at DEMO_ONLY.
                external_signal_count=10,
                position_integrity_state=PositionIntegrityState.RECONCILED,
                policy_state=PolicyState.OPEN,
                chaos_veto_active=False,
                calibration_missing=False,
                calibration_heuristic_only=False,
                contextual_interpretation_enabled=True,
            )
        )
        assert VetoReason.SEEDED_TRUTH_ONLY in result.veto_reasons
        # External evidence_summary unset, so we trust the integer count
        # but truth_origin pins the permission to DEMO_ONLY.
        assert result.canonical_action_permission in {
            ActionPermission.DEMO_ONLY,
            ActionPermission.BLOCK_CAPITAL,
        }
        assert "demo/research diagnostics only" in "; ".join(result.allowed_use)

    def test_format_action_permission_summary(self):
        result = resolve_action_permission(**_baseline_kwargs())
        lines = format_action_permission_summary(result)
        text = "\n".join(lines)
        assert "canonical_action_permission=BLOCK_CAPITAL" in text
        assert "veto_reasons=[" in text
        assert "allowed_use=" in text
        assert "forbidden_use=" in text

    def test_jail_mode_blocks(self):
        result = resolve_action_permission(
            **_baseline_kwargs(
                truth_origin=TruthOrigin.LIVE_EXTERNAL,
                external_signal_count=10,
                position_integrity_state=PositionIntegrityState.RECONCILED,
                policy_state=PolicyState.OPEN,
                chaos_veto_active=False,
                calibration_missing=False,
                calibration_heuristic_only=False,
                contextual_interpretation_enabled=True,
                jail_mode_active=True,
            )
        )
        assert VetoReason.JAIL_MODE_ACTIVE in result.veto_reasons
        assert (
            result.canonical_action_permission == ActionPermission.BLOCK_CAPITAL
        )
