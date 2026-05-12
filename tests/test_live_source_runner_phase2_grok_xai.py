"""
Tests for Phase 2 live source runner — Grok/xAI interpretation.

Principles
----------
- Zero live network calls. All HTTP is intercepted with unittest.mock.patch.
- Missing XAI_API_KEY skips cleanly with a meaningful reason string.
- Grok output is hypothesis/interpretation only, never truth.
- Advisory contract enforced on all outputs: ADVISORY_ONLY, LOCKED, AI=0, BROKER=false.
- No broker API calls. No trade/execution fields in any report.
- No private-key, wallet, signing, transaction-send, or broadcast logic.
"""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _mock_response(payload: object) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


_GROK_JSON_CONTENT = {
    "interpreted_topic": "Global interest rate trajectory",
    "narrative_frame": "Central bank divergence",
    "contradiction_flags": [
        "Fed signals pause but inflation remains sticky",
        "ECB more hawkish than forward guidance implied",
    ],
    "confidence_score": 0.72,
    "summary_text": (
        "Markets are pricing in a prolonged higher-for-longer rate environment. "
        "Central bank divergence is the dominant theme with notable contradictions "
        "between forward guidance and actual policy trajectory."
    ),
}

_GROK_API_RESPONSE = {
    "id": "chatcmpl-test123",
    "object": "chat.completion",
    "created": 1234567890,
    "model": "grok-beta",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": json.dumps(_GROK_JSON_CONTENT),
            },
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 50, "completion_tokens": 120},
}


@pytest.fixture()
def repo_root() -> Path:
    return REPO_ROOT


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


class TestNormalizationGrokXai:
    def test_normalize_grok_fields(self) -> None:
        from scripts.live_source_runner_phase2 import _normalize_grok_record

        rec = {
            "source": "grok_xai",
            "model_name": "grok-beta",
            "source_prompt": "What macro themes dominate?",
            "interpreted_topic": "Rate divergence",
            "narrative_frame": "Higher-for-longer",
            "contradiction_flags": ["Sticky inflation vs dovish signals"],
            "confidence_score": 0.80,
            "summary_text": "Central banks remain divided.",
            "grok_response": "raw response text",
            "created_at": "2026-05-10T12:00:00+00:00",
        }
        out = _normalize_grok_record(rec)
        assert out["source_name"] == "grok_xai"
        assert out["signal_type"] == "ai_interpretation"
        assert out["interpreted_topic"] == "Rate divergence"
        assert out["narrative_frame"] == "Higher-for-longer"
        assert out["contradiction_flags"] == ["Sticky inflation vs dovish signals"]
        assert out["confidence_score"] == 0.80
        assert out["summary_text"] == "Central banks remain divided."
        assert out["model_name"] == "grok-beta"
        assert out["source_prompt"] == "What macro themes dominate?"
        assert out["grok_response"] == "raw response text"
        assert out["created_at"] == "2026-05-10T12:00:00+00:00"

    def test_normalize_grok_advisory_fields(self) -> None:
        from scripts.live_source_runner_phase2 import _normalize_grok_record

        rec = {"source_prompt": "test", "created_at": "2026-05-10T00:00:00+00:00"}
        out = _normalize_grok_record(rec)
        assert out["advisory_status"] == "ADVISORY_ONLY"
        assert out["human_review_required"] is True
        assert out["execution_gate"] == "LOCKED"
        assert out["ai_execution_count"] == 0
        assert out["broker_api_called"] is False

    def test_normalize_grok_event_id_format(self) -> None:
        from scripts.live_source_runner_phase2 import _normalize_grok_record

        rec = {
            "source_prompt": "What macro themes dominate?",
            "created_at": "2026-05-10T12:00:00+00:00",
        }
        out = _normalize_grok_record(rec)
        assert out["event_id"].startswith("grok_xai_")
        assert len(out["event_id"]) == len("grok_xai_") + 16

    def test_normalize_grok_event_id_deterministic(self) -> None:
        from scripts.live_source_runner_phase2 import _normalize_grok_record

        rec = {
            "source_prompt": "test prompt",
            "created_at": "2026-05-10T12:00:00+00:00",
        }
        assert _normalize_grok_record(rec)["event_id"] == _normalize_grok_record(rec)["event_id"]

    def test_normalize_grok_empty_topic_uses_default_title(self) -> None:
        from scripts.live_source_runner_phase2 import _normalize_grok_record

        rec = {"source_prompt": "q", "created_at": "ts", "interpreted_topic": ""}
        out = _normalize_grok_record(rec)
        assert out["title"] == "Grok Market Interpretation"

    def test_normalize_grok_topic_used_as_title(self) -> None:
        from scripts.live_source_runner_phase2 import _normalize_grok_record

        rec = {
            "source_prompt": "q",
            "created_at": "ts",
            "interpreted_topic": "Rate divergence",
        }
        out = _normalize_grok_record(rec)
        assert out["title"] == "Rate divergence"

    def test_normalize_grok_no_order_fields(self) -> None:
        from scripts.live_source_runner_phase2 import _normalize_grok_record

        rec = {"source_prompt": "q", "created_at": "ts"}
        out = _normalize_grok_record(rec)
        forbidden = {"order_id", "trade_id", "execute", "broker_order"}
        assert not any(k in out for k in forbidden)


