"""
Phase H — Tests for the four remaining live source adapters:

  * GDELT — shorter timeouts + CLI overrides + sanitized failure reasons
  * Etherscan — sanitized NOTOK classification + API-key redaction + chainid param
  * Grok/xAI — sanitized 400/401/429/timeout reporting + model fallback
  * Asia Disclosure — placeholder honesty + no-fake-records invariant

All HTTP is mocked. No live network calls. Read-only contract enforced.
"""
from __future__ import annotations

import json
import os
from tests.helpers import scanner_probes as probes
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from scripts.ingestion.base_loader import LoaderResult, SkipLoader
from scripts.ingestion.etherscan_loader import (
    EtherscanLoader,
    _classify_notok,
    _sanitize,
)
from scripts.ingestion.gdelt_loader import GDELTLoader
from scripts.ingestion.grok_interpreter import GrokInterpreter


_TEST_ADDRESS = "0xde0B295669a9FD93d5F28D9Ec85E40f4cb697BAe"
_API_KEY = "supersecret-etherscan-key"


# ---------------------------------------------------------------------------
# Etherscan — sanitized NOTOK responses and chainid param
# ---------------------------------------------------------------------------


def _mock_resp(payload: object, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    resp.text = json.dumps(payload) if isinstance(payload, (dict, list)) else str(payload)
    return resp


class TestEtherscanClassifyNotok:
    def test_no_transactions_is_empty(self) -> None:
        assert _classify_notok("No transactions found", "") == "EMPTY"
        assert _classify_notok("OK", "No transactions found") == "EMPTY"

    def test_invalid_api_key_is_auth(self) -> None:
        assert _classify_notok("NOTOK", "Invalid API Key") == "AUTH"
        assert _classify_notok("NOTOK", "Missing/Invalid API Key") == "AUTH"

    def test_rate_limit_classified(self) -> None:
        assert _classify_notok("NOTOK", "Max calls per sec rate limit reached") == "RATE_LIMITED"
        assert _classify_notok("NOTOK", "Too many requests") == "RATE_LIMITED"

    def test_invalid_address_classified(self) -> None:
        assert _classify_notok("NOTOK", "Invalid address format") == "INVALID_REQUEST"

    def test_deprecated_classified(self) -> None:
        assert _classify_notok("NOTOK", "endpoint not found, please use v2") == "DEPRECATED"
        assert _classify_notok("NOTOK", "missing chainid parameter") == "DEPRECATED"

    def test_generic_fallback(self) -> None:
        assert _classify_notok("NOTOK", "something we don't know") == "GENERIC"


class TestEtherscanSanitizer:
    def test_strips_api_key(self) -> None:
        out = _sanitize(f"Etherscan failed with apikey={_API_KEY}", _API_KEY)
        assert _API_KEY not in out
        assert "<redacted>" in out

    def test_empty_input(self) -> None:
        assert _sanitize("", _API_KEY) == ""
        assert _sanitize(None, _API_KEY) == ""  # type: ignore[arg-type]


class TestEtherscanNotokSurface:
    @pytest.fixture(autouse=True)
    def _set_key(self):
        os.environ["ETHERSCAN_API_KEY"] = _API_KEY
        yield
        os.environ.pop("ETHERSCAN_API_KEY", None)

    def test_invalid_key_response_classified_as_auth(self) -> None:
        payload = {"status": "0", "message": "NOTOK", "result": "Invalid API Key"}
        with patch("requests.get", return_value=_mock_resp(payload)):
            result = EtherscanLoader(address=_TEST_ADDRESS).safe_fetch()
        assert result.skipped
        assert "[ETHERSCAN_AUTH]" in result.skip_reason
        assert "Invalid API Key" in result.skip_reason

    def test_rate_limit_response_classified(self) -> None:
        payload = {
            "status": "0",
            "message": "NOTOK",
            "result": "Max calls per sec rate limit reached (5/sec)",
        }
        with patch("requests.get", return_value=_mock_resp(payload)):
            result = EtherscanLoader(address=_TEST_ADDRESS).safe_fetch()
        assert result.skipped
        assert "[RATE_LIMITED]" in result.skip_reason

    def test_deprecated_response_mentions_v2(self) -> None:
        payload = {
            "status": "0",
            "message": "NOTOK",
            "result": "endpoint not found, please use v2",
        }
        with patch("requests.get", return_value=_mock_resp(payload)):
            result = EtherscanLoader(address=_TEST_ADDRESS).safe_fetch()
        assert result.skipped
        assert "[ETHERSCAN_DEPRECATED]" in result.skip_reason
        assert "v2" in result.skip_reason

    def test_api_key_never_appears_in_skip_reason(self) -> None:
        payload = {
            "status": "0",
            "message": "NOTOK",
            "result": f"Invalid API Key {_API_KEY}",
        }
        with patch("requests.get", return_value=_mock_resp(payload)):
            result = EtherscanLoader(address=_TEST_ADDRESS).safe_fetch()
        assert _API_KEY not in result.skip_reason
        assert "<redacted>" in result.skip_reason

    def test_no_transactions_returns_empty_ok(self) -> None:
        payload = {"status": "0", "message": "No transactions found", "result": []}
        with patch("requests.get", return_value=_mock_resp(payload)):
            result = EtherscanLoader(address=_TEST_ADDRESS).fetch()
        assert not result.skipped
        assert result.records == []

    def test_chainid_param_sent(self) -> None:
        payload = {"status": "1", "message": "OK", "result": []}
        with patch("requests.get", return_value=_mock_resp(payload)) as mock_get:
            EtherscanLoader(address=_TEST_ADDRESS).fetch()
        _args, kwargs = mock_get.call_args
        params = kwargs.get("params", {})
        assert params.get("chainid") == 1

    def test_generic_notok_still_surfaces_result(self) -> None:
        payload = {
            "status": "0",
            "message": "NOTOK",
            "result": "Some new unclassified problem",
        }
        with patch("requests.get", return_value=_mock_resp(payload)):
            result = EtherscanLoader(address=_TEST_ADDRESS).safe_fetch()
        assert result.skipped
        assert "Some new unclassified problem" in result.skip_reason


# ---------------------------------------------------------------------------
# Grok/xAI — sanitized error surfacing
# ---------------------------------------------------------------------------


def _grok_resp(status: int, body: dict | str) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    if isinstance(body, dict):
        resp.json.return_value = body
        resp.text = json.dumps(body)
    else:
        resp.json.side_effect = ValueError("no json")
        resp.text = body
    if status >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status}")
    else:
        resp.raise_for_status.return_value = None
    return resp


