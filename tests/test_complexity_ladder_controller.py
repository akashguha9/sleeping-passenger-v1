from __future__ import annotations

import json
from pathlib import Path

from scripts.complexity_ladder_controller import build_complexity_ladder_controller
from scripts.runtime_common import build_runtime_state_from_scm_report_payload
from scripts.signal_conversion_monitor import build_signal_conversion_report


def _runtime_state() -> dict:
    return build_runtime_state_from_scm_report_payload(build_signal_conversion_report())


def _hybrid_runtime_state() -> dict:
    state = _runtime_state()
    state["external_observation_active"] = True
    state["external_observation_source"] = "yahoo_finance"
    state["external_observation_fetched_at"] = "2026-04-23T10:15:00+00:00"
    return state


def _experience_report(
    *,
    operating_mode: str = "seeded",
    recommended_surface_profile: str = "trainer",
    trainer_mode_active: bool = True,
    utility_readiness: float = 0.6,
    jet_readiness: float = 0.55,
    unresolved_data_gap_rate: float = 0.0,
    degraded_mode_required: bool = False,
    premium_surface_eligible: bool = False,
) -> dict:
    return {
        "operating_mode": operating_mode,
        "trainer_mode_metadata": {
            "trainer_mode_active": trainer_mode_active,
            "recommended_surface_profile": recommended_surface_profile,
        },
        "readiness_ladder": {
            "recommended_surface_profile": recommended_surface_profile,
            "utility_readiness": utility_readiness,
            "jet_readiness": jet_readiness,
        },
        "visibility_legibility_layer": {
            "unresolved_data_gap_rate": unresolved_data_gap_rate,
        },
        "utility_resilience_layer": {
            "degraded_mode_required": degraded_mode_required,
        },
        "premium_compression_layer": {
            "premium_surface_eligible": premium_surface_eligible,
        },
    }


def test_seeded_mode_forces_trainer_safe_exposure(monkeypatch) -> None:
    monkeypatch.setenv("PIPELINE_ENABLE_PAPER_EXECUTION", "false")
    monkeypatch.setenv("PIPELINE_ENABLE_LIVE_EXECUTION", "false")

    report = _experience_report(
        operating_mode="hybrid",
        recommended_surface_profile="jet",
        trainer_mode_active=False,
        utility_readiness=0.95,
        jet_readiness=0.95,
        unresolved_data_gap_rate=0.0,
        degraded_mode_required=False,
        premium_surface_eligible=True,
    )

    controller = build_complexity_ladder_controller(
        report_payload=report,
        runtime_state=_runtime_state(),
        write_runtime=False,
    )

    assert controller["operating_mode"] == "seeded"
    assert controller["trainer_surface_allowed"] is True
    assert controller["utility_surface_allowed"] is False
    assert controller["premium_surface_allowed"] is False
    assert controller["operator_surface_recommendation"] == "trainer"
    assert controller["explanation_heavy_required"] is True
    assert "seeded_mode_forces_trainer_surface" in controller["controller_reasoning"]


def test_low_jet_readiness_disables_premium_surface(monkeypatch) -> None:
    monkeypatch.setenv("PIPELINE_ENABLE_PAPER_EXECUTION", "false")
    monkeypatch.setenv("PIPELINE_ENABLE_LIVE_EXECUTION", "false")

    controller = build_complexity_ladder_controller(
        report_payload=_experience_report(
            operating_mode="hybrid",
            recommended_surface_profile="jet",
            trainer_mode_active=False,
            utility_readiness=0.82,
            jet_readiness=0.55,
            unresolved_data_gap_rate=0.0,
            degraded_mode_required=False,
            premium_surface_eligible=True,
        ),
        runtime_state=_hybrid_runtime_state(),
        write_runtime=False,
    )

    assert controller["operating_mode"] == "hybrid"
    assert controller["utility_surface_allowed"] is True
    assert controller["premium_surface_allowed"] is False
    assert controller["operator_surface_recommendation"] == "utility"
    assert "jet_readiness_below_threshold" in controller["controller_reasoning"]


def test_missing_artifact_falls_back_safely(
    scratch_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PIPELINE_ENABLE_PAPER_EXECUTION", "false")
    monkeypatch.setenv("PIPELINE_ENABLE_LIVE_EXECUTION", "false")

    output_path = scratch_path / "complexity_ladder_controller.json"
    controller = build_complexity_ladder_controller(
        runtime_state=_runtime_state(),
        input_path=scratch_path / "missing_experience_mode_report.json",
        output_path=output_path,
        write_runtime=True,
    )

    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert controller["trainer_surface_allowed"] is True
    assert controller["utility_surface_allowed"] is False
    assert controller["premium_surface_allowed"] is False
    assert controller["explanation_heavy_required"] is True
    assert controller["degraded_mode_annotations_required"] is True
    assert controller["drilldown_required"] is True
    assert controller["operator_surface_recommendation"] == "trainer"
    assert "experience_mode_report_missing" in controller["controller_reasoning"]
    assert written["artifact_kind"] == "complexity_ladder_controller"


def test_unresolved_gap_breaches_force_premium_surface_false(monkeypatch) -> None:
    monkeypatch.setenv("PIPELINE_ENABLE_PAPER_EXECUTION", "false")
    monkeypatch.setenv("PIPELINE_ENABLE_LIVE_EXECUTION", "false")

    controller = build_complexity_ladder_controller(
        report_payload=_experience_report(
            operating_mode="hybrid",
            recommended_surface_profile="jet",
            trainer_mode_active=False,
            utility_readiness=0.92,
            jet_readiness=0.93,
            unresolved_data_gap_rate=0.35,
            degraded_mode_required=False,
            premium_surface_eligible=True,
        ),
        runtime_state=_hybrid_runtime_state(),
        write_runtime=False,
    )

    assert controller["utility_surface_allowed"] is True
    assert controller["premium_surface_allowed"] is False
    assert controller["degraded_mode_annotations_required"] is True
    assert controller["operator_surface_recommendation"] == "utility"
    assert "unresolved_gap_breach_forces_no_premium" in controller["controller_reasoning"]
