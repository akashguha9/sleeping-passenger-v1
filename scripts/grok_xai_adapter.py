from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from scripts.external_data_common import (
        build_external_runtime_state,
        build_request_url,
        classify_payload_kind,
        load_external_env,
        resolve_env_value,
        sample_payload,
        sanitize_request_url,
    )
    from scripts.runtime_common import (
        ACTION_REPORT_PATH,
        BLOCKSCOUT_REPORT_PATH,
        GROK_XAI_REPORT_PATH,
        HEALTH_REPORT_PATH,
        LLM_PROVIDER_CONFIG_PATH,
        POLYMARKET_GAMMA_REPORT_PATH,
        load_current_pipeline_state,
        load_json_file,
        repo_relative,
        stamp_payload,
        utc_timestamp,
        write_json_atomic,
    )
except ModuleNotFoundError:
    from external_data_common import (
        build_external_runtime_state,
        build_request_url,
        classify_payload_kind,
        load_external_env,
        resolve_env_value,
        sample_payload,
        sanitize_request_url,
    )
    from runtime_common import (
        ACTION_REPORT_PATH,
        BLOCKSCOUT_REPORT_PATH,
        GROK_XAI_REPORT_PATH,
        HEALTH_REPORT_PATH,
        LLM_PROVIDER_CONFIG_PATH,
        POLYMARKET_GAMMA_REPORT_PATH,
        load_current_pipeline_state,
        load_json_file,
        repo_relative,
        stamp_payload,
        utc_timestamp,
        write_json_atomic,
    )


SOURCE_NAME = "grok_xai"
SOURCE_TYPE = "external_llm_intelligence"
DEFAULT_ENDPOINT_PATH = "/v1/chat/completions"
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_USER_AGENT = "pipeline-v5.7-core/grok-xai"
DEFAULT_USE_CASE = "signal_ranking_interpreter"

ALLOWED_OPERATOR_ACTIONS = {
    "monitor",
    "cross_check",
    "review_with_human",
    "gather_more_evidence",
    "deprioritize",
}
ALLOWED_SIGNAL_TYPES = {
    "event_market",
    "narrative_shift",
    "flow_signal",
    "timing_signal",
    "risk_flag",
    "unknown",
}
ALLOWED_RELEVANCE = {"high", "medium", "low", "unclear"}

USE_CASE_ALIASES = {
    "polymarket": "polymarket_payload_interpreter",
    "polymarket_payload_interpreter": "polymarket_payload_interpreter",
    "blockscout": "blockscout_payload_interpreter",
    "blockscout_payload_interpreter": "blockscout_payload_interpreter",
    "signal-ranking": "signal_ranking_interpreter",
    "signal_ranking": "signal_ranking_interpreter",
    "signal_ranking_interpreter": "signal_ranking_interpreter",
}

PostTransport = Callable[
    [str, dict[str, str] | None, dict[str, Any], float],
    tuple[int | None, str],
]


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


def default_llm_provider_config() -> dict[str, Any]:
    return {
        "version": 1,
        "mode": "read_only_advisory",
        "read_only_contract": {
            "suggestion_only": True,
            "paper_safe": True,
            "live_execution_enabled": False,
            "order_placement_supported": False,
            "wallet_signing_supported": False,
            "autonomous_execution_supported": False,
            "hardcoded_secrets_present": False,
            "silent_model_fallback_allowed": False,
        },
        "providers": {
            SOURCE_NAME: {
                "env_api_key": "XAI_API_KEY",
                "env_base_url": "XAI_API_BASE_URL",
                "env_model": "XAI_MODEL",
                "require_explicit_model_env": True,
                "allow_model_fallback": False,
                "endpoint_path": DEFAULT_ENDPOINT_PATH,
                "timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
                "user_agent": DEFAULT_USER_AGENT,
                "report_path": "runtime/grok_xai_report.json",
                "response_format_mode": "json_schema",
                "default_use_case": DEFAULT_USE_CASE,
                "use_case_defaults": {
                    "polymarket_payload_interpreter": {
                        "temperature": 0.0,
                        "max_output_tokens": 500,
                    },
                    "blockscout_payload_interpreter": {
                        "temperature": 0.0,
                        "max_output_tokens": 500,
                    },
                    "signal_ranking_interpreter": {
                        "temperature": 0.0,
                        "max_output_tokens": 700,
                    },
                },
            }
        },
    }


def load_llm_provider_config(config_path: Path | None = None) -> dict[str, Any]:
    load_external_env()
    default_config = default_llm_provider_config()
    payload = load_json_file(config_path or LLM_PROVIDER_CONFIG_PATH, default={}) or {}
    if not isinstance(payload, dict):
        return default_config
    return _deep_merge(default_config, payload)


def get_provider_config(provider_name: str, config_path: Path | None = None) -> dict[str, Any]:
    config = load_llm_provider_config(config_path)
    providers = config.get("providers", {})
    provider_config = providers.get(provider_name, {}) if isinstance(providers, dict) else {}
    return provider_config if isinstance(provider_config, dict) else {}