class TestGrokSanitizedErrors:
    # Probe assembled at runtime — never literal scanner bait in source.
    _SECRET = probes.xai_style_token("do-not-leak")

    def test_400_skip_reason_contains_status_and_body(self) -> None:
        body = {"error": {"message": "Model not available"}}
        with patch.dict(os.environ, {"XAI_API_KEY": self._SECRET, "XAI_MODEL": ""}):
            with patch("requests.post", return_value=_grok_resp(400, body)):
                result = GrokInterpreter().safe_fetch()
        assert result.skipped
        assert "status=400" in result.skip_reason
        assert "Model not available" in result.skip_reason

    def test_401_is_auth_error(self) -> None:
        body = {"error": {"message": "Unauthorized"}}
        with patch.dict(os.environ, {"XAI_API_KEY": self._SECRET, "XAI_MODEL": ""}):
            with patch("requests.post", return_value=_grok_resp(401, body)):
                result = GrokInterpreter().safe_fetch()
        assert result.skipped
        assert "[XAI_AUTH]" in result.skip_reason

    def test_429_is_rate_limited(self) -> None:
        body = {"error": {"message": "rate limit reached"}}
        with patch.dict(os.environ, {"XAI_API_KEY": self._SECRET, "XAI_MODEL": ""}):
            with patch("requests.post", return_value=_grok_resp(429, body)):
                result = GrokInterpreter().safe_fetch()
        assert result.skipped
        assert "[RATE_LIMITED]" in result.skip_reason

    def test_404_falls_back_to_next_model(self) -> None:
        """404 on one model should trigger fallback through the candidate list."""
        attempts: list[str] = []

        def post_side_effect(url, json=None, headers=None, timeout=None, **kw):
            attempts.append(json.get("model"))
            if len(attempts) < 3:
                return _grok_resp(404, {"error": {"message": "model not found"}})
            return _grok_resp(200, {
                "choices": [{"message": {"content": json_dumps({
                    "interpreted_topic": "x",
                    "narrative_frame": "y",
                    "contradiction_flags": [],
                    "confidence_score": 0.5,
                    "summary_text": "ok",
                })}}]
            })

        with patch.dict(os.environ, {"XAI_API_KEY": self._SECRET, "XAI_MODEL": ""}):
            with patch("requests.post", side_effect=post_side_effect):
                result = GrokInterpreter().fetch()
        assert not result.skipped
        assert len(attempts) >= 2

    def test_api_key_never_appears_in_skip_reason(self) -> None:
        body = {"error": {"message": f"used apikey={self._SECRET}"}}
        with patch.dict(os.environ, {"XAI_API_KEY": self._SECRET, "XAI_MODEL": ""}):
            with patch("requests.post", return_value=_grok_resp(400, body)):
                result = GrokInterpreter().safe_fetch()
        assert self._SECRET not in result.skip_reason
        assert "<redacted>" in result.skip_reason

    def test_timeout_reports_model(self) -> None:
        import requests as req_mod

        with patch.dict(os.environ, {"XAI_API_KEY": self._SECRET, "XAI_MODEL": ""}):
            with patch("requests.post", side_effect=req_mod.exceptions.Timeout("slow")):
                result = GrokInterpreter().safe_fetch()
        assert result.skipped
        assert "[TIMEOUT]" in result.skip_reason


