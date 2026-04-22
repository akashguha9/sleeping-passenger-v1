from __future__ import annotations

import json
from pathlib import Path

from scripts.environment_fit_report import (
    build_environment_fit_report,
    format_environment_fit_summary,
)
from scripts.runtime_common import build_runtime_state_from_scm_report_payload
from scripts.signal_conversion_monitor import build_signal_conversion_report


def _runtime_state() -> dict:
    return build_runtime_state_from_scm_report_payload(build_signal_conversion_report())


def test_environment_fit_report_seeded_local_alignment(
    scratch_path: Path,
) -> None:
    output_path = scratch_path / "environment_fit_report.json"
    report = build_environment_fit_report(
        runtime_state=_runtime_state(),
        operating_mode_report={
            "operating_mode": "seeded",
            "truth_origin": "seeded",
            "quote_provider_state": "placeholder",
            "live_execution_enabled": False,
        },
        governance_status_report={
            "controls": {
                "artifact_coherence": {"state": "legacy_polluted"},
            }
        },
        experience_mode_report={
            "trainer_mode_metadata": {
                "trainer_mode_active": True,
                "recommended_surface_profile": "trainer",
            },
            "readiness_ladder": {
                "recommended_surface_profile": "trainer",
                "trainer_readiness": 0.82,
                "utility_readiness": 0.68,
                "jet_readiness": 0.55,
            },
            "visibility_legibility_layer": {
                "visibility_legibility_score": 0.85,
                "unresolved_data_gap_rate": 0.33,
                "missing_mark_frequency": 0.0,
            },
            "utility_resilience_layer": {
                "degraded_mode_required": True,
                "confidence_downgrade_required": True,
            },
            "premium_compression_layer": {
                "premium_surface_eligible": False,
            },
        },
        output_path=output_path,
        write_runtime=True,
    )

    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["environment_fit_scorer"]["fit_state"] == "aligned"
    assert report["environment_fit_scorer"]["respect_where_you_are_flag"] is True
    assert (
        report["robustness_precision_classifier"]["classification"]
        == "robustness_first"
    )
    assert (
        report["local_signal_priority_engine"]["local_signal_priority_state"]
        == "local_primary"
    )
    assert written["artifact_kind"] == "environment_fit_report"


def test_environment_fit_report_refuses_precision_without_earned_conditions() -> None:
    report = build_environment_fit_report(
        runtime_state=_runtime_state(),
        operating_mode_report={
            "operating_mode": "hybrid",
            "truth_origin": "external",
            "quote_provider_state": "external_observation",
            "live_execution_enabled": False,
        },
        governance_status_report={
            "controls": {
                "artifact_coherence": {"state": "coherent"},
            }
        },
        experience_mode_report={
            "trainer_mode_metadata": {
                "trainer_mode_active": False,
                "recommended_surface_profile": "utility",
            },
            "readiness_ladder": {
                "recommended_surface_profile": "utility",
                "trainer_readiness": 0.82,
                "utility_readiness": 0.70,
                "jet_readiness": 0.55,
            },
            "visibility_legibility_layer": {
                "visibility_legibility_score": 0.85,
                "unresolved_data_gap_rate": 0.0,
                "missing_mark_frequency": 0.0,
            },
            "utility_resilience_layer": {
                "degraded_mode_required": False,
                "confidence_downgrade_required": False,
            },
            "premium_compression_layer": {
                "premium_surface_eligible": False,
            },
        },
        write_runtime=False,
    )

    assert report["robustness_precision_classifier"]["classification"] == "balanced_transition"
    assert report["robustness_precision_classifier"]["precision_ready"] is False
    assert report["strategy_family_selector"]["selected_family"] == "utility"
    summary = format_environment_fit_summary(report)
    assert "robustness_precision_classification=balanced_transition" in summary


def test_environment_fit_report_handles_sparse_inputs_safely() -> None:
    report = build_environment_fit_report(
        runtime_state=_runtime_state(),
        operating_mode_report={
            "operating_mode": "seeded",
            "truth_origin": "seeded",
        },
        governance_status_report={
            "controls": {
                "artifact_coherence": {"state": "unknown"},
            }
        },
        experience_mode_report={
            "trainer_mode_metadata": {},
            "readiness_ladder": {},
            "visibility_legibility_layer": {},
            "utility_resilience_layer": {},
            "premium_compression_layer": {},
        },
        write_runtime=False,
    )

    assert report["environment_fit_scorer"]["environment_fit_score"] >= 0.0
    assert report["over_customization_guardrail"]["recommended_change_style"] == "additive_extensions_only"
    assert report["identity_utility_layer"]["state"] == "concept_only"
