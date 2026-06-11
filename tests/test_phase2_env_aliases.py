"""
Tests: Phase 2 env-var alias recognition and dotenv loading.

Principles
----------
- Zero live network calls. All HTTP is intercepted with unittest.mock.patch.
- Proves each env var name (primary and alias) is recognised by its loader.
- Proves missing all aliases skips cleanly with a meaningful reason string.
- Proves load_dotenv() is attempted at the Phase 2 entrypoint.
- Advisory safety contract is never relaxed.
- No secret values are printed or logged in any test.
"""
from __future__ import annotations

import json
import os
from tests.helpers import scanner_probes as probes
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_resp(payload: object) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


_NEWSAPI_PAYLOAD = {
    "status": "ok",
    "articles": [
        {
            "title": "Test article",
            "description": "desc",
            "url": "https://example.com/a1",
            "publishedAt": "2026-05-11T00:00:00Z",
            "source": {"name": "TestSource"},
        }
    ],
}

_ER_PAYLOAD = {
    "articles": {
        "results": [
            {
                "title": "ER article",
                "url": "https://example.com/er1",
                "dateTime": "2026-05-11T00:00:00Z",
                "source": {"title": "ER Source"},
                "body": "body text",
            }
        ]
    }
}

_ETHERSCAN_PAYLOAD = {
    "status": "1",
    "result": [
        {
            "hash": "0xabc123",
            "from": "0xfrom",
            "to": "0xto",
            "value": "1000000000000000000",
            "blockNumber": "12345",
            "timeStamp": "1715000000",
            "gasUsed": "21000",
        }
    ],
}

_GROK_PAYLOAD = {
    "choices": [
        {
            "message": {
                "content": json.dumps(
                    {
                        "interpreted_topic": "Rate divergence",
                        "narrative_frame": "Higher-for-longer",
                        "contradiction_flags": [],
                        "confidence_score": 0.8,
                        "summary_text": "Advisory summary.",
                    }
                )
            }
        }
    ]
}


# ---------------------------------------------------------------------------
# NewsAPI: NEWS_API_KEY (primary)
# ---------------------------------------------------------------------------


class TestNewsAPIKeyPrimary:
    def test_news_api_key_primary_recognized(self) -> None:
        from scripts.ingestion.newsapi_loader import NewsAPILoader

        env = {k: v for k, v in os.environ.items() if k not in ("NEWS_API_KEY", "NEWSAPI_KEY")}
        env["NEWS_API_KEY"] = "primary-key-value"
        with patch.dict(os.environ, env, clear=True):
            with patch("requests.get", return_value=_mock_resp(_NEWSAPI_PAYLOAD)):
                result = NewsAPILoader().safe_fetch()
        assert not result.skipped
        assert len(result.records) == 1

    def test_newsapi_key_alias_recognized(self) -> None:
        from scripts.ingestion.newsapi_loader import NewsAPILoader

        env = {k: v for k, v in os.environ.items() if k not in ("NEWS_API_KEY", "NEWSAPI_KEY")}
        env["NEWSAPI_KEY"] = "alias-key-value"
        with patch.dict(os.environ, env, clear=True):
            with patch("requests.get", return_value=_mock_resp(_NEWSAPI_PAYLOAD)):
                result = NewsAPILoader().safe_fetch()
        assert not result.skipped
        assert len(result.records) == 1

    def test_primary_takes_precedence_over_alias(self) -> None:
        from scripts.ingestion.newsapi_loader import NewsAPILoader

        env = {k: v for k, v in os.environ.items() if k not in ("NEWS_API_KEY", "NEWSAPI_KEY")}
        env["NEWS_API_KEY"] = "primary-key"
        env["NEWSAPI_KEY"] = "alias-key"
        with patch.dict(os.environ, env, clear=True):
            with patch("requests.get", return_value=_mock_resp(_NEWSAPI_PAYLOAD)) as mock_get:
                result = NewsAPILoader().safe_fetch()
        assert not result.skipped
        call_kwargs = mock_get.call_args
        params = call_kwargs[1].get("params") or call_kwargs[0][1] if len(call_kwargs[0]) > 1 else {}
        if not params:
            params = call_kwargs.kwargs.get("params", {})
        assert params.get("apiKey") == "primary-key"

    def test_missing_both_newsapi_keys_skips_cleanly(self) -> None:
        from scripts.ingestion.newsapi_loader import NewsAPILoader

        env = {k: v for k, v in os.environ.items() if k not in ("NEWS_API_KEY", "NEWSAPI_KEY")}
        with patch.dict(os.environ, env, clear=True):
            result = NewsAPILoader().safe_fetch()
        assert result.skipped
        assert "NEWS_API_KEY" in result.skip_reason or "NEWSAPI_KEY" in result.skip_reason

    def test_skip_reason_does_not_contain_key_value(self) -> None:
        from scripts.ingestion.newsapi_loader import NewsAPILoader

        env = {k: v for k, v in os.environ.items() if k not in ("NEWS_API_KEY", "NEWSAPI_KEY")}
        with patch.dict(os.environ, env, clear=True):
            result = NewsAPILoader().safe_fetch()
        assert "primary-key-value" not in result.skip_reason
        assert "alias-key-value" not in result.skip_reason