def _normalize_use_case(value: str | None) -> str:
    normalized = str(value or DEFAULT_USE_CASE).strip().lower()
    return USE_CASE_ALIASES.get(normalized, DEFAULT_USE_CASE)


def _report_path(config: dict[str, Any]) -> Path:
    relative_path = str(config.get("report_path") or "").strip()
    if not relative_path:
        return GROK_XAI_REPORT_PATH
    return (REPO_ROOT / relative_path).resolve()


def _default_transport(
    url: str,
    headers: dict[str, str] | None,
    payload: dict[str, Any],
    timeout_seconds: float,
) -> tuple[int | None, str]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers or {},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8", errors="replace")
            return int(response.getcode()), body
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return int(exc.code), body
    except URLError as exc:
        raise RuntimeError(str(getattr(exc, "reason", exc)))


def _extract_error_message(body: str) -> str:
    normalized_body = str(body or "").strip()
    if not normalized_body:
        return "empty_response"
    try:
        payload = json.loads(normalized_body)
    except json.JSONDecodeError:
        return normalized_body[:240]
    if isinstance(payload, dict):
        for key in ("error", "message", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:240]
            if isinstance(value, dict):
                nested_message = value.get("message")
                if isinstance(nested_message, str) and nested_message.strip():
                    return nested_message.strip()[:240]
    return normalized_body[:240]


def _post_json(
    request_url: str,
    *,
    headers: dict[str, str] | None = None,
    payload: dict[str, Any],
    timeout_seconds: float,
    transport: PostTransport | None = None,
    unauthorized_statuses: set[int] | None = None,
) -> dict[str, Any]:
    sanitized_url = sanitize_request_url(request_url)
    auth_failures = unauthorized_statuses or {401, 403}
    try:
        status_code, body = (transport or _default_transport)(
            request_url,
            headers,
            payload,
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
            "sample": None,
        }

    status = int(status_code) if status_code is not None else None
    normalized_body = str(body or "").strip()
    if status in auth_failures:
        return {
            "ok": False,
            "status_code": status,
            "error_kind": "unauthorized",
            "error": _extract_error_message(normalized_body),
            "request_url": sanitized_url,
            "payload": None,
            "sample": None,
        }
    if status is None or status < 200 or status >= 300:
        return {
            "ok": False,
            "status_code": status,
            "error_kind": "http_error",
            "error": _extract_error_message(normalized_body),
            "request_url": sanitized_url,
            "payload": None,
            "sample": normalized_body[:240] or None,
        }
    if not normalized_body:
        return {
            "ok": False,
            "status_code": status,
            "error_kind": "empty_response",
            "error": "empty_response",
            "request_url": sanitized_url,
            "payload": None,
            "sample": None,
        }

    try:
        response_payload = json.loads(normalized_body)
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "status_code": status,
            "error_kind": "invalid_json",
            "error": str(exc),
            "request_url": sanitized_url,
            "payload": None,
            "sample": normalized_body[:240],
        }

    if response_payload in (None, {}, []):
        return {
            "ok": False,
            "status_code": status,
            "error_kind": "empty_response",
            "error": "empty_response",
            "request_url": sanitized_url,
            "payload": response_payload,
            "sample": sample_payload(response_payload, max_items=3),
        }

    return {
        "ok": True,
        "status_code": status,
        "error_kind": None,
        "error": None,
        "request_url": sanitized_url,
        "payload": response_payload,
        "sample": sample_payload(response_payload, max_items=3),
    }


def _compact_runtime_path(path: Path) -> str:
    return repo_relative(path)


def _read_json_path(path: Path) -> tuple[Any, list[str]]:
    if not path.exists():
        return {}, [f"missing_input_path:{_compact_runtime_path(path)}"]
    try:
        return load_json_file(path, default={}), []
    except json.JSONDecodeError as exc:
        return {}, [f"invalid_input_json:{_compact_runtime_path(path)}:{exc}"]


