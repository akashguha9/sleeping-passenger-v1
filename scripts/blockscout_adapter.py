from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from scripts.external_data_common import (
        READ_ONLY_CONTRACT,
        Transport,
        build_external_runtime_state,
        compute_coverage_state,
        get_provider_config,
        http_get_json,
        resolve_env_value,
    )
    from scripts.runtime_common import (
        BLOCKSCOUT_REPORT_PATH,
        load_current_pipeline_state,
        repo_relative,
        stamp_payload,
        utc_timestamp,
        write_json_atomic,
    )
except ModuleNotFoundError:
    from external_data_common import (
        READ_ONLY_CONTRACT,
        Transport,
        build_external_runtime_state,
        compute_coverage_state,
        get_provider_config,
        http_get_json,
        resolve_env_value,
    )
    from runtime_common import (
        BLOCKSCOUT_REPORT_PATH,
        load_current_pipeline_state,
        repo_relative,
        stamp_payload,
        utc_timestamp,
        write_json_atomic,
    )


SOURCE_NAME = "blockscout"
SOURCE_TYPE = "external_blockchain_explorer"


def _result_row(
    *,
    name: str,
    path: str,
    result: dict[str, Any] | None = None,
    summary: dict[str, Any] | None = None,
    attempted: bool = True,
    note: str | None = None,
) -> dict[str, Any]:
    payload = result or {}
    return {
        "endpoint_name": name,
        "path": path,
        "attempted": attempted,
        "ok": bool(payload.get("ok", False)) if attempted else False,
        "status_code": payload.get("status_code") if attempted else None,
        "error_kind": payload.get("error_kind") if attempted else "skipped",
        "error": payload.get("error"),
        "request_url": payload.get("request_url"),
        "payload_kind": payload.get("payload_kind"),
        "item_count": payload.get("item_count", 0) if attempted else 0,
        "summary": summary or {},
        "note": note,
    }


def _is_pro_mode(base_url: str, configured_mode: str) -> bool:
    mode = str(configured_mode or "auto").strip().lower()
    if mode == "pro":
        return True
    if mode == "instance":
        return False
    parsed = urlparse(base_url)
    host = str(parsed.netloc or "").lower()
    return host in {"api.blockscout.com", "dev.blockscout.com"}


def _path_for(mode_is_pro: bool, chain_id: str | None, suffix: str) -> str | None:
    normalized_suffix = "/" + suffix.lstrip("/")
    if mode_is_pro:
        if not chain_id:
            return None
        return f"/{chain_id}/api/v2{normalized_suffix}"
    return f"/api/v2{normalized_suffix}"


