from __future__ import annotations

import argparse
import json

try:
    from scripts.perception_control import build_perception_control_report
    from scripts.runtime_common import (
        SIGNAL_REFINERY_REPORT_PATH,
        TENNIS_ARCHETYPE_REPORT_PATH,
        build_runtime_state_from_scm_report_payload,
        load_json_file,
        repo_relative,
    )
    from scripts.signal_conversion_monitor import build_signal_conversion_report
    from scripts.signal_refinery import build_signal_refinery_report
    from scripts.tennis_archetype_execution import (
        format_tennis_archetype_summary,
        load_runtime_compatible_signals,
        synthetic_signals,
        write_tennis_archetype_report,
    )
except ModuleNotFoundError:
    from perception_control import build_perception_control_report
    from runtime_common import (  # type: ignore[no-redef]
        SIGNAL_REFINERY_REPORT_PATH,
        TENNIS_ARCHETYPE_REPORT_PATH,
        build_runtime_state_from_scm_report_payload,
        load_json_file,
        repo_relative,
    )
    from signal_conversion_monitor import build_signal_conversion_report  # type: ignore[no-redef]
    from signal_refinery import build_signal_refinery_report  # type: ignore[no-redef]
    from tennis_archetype_execution import (  # type: ignore[no-redef]
        format_tennis_archetype_summary,
        load_runtime_compatible_signals,
        synthetic_signals,
        write_tennis_archetype_report,
    )


def run_tennis_archetype_diagnostics(*, write_runtime: bool = True) -> dict:
    scm_report = build_signal_conversion_report()
    runtime_state = build_runtime_state_from_scm_report_payload(scm_report)
    signal_refinery_report = build_signal_refinery_report(
        runtime_state=runtime_state,
        trend_report={},
        write_runtime=False,
    )
    perception_control_report = build_perception_control_report(
        runtime_state=runtime_state,
        signal_refinery_report=signal_refinery_report,
        trend_report={},
        write_runtime=False,
    )
    signals = load_runtime_compatible_signals(
        runtime_state=runtime_state,
        signal_refinery_report=signal_refinery_report,
        perception_control_report=perception_control_report,
    )
    if not signals:
        fallback = load_json_file(SIGNAL_REFINERY_REPORT_PATH, default={})
        signals = load_runtime_compatible_signals(
            runtime_state=runtime_state,
            signal_refinery_report=fallback if isinstance(fallback, dict) else {},
            perception_control_report=perception_control_report,
        )
    if not signals:
        signals = synthetic_signals()
    report = write_tennis_archetype_report(
        signals,
        runtime_state=runtime_state,
        write_runtime=write_runtime,
    )
    report["report_path"] = repo_relative(TENNIS_ARCHETYPE_REPORT_PATH)
    return report


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run tennis archetype execution diagnostics.")
    parser.add_argument("--summary", action="store_true", help="Emit concise summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    report = run_tennis_archetype_diagnostics(write_runtime=True)
    if args.summary:
        print(format_tennis_archetype_summary(report))
    else:
        print(json.dumps(report["artifact"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