def _compact_polymarket_fragment(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return sample_payload(payload, max_items=3)
    signal_inputs = payload.get("signal_inputs", [])
    if not isinstance(signal_inputs, list):
        signal_inputs = []
    endpoint_results = payload.get("endpoint_results", [])
    if not isinstance(endpoint_results, list):
        endpoint_results = []
    return {
        "source_name": payload.get("source_name"),
        "external_observation_active": payload.get("external_observation_active"),
        "coverage_state": payload.get("coverage_state"),
        "signal_inputs": [
            {
                "ticker": row.get("ticker"),
                "question": row.get("question"),
                "category": row.get("category"),
                "observability_score": row.get("observability_score"),
                "condition_id": row.get("condition_id"),
            }
            for row in signal_inputs[:3]
            if isinstance(row, dict)
        ],
        "endpoint_results": [
            {
                "endpoint_name": row.get("endpoint_name"),
                "ok": row.get("ok"),
                "summary": row.get("summary"),
            }
            for row in endpoint_results[:3]
            if isinstance(row, dict)
        ],
        "limitations": list(payload.get("limitations", []))[:5],
        "note": payload.get("note"),
    }


def _compact_blockscout_fragment(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return sample_payload(payload, max_items=3)
    endpoint_results = payload.get("endpoint_results", [])
    if not isinstance(endpoint_results, list):
        endpoint_results = []
    return {
        "source_name": payload.get("source_name"),
        "external_observation_active": payload.get("external_observation_active"),
        "coverage_state": payload.get("coverage_state"),
        "resolved_mode": payload.get("resolved_mode"),
        "chain_id": payload.get("chain_id"),
        "endpoint_results": [
            {
                "endpoint_name": row.get("endpoint_name"),
                "ok": row.get("ok"),
                "summary": row.get("summary"),
            }
            for row in endpoint_results[:3]
            if isinstance(row, dict)
        ],
        "limitations": list(payload.get("limitations", []))[:5],
        "note": payload.get("note"),
    }


def _compact_signal_ranking_fragment(runtime_state: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    limitations: list[str] = []
    action_report = load_json_file(ACTION_REPORT_PATH, default={}) or {}
    health_report = load_json_file(HEALTH_REPORT_PATH, default={}) or {}
    if not isinstance(action_report, dict) or not action_report:
        action_report = {}
        limitations.append(f"missing_runtime_artifact:{_compact_runtime_path(ACTION_REPORT_PATH)}")
    if not isinstance(health_report, dict) or not health_report:
        health_report = {}
        limitations.append(f"missing_runtime_artifact:{_compact_runtime_path(HEALTH_REPORT_PATH)}")

    per_signal_rows = runtime_state.get("per_signal_attribution", [])
    if not isinstance(per_signal_rows, list):
        per_signal_rows = []
    action_rows = action_report.get("actions", [])
    if not isinstance(action_rows, list):
        action_rows = []

    payload = {
        "signal_summary": runtime_state.get("signal_summary", {}),
        "candidate_signals": [
            {
                "signal_id": row.get("signal_id"),
                "ticker": row.get("ticker"),
                "status": row.get("status"),
                "priority_score": row.get("priority_score"),
                "blocker_attribution": row.get("blocker_attribution"),
                "signal_origin": row.get("signal_origin"),
            }
            for row in per_signal_rows[:5]
            if isinstance(row, dict)
        ],
        "action_rows": [
            {
                "ticker": row.get("ticker"),
                "action": row.get("action"),
                "priority_score": row.get("priority_score"),
                "reason": row.get("reason"),
                "policy_state": row.get("policy_state"),
            }
            for row in action_rows[:5]
            if isinstance(row, dict)
        ],
        "health_context": {
            "what_should_i_do_next": health_report.get("what_should_i_do_next"),
            "system_readiness_state": health_report.get("system_readiness_state"),
            "friction_band": (health_report.get("friction") or {}).get("friction_band"),
            "signal_source_summary": health_report.get("signal_source_summary"),
        },
    }
    if not payload["candidate_signals"]:
        limitations.append("no_candidate_signals_available_for_ranking")
    return payload, limitations


def _resolve_use_case_input(
    *,
    use_case: str,
    input_path: Path | None = None,
    input_json: str | None = None,
    runtime_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if input_json is not None:
        try:
            payload = json.loads(input_json)
            return {
                "input_source": "inline_json",
                "payload": payload,
                "input_kind": classify_payload_kind(payload),
                "limitations": [],
                "input_preview": sample_payload(payload, max_items=4),
            }
        except json.JSONDecodeError as exc:
            return {
                "input_source": "inline_json",
                "payload": {},
                "input_kind": "dict",
                "limitations": [f"invalid_input_json:inline_json:{exc}"],
                "input_preview": {},
                "input_error_kind": "invalid_input_json",
                "input_error": str(exc),
            }

    if input_path is not None:
        payload, limitations = _read_json_path(input_path)
        return {
            "input_source": f"file:{_compact_runtime_path(input_path)}",
            "payload": payload,
            "input_kind": classify_payload_kind(payload),
            "limitations": limitations,
            "input_preview": sample_payload(payload, max_items=4),
        }

    if use_case == "polymarket_payload_interpreter":
        payload, limitations = _read_json_path(POLYMARKET_GAMMA_REPORT_PATH)
        compact = _compact_polymarket_fragment(payload)
        return {
            "input_source": f"file:{_compact_runtime_path(POLYMARKET_GAMMA_REPORT_PATH)}",
            "payload": compact,
            "input_kind": classify_payload_kind(compact),
            "limitations": limitations,
            "input_preview": sample_payload(compact, max_items=4),
        }
    if use_case == "blockscout_payload_interpreter":
        payload, limitations = _read_json_path(BLOCKSCOUT_REPORT_PATH)
        compact = _compact_blockscout_fragment(payload)
        return {
            "input_source": f"file:{_compact_runtime_path(BLOCKSCOUT_REPORT_PATH)}",
            "payload": compact,
            "input_kind": classify_payload_kind(compact),
            "limitations": limitations,
            "input_preview": sample_payload(compact, max_items=4),
        }

    base_state = runtime_state or load_current_pipeline_state(prefer_runtime_files=True)
    compact, limitations = _compact_signal_ranking_fragment(base_state)
    return {
        "input_source": "runtime_signal_bundle",
        "payload": compact,
        "input_kind": classify_payload_kind(compact),
        "limitations": limitations,
        "input_preview": sample_payload(compact, max_items=4),
    }


def _polymarket_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "object_type",
            "primary_thesis",
            "why_it_matters",
            "key_risks",
            "likely_signal_type",
            "confidence",
            "recommended_operator_action",
        ],
        "properties": {
            "object_type": {"type": "string"},
            "primary_thesis": {"type": "string"},
            "why_it_matters": {"type": "string"},
            "key_risks": {"type": "array", "items": {"type": "string"}},
            "likely_signal_type": {
                "type": "string",
                "enum": sorted(ALLOWED_SIGNAL_TYPES),
            },
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "recommended_operator_action": {
                "type": "string",
                "enum": sorted(ALLOWED_OPERATOR_ACTIONS),
            },
        },
    }


def _blockscout_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "object_type",
            "activity_pattern",
            "why_it_matters",
            "notable_flags",
            "likely_relevance",
            "confidence",
            "recommended_operator_action",
        ],
        "properties": {
            "object_type": {"type": "string"},
            "activity_pattern": {"type": "string"},
            "why_it_matters": {"type": "string"},
            "notable_flags": {"type": "array", "items": {"type": "string"}},
            "likely_relevance": {
                "type": "string",
                "enum": sorted(ALLOWED_RELEVANCE),
            },
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "recommended_operator_action": {
                "type": "string",
                "enum": sorted(ALLOWED_OPERATOR_ACTIONS),
            },
        },
    }