# ---------------------------------------------------------------------------
# GrokInterpreter initialisation
# ---------------------------------------------------------------------------


class TestGrokInterpreterInit:
    def test_default_prompt_set(self) -> None:
        from scripts.ingestion.grok_interpreter import GrokInterpreter

        gi = GrokInterpreter()
        assert gi._prompt  # non-empty default

    def test_custom_prompt(self) -> None:
        from scripts.ingestion.grok_interpreter import GrokInterpreter

        gi = GrokInterpreter(prompt="Custom prompt here.")
        assert gi._prompt == "Custom prompt here."

    def test_custom_model(self) -> None:
        from scripts.ingestion.grok_interpreter import GrokInterpreter

        gi = GrokInterpreter(model="grok-2")
        assert gi._model == "grok-2"

    def test_custom_max_items(self) -> None:
        from scripts.ingestion.grok_interpreter import GrokInterpreter

        gi = GrokInterpreter(max_items=3)
        assert gi._max_items == 3

    def test_max_items_minimum_one(self) -> None:
        from scripts.ingestion.grok_interpreter import GrokInterpreter

        gi = GrokInterpreter(max_items=0)
        assert gi._max_items == 1

    def test_max_items_negative_clamped(self) -> None:
        from scripts.ingestion.grok_interpreter import GrokInterpreter

        gi = GrokInterpreter(max_items=-5)
        assert gi._max_items == 1

    def test_source_name(self) -> None:
        from scripts.ingestion.grok_interpreter import GrokInterpreter

        assert GrokInterpreter.source_name == "grok_xai"

    def test_requires_key(self) -> None:
        from scripts.ingestion.grok_interpreter import GrokInterpreter

        assert GrokInterpreter.requires_key is True


# ---------------------------------------------------------------------------
# Missing API key
# ---------------------------------------------------------------------------


class TestGrokInterpreterMissingKey:
    def test_skip_when_no_key(self) -> None:
        from scripts.ingestion.grok_interpreter import GrokInterpreter
        from scripts.ingestion.base_loader import SkipLoader

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XAI_API_KEY", None)
            os.environ.pop("GROK_API_KEY", None)
            gi = GrokInterpreter()
            with pytest.raises(SkipLoader):
                gi.fetch()

    def test_skip_reason_mentions_key(self) -> None:
        from scripts.ingestion.grok_interpreter import GrokInterpreter

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XAI_API_KEY", None)
            os.environ.pop("GROK_API_KEY", None)
            gi = GrokInterpreter()
            result = gi.safe_fetch()
            assert result.skipped
            assert "XAI_API_KEY" in result.skip_reason

    def test_safe_fetch_returns_skipped_loader_result(self) -> None:
        from scripts.ingestion.grok_interpreter import GrokInterpreter
        from scripts.ingestion.base_loader import LoaderResult

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XAI_API_KEY", None)
            os.environ.pop("GROK_API_KEY", None)
            gi = GrokInterpreter()
            result = gi.safe_fetch()
            assert isinstance(result, LoaderResult)
            assert result.skipped is True
            assert result.records == []

    def test_safe_fetch_source_name_preserved(self) -> None:
        from scripts.ingestion.grok_interpreter import GrokInterpreter

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XAI_API_KEY", None)
            os.environ.pop("GROK_API_KEY", None)
            gi = GrokInterpreter()
            result = gi.safe_fetch()
            assert result.source_name == "grok_xai"


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------


