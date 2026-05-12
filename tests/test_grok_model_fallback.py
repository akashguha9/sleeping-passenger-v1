"""
Tests for Grok/xAI interpreter — model fallback, 400 handling,
sanitized errors, no execution language, advisory contract.

All HTTP is mocked. No live network calls.
"""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch, call

import pytest

from scripts.ingestion.grok_interpreter import (
    GrokInterpreter,
    _build_model_candidates,
    _DEPRECATED_MODELS,
    _MODEL_FALLBACK_ORDER,
    _DEFAULT_MODEL,
)
from scripts.ingestion.base_loader import SkipLoader, LoaderResult

_VALID_GROK_JSON = {
    "interpreted_topic": "Fed policy trajectory",
    "narrative_frame": "Higher-for-longer",
    "contradiction_flags": ["Mixed signals from Powell", "Market pricing diverges"],
    "confidence_score": 0.75,
    "summary_text": "The Fed remains data-dependent amid sticky inflation.",
}

_VALID_API_RESPONSE = {
    "choices": [
        {
            "message": {
                "role": "assistant",
                "content": json.dumps(_VALID_GROK_JSON),
            },
            "finish_reason": "stop",
        }
    ]
}


def _mock_ok(payload: object) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


def _mock_400(body: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 400
    resp.json.return_value = body or {"error": {"message": "Model not found"}}
    resp.text = json.dumps(body or {"error": {"message": "Model not found"}})
    resp.raise_for_status.side_effect = Exception("400 Bad Request")
    return resp


class TestBuildModelCandidates:
    def test_env_model_prepended_when_valid(self) -> None:
        candidates = _build_model_candidates("grok-3-mini")
        assert candidates[0] == "grok-3-mini"

    def test_deprecated_env_model_skipped(self) -> None:
        for deprecated in _DEPRECATED_MODELS:
            candidates = _build_model_candidates(deprecated)
            assert deprecated not in candidates

    def test_fallback_order_appended(self) -> None:
        candidates = _build_model_candidates("")
        for m in _MODEL_FALLBACK_ORDER:
            assert m in candidates

    def test_no_duplicates(self) -> None:
        candidates = _build_model_candidates("grok-3-mini")
        assert len(candidates) == len(set(candidates))

    def test_empty_env_model_falls_to_fallback(self) -> None:
        candidates = _build_model_candidates("")
        assert candidates == _MODEL_FALLBACK_ORDER

    def test_grok_beta_excluded_always(self) -> None:
        candidates = _build_model_candidates("grok-beta")
        assert "grok-beta" not in candidates


class TestGrokMissingKey:
    def test_skip_when_no_api_key(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XAI_API_KEY", None)
            os.environ.pop("GROK_API_KEY", None)
            loader = GrokInterpreter()
            with pytest.raises(SkipLoader):
                loader.fetch()

    def test_safe_fetch_skipped_no_key(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XAI_API_KEY", None)
            os.environ.pop("GROK_API_KEY", None)
            result = GrokInterpreter().safe_fetch()
        assert result.skipped


class TestGrokSuccessPath:
    def test_fetch_returns_loader_result(self) -> None:
        with patch.dict(os.environ, {"XAI_API_KEY": "test-key"}):
            with patch("requests.post", return_value=_mock_ok(_VALID_API_RESPONSE)):
                result = GrokInterpreter().fetch()
        assert isinstance(result, LoaderResult)
        assert not result.skipped
        assert len(result.records) == 1

    def test_payload_includes_system_and_user_messages(self) -> None:
        with patch.dict(os.environ, {"XAI_API_KEY": "test-key"}):
            with patch("requests.post", return_value=_mock_ok(_VALID_API_RESPONSE)) as mp:
                GrokInterpreter().fetch()
        _, kwargs = mp.call_args
        payload = kwargs.get("json", {})
        messages = payload.get("messages", [])
        roles = [m["role"] for m in messages]
        assert "system" in roles
        assert "user" in roles

    def test_payload_includes_temperature(self) -> None:
        with patch.dict(os.environ, {"XAI_API_KEY": "test-key"}):
            with patch("requests.post", return_value=_mock_ok(_VALID_API_RESPONSE)) as mp:
                GrokInterpreter().fetch()
        _, kwargs = mp.call_args
        payload = kwargs.get("json", {})
        assert "temperature" in payload

    def test_payload_includes_max_tokens(self) -> None:
        with patch.dict(os.environ, {"XAI_API_KEY": "test-key"}):
            with patch("requests.post", return_value=_mock_ok(_VALID_API_RESPONSE)) as mp:
                GrokInterpreter().fetch()
        _, kwargs = mp.call_args
        payload = kwargs.get("json", {})
        assert "max_tokens" in payload

    def test_record_advisory_stamps(self) -> None:
        with patch.dict(os.environ, {"XAI_API_KEY": "test-key"}):
            with patch("requests.post", return_value=_mock_ok(_VALID_API_RESPONSE)):
                result = GrokInterpreter().fetch()
        rec = result.records[0]
        assert rec["advisory_status"] == "ADVISORY_ONLY"
        assert rec["human_review_required"] is True
        assert rec["execution_gate"] == "LOCKED"
        assert rec["ai_execution_count"] == 0

    def test_record_has_interpreted_topic(self) -> None:
        with patch.dict(os.environ, {"XAI_API_KEY": "test-key"}):
            with patch("requests.post", return_value=_mock_ok(_VALID_API_RESPONSE)):
                result = GrokInterpreter().fetch()
        assert result.records[0]["interpreted_topic"] == "Fed policy trajectory"

    def test_system_prompt_no_execution_language(self) -> None:
        from scripts.ingestion.grok_interpreter import _ADVISORY_SYSTEM_PROMPT
        prompt_lower = _ADVISORY_SYSTEM_PROMPT.lower()
        assert "buy" not in prompt_lower or "never recommend" in prompt_lower
        assert "never recommend" in prompt_lower
        assert "no execution" in prompt_lower or "advisory" in prompt_lower


class TestGrokModelFallback:
    def test_400_tries_next_model(self) -> None:
        """On 400, should iterate through fallback models until success."""
        call_count = {"n": 0}
        models_tried = []

        def mock_post(*args, **kwargs):
            call_count["n"] += 1
            payload = kwargs.get("json", {})
            model = payload.get("model", "unknown")
            models_tried.append(model)
            if call_count["n"] < 3:
                return _mock_400()
            return _mock_ok(_VALID_API_RESPONSE)

        with patch.dict(os.environ, {"XAI_API_KEY": "test-key", "XAI_MODEL": ""}):
            with patch("requests.post", side_effect=mock_post):
                result = GrokInterpreter().fetch()

        assert not result.skipped
        assert call_count["n"] >= 2
        assert len(set(models_tried)) >= 2  # different models tried

    def test_all_models_400_raises_skip(self) -> None:
        """When all candidates return 400, should raise SkipLoader."""
        with patch.dict(os.environ, {"XAI_API_KEY": "test-key", "XAI_MODEL": ""}):
            with patch("requests.post", return_value=_mock_400()):
                with pytest.raises(SkipLoader) as exc_info:
                    GrokInterpreter().fetch()
        assert "failed" in str(exc_info.value).lower()

    def test_deprecated_model_in_env_skipped(self) -> None:
        """grok-beta in XAI_MODEL env should be skipped, not tried first."""
        models_tried = []

        def mock_post(*args, **kwargs):
            payload = kwargs.get("json", {})
            models_tried.append(payload.get("model", ""))
            return _mock_ok(_VALID_API_RESPONSE)

        with patch.dict(os.environ, {"XAI_API_KEY": "test-key", "XAI_MODEL": "grok-beta"}):
            with patch("requests.post", side_effect=mock_post):
                GrokInterpreter().fetch()

        assert "grok-beta" not in models_tried

    def test_valid_env_model_tried_first(self) -> None:
        """Valid XAI_MODEL env var should be the first model tried."""
        models_tried = []

        def mock_post(*args, **kwargs):
            payload = kwargs.get("json", {})
            models_tried.append(payload.get("model", ""))
            return _mock_ok(_VALID_API_RESPONSE)

        with patch.dict(os.environ, {"XAI_API_KEY": "test-key", "XAI_MODEL": "grok-3"}):
            with patch("requests.post", side_effect=mock_post):
                GrokInterpreter().fetch()

        assert models_tried[0] == "grok-3"

    def test_safe_fetch_skipped_on_all_400(self) -> None:
        with patch.dict(os.environ, {"XAI_API_KEY": "test-key", "XAI_MODEL": ""}):
            with patch("requests.post", return_value=_mock_400()):
                result = GrokInterpreter().safe_fetch()
        assert result.skipped


class TestGrok400Sanitization:
    def test_400_skip_reason_does_not_contain_api_key(self) -> None:
        secret = "super-secret-api-key-value"
        with patch.dict(os.environ, {"XAI_API_KEY": secret, "XAI_MODEL": ""}):
            with patch("requests.post", return_value=_mock_400()):
                result = GrokInterpreter().safe_fetch()
        assert result.skipped
        assert secret not in result.skip_reason

    def test_400_safe_fetch_skip_reason_not_empty(self) -> None:
        with patch.dict(os.environ, {"XAI_API_KEY": "test-key", "XAI_MODEL": ""}):
            with patch("requests.post", return_value=_mock_400()):
                result = GrokInterpreter().safe_fetch()
        assert result.skip_reason


class TestGrokNoForbiddenCode:
    FORBIDDEN = [
        "private_key", "sign_transaction", "send_transaction",
        "broadcast", "wallet_sign", "approve_token", "place_order",
        "execute_trade", "buy_order", "sell_order",
    ]

    def test_no_forbidden_strings_in_grok_interpreter(self) -> None:
        from pathlib import Path
        src = (Path(__file__).parents[1] / "scripts" / "ingestion" / "grok_interpreter.py").read_text().lower()
        for s in self.FORBIDDEN:
            assert s not in src, f"Forbidden string {s!r} found in grok_interpreter.py"

    def test_model_name_in_record(self) -> None:
        with patch.dict(os.environ, {"XAI_API_KEY": "test-key", "XAI_MODEL": ""}):
            with patch("requests.post", return_value=_mock_ok(_VALID_API_RESPONSE)):
                result = GrokInterpreter(model="grok-3-mini").fetch()
        assert result.records[0]["model_name"] in _MODEL_FALLBACK_ORDER


class TestGrokPhase2RunnerDefault:
    def test_default_model_is_not_grok_beta(self) -> None:
        import inspect
        from scripts.live_source_runner_phase2 import run_phase2
        sig = inspect.signature(run_phase2)
        default_model = sig.parameters["grok_model"].default
        assert default_model != "grok-beta"
        assert default_model == "grok-3-mini"

    def test_cli_default_is_not_grok_beta(self) -> None:
        from scripts.run_live_sources_phase2 import _parse_args
        with patch("sys.argv", ["prog", "--source", "grok_xai", "--dry-run"]):
            args = _parse_args()
        assert args.grok_model != "grok-beta"
