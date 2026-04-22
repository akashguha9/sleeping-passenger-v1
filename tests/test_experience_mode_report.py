import json
from pathlib import Path

from scripts.experience_mode_report import (
    build_experience_mode_report,
    format_experience_mode_summary,
)
from scripts.runtime_common import build_runtime_state_from_scm_report_payload
from scripts.signal_conversion_monitor import build_signal_conversion_report


def _runtime_state() -> dict:
    return build_runtime_state_from_scm_report_payload(build_signal_conversion_report())


def test_experience_mode_report_defaults_to_trainer_for_seeded_early_state(
    scratch_path: Path,
) -> None:
    runtime_state = _runtime_state()
    output_path = scratch_path / "experience_mode_report.json"

    report = build_experience_mode_report(
        runtime_state=runtime_state,
        health_report={
            "visibility_timing_context": {
                "average_light_score": 0.42,
                "average_shadow_score": 0.58,
                "average_temporal_position": 0.35,
                "phase_distribution": {"crescent": 2, "quarter": 1},
                "full_context_coverage_ratio": 0.75,
                "context_scored_count": 3,
                "trap_flag_rate": 0.0,
            }
        },
        governance_status_report={
            "controls": {
                "artifact_coherence": {"state": "legacy_polluted"},
                "provenance": {"state": "basic"},
            }
        },
        governance_feedback_report={
            "gate_usage": {"average_fpeg_score": 0.85},
            "interaction_quality_summary": {"average_score": 0.6},
        },
        operating_mode_report={
            "operating_mode": "seeded",
            "live_execution_enabled": False,
        },
        reconciliation_summary={
            "total_closed_paper_trades": 2,
            "sample_size_for_learning": 2,
            "evidence_strength": "insufficient_evidence",
            "unresolved_data_gap_rate": 0.5,
            "leakage_diagnostics": {"missing_mark_frequency": 0.5},
        },
        reconciliation_history_rows=[
            {"lineage_completeness_score": 0.8},
            {"lineage_completeness_score": 0.9},
        ],
        output_path=output_path,
        write_runtime=True,
    )

    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["trainer_mode_metadata"]["trainer_mode_active"] is True
    assert report["trainer_mode_metadata"]["recommended_surface_profile"] == "trainer"
    assert report["readiness_ladder"]["trainer_readiness"] >= 0.55
    assert report["utility_resilience_layer"]["degraded_mode_required"] is True
    assert report["premium_compression_layer"]["premium_surface_eligible"] is False
    assert written["artifact_kind"] == "experience_mode_report"


def test_experience_mode_report_handles_missing_reconciliation_history() -> None:
    report = build_experience_mode_report(
        runtime_state=_runtime_state(),
        health_report={
            "visibility_timing_context": {
                "average_light_score": 0.3,
                "average_shadow_score": 0.7,
                "average_temporal_position": 0.2,
                "phase_distribution": {"new_moon": 1},
                "full_context_coverage_ratio": 0.25,
                "context_scored_count": 1,
                "trap_flag_rate": 0.0,
            }
        },
        governance_status_report={
            "controls": {
                "artifact_coherence": {"state": "legacy_polluted"},
                "provenance": {"state": "basic"},
            }
        },
        governance_feedback_report={
            "gate_usage": {"average_fpeg_score": 0.5},
            "interaction_quality_summary": {"average_score": None},
        },
        operating_mode_report={
            "operating_mode": "paper_prepared",
            "live_execution_enabled": False,
        },
        reconciliation_summary={
            "total_closed_paper_trades": 0,
            "sample_size_for_learning": 0,
            "evidence_strength": "insufficient_evidence",
            "unresolved_data_gap_rate": None,
            "leakage_diagnostics": {"missing_mark_frequency": None},
        },
        reconciliation_history_rows=[],
        write_runtime=False,
    )

    assert report["visibility_legibility_layer"]["average_lineage_completeness_score"] is None
    assert report["readiness_ladder"]["recommended_surface_profile"] == "trainer"
    summary = format_experience_mode_summary(report)
    assert "Experience Mode Report" in summary
    assert "recommended_surface_profile=trainer" in summary
