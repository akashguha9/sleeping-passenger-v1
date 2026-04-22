from __future__ import annotations

import json
from pathlib import Path

from scripts.pipeline_health_report import build_pipeline_health_report
from scripts.runtime_common import build_runtime_state_from_scm_report_payload
from scripts.signal_conversion_monitor import build_signal_conversion_report


def _runtime_state() -> dict:
    return build_runtime_state_from_scm_report_payload(build_signal_conversion_report())


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_pipeline_health_report_includes_compact_experience_mode_summary(
    scratch_path: Path,
) -> None:
    experience_path = scratch_path / "experience_mode_report.json"
    controller_path = scratch_path / "complexity_ladder_controller.json"

    _write_json(
        experience_path,
        {
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
            "utility_resilience_layer": {"degraded_mode_required": True},
            "premium_compression_layer": {"premium_surface_eligible": False},
        },
    )
    _write_json(
        controller_path,
        {
            "operator_surface_recommendation": "trainer",
            "trainer_surface_allowed": True,
            "utility_surface_allowed": False,
            "premium_surface_allowed": False,
            "degraded_mode_annotations_required": True,
        },
    )

    payload = build_pipeline_health_report(
        include_tests=False,
        write_runtime=False,
        runtime_state=_runtime_state(),
        experience_mode_report_path=experience_path,
        complexity_ladder_controller_path=controller_path,
    )

    assert payload["experience_mode_summary"] == {
        "experience_mode_report_present": True,
        "complexity_ladder_controller_present": True,
        "recommended_surface_profile": "trainer",
        "trainer_mode_active": True,
        "degraded_mode_required": True,
        "premium_surface_eligible": False,
        "premium_surface_allowed": False,
    }


def test_pipeline_health_report_experience_mode_summary_falls_back_safely(
    scratch_path: Path,
) -> None:
    payload = build_pipeline_health_report(
        include_tests=False,
        write_runtime=False,
        runtime_state=_runtime_state(),
        experience_mode_report_path=scratch_path / "missing_experience_mode_report.json",
        complexity_ladder_controller_path=scratch_path / "missing_complexity_ladder_controller.json",
    )

    assert payload["experience_mode_summary"] == {
        "experience_mode_report_present": False,
        "complexity_ladder_controller_present": False,
        "recommended_surface_profile": "trainer",
        "trainer_mode_active": True,
        "degraded_mode_required": True,
        "premium_surface_eligible": False,
        "premium_surface_allowed": False,
    }


def test_pipeline_health_report_experience_summary_keeps_premium_false_when_jet_not_ready(
    scratch_path: Path,
) -> None:
    experience_path = scratch_path / "experience_mode_report.json"
    controller_path = scratch_path / "complexity_ladder_controller.json"

    _write_json(
        experience_path,
        {
            "trainer_mode_metadata": {
                "trainer_mode_active": False,
                "recommended_surface_profile": "utility",
            },
            "readiness_ladder": {
                "recommended_surface_profile": "utility",
                "trainer_readiness": 0.82,
                "utility_readiness": 0.7,
                "jet_readiness": 0.55,
            },
            "utility_resilience_layer": {"degraded_mode_required": False},
            "premium_compression_layer": {"premium_surface_eligible": False},
        },
    )
    _write_json(
        controller_path,
        {
            "operator_surface_recommendation": "utility",
            "trainer_surface_allowed": True,
            "utility_surface_allowed": True,
            "premium_surface_allowed": False,
            "degraded_mode_annotations_required": False,
        },
    )

    payload = build_pipeline_health_report(
        include_tests=False,
        write_runtime=False,
        runtime_state=_runtime_state(),
        experience_mode_report_path=experience_path,
        complexity_ladder_controller_path=controller_path,
    )

    assert payload["experience_mode_summary"]["recommended_surface_profile"] == "utility"
    assert payload["experience_mode_summary"]["premium_surface_eligible"] is False
    assert payload["experience_mode_summary"]["premium_surface_allowed"] is False
