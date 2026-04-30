import subprocess
import sys
from pathlib import Path

from scripts.run_diagnostics_pipeline import run_diagnostics_pipeline
from scripts.perception_control import build_perception_control_report
from scripts.runtime_common import build_runtime_state_from_scm_report_payload
from scripts.signal_conversion_monitor import build_signal_conversion_report
from scripts.signal_refinery import build_signal_refinery_report
from scripts.snapshot_logger import build_snapshot_row
from scripts.trend_engine import build_trend_report


REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_SNAPSHOT_LOG = REPO_ROOT / "tests" / "fixtures" / "system_snapshots_seed.jsonl"


def test_signal_refinery_live_seed_shape() -> None:
    runtime_state = build_runtime_state_from_scm_report_payload(
        build_signal_conversion_report()
    )
    trend_report = build_trend_report(log_path=SEED_SNAPSHOT_LOG, write_runtime=False)

    report = build_signal_refinery_report(
        runtime_state=runtime_state,
        trend_report=trend_report,
        write_runtime=False,
    )

    assert report["horsepower_monitor"]["signal_count_total"] == 8
    assert report["horsepower_monitor"]["signals_above_threshold"] == 7
    assert report["signal_admission_gate"]["admitted_count"] == 4
    assert set(report["signal_admission_gate"]["rejected_tickers"]) == {"FCG", "GLD", "UNG"}
    assert report["validation_engine"]["validated_signal_count"] == 2
    assert report["launch_control"]["review_ready_count"] == 0
    assert report["launch_control"]["deployable_signal_count"] == 0
    assert report["thermal_battery_manager"]["thermal_state"] == "COOLING"
    assert report["repeatability_tracker"]["trade_close_count"] == 4
    assert report["maintenance_wear_log"]["veto_override_count"] == 2
    assert report["time_to_valid_signal_kpi"]["measurement_mode"] == "HEURISTIC_SIGNAL_ID_CLOCK"
    assert report["decision_engine_summary"]["current_operating_mode"] == "VALIDATED_BUT_DEPLOYMENT_BLOCKED"
    assert "visibility_timing_context" in report
    assert report["visibility_timing_context"]["context_scored_count"] == len(
        report["validation_engine"]["signals"]
    )
    first_signal = report["validation_engine"]["signals"][0]
    assert 0.0 <= first_signal["light_score"] <= 1.0
    assert 0.0 <= first_signal["shadow_score"] <= 1.0
    assert 0.0 <= first_signal["temporal_position"] <= 1.0
    assert first_signal["moon_phase"] in {
        "new_moon",
        "crescent",
        "quarter",
        "gibbous",
        "full_moon",
        "waning",
    }


def test_signal_refinery_all_clear_reviews_candidates_but_blocks_deployment() -> None:
    runtime_state = build_runtime_state_from_scm_report_payload(
        build_signal_conversion_report(simulate_all_clear=True)
    )
    report = build_signal_refinery_report(runtime_state=runtime_state, write_runtime=False)
    rows = {row["ticker"]: row for row in report["launch_control"]["launch_rows"]}

    assert report["launch_control"]["review_ready_names"] == ["RTX", "ZIM"]
    assert report["launch_control"]["deployable_signal_count"] == 0
    assert rows["RTX"]["launch_state"] == "REVIEW_READY"
    assert rows["ZIM"]["launch_state"] == "REVIEW_READY"
    assert "GLD" not in rows
    assert report["decision_engine_summary"]["current_operating_mode"] == "VALIDATED_BUT_DEPLOYMENT_BLOCKED"


def test_snapshot_row_carries_signal_refinery_metrics() -> None:
    runtime_state = build_runtime_state_from_scm_report_payload(
        build_signal_conversion_report()
    )
    runtime_state["signal_refinery"] = build_signal_refinery_report(
        runtime_state=runtime_state,
        trend_report=build_trend_report(log_path=SEED_SNAPSHOT_LOG, write_runtime=False),
        write_runtime=False,
    )
    runtime_state["perception_control"] = build_perception_control_report(
        runtime_state=runtime_state,
        signal_refinery_report=runtime_state["signal_refinery"],
        trend_report=build_trend_report(log_path=SEED_SNAPSHOT_LOG, write_runtime=False),
        write_runtime=False,
    )

    row = build_snapshot_row(runtime_state=runtime_state)

    assert row["validated_signal_count"] == 2
    assert row["decision_grade_signal_count"] == 2
    assert row["thermal_state"] == "COOLING"
    assert row["rolling_expectancy_pct"] == -1.935
    assert row["perception_control_state"] == "CONSTRAINED"
    assert row["gravity_rejection_count"] == 2
    assert row["dominant_spectrum_class"] == "structural"


def test_signal_refinery_visibility_timing_summary_is_bounded() -> None:
    runtime_state = build_runtime_state_from_scm_report_payload(
        build_signal_conversion_report()
    )
    trend_report = build_trend_report(log_path=SEED_SNAPSHOT_LOG, write_runtime=False)

    report = build_signal_refinery_report(
        runtime_state=runtime_state,
        trend_report=trend_report,
        write_runtime=False,
    )

    summary = report["visibility_timing_context"]
    assert 0.0 <= summary["average_light_score"] <= 1.0
    assert 0.0 <= summary["average_shadow_score"] <= 1.0
    assert 0.0 <= summary["average_temporal_position"] <= 1.0
    assert summary["context_scored_count"] == len(report["validation_engine"]["signals"])
    assert summary["trap_flag_count"] <= summary["context_scored_count"]


def test_run_diagnostics_pipeline_includes_signal_refinery() -> None:
    payload = run_diagnostics_pipeline(write_runtime=False)

    assert payload["signal_refinery"]["validation_engine"]["validated_signal_count"] == 2
    assert payload["signal_refinery"]["launch_control"]["review_ready_count"] == 0
    assert payload["perception_control"]["perception_control_state"] == "BALANCED"
    assert payload["perception_control"]["noise_suppression_ratio"] == 0.429
    assert payload["trends"]["validation_quality_trend"]["label"] in {
        "IMPROVING",
        "FLAT",
        "DETERIORATING",
    }
    assert payload["trends"]["decision_grade_signal_trend"]["label"] in {
        "IMPROVING",
        "FLAT",
        "DETERIORATING",
    }


def test_signal_refinery_summary_cli() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "signal_refinery.py"), "--summary"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    lines = result.stdout.strip().splitlines()
    assert lines[0] == "Signal Refinery"
    assert lines[1].startswith("operating_mode=")
    assert lines[2] == "signals_above_threshold=7"
    assert lines[3] == "admitted_signal_count=4"
    assert lines[4] == "rejected_signal_count=3"
    assert lines[5] == "validated_signal_count=2"
