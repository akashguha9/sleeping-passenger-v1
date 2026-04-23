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
    from scripts.blockscout_adapter import build_blockscout_report, write_blockscout_report
    from scripts.external_data_common import (
        READ_ONLY_CONTRACT,
        Transport,
        build_external_runtime_state,
        load_external_data_config,
    )
    from scripts.polymarket_clob_adapter import (
        build_polymarket_clob_report,
        write_polymarket_clob_report,
    )
    from scripts.polymarket_data_adapter import (
        build_polymarket_data_report,
        write_polymarket_data_report,
    )
    from scripts.polymarket_gamma_adapter import (
        build_polymarket_gamma_report,
        write_polymarket_gamma_report,
    )
    from scripts.runtime_common import (
        EXTERNAL_DATA_REPORT_PATH,
        load_current_pipeline_state,
        repo_relative,
        stamp_payload,
        utc_timestamp,
        write_json_atomic,
    )
except ModuleNotFoundError:
    from blockscout_adapter import build_blockscout_report, write_blockscout_report
    from external_data_common import (
        READ_ONLY_CONTRACT,
        Transport,
        build_external_runtime_state,
        load_external_data_config,
    )
    from polymarket_clob_adapter import build_polymarket_clob_report, write_polymarket_clob_report
    from polymarket_data_adapter import build_polymarket_data_report, write_polymarket_data_report
    from polymarket_gamma_adapter import build_polymarket_gamma_report, write_polymarket_gamma_report
    from runtime_common import (
        EXTERNAL_DATA_REPORT_PATH,
        load_current_pipeline_state,
        repo_relative,
        stamp_payload,
        utc_timestamp,
        write_json_atomic,
    )


SOURCE_NAME = "external_data_runtime_sync"