def json_dumps(d: dict) -> str:
    return json.dumps(d)


# ---------------------------------------------------------------------------
# GDELT — bounded total budget and CLI param plumbing
# ---------------------------------------------------------------------------


class TestGDELTLoaderBudget:
    def test_default_total_budget_under_12s(self) -> None:
        loader = GDELTLoader()
        budget = loader._timeout + loader._fallback_timeout
        assert budget <= 12, f"GDELT total budget {budget}s is too generous"

    def test_query_override(self) -> None:
        loader = GDELTLoader(query="bitcoin")
        assert loader._query == "bitcoin"

    def test_max_records_override(self) -> None:
        loader = GDELTLoader(max_records=5)
        assert loader._max == 5


class TestGDELTPhase1RunnerWiring:
    def test_run_phase1_accepts_gdelt_query_param(self) -> None:
        import inspect
        from scripts.live_source_runner import run_phase1

        sig = inspect.signature(run_phase1)
        assert "gdelt_query" in sig.parameters
        assert "gdelt_timeout" in sig.parameters

    def test_cli_exposes_gdelt_query_flag(self) -> None:
        import sys
        from scripts.run_live_sources_phase1 import _parse_args

        with patch.object(sys, "argv", ["prog", "--dry-run", "--gdelt-query", "btc"]):
            args = _parse_args()
        assert args.gdelt_query == "btc"

    def test_cli_exposes_gdelt_timeout_flag(self) -> None:
        import sys
        from scripts.run_live_sources_phase1 import _parse_args

        with patch.object(sys, "argv", ["prog", "--dry-run", "--gdelt-timeout", "4"]):
            args = _parse_args()
        assert args.gdelt_timeout == 4

    def test_cli_exposes_gdelt_max_records_alias(self) -> None:
        import sys
        from scripts.run_live_sources_phase1 import _parse_args

        with patch.object(
            sys, "argv", ["prog", "--dry-run", "--gdelt-max-records", "12"]
        ):
            args = _parse_args()
        assert args.gdelt_max_records_alias == 12


