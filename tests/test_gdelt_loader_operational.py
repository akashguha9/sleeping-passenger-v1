"""
Tests for GDELT loader — retry, backoff, 429, timeout, user-agent.

All HTTP is mocked. No live network calls.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch, call

import pytest

from scripts.ingestion.gdelt_loader import GDELTLoader
from scripts.ingestion.base_loader import SkipLoader, LoaderResult


def _mock_ok(articles: list[dict]) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"articles": articles}
    resp.raise_for_status.return_value = None
    return resp


def _mock_status(status_code: int) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return resp


_SAMPLE_ARTICLES = [
    {
        "url": "https://example.com/article1",
        "title": "Economy grows 3%",
        "seendate": "2026-05-11T12:00:00",
        "domain": "example.com",
        "language": "English",
        "sourcecountry": "US",
    },
    {
        "url": "https://example.com/article2",
        "title": "Inflation hits 6-month low",
        "seendate": "2026-05-11T11:30:00",
        "domain": "example.com",
        "language": "English",
        "sourcecountry": "US",
    },
]


class TestGDELTLoaderInit:
    def test_defaults(self) -> None:
        loader = GDELTLoader()
        assert loader._max == 25
        assert loader._timeout == 8  # was 15, now 8

    def test_custom_params(self) -> None:
        loader = GDELTLoader(query="bitcoin", max_records=10, timeout=5)
        assert loader._query == "bitcoin"
        assert loader._max == 10
        assert loader._timeout == 5

    def test_source_name(self) -> None:
        assert GDELTLoader.source_name == "gdelt"


class TestGDELTSuccessPath:
    def test_fetch_returns_loader_result(self) -> None:
        loader = GDELTLoader()
        with patch("requests.get", return_value=_mock_ok(_SAMPLE_ARTICLES)):
            result = loader.fetch()
        assert isinstance(result, LoaderResult)
        assert not result.skipped
        assert len(result.records) == 2

    def test_records_have_advisory_stamps(self) -> None:
        loader = GDELTLoader()
        with patch("requests.get", return_value=_mock_ok(_SAMPLE_ARTICLES)):
            result = loader.fetch()
        for rec in result.records:
            assert rec["advisory_status"] == "ADVISORY_ONLY"
            assert rec["human_review_required"] is True
            assert rec["execution_gate"] == "LOCKED"

    def test_records_have_expected_fields(self) -> None:
        loader = GDELTLoader()
        with patch("requests.get", return_value=_mock_ok(_SAMPLE_ARTICLES)):
            result = loader.fetch()
        rec = result.records[0]
        assert "url" in rec
        assert "title" in rec
        assert "seendate" in rec
        assert rec["source"] == "gdelt"

    def test_user_agent_sent(self) -> None:
        loader = GDELTLoader()
        with patch("requests.get", return_value=_mock_ok(_SAMPLE_ARTICLES)) as mock_get:
            loader.fetch()
        _, kwargs = mock_get.call_args
        headers = kwargs.get("headers", {})
        assert "User-Agent" in headers

    def test_empty_articles_returns_empty_records(self) -> None:
        loader = GDELTLoader()
        with patch("requests.get", return_value=_mock_ok([])):
            result = loader.fetch()
        assert result.records == []


class TestGDELT429:
    def test_429_raises_skip_loader(self) -> None:
        loader = GDELTLoader()
        rate_limited = _mock_status(429)
        rate_limited.status_code = 429
        with patch("requests.get", return_value=rate_limited):
            with pytest.raises(SkipLoader) as exc_info:
                loader.fetch()
        assert "[RATE_LIMITED]" in str(exc_info.value)

    def test_429_safe_fetch_status_rate_limited(self) -> None:
        loader = GDELTLoader()
        rate_limited = MagicMock()
        rate_limited.status_code = 429
        with patch("requests.get", return_value=rate_limited):
            result = loader.safe_fetch()
        assert result.skipped
        assert "[RATE_LIMITED]" in result.skip_reason

    def test_429_does_not_retry(self) -> None:
        loader = GDELTLoader()
        rate_limited = MagicMock()
        rate_limited.status_code = 429
        with patch("requests.get", return_value=rate_limited) as mock_get:
            loader.safe_fetch()
        # 429 triggers immediate bail, no second request
        assert mock_get.call_count == 1


class TestGDELTTimeout:
    def test_timeout_raises_skip_loader(self) -> None:
        import requests as req_mod
        loader = GDELTLoader()
        with patch("requests.get", side_effect=req_mod.exceptions.Timeout("timed out")):
            with pytest.raises(SkipLoader) as exc_info:
                loader.fetch()
        assert "[TIMEOUT]" in str(exc_info.value)

    def test_timeout_safe_fetch_skipped(self) -> None:
        import requests as req_mod
        loader = GDELTLoader()
        with patch("requests.get", side_effect=req_mod.exceptions.Timeout("timed out")):
            result = loader.safe_fetch()
        assert result.skipped
        assert "[TIMEOUT]" in result.skip_reason

    def test_timeout_retries_with_fallback_query(self) -> None:
        """After a timeout, a second attempt should be made with the fallback query."""
        import requests as req_mod
        loader = GDELTLoader()
        call_count = {"n": 0}

        def side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise req_mod.exceptions.Timeout("timed out")
            return _mock_ok(_SAMPLE_ARTICLES)

        with patch("requests.get", side_effect=side_effect):
            result = loader.fetch()
        assert call_count["n"] == 2
        assert not result.skipped


class TestGDELTRunnerStatus:
    def test_runner_status_rate_limited(self) -> None:
        from scripts.live_source_runner import run_phase1
        rate_limited = MagicMock()
        rate_limited.status_code = 429
        with patch("requests.get", return_value=rate_limited):
            report = run_phase1(dry_run=True, sources=["gdelt"])
        src = report.sources[0]
        assert src.status == "rate_limited"

    def test_runner_status_ok_on_success(self) -> None:
        from scripts.live_source_runner import run_phase1
        with patch("requests.get", return_value=_mock_ok(_SAMPLE_ARTICLES)):
            report = run_phase1(dry_run=True, sources=["gdelt"])
        src = report.sources[0]
        assert src.status == "ok"
        assert src.fetched_count == 2
