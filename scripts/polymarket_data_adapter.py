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
        POLYMARKET_DATA_REPORT_PATH,
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
        POLYMARKET_DATA_REPORT_PATH,
        load_current_pipeline_state,
        repo_relative,
        stamp_payload,
        utc_timestamp,
        write_json_atomic,
    )


SOURCE_NAME = "polymarket_data"
SOURCE_TYPE = "external_prediction_market_data"


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


def _trades_summary(payload: Any) -> dict[str, Any]:
    trades = payload if isinstance(payload, list) else []
    unique_markets = []
    for row in trades:
        if not isinstance(row, dict):
            continue
        condition_id = str(row.get("conditionId") or "").strip()
        if condition_id and condition_id not in unique_markets:
            unique_markets.append(condition_id)
    return {
        "returned_trade_count": len(trades),
        "unique_market_count": len(unique_markets),
        "condition_ids_sample": unique_markets[:3],
        "title_sample": [
            str(row.get("title") or row.get("slug") or "").strip()
            for row in trades[:3]
            if isinstance(row, dict)
        ],
    }


def _open_interest_summary(payload: Any) -> dict[str, Any]:
    rows = payload if isinstance(payload, list) else []
    total_value = 0.0
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            total_value += float(row.get("value", 0.0))
        except (TypeError, ValueError):
            continue
    return {
        "returned_open_interest_count": len(rows),
        "sample_total_open_interest": round(total_value, 4),
        "market_sample": [
            str(row.get("market") or "").strip()
            for row in rows[:3]
            if isinstance(row, dict)
        ],
    }


def _extract_condition_ids(trades_payload: Any, limit: int) -> list[str]:
    if not isinstance(trades_payload, list):
        return []
    ids: list[str] = []
    for row in trades_payload:
        if not isinstance(row, dict):
            continue
        condition_id = str(row.get("conditionId") or "").strip()
        if condition_id and condition_id not in ids:
            ids.append(condition_id)
        if len(ids) >= max(1, limit):
            break
    return ids


def build_polymarket_data_report(
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
    if base_url:
        trades_result = http_get_json(
            base_url,
            "/trades",
            params=config.get("trades_params"),
            headers={"User-Agent": "pipeline-v5.7-core/external-data"},
            timeout_seconds=timeout_seconds,
            transport=transport,
            max_sample_items=max_sample_items,
        )
        endpoint_rows.append(
            _result_row(
                name="trades",
                path="/trades",
                result=trades_result,
                summary=_trades_summary(trades_result.get("payload")) if trades_result.get("ok") else {},
                note="Data API trade history is public and advisory only.",
            )
        )

        condition_ids = _extract_condition_ids(
            trades_result.get("payload"),
            int(config.get("max_open_interest_markets") or 3),
        )
        if condition_ids:
            open_interest_result = http_get_json(
                base_url,
                "/oi",
                params={"market": condition_ids},
                headers={"User-Agent": "pipeline-v5.7-core/external-data"},
                timeout_seconds=timeout_seconds,
                transport=transport,
                max_sample_items=max_sample_items,
            )
            endpoint_rows.append(
                _result_row(
                    name="open_interest",
                    path="/oi",
                    result=open_interest_result,
                    summary=_open_interest_summary(open_interest_result.get("payload"))
                    if open_interest_result.get("ok")
                    else {},
                    note="Open-interest sampling is restricted to observed trade markets to avoid fake breadth.",
                )
            )
        else:
            limitations.append("open_interest_skipped_no_trade_markets_observed")
            endpoint_rows.append(
                _result_row(
                    name="open_interest",
                    path="/oi",
                    attempted=False,
                    note="Skipped because no market identifiers were observed from recent public trades.",
                )
            )
    else:
        limitations.append("missing_env_base_url:POLY_DATA_BASE_URL")

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
        limitations.append("no_public_data_api_endpoint_succeeded")

    payload = stamp_payload(
        {
            "artifact_kind": "external_data_source_report",
            "fetched_at": fetch_timestamp,
            "source_name": SOURCE_NAME,
            "source_type": SOURCE_TYPE,
            "base_url": base_url,
            "external_observation_active": success_count > 0,
            "attempted_count": attempted_count,
            "success_count": success_count,
            "failure_count": failure_count,
            "coverage_state": compute_coverage_state(stamped_rows),
            "read_only_contract": dict(READ_ONLY_CONTRACT),
            "endpoint_results": stamped_rows,
            "limitations": limitations,
            "note": (
                "Polymarket Data integration is read-only user/market analytics sampling. "
                "It does not authenticate user accounts or place orders."
            ),
        },
        runtime_state=stamping_state,
    )
    return payload


def write_polymarket_data_report(
    *,
    runtime_state: dict[str, Any] | None = None,
    config_path: Path | None = None,
    transport: Transport | None = None,
    output_path: Path | None = None,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    payload = build_polymarket_data_report(
        runtime_state=runtime_state,
        config_path=config_path,
        transport=transport,
        fetched_at=fetched_at,
    )
    write_json_atomic(output_path or POLYMARKET_DATA_REPORT_PATH, payload, stamp=False)
    return payload


def format_polymarket_data_summary(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Polymarket Data",
            f"operating_mode={report['operating_mode']}",
            f"truth_origin={report['truth_origin']}",
            f"success_count={report['success_count']}",
            f"failure_count={report['failure_count']}",
            f"coverage_state={report['coverage_state']}",
            f"output_path={repo_relative(POLYMARKET_DATA_REPORT_PATH)}",
        ]
    )


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch read-only Polymarket Data API observations."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    mode.add_argument("--summary", action="store_true", help="Emit a compact human-readable summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    report = write_polymarket_data_report()
    if args.summary:
        print(format_polymarket_data_summary(report))
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