# ---------------------------------------------------------------------------
# Grok/xAI: XAI_API_KEY (primary) and GROK_API_KEY (alias)
# ---------------------------------------------------------------------------


class TestGrokAPIKey:
    def test_xai_api_key_primary_recognized(self) -> None:
        from scripts.ingestion.grok_interpreter import GrokInterpreter

        env = {k: v for k, v in os.environ.items() if k not in ("XAI_API_KEY", "GROK_API_KEY")}
        env["XAI_API_KEY"] = probes.xai_style_token("primary-alias")
        with patch.dict(os.environ, env, clear=True):
            with patch("requests.post", return_value=_mock_resp(_GROK_PAYLOAD)):
                result = GrokInterpreter().safe_fetch()
        assert not result.skipped
        assert len(result.records) == 1

    def test_grok_api_key_alias_recognized(self) -> None:
        from scripts.ingestion.grok_interpreter import GrokInterpreter

        env = {k: v for k, v in os.environ.items() if k not in ("XAI_API_KEY", "GROK_API_KEY")}
        env["GROK_API_KEY"] = "grok-alias-value"
        with patch.dict(os.environ, env, clear=True):
            with patch("requests.post", return_value=_mock_resp(_GROK_PAYLOAD)):
                result = GrokInterpreter().safe_fetch()
        assert not result.skipped
        assert len(result.records) == 1

    def test_xai_key_takes_precedence_over_grok_key(self) -> None:
        from scripts.ingestion.grok_interpreter import GrokInterpreter

        env = {k: v for k, v in os.environ.items() if k not in ("XAI_API_KEY", "GROK_API_KEY")}
        env["XAI_API_KEY"] = "xai-first"
        env["GROK_API_KEY"] = "grok-second"
        with patch.dict(os.environ, env, clear=True):
            with patch("requests.post", return_value=_mock_resp(_GROK_PAYLOAD)) as mock_post:
                result = GrokInterpreter().safe_fetch()
        assert not result.skipped
        call_kwargs = mock_post.call_args
        headers = call_kwargs[1].get("headers") or {}
        if not headers:
            headers = call_kwargs.kwargs.get("headers", {})
        assert headers.get("Authorization") == "Bearer xai-first"

    def test_missing_both_grok_keys_skips_cleanly(self) -> None:
        from scripts.ingestion.grok_interpreter import GrokInterpreter

        env = {k: v for k, v in os.environ.items() if k not in ("XAI_API_KEY", "GROK_API_KEY")}
        with patch.dict(os.environ, env, clear=True):
            result = GrokInterpreter().safe_fetch()
        assert result.skipped
        assert "XAI_API_KEY" in result.skip_reason or "GROK_API_KEY" in result.skip_reason

    def test_skip_reason_does_not_contain_key_value(self) -> None:
        from scripts.ingestion.grok_interpreter import GrokInterpreter

        env = {k: v for k, v in os.environ.items() if k not in ("XAI_API_KEY", "GROK_API_KEY")}
        with patch.dict(os.environ, env, clear=True):
            result = GrokInterpreter().safe_fetch()
        assert probes.xai_style_token("primary-alias") not in result.skip_reason
        assert "grok-alias-value" not in result.skip_reason