def _signal_ranking_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "ranked_items",
            "top_item",
            "why_top_item",
            "risks_of_misread",
            "operator_focus",
        ],
        "properties": {
            "ranked_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "item_id",
                        "label",
                        "rank",
                        "relevance_score",
                        "rationale",
                    ],
                    "properties": {
                        "item_id": {"type": "string"},
                        "label": {"type": "string"},
                        "rank": {"type": "integer", "minimum": 1},
                        "relevance_score": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                        },
                        "rationale": {"type": "string"},
                    },
                },
            },
            "top_item": {
                "type": ["object", "null"],
                "additionalProperties": False,
                "required": ["item_id", "label", "rank"],
                "properties": {
                    "item_id": {"type": "string"},
                    "label": {"type": "string"},
                    "rank": {"type": "integer", "minimum": 1},
                },
            },
            "why_top_item": {"type": "string"},
            "risks_of_misread": {"type": "array", "items": {"type": "string"}},
            "operator_focus": {"type": "string"},
        },
    }


def _schema_for_use_case(use_case: str) -> dict[str, Any]:
    if use_case == "polymarket_payload_interpreter":
        return _polymarket_schema()
    if use_case == "blockscout_payload_interpreter":
        return _blockscout_schema()
    return _signal_ranking_schema()


def _system_prompt_for_use_case(use_case: str) -> str:
    if use_case == "polymarket_payload_interpreter":
        return (
            "You are a read-only intelligence layer inside a paper-safe decision pipeline. "
            "Interpret only the supplied Polymarket payload fragment. Do not imply market proof, "
            "trade approval, or execution authority. If evidence is thin, lower confidence and "
            "prefer gather_more_evidence or cross_check. Return JSON only."
        )
    if use_case == "blockscout_payload_interpreter":
        return (
            "You are a read-only intelligence layer inside a paper-safe decision pipeline. "
            "Interpret only the supplied Blockscout payload fragment. Describe the observed "
            "activity pattern without claiming onchain intent beyond the payload. Return JSON only."
        )
    return (
        "You are a read-only intelligence layer inside a paper-safe decision pipeline. "
        "Rank only the supplied candidate signals and runtime snippets. You do not approve trades, "
        "change governance, or fabricate certainty. Return JSON only."
    )


