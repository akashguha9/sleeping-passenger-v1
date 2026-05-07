from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts.extreme_state.extreme_state_report import build_extreme_state_report
from scripts.run_diagnostics_pipeline import run_diagnostics_pipeline


REPO_ROOT = Path(__file__).resolve().parents[1]


def _base_signal() -> dict:
    return {
        "signal_id": "SIG_X",
        "symbol": "EDGE",
        "policy_state": "READY",
        "signal_strength_score": 0.76,
        "signal_validity_score": 0.72,
        "technique_score": 0.70,
        "structure_score": 0.60,
        "timing_score": 0.60,
        "sequence_quality": 0.60,
        "timing_precision": 0.60,
        "transfer_efficiency": 0.60,
        "contact_quality": 0.60,
        "access_score": 0.55,
        "angle_score": 0.55,
        "timing_access_score": 0.55,
        "constraint_reduction_score": 0.55,
        "successful_repetitions": 2,
        "total_attempts": 4,
        "stress_survival_score": 0.60,
        "trigger_presence_score": 0.60,
        "conversion_trigger_score": 0.60,
        "timing_window_score": 0.60,
        "opponent_weakness_score": 0.55,
        "opponent_counter_signal_strength": 0.30,
        "exit_clarity_score": 0.70,
        "stability_score": 0.55,
        "duration_zscore_normalized": 0.25,
        "transition_count": 1,
        "transition_rate": 0.60,
        "cost_increase_score": 0.20,
        "visible_volatility_score": 0.45,
        "time_cost": 0.20,
        "mental_cost": 0.20,
        "opportunity_cost": 0.20,
        "risk_cost": 0.20,
    }


def test_extreme_state_report_contains_required_top_level_keys(scratch_path) -> None:
    report = build_extreme_state_report(
        [_base_signal()],
        runtime_state={"execution_policy": {"policy_state": "READY"}},
        output_path=scratch_path / "extreme_state_report.json",
        events_path=scratch_path / "extreme_state_events.jsonl",
        write_runtime=True,
    )
    assert report["report_path"].endswith("extreme_state_report.json")
    assert report["events_path"].endswith("extreme_state_events.jsonl")
    assert "run_id" in report
    assert "scores" in report
    assert "signals" in report
    assert "extreme_state_logic" in report
    assert (scratch_path / "extreme_state_report.json").exists()
    assert (scratch_path / "extreme_state_events.jsonl").exists()


def test_pipeline_health_report_includes_extreme_state_summary() -> None:
    report = run_diagnostics_pipeline(write_runtime=False)
    assert "extreme_state_logic" in report
    assert "extreme_state_signals_evaluated" in report
    assert "extreme_state_report_path" in report


def test_run_extreme_state_report_summary_cli() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "run_extreme_state_report.py"), "--summary", "--no-write"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    output = result.stdout
    assert "Extreme State Report" in output
    assert "extreme_state=" in output
    assert "signals_evaluated=" in output
    assert "recommended_action=" in output