class TestGrokInterpreterJsonParsing:
    def _make_interpreter(self, prompt: str = "test") -> object:
        from scripts.ingestion.grok_interpreter import GrokInterpreter

        return GrokInterpreter(prompt=prompt)

    def test_parse_valid_json(self) -> None:
        gi = self._make_interpreter()
        result = gi._parse_grok_response(json.dumps(_GROK_JSON_CONTENT), "2026-05-10T00:00:00+00:00")
        assert result["interpreted_topic"] == "Global interest rate trajectory"
        assert result["narrative_frame"] == "Central bank divergence"
        assert isinstance(result["contradiction_flags"], list)
        assert len(result["contradiction_flags"]) == 2
        assert result["confidence_score"] == pytest.approx(0.72, abs=1e-6)
        assert "Central banks" in result["summary_text"] or "Markets are" in result["summary_text"]

    def test_parse_missing_fields_uses_defaults(self) -> None:
        gi = self._make_interpreter()
        result = gi._parse_grok_response(json.dumps({}), "ts")
        assert result["interpreted_topic"] == ""
        assert result["narrative_frame"] == ""
        assert result["contradiction_flags"] == []
        assert result["confidence_score"] is None

    def test_parse_non_json_falls_back(self) -> None:
        gi = self._make_interpreter()
        raw = "This is a plain text response from Grok."
        result = gi._parse_grok_response(raw, "ts")
        assert result["summary_text"] == raw.strip()
        assert result["interpreted_topic"] == ""

    def test_parse_empty_content(self) -> None:
        gi = self._make_interpreter()
        result = gi._parse_grok_response("", "ts")
        assert result["interpreted_topic"] == ""
        assert result["summary_text"] == ""
        assert result["confidence_score"] is None

    def test_parse_confidence_clamped_high(self) -> None:
        gi = self._make_interpreter()
        data = {**_GROK_JSON_CONTENT, "confidence_score": 1.5}
        result = gi._parse_grok_response(json.dumps(data), "ts")
        assert result["confidence_score"] == pytest.approx(1.0, abs=1e-6)

    def test_parse_confidence_clamped_low(self) -> None:
        gi = self._make_interpreter()
        data = {**_GROK_JSON_CONTENT, "confidence_score": -0.5}
        result = gi._parse_grok_response(json.dumps(data), "ts")
        assert result["confidence_score"] == pytest.approx(0.0, abs=1e-6)

    def test_parse_confidence_int_converted(self) -> None:
        gi = self._make_interpreter()
        data = {**_GROK_JSON_CONTENT, "confidence_score": 1}
        result = gi._parse_grok_response(json.dumps(data), "ts")
        assert isinstance(result["confidence_score"], float)
        assert result["confidence_score"] == pytest.approx(1.0, abs=1e-6)

    def test_parse_contradiction_flags_list(self) -> None:
        gi = self._make_interpreter()
        data = {**_GROK_JSON_CONTENT, "contradiction_flags": ["flag A", "flag B"]}
        result = gi._parse_grok_response(json.dumps(data), "ts")
        assert result["contradiction_flags"] == ["flag A", "flag B"]

    def test_parse_contradiction_flags_non_list(self) -> None:
        gi = self._make_interpreter()
        data = {**_GROK_JSON_CONTENT, "contradiction_flags": "not a list"}
        result = gi._parse_grok_response(json.dumps(data), "ts")
        assert result["contradiction_flags"] == []

    def test_parse_includes_raw_response(self) -> None:
        gi = self._make_interpreter()
        raw = json.dumps(_GROK_JSON_CONTENT)
        result = gi._parse_grok_response(raw, "ts")
        assert result["grok_response"] == raw

    def test_parse_includes_model_name(self) -> None:
        gi = self._make_interpreter(prompt="test prompt")
        result = gi._parse_grok_response("{}", "ts")
        # model_name defaults to _DEFAULT_MODEL when no effective_model provided
        from scripts.ingestion.grok_interpreter import _DEFAULT_MODEL
        assert result["model_name"] == _DEFAULT_MODEL

    def test_parse_includes_source_prompt(self) -> None:
        gi = self._make_interpreter(prompt="My custom query")
        result = gi._parse_grok_response("{}", "ts")
        assert result["source_prompt"] == "My custom query"


# ---------------------------------------------------------------------------
# Mocked HTTP fetch
# ---------------------------------------------------------------------------


