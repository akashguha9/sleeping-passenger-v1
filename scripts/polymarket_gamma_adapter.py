from __future__ import annotations

import argparse
import json
import math
import re
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
        POLYMARKET_GAMMA_REPORT_PATH,
        SIGNAL_VOCODER_ETIL_INPUTS_PATH,
        load_current_pipeline_state,
        repo_relative,
        set_source_mode,
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
        POLYMARKET_GAMMA_REPORT_PATH,
        SIGNAL_VOCODER_ETIL_INPUTS_PATH,
        load_current_pipeline_state,
        repo_relative,
        set_source_mode,
        stamp_payload,
        utc_timestamp,
        write_json_atomic,
    )


SOURCE_NAME = "polymarket_gamma"
SOURCE_TYPE = "external_prediction_market_data"
DEFAULT_MIN_SIGNAL_SCORE = 0.58
DEFAULT_MAX_SIGNAL_INPUTS = 1
DEFAULT_TICKER_PREFIX = "PM"
DEFAULT_MAX_TICKER_LENGTH = 18


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


def _coerce_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _coerce_outcome_prices(value: Any) -> list[float]:
    if isinstance(value, list):
        candidates = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            return []
        candidates = decoded if isinstance(decoded, list) else []
    else:
        return []

    prices: list[float] = []
    for item in candidates:
        price = _coerce_float(item)
        if price is not None:
            prices.append(price)
    return prices


def _sanitize_ticker_fragment(value: str, *, max_length: int) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", value.strip().upper())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    if not normalized:
        return "MARKET"
    return normalized[:max_length].rstrip("_") or "MARKET"


def _derive_market_sort_key(market: dict[str, Any]) -> tuple[float, float, float]:
    volume = _coerce_float(market.get("volumeNum") or market.get("volume")) or 0.0
    liquidity = _coerce_float(market.get("liquidityNum") or market.get("liquidity")) or 0.0
    volume_24h = _coerce_float(market.get("volume24hr")) or 0.0
    return (volume_24h, volume, liquidity)


def _markets_summary(payload: Any) -> dict[str, Any]:
    markets = payload if isinstance(payload, list) else []
    active_count = sum(1 for row in markets if isinstance(row, dict) and row.get("active") is True)
    condition_ids = [
        str(row.get("conditionId") or row.get("id") or "").strip()
        for row in markets
        if isinstance(row, dict)
    ]
    return {
        "returned_market_count": len(markets),
        "active_market_count": active_count,
        "condition_ids_sample": [value for value in condition_ids if value][:3],
        "question_sample": [
            str(row.get("question") or row.get("slug") or "").strip()
            for row in markets[:3]
            if isinstance(row, dict)
        ],
    }


def _events_payload_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        events = payload.get("events", [])
    else:
        events = payload
    if not isinstance(events, list):
        return []
    return [row for row in events if isinstance(row, dict)]


def _events_summary(payload: Any) -> dict[str, Any]:
    events = _events_payload_rows(payload)
    return {
        "returned_event_count": len(events),
        "active_event_count": sum(1 for row in events if row.get("active") is True),
        "slug_sample": [
            str(row.get("slug") or row.get("id") or "").strip()
            for row in events[:3]
        ],
        "category_sample": [
            str(row.get("category") or "").strip()
            for row in events[:3]
            if row.get("category")
        ],
    }


def _build_event_maps(events_payload: Any) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    events = _events_payload_rows(events_payload)
    slug_map: dict[str, dict[str, Any]] = {}
    id_map: dict[str, dict[str, Any]] = {}
    for event in events:
        slug = str(event.get("slug") or "").strip().lower()
        event_id = str(event.get("id") or "").strip()
        if slug:
            slug_map[slug] = event
        if event_id:
            id_map[event_id] = event
    return slug_map, id_map


