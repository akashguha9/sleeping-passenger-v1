from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.grok_xai_adapter import (
    build_grok_xai_report,
    default_llm_provider_config,
    load_llm_provider_config,
    write_grok_xai_report,
)
from scripts.pipeline_health_report import build_pipeline_health_report
from scripts.runtime_common import build_runtime_state_from_scm_report_payload
from scripts.signal_conversion_monitor import build_signal_conversion_report


def _runtime_state() -> dict:
    return build_runtime_state_from_scm_report_payload(build_signal_conversion_report())


def _write_config(path: Path, scratch_path: Path) -> Path:
    config = default_llm_provider_config()
    config["providers"]["grok_xai"]["timeout_seconds"] = 9.0
    config["providers"]["grok_xai"]["report_path"] = str(scratch_path / "grok_xai_report.json")
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return path


def test_llm_provider_config_loading_keeps_defaults_under_override(
    scratch_path: Path,
) -> None:
    config_path = _write_config(scratch_path / "llm_provider_config.json", scratch_path)

    payload = load_llm_provider_config(config_path)

    assert payload["providers"]["grok_xai"]["timeout_seconds"] == 9.0
    assert payload["providers"]["grok_xai"]["env_api_key"] == "XAI_API_KEY"
    assert payload["providers"]["grok_xai"]["env_model"] == "XAI_MODEL"
    assert payload["read_only_contract"]["silent_model_fallback_allowed"] is False
    assert payload["read_only_contract"]["wallet_signing_supported"] is False


def test_grok_xai_unauthorized_handling_is_classified_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XAI_API_BASE_URL", "https://api.x.ai/v1")
    monkeypatch.setenv("XAI_API_KEY", "bad-key")
    monkeypatch.setenv("XAI_MODEL", "grok-test")

    def unauthorized_transport(
        url: str,
        headers: dict[str, str] | None,
        payload: dict,
        timeout: float,
    ):
        assert headers is not None
        assert headers["Authorization"] == "Bearer bad-key"
        assert payload["model"] == "grok-test"
        return 401, json.dumps({"error": {"message": "invalid api key"}})

    report = build_grok_xai_report(
        use_case="polymarket_payload_interpreter",
        runtime_state=_runtime_state(),
        input_json=json.dumps({"event": "test"}),
        transport=unauthorized_transport,
    )

    assert report["request_attempted"] is True
    assert report["request_success"] is False
    assert report["error_kind"] == "unauthorized"
    assert report["read_only_contract"]["suggestion_only"] is True
    assert report["read_only_contract"]["live_execution_enabled"] is False


def test_grok_xai_invalid_json_handling_is_truthful(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XAI_API_BASE_URL", "https://api.x.ai/v1")
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    monkeypatch.setenv("XAI_MODEL", "grok-test")

    def invalid_json_transport(
        url: str,
        headers: dict[str, str] | None,
        payload: dict,
        timeout: float,
    ):
        return 200, "not valid json"

    report = build_grok_xai_report(
        use_case="blockscout_payload_interpreter",
        runtime_state=_runtime_state(),
        input_json=json.dumps({"blocks": [1, 2, 3]}),
        transport=invalid_json_transport,
    )

    assert report["request_success"] is False
    assert report["error_kind"] == "invalid_json"


def test_grok_xai_empty_response_handling_is_truthful(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XAI_API_BASE_URL", "https://api.x.ai/v1")
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    monkeypatch.setenv("XAI_MODEL", "grok-test")

    def empty_content_transport(
        url: str,
        headers: dict[str, str] | None,
        payload: dict,
        timeout: float,
    ):
        return 200, json.dumps({"id": "resp_1", "choices": [{"message": {"content": ""}}]})

    report = build_grok_xai_report(
        use_case="blockscout_payload_interpreter",
        runtime_state=_runtime_state(),
        input_json=json.dumps({"backend_version": "7.0.0"}),
        transport=empty_content_transport,
    )

    assert report["request_success"] is False
    assert report["error_kind"] == "empty_response"


def test_grok_xai_successful_structured_output_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XAI_API_BASE_URL", "https://api.x.ai/v1")
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    monkeypatch.setenv("XAI_MODEL", "grok-test")

    def success_transport(
        url: str,
        headers: dict[str, str] | None,
        payload: dict,
        timeout: float,
    ):
        assert payload["model"] == "grok-test"
        return (
            200,
            json.dumps(
                {
                    "id": "resp_success",
                    "model": "grok-test",
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "ranked_items": [
                                            {
                                                "item_id": "RTX",
                                                "label": "RTX clean watchlist candidate",
                                                "rank": 1,
                                                "relevance_score": 0.84,
                                                "rationale": "Highest current priority score.",
                                            },
                                            {
                                                "item_id": "ZIM",
                                                "label": "ZIM secondary candidate",
                                                "rank": 2,
                                                "relevance_score": 0.61,
                                                "rationale": "Still relevant but lower urgency.",
                                            },
                                        ],
                                        "top_item": {
                                            "item_id": "RTX",
                                            "label": "RTX clean watchlist candidate",
                                            "rank": 1,
                                        },
                                        "why_top_item": "RTX is the clearest current candidate.",
                                        "risks_of_misread": [
                                            "Priority may reflect stale runtime state."
                                        ],
                                        "operator_focus": "Cross-check RTX before escalating action."
                                    }
                                )
                            }
                        }
                    ],
                }
            ),
        )

    report = build_grok_xai_report(
        use_case="signal_ranking_interpreter",
        runtime_state=_runtime_state(),
        input_json=json.dumps({"candidate_signals": [{"ticker": "RTX"}]}),
        transport=success_transport,
    )

    assert report["request_success"] is True
    assert report["error_kind"] is None
    assert report["model_used"] == "grok-test"
    assert report["extracted_output"]["top_item"]["item_id"] == "RTX"
    assert report["extracted_output"]["ranked_items"][0]["rank"] == 1