class TestGrokInterpreterMockedHTTP:
    def test_fetch_returns_loader_result(self) -> None:
        from scripts.ingestion.grok_interpreter import GrokInterpreter
        from scripts.ingestion.base_loader import LoaderResult

        with patch.dict(os.environ, {"XAI_API_KEY": "test-key-123"}):
            with patch("requests.post", return_value=_mock_response(_GROK_API_RESPONSE)):
                gi = GrokInterpreter()
                result = gi.fetch()
                assert isinstance(result, LoaderResult)
                assert not result.skipped
                assert len(result.records) == 1

    def test_fetch_record_has_advisory_fields(self) -> None:
        from scripts.ingestion.grok_interpreter import GrokInterpreter

        with patch.dict(os.environ, {"XAI_API_KEY": "test-key-123"}):
            with patch("requests.post", return_value=_mock_response(_GROK_API_RESPONSE)):
                gi = GrokInterpreter()
                result = gi.fetch()
                rec = result.records[0]
                assert rec["advisory_status"] == "ADVISORY_ONLY"
                assert rec["human_review_required"] is True
                assert rec["execution_gate"] == "LOCKED"

    def test_fetch_record_has_model_name(self) -> None:
        from scripts.ingestion.grok_interpreter import GrokInterpreter, _MODEL_FALLBACK_ORDER

        with patch.dict(os.environ, {"XAI_API_KEY": "test-key-123"}):
            with patch("requests.post", return_value=_mock_response(_GROK_API_RESPONSE)):
                gi = GrokInterpreter(model="grok-3-mini")
                result = gi.fetch()
                assert result.records[0]["model_name"] in _MODEL_FALLBACK_ORDER

    def test_fetch_record_has_source_prompt(self) -> None:
        from scripts.ingestion.grok_interpreter import GrokInterpreter

        with patch.dict(os.environ, {"XAI_API_KEY": "test-key-123"}):
            with patch("requests.post", return_value=_mock_response(_GROK_API_RESPONSE)):
                gi = GrokInterpreter(prompt="Custom market query")
                result = gi.fetch()
                assert result.records[0]["source_prompt"] == "Custom market query"

    def test_fetch_parses_interpretation_fields(self) -> None:
        from scripts.ingestion.grok_interpreter import GrokInterpreter

        with patch.dict(os.environ, {"XAI_API_KEY": "test-key-123"}):
            with patch("requests.post", return_value=_mock_response(_GROK_API_RESPONSE)):
                gi = GrokInterpreter()
                result = gi.fetch()
                rec = result.records[0]
                assert rec["interpreted_topic"] == "Global interest rate trajectory"
                assert rec["narrative_frame"] == "Central bank divergence"
                assert isinstance(rec["contradiction_flags"], list)

    def test_fetch_empty_choices_graceful(self) -> None:
        from scripts.ingestion.grok_interpreter import GrokInterpreter
        from scripts.ingestion.base_loader import LoaderResult

        empty_resp = {**_GROK_API_RESPONSE, "choices": []}
        with patch.dict(os.environ, {"XAI_API_KEY": "test-key-123"}):
            with patch("requests.post", return_value=_mock_response(empty_resp)):
                gi = GrokInterpreter()
                result = gi.fetch()
                assert isinstance(result, LoaderResult)
                assert not result.skipped
                assert len(result.records) == 1
                assert result.records[0]["summary_text"] == ""

    def test_fetch_source_name_in_result(self) -> None:
        from scripts.ingestion.grok_interpreter import GrokInterpreter

        with patch.dict(os.environ, {"XAI_API_KEY": "test-key-123"}):
            with patch("requests.post", return_value=_mock_response(_GROK_API_RESPONSE)):
                gi = GrokInterpreter()
                result = gi.fetch()
                assert result.source_name == "grok_xai"


# ---------------------------------------------------------------------------
# API error handling
# ---------------------------------------------------------------------------


