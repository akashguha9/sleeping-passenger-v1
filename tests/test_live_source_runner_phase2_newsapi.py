"""
Tests for Phase 2 live source runner — NewsAPI.

Principles
----------
- Zero live network calls. All HTTP is intercepted with unittest.mock.patch.
- Missing NEWS_API_KEY skips cleanly with a meaningful reason string.
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
    return tmp_path / "test_phase2.db"


@pytest.fixture()
def newsapi_payload() -> dict:
    return {
        "status": "ok",
        "totalResults": 2,
        "articles": [
            {
                "title": "Markets rally amid Fed rate decision",
                "description": "US equity markets surged after the Fed held rates steady.",
                "url": "https://example.com/news/1",
                "publishedAt": "2026-05-10T09:00:00Z",
                "source": {"name": "Reuters"},
            },
            {
                "title": "Economy shows signs of resilience",
                "description": "GDP figures beat expectations for Q1 2026.",
                "url": "https://example.com/news/2",
                "publishedAt": "2026-05-10T08:30:00Z",
                "source": {"name": "Bloomberg"},
            },
        ],
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

        s = SourceRunResult(source_name="newsapi", status="ok", timestamp_utc="t")
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

    def test_report_to_dict_no_trade_or_broker_order_fields(self) -> None:
        from scripts.live_source_runner_phase2 import Phase2RunReport

        d = Phase2RunReport(dry_run=True, run_at="t").to_dict()
        forbidden_keys = {"trade_id", "broker_order_id", "executed", "order_id"}
        assert not forbidden_keys & set(d.keys())


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


class TestNormalization:
    def test_normalize_newsapi_fields(self) -> None:
        from scripts.live_source_runner_phase2 import _normalize_newsapi_record

        rec = {
            "url": "https://example.com/news/1",
            "title": "Markets rally",
            "description": "Stocks up.",
            "published_at": "2026-05-10T09:00:00Z",
            "source_name": "Reuters",
            "source": "newsapi",
        }
        out = _normalize_newsapi_record(rec)
        assert out["source_name"] == "newsapi"
        assert out["signal_type"] == "news_article"
        assert out["title"] == "Markets rally"
        assert out["url"] == "https://example.com/news/1"
        assert out["publisher"] == "Reuters"
        assert out["advisory_status"] == "ADVISORY_ONLY"
        assert out["human_review_required"] is True
        assert out["execution_gate"] == "LOCKED"
        assert out["ai_execution_count"] == 0
        assert out["broker_api_called"] is False

    def test_normalize_newsapi_event_id_format(self) -> None:
        from scripts.live_source_runner_phase2 import _normalize_newsapi_record

        rec = {"url": "https://example.com/news/1", "title": "Test"}
        out = _normalize_newsapi_record(rec)
        assert out["event_id"].startswith("newsapi_")
        assert len(out["event_id"]) == len("newsapi_") + 16

    def test_stable_event_id_deterministic(self) -> None:
        from scripts.live_source_runner_phase2 import _stable_event_id

        assert _stable_event_id("newsapi", "https://x.com/a") == _stable_event_id(
            "newsapi", "https://x.com/a"
        )

    def test_stable_event_id_different_urls(self) -> None:
        from scripts.live_source_runner_phase2 import _stable_event_id

        assert _stable_event_id("newsapi", "https://x.com/1") != _stable_event_id(
            "newsapi", "https://x.com/2"
        )

    def test_all_normalized_records_advisory_stamped(self, newsapi_payload: dict) -> None:
        from scripts.live_source_runner_phase2 import _normalize_newsapi_record

        for art in newsapi_payload["articles"]:
            rec = {
                "url": art.get("url", ""),
                "title": art.get("title", ""),
                "description": art.get("description", ""),
                "published_at": art.get("publishedAt", ""),
                "source_name": (art.get("source") or {}).get("name", ""),
                "source": "newsapi",
            }
            out = _normalize_newsapi_record(rec)
            assert out["advisory_status"] == "ADVISORY_ONLY"
            assert out["human_review_required"] is True
            assert out["execution_gate"] == "LOCKED"
            assert out["ai_execution_count"] == 0
            assert out["broker_api_called"] is False


# ---------------------------------------------------------------------------
# NewsAPI — mocked HTTP
# ---------------------------------------------------------------------------


class TestNewsAPIMocked:
    def test_dry_run_fetches_correct_count(self, newsapi_payload: dict) -> None:
        os.environ["NEWS_API_KEY"] = "test-key-mock"
        try:
            with patch("requests.get", return_value=_mock_response(newsapi_payload)):
                from scripts.live_source_runner_phase2 import run_phase2

                report = run_phase2(dry_run=True)

            newsapi = next(s for s in report.sources if s.source_name == "newsapi")
            assert newsapi.status == "ok"
            assert newsapi.fetched_count == 2
            assert newsapi.events_persisted == 0
            assert report.advisory_status == "ADVISORY_ONLY"
            assert report.ai_execution_count == 0
            assert report.broker_api_called is False
        finally:
            os.environ.pop("NEWS_API_KEY", None)

    def test_dry_run_never_calls_persist(self, newsapi_payload: dict) -> None:
        os.environ["NEWS_API_KEY"] = "test-key-mock"
        try:
            with patch("requests.get", return_value=_mock_response(newsapi_payload)):
                from scripts.live_source_runner_phase2 import run_phase2

                with patch(
                    "scripts.live_source_runner_phase2._persist_events"
                ) as persist_mock:
                    run_phase2(dry_run=True)
                    persist_mock.assert_not_called()
        finally:
            os.environ.pop("NEWS_API_KEY", None)

    def test_network_error_yields_skipped_source(self) -> None:
        os.environ["NEWS_API_KEY"] = "test-key-mock"
        try:
            with patch("requests.get", side_effect=Exception("network down")):
                from scripts.live_source_runner_phase2 import run_phase2

                report = run_phase2(dry_run=True)

            newsapi = next(s for s in report.sources if s.source_name == "newsapi")
            assert newsapi.status in ("skipped", "http_error")
            assert newsapi.fetched_count == 0
        finally:
            os.environ.pop("NEWS_API_KEY", None)

    def test_empty_articles_list(self) -> None:
        os.environ["NEWS_API_KEY"] = "test-key-mock"
        try:
            with patch(
                "requests.get",
                return_value=_mock_response({"status": "ok", "articles": []}),
            ):
                from scripts.live_source_runner_phase2 import run_phase2

                report = run_phase2(dry_run=True)

            newsapi = next(s for s in report.sources if s.source_name == "newsapi")
            assert newsapi.status == "ok"
            assert newsapi.fetched_count == 0
        finally:
            os.environ.pop("NEWS_API_KEY", None)

    def test_total_fetched_accumulates(self, newsapi_payload: dict) -> None:
        os.environ["NEWS_API_KEY"] = "test-key-mock"
        try:
            with patch("requests.get", return_value=_mock_response(newsapi_payload)):
                from scripts.live_source_runner_phase2 import run_phase2

                report = run_phase2(dry_run=True)

            assert report.total_fetched == 2
            assert report.total_persisted == 0
        finally:
            os.environ.pop("NEWS_API_KEY", None)


# ---------------------------------------------------------------------------
# Skip without NEWS_API_KEY
# ---------------------------------------------------------------------------


class TestNewsAPISkipWithoutKey:
    def test_skips_cleanly_without_env_var(self) -> None:
        os.environ.pop("NEWS_API_KEY", None)
        os.environ.pop("NEWSAPI_KEY", None)
        with patch("requests.get", side_effect=Exception("should not be called")):
            from scripts.live_source_runner_phase2 import run_phase2

            report = run_phase2(dry_run=True)

        newsapi = next(s for s in report.sources if s.source_name == "newsapi")
        assert newsapi.status == "skipped"
        assert newsapi.fetched_count == 0
        assert newsapi.skipped_reason

    def test_skip_reason_mentions_api_key(self) -> None:
        os.environ.pop("NEWS_API_KEY", None)
        os.environ.pop("NEWSAPI_KEY", None)
        from scripts.live_source_runner_phase2 import run_phase2

        report = run_phase2(dry_run=True)
        newsapi = next(s for s in report.sources if s.source_name == "newsapi")
        assert "NEWS_API_KEY" in newsapi.skipped_reason

    def test_advisory_fields_intact_when_skipped(self) -> None:
        os.environ.pop("NEWS_API_KEY", None)
        os.environ.pop("NEWSAPI_KEY", None)
        from scripts.live_source_runner_phase2 import run_phase2

        report = run_phase2(dry_run=True)
        assert report.advisory_status == "ADVISORY_ONLY"
        assert report.execution_gate == "LOCKED"
        assert report.ai_execution_count == 0
        assert report.broker_api_called is False


# ---------------------------------------------------------------------------
# Write-mode persistence
# ---------------------------------------------------------------------------


class TestWriteMode:
    def test_write_mode_calls_persist(self, newsapi_payload: dict) -> None:
        os.environ["NEWS_API_KEY"] = "test-key-mock"
        try:
            with patch("requests.get", return_value=_mock_response(newsapi_payload)):
                from scripts.live_source_runner_phase2 import run_phase2

                with (
                    patch(
                        "scripts.live_source_runner_phase2._persist_events",
                        return_value=2,
                    ) as persist_mock,
                    patch("scripts.live_source_runner_phase2._log_run"),
                ):
                    report = run_phase2(dry_run=False)
                    persist_mock.assert_called_once()

            newsapi = next(s for s in report.sources if s.source_name == "newsapi")
            assert newsapi.events_persisted == 2
            assert report.total_persisted == 2
        finally:
            os.environ.pop("NEWS_API_KEY", None)

    def test_write_mode_logs_run(self, newsapi_payload: dict) -> None:
        os.environ["NEWS_API_KEY"] = "test-key-mock"
        try:
            with patch("requests.get", return_value=_mock_response(newsapi_payload)):
                from scripts.live_source_runner_phase2 import run_phase2

                with (
                    patch(
                        "scripts.live_source_runner_phase2._persist_events",
                        return_value=2,
                    ),
                    patch("scripts.live_source_runner_phase2._log_run") as log_mock,
                ):
                    run_phase2(dry_run=False)
                    assert log_mock.call_count >= 1
        finally:
            os.environ.pop("NEWS_API_KEY", None)

    def test_dry_run_skipped_never_logs(self) -> None:
        os.environ.pop("NEWS_API_KEY", None)
        from scripts.live_source_runner_phase2 import run_phase2

        with patch("scripts.live_source_runner_phase2._log_run") as log_mock:
            run_phase2(dry_run=True)
            log_mock.assert_not_called()


# ---------------------------------------------------------------------------
# No-execution safety
# ---------------------------------------------------------------------------


class TestNoExecutionSafety:
    def test_runner_report_never_contains_trade_fields(self, newsapi_payload: dict) -> None:
        os.environ["NEWS_API_KEY"] = "test-key-mock"
        try:
            with patch("requests.get", return_value=_mock_response(newsapi_payload)):
                from scripts.live_source_runner_phase2 import run_phase2

                report = run_phase2(dry_run=True)

            d = report.to_dict()
            forbidden = {"trade_id", "broker_order_id", "executed", "order_id", "buy", "sell"}
            assert not forbidden & set(d.keys())
        finally:
            os.environ.pop("NEWS_API_KEY", None)

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

    def test_run_phase2_cli_no_forbidden_methods(self) -> None:
        cli_path = REPO_ROOT / "scripts" / "run_live_sources_phase2.py"
        source = cli_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        forbidden = {"place_order", "execute_trade", "submit_order"}
        defined = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert not defined & forbidden

    def test_newsapi_loader_no_forbidden_methods(self) -> None:
        loader_path = REPO_ROOT / "scripts" / "ingestion" / "newsapi_loader.py"
        source = loader_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        forbidden = {"place_order", "execute_trade", "submit_order", "auto_buy", "auto_sell"}
        defined = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert not defined & forbidden


# ---------------------------------------------------------------------------
# All-sources-skipped scenario
# ---------------------------------------------------------------------------


class TestAllSkipped:
    def test_all_skipped_report_is_valid(self) -> None:
        os.environ.pop("NEWS_API_KEY", None)
        os.environ.pop("NEWSAPI_KEY", None)
        from scripts.live_source_runner_phase2 import run_phase2

        report = run_phase2(dry_run=True)
        assert report.total_fetched == 0
        assert report.total_persisted == 0
        assert report.advisory_status == "ADVISORY_ONLY"
        assert all(s.status == "skipped" for s in report.sources)
        assert len(report.sources) == 1

    def test_all_skipped_sources_named(self) -> None:
        os.environ.pop("NEWS_API_KEY", None)
        os.environ.pop("NEWSAPI_KEY", None)
        from scripts.live_source_runner_phase2 import run_phase2

        report = run_phase2(dry_run=True)
        names = {s.source_name for s in report.sources}
        assert names == {"newsapi"}

    def test_report_to_dict_valid_when_all_skipped(self) -> None:
        os.environ.pop("NEWS_API_KEY", None)
        os.environ.pop("NEWSAPI_KEY", None)
        from scripts.live_source_runner_phase2 import run_phase2

        report = run_phase2(dry_run=True)
        d = report.to_dict()
        assert isinstance(d["sources"], list)
        assert d["total_fetched"] == 0
        assert d["broker_api_called"] is False


# ---------------------------------------------------------------------------
# Duration tracking
# ---------------------------------------------------------------------------


class TestDurationTracking:
    def test_duration_ms_is_non_negative_on_success(self, newsapi_payload: dict) -> None:
        os.environ["NEWS_API_KEY"] = "test-key-mock"
        try:
            with patch("requests.get", return_value=_mock_response(newsapi_payload)):
                from scripts.live_source_runner_phase2 import run_phase2

                report = run_phase2(dry_run=True)

            for src in report.sources:
                assert src.duration_ms >= 0
        finally:
            os.environ.pop("NEWS_API_KEY", None)

    def test_duration_ms_is_non_negative_on_skip(self) -> None:
        os.environ.pop("NEWS_API_KEY", None)
        os.environ.pop("NEWSAPI_KEY", None)
        from scripts.live_source_runner_phase2 import run_phase2

        report = run_phase2(dry_run=True)
        for src in report.sources:
            assert src.duration_ms >= 0


# ---------------------------------------------------------------------------
# NewsAPI loader unit tests
# ---------------------------------------------------------------------------


class TestNewsAPILoader:
    def test_loader_skips_without_api_key(self) -> None:
        os.environ.pop("NEWS_API_KEY", None)
        os.environ.pop("NEWSAPI_KEY", None)
        from scripts.ingestion.newsapi_loader import NewsAPILoader

        loader = NewsAPILoader()
        result = loader.safe_fetch()
        assert result.skipped is True
        assert "NEWS_API_KEY" in result.skip_reason

    def test_loader_returns_records_with_key(self, newsapi_payload: dict) -> None:
        os.environ["NEWS_API_KEY"] = "test-key-mock"
        try:
            with patch("requests.get", return_value=_mock_response(newsapi_payload)):
                from scripts.ingestion.newsapi_loader import NewsAPILoader

                loader = NewsAPILoader()
                result = loader.fetch()

            assert result.skipped is False
            assert len(result.records) == 2
            assert result.source_name == "newsapi"
        finally:
            os.environ.pop("NEWS_API_KEY", None)

    def test_loader_stamps_advisory_on_records(self, newsapi_payload: dict) -> None:
        os.environ["NEWS_API_KEY"] = "test-key-mock"
        try:
            with patch("requests.get", return_value=_mock_response(newsapi_payload)):
                from scripts.ingestion.newsapi_loader import NewsAPILoader

                loader = NewsAPILoader()
                result = loader.fetch()

            for rec in result.records:
                assert rec["advisory_status"] == "ADVISORY_ONLY"
                assert rec["human_review_required"] is True
                assert rec["execution_gate"] == "LOCKED"
        finally:
            os.environ.pop("NEWS_API_KEY", None)

    def test_loader_result_advisory_status(self) -> None:
        os.environ.pop("NEWS_API_KEY", None)
        os.environ.pop("NEWSAPI_KEY", None)
        from scripts.ingestion.newsapi_loader import NewsAPILoader

        loader = NewsAPILoader()
        result = loader.safe_fetch()
        assert result.advisory_status == "ADVISORY_ONLY"
        assert result.human_review_required is True
        assert result.execution_gate == "LOCKED"

    def test_loader_records_have_expected_fields(self, newsapi_payload: dict) -> None:
        os.environ["NEWS_API_KEY"] = "test-key-mock"
        try:
            with patch("requests.get", return_value=_mock_response(newsapi_payload)):
                from scripts.ingestion.newsapi_loader import NewsAPILoader

                loader = NewsAPILoader()
                result = loader.fetch()

            for rec in result.records:
                assert "title" in rec
                assert "url" in rec
                assert "published_at" in rec
                assert "source_name" in rec
                assert rec["source"] == "newsapi"
        finally:
            os.environ.pop("NEWS_API_KEY", None)

    def test_loader_network_error_safe_fetch(self) -> None:
        os.environ["NEWS_API_KEY"] = "test-key-mock"
        try:
            with patch("requests.get", side_effect=Exception("timeout")):
                from scripts.ingestion.newsapi_loader import NewsAPILoader

                loader = NewsAPILoader()
                result = loader.safe_fetch()

            assert result.skipped is True
            assert "unreachable" in result.skip_reason.lower()
        finally:
            os.environ.pop("NEWS_API_KEY", None)
