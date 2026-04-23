from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.blockscout_adapter import build_blockscout_report
from scripts.external_data_common import default_external_data_config, load_external_data_config
from scripts.external_data_runtime_sync import write_external_data_runtime_report
from scripts.polymarket_data_adapter import build_polymarket_data_report
from scripts.polymarket_gamma_adapter import (
    build_polymarket_gamma_report,
    write_polymarket_gamma_report,
)
from scripts.runtime_common import (
    build_runtime_state_from_scm_report_payload,
    resolve_source_mode,
    set_source_mode,
)
from scripts.signal_conversion_monitor import build_signal_conversion_report


def _runtime_state() -> dict:
    return build_runtime_state_from_scm_report_payload(build_signal_conversion_report())


def _write_config(path: Path, scratch_path: Path) -> Path:
    config = default_external_data_config()
    config["providers"]["polymarket_gamma"]["report_path"] = str(
        scratch_path / "polymarket_gamma_report.json"
    )
    config["providers"]["polymarket_gamma"]["signal_ingestion"]["signal_output_path"] = str(
        scratch_path / "signal_vocoder_etil_inputs.json"
    )
    config["providers"]["polymarket_data"]["report_path"] = str(
        scratch_path / "polymarket_data_report.json"
    )
    config["providers"]["polymarket_clob"]["report_path"] = str(
        scratch_path / "polymarket_clob_report.json"
    )
    config["providers"]["blockscout"]["report_path"] = str(
        scratch_path / "blockscout_report.json"
    )
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return path


def _gamma_success_transport(url: str, params: dict | None, headers: dict | None, timeout: float):
    if url.endswith("/markets"):
        return (
            200,
            json.dumps(
                [
                    {
                        "conditionId": "0xaaa",
                        "question": "Will gamma test pass?",
                        "active": True,
                    }
                ]
            ),
        )
    if url.endswith("/events/keyset"):
        return (
            200,
            json.dumps(
                {
                    "events": [
                        {
                            "slug": "gamma-test",
                            "active": True,
                            "category": "testing",
                        }
                    ]
                }
            ),
        )
    raise AssertionError(f"unexpected url: {url}")


def _full_success_transport(url: str, params: dict | None, headers: dict | None, timeout: float):
    if url.endswith("/markets"):
        return (
            200,
            json.dumps(
                [
                    {
                        "conditionId": "0xaaa",
                        "question": "Will gamma test pass?",
                        "active": True,
                    }
                ]
            ),
        )
    if url.endswith("/events/keyset"):
        return (
            200,
            json.dumps(
                {"events": [{"slug": "gamma-test", "active": True, "category": "testing"}]}
            ),
        )
    if url.endswith("/trades"):
        return (
            200,
            json.dumps(
                [
                    {
                        "conditionId": "0xaaa",
                        "title": "Will data test pass?",
                        "slug": "data-test",
                    }
                ]
            ),
        )
    if url.endswith("/oi"):
        return (200, json.dumps([{"market": "0xaaa", "value": 321.5}]))
    if url.endswith("/time"):
        return (200, json.dumps(1700000000))
    if url.endswith("/simplified-markets"):
        return (
            200,
            json.dumps(
                {
                    "data": [
                        {
                            "condition_id": "0xaaa",
                            "active": True,
                            "tokens": [
                                {"token_id": "token-1", "outcome": "YES", "price": 0.52}
                            ],
                        }
                    ],
                    "count": 1,
                    "limit": 1,
                }
            ),
        )
    if url.endswith("/book"):
        return (
            200,
            json.dumps(
                {
                    "market": "0xaaa",
                    "asset_id": "token-1",
                    "bids": [{"price": "0.51", "size": "100"}],
                    "asks": [{"price": "0.53", "size": "100"}],
                    "tick_size": "0.01",
                    "last_trade_price": "0.52",
                }
            ),
        )
    if url.endswith("/price"):
        return (200, json.dumps({"price": 0.51}))
    if url.endswith("/spread"):
        return (200, json.dumps({"spread": "0.02"}))
    if url.endswith("/prices-history"):
        return (
            200,
            json.dumps({"history": [{"t": 1700000000, "p": 0.5}, {"t": 1700086400, "p": 0.52}]}),
        )
    if url.endswith("/10/api/v2/config/backend-version"):
        return (200, json.dumps({"backend_version": "7.0.0"}))
    if url.endswith("/10/api/v2/main-page/blocks"):
        return (200, json.dumps([{"height": 12345}, {"height": 12344}]))
    raise AssertionError(f"unexpected url: {url}")


def test_external_data_config_loading_keeps_defaults_under_override(
    scratch_path: Path,
) -> None:
    config_path = scratch_path / "external_data_config.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "polymarket_gamma": {"markets_params": {"limit": 2, "closed": False}}
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    payload = load_external_data_config(config_path)

    assert payload["providers"]["polymarket_gamma"]["markets_params"]["limit"] == 2
    assert payload["providers"]["polymarket_gamma"]["signal_ingestion"]["enabled"] is True
    assert payload["providers"]["blockscout"]["env_api_key"] == "BLOCKSCOUT_API_KEY"
    assert payload["read_only_contract"]["order_placement_supported"] is False
    assert payload["read_only_contract"]["wallet_signing_supported"] is False


def test_polymarket_gamma_success_path_promotes_to_external_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POLY_GAMMA_BASE_URL", "https://gamma.example")

    report = build_polymarket_gamma_report(
        runtime_state=_runtime_state(),
        transport=_gamma_success_transport,
    )

    assert report["success_count"] == 2
    assert report["failure_count"] == 0
    assert report["external_observation_active"] is True
    assert report["truth_origin"] == "external"
    assert report["operating_mode"] == "hybrid"
    assert report["signal_input_summary"]["signal_count"] == 1
    signal_input = report["signal_inputs"][0]
    assert signal_input["status"] == "WATCHLIST"
    assert signal_input["source_name"] == "polymarket_gamma"
    assert signal_input["signal_origin"] == "external"


