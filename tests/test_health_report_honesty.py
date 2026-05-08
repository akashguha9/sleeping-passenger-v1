"""Tests that the canonical spine is reflected honestly in the health report.

These tests run the full ``build_pipeline_health_report`` pipeline in
seeded mode and assert that the canonical block is consistent with the
underlying state — there must be no contradiction between the legacy
``system_readiness_state`` / ``can_deploy_capital`` fields and the new
``canonical_action_permission`` / ``veto_reasons`` fields.
"""
from __future__ import annotations

import pytest

from scripts.pipeline_health_report import (
    build_pipeline_health_report,
    format_pipeline_health_summary,
)


@pytest.fixture(scope="module")
def report():
    return build_pipeline_health_report(write_runtime=False)


class TestHealthReportHonesty:
    def test_seeded_runtime_does_not_claim_external_truth(self, report):
        assert report["truth_origin"] == "seeded"
        assert int(report["external_signal_count"]) == 0
        assert report["external_truth_status"] == "NO_EXTERNAL_TRUTH"

    def test_canonical_action_permission_is_block_capital(self, report):
        assert report["canonical_action_permission"] == "BLOCK_CAPITAL"

    def test_veto_reasons_include_no_external_truth(self, report):
        assert "NO_EXTERNAL_TRUTH" in report["veto_reasons"]

    def test_veto_reasons_include_seeded_truth(self, report):
        assert "SEEDED_TRUTH_ONLY" in report["veto_reasons"]

    def test_veto_reasons_include_position_diverged(self, report):
        # The seeded MVP runtime always has divergent positions.
        assert (
            "POSITION_DIVERGED" in report["veto_reasons"]
            or "POSITION_UNKNOWN" in report["veto_reasons"]
        )

    def test_veto_reasons_include_policy_restricted(self, report):
        assert "POLICY_RESTRICTED" in report["veto_reasons"]

    def test_veto_reasons_include_calibration_missing(self, report):
        assert "CALIBRATION_MISSING" in report["veto_reasons"]

    def test_calibration_status_demo_only_in_seeded(self, report):
        assert report["calibration_status"] == "DEMO_ONLY"

    def test_no_contradiction_with_legacy_readiness(self, report):
        # If the report says system_readiness_state=DO_NOT_DEPLOY, then
        # the canonical action permission must NOT claim deployable.
        if report.get("system_readiness_state") == "DO_NOT_DEPLOY":
            assert (
                report["canonical_action_permission"] != "DEPLOY_CAPITAL"
            )

    def test_can_deploy_capital_consistent(self, report):
        if not report.get("can_deploy_capital", False):
            assert (
                report["canonical_action_permission"] != "DEPLOY_CAPITAL"
            )

    def test_forbidden_use_in_block_capital_state(self, report):
        if report["canonical_action_permission"] == "BLOCK_CAPITAL":
            forbidden = report.get("forbidden_use") or []
            assert any("capital deployment" in row for row in forbidden)

    def test_evidence_ledger_status_present(self, report):
        assert report.get("evidence_ledger_status") in {
            "EMPTY",
            "SEEDED_ONLY",
            "MIXED_OR_EXTERNAL",
        }

    def test_decision_ledger_status_present(self, report):
        assert report.get("decision_ledger_status") == "IN_MEMORY_ONLY"

    def test_truth_origin_breakdown_present(self, report):
        breakdown = report.get("truth_origin_breakdown")
        assert breakdown
        assert "SEEDED" in breakdown

    def test_summary_lines_contain_canonical_block(self, report):
        text = format_pipeline_health_summary(report)
        assert "canonical_action_permission=" in text
        assert "veto_reasons=[" in text
        assert "truth_origin_breakdown=" in text
        assert "external_truth_status=" in text
        assert "calibration_status=" in text
        assert "allowed_use=" in text
        assert "forbidden_use=" in text

    def test_block_capital_emits_demo_or_research_use(self, report):
        if report["canonical_action_permission"] == "BLOCK_CAPITAL":
            allowed = "; ".join(report.get("allowed_use") or [])
            assert (
                "demo" in allowed.lower()
                or "research" in allowed.lower()
            )

    def test_action_permission_explanation_present(self, report):
        assert isinstance(report.get("action_permission_explanation"), str)
        assert len(report["action_permission_explanation"]) > 0