def _user_prompt_for_use_case(use_case: str, payload: Any) -> str:
    if use_case == "polymarket_payload_interpreter":
        instruction = (
            "Classify the Polymarket fragment. Extract what the object is, the main thesis, why "
            "it matters, key risks, the most likely signal type, a bounded confidence score, and "
            "the best operator follow-up."
        )
    elif use_case == "blockscout_payload_interpreter":
        instruction = (
            "Classify the Blockscout fragment. Extract the observed activity pattern, why it may "
            "matter, notable flags, likely relevance, bounded confidence, and the best operator "
            "follow-up."
        )
    else:
        instruction = (
            "Rank the supplied candidate signals and action snippets. Identify the strongest item "
            "to inspect next, why it ranks first, the main risks of misreading it, and the focus "
            "the operator should keep."
        )
    return (
        f"{instruction}\n"
        "Return only valid JSON matching the requested schema.\n"
        "Payload:\n"
        f"{json.dumps(payload, indent=2, sort_keys=True)}"
    )


def _build_request_body(
    *,
    use_case: str,
    input_payload: Any,
    model_name: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    use_case_defaults = config.get("use_case_defaults", {})
    if not isinstance(use_case_defaults, dict):
        use_case_defaults = {}
    request_defaults = use_case_defaults.get(use_case, {})
    if not isinstance(request_defaults, dict):
        request_defaults = {}

    payload: dict[str, Any] = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": _system_prompt_for_use_case(use_case)},
            {"role": "user", "content": _user_prompt_for_use_case(use_case, input_payload)},
        ],
        "temperature": float(request_defaults.get("temperature", 0.0)),
        "stream": False,
        "response_format": {
            "type": str(config.get("response_format_mode") or "json_schema"),
            "json_schema": {
                "name": use_case,
                "schema": _schema_for_use_case(use_case),
                "strict": True,
            },
        },
    }
    max_output_tokens = request_defaults.get("max_output_tokens")
    if max_output_tokens is not None:
        payload["max_tokens"] = int(max_output_tokens)
    return payload


def _resolve_endpoint_path(config: dict[str, Any]) -> str:
    configured = str(config.get("endpoint_path") or DEFAULT_ENDPOINT_PATH).strip()
    if not configured:
        return DEFAULT_ENDPOINT_PATH
    if configured == "/chat/completions":
        return DEFAULT_ENDPOINT_PATH
    if configured == "chat/completions":
        return DEFAULT_ENDPOINT_PATH
    if not configured.startswith("/"):
        return f"/{configured}"
    return configured