def test_write_grok_xai_report_generates_runtime_artifact(
    scratch_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _write_config(scratch_path / "llm_provider_config.json", scratch_path)
    output_path = scratch_path / "grok_xai_report.json"
    monkeypatch.setenv("XAI_API_BASE_URL", "https://api.x.ai/v1")
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    monkeypatch.setenv("XAI_MODEL", "grok-test")

    def success_transport(
        url: str,
        headers: dict[str, str] | None,
        payload: dict,
        timeout: float,
    ):
        return (
            200,
            json.dumps(
                {
                    "id": "resp_polymarket",
                    "model": "grok-test",
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "object_type": "prediction_market_event",
                                        "primary_thesis": "The market prices a binary event window.",
                                        "why_it_matters": "It compresses crowd belief into one contract.",
                                        "key_risks": ["Liquidity can distort price discovery."],
                                        "likely_signal_type": "event_market",
                                        "confidence": 0.68,
                                        "recommended_operator_action": "cross_check",
                                    }
                                )
                            }
                        }
                    ],
                }
            ),
        )

    report = write_grok_xai_report(
        use_case="polymarket_payload_interpreter",
        runtime_state=_runtime_state(),
        config_path=config_path,
        input_json=json.dumps({"question": "Will test pass?"}),
        transport=success_transport,
        output_path=output_path,
    )

    persisted = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["request_success"] is True
    assert persisted["request_success"] is True
    assert persisted["artifact_kind"] == "grok_intelligence_report"
    assert persisted["extracted_output"]["likely_signal_type"] == "event_market"


def test_grok_xai_governance_boundary_remains_advisory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XAI_API_BASE_URL", "https://api.x.ai/v1")
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    monkeypatch.setenv("XAI_MODEL", "grok-test")

    def success_transport(
        url: str,
        headers: dict[str, str] | None,
        payload: dict,
        timeout: float,
    ):
        return (
            200,
            json.dumps(
                {
                    "id": "resp_blockscout",
                    "model": "grok-test",
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "object_type": "explorer_snapshot",
                                        "activity_pattern": "Stable recent block production.",
                                        "why_it_matters": "It suggests the chain is live and observable.",
                                        "notable_flags": ["No anomaly is directly proven here."],
                                        "likely_relevance": "medium",
                                        "confidence": 0.57,
                                        "recommended_operator_action": "monitor",
                                    }
                                )
                            }
                        }
                    ],
                }
            ),
        )

    report = build_grok_xai_report(
        use_case="blockscout_payload_interpreter",
        runtime_state=_runtime_state(),
        input_json=json.dumps({"blocks": [{"height": 12345}]}),
        transport=success_transport,
    )

    assert report["request_success"] is True
    assert report["read_only_contract"]["suggestion_only"] is True
    assert report["read_only_contract"]["paper_safe"] is True
    assert report["read_only_contract"]["order_placement_supported"] is False
    assert report["read_only_contract"]["wallet_signing_supported"] is False
    assert report["read_only_contract"]["autonomous_execution_supported"] is False
    assert report["read_only_contract"]["silent_model_fallback_allowed"] is False


def test_pipeline_health_report_accepts_explicit_grok_summary() -> None:
    payload = build_pipeline_health_report(
        include_tests=False,
        write_runtime=False,
        runtime_state=_runtime_state(),
        grok_xai_report={
            "request_attempted": True,
            "request_success": True,
            "use_case": "signal_ranking_interpreter",
            "model_used": "grok-test",
            "extracted_output": {
                "top_item": {"item_id": "RTX", "label": "RTX", "rank": 1},
                "operator_focus": "Review RTX first.",
            },
            "note": "Intelligence only.",
        },
    )

    assert payload["intelligence_summary"] == {
        "grok_report_present": True,
        "request_attempted": True,
        "request_success": True,
        "use_case": "signal_ranking_interpreter",
        "model_used": "grok-test",
        "recommended_operator_action": None,
        "operator_focus": "Review RTX first.",
        "top_item": {"item_id": "RTX", "label": "RTX", "rank": 1},
        "error_kind": None,
        "note": "Intelligence only.",
    }
