from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from scripts.runtime_common import EXTERNAL_DATA_CONFIG_PATH, load_json_file
except ModuleNotFoundError:
    from runtime_common import EXTERNAL_DATA_CONFIG_PATH, load_json_file


Transport = Callable[[str, dict[str, Any] | None, dict[str, str] | None, float], tuple[int | None, str]]

SENSITIVE_QUERY_KEYS = {"apikey", "api_key", "key", "token", "signature", "passphrase"}
READ_ONLY_CONTRACT = {
    "suggestion_only": True,
    "paper_safe": True,
    "live_execution_enabled": False,
    "order_placement_supported": False,
    "wallet_signing_supported": False,
    "hardcoded_secrets_present": False,
}


def _deep_merge(base: Any, override: Any) -> Any:
    if not isinstance(base, dict) or not isinstance(override, dict):
        return override
    merged = dict(base)
    for key, value in override.items():
        if key in merged:
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _coerce_env_value(value: str) -> str:
    normalized = value.strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {'"', "'"}:
        return normalized[1:-1]
    return normalized


def load_external_env(env_path: Path | None = None) -> dict[str, str]:
    path = env_path or (REPO_ROOT / ".env")
    loaded: dict[str, str] = {}
    if not path.exists():
        return loaded
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env_key = key.strip()
        if not env_key or env_key in os.environ:
            continue
        env_value = _coerce_env_value(value)
        os.environ[env_key] = env_value
        loaded[env_key] = env_value
    return loaded


def default_external_data_config() -> dict[str, Any]:
    return {
        "version": 1,
        "mode": "read_only_advisory",
        "request_defaults": {
            "timeout_seconds": 12.0,
            "user_agent": "pipeline-v5.7-core/external-data",
            "max_sample_items": 3,
        },
        "read_only_contract": dict(READ_ONLY_CONTRACT),
        "providers": {
            "polymarket_gamma": {
                "env_base_url": "POLY_GAMMA_BASE_URL",
                "report_path": "runtime/polymarket_gamma_report.json",
                "markets_params": {"limit": 5, "closed": False},
                "events_params": {"limit": 5, "closed": False},
                "signal_ingestion": {
                    "enabled": True,
                    "max_signal_inputs": 1,
                    "min_signal_score": 0.58,
                    "ticker_prefix": "PM",
                    "max_ticker_length": 18,
                    "signal_output_path": "runtime/signal_vocoder_etil_inputs.json",
                },
            },
            "polymarket_data": {
                "env_base_url": "POLY_DATA_BASE_URL",
                "report_path": "runtime/polymarket_data_report.json",
                "trades_params": {"limit": 10, "offset": 0, "takerOnly": True},
                "max_open_interest_markets": 3,
            },
            "polymarket_clob": {
                "env_base_url": "POLY_CLOB_BASE_URL",
                "report_path": "runtime/polymarket_clob_report.json",
                "history_interval": "1d",
                "history_fidelity": 1440,
            },
            "blockscout": {
                "env_base_url": "BLOCKSCOUT_API_BASE_URL",
                "env_api_key": "BLOCKSCOUT_API_KEY",
                "env_chain_id": "BLOCKSCOUT_DEFAULT_CHAIN_ID",
                "routing_mode": "auto",
                "report_path": "runtime/blockscout_report.json",
                "recent_blocks_limit": 5,
            },
        },
    }


def load_external_data_config(config_path: Path | None = None) -> dict[str, Any]:
    load_external_env()
    default_config = default_external_data_config()
    payload = load_json_file(config_path or EXTERNAL_DATA_CONFIG_PATH, default={}) or {}
    if not isinstance(payload, dict):
        return default_config
    return _deep_merge(default_config, payload)


def get_provider_config(provider_name: str, config_path: Path | None = None) -> dict[str, Any]:
    config = load_external_data_config(config_path)
    providers = config.get("providers", {})
    provider_config = providers.get(provider_name, {}) if isinstance(providers, dict) else {}
    return provider_config if isinstance(provider_config, dict) else {}


