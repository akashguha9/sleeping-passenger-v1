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
        POLYMARKET_CLOB_REPORT_PATH,
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
        POLYMARKET_CLOB_REPORT_PATH,
        load_current_pipeline_state,
        repo_relative,
        stamp_payload,
        utc_timestamp,
        write_json_atomic,
    )


SOURCE_NAME = "polymarket_clob"
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


def _simplified_markets_summary(payload: Any) -> dict[str, Any]:
    rows = []
    if isinstance(payload, dict):
        rows = payload.get("data", [])
    if not isinstance(rows, list):
        rows = []
    return {
        "returned_market_count": len(rows),
        "active_market_count": sum(
            1 for row in rows if isinstance(row, dict) and row.get("active") is True
        ),
        "condition_ids_sample": [
            str(row.get("condition_id") or "").strip()
            for row in rows[:3]
            if isinstance(row, dict)
        ],
    }


def _select_token_id(payload: Any) -> tuple[str | None, str | None]:
    rows = []
    if isinstance(payload, dict):
        rows = payload.get("data", [])
    if not isinstance(rows, list):
        return None, None
    for row in rows:
        if not isinstance(row, dict):
            continue
        tokens = row.get("tokens", [])
        if not isinstance(tokens, list):
            continue
        for token in tokens:
            if not isinstance(token, dict):
                continue
            token_id = str(token.get("token_id") or "").strip()
            condition_id = str(row.get("condition_id") or "").strip()
            if token_id:
                return token_id, condition_id or None
    return None, None


