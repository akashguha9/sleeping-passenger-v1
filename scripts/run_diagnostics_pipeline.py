from __future__ import annotations

import argparse
import json

try:
    from scripts.action_engine import build_action_report
    from scripts.blocker_cost_engine import build_blocker_cost_report
    from scripts.pipeline_health_report import (
        build_pipeline_health_report,
        build_runtime_state_from_scm_report,
        format_pipeline_health_summary,
    )
    from scripts.runtime_common import persist_current_runtime_state
    from scripts.signal_conversion_monitor import build_signal_conversion_report
    from scripts.snapshot_logger import log_snapshot
    from scripts.trend_engine import build_trend_report
except ModuleNotFoundError:
    from action_engine import build_action_report
    from blocker_cost_engine import build_blocker_cost_report
    from pipeline_health_report import (
        build_pipeline_health_report,
        build_runtime_state_from_scm_report,
        format_pipeline_health_summary,
    )
    from runtime_common import persist_current_runtime_state
    from signal_conversion_monitor import build_signal_conversion_report
    from snapshot_logger import log_snapshot
    from trend_engine import build_trend_report


def run_diagnostics_pipeline(
    include_tests: bool = False,
    write_runtime: bool = True,
) -> dict:
    scm_report = build_signal_conversion_report()
    runtime_state = build_runtime_state_from_scm_report(scm_report)

    if write_runtime:
        persist_current_runtime_state(runtime_state)

    action_report = build_action_report(
        runtime_state=runtime_state,
        write_runtime=write_runtime,
    )
    friction_report = build_blocker_cost_report(
        runtime_state=runtime_state,
        write_runtime=write_runtime,
    )

    latest_snapshot_timestamp = None
    if write_runtime:
        snapshot_row = log_snapshot(runtime_state=runtime_state)
        latest_snapshot_timestamp = snapshot_row.get("timestamp")

    trend_report = build_trend_report(write_runtime=write_runtime)
    return build_pipeline_health_report(
        include_tests=include_tests,
        write_runtime=write_runtime,
        runtime_state=runtime_state,
        action_report=action_report,
        friction_report=friction_report,
        trend_report=trend_report,
        latest_snapshot_timestamp=latest_snapshot_timestamp,
    )


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the full diagnostics pipeline in dependency order and emit the final health report."
    )
    parser.add_argument(
        "--include-tests",
        action="store_true",
        help="Run the targeted test slice as part of the final health report.",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Do not persist runtime artifacts while running the pipeline.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    mode.add_argument("--summary", action="store_true", help="Emit a compact human-readable summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)

    report = run_diagnostics_pipeline(
        include_tests=args.include_tests,
        write_runtime=not args.no_write,
    )
    if args.summary:
        print(format_pipeline_health_summary(report))
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