def _match_market_event(
    market: dict[str, Any],
    event_slug_map: dict[str, dict[str, Any]],
    event_id_map: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    for embedded in market.get("events", []):
        if isinstance(embedded, dict):
            return embedded

    market_slug = str(market.get("slug") or "").strip().lower()
    if market_slug and market_slug in event_slug_map:
        return event_slug_map[market_slug]

    event_ids = market.get("eventIds") or market.get("event_ids") or []
    if isinstance(event_ids, list):
        for event_id in event_ids:
            mapped = event_id_map.get(str(event_id).strip())
            if mapped is not None:
                return mapped
    return None


def _derive_signal_score(market: dict[str, Any], event: dict[str, Any] | None) -> tuple[float, dict[str, Any]]:
    evidence_points: list[str] = []
    score = 0.50

    if market.get("active") is True:
        score += 0.04
        evidence_points.append("market_active")
    if str(market.get("question") or "").strip():
        score += 0.02
        evidence_points.append("market_question_present")
    if str(market.get("conditionId") or market.get("id") or "").strip():
        score += 0.02
        evidence_points.append("market_condition_present")
    if str(market.get("slug") or "").strip():
        score += 0.01
        evidence_points.append("market_slug_present")

    volume = max(
        0.0,
        _coerce_float(market.get("volume24hr"))
        or _coerce_float(market.get("volumeNum"))
        or _coerce_float(market.get("volume"))
        or 0.0,
    )
    liquidity = max(
        0.0,
        _coerce_float(market.get("liquidityNum"))
        or _coerce_float(market.get("liquidity"))
        or 0.0,
    )
    score += min(math.log10(volume + 1.0) / 6.0, 1.0) * 0.02
    score += min(math.log10(liquidity + 1.0) / 6.0, 1.0) * 0.01
    if volume > 0:
        evidence_points.append("market_volume_present")
    if liquidity > 0:
        evidence_points.append("market_liquidity_present")

    outcome_prices = _coerce_outcome_prices(market.get("outcomePrices"))
    if outcome_prices:
        score += 0.01
        evidence_points.append("market_outcome_prices_present")

    if isinstance(event, dict):
        if event.get("active") is True:
            score += 0.01
            evidence_points.append("event_active")
        if str(event.get("category") or "").strip():
            evidence_points.append("event_category_present")

    bounded_score = round(min(max(score, 0.0), 0.62), 3)
    evidence = {
        "evidence_points": evidence_points,
        "market_volume": volume,
        "market_liquidity": liquidity,
        "event_category": str((event or {}).get("category") or "").strip(),
        "outcome_prices_available": bool(outcome_prices),
    }
    return bounded_score, evidence


def _build_gamma_signal_inputs(
    markets_payload: Any,
    events_payload: Any,
    config: dict[str, Any],
    *,
    fetched_at: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    limitations: list[str] = []
    signal_ingestion = config.get("signal_ingestion", {})
    if not isinstance(signal_ingestion, dict):
        signal_ingestion = {}
    if signal_ingestion.get("enabled", True) is False:
        return [], ["signal_ingestion_disabled"]

    min_signal_score = float(
        signal_ingestion.get("min_signal_score")
        or signal_ingestion.get("min_observability_score")
        or DEFAULT_MIN_SIGNAL_SCORE
    )
    max_signal_inputs = int(signal_ingestion.get("max_signal_inputs") or DEFAULT_MAX_SIGNAL_INPUTS)
    ticker_prefix = str(signal_ingestion.get("ticker_prefix") or DEFAULT_TICKER_PREFIX).strip().upper()
    max_ticker_length = int(
        signal_ingestion.get("max_ticker_length") or DEFAULT_MAX_TICKER_LENGTH
    )

    markets = [row for row in (markets_payload if isinstance(markets_payload, list) else []) if isinstance(row, dict)]
    if not markets:
        return [], ["no_market_rows_available_for_signal_ingestion"]

    event_slug_map, event_id_map = _build_event_maps(events_payload)
    signal_inputs: list[dict[str, Any]] = []

    for market in sorted(markets, key=_derive_market_sort_key, reverse=True):
        if market.get("active") is not True:
            continue
        condition_id = str(market.get("conditionId") or market.get("id") or "").strip()
        question = str(market.get("question") or market.get("slug") or "").strip()
        if not condition_id or not question:
            continue

        matched_event = _match_market_event(market, event_slug_map, event_id_map)
        score, evidence = _derive_signal_score(market, matched_event)
        if score < min_signal_score:
            continue

        event_ticker = str((matched_event or {}).get("ticker") or "").strip()
        market_slug = str(market.get("slug") or "").strip()
        ticker_fragment = _sanitize_ticker_fragment(
            event_ticker or market_slug or question,
            max_length=max(4, max_ticker_length - len(ticker_prefix) - 1),
        )
        ticker = f"{ticker_prefix}_{ticker_fragment}"
        signal_id = f"SIG_POLY_GAMMA_{condition_id[:12].upper()}"

        signal_inputs.append(
            {
                "signal_id": signal_id,
                "ticker": ticker,
                "ce_score": score,
                "priority_score": score,
                "status": "WATCHLIST",
                "conversion_state": "NOT_EXECUTED",
                "blocker_attribution": "NONE",
                "promotable_clean_candidate": False,
                "watchlist_tier": "STANDARD",
                "candidate_conversion_state": "NOT_EXECUTED",
                "pre_entry_state": "NONE",
                "signal_origin": "external",
                "source_name": SOURCE_NAME,
                "origin_label": "polymarket_gamma_public_market",
                "condition_id": condition_id,
                "question": question,
                "event_slug": str((matched_event or {}).get("slug") or market_slug).strip(),
                "category": str((matched_event or {}).get("category") or market.get("category") or "").strip(),
                "fetched_at": fetched_at,
                "observability_score": score,
                "evidence": evidence,
            }
        )
        if len(signal_inputs) >= max_signal_inputs:
            break

    if not signal_inputs:
        limitations.append("no_gamma_markets_met_conservative_signal_threshold")
    return signal_inputs, limitations


def build_signal_vocoder_etil_payload(
    report: dict[str, Any],
    *,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    signal_inputs = report.get("signal_inputs", [])
    if not isinstance(signal_inputs, list):
        signal_inputs = []
    payload = {
        "artifact_kind": "signal_vocoder_etil_inputs",
        "fetched_at": fetched_at or str(report.get("fetched_at") or utc_timestamp()),
        "source_name": SOURCE_NAME,
        "source_type": SOURCE_TYPE,
        "external_observation_active": bool(report.get("external_observation_active")),
        "signal_inputs": [dict(row) for row in signal_inputs if isinstance(row, dict)],
        "signal_count": len(signal_inputs),
        "limitations": list(report.get("signal_ingestion_limitations", [])),
        "read_only_contract": dict(READ_ONLY_CONTRACT),
        "note": (
            "Signal vocoder ETIL inputs are read-only external watchlist candidates derived "
            "from public Polymarket Gamma market discovery. They do not enable execution."
        ),
    }
    return payload


def build_polymarket_gamma_report(
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
    markets_result: dict[str, Any] = {}
    events_result: dict[str, Any] = {}
    if base_url:
        markets_result = http_get_json(
            base_url,
            "/markets",
            params=config.get("markets_params"),
            headers={"User-Agent": "pipeline-v5.7-core/external-data"},
            timeout_seconds=timeout_seconds,
            transport=transport,
            max_sample_items=max_sample_items,
        )
        endpoint_rows.append(
            _result_row(
                name="markets",
                path="/markets",
                result=markets_result,
                summary=_markets_summary(markets_result.get("payload")) if markets_result.get("ok") else {},
                note="Gamma market discovery is public and read-only.",
            )
        )

        events_result = http_get_json(
            base_url,
            "/events/keyset",
            params=config.get("events_params"),
            headers={"User-Agent": "pipeline-v5.7-core/external-data"},
            timeout_seconds=timeout_seconds,
            transport=transport,
            max_sample_items=max_sample_items,
        )
        endpoint_rows.append(
            _result_row(
                name="events_keyset",
                path="/events/keyset",
                result=events_result,
                summary=_events_summary(events_result.get("payload")) if events_result.get("ok") else {},
                note="Cursor-based event pagination is public and avoids offset drift.",
            )
        )
    else:
        limitations.append("missing_env_base_url:POLY_GAMMA_BASE_URL")

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

    signal_inputs, signal_input_limitations = _build_gamma_signal_inputs(
        markets_result.get("payload"),
        events_result.get("payload"),
        config,
        fetched_at=fetch_timestamp,
    )
    limitations.extend(signal_input_limitations)

    if success_count == 0:
        limitations.append("no_public_gamma_endpoint_succeeded")

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
            "signal_inputs": signal_inputs,
            "signal_input_summary": {
                "signal_count": len(signal_inputs),
                "signal_tickers": [row["ticker"] for row in signal_inputs],
            },
            "signal_ingestion_limitations": signal_input_limitations,
            "limitations": limitations,
            "note": (
                "Polymarket Gamma integration is discovery-only: public markets/events "
                "observation for advisory workflows. When coverage is sufficient, it also emits "
                "a conservative watchlist-only ETIL signal input. No execution, no wallet signing."
            ),
        },
        runtime_state=stamping_state,
    )
    return payload


def write_polymarket_gamma_report(
    *,
    runtime_state: dict[str, Any] | None = None,
    config_path: Path | None = None,
    transport: Transport | None = None,
    output_path: Path | None = None,
    fetched_at: str | None = None,
    signal_output_path: Path | None = None,
) -> dict[str, Any]:
    payload = build_polymarket_gamma_report(
        runtime_state=runtime_state,
        config_path=config_path,
        transport=transport,
        fetched_at=fetched_at,
    )
    signal_payload = build_signal_vocoder_etil_payload(payload, fetched_at=fetched_at)
    has_signal_inputs = bool(signal_payload.get("signal_count", 0))
    set_source_mode("LIVE_ETIL" if has_signal_inputs else "SYNTHETIC_RUNTIME_FALLBACK")

    stamping_state = build_external_runtime_state(
        runtime_state or load_current_pipeline_state(),
        active=bool(payload.get("external_observation_active")),
        source_name=SOURCE_NAME,
        fetched_at=str(payload.get("fetched_at") or fetched_at or utc_timestamp()),
    )
    restamped_payload = stamp_payload(payload, runtime_state=stamping_state)
    write_json_atomic(output_path or POLYMARKET_GAMMA_REPORT_PATH, restamped_payload, stamp=False)
    write_json_atomic(signal_output_path or SIGNAL_VOCODER_ETIL_INPUTS_PATH, signal_payload)
    return restamped_payload


def format_polymarket_gamma_summary(report: dict[str, Any]) -> str:
    signal_summary = report.get("signal_input_summary", {})
    return "\n".join(
        [
            "Polymarket Gamma",
            f"operating_mode={report['operating_mode']}",
            f"truth_origin={report['truth_origin']}",
            f"success_count={report['success_count']}",
            f"failure_count={report['failure_count']}",
            f"coverage_state={report['coverage_state']}",
            f"signal_input_count={int(signal_summary.get('signal_count', 0))}",
            f"output_path={repo_relative(POLYMARKET_GAMMA_REPORT_PATH)}",
        ]
    )


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch read-only Polymarket Gamma discovery data."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    mode.add_argument("--summary", action="store_true", help="Emit a compact human-readable summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    report = write_polymarket_gamma_report()
    if args.summary:
        print(format_polymarket_gamma_summary(report))
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