class TestGrokInterpreterAPIError:
    def test_connection_error_raises_skip_loader(self) -> None:
        from scripts.ingestion.grok_interpreter import GrokInterpreter
        from scripts.ingestion.base_loader import SkipLoader

        import requests as req_module

        with patch.dict(os.environ, {"XAI_API_KEY": "test-key-123"}):
            with patch("requests.post", side_effect=req_module.ConnectionError("timeout")):
                gi = GrokInterpreter()
                with pytest.raises(SkipLoader) as exc_info:
                    gi.fetch()
                assert "unreachable" in str(exc_info.value).lower()

    def test_http_error_raises_skip_loader(self) -> None:
        from scripts.ingestion.grok_interpreter import GrokInterpreter
        from scripts.ingestion.base_loader import SkipLoader

        bad_resp = MagicMock()
        bad_resp.raise_for_status.side_effect = Exception("401 Unauthorized")
        bad_resp.json.return_value = {}

        with patch.dict(os.environ, {"XAI_API_KEY": "test-key-123"}):
            with patch("requests.post", return_value=bad_resp):
                gi = GrokInterpreter()
                with pytest.raises(SkipLoader):
                    gi.fetch()

    def test_api_error_safe_fetch_skipped(self) -> None:
        from scripts.ingestion.grok_interpreter import GrokInterpreter

        import requests as req_module

        with patch.dict(os.environ, {"XAI_API_KEY": "test-key-123"}):
            with patch("requests.post", side_effect=req_module.ConnectionError("refused")):
                gi = GrokInterpreter()
                result = gi.safe_fetch()
                assert result.skipped is True


# ---------------------------------------------------------------------------
# Phase 2 runner integration
# ---------------------------------------------------------------------------


class TestPhase2RunnerGrokXai:
    def test_run_phase2_grok_xai_no_key_skipped(self) -> None:
        from scripts.live_source_runner_phase2 import run_phase2

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XAI_API_KEY", None)
            os.environ.pop("GROK_API_KEY", None)
            report = run_phase2(dry_run=True, sources=["grok_xai"])
            assert len(report.sources) == 1
            assert report.sources[0].status == "skipped"
            assert report.total_fetched == 0

    def test_run_phase2_grok_xai_with_mock(self) -> None:
        from scripts.live_source_runner_phase2 import run_phase2

        with patch.dict(os.environ, {"XAI_API_KEY": "test-key-123"}):
            with patch("requests.post", return_value=_mock_response(_GROK_API_RESPONSE)):
                report = run_phase2(dry_run=True, sources=["grok_xai"])
                assert len(report.sources) == 1
                assert report.sources[0].status == "ok"
                assert report.sources[0].fetched_count == 1
                assert report.total_fetched == 1

    def test_run_phase2_grok_xai_source_name(self) -> None:
        from scripts.live_source_runner_phase2 import run_phase2

        with patch.dict(os.environ, {"XAI_API_KEY": "test-key-123"}):
            with patch("requests.post", return_value=_mock_response(_GROK_API_RESPONSE)):
                report = run_phase2(dry_run=True, sources=["grok_xai"])
                assert report.sources[0].source_name == "grok_xai"

    def test_run_phase2_grok_xai_dry_run_no_persist(self) -> None:
        from scripts.live_source_runner_phase2 import run_phase2

        with patch.dict(os.environ, {"XAI_API_KEY": "test-key-123"}):
            with patch("requests.post", return_value=_mock_response(_GROK_API_RESPONSE)):
                with patch("scripts.live_source_runner_phase2._persist_events") as mock_persist:
                    report = run_phase2(dry_run=True, sources=["grok_xai"])
                    mock_persist.assert_not_called()
                    assert report.total_persisted == 0

    def test_run_phase2_only_requested_source_runs(self) -> None:
        from scripts.live_source_runner_phase2 import run_phase2

        with patch.dict(os.environ, {"XAI_API_KEY": "test-key-123"}):
            with patch("requests.post", return_value=_mock_response(_GROK_API_RESPONSE)):
                report = run_phase2(dry_run=True, sources=["grok_xai"])
                source_names = [s.source_name for s in report.sources]
                assert source_names == ["grok_xai"]

    def test_run_phase2_grok_custom_query_passed(self) -> None:
        from scripts.live_source_runner_phase2 import run_phase2
        from scripts.ingestion.grok_interpreter import GrokInterpreter

        captured_prompt = []

        original_init = GrokInterpreter.__init__

        def patched_init(self, prompt=None, **kwargs):
            captured_prompt.append(prompt)
            original_init(self, prompt=prompt, **kwargs)

        with patch.dict(os.environ, {"XAI_API_KEY": "test-key-123"}):
            with patch("requests.post", return_value=_mock_response(_GROK_API_RESPONSE)):
                with patch.object(GrokInterpreter, "__init__", patched_init):
                    run_phase2(
                        dry_run=True,
                        sources=["grok_xai"],
                        grok_query="Custom macro query",
                    )
                    assert "Custom macro query" in captured_prompt