def _extract_message_content(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices", [])
    if not isinstance(choices, list) or not choices:
        return ""
    first_choice = choices[0] if isinstance(choices[0], dict) else {}
    message = first_choice.get("message", {})
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            text_value = item.get("text")
            if isinstance(text_value, str) and text_value.strip():
                parts.append(text_value.strip())
        return "\n".join(parts).strip()
    return ""


def _strip_fenced_json(text: str) -> str:
    normalized = text.strip()
    if normalized.startswith("```") and normalized.endswith("```"):
        lines = normalized.splitlines()
        if len(lines) >= 3:
            return "\n".join(lines[1:-1]).strip()
    return normalized


def _ensure_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _ensure_string_array(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{key} entries must be non-empty strings")
        result.append(item.strip())
    return result


def _ensure_confidence(payload: dict[str, Any], key: str = "confidence") -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be numeric")
    normalized = float(value)
    if normalized < 0.0 or normalized > 1.0:
        raise ValueError(f"{key} must be between 0.0 and 1.0")
    return round(normalized, 4)


def _validate_polymarket_output(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("structured output must be an object")
    likely_signal_type = _ensure_string(payload, "likely_signal_type")
    if likely_signal_type not in ALLOWED_SIGNAL_TYPES:
        raise ValueError("likely_signal_type must be one of the allowed signal types")
    recommended_operator_action = _ensure_string(payload, "recommended_operator_action")
    if recommended_operator_action not in ALLOWED_OPERATOR_ACTIONS:
        raise ValueError("recommended_operator_action must be an allowed action")
    return {
        "object_type": _ensure_string(payload, "object_type"),
        "primary_thesis": _ensure_string(payload, "primary_thesis"),
        "why_it_matters": _ensure_string(payload, "why_it_matters"),
        "key_risks": _ensure_string_array(payload, "key_risks"),
        "likely_signal_type": likely_signal_type,
        "confidence": _ensure_confidence(payload),
        "recommended_operator_action": recommended_operator_action,
    }


def _validate_blockscout_output(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("structured output must be an object")
    likely_relevance = _ensure_string(payload, "likely_relevance")
    if likely_relevance not in ALLOWED_RELEVANCE:
        raise ValueError("likely_relevance must be an allowed relevance band")
    recommended_operator_action = _ensure_string(payload, "recommended_operator_action")
    if recommended_operator_action not in ALLOWED_OPERATOR_ACTIONS:
        raise ValueError("recommended_operator_action must be an allowed action")
    return {
        "object_type": _ensure_string(payload, "object_type"),
        "activity_pattern": _ensure_string(payload, "activity_pattern"),
        "why_it_matters": _ensure_string(payload, "why_it_matters"),
        "notable_flags": _ensure_string_array(payload, "notable_flags"),
        "likely_relevance": likely_relevance,
        "confidence": _ensure_confidence(payload),
        "recommended_operator_action": recommended_operator_action,
    }


def _validate_top_item(payload: Any) -> dict[str, Any] | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("top_item must be an object or null")
    rank = payload.get("rank")
    if isinstance(rank, bool) or not isinstance(rank, int) or rank < 1:
        raise ValueError("top_item.rank must be a positive integer")
    return {
        "item_id": _ensure_string(payload, "item_id"),
        "label": _ensure_string(payload, "label"),
        "rank": rank,
    }


def _validate_signal_ranking_output(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("structured output must be an object")
    ranked_items_value = payload.get("ranked_items")
    if not isinstance(ranked_items_value, list):
        raise ValueError("ranked_items must be a list")
    ranked_items: list[dict[str, Any]] = []
    for item in ranked_items_value:
        if not isinstance(item, dict):
            raise ValueError("ranked_items entries must be objects")
        rank = item.get("rank")
        if isinstance(rank, bool) or not isinstance(rank, int) or rank < 1:
            raise ValueError("ranked_items.rank must be a positive integer")
        relevance_score = item.get("relevance_score")
        if isinstance(relevance_score, bool) or not isinstance(relevance_score, (int, float)):
            raise ValueError("ranked_items.relevance_score must be numeric")
        normalized_relevance = float(relevance_score)
        if normalized_relevance < 0.0 or normalized_relevance > 1.0:
            raise ValueError("ranked_items.relevance_score must be between 0.0 and 1.0")
        ranked_items.append(
            {
                "item_id": _ensure_string(item, "item_id"),
                "label": _ensure_string(item, "label"),
                "rank": rank,
                "relevance_score": round(normalized_relevance, 4),
                "rationale": _ensure_string(item, "rationale"),
            }
        )
    return {
        "ranked_items": ranked_items,
        "top_item": _validate_top_item(payload.get("top_item")),
        "why_top_item": _ensure_string(payload, "why_top_item"),
        "risks_of_misread": _ensure_string_array(payload, "risks_of_misread"),
        "operator_focus": _ensure_string(payload, "operator_focus"),
    }


def _validate_structured_output(use_case: str, payload: Any) -> dict[str, Any]:
    if use_case == "polymarket_payload_interpreter":
        return _validate_polymarket_output(payload)
    if use_case == "blockscout_payload_interpreter":
        return _validate_blockscout_output(payload)
    return _validate_signal_ranking_output(payload)


def _failure_payload(
    *,
    runtime_state: dict[str, Any],
    fetched_at: str,
    use_case: str,
    config: dict[str, Any],
    input_context: dict[str, Any],
    model_requested: str | None,
    request_url: str | None,
    request_attempted: bool,
    request_success: bool,
    status_code: int | None,
    error_kind: str,
    error: str,
    response_sample: Any = None,
) -> dict[str, Any]:
    return stamp_payload(
        {
            "artifact_kind": "grok_intelligence_report",
            "fetched_at": fetched_at,
            "source_name": SOURCE_NAME,
            "source_type": SOURCE_TYPE,
            "provider_name": SOURCE_NAME,
            "use_case": use_case,
            "model_requested": model_requested,
            "model_used": None,
            "request_attempted": request_attempted,
            "request_success": request_success,
            "status_code": status_code,
            "error_kind": error_kind,
            "error": error,
            "request_url": request_url,
            "response_format_mode": str(config.get("response_format_mode") or "json_schema"),
            "input_source": input_context.get("input_source"),
            "input_kind": input_context.get("input_kind"),
            "input_preview": input_context.get("input_preview"),
            "input_limitations": list(input_context.get("limitations", [])),
            "response_sample": response_sample,
            "extracted_output": None,
            "read_only_contract": dict(load_llm_provider_config().get("read_only_contract", {})),
            "note": (
                "Grok is an intelligence layer only. It interprets observed payloads into "
                "structured JSON for operator review and does not approve trades, bypass "
                "governance, or enable execution."
            ),
        },
        runtime_state=runtime_state,
    )


def _runtime_state_for_stamping(
    base_state: dict[str, Any],
    *,
    use_case: str,
    input_payload: Any,
    fetched_at: str,
) -> dict[str, Any]:
    if use_case in {"polymarket_payload_interpreter", "blockscout_payload_interpreter"}:
        if (
            isinstance(input_payload, dict)
            and input_payload.get("source_name")
            and bool(input_payload.get("external_observation_active"))
        ):
            return build_external_runtime_state(
                base_state,
                active=True,
                source_name=str(input_payload.get("source_name") or use_case),
                fetched_at=fetched_at,
            )
    return base_state


def build_grok_xai_report(
    *,
    use_case: str | None = None,
    runtime_state: dict[str, Any] | None = None,
    config_path: Path | None = None,
    transport: PostTransport | None = None,
    input_path: Path | None = None,
    input_json: str | None = None,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    canonical_use_case = _normalize_use_case(use_case)
    config = get_provider_config(SOURCE_NAME, config_path)
    full_config = load_llm_provider_config(config_path)
    read_only_contract = dict(full_config.get("read_only_contract", {}))
    base_state = runtime_state or load_current_pipeline_state(prefer_runtime_files=True)
    fetch_timestamp = fetched_at or utc_timestamp()
    input_context = _resolve_use_case_input(
        use_case=canonical_use_case,
        input_path=input_path,
        input_json=input_json,
        runtime_state=base_state,
    )
    stamping_state = _runtime_state_for_stamping(
        base_state,
        use_case=canonical_use_case,
        input_payload=input_context.get("payload"),
        fetched_at=fetch_timestamp,
    )

    if input_context.get("input_error_kind"):
        payload = _failure_payload(
            runtime_state=stamping_state,
            fetched_at=fetch_timestamp,
            use_case=canonical_use_case,
            config=config,
            input_context=input_context,
            model_requested=None,
            request_url=None,
            request_attempted=False,
            request_success=False,
            status_code=None,
            error_kind=str(input_context.get("input_error_kind")),
            error=str(input_context.get("input_error") or "invalid_input_json"),
        )
        payload["read_only_contract"] = read_only_contract
        return payload

    base_url = resolve_env_value(config.get("env_base_url"))
    api_key = resolve_env_value(config.get("env_api_key"))
    model_name = resolve_env_value(config.get("env_model"))
    timeout_seconds = float(config.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)
    endpoint_path = _resolve_endpoint_path(config)
    user_agent = str(config.get("user_agent") or DEFAULT_USER_AGENT)
    require_explicit_model_env = bool(config.get("require_explicit_model_env", True))

    missing_requirements: list[str] = []
    if not base_url:
        missing_requirements.append(
            f"missing_env_base_url:{config.get('env_base_url') or 'XAI_API_BASE_URL'}"
        )
    if not api_key:
        missing_requirements.append(
            f"missing_env_api_key:{config.get('env_api_key') or 'XAI_API_KEY'}"
        )
    if require_explicit_model_env and not model_name:
        missing_requirements.append(
            f"missing_env_model:{config.get('env_model') or 'XAI_MODEL'}"
        )
    if missing_requirements:
        payload = _failure_payload(
            runtime_state=stamping_state,
            fetched_at=fetch_timestamp,
            use_case=canonical_use_case,
            config=config,
            input_context=input_context,
            model_requested=model_name,
            request_url=None,
            request_attempted=False,
            request_success=False,
            status_code=None,
            error_kind="config_error",
            error="; ".join(missing_requirements),
        )
        payload["limitations"] = list(input_context.get("limitations", [])) + missing_requirements
        payload["read_only_contract"] = read_only_contract
        return payload

    request_body = _build_request_body(
        use_case=canonical_use_case,
        input_payload=input_context.get("payload"),
        model_name=str(model_name),
        config=config,
    )
    request_url = build_request_url(str(base_url), endpoint_path)
    response = _post_json(
        request_url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": user_agent,
        },
        payload=request_body,
        timeout_seconds=timeout_seconds,
        transport=transport,
    )
    if not response.get("ok"):
        payload = _failure_payload(
            runtime_state=stamping_state,
            fetched_at=fetch_timestamp,
            use_case=canonical_use_case,
            config=config,
            input_context=input_context,
            model_requested=str(model_name),
            request_url=response.get("request_url"),
            request_attempted=True,
            request_success=False,
            status_code=response.get("status_code"),
            error_kind=str(response.get("error_kind") or "request_error"),
            error=str(response.get("error") or "request_error"),
            response_sample=response.get("sample"),
        )
        payload["limitations"] = list(input_context.get("limitations", []))
        payload["read_only_contract"] = read_only_contract
        return payload

    response_payload = response.get("payload")
    content = _extract_message_content(response_payload)
    if not content:
        payload = _failure_payload(
            runtime_state=stamping_state,
            fetched_at=fetch_timestamp,
            use_case=canonical_use_case,
            config=config,
            input_context=input_context,
            model_requested=str(model_name),
            request_url=response.get("request_url"),
            request_attempted=True,
            request_success=False,
            status_code=response.get("status_code"),
            error_kind="empty_response",
            error="empty_response",
            response_sample=response.get("sample"),
        )
        payload["limitations"] = list(input_context.get("limitations", []))
        payload["read_only_contract"] = read_only_contract
        return payload

    try:
        structured_output = json.loads(_strip_fenced_json(content))
    except json.JSONDecodeError as exc:
        payload = _failure_payload(
            runtime_state=stamping_state,
            fetched_at=fetch_timestamp,
            use_case=canonical_use_case,
            config=config,
            input_context=input_context,
            model_requested=str(model_name),
            request_url=response.get("request_url"),
            request_attempted=True,
            request_success=False,
            status_code=response.get("status_code"),
            error_kind="invalid_json",
            error=str(exc),
            response_sample=content[:240],
        )
        payload["limitations"] = list(input_context.get("limitations", []))
        payload["read_only_contract"] = read_only_contract
        return payload

    try:
        validated_output = _validate_structured_output(canonical_use_case, structured_output)
    except ValueError as exc:
        payload = _failure_payload(
            runtime_state=stamping_state,
            fetched_at=fetch_timestamp,
            use_case=canonical_use_case,
            config=config,
            input_context=input_context,
            model_requested=str(model_name),
            request_url=response.get("request_url"),
            request_attempted=True,
            request_success=False,
            status_code=response.get("status_code"),
            error_kind="invalid_structured_output",
            error=str(exc),
            response_sample=sample_payload(structured_output, max_items=4),
        )
        payload["limitations"] = list(input_context.get("limitations", []))
        payload["read_only_contract"] = read_only_contract
        return payload

    model_used = None
    if isinstance(response_payload, dict):
        model_used = response_payload.get("model") or response_payload.get("model_name")

    payload = stamp_payload(
        {
            "artifact_kind": "grok_intelligence_report",
            "fetched_at": fetch_timestamp,
            "source_name": SOURCE_NAME,
            "source_type": SOURCE_TYPE,
            "provider_name": SOURCE_NAME,
            "use_case": canonical_use_case,
            "model_requested": str(model_name),
            "model_used": str(model_used or model_name),
            "request_attempted": True,
            "request_success": True,
            "status_code": response.get("status_code"),
            "error_kind": None,
            "error": None,
            "request_url": response.get("request_url"),
            "response_format_mode": str(config.get("response_format_mode") or "json_schema"),
            "response_id": response_payload.get("id") if isinstance(response_payload, dict) else None,
            "system_fingerprint": response_payload.get("system_fingerprint")
            if isinstance(response_payload, dict)
            else None,
            "input_source": input_context.get("input_source"),
            "input_kind": input_context.get("input_kind"),
            "input_preview": input_context.get("input_preview"),
            "input_limitations": list(input_context.get("limitations", [])),
            "response_sample": response.get("sample"),
            "extracted_output": validated_output,
            "read_only_contract": read_only_contract,
            "limitations": list(input_context.get("limitations", [])),
            "note": (
                "Grok is an intelligence layer only. It interprets observed payloads into "
                "structured JSON for operator review and does not approve trades, bypass "
                "governance, or enable execution."
            ),
        },
        runtime_state=stamping_state,
    )
    return payload


def write_grok_xai_report(
    *,
    use_case: str | None = None,
    runtime_state: dict[str, Any] | None = None,
    config_path: Path | None = None,
    transport: PostTransport | None = None,
    input_path: Path | None = None,
    input_json: str | None = None,
    output_path: Path | None = None,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    config = get_provider_config(SOURCE_NAME, config_path)
    payload = build_grok_xai_report(
        use_case=use_case,
        runtime_state=runtime_state,
        config_path=config_path,
        transport=transport,
        input_path=input_path,
        input_json=input_json,
        fetched_at=fetched_at,
    )
    write_json_atomic(output_path or _report_path(config), payload, stamp=False)
    return payload


def format_grok_xai_summary(report: dict[str, Any]) -> str:
    extracted = report.get("extracted_output", {})
    if not isinstance(extracted, dict):
        extracted = {}
    operator_hint = (
        extracted.get("recommended_operator_action")
        or extracted.get("operator_focus")
        or "none"
    )
    return "\n".join(
        [
            "Grok xAI Intelligence",
            f"operating_mode={report['operating_mode']}",
            f"truth_origin={report['truth_origin']}",
            f"use_case={report.get('use_case')}",
            f"request_success={str(bool(report.get('request_success'))).lower()}",
            f"error_kind={report.get('error_kind') or 'none'}",
            f"model_used={report.get('model_used') or 'none'}",
            f"operator_hint={operator_hint}",
            f"output_path={repo_relative(GROK_XAI_REPORT_PATH)}",
        ]
    )


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Call xAI Grok as a read-only intelligence extraction layer."
    )
    parser.add_argument(
        "--use-case",
        default=DEFAULT_USE_CASE,
        choices=sorted(
            {
                "polymarket_payload_interpreter",
                "blockscout_payload_interpreter",
                "signal_ranking_interpreter",
            }
        ),
        help="Which structured intelligence prompt to run.",
    )
    parser.add_argument(
        "--input-path",
        type=Path,
        help="Optional JSON file to interpret instead of the default runtime artifact for the chosen use case.",
    )
    parser.add_argument(
        "--input-json",
        help="Optional inline JSON payload to interpret instead of loading a file.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    mode.add_argument("--summary", action="store_true", help="Emit a compact human-readable summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    report = write_grok_xai_report(
        use_case=args.use_case,
        input_path=args.input_path,
        input_json=args.input_json,
    )
    if args.summary:
        print(format_grok_xai_summary(report))
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