def _book_summary(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    bids = payload.get("bids", [])
    asks = payload.get("asks", [])
    return {
        "market": payload.get("market"),
        "asset_id": payload.get("asset_id"),
        "bid_depth_levels": len(bids) if isinstance(bids, list) else 0,
        "ask_depth_levels": len(asks) if isinstance(asks, list) else 0,
        "last_trade_price": payload.get("last_trade_price"),
        "tick_size": payload.get("tick_size"),
    }


def _price_summary(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return {"price": payload.get("price")}
    return {"price": payload}


def _spread_summary(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return {"spread": payload.get("spread")}
    return {"spread": payload}


def _history_summary(payload: Any) -> dict[str, Any]:
    history = payload.get("history", []) if isinstance(payload, dict) else []
    if not isinstance(history, list):
        history = []
    return {
        "history_point_count": len(history),
        "latest_point": history[-1] if history else None,
    }


def build_polymarket_clob_report(
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
        time_result = http_get_json(
            base_url,
            "/time",
            headers={"User-Agent": "pipeline-v5.7-core/external-data"},
            timeout_seconds=timeout_seconds,
            transport=transport,
            max_sample_items=max_sample_items,
        )
        endpoint_rows.append(
            _result_row(
                name="server_time",
                path="/time",
                result=time_result,
                summary={"server_time": time_result.get("payload")} if time_result.get("ok") else {},
                note="Public CLOB server time endpoint confirms read-only connectivity.",
            )
        )

        markets_result = http_get_json(
            base_url,
            "/simplified-markets",
            headers={"User-Agent": "pipeline-v5.7-core/external-data"},
            timeout_seconds=timeout_seconds,
            transport=transport,
            max_sample_items=max_sample_items,
        )
        endpoint_rows.append(
            _result_row(
                name="simplified_markets",
                path="/simplified-markets",
                result=markets_result,
                summary=_simplified_markets_summary(markets_result.get("payload"))
                if markets_result.get("ok")
                else {},
                note="Only public simplified market discovery is used; no authenticated trade endpoints are touched.",
            )
        )

        token_id, condition_id = _select_token_id(markets_result.get("payload"))
        if token_id:
            book_result = http_get_json(
                base_url,
                "/book",
                params={"token_id": token_id},
                headers={"User-Agent": "pipeline-v5.7-core/external-data"},
                timeout_seconds=timeout_seconds,
                transport=transport,
                max_sample_items=max_sample_items,
            )
            endpoint_rows.append(
                _result_row(
                    name="book",
                    path="/book",
                    result=book_result,
                    summary=_book_summary(book_result.get("payload")) if book_result.get("ok") else {},
                    note="Orderbook access is public; order posting is explicitly out of scope.",
                )
            )

            price_result = http_get_json(
                base_url,
                "/price",
                params={"token_id": token_id, "side": "BUY"},
                headers={"User-Agent": "pipeline-v5.7-core/external-data"},
                timeout_seconds=timeout_seconds,
                transport=transport,
                max_sample_items=max_sample_items,
            )
            endpoint_rows.append(
                _result_row(
                    name="price",
                    path="/price",
                    result=price_result,
                    summary=_price_summary(price_result.get("payload")) if price_result.get("ok") else {},
                )
            )

            spread_result = http_get_json(
                base_url,
                "/spread",
                params={"token_id": token_id},
                headers={"User-Agent": "pipeline-v5.7-core/external-data"},
                timeout_seconds=timeout_seconds,
                transport=transport,
                max_sample_items=max_sample_items,
            )
            endpoint_rows.append(
                _result_row(
                    name="spread",
                    path="/spread",
                    result=spread_result,
                    summary=_spread_summary(spread_result.get("payload")) if spread_result.get("ok") else {},
                )
            )

            history_result = http_get_json(
                base_url,
                "/prices-history",
                params={
                    "market": token_id,
                    "interval": config.get("history_interval") or "1d",
                    "fidelity": int(config.get("history_fidelity") or 1440),
                },
                headers={"User-Agent": "pipeline-v5.7-core/external-data"},
                timeout_seconds=timeout_seconds,
                transport=transport,
                max_sample_items=max_sample_items,
            )
            endpoint_rows.append(
                _result_row(
                    name="prices_history",
                    path="/prices-history",
                    result=history_result,
                    summary=_history_summary(history_result.get("payload"))
                    if history_result.get("ok")
                    else {},
                    note=f"History uses discovered token_id={token_id} condition_id={condition_id or 'unknown'}.",
                )
            )
        else:
            limitations.append("token_specific_clob_endpoints_skipped_no_public_token_discovered")
            for endpoint_name, endpoint_path in (
                ("book", "/book"),
                ("price", "/price"),
                ("spread", "/spread"),
                ("prices_history", "/prices-history"),
            ):
                endpoint_rows.append(
                    _result_row(
                        name=endpoint_name,
                        path=endpoint_path,
                        attempted=False,
                        note="Skipped because no public token ID was discovered from simplified markets.",
                    )
                )
    else:
        limitations.append("missing_env_base_url:POLY_CLOB_BASE_URL")

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
        limitations.append("no_public_clob_read_endpoint_succeeded")

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
                "Polymarket CLOB integration uses public read endpoints only: server time, "
                "market discovery, price, spread, book, and price history. No orders, no auth headers."
            ),
        },
        runtime_state=stamping_state,
    )
    return payload


def write_polymarket_clob_report(
    *,
    runtime_state: dict[str, Any] | None = None,
    config_path: Path | None = None,
    transport: Transport | None = None,
    output_path: Path | None = None,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    payload = build_polymarket_clob_report(
        runtime_state=runtime_state,
        config_path=config_path,
        transport=transport,
        fetched_at=fetched_at,
    )
    write_json_atomic(output_path or POLYMARKET_CLOB_REPORT_PATH, payload, stamp=False)
    return payload


def format_polymarket_clob_summary(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Polymarket CLOB",
            f"operating_mode={report['operating_mode']}",
            f"truth_origin={report['truth_origin']}",
            f"success_count={report['success_count']}",
            f"failure_count={report['failure_count']}",
            f"coverage_state={report['coverage_state']}",
            f"output_path={repo_relative(POLYMARKET_CLOB_REPORT_PATH)}",
        ]
    )


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch read-only Polymarket CLOB observations."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    mode.add_argument("--summary", action="store_true", help="Emit a compact human-readable summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    report = write_polymarket_clob_report()
    if args.summary:
        print(format_polymarket_clob_summary(report))
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
