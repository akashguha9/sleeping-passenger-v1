from pathlib import Path

from scripts.action_engine import build_action_report
from scripts.archetype_profile import build_archetype_profile_report
from scripts.pipeline_health_report import build_pipeline_health_report
from scripts.runtime_common import build_runtime_state_from_scm_report_payload
from scripts.signal_conversion_monitor import build_signal_conversion_report
from scripts.signal_refinery import build_signal_refinery_report
from scripts.trend_engine import build_trend_report


REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_SNAPSHOT_LOG = REPO_ROOT / "tests" / "fixtures" / "system_snapshots_seed.jsonl"


def test_pipeline_health_report_includes_archetype_and_closure_layers() -> None:
    payload = build_pipeline_health_report(
        include_tests=False,
        write_runtime=False,
        runtime_state=build_runtime_state_from_scm_report_payload(build_signal_conversion_report()),
    )

    assert "closure_deficit" in payload
    assert "archetype_profile" in payload
    assert payload["archetype_profile"]["governance_boundary"]["suggestion_only"] is True
    assert payload["archetype_profile"]["governance_boundary"]["live_execution_enabled"] is False


def test_archetype_profile_friction_drops_when_blockers_clear() -> None:
    live_payload = build_pipeline_health_report(
        include_tests=False,
        write_runtime=False,
        runtime_state=build_runtime_state_from_scm_report_payload(build_signal_conversion_report()),
    )
    all_clear_payload = build_pipeline_health_report(
        include_tests=False,
        write_runtime=False,
        runtime_state=build_runtime_state_from_scm_report_payload(
            build_signal_conversion_report(simulate_all_clear=True)
        ),
    )

    live_score = live_payload["archetype_profile"]["friction_detector"]["friction_score"]
    all_clear_score = all_clear_payload["archetype_profile"]["friction_detector"]["friction_score"]

    assert live_score > all_clear_score


def test_entropy_tagger_does_not_label_everything_as_opportunity() -> None:
    payload = build_pipeline_health_report(
        include_tests=False,
        write_runtime=False,
        runtime_state=build_runtime_state_from_scm_report_payload(build_signal_conversion_report()),
    )
    states = [row["entropy_state"] for row in payload["archetype_profile"]["action_profiles"]]

    assert "UNSTABLE_NOISE" in states
    assert states.count("CLEAN_OPPORTUNITY") + states.count("BOUNDED_ENTROPY_OPPORTUNITY") < len(states)


def test_archetype_profile_stays_truth_first_under_sparse_data() -> None:
    runtime_state = build_runtime_state_from_scm_report_payload(build_signal_conversion_report())
    action_report = build_action_report(runtime_state=runtime_state, write_runtime=False)
    sparse_signal_refinery_report = {
        "signal_admission_gate": {"signal_rows": []},
        "validation_engine": {"signals": []},
        "launch_control": {"launch_rows": [], "review_ready_count": 0, "blocked_crowding_count": 0},
        "thermal_battery_manager": {"thermal_state": "CONSTRAINED", "position_headroom": 0, "cluster_concentration": [], "deployment_allowed": False, "chaos_open_position_count": 0, "max_open_positions": 1},
        "repeatability_tracker": {"trade_close_count": 0},
    }

    report = build_archetype_profile_report(
        runtime_state=runtime_state,
        action_report=action_report,
        signal_refinery_report=sparse_signal_refinery_report,
        friction_report={"friction_band": "LOW_FRICTION", "components": []},
        trend_report=build_trend_report(log_path=SEED_SNAPSHOT_LOG, write_runtime=False),
        governance_feedback_report={"override_summary": {}},
        closure_deficit_report={
            "closure_deficit_state": "SPARSE",
            "counts": {"actions_reconciled_with_sufficient_evidence": 0},
            "gap_components": [],
            "ratios": {},
        },
        operator_control_report={"drift_monitor": {}},
        blocked_promotable_candidate_queue=[],
        gate_resolution_preview={},
        entry_review_packets=[],
        transition_review_packets=[],
        packet_summary={},
        write_runtime=False,
    )

    first = report["action_profiles"][0]
    assert first["profile_confidence"]["state"] == "SPARSE"
    assert first["composite_archetype_score"] <= 0.6
    assert report["governance_boundary"]["suggestion_only"] is True