def resolve_env_value(name: str | None, default: str | None = None) -> str | None:
    load_external_env()
    if not name:
        return default
    value = str(os.environ.get(name, "")).strip()
    return value or default


def build_external_runtime_state(
    runtime_state: dict[str, Any] | None,
    *,
    active: bool,
    source_name: str,
    fetched_at: str,
    active_sources: list[str] | None = None,
) -> dict[str, Any]:
    state = dict(runtime_state or {})
    state["external_observation_active"] = bool(active)
    state["external_observation_source"] = source_name
    state["external_observation_fetched_at"] = fetched_at
    if active_sources is not None:
        state["external_observation_sources"] = list(active_sources)
    return state


def _normalize_json_path(base_url: str, path: str) -> str:
    parsed = urlparse(base_url.strip())
    base_path = parsed.path.rstrip("/")
    target_path = "/" + str(path or "").lstrip("/")
    if base_path and target_path.startswith(base_path + "/"):
        target_path = target_path[len(base_path) :]
    if base_path and target_path == base_path:
        target_path = ""
    segments = [segment for segment in [base_path.strip("/"), target_path.strip("/")] if segment]
    final_path = "/" + "/".join(segments) if segments else ""
    return urlunparse(parsed._replace(path=final_path, query="", fragment=""))


def build_request_url(
    base_url: str,
    path: str,
    params: dict[str, Any] | None = None,
) -> str:
    url = _normalize_json_path(base_url, path).rstrip("/")
    if not params:
        return url
    normalized_params: dict[str, Any] = {}
    for key, value in params.items():
        if isinstance(value, bool):
            normalized_params[key] = str(value).lower()
            continue
        if isinstance(value, list):
            normalized_params[key] = [
                str(item).lower() if isinstance(item, bool) else item for item in value
            ]
            continue
        normalized_params[key] = value
    query = urlencode(normalized_params, doseq=True)
    return f"{url}?{query}" if query else url


def sanitize_request_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.query:
        return url
    redacted_pairs: list[tuple[str, str]] = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key.lower() in SENSITIVE_QUERY_KEYS and value:
            redacted_pairs.append((key, "<redacted>"))
        else:
            redacted_pairs.append((key, value))
    return urlunparse(parsed._replace(query=urlencode(redacted_pairs, doseq=True)))


def _default_transport(
    url: str,
    params: dict[str, Any] | None,
    headers: dict[str, str] | None,
    timeout_seconds: float,
) -> tuple[int | None, str]:
    request_url = build_request_url(url, "", params=params)
    request = Request(request_url, headers=headers or {}, method="GET")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8", errors="replace")
            return int(response.getcode()), body
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return int(exc.code), body
    except URLError as exc:
        raise RuntimeError(str(getattr(exc, "reason", exc)))


def infer_item_count(payload: Any) -> int:
    if payload is None or payload == "":
        return 0
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        for key in ("data", "items", "events", "history", "markets"):
            value = payload.get(key)
            if isinstance(value, list):
                return len(value)
        return 0 if not payload else len(payload)
    return 1


def sample_payload(payload: Any, max_items: int = 3) -> Any:
    if isinstance(payload, list):
        return payload[:max(1, max_items)]
    if isinstance(payload, dict):
        sampled: dict[str, Any] = {}
        for key, value in payload.items():
            if isinstance(value, list):
                sampled[key] = value[:max(1, max_items)]
            elif isinstance(value, dict):
                sampled[key] = {
                    child_key: child_value
                    for child_key, child_value in list(value.items())[: max(1, max_items)]
                }
            elif isinstance(value, (str, int, float, bool)) or value is None:
                sampled[key] = value
            if len(sampled) >= max_items:
                break
        return sampled
    return payload


def classify_payload_kind(payload: Any) -> str:
    if isinstance(payload, list):
        return "list"
    if isinstance(payload, dict):
        return "dict"
    return type(payload).__name__