def test_write_polymarket_gamma_report_writes_etil_signal_inputs(
    scratch_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIPELINE_SOURCE_MODE", "SYNTHETIC_RUNTIME_FALLBACK")
    monkeypatch.setenv("POLY_GAMMA_BASE_URL", "https://gamma.example")
    report_path = scratch_path / "polymarket_gamma_report.json"
    signal_inputs_path = scratch_path / "signal_vocoder_etil_inputs.json"

    try:
        report = write_polymarket_gamma_report(
            runtime_state=_runtime_state(),
            transport=_gamma_success_transport,
            output_path=report_path,
            signal_output_path=signal_inputs_path,
        )

        etil_payload = json.loads(signal_inputs_path.read_text(encoding="utf-8"))
        assert report["source_mode"] == "LIVE_ETIL"
        assert etil_payload["signal_count"] == 1
        assert etil_payload["signal_inputs"][0]["source_name"] == "polymarket_gamma"
        assert resolve_source_mode(signal_inputs_path) == "LIVE_ETIL"
    finally:
        set_source_mode("SYNTHETIC_RUNTIME_FALLBACK")


def test_polymarket_gamma_request_failures_are_persisted_truthfully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POLY_GAMMA_BASE_URL", "https://gamma.example")

    def failing_transport(url: str, params: dict | None, headers: dict | None, timeout: float):
        raise RuntimeError("simulated_network_failure")

    report = build_polymarket_gamma_report(
        runtime_state=_runtime_state(),
        transport=failing_transport,
    )

    assert report["success_count"] == 0
    assert report["failure_count"] == 2
    assert report["external_observation_active"] is False
    assert report["coverage_state"] == "UNAVAILABLE"
    assert report["endpoint_results"][0]["error_kind"] == "request_error"


def test_blockscout_unauthorized_responses_are_classified_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BLOCKSCOUT_API_BASE_URL", "https://api.blockscout.com")
    monkeypatch.setenv("BLOCKSCOUT_API_KEY", "invalid-key")
    monkeypatch.setenv("BLOCKSCOUT_DEFAULT_CHAIN_ID", "10")

    def unauthorized_transport(url: str, params: dict | None, headers: dict | None, timeout: float):
        return (422, json.dumps({"message": "invalid api key"}))

    report = build_blockscout_report(
        runtime_state=_runtime_state(),
        transport=unauthorized_transport,
    )

    assert report["success_count"] == 0
    assert report["failure_count"] == 2
    assert report["coverage_state"] == "UNAVAILABLE"
    assert report["endpoint_results"][0]["error_kind"] == "unauthorized"
    assert report["external_observation_active"] is False


def test_polymarket_data_empty_response_is_not_promoted_to_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POLY_DATA_BASE_URL", "https://data.example")

    def empty_transport(url: str, params: dict | None, headers: dict | None, timeout: float):
        if url.endswith("/trades"):
            return (200, "[]")
        raise AssertionError(f"unexpected url: {url}")

    report = build_polymarket_data_report(
        runtime_state=_runtime_state(),
        transport=empty_transport,
    )

    trades_row = report["endpoint_results"][0]
    open_interest_row = report["endpoint_results"][1]
    assert trades_row["error_kind"] == "empty_response"
    assert trades_row["ok"] is False
    assert open_interest_row["attempted"] is False
    assert report["external_observation_active"] is False


def test_external_data_runtime_sync_writes_reports_and_keeps_read_only_contract(
    scratch_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _write_config(scratch_path / "external_data_config.json", scratch_path)
    output_path = scratch_path / "external_data_report.json"
    monkeypatch.setenv("POLY_GAMMA_BASE_URL", "https://gamma.example")
    monkeypatch.setenv("POLY_DATA_BASE_URL", "https://data.example")
    monkeypatch.setenv("POLY_CLOB_BASE_URL", "https://clob.example")
    monkeypatch.setenv("BLOCKSCOUT_API_BASE_URL", "https://api.blockscout.com")
    monkeypatch.setenv("BLOCKSCOUT_API_KEY", "test-key")
    monkeypatch.setenv("BLOCKSCOUT_DEFAULT_CHAIN_ID", "10")

    try:
        report = write_external_data_runtime_report(
            runtime_state=_runtime_state(),
            config_path=config_path,
            transport=_full_success_transport,
            output_path=output_path,
            fetched_at="2026-04-23T00:00:00+00:00",
        )

        payload = json.loads(output_path.read_text(encoding="utf-8"))
        assert report["success_source_count"] == 4
        assert report["failure_source_count"] == 0
        assert report["external_observation_active"] is True
        assert report["operating_mode"] == "hybrid"
        assert payload["read_only_contract"]["suggestion_only"] is True
        assert payload["read_only_contract"]["paper_safe"] is True
        assert payload["read_only_contract"]["live_execution_enabled"] is False
        assert payload["read_only_contract"]["order_placement_supported"] is False
        assert payload["read_only_contract"]["wallet_signing_supported"] is False

        assert (scratch_path / "polymarket_gamma_report.json").exists()
        assert (scratch_path / "signal_vocoder_etil_inputs.json").exists()
        assert (scratch_path / "polymarket_data_report.json").exists()
        assert (scratch_path / "polymarket_clob_report.json").exists()
        assert (scratch_path / "blockscout_report.json").exists()
    finally:
        set_source_mode("SYNTHETIC_RUNTIME_FALLBACK")
