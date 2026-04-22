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
    from scripts.artifact_coherence_check import build_artifact_coherence_report
    from scripts.pipeline_health_report import build_pipeline_health_report
    from scripts.repo_operating_mode import build_operating_mode_report
except ModuleNotFoundError:
    from artifact_coherence_check import build_artifact_coherence_report
    from pipeline_health_report import build_pipeline_health_report
    from repo_operating_mode import build_operating_mode_report


REQUIRED_PROVENANCE_FIELDS = [
    "run_id",
    "source_mode",
    "operating_mode",
    "truth_origin",
    "artifact_written_at",
    "commit_hash",
    "config_fingerprint",
]


def _has_basic_provenance(payload: dict[str, Any]) -> bool:
    return all(payload.get(field) not in {None, ""} for field in REQUIRED_PROVENANCE_FIELDS)


def _deployment_permission_state(health_report: dict[str, Any], mode_report: dict[str, Any]) -> str:
    if bool(health_report.get("can_deploy_capital")):
        return "permitted"
    if bool(mode_report.get("paper_execution_enabled")) or bool(mode_report.get("live_execution_enabled")):
        return "configured_but_blocked"
    return "restricted"


def build_governance_status_report() -> dict[str, Any]:
    mode_report = build_operating_mode_report()
    health_report = build_pipeline_health_report(include_tests=False, write_runtime=False)
    coherence_report = build_artifact_coherence_report()
    provenance_present = _has_basic_provenance(health_report)
    if coherence_report["coherent"]:
        artifact_coherence_state = "coherent"
    elif coherence_report["legacy_artifacts"]:
        artifact_coherence_state = "legacy_polluted"
    else:
        artifact_coherence_state = "incoherent"
    provenance_state = "basic" if provenance_present else "partial"

    return {
        "operating_mode": mode_report["operating_mode"],
        "truth_origin": mode_report["truth_origin"],
        "system_readiness_state": health_report["system_readiness_state"],
        "can_deploy_capital": health_report["can_deploy_capital"],
        "deployment_permission_state": _deployment_permission_state(health_report, mode_report),
        "quote_provider_state": mode_report["quote_provider_state"],
        "paper_execution_enabled": mode_report["paper_execution_enabled"],
        "live_execution_enabled": mode_report["live_execution_enabled"],
        "controls": {
            "artifact_coherence": {
                "state": artifact_coherence_state,
                "legacy_artifact_count": len(coherence_report["legacy_artifacts"]),
                "legacy_artifacts": coherence_report["legacy_artifacts"],
                "note": (
                    "Current coherence state is derived from the standalone artifact check, "
                    "not assumed from stamping support alone."
                ),
            },
            "provenance": {
                "state": provenance_state,
                "note": "Artifacts carry run_id, source_mode, commit_hash, and config_fingerprint.",
            },
            "operator_integrity": {
                "state": "partial",
                "note": (
                    "The tree now carries advisory first-principles governance fields and "
                    "override/interaction ledgers, but it still lacks a hard operator-"
                    "integrity block or emotional-trigger enforcement layer."
                ),
            },
            "disclosure_discipline": {
                "state": "partial",
                "note": (
                    "The repo is explicit about seeded mode and placeholder adapters, "
                    "but it has no separate redaction or disclosure-policy module."
                ),
            },
        },
        "note": (
            "This is a conservative status view over the current tree. It does not imply "
            "a separate governance framework exists."
        ),
    }


def format_governance_status_summary(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Governance Status",
            f"operating_mode={report['operating_mode']}",
            f"truth_origin={report['truth_origin']}",
            f"system_readiness_state={report['system_readiness_state']}",
            f"can_deploy_capital={str(report['can_deploy_capital']).lower()}",
            f"deployment_permission_state={report['deployment_permission_state']}",
            f"artifact_coherence_state={report['controls']['artifact_coherence']['state']}",
            f"provenance_state={report['controls']['provenance']['state']}",
            f"operator_integrity_state={report['controls']['operator_integrity']['state']}",
            f"disclosure_discipline_state={report['controls']['disclosure_discipline']['state']}",
        ]
    )


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Summarize the current tree's conservative governance posture."
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--summary", action="store_true", help="Emit a compact human-readable summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    report = build_governance_status_report()
    if args.summary:
        print(format_governance_status_summary(report))
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
