"""
Tests for Global Filings loader — SEC EFTS active provider, placeholder status,
advisory contract.

All HTTP is mocked. No live network calls.
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.ingestion.global_filings_loader import GlobalFilingsLoader, _PROVIDER_CONFIGS
from scripts.ingestion.base_loader import SkipLoader, LoaderResult

REPO_ROOT = Path(__file__).resolve().parents[1]


def _mock_response(payload: object) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status.return_value = None
    resp.json.return_value = payload
    return resp


_SAMPLE_EFTS_RESPONSE = {
    "hits": {
        "total": {"value": 2},
        "hits": [
            {
                "_source": {
                    "entity_name": "APPLE INC",
                    "display_names": [{"name": "Apple Inc.", "ticker": "AAPL"}],
                    "form_type": "8-K",
                    "file_date": "2026-05-10",
                    "accession_no": "0000320193-26-000001",
                    "period_of_report": "2026-05-10",
                }
            },
            {
                "_source": {
                    "entity_name": "MICROSOFT CORP",
                    "display_names": [{"name": "Microsoft Corporation", "ticker": "MSFT"}],
                    "form_type": "10-Q",
                    "file_date": "2026-05-09",
                    "accession_no": "0000789019-26-000002",
                    "period_of_report": "2026-03-31",
                }
            },
        ],
    }
}


class TestProviderConfigs:
    def test_sec_efts_is_active(self) -> None:
        assert _PROVIDER_CONFIGS["sec_efts"]["active"] is True

    def test_asx_is_not_active(self) -> None:
        assert not _PROVIDER_CONFIGS["asx"]["active"]

    def test_all_placeholder_providers_inactive(self) -> None:
        placeholders = ["asx", "hkex", "sgx", "uk_rns", "esma", "sedar", "tdnet"]
        for p in placeholders:
            assert not _PROVIDER_CONFIGS[p]["active"], f"{p} should be inactive"

    def test_sec_efts_has_correct_url(self) -> None:
        assert "efts.sec.gov" in _PROVIDER_CONFIGS["sec_efts"]["url"]

    def test_sec_efts_requires_key(self) -> None:
        assert _PROVIDER_CONFIGS["sec_efts"]["requires_key"] is True
        assert _PROVIDER_CONFIGS["sec_efts"]["key_env"] == "SEC_USER_AGENT"


class TestGlobalFilingsNoActiveProvider:
    def test_skip_when_no_active_providers_selected(self) -> None:
        with patch.dict(os.environ, {"SEC_USER_AGENT": "Test/1.0"}):
            loader = GlobalFilingsLoader(providers=["asx", "hkex"])
            with pytest.raises(SkipLoader) as exc_info:
                loader.fetch()
        assert "[PLACEHOLDER]" in str(exc_info.value)

    def test_safe_fetch_placeholder_status(self) -> None:
        with patch.dict(os.environ, {"SEC_USER_AGENT": "Test/1.0"}):
            loader = GlobalFilingsLoader(providers=["hkex", "tdnet"])
            result = loader.safe_fetch()
        assert result.skipped
        assert "[PLACEHOLDER]" in result.skip_reason


class TestGlobalFilingsSECEFTS:
    def test_fetch_returns_loader_result(self) -> None:
        with patch.dict(os.environ, {"SEC_USER_AGENT": "Test Agent/1.0 test@example.com"}):
            with patch("requests.get", return_value=_mock_response(_SAMPLE_EFTS_RESPONSE)):
                loader = GlobalFilingsLoader(providers=["sec_efts"])
                result = loader.fetch()
        assert isinstance(result, LoaderResult)
        assert not result.skipped

    def test_fetch_returns_records(self) -> None:
        with patch.dict(os.environ, {"SEC_USER_AGENT": "Test/1.0"}):
            with patch("requests.get", return_value=_mock_response(_SAMPLE_EFTS_RESPONSE)):
                loader = GlobalFilingsLoader(providers=["sec_efts"])
                result = loader.fetch()
        assert len(result.records) == 2

    def test_records_have_advisory_stamps(self) -> None:
        with patch.dict(os.environ, {"SEC_USER_AGENT": "Test/1.0"}):
            with patch("requests.get", return_value=_mock_response(_SAMPLE_EFTS_RESPONSE)):
                loader = GlobalFilingsLoader(providers=["sec_efts"])
                result = loader.fetch()
        for rec in result.records:
            assert rec["advisory_status"] == "ADVISORY_ONLY"
            assert rec["human_review_required"] is True
            assert rec["execution_gate"] == "LOCKED"

    def test_records_have_correct_fields(self) -> None:
        with patch.dict(os.environ, {"SEC_USER_AGENT": "Test/1.0"}):
            with patch("requests.get", return_value=_mock_response(_SAMPLE_EFTS_RESPONSE)):
                loader = GlobalFilingsLoader(providers=["sec_efts"])
                result = loader.fetch()
        rec = result.records[0]
        assert "issuer_name" in rec
        assert "disclosure_type" in rec
        assert "jurisdiction" in rec
        assert "published_at" in rec
        assert rec["jurisdiction"] == "US"

    def test_user_agent_sent(self) -> None:
        agent = "MyApp/1.0 user@example.com"
        with patch.dict(os.environ, {"SEC_USER_AGENT": agent}):
            with patch("requests.get", return_value=_mock_response(_SAMPLE_EFTS_RESPONSE)) as mg:
                loader = GlobalFilingsLoader(providers=["sec_efts"])
                loader.fetch()
        _, kwargs = mg.call_args
        headers = kwargs.get("headers", {})
        assert headers.get("User-Agent") == agent

    def test_missing_sec_user_agent_skips(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SEC_USER_AGENT", None)
            loader = GlobalFilingsLoader(providers=["sec_efts"])
            result = loader.safe_fetch()
        assert result.skipped

    def test_date_range_params_sent(self) -> None:
        with patch.dict(os.environ, {"SEC_USER_AGENT": "Test/1.0"}):
            with patch("requests.get", return_value=_mock_response(_SAMPLE_EFTS_RESPONSE)) as mg:
                loader = GlobalFilingsLoader(providers=["sec_efts"])
                loader.fetch()
        _, kwargs = mg.call_args
        params = kwargs.get("params", {})
        assert "startdt" in params
        assert "enddt" in params

    def test_empty_hits_returns_empty_records(self) -> None:
        empty = {"hits": {"total": {"value": 0}, "hits": []}}
        with patch.dict(os.environ, {"SEC_USER_AGENT": "Test/1.0"}):
            with patch("requests.get", return_value=_mock_response(empty)):
                loader = GlobalFilingsLoader(providers=["sec_efts"])
                result = loader.fetch()
        assert result.records == []

    def test_api_error_skips(self) -> None:
        with patch.dict(os.environ, {"SEC_USER_AGENT": "Test/1.0"}):
            with patch("requests.get", side_effect=Exception("connection refused")):
                loader = GlobalFilingsLoader(providers=["sec_efts"])
                result = loader.safe_fetch()
        assert result.skipped

    def test_sec_efts_provider_label(self) -> None:
        with patch.dict(os.environ, {"SEC_USER_AGENT": "Test/1.0"}):
            with patch("requests.get", return_value=_mock_response(_SAMPLE_EFTS_RESPONSE)):
                loader = GlobalFilingsLoader(providers=["sec_efts"])
                result = loader.fetch()
        for rec in result.records:
            assert rec["provider"] == "sec_efts"


class TestGlobalFilingsQueryFilter:
    def test_query_filter_applied(self) -> None:
        with patch.dict(os.environ, {"SEC_USER_AGENT": "Test/1.0"}):
            with patch("requests.get", return_value=_mock_response(_SAMPLE_EFTS_RESPONSE)):
                # Filter for "apple" — should match first record only
                loader = GlobalFilingsLoader(providers=["sec_efts"], query="apple")
                result = loader.fetch()
        # At least one record should contain "apple" in searchable fields
        for rec in result.records:
            searchable = " ".join([
                rec.get("issuer_name", ""),
                rec.get("ticker_or_identifier", ""),
                rec.get("summary", ""),
                rec.get("disclosure_type", ""),
            ]).lower()
            assert "apple" in searchable


class TestGlobalFilingsRunnerIntegration:
    def test_run_phase2_global_filings_placeholder_when_no_sec_agent(self) -> None:
        from scripts.live_source_runner_phase2 import run_phase2
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SEC_USER_AGENT", None)
            report = run_phase2(dry_run=True, sources=["global_filings"])
        src = report.sources[0]
        assert src.status in ("placeholder", "skipped", "http_error")

    def test_run_phase2_global_filings_ok_with_mock(self) -> None:
        from scripts.live_source_runner_phase2 import run_phase2
        with patch.dict(os.environ, {"SEC_USER_AGENT": "Test/1.0"}):
            with patch("requests.get", return_value=_mock_response(_SAMPLE_EFTS_RESPONSE)):
                report = run_phase2(dry_run=True, sources=["global_filings"])
        src = report.sources[0]
        assert src.status == "ok"
        assert src.fetched_count > 0
