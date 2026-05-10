"""
Tests for Phase 2 live source runner — Event Registry.

Principles
----------
- Zero live network calls. All HTTP is intercepted with unittest.mock.patch.
- Missing EVENT_REGISTRY_API_KEY skips cleanly with a meaningful reason string.
- Advisory contract enforced on all outputs: ADVISORY_ONLY, LOCKED, AI=0, BROKER=false.
- No broker API calls. No trade/execution fields in any report.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db(tmp_path: Path) -> Path:
    return tmp_path / "test_phase2_er.db"


@pytest.fixture()
def er_payload() -> dict:
    return {
        "articles": {
            "results": [
                {
                    "title": "Global markets rally on rate cut hopes",
                    "url": "https://example.com/er/1",
                    "dateTime": "2026-05-10T09:00:00Z",
                    "source": {"title": "Reuters"},
                    "body": "World equity markets rose on Friday as investors anticipated central bank rate cuts.",
                },
                {
                    "title": "Economy shows resilience amid trade tensions",
                    "url": "https://example.com/er/2",
                    "dateTime": "2026-05-10T08:30:00Z",
                    "source": {"title": "Bloomberg"},
                    "body": "GDP data beat consensus estimates, driven by consumer spending.",
                },
            ]
        }
    }


def _mock_response(payload: object) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


# ---------------------------------------------------------------------------
# Advisory contract — dataclasses
# ---------------------------------------------------------------------------


class TestAdvisoryContract:
    def test_phase2_report_defaults(self) -> None:
        from scripts.live_source_runner_phase2 import Phase2RunReport

        r = Phase2RunReport(dry_run=True, run_at="t")
        assert r.advisory_status == "ADVISORY_ONLY"
        assert r.execution_gate == "LOCKED"
        assert r.ai_execution_count == 0
        assert r.human_review_required is True
        assert r.broker_api_called is False

    def test_source_run_result_defaults(self) -> None:
        from scripts.live_source_runner_phase2 import SourceRunResult

        s = SourceRunResult(source_name="event_registry", status="ok", timestamp_utc="t")
        assert s.advisory_status == "ADVISORY_ONLY"
        assert s.broker_api_called is False

    def test_report_to_dict_carries_advisory_fields(self) -> None:
        from scripts.live_source_runner_phase2 import Phase2RunReport

        d = Phase2RunReport(dry_run=True, run_at="t").to_dict()
        assert d["advisory_status"] == "ADVISORY_ONLY"
        assert d["execution_gate"] == "LOCKED"
        assert d["ai_execution_count"] == 0
        assert d["human_review_required"] is True
        assert d["broker_api_called"] is False


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


class TestNormalizationEventRegistry:
    def test_normalize_event_registry_fields(self) -> None:
        from scripts.live_source_runner_phase2 import _normalize_event_registry_record

        rec = {
            "url": "https://example.com/er/1",
            "title": "Global markets rally",
            "date_time": "2026-05-10T09:00:00Z",
            "source_name": "Reuters",
            "body": "World equity markets rose on Friday.",
            "source": "event_registry",
        }
        out = _normalize_event_registry_record(rec)
        assert out["source_name"] == "event_registry"
        assert out["signal_type"] == "news_article"
        assert out["title"] == "Global markets rally"
        assert out["url"] == "https://example.com/er/1"
        assert out["publisher"] == "Reuters"
        assert out["date_time"] == "2026-05-10T09:00:00Z"
        assert out["body"] == "World equity markets rose on Friday."
        assert out["advisory_status"] == "ADVISORY_ONLY"
        assert out["human_review_required"] is True
        assert out["execution_gate"] == "LOCKED"
        assert out["ai_execution_count"] == 0
        assert out["broker_api_called"] is False

    def test_normalize_event_registry_event_id_format(self) -> None:
        from scripts.live_source_runner_phase2 import _normalize_event_registry_record

        rec = {"url": "https://example.com/er/1", "title": "Test"}
        out = _normalize_event_registry_record(rec)
        assert out["event_id"].startswith("event_registry_")
        assert len(out["event_id"]) == len("event_registry_") + 16

    def test_stable_event_id_deterministic_for_er(self) -> None:
        from scripts.live_source_runner_phase2 import _stable_event_id

        assert _stable_event_id("event_registry", "https://x.com/a") == _stable_event_id(
            "event_registry", "https://x.com/a"
        )

    def test_stable_event_id_differs_from_newsapi(self) -> None:
        from scripts.live_source_runner_phase2 import _stable_event_id

        url = "https://x.com/same-url"
        assert _stable_event_id("event_registry", url) != _stable_event_id("newsapi", url)

    def test_all_normalized_records_advisory_stamped(self, er_payload: dict) -> None:
        from scripts.live_source_runner_phase2 import _normalize_event_registry_record

        for art in er_payload["articles"]["results"]:
            rec = {
                "url": art.get("url", ""),
                "title": art.get("title", ""),
                "date_time": art.get("dateTime", ""),
                "source_name": (art.get("source") or {}).get("title", ""),
                "body": art.get("body", "")[:500],
                "source": "event_registry",
            }
            out = _normalize_event_registry_record(rec)
            assert out["advisory_status"] == "ADVISORY_ONLY"
            assert out["human_review_required"] is True
            assert out["execution_gate"] == "LOCKED"
            assert out["ai_execution_count"] == 0
            assert out["broker_api_called"] is False

    def test_normalize_missing_url_produces_empty_url(self) -> None:
        from scripts.live_source_runner_phase2 import _normalize_event_registry_record

        rec = {"title": "No URL here"}
        out = _normalize_event_registry_record(rec)
        assert out["url"] == ""
        assert out["event_id"].startswith("event_registry_")


# ---------------------------------------------------------------------------
# Event Registry — mocked HTTP (POST)
# ---------------------------------------------------------------------------


class TestEventRegistryMocked:
    def test_dry_run_fetches_correct_count(self, er_payload: dict) -> None:
        os.environ["EVENT_REGISTRY_API_KEY"] = "test-er-key-mock"
        try:
            with patch("requests.post", return_value=_mock_response(er_payload)):
                from scripts.live_source_runner_phase2 import run_phase2

                report = run_phase2(dry_run=True, sources=["event_registry"])

            er = next(s for s in report.sources if s.source_name == "event_registry")
            assert er.status == "ok"
            assert er.fetched_count == 2
            assert er.events_persisted == 0
            assert report.advisory_status == "ADVISORY_ONLY"
            assert report.ai_execution_count == 0
            assert report.broker_api_called is False
        finally:
            os.environ.pop("EVENT_REGISTRY_API_KEY", None)

    def test_dry_run_never_calls_persist(self, er_payload: dict) -> None:
        os.environ["EVENT_REGISTRY_API_KEY"] = "test-er-key-mock"
        try:
            with patch("requests.post", return_value=_mock_response(er_payload)):
                from scripts.live_source_runner_phase2 import run_phase2

                with patch(
                    "scripts.live_source_runner_phase2._persist_events"
                ) as persist_mock:
                    run_phase2(dry_run=True, sources=["event_registry"])
                    persist_mock.assert_not_called()
        finally:
            os.environ.pop("EVENT_REGISTRY_API_KEY", None)

    def test_network_error_yields_skipped_source(self) -> None:
        os.environ["EVENT_REGISTRY_API_KEY"] = "test-er-key-mock"
        try:
            with patch("requests.post", side_effect=Exception("network down")):
                from scripts.live_source_runner_phase2 import run_phase2

                report = run_phase2(dry_run=True, sources=["event_registry"])

            er = next(s for s in report.sources if s.source_name == "event_registry")
            assert er.status == "skipped"
            assert er.fetched_count == 0
        finally:
            os.environ.pop("EVENT_REGISTRY_API_KEY", None)

    def test_empty_results_list(self) -> None:
        os.environ["EVENT_REGISTRY_API_KEY"] = "test-er-key-mock"
        try:
            with patch(
                "requests.post",
                return_value=_mock_response({"articles": {"results": []}}),
            ):
                from scripts.live_source_runner_phase2 import run_phase2

                report = run_phase2(dry_run=True, sources=["event_registry"])

            er = next(s for s in report.sources if s.source_name == "event_registry")
            assert er.status == "ok"
            assert er.fetched_count == 0
        finally:
            os.environ.pop("EVENT_REGISTRY_API_KEY", None)

    def test_malformed_response_yields_zero_records(self) -> None:
        os.environ["EVENT_REGISTRY_API_KEY"] = "test-er-key-mock"
        try:
            with patch("requests.post", return_value=_mock_response({"unexpected": True})):
                from scripts.live_source_runner_phase2 import run_phase2

                report = run_phase2(dry_run=True, sources=["event_registry"])

            er = next(s for s in report.sources if s.source_name == "event_registry")
            assert er.status == "ok"
            assert er.fetched_count == 0
        finally:
            os.environ.pop("EVENT_REGISTRY_API_KEY", None)

    def test_total_fetched_accumulates(self, er_payload: dict) -> None:
        os.environ["EVENT_REGISTRY_API_KEY"] = "test-er-key-mock"
        try:
            with patch("requests.post", return_value=_mock_response(er_payload)):
                from scripts.live_source_runner_phase2 import run_phase2

                report = run_phase2(dry_run=True, sources=["event_registry"])

            assert report.total_fetched == 2
            assert report.total_persisted == 0
        finally:
            os.environ.pop("EVENT_REGISTRY_API_KEY", None)

    def test_records_have_no_duplicate_event_ids(self, er_payload: dict) -> None:
        os.environ["EVENT_REGISTRY_API_KEY"] = "test-er-key-mock"
        try:
            with patch("requests.post", return_value=_mock_response(er_payload)):
                from scripts.live_source_runner_phase2 import (
                    _normalize_event_registry_record,
                )
                from scripts.ingestion.event_registry_loader import EventRegistryLoader

                loader = EventRegistryLoader()
                result = loader.fetch()

            event_ids = [_normalize_event_registry_record(r)["event_id"] for r in result.records]
            assert len(event_ids) == len(set(event_ids))
        finally:
            os.environ.pop("EVENT_REGISTRY_API_KEY", None)


# ---------------------------------------------------------------------------
# Skip without EVENT_REGISTRY_API_KEY
# ---------------------------------------------------------------------------


class TestEventRegistrySkipWithoutKey:
    def test_skips_cleanly_without_env_var(self) -> None:
        os.environ.pop("EVENT_REGISTRY_API_KEY", None)
        with patch("requests.post", side_effect=Exception("should not be called")):
            from scripts.live_source_runner_phase2 import run_phase2

            report = run_phase2(dry_run=True, sources=["event_registry"])

        er = next(s for s in report.sources if s.source_name == "event_registry")
        assert er.status == "skipped"
        assert er.fetched_count == 0
        assert er.skipped_reason

    def test_skip_reason_mentions_api_key(self) -> None:
        os.environ.pop("EVENT_REGISTRY_API_KEY", None)
        from scripts.live_source_runner_phase2 import run_phase2

        report = run_phase2(dry_run=True, sources=["event_registry"])
        er = next(s for s in report.sources if s.source_name == "event_registry")
        assert "EVENT_REGISTRY_API_KEY" in er.skipped_reason

    def test_advisory_fields_intact_when_skipped(self) -> None:
        os.environ.pop("EVENT_REGISTRY_API_KEY", None)
        from scripts.live_source_runner_phase2 import run_phase2

        report = run_phase2(dry_run=True, sources=["event_registry"])
        assert report.advisory_status == "ADVISORY_ONLY"
        assert report.execution_gate == "LOCKED"
        assert report.ai_execution_count == 0
        assert report.broker_api_called is False

    def test_newsapi_also_skips_independently(self) -> None:
        os.environ.pop("EVENT_REGISTRY_API_KEY", None)
        os.environ.pop("NEWS_API_KEY", None)
        from scripts.live_source_runner_phase2 import run_phase2

        report = run_phase2(dry_run=True, sources=["newsapi", "event_registry"])
        assert all(s.status == "skipped" for s in report.sources)
        assert report.total_fetched == 0


# ---------------------------------------------------------------------------
# Write-mode persistence
# ---------------------------------------------------------------------------


class TestEventRegistryWriteMode:
    def test_write_mode_calls_persist(self, er_payload: dict) -> None:
        os.environ["EVENT_REGISTRY_API_KEY"] = "test-er-key-mock"
        try:
            with patch("requests.post", return_value=_mock_response(er_payload)):
                from scripts.live_source_runner_phase2 import run_phase2

                with (
                    patch(
                        "scripts.live_source_runner_phase2._persist_events",
                        return_value=2,
                    ) as persist_mock,
                    patch("scripts.live_source_runner_phase2._log_run"),
                ):
                    report = run_phase2(dry_run=False, sources=["event_registry"])
                    persist_mock.assert_called_once()

            er = next(s for s in report.sources if s.source_name == "event_registry")
            assert er.events_persisted == 2
            assert report.total_persisted == 2
        finally:
            os.environ.pop("EVENT_REGISTRY_API_KEY", None)

    def test_write_mode_logs_run(self, er_payload: dict) -> None:
        os.environ["EVENT_REGISTRY_API_KEY"] = "test-er-key-mock"
        try:
            with patch("requests.post", return_value=_mock_response(er_payload)):
                from scripts.live_source_runner_phase2 import run_phase2

                with (
                    patch(
                        "scripts.live_source_runner_phase2._persist_events",
                        return_value=2,
                    ),
                    patch("scripts.live_source_runner_phase2._log_run") as log_mock,
                ):
                    run_phase2(dry_run=False, sources=["event_registry"])
                    assert log_mock.call_count >= 1
        finally:
            os.environ.pop("EVENT_REGISTRY_API_KEY", None)

    def test_dry_run_skipped_never_logs(self) -> None:
        os.environ.pop("EVENT_REGISTRY_API_KEY", None)
        from scripts.live_source_runner_phase2 import run_phase2

        with patch("scripts.live_source_runner_phase2._log_run") as log_mock:
            run_phase2(dry_run=True, sources=["event_registry"])
            log_mock.assert_not_called()

    def test_persist_events_receives_correct_source_name(self, er_payload: dict) -> None:
        os.environ["EVENT_REGISTRY_API_KEY"] = "test-er-key-mock"
        try:
            with patch("requests.post", return_value=_mock_response(er_payload)):
                from scripts.live_source_runner_phase2 import run_phase2

                with (
                    patch(
                        "scripts.live_source_runner_phase2._persist_events",
                        return_value=2,
                    ) as persist_mock,
                    patch("scripts.live_source_runner_phase2._log_run"),
                ):
                    run_phase2(dry_run=False, sources=["event_registry"])
                    _, call_kwargs = persist_mock.call_args
                    positional = persist_mock.call_args[0]
                    assert positional[1] == "event_registry"
        finally:
            os.environ.pop("EVENT_REGISTRY_API_KEY", None)


# ---------------------------------------------------------------------------
# No-execution safety
# ---------------------------------------------------------------------------


class TestEventRegistryNoExecutionSafety:
    def test_runner_report_never_contains_trade_fields(self, er_payload: dict) -> None:
        os.environ["EVENT_REGISTRY_API_KEY"] = "test-er-key-mock"
        try:
            with patch("requests.post", return_value=_mock_response(er_payload)):
                from scripts.live_source_runner_phase2 import run_phase2

                report = run_phase2(dry_run=True, sources=["event_registry"])

            d = report.to_dict()
            forbidden = {"trade_id", "broker_order_id", "executed", "order_id", "buy", "sell"}
            assert not forbidden & set(d.keys())
        finally:
            os.environ.pop("EVENT_REGISTRY_API_KEY", None)

    def test_phase2_runner_no_forbidden_methods(self) -> None:
        runner_path = REPO_ROOT / "scripts" / "live_source_runner_phase2.py"
        source = runner_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        forbidden = {
            "place_order",
            "execute_trade",
            "submit_order",
            "auto_buy",
            "auto_sell",
            "cancel_order",
            "modify_order",
        }
        defined = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert not defined & forbidden

    def test_event_registry_loader_no_forbidden_methods(self) -> None:
        loader_path = REPO_ROOT / "scripts" / "ingestion" / "event_registry_loader.py"
        source = loader_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        forbidden = {"place_order", "execute_trade", "submit_order", "auto_buy", "auto_sell"}
        defined = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert not defined & forbidden

    def test_normalized_event_ai_execution_count_is_zero(self) -> None:
        from scripts.live_source_runner_phase2 import _normalize_event_registry_record

        rec = {"url": "https://example.com/er/1", "title": "Test"}
        out = _normalize_event_registry_record(rec)
        assert out["ai_execution_count"] == 0

    def test_normalized_event_broker_api_called_is_false(self) -> None:
        from scripts.live_source_runner_phase2 import _normalize_event_registry_record

        rec = {"url": "https://example.com/er/1", "title": "Test"}
        out = _normalize_event_registry_record(rec)
        assert out["broker_api_called"] is False

    def test_normalized_event_execution_gate_is_locked(self) -> None:
        from scripts.live_source_runner_phase2 import _normalize_event_registry_record

        rec = {"url": "https://example.com/er/1", "title": "Test"}
        out = _normalize_event_registry_record(rec)
        assert out["execution_gate"] == "LOCKED"


# ---------------------------------------------------------------------------
# Duration tracking
# ---------------------------------------------------------------------------


class TestEventRegistryDurationTracking:
    def test_duration_ms_is_non_negative_on_success(self, er_payload: dict) -> None:
        os.environ["EVENT_REGISTRY_API_KEY"] = "test-er-key-mock"
        try:
            with patch("requests.post", return_value=_mock_response(er_payload)):
                from scripts.live_source_runner_phase2 import run_phase2

                report = run_phase2(dry_run=True, sources=["event_registry"])

            for src in report.sources:
                assert src.duration_ms >= 0
        finally:
            os.environ.pop("EVENT_REGISTRY_API_KEY", None)

    def test_duration_ms_is_non_negative_on_skip(self) -> None:
        os.environ.pop("EVENT_REGISTRY_API_KEY", None)
        from scripts.live_source_runner_phase2 import run_phase2

        report = run_phase2(dry_run=True, sources=["event_registry"])
        for src in report.sources:
            assert src.duration_ms >= 0


# ---------------------------------------------------------------------------
# EventRegistryLoader unit tests
# ---------------------------------------------------------------------------


class TestEventRegistryLoader:
    def test_loader_skips_without_api_key(self) -> None:
        os.environ.pop("EVENT_REGISTRY_API_KEY", None)
        from scripts.ingestion.event_registry_loader import EventRegistryLoader

        loader = EventRegistryLoader()
        result = loader.safe_fetch()
        assert result.skipped is True
        assert "EVENT_REGISTRY_API_KEY" in result.skip_reason

    def test_loader_returns_records_with_key(self, er_payload: dict) -> None:
        os.environ["EVENT_REGISTRY_API_KEY"] = "test-er-key-mock"
        try:
            with patch("requests.post", return_value=_mock_response(er_payload)):
                from scripts.ingestion.event_registry_loader import EventRegistryLoader

                loader = EventRegistryLoader()
                result = loader.fetch()

            assert result.skipped is False
            assert len(result.records) == 2
            assert result.source_name == "event_registry"
        finally:
            os.environ.pop("EVENT_REGISTRY_API_KEY", None)

    def test_loader_stamps_advisory_on_records(self, er_payload: dict) -> None:
        os.environ["EVENT_REGISTRY_API_KEY"] = "test-er-key-mock"
        try:
            with patch("requests.post", return_value=_mock_response(er_payload)):
                from scripts.ingestion.event_registry_loader import EventRegistryLoader

                loader = EventRegistryLoader()
                result = loader.fetch()

            for rec in result.records:
                assert rec["advisory_status"] == "ADVISORY_ONLY"
                assert rec["human_review_required"] is True
                assert rec["execution_gate"] == "LOCKED"
        finally:
            os.environ.pop("EVENT_REGISTRY_API_KEY", None)

    def test_loader_result_advisory_status(self) -> None:
        os.environ.pop("EVENT_REGISTRY_API_KEY", None)
        from scripts.ingestion.event_registry_loader import EventRegistryLoader

        loader = EventRegistryLoader()
        result = loader.safe_fetch()
        assert result.advisory_status == "ADVISORY_ONLY"
        assert result.human_review_required is True
        assert result.execution_gate == "LOCKED"

    def test_loader_records_have_expected_fields(self, er_payload: dict) -> None:
        os.environ["EVENT_REGISTRY_API_KEY"] = "test-er-key-mock"
        try:
            with patch("requests.post", return_value=_mock_response(er_payload)):
                from scripts.ingestion.event_registry_loader import EventRegistryLoader

                loader = EventRegistryLoader()
                result = loader.fetch()

            for rec in result.records:
                assert "title" in rec
                assert "url" in rec
                assert "date_time" in rec
                assert "source_name" in rec
                assert "body" in rec
                assert rec["source"] == "event_registry"
        finally:
            os.environ.pop("EVENT_REGISTRY_API_KEY", None)

    def test_loader_network_error_safe_fetch(self) -> None:
        os.environ["EVENT_REGISTRY_API_KEY"] = "test-er-key-mock"
        try:
            with patch("requests.post", side_effect=Exception("timeout")):
                from scripts.ingestion.event_registry_loader import EventRegistryLoader

                loader = EventRegistryLoader()
                result = loader.safe_fetch()

            assert result.skipped is True
            assert "unreachable" in result.skip_reason.lower()
        finally:
            os.environ.pop("EVENT_REGISTRY_API_KEY", None)

    def test_loader_custom_keywords(self, er_payload: dict) -> None:
        os.environ["EVENT_REGISTRY_API_KEY"] = "test-er-key-mock"
        try:
            with patch("requests.post", return_value=_mock_response(er_payload)) as post_mock:
                from scripts.ingestion.event_registry_loader import EventRegistryLoader

                loader = EventRegistryLoader(keywords=["crypto", "bitcoin"])
                loader.fetch()

            call_json = post_mock.call_args[1]["json"]
            assert call_json["keyword"] == ["crypto", "bitcoin"]
        finally:
            os.environ.pop("EVENT_REGISTRY_API_KEY", None)

    def test_loader_source_name_is_event_registry(self) -> None:
        from scripts.ingestion.event_registry_loader import EventRegistryLoader

        loader = EventRegistryLoader()
        assert loader.source_name == "event_registry"

    def test_loader_non_dict_articles_skipped(self) -> None:
        os.environ["EVENT_REGISTRY_API_KEY"] = "test-er-key-mock"
        payload = {"articles": {"results": ["not-a-dict", None, 42]}}
        try:
            with patch("requests.post", return_value=_mock_response(payload)):
                from scripts.ingestion.event_registry_loader import EventRegistryLoader

                loader = EventRegistryLoader()
                result = loader.fetch()

            assert result.records == []
        finally:
            os.environ.pop("EVENT_REGISTRY_API_KEY", None)


# ---------------------------------------------------------------------------
# Multi-source run (newsapi + event_registry together)
# ---------------------------------------------------------------------------


class TestMultiSourceRun:
    def test_both_sources_run_independently(self, er_payload: dict) -> None:
        newsapi_payload = {
            "status": "ok",
            "articles": [
                {
                    "title": "Fed holds rates",
                    "url": "https://example.com/news/1",
                    "publishedAt": "2026-05-10T09:00:00Z",
                    "source": {"name": "Reuters"},
                    "description": "The Fed held rates steady.",
                },
            ],
        }
        os.environ["NEWS_API_KEY"] = "test-news-key"
        os.environ["EVENT_REGISTRY_API_KEY"] = "test-er-key"
        try:
            with (
                patch("requests.get", return_value=_mock_response(newsapi_payload)),
                patch("requests.post", return_value=_mock_response(er_payload)),
            ):
                from scripts.live_source_runner_phase2 import run_phase2

                report = run_phase2(dry_run=True, sources=["newsapi", "event_registry"])

            assert report.total_fetched == 3
            names = {s.source_name for s in report.sources}
            assert names == {"newsapi", "event_registry"}
            assert report.advisory_status == "ADVISORY_ONLY"
            assert report.ai_execution_count == 0
        finally:
            os.environ.pop("NEWS_API_KEY", None)
            os.environ.pop("EVENT_REGISTRY_API_KEY", None)

    def test_er_skips_newsapi_still_runs(self, er_payload: dict) -> None:
        newsapi_payload = {
            "status": "ok",
            "articles": [
                {
                    "title": "Market update",
                    "url": "https://example.com/news/2",
                    "publishedAt": "2026-05-10T08:00:00Z",
                    "source": {"name": "AP"},
                    "description": "Brief market update.",
                },
            ],
        }
        os.environ["NEWS_API_KEY"] = "test-news-key"
        os.environ.pop("EVENT_REGISTRY_API_KEY", None)
        try:
            with patch("requests.get", return_value=_mock_response(newsapi_payload)):
                from scripts.live_source_runner_phase2 import run_phase2

                report = run_phase2(dry_run=True, sources=["newsapi", "event_registry"])

            news = next(s for s in report.sources if s.source_name == "newsapi")
            er = next(s for s in report.sources if s.source_name == "event_registry")
            assert news.status == "ok"
            assert news.fetched_count == 1
            assert er.status == "skipped"
        finally:
            os.environ.pop("NEWS_API_KEY", None)
