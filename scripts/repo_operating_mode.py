from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from scripts.runtime_common import (
        build_deployment_permissions,
        build_runtime_state_from_scm_report_payload,
        build_truth_context,
        classify_operating_mode,
        stamp_payload,
    )
    from scripts.signal_conversion_monitor import build_signal_conversion_report
except ModuleNotFoundError:
    from runtime_common import (
        build_deployment_permissions,
        build_runtime_state_from_scm_report_payload,
        build_truth_context,
        classify_operating_mode,
        stamp_payload,
    )
    from signal_conversion_monitor import build_signal_conversion_report


def _mode_reason(report: dict[str, Any]) -> str:
    mode = report["operating_mode"]
    if mode == "seeded":
        return "Seeded mode: local-file-driven signals, placeholder quote contract, and no execution path enabled."
    if mode == "hybrid":
        return "Hybrid mode: at least one external observation surface is active, but execution remains detached."
    if mode == "paper_prepared":
        return "Paper-prepared mode: paper execution is enabled, but live execution is still off."
    if mode == "live_prepared":
        return "Live-prepared mode: external observation and live execution are both enabled."
    return "Operating mode is unknown."


def build_operating_mode_report(runtime_state: dict[str, Any] | None = None) -> dict[str, Any]:
    state = runtime_state or build_runtime_state_from_scm_report_payload(
        build_signal_conversion_report()
    )
    truth_context = build_truth_context(state)
    deployment = build_deployment_permissions(state)
    report = {
        "operating_mode": classify_operating_mode(state),
        "truth_origin": truth_context["truth_origin"],
        "truth_origin_tags": truth_context["truth_origin_tags"],
        "source_mode": truth_context["source_mode"],
        "quote_provider": truth_context["quote_provider"],
        "quote_provider_state": truth_context["quote_provider_state"],
        "live_quotes_available": truth_context["live_quotes_available"],
        "paper_execution_enabled": deployment["paper_execution_enabled"],
        "live_execution_enabled": deployment["live_execution_enabled"],
    }
    report["mode_reason"] = _mode_reason(report)
    return stamp_payload(report, runtime_state=state)


def format_operating_mode_summary(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Repo Operating Mode",
            f"operating_mode={report['operating_mode']}",
            f"truth_origin={report['truth_origin']}",
            f"source_mode={report['source_mode']}",
            f"quote_provider_state={report['quote_provider_state']}",
            f"paper_execution_enabled={str(report['paper_execution_enabled']).lower()}",
            f"live_execution_enabled={str(report['live_execution_enabled']).lower()}",
            f"mode_reason={report['mode_reason']}",
        ]
    )


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize the repo operating mode from current local runtime state.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--summary", action="store_true", help="Emit a compact human-readable summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    report = build_operating_mode_report()
    if args.summary:
        print(format_operating_mode_summary(report))
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