# ---------------------------------------------------------------------------
# Write mode persistence
# ---------------------------------------------------------------------------


class TestGrokXaiWriteMode:
    def test_write_mode_calls_persist(self) -> None:
        from scripts.live_source_runner_phase2 import run_phase2

        with patch.dict(os.environ, {"XAI_API_KEY": "test-key-123"}):
            with patch("requests.post", return_value=_mock_response(_GROK_API_RESPONSE)):
                with patch("scripts.live_source_runner_phase2._persist_events", return_value=1) as mp:
                    with patch("scripts.live_source_runner_phase2._log_run"):
                        report = run_phase2(dry_run=False, sources=["grok_xai"])
                        mp.assert_called_once()
                        assert report.total_persisted == 1

    def test_write_mode_calls_log_run(self) -> None:
        from scripts.live_source_runner_phase2 import run_phase2

        with patch.dict(os.environ, {"XAI_API_KEY": "test-key-123"}):
            with patch("requests.post", return_value=_mock_response(_GROK_API_RESPONSE)):
                with patch("scripts.live_source_runner_phase2._persist_events", return_value=1):
                    with patch("scripts.live_source_runner_phase2._log_run") as ml:
                        run_phase2(dry_run=False, sources=["grok_xai"])
                        ml.assert_called_once()

    def test_write_mode_skipped_source_no_persist(self) -> None:
        from scripts.live_source_runner_phase2 import run_phase2

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XAI_API_KEY", None)
            os.environ.pop("GROK_API_KEY", None)
            with patch("scripts.live_source_runner_phase2._persist_events") as mp:
                run_phase2(dry_run=False, sources=["grok_xai"])
                mp.assert_not_called()


# ---------------------------------------------------------------------------
# Safety invariants
# ---------------------------------------------------------------------------


class TestGrokXaiSafetyInvariants:
    def _get_report(self):
        from scripts.live_source_runner_phase2 import run_phase2

        with patch.dict(os.environ, {"XAI_API_KEY": "test-key-123"}):
            with patch("requests.post", return_value=_mock_response(_GROK_API_RESPONSE)):
                return run_phase2(dry_run=True, sources=["grok_xai"])

    def test_report_advisory_status(self) -> None:
        report = self._get_report()
        assert report.advisory_status == "ADVISORY_ONLY"

    def test_report_execution_gate_locked(self) -> None:
        report = self._get_report()
        assert report.execution_gate == "LOCKED"

    def test_report_ai_execution_count_zero(self) -> None:
        report = self._get_report()
        assert report.ai_execution_count == 0

    def test_report_human_review_required(self) -> None:
        report = self._get_report()
        assert report.human_review_required is True

    def test_report_broker_api_called_false(self) -> None:
        report = self._get_report()
        assert report.broker_api_called is False

    def test_source_result_advisory_status(self) -> None:
        report = self._get_report()
        for src in report.sources:
            assert src.advisory_status == "ADVISORY_ONLY"

    def test_source_result_broker_api_false(self) -> None:
        report = self._get_report()
        for src in report.sources:
            assert src.broker_api_called is False

    def test_normalized_event_advisory_status(self) -> None:
        from scripts.live_source_runner_phase2 import _normalize_grok_record

        rec = {"source_prompt": "q", "created_at": "ts"}
        out = _normalize_grok_record(rec)
        assert out["advisory_status"] == "ADVISORY_ONLY"

    def test_normalized_event_execution_gate(self) -> None:
        from scripts.live_source_runner_phase2 import _normalize_grok_record

        rec = {"source_prompt": "q", "created_at": "ts"}
        out = _normalize_grok_record(rec)
        assert out["execution_gate"] == "LOCKED"

    def test_normalized_event_ai_count_zero(self) -> None:
        from scripts.live_source_runner_phase2 import _normalize_grok_record

        rec = {"source_prompt": "q", "created_at": "ts"}
        out = _normalize_grok_record(rec)
        assert out["ai_execution_count"] == 0

    def test_normalized_event_human_review(self) -> None:
        from scripts.live_source_runner_phase2 import _normalize_grok_record

        rec = {"source_prompt": "q", "created_at": "ts"}
        out = _normalize_grok_record(rec)
        assert out["human_review_required"] is True