def http_get_json(
    base_url: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout_seconds: float = 12.0,
    transport: Transport | None = None,
    unauthorized_statuses: set[int] | None = None,
    max_sample_items: int = 3,
) -> dict[str, Any]:
    request_url = build_request_url(base_url, path, params=params)
    sanitized_url = sanitize_request_url(request_url)
    auth_failures = unauthorized_statuses or {401, 403}
    try:
        status_code, body = (transport or _default_transport)(
            _normalize_json_path(base_url, path),
            params,
            headers,
            timeout_seconds,
        )
    except Exception as exc:
        return {
            "ok": False,
            "status_code": None,
            "error_kind": "request_error",
            "error": str(exc),
            "request_url": sanitized_url,
            "payload": None,
            "item_count": 0,
            "payload_kind": "none",
            "sample": None,
        }

    status = int(status_code) if status_code is not None else None
    normalized_body = str(body or "").strip()
    if status in auth_failures:
        return {
            "ok": False,
            "status_code": status,
            "error_kind": "unauthorized",
            "error": normalized_body[:240] or "unauthorized",
            "request_url": sanitized_url,
            "payload": None,
            "item_count": 0,
            "payload_kind": "none",
            "sample": None,
        }
    if status is None or status < 200 or status >= 300:
        return {
            "ok": False,
            "status_code": status,
            "error_kind": "http_error",
            "error": normalized_body[:240] or f"http_status_{status}",
            "request_url": sanitized_url,
            "payload": None,
            "item_count": 0,
            "payload_kind": "none",
            "sample": None,
        }
    if not normalized_body:
        return {
            "ok": False,
            "status_code": status,
            "error_kind": "empty_response",
            "error": "empty_response",
            "request_url": sanitized_url,
            "payload": None,
            "item_count": 0,
            "payload_kind": "none",
            "sample": None,
        }

    try:
        payload = json.loads(normalized_body)
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "status_code": status,
            "error_kind": "invalid_json",
            "error": str(exc),
            "request_url": sanitized_url,
            "payload": None,
            "item_count": 0,
            "payload_kind": "none",
            "sample": normalized_body[:240],
        }

    if payload in (None, {}, []):
        return {
            "ok": False,
            "status_code": status,
            "error_kind": "empty_response",
            "error": "empty_response",
            "request_url": sanitized_url,
            "payload": payload,
            "item_count": 0,
            "payload_kind": classify_payload_kind(payload),
            "sample": sample_payload(payload, max_items=max_sample_items),
        }

    return {
        "ok": True,
        "status_code": status,
        "error_kind": None,
        "error": None,
        "request_url": sanitized_url,
        "payload": payload,
        "item_count": infer_item_count(payload),
        "payload_kind": classify_payload_kind(payload),
        "sample": sample_payload(payload, max_items=max_sample_items),
    }


def request_with_retry(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_body: Any = None,
    timeout: float = 10.0,
    retries: int = 2,
    backoff_seconds: float = 0.5,
):
    """R3 fix: shared outbound HTTP helper with timeout + bounded retries.

    Every loader should route through this so timeout / retry policy
    lives in one place.  ``backoff_seconds`` is exponential with light
    jitter.  Read-only: never places orders, never calls a broker,
    never increments ``ai_execution_count``.
    """
    import random
    import time

    try:
        import requests
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("requests is required for request_with_retry") from exc

    last_exc: Exception | None = None
    for attempt in range(max(1, int(retries) + 1)):
        try:
            return requests.request(
                method=method.upper(),
                url=url,
                headers=headers,
                params=params,
                json=json_body,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            last_exc = exc
            if attempt >= retries:
                break
            sleep_s = backoff_seconds * (2**attempt) + random.uniform(0, 0.1)
            time.sleep(sleep_s)
    assert last_exc is not None
    raise last_exc


def compute_coverage_state(endpoint_rows: list[dict[str, Any]]) -> str:
    attempted = [row for row in endpoint_rows if bool(row.get("attempted", True))]
    if not attempted:
        return "UNAVAILABLE"
    success_count = sum(1 for row in attempted if bool(row.get("ok")))
    if success_count == len(attempted):
        return "AVAILABLE"
    if success_count > 0:
        return "PARTIAL"
    return "UNAVAILABLE"