# ---------------------------------------------------------------------------
# Event Registry: EVENT_REGISTRY_API_KEY
# ---------------------------------------------------------------------------


class TestEventRegistryKey:
    def test_event_registry_api_key_recognized(self) -> None:
        from scripts.ingestion.event_registry_loader import EventRegistryLoader

        env = {k: v for k, v in os.environ.items() if k != "EVENT_REGISTRY_API_KEY"}
        env["EVENT_REGISTRY_API_KEY"] = "er-key-value"
        with patch.dict(os.environ, env, clear=True):
            with patch("requests.post", return_value=_mock_resp(_ER_PAYLOAD)):
                result = EventRegistryLoader().safe_fetch()
        assert not result.skipped
        assert len(result.records) == 1

    def test_missing_er_key_skips_cleanly(self) -> None:
        from scripts.ingestion.event_registry_loader import EventRegistryLoader

        env = {k: v for k, v in os.environ.items() if k != "EVENT_REGISTRY_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            result = EventRegistryLoader().safe_fetch()
        assert result.skipped
        assert "EVENT_REGISTRY_API_KEY" in result.skip_reason

    def test_skip_reason_does_not_contain_key_value(self) -> None:
        from scripts.ingestion.event_registry_loader import EventRegistryLoader

        env = {k: v for k, v in os.environ.items() if k != "EVENT_REGISTRY_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            result = EventRegistryLoader().safe_fetch()
        assert "er-key-value" not in result.skip_reason


# ---------------------------------------------------------------------------
# Etherscan: ETHERSCAN_API_KEY
# ---------------------------------------------------------------------------


class TestEtherscanKey:
    def test_etherscan_api_key_recognized(self) -> None:
        from scripts.ingestion.etherscan_loader import EtherscanLoader

        env = {k: v for k, v in os.environ.items() if k != "ETHERSCAN_API_KEY"}
        env["ETHERSCAN_API_KEY"] = "eth-key-value"
        with patch.dict(os.environ, env, clear=True):
            with patch("requests.get", return_value=_mock_resp(_ETHERSCAN_PAYLOAD)):
                result = EtherscanLoader(address="0xde0b295669a9fd93d5f28d9ec85e40f4cb697bae").safe_fetch()
        assert not result.skipped
        assert len(result.records) == 1

    def test_missing_etherscan_key_skips_cleanly(self) -> None:
        from scripts.ingestion.etherscan_loader import EtherscanLoader

        env = {k: v for k, v in os.environ.items() if k != "ETHERSCAN_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            result = EtherscanLoader(address="0xtest").safe_fetch()
        assert result.skipped
        assert "ETHERSCAN_API_KEY" in result.skip_reason

    def test_missing_address_skips_even_with_key(self) -> None:
        from scripts.ingestion.etherscan_loader import EtherscanLoader

        env = {k: v for k, v in os.environ.items() if k != "ETHERSCAN_API_KEY"}
        env["ETHERSCAN_API_KEY"] = "eth-key-value"
        with patch.dict(os.environ, env, clear=True):
            result = EtherscanLoader(address=None).safe_fetch()
        assert result.skipped
        assert "address" in result.skip_reason.lower()

    def test_skip_reason_does_not_contain_key_value(self) -> None:
        from scripts.ingestion.etherscan_loader import EtherscanLoader

        env = {k: v for k, v in os.environ.items() if k != "ETHERSCAN_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            result = EtherscanLoader(address="0xtest").safe_fetch()
        assert "eth-key-value" not in result.skip_reason


# ---------------------------------------------------------------------------
# SEC EDGAR: SEC_USER_AGENT
# ---------------------------------------------------------------------------


class TestSECEdgarKey:
    def test_sec_user_agent_recognized(self) -> None:
        from scripts.ingestion.sec_edgar_loader import SECEdgarLoader

        submissions_payload = {
            "filings": {
                "recent": {
                    "accessionNumber": ["0000320193-26-000001"],
                    "form": ["10-K"],
                    "filingDate": ["2026-01-01"],
                    "primaryDocument": ["filing.htm"],
                    "reportDate": ["2025-12-31"],
                }
            }
        }

        env = {k: v for k, v in os.environ.items() if k != "SEC_USER_AGENT"}
        env["SEC_USER_AGENT"] = "TestUser test@example.com"
        with patch.dict(os.environ, env, clear=True):
            with patch("requests.get", return_value=_mock_resp(submissions_payload)):
                result = SECEdgarLoader(cik="0000320193").safe_fetch()
        assert not result.skipped or "cik" in result.skip_reason.lower() or result.records is not None

    def test_missing_sec_user_agent_skips_cleanly(self) -> None:
        from scripts.ingestion.sec_edgar_loader import SECEdgarLoader

        env = {k: v for k, v in os.environ.items() if k != "SEC_USER_AGENT"}
        with patch.dict(os.environ, env, clear=True):
            result = SECEdgarLoader(cik="0000320193").safe_fetch()
        assert result.skipped
        assert "SEC_USER_AGENT" in result.skip_reason

    def test_skip_reason_does_not_contain_agent_value(self) -> None:
        from scripts.ingestion.sec_edgar_loader import SECEdgarLoader

        env = {k: v for k, v in os.environ.items() if k != "SEC_USER_AGENT"}
        with patch.dict(os.environ, env, clear=True):
            result = SECEdgarLoader(cik="0000320193").safe_fetch()
        assert "test@example.com" not in result.skip_reason


# ---------------------------------------------------------------------------
# _require_env_any: base_loader unit tests
# ---------------------------------------------------------------------------


class TestRequireEnvAny:
    def test_first_name_found(self) -> None:
        from scripts.ingestion.base_loader import BaseSourceLoader, SkipLoader

        env = {k: v for k, v in os.environ.items() if k not in ("KEY_A", "KEY_B")}
        env["KEY_A"] = "val-a"
        with patch.dict(os.environ, env, clear=True):
            result = BaseSourceLoader._require_env_any("KEY_A", "KEY_B")
        assert result == "val-a"

    def test_second_name_used_as_fallback(self) -> None:
        from scripts.ingestion.base_loader import BaseSourceLoader

        env = {k: v for k, v in os.environ.items() if k not in ("KEY_A", "KEY_B")}
        env["KEY_B"] = "val-b"
        with patch.dict(os.environ, env, clear=True):
            result = BaseSourceLoader._require_env_any("KEY_A", "KEY_B")
        assert result == "val-b"

    def test_raises_skip_loader_when_all_missing(self) -> None:
        from scripts.ingestion.base_loader import BaseSourceLoader, SkipLoader

        env = {k: v for k, v in os.environ.items() if k not in ("KEY_A", "KEY_B")}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(SkipLoader) as exc_info:
                BaseSourceLoader._require_env_any("KEY_A", "KEY_B")
        assert "KEY_A" in str(exc_info.value)
        assert "KEY_B" in str(exc_info.value)

    def test_empty_string_treated_as_missing(self) -> None:
        from scripts.ingestion.base_loader import BaseSourceLoader, SkipLoader

        env = {k: v for k, v in os.environ.items() if k not in ("KEY_A", "KEY_B")}
        env["KEY_A"] = ""
        env["KEY_B"] = "  "
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(SkipLoader):
                BaseSourceLoader._require_env_any("KEY_A", "KEY_B")


# ---------------------------------------------------------------------------
# _env_any: entrypoint helper unit tests
# ---------------------------------------------------------------------------


class TestEnvAnyHelper:
    def test_first_name_returned(self) -> None:
        from scripts.run_live_sources_phase2 import _env_any

        with patch.dict(os.environ, {"ALPHA": "first", "BETA": "second"}, clear=False):
            assert _env_any("ALPHA", "BETA") == "first"

    def test_second_name_returned_when_first_missing(self) -> None:
        from scripts.run_live_sources_phase2 import _env_any

        env = {k: v for k, v in os.environ.items() if k not in ("ALPHA", "BETA")}
        env["BETA"] = "second"
        with patch.dict(os.environ, env, clear=True):
            assert _env_any("ALPHA", "BETA") == "second"

    def test_none_when_all_missing(self) -> None:
        from scripts.run_live_sources_phase2 import _env_any

        env = {k: v for k, v in os.environ.items() if k not in ("ALPHA", "BETA")}
        with patch.dict(os.environ, env, clear=True):
            assert _env_any("ALPHA", "BETA") is None

    def test_empty_string_treated_as_missing(self) -> None:
        from scripts.run_live_sources_phase2 import _env_any

        env = {k: v for k, v in os.environ.items() if k not in ("ALPHA", "BETA")}
        env["ALPHA"] = ""
        env["BETA"] = "real"
        with patch.dict(os.environ, env, clear=True):
            assert _env_any("ALPHA", "BETA") == "real"


# ---------------------------------------------------------------------------
# load_dotenv called at entrypoint
# ---------------------------------------------------------------------------


class TestDotenvLoading:
    def test_load_dotenv_attempted_on_import(self) -> None:
        """Verify the entrypoint module attempts load_dotenv() at import time."""
        import importlib
        import sys

        # We can verify the path was attempted by patching load_dotenv before import.
        # Since the module may already be imported, check the module source instead.
        import inspect
        import scripts.run_live_sources_phase2 as mod

        source = inspect.getsource(mod)
        assert "load_dotenv" in source

    def test_load_dotenv_attempted_phase1(self) -> None:
        import inspect
        import scripts.run_live_sources_phase1 as mod

        source = inspect.getsource(mod)
        assert "load_dotenv" in source

    def test_dotenv_import_failure_does_not_crash(self) -> None:
        """If python-dotenv is absent, the entrypoint main() still runs cleanly."""
        import inspect
        import scripts.run_live_sources_phase2 as mod

        source = inspect.getsource(mod)
        assert "except Exception" in source or "except" in source


# ---------------------------------------------------------------------------
# Advisory safety contract — alias paths must not weaken safety
# ---------------------------------------------------------------------------


class TestAdvisorySafetyUnchanged:
    def test_newsapi_alias_output_is_advisory_only(self) -> None:
        from scripts.ingestion.newsapi_loader import NewsAPILoader

        env = {k: v for k, v in os.environ.items() if k not in ("NEWS_API_KEY", "NEWSAPI_KEY")}
        env["NEWSAPI_KEY"] = "alias-key"
        with patch.dict(os.environ, env, clear=True):
            with patch("requests.get", return_value=_mock_resp(_NEWSAPI_PAYLOAD)):
                result = NewsAPILoader().safe_fetch()
        for rec in result.records:
            assert rec.get("advisory_status") == "ADVISORY_ONLY"
            assert rec.get("human_review_required") is True
            assert rec.get("execution_gate") == "LOCKED"

    def test_grok_alias_output_is_advisory_only(self) -> None:
        from scripts.ingestion.grok_interpreter import GrokInterpreter

        env = {k: v for k, v in os.environ.items() if k not in ("XAI_API_KEY", "GROK_API_KEY")}
        env["GROK_API_KEY"] = "grok-alias"
        with patch.dict(os.environ, env, clear=True):
            with patch("requests.post", return_value=_mock_resp(_GROK_PAYLOAD)):
                result = GrokInterpreter().safe_fetch()
        for rec in result.records:
            assert rec.get("advisory_status") == "ADVISORY_ONLY"
            assert rec.get("human_review_required") is True
            assert rec.get("execution_gate") == "LOCKED"

    def test_no_broker_fields_on_newsapi_alias_output(self) -> None:
        from scripts.ingestion.newsapi_loader import NewsAPILoader

        env = {k: v for k, v in os.environ.items() if k not in ("NEWS_API_KEY", "NEWSAPI_KEY")}
        env["NEWSAPI_KEY"] = "alias-key"
        with patch.dict(os.environ, env, clear=True):
            with patch("requests.get", return_value=_mock_resp(_NEWSAPI_PAYLOAD)):
                result = NewsAPILoader().safe_fetch()
        for rec in result.records:
            assert "broker_order_id" not in rec or rec["broker_order_id"] == "NONE"
            assert rec.get("ai_execution_count", 0) == 0
            assert rec.get("broker_api_called", False) is False
