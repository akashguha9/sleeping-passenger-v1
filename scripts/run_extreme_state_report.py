from __future__ import annotations

import argparse
import json
from typing import Any

try:
    from scripts.extreme_state import build_extreme_state_report, format_extreme_state_summary
    from scripts.runtime_common import load_current_pipeline_state
    from scripts.signal_conversion_monitor import build_signal_conversion_report
except ModuleNotFoundError:
    from extreme_state import build_extreme_state_report, format_extreme_state_summary  # type: ignore[no-redef]
    from runtime_common import load_current_pipeline_state  # type: ignore[no-redef]
    from signal_conversion_monitor import build_signal_conversion_report  # type: ignore[no-redef]


def _fallback_signals() -> list[dict[str, Any]]:
    return [
        {
            "signal_id": "SYN_EXTREME_001",
            "symbol": "EDGE",
            "policy_state": "RESTRICTED",
            "signal_strength_score": 0.72,
            "signal_validity_score": 0.66,
            "technique_score": 0.70,
            "structure_score": 0.58,
            "timing_score": 0.64,
            "sequence_quality": 0.74,
            "timing_precision": 0.70,
            "transfer_efficiency": 0.66,
            "contact_quality": 0.72,
            "access_score": 0.63,
            "angle_score": 0.58,
            "timing_access_score": 0.61,
            "constraint_reduction_score": 0.55,
            "successful_repetitions": 2,
            "total_attempts": 4,
            "stress_survival_score": 0.55,
            "persistence_score": 0.60,
            "trigger_presence_score": 0.45,
            "conversion_trigger_score": 0.45,
            "timing_window_score": 0.40,
            "opponent_weakness_score": 0.48,
            "opponent_counter_signal_strength": 0.54,
            "exit_clarity_score": 0.38,
            "stability_score": 0.72,
            "duration_zscore_normalized": 0.78,
            "transition_count": 0,
            "transition_rate": 0.12,
            "cost_increase_score": 0.62,
            "visible_volatility_score": 0.22,
            "time_cost": 0.52,
            "mental_cost": 0.44,
            "opportunity_cost": 0.58,
            "risk_cost": 0.50,
            "warnings": ["synthetic_fallback_signal"],
        }
    ]


def _load_signal_rows() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    state = load_current_pipeline_state(prefer_runtime_files=True)
    rows = state.get("per_signal_attribution", [])
    if isinstance(rows, list) and rows:
        return [row for row in rows if isinstance(row, dict)], state
    scm_report = build_signal_conversion_report()
    state = {
        "execution_policy": scm_report.get("execution_policy", {}),
        "per_signal_attribution": scm_report.get("per_signal_attribution", []),
        "scm_review": scm_report.get("scm_review", {}),
    }
    rows = scm_report.get("per_signal_attribution", [])
    if isinstance(rows, list) and rows:
        return [row for row in rows if isinstance(row, dict)], state
    return _fallback_signals(), {"execution_policy": {"policy_state": "RESTRICTED"}}


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the extreme-state logic report.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--summary", action="store_true", help="Emit compact summary output.")
    mode.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Do not persist runtime/extreme_state_report.json.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    rows, state = _load_signal_rows()
    report = build_extreme_state_report(rows, runtime_state=state, write_runtime=not args.no_write)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(format_extreme_state_summary(report))
        if report.get("truth_origin") == "seeded":
            print("warning=all inputs remain seeded or synthetic; external reality is not connected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