def _query_for(mode_is_pro: bool, api_key: str | None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    query = dict(extra or {})
    if api_key:
        query["apikey"] = api_key
    return query


def _backend_version_summary(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return {"backend_version": payload.get("backend_version")}
    return {"backend_version": payload}


def _blocks_summary(payload: Any) -> dict[str, Any]:
    rows = payload if isinstance(payload, list) else []
    latest_height = None
    if rows and isinstance(rows[0], dict):
        latest_height = rows[0].get("height")
    return {
        "returned_block_count": len(rows),
        "latest_block_height": latest_height,
        "height_sample": [
            row.get("height")
            for row in rows[:3]
            if isinstance(row, dict) and row.get("height") is not None
        ],
    }


def build_blockscout_report(
    *,
    runtime_state: dict[str, Any] | None = None,
    config_path: Path | None = None,
    transport: Transport | None = None,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    config = get_provider_config(SOURCE_NAME, config_path)
    base_state = runtime_state or load_current_pipeline_state()
    fetch_timestamp = fetched_at or utc_timestamp()
    base_url = resolve_env_value(config.get("env_base_url"))
    api_key = resolve_env_value(config.get("env_api_key"))
    chain_id = resolve_env_value(config.get("env_chain_id"))
    timeout_seconds = float(config.get("timeout_seconds") or 12.0)
    max_sample_items = int(config.get("max_sample_items") or 3)

    provisional_state = build_external_runtime_state(
        base_state,
        active=False,
        source_name=SOURCE_NAME,
        fetched_at=fetch_timestamp,
    )

    limitations: list[str] = []
    endpoint_rows: list[dict[str, Any]] = []
    routing_mode = str(config.get("routing_mode") or "auto").lower()

    if base_url:
        pro_mode = _is_pro_mode(base_url, routing_mode)
        if pro_mode and not api_key:
            limitations.append("blockscout_pro_mode_missing_api_key")
        if pro_mode and not chain_id:
            limitations.append("blockscout_pro_mode_missing_chain_id")

        backend_path = _path_for(pro_mode, chain_id, "/config/backend-version")
        if backend_path:
            backend_result = http_get_json(
                base_url,
                backend_path,
                params=_query_for(pro_mode, api_key),
                headers={"User-Agent": "pipeline-v5.7-core/external-data"},
                timeout_seconds=timeout_seconds,
                transport=transport,
                unauthorized_statuses={401, 403, 422} if pro_mode else {401, 403},
                max_sample_items=max_sample_items,
            )
            endpoint_rows.append(
                _result_row(
                    name="backend_version",
                    path=backend_path,
                    result=backend_result,
                    summary=_backend_version_summary(backend_result.get("payload"))
                    if backend_result.get("ok")
                    else {},
                    note=(
                        "Blockscout backend version is explicitly documented for both instance "
                        "and PRO routing patterns."
                    ),
                )
            )
        else:
            endpoint_rows.append(
                _result_row(
                    name="backend_version",
                    path="/api/v2/config/backend-version",
                    attempted=False,
                    note="Skipped because Blockscout PRO routing needs a chain id.",
                )
            )

        blocks_path = _path_for(pro_mode, chain_id, "/main-page/blocks")
        if blocks_path:
            blocks_result = http_get_json(
                base_url,
                blocks_path,
                params=_query_for(
                    pro_mode,
                    api_key,
                    extra={"limit": int(config.get("recent_blocks_limit") or 5)},
                ),
                headers={"User-Agent": "pipeline-v5.7-core/external-data"},
                timeout_seconds=timeout_seconds,
                transport=transport,
                unauthorized_statuses={401, 403, 422} if pro_mode else {401, 403},
                max_sample_items=max_sample_items,
            )
            endpoint_rows.append(
                _result_row(
                    name="main_page_blocks",
                    path=blocks_path,
                    result=blocks_result,
                    summary=_blocks_summary(blocks_result.get("payload"))
                    if blocks_result.get("ok")
                    else {},
                    note=(
                        "This is a read-only explorer surface. In PRO mode the v2 path pattern "
                        "is probed conservatively and may not be enabled on every deployment."
                    ),
                )
            )
            if pro_mode and not blocks_result.get("ok"):
                limitations.append("blockscout_pro_recent_blocks_endpoint_unconfirmed_or_unavailable")
        else:
            endpoint_rows.append(
                _result_row(
                    name="main_page_blocks",
                    path="/api/v2/main-page/blocks",
                    attempted=False,
                    note="Skipped because Blockscout PRO routing needs a chain id.",
                )
            )
    else:
        limitations.append("missing_env_base_url:BLOCKSCOUT_API_BASE_URL")

    attempted_count = sum(1 for row in endpoint_rows if row["attempted"])
    success_count = sum(1 for row in endpoint_rows if row["attempted"] and row["ok"])
    failure_count = sum(1 for row in endpoint_rows if row["attempted"] and not row["ok"])
    effective_state = build_external_runtime_state(
        base_state,
        active=success_count > 0,
        source_name=SOURCE_NAME,
        fetched_at=fetch_timestamp,
    )
    stamping_state = effective_state if success_count > 0 else provisional_state
    stamped_rows = [stamp_payload(row, runtime_state=stamping_state) for row in endpoint_rows]

    if success_count == 0:
        limitations.append("no_blockscout_endpoint_succeeded")

    payload = stamp_payload(
        {
            "artifact_kind": "external_data_source_report",
            "fetched_at": fetch_timestamp,
            "source_name": SOURCE_NAME,
            "source_type": SOURCE_TYPE,
            "base_url": base_url,
            "routing_mode": routing_mode,
            "resolved_mode": "pro" if base_url and _is_pro_mode(base_url, routing_mode) else "instance",
            "chain_id": chain_id,
            "external_observation_active": success_count > 0,
            "attempted_count": attempted_count,
            "success_count": success_count,
            "failure_count": failure_count,
            "coverage_state": compute_coverage_state(stamped_rows),
            "read_only_contract": dict(READ_ONLY_CONTRACT),
            "endpoint_results": stamped_rows,
            "limitations": limitations,
            "note": (
                "Blockscout integration is explorer/API observation only. It reads public or "
                "API-key-gated explorer endpoints and never signs transactions or submits writes."
            ),
        },
        runtime_state=stamping_state,
    )
    return payload


def write_blockscout_report(
    *,
    runtime_state: dict[str, Any] | None = None,
    config_path: Path | None = None,
    transport: Transport | None = None,
    output_path: Path | None = None,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    payload = build_blockscout_report(
        runtime_state=runtime_state,
        config_path=config_path,
        transport=transport,
        fetched_at=fetched_at,
    )
    write_json_atomic(output_path or BLOCKSCOUT_REPORT_PATH, payload, stamp=False)
    return payload


def format_blockscout_summary(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Blockscout",
            f"operating_mode={report['operating_mode']}",
            f"truth_origin={report['truth_origin']}",
            f"success_count={report['success_count']}",
            f"failure_count={report['failure_count']}",
            f"coverage_state={report['coverage_state']}",
            f"output_path={repo_relative(BLOCKSCOUT_REPORT_PATH)}",
        ]
    )


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch read-only Blockscout explorer/API observations."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    mode.add_argument("--summary", action="store_true", help="Emit a compact human-readable summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    report = write_blockscout_report()
    if args.summary:
        print(format_blockscout_summary(report))
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