# ---------------------------------------------------------------------------
# Asia Disclosure — no fake records on placeholder mode
# ---------------------------------------------------------------------------


class TestAsiaDisclosurePlaceholderHonesty:
    """Hermetic tests for Asia Disclosure honesty.

    Asia Disclosure was historically a pure placeholder source.  It now
    wires two real official-API sub-sources (EDINET / OpenDART) plus
    legacy placeholders.  These tests assert the new contract without
    making any network call:
      * without keys, the loader skips with a structured reason that
        names the missing env vars
      * legacy provider names remain in the placeholder summary
      * no records are persisted in the missing-key state
      * runner classifies the result as ``skipped`` (not ``ok``)
    """

    _SUB_KEYS = (
        "EDINET_API_KEY",
        "JAPAN_EDINET_API_KEY",
        "OPENDART_API_KEY",
        "KOREA_DART_API_KEY",
    )

    def _hermetic(self):
        import os as _os

        stripped = {
            k: v for k, v in _os.environ.items() if k not in self._SUB_KEYS
        }
        return patch.dict("os.environ", stripped, clear=True)

    def test_skip_reason_says_optional_config_missing(self) -> None:
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader

        with self._hermetic():
            loader = AsiaDisclosureLoader()
            result = loader.safe_fetch()
        assert result.skipped
        assert "[OPTIONAL_CONFIG_MISSING]" in result.skip_reason

    def test_active_sub_sources_named_in_summary(self) -> None:
        """The structured sub_source_status payload names the active
        sub-sources (EDINET / OpenDART) that were attempted in this run."""
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader

        with self._hermetic():
            loader = AsiaDisclosureLoader()
            result = loader.safe_fetch()
        text = result.skip_reason.lower()
        assert "edinet" in text
        assert "opendart" in text

    def test_legacy_providers_remain_in_provider_configs(self) -> None:
        """Honest-history check: the legacy SSE/SZSE/HKEX/TDnet/SGX/dart
        entries remain in ``_PROVIDER_CONFIGS`` (as ``active=False``
        placeholders), so the jurisdiction-filter path still answers
        truthfully for them."""
        from scripts.ingestion.asia_disclosure_loader import _PROVIDER_CONFIGS

        for provider in ("sse", "szse", "hkex", "tdnet", "sgx", "dart"):
            assert provider in _PROVIDER_CONFIGS
            assert _PROVIDER_CONFIGS[provider]["active"] is False

    def test_no_keys_run_has_zero_records(self) -> None:
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader

        with self._hermetic():
            loader = AsiaDisclosureLoader()
            result = loader.safe_fetch()
        assert len(result.records) == 0

    def test_no_persist_when_keys_missing(self) -> None:
        """In write mode without EDINET/OpenDART keys, _persist_events
        must not be called for asia_disclosure."""
        from scripts.live_source_runner_phase2 import run_phase2

        with self._hermetic():
            with patch(
                "scripts.live_source_runner_phase2._persist_events"
            ) as persist_mock, patch(
                "scripts.live_source_runner_phase2._log_run"
            ):
                run_phase2(dry_run=False, sources=["asia_disclosure"])
        persist_mock.assert_not_called()

    def test_skipped_status_classified_when_no_keys(self) -> None:
        from scripts.live_source_runner_phase2 import run_phase2

        with self._hermetic():
            report = run_phase2(dry_run=True, sources=["asia_disclosure"])
        asia = next(s for s in report.sources if s.source_name == "asia_disclosure")
        assert asia.status in {"skipped", "placeholder"}
        assert asia.fetched_count == 0