def apply_external_observation_report(
    runtime_state: dict[str, Any] | None,
    report: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = report if isinstance(report, dict) else {}
    fetched_at = str(payload.get("fetched_at") or utc_timestamp())
    active_sources = payload.get("active_sources", [])
    if not isinstance(active_sources, list):
        active_sources = []
    return build_external_runtime_state(
        runtime_state,
        active=bool(payload.get("external_observation_active")),
        source_name=SOURCE_NAME,
        fetched_at=fetched_at,
        active_sources=[str(value) for value in active_sources if str(value).strip()],
    )


def _provider_report_path(provider_name: str, config_path: Path | None = None) -> Path:
    config = load_external_data_config(config_path)
    providers = config.get("providers", {})
    provider_config = providers.get(provider_name, {}) if isinstance(providers, dict) else {}
    relative_path = str(provider_config.get("report_path") or "").strip()
    if relative_path:
        return REPO_ROOT / relative_path
    return EXTERNAL_DATA_REPORT_PATH.parent / f"{provider_name}.json"


def _provider_signal_output_path(provider_name: str, config_path: Path | None = None) -> Path | None:
    config = load_external_data_config(config_path)
    providers = config.get("providers", {})
    provider_config = providers.get(provider_name, {}) if isinstance(providers, dict) else {}
    if not isinstance(provider_config, dict):
        return None
    signal_ingestion = provider_config.get("signal_ingestion", {})
    if not isinstance(signal_ingestion, dict):
        return None
    relative_path = str(signal_ingestion.get("signal_output_path") or "").strip()
    if not relative_path:
        return None
    return REPO_ROOT / relative_path


def _build_source_reports(
    *,
    runtime_state: dict[str, Any] | None,
    config_path: Path | None,
    transport: Transport | None,
    fetched_at: str,
) -> dict[str, dict[str, Any]]:
    base_state = runtime_state or load_current_pipeline_state()
    return {
        "polymarket_gamma": build_polymarket_gamma_report(
            runtime_state=base_state,
            config_path=config_path,
            transport=transport,
            fetched_at=fetched_at,
        ),
        "polymarket_data": build_polymarket_data_report(
            runtime_state=base_state,
            config_path=config_path,
            transport=transport,
            fetched_at=fetched_at,
        ),
        "polymarket_clob": build_polymarket_clob_report(
            runtime_state=base_state,
            config_path=config_path,
            transport=transport,
            fetched_at=fetched_at,
        ),
        "blockscout": build_blockscout_report(
            runtime_state=base_state,
            config_path=config_path,
            transport=transport,
            fetched_at=fetched_at,
        ),
    }


def _write_source_reports(
    *,
    runtime_state: dict[str, Any] | None,
    config_path: Path | None,
    transport: Transport | None,
    fetched_at: str,
) -> dict[str, dict[str, Any]]:
    base_state = runtime_state or load_current_pipeline_state()
    return {
        "polymarket_gamma": write_polymarket_gamma_report(
            runtime_state=base_state,
            config_path=config_path,
            transport=transport,
            output_path=_provider_report_path("polymarket_gamma", config_path),
            signal_output_path=_provider_signal_output_path("polymarket_gamma", config_path),
            fetched_at=fetched_at,
        ),
        "polymarket_data": write_polymarket_data_report(
            runtime_state=base_state,
            config_path=config_path,
            transport=transport,
            output_path=_provider_report_path("polymarket_data", config_path),
            fetched_at=fetched_at,
        ),
        "polymarket_clob": write_polymarket_clob_report(
            runtime_state=base_state,
            config_path=config_path,
            transport=transport,
            output_path=_provider_report_path("polymarket_clob", config_path),
            fetched_at=fetched_at,
        ),
        "blockscout": write_blockscout_report(
            runtime_state=base_state,
            config_path=config_path,
            transport=transport,
            output_path=_provider_report_path("blockscout", config_path),
            fetched_at=fetched_at,
        ),
    }


def _build_aggregate_payload(
    *,
    runtime_state: dict[str, Any] | None,
    source_reports: dict[str, dict[str, Any]],
    config_path: Path | None,
    fetched_at: str,
) -> dict[str, Any]:
    base_state = runtime_state or load_current_pipeline_state()
    active_sources = [
        name
        for name, report in source_reports.items()
        if bool(report.get("external_observation_active"))
    ]
    source_summaries = [
        {
            "provider_name": name,
            "external_observation_active": bool(report.get("external_observation_active")),
            "success_count": int(report.get("success_count", 0)),
            "failure_count": int(report.get("failure_count", 0)),
            "coverage_state": report.get("coverage_state"),
            "report_path": repo_relative(_provider_report_path(name, config_path)),
        }
        for name, report in source_reports.items()
    ]
    limitations: list[str] = []
    for report in source_reports.values():
        for limitation in report.get("limitations", []):
            normalized = str(limitation).strip()
            if normalized and normalized not in limitations:
                limitations.append(normalized)

    effective_state = build_external_runtime_state(
        base_state,
        active=bool(active_sources),
        source_name=SOURCE_NAME,
        fetched_at=fetched_at,
        active_sources=active_sources,
    )
    provisional_state = build_external_runtime_state(
        base_state,
        active=False,
        source_name=SOURCE_NAME,
        fetched_at=fetched_at,
        active_sources=[],
    )
    stamping_state = effective_state if active_sources else provisional_state

    return stamp_payload(
        {
            "artifact_kind": "external_data_runtime_report",
            "fetched_at": fetched_at,
            "source_name": SOURCE_NAME,
            "source_type": "external_data_runtime",
            "external_observation_active": bool(active_sources),
            "active_sources": active_sources,
            "success_source_count": len(active_sources),
            "failure_source_count": len(source_reports) - len(active_sources),
            "read_only_contract": dict(READ_ONLY_CONTRACT),
            "source_summaries": source_summaries,
            "limitations": limitations,
            "note": (
                "External data sync aggregates read-only Polymarket and Blockscout observation. "
                "This is advisory context only and does not add execution permissions."
            ),
        },
        runtime_state=stamping_state,
    )


def build_external_data_runtime_report(
    *,
    runtime_state: dict[str, Any] | None = None,
    config_path: Path | None = None,
    transport: Transport | None = None,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    fetch_timestamp = fetched_at or utc_timestamp()
    source_reports = _build_source_reports(
        runtime_state=runtime_state,
        config_path=config_path,
        transport=transport,
        fetched_at=fetch_timestamp,
    )
    return _build_aggregate_payload(
        runtime_state=runtime_state,
        source_reports=source_reports,
        config_path=config_path,
        fetched_at=fetch_timestamp,
    )


def write_external_data_runtime_report(
    *,
    runtime_state: dict[str, Any] | None = None,
    config_path: Path | None = None,
    transport: Transport | None = None,
    output_path: Path | None = None,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    fetch_timestamp = fetched_at or utc_timestamp()
    source_reports = _write_source_reports(
        runtime_state=runtime_state,
        config_path=config_path,
        transport=transport,
        fetched_at=fetch_timestamp,
    )
    payload = _build_aggregate_payload(
        runtime_state=runtime_state,
        source_reports=source_reports,
        config_path=config_path,
        fetched_at=fetch_timestamp,
    )
    write_json_atomic(output_path or EXTERNAL_DATA_REPORT_PATH, payload, stamp=False)
    return payload


def format_external_data_runtime_summary(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "External Data Sync",
            f"operating_mode={report['operating_mode']}",
            f"truth_origin={report['truth_origin']}",
            f"external_observation_active={str(report['external_observation_active']).lower()}",
            f"success_source_count={report['success_source_count']}",
            f"failure_source_count={report['failure_source_count']}",
            (
                "active_sources="
                + (", ".join(report["active_sources"]) if report.get("active_sources") else "none")
            ),
            f"output_path={repo_relative(EXTERNAL_DATA_REPORT_PATH)}",
        ]
    )


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Synchronize read-only Polymarket and Blockscout runtime artifacts."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    mode.add_argument("--summary", action="store_true", help="Emit a compact human-readable summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    report = write_external_data_runtime_report()
    if args.summary:
        print(format_external_data_runtime_summary(report))
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