# ---------------------------------------------------------------------------
# No forbidden methods (AST check)
# ---------------------------------------------------------------------------


class TestGrokXaiNoForbiddenMethods:
    FORBIDDEN_METHODS = {
        "place_order",
        "execute_trade",
        "send_transaction",
        "sign_transaction",
        "broadcast_transaction",
        "approve_token",
        "submit_order",
        "send_order",
        "cancel_order",
    }
    FORBIDDEN_STRINGS = [
        "private_key",
        "wallet_sign",
        "sign_transaction",
        "broadcast_transaction(",
        "token_approval(",
    ]

    def _collect_attr_calls(self, source: str) -> set[str]:
        tree = ast.parse(source)
        return {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }

    def test_no_forbidden_in_grok_interpreter(self, repo_root: Path) -> None:
        src = (repo_root / "scripts" / "ingestion" / "grok_interpreter.py").read_text()
        found = self._collect_attr_calls(src) & self.FORBIDDEN_METHODS
        assert not found, f"Forbidden methods found: {found}"

    def test_no_forbidden_in_runner(self, repo_root: Path) -> None:
        src = (repo_root / "scripts" / "live_source_runner_phase2.py").read_text()
        found = self._collect_attr_calls(src) & self.FORBIDDEN_METHODS
        assert not found, f"Forbidden methods found: {found}"

    def test_no_forbidden_strings_in_grok_interpreter(self, repo_root: Path) -> None:
        src = (repo_root / "scripts" / "ingestion" / "grok_interpreter.py").read_text().lower()
        for s in self.FORBIDDEN_STRINGS:
            assert s not in src, f"Forbidden string '{s}' found in grok_interpreter.py"

    def test_no_broker_api_in_grok_interpreter(self, repo_root: Path) -> None:
        src = (repo_root / "scripts" / "ingestion" / "grok_interpreter.py").read_text()
        assert "broker_api" not in src.lower() or "broker_api_called" in src
        assert "place_order" not in src
        assert "execute_trade" not in src

    def test_no_buy_sell_endpoint_in_grok_interpreter(self, repo_root: Path) -> None:
        src = (repo_root / "scripts" / "ingestion" / "grok_interpreter.py").read_text().lower()
        assert "buy_order" not in src
        assert "sell_order" not in src
        assert "execute_order" not in src


# ---------------------------------------------------------------------------
# CLI support
# ---------------------------------------------------------------------------


class TestGrokXaiCLI:
    def test_grok_xai_in_supported_sources(self) -> None:
        from scripts.run_live_sources_phase2 import _SUPPORTED_SOURCES

        assert "grok_xai" in _SUPPORTED_SOURCES

    def test_parse_args_accepts_grok_xai(self) -> None:
        from scripts.run_live_sources_phase2 import _parse_args

        with patch("sys.argv", ["prog", "--source", "grok_xai", "--dry-run"]):
            args = _parse_args()
            assert args.source == "grok_xai"
            assert args.dry_run is True

    def test_parse_args_grok_query(self) -> None:
        from scripts.run_live_sources_phase2 import _parse_args

        with patch("sys.argv", [
            "prog", "--source", "grok_xai", "--dry-run",
            "--grok-query", "What macro risks dominate?"
        ]):
            args = _parse_args()
            assert args.grok_query == "What macro risks dominate?"

    def test_parse_args_grok_max_items(self) -> None:
        from scripts.run_live_sources_phase2 import _parse_args

        with patch("sys.argv", [
            "prog", "--source", "grok_xai", "--dry-run", "--grok-max-items", "2"
        ]):
            args = _parse_args()
            assert args.grok_max_items == 2

    def test_parse_args_grok_model(self) -> None:
        from scripts.run_live_sources_phase2 import _parse_args

        with patch("sys.argv", [
            "prog", "--source", "grok_xai", "--dry-run", "--grok-model", "grok-2"
        ]):
            args = _parse_args()
            assert args.grok_model == "grok-2"

    def test_parse_args_grok_defaults(self) -> None:
        from scripts.run_live_sources_phase2 import _parse_args

        with patch("sys.argv", ["prog", "--source", "grok_xai", "--dry-run"]):
            args = _parse_args()
            assert args.grok_query is None
            assert args.grok_max_items == 1
            assert args.grok_model == "grok-3-mini"
