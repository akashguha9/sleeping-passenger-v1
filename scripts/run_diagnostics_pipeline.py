from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from scripts.action_engine import build_action_report
    from scripts.blocker_cost_engine import build_blocker_cost_report
    from scripts.pipeline_health_report import (
        build_pipeline_health_report,
        build_runtime_state_from_scm_report,
        format_pipeline_health_summary,
    )
    from scripts.runtime_common import (
        SNAPSHOT_LOG_PATH,
        persist_current_runtime_state,
        resolve_source_mode,
    )
    from scripts.signal_conversion_monitor import build_signal_conversion_report
    from scripts.snapshot_logger import build_snapshot_row, log_snapshot
    from scripts.trend_engine import build_trend_report
except ModuleNotFoundError:
    from action_engine import build_action_report
    from blocker_cost_engine import build_blocker_cost_report
    from pipeline_health_report import (
        build_pipeline_health_report,
        build_runtime_state_from_scm_report,
        format_pipeline_health_summary,
    )
    from runtime_common import (
        SNAPSHOT_LOG_PATH,
        persist_current_runtime_state,
        resolve_source_mode,
    )
    from signal_conversion_monitor import build_signal_conversion_report
    from snapshot_logger import build_snapshot_row, log_snapshot
    from trend_engine import build_trend_report


def run_diagnostics_pipeline(
    include_tests: bool = False,
    write_runtime: bool = True,
    write_snapshot: bool = False,
    snapshot_log_path: Path | None = None,
    simulate_gsce_clear: bool = False,
    simulate_realm_bis_clear: bool = False,
    simulate_all_clear: bool = False,
) -> dict:
    # Resolve source_mode once per pipeline run. All runtime/*.json artifacts
    # written during this run will inherit this value via runtime_common's
    # stamp_payload() hook in write_json_atomic(). This is what prevents the
    # coherence drift described in the Windows audit (vocoder reporting
    # SYNTHETIC_RUNTIME_FALLBACK while behavioral_review reports LIVE_ETIL).
    resolve_source_mode()

    simulation_requested = any(
        [simulate_gsce_clear, simulate_realm_bis_clear, simulate_all_clear]
    )
    scm_report = build_signal_conversion_report(
        simulate_gsce_clear=simulate_gsce_clear,
        simulate_realm_bis_clear=simulate_realm_bis_clear,
        simulate_all_clear=simulate_all_clear,
    )
    runtime_state = build_runtime_state_from_scm_report(scm_report)
    scenario = str(runtime_state.get("simulation_context", {}).get("scenario") or "LIVE").upper()
    resolved_snapshot_log_path = snapshot_log_path or SNAPSHOT_LOG_PATH
    effective_write_runtime = write_runtime and not simulation_requested

    if effective_write_runtime:
        persist_current_runtime_state(runtime_state)

    action_report = build_action_report(
        runtime_state=runtime_state,
        write_runtime=effective_write_runtime,
    )
    friction_report = build_blocker_cost_report(
        runtime_state=runtime_state,
        write_runtime=effective_write_runtime,
    )

    latest_snapshot_timestamp = None
    current_snapshot_row = None
    should_write_snapshot = effective_write_runtime or write_snapshot
    if should_write_snapshot:
        snapshot_row = log_snapshot(path=resolved_snapshot_log_path, runtime_state=runtime_state)
        latest_snapshot_timestamp = snapshot_row.get("timestamp")
    elif simulation_requested:
        current_snapshot_row = build_snapshot_row(
            runtime_state=runtime_state,
            snapshot_path=resolved_snapshot_log_path,
        )

    trend_report = build_trend_report(
        log_path=resolved_snapshot_log_path,
        write_runtime=effective_write_runtime,
        current_snapshot_row=current_snapshot_row,
        scenario_scope=scenario,
    )
    report = build_pipeline_health_report(
        include_tests=include_tests,
        write_runtime=effective_write_runtime,
        runtime_state=runtime_state,
        action_report=action_report,
        friction_report=friction_report,
        trend_report=trend_report,
        latest_snapshot_timestamp=latest_snapshot_timestamp,
        simulate_gsce_clear=simulate_gsce_clear,
        simulate_realm_bis_clear=simulate_realm_bis_clear,
        simulate_all_clear=simulate_all_clear,
    )
    return report


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
    parser.add_argument(
        "--write-snapshot",
        action="store_true",
        help="Persist a scenario-tagged snapshot row even during simulation mode.",
    )
    simulation = parser.add_mutually_exclusive_group()
    simulation.add_argument(
        "--simulate-gsce-clear",
        action="store_true",
        help="Preview the GSCE-clear transition path without writing runtime artifacts.",
    )
    simulation.add_argument(
        "--simulate-realm-bis-clear",
        action="store_true",
        help="Preview the REALM_BIS-clear transition path without writing runtime artifacts.",
    )
    simulation.add_argument(
        "--simulate-all-clear",
        action="store_true",
        help="Preview the fully cleared transition path without writing runtime artifacts.",
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
        write_snapshot=args.write_snapshot,
        simulate_gsce_clear=args.simulate_gsce_clear,
        simulate_realm_bis_clear=args.simulate_realm_bis_clear,
        simulate_all_clear=args.simulate_all_clear,
    )
    if args.summary:
        print(format_pipeline_health_summary(report))
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
