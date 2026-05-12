"""
Tests for SEC EDGAR loader — CIK validation, watchlist, mocked success, advisory contract.

All HTTP is mocked. No live network calls.
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.ingestion.sec_edgar_loader import (
    SECEdgarLoader,
    _validate_cik,
    _DEFAULT_WATCHLIST,
)
from scripts.ingestion.base_loader import SkipLoader, LoaderResult

REPO_ROOT = Path(__file__).resolve().parents[1]


def _mock_response(payload: object) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    resp.status_code = 200
    return resp


_SAMPLE_EDGAR_PAYLOAD = {
    "name": "APPLE INC",
    "entityType": "operating",
    "filings": {
        "recent": {
            "form": ["10-K", "10-Q", "8-K", "10-K"],
            "filingDate": ["2026-01-01", "2025-10-01", "2025-07-01", "2025-01-01"],
            "accessionNumber": [
                "0000320193-26-000001",
                "0000320193-25-000002",
                "0000320193-25-000003",
                "0000320193-25-000004",
            ],
        }
    },
}


class TestCIKValidation:
    def test_valid_numeric_cik(self) -> None:
        assert _validate_cik("0000320193") is None
        assert _validate_cik("320193") is None
        assert _validate_cik("1") is None

    def test_empty_cik_invalid(self) -> None:
        assert _validate_cik("") is not None
        assert _validate_cik("  ") is not None

    def test_alpha_cik_invalid(self) -> None:
        err = _validate_cik("AAPL")
        assert err is not None
        assert "malformed" in err.lower()

    def test_mixed_cik_invalid(self) -> None:
        err = _validate_cik("ABC123")
        assert err is not None

    def test_too_long_cik_invalid(self) -> None:
        err = _validate_cik("12345678901")  # 11 digits
        assert err is not None

    def test_exactly_ten_digits_valid(self) -> None:
        assert _validate_cik("0000320193") is None


class TestSECEdgarLoaderMissingKey:
    def test_skip_when_no_user_agent(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SEC_USER_AGENT", None)
            loader = SECEdgarLoader(cik="0000320193")
            with pytest.raises(SkipLoader) as exc_info:
                loader.fetch()
        assert "SEC_USER_AGENT" in str(exc_info.value)

    def test_safe_fetch_skipped_no_user_agent(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SEC_USER_AGENT", None)
            loader = SECEdgarLoader(cik="0000320193")
            result = loader.safe_fetch()
        assert result.skipped
        assert "SEC_USER_AGENT" in result.skip_reason


class TestSECEdgarLoaderNoCIK:
    def test_skip_when_no_cik_no_watchlist(self) -> None:
        with patch.dict(os.environ, {"SEC_USER_AGENT": "Test/1.0"}):
            loader = SECEdgarLoader()
            with pytest.raises(SkipLoader) as exc_info:
                loader.fetch()
        assert "cik" in str(exc_info.value).lower() or "watchlist" in str(exc_info.value).lower()

    def test_safe_fetch_skipped_no_cik(self) -> None:
        with patch.dict(os.environ, {"SEC_USER_AGENT": "Test/1.0"}):
            loader = SECEdgarLoader()
            result = loader.safe_fetch()
        assert result.skipped


class TestSECEdgarLoaderMalformedCIK:
    def test_malformed_cik_raises_skip(self) -> None:
        with patch.dict(os.environ, {"SEC_USER_AGENT": "Test/1.0"}):
            loader = SECEdgarLoader(cik="NOT-A-CIK")
            with pytest.raises(SkipLoader) as exc_info:
                loader.fetch()
        assert "invalid cik" in str(exc_info.value).lower()

    def test_alpha_cik_raises_skip(self) -> None:
        with patch.dict(os.environ, {"SEC_USER_AGENT": "Test/1.0"}):
            loader = SECEdgarLoader(cik="AAPL")
            with pytest.raises(SkipLoader):
                loader.fetch()


class TestSECEdgarLoaderSingleCIK:
    def test_fetch_returns_loader_result(self) -> None:
        with patch.dict(os.environ, {"SEC_USER_AGENT": "Test Agent/1.0"}):
            with patch("requests.get", return_value=_mock_response(_SAMPLE_EDGAR_PAYLOAD)):
                loader = SECEdgarLoader(cik="0000320193", form_type="10-K")
                result = loader.fetch()
        assert isinstance(result, LoaderResult)
        assert not result.skipped

    def test_fetch_filters_by_form_type(self) -> None:
        with patch.dict(os.environ, {"SEC_USER_AGENT": "Test Agent/1.0"}):
            with patch("requests.get", return_value=_mock_response(_SAMPLE_EDGAR_PAYLOAD)):
                loader = SECEdgarLoader(cik="0000320193", form_type="10-K")
                result = loader.fetch()
        for rec in result.records:
            assert rec["form_type"] == "10-K"

    def test_fetch_records_have_advisory_stamps(self) -> None:
        with patch.dict(os.environ, {"SEC_USER_AGENT": "Test Agent/1.0"}):
            with patch("requests.get", return_value=_mock_response(_SAMPLE_EDGAR_PAYLOAD)):
                loader = SECEdgarLoader(cik="0000320193")
                result = loader.fetch()
        for rec in result.records:
            assert rec["advisory_status"] == "ADVISORY_ONLY"
            assert rec["human_review_required"] is True
            assert rec["execution_gate"] == "LOCKED"

    def test_fetch_record_has_cik(self) -> None:
        with patch.dict(os.environ, {"SEC_USER_AGENT": "Test Agent/1.0"}):
            with patch("requests.get", return_value=_mock_response(_SAMPLE_EDGAR_PAYLOAD)):
                loader = SECEdgarLoader(cik="0000320193", form_type="10-K")
                result = loader.fetch()
        for rec in result.records:
            assert rec["cik"] == "0000320193"

    def test_fetch_record_has_entity_name(self) -> None:
        with patch.dict(os.environ, {"SEC_USER_AGENT": "Test Agent/1.0"}):
            with patch("requests.get", return_value=_mock_response(_SAMPLE_EDGAR_PAYLOAD)):
                loader = SECEdgarLoader(cik="0000320193", form_type="10-K")
                result = loader.fetch()
        assert result.records[0]["entity_name"] == "APPLE INC"

    def test_user_agent_header_sent(self) -> None:
        with patch.dict(os.environ, {"SEC_USER_AGENT": "MyApp/1.0 admin@example.com"}):
            with patch("requests.get", return_value=_mock_response(_SAMPLE_EDGAR_PAYLOAD)) as mock_get:
                loader = SECEdgarLoader(cik="0000320193", form_type="10-K")
                loader.fetch()
        _, kwargs = mock_get.call_args
        headers = kwargs.get("headers", {})
        assert headers.get("User-Agent") == "MyApp/1.0 admin@example.com"

    def test_url_uses_padded_cik(self) -> None:
        with patch.dict(os.environ, {"SEC_USER_AGENT": "Test/1.0"}):
            with patch("requests.get", return_value=_mock_response(_SAMPLE_EDGAR_PAYLOAD)) as mock_get:
                loader = SECEdgarLoader(cik="320193", form_type="10-K")
                loader.fetch()
        url_called = mock_get.call_args[0][0]
        assert "CIK0000320193" in url_called

    def test_max_filings_respected(self) -> None:
        with patch.dict(os.environ, {"SEC_USER_AGENT": "Test/1.0"}):
            with patch("requests.get", return_value=_mock_response(_SAMPLE_EDGAR_PAYLOAD)):
                loader = SECEdgarLoader(cik="0000320193", form_type="10-K", max_filings=1)
                result = loader.fetch()
        assert len(result.records) <= 1


class TestSECEdgarDefaultWatchlist:
    def test_watchlist_has_entries(self) -> None:
        assert len(_DEFAULT_WATCHLIST) >= 7

    def test_watchlist_mode_enabled(self) -> None:
        with patch.dict(os.environ, {"SEC_USER_AGENT": "Test/1.0"}):
            with patch("requests.get", return_value=_mock_response(_SAMPLE_EDGAR_PAYLOAD)):
                loader = SECEdgarLoader(use_default_watchlist=True, form_type="10-K")
                result = loader.fetch()
        assert isinstance(result, LoaderResult)
        assert not result.skipped
        # Should have results for each watchlist entry that returned filings
        assert len(result.records) > 0

    def test_watchlist_mode_iterates_multiple_ciks(self) -> None:
        call_count = {"n": 0}

        def mock_get(*args, **kwargs):
            call_count["n"] += 1
            return _mock_response(_SAMPLE_EDGAR_PAYLOAD)

        with patch.dict(os.environ, {"SEC_USER_AGENT": "Test/1.0"}):
            with patch("requests.get", side_effect=mock_get):
                loader = SECEdgarLoader(use_default_watchlist=True, form_type="10-K")
                loader.fetch()
        assert call_count["n"] == len(_DEFAULT_WATCHLIST)

    def test_watchlist_no_cik_no_flag_skips(self) -> None:
        with patch.dict(os.environ, {"SEC_USER_AGENT": "Test/1.0"}):
            loader = SECEdgarLoader()
            result = loader.safe_fetch()
        assert result.skipped

    def test_watchlist_cik_and_flag_uses_cik(self) -> None:
        """Explicit CIK takes precedence over watchlist flag."""
        with patch.dict(os.environ, {"SEC_USER_AGENT": "Test/1.0"}):
            with patch("requests.get", return_value=_mock_response(_SAMPLE_EDGAR_PAYLOAD)) as mg:
                loader = SECEdgarLoader(cik="0000320193", use_default_watchlist=True)
                loader.fetch()
        # Should make exactly one request (for the explicit CIK)
        assert mg.call_count == 1


class TestSECEdgarRunnerCLI:
    def test_phase1_runner_accepts_sec_cik(self) -> None:
        from scripts.run_live_sources_phase1 import _parse_args
        from unittest.mock import patch as up
        with up("sys.argv", ["prog", "--source", "sec_edgar", "--dry-run", "--sec-cik", "0000320193"]):
            args = _parse_args()
        assert args.sec_cik == "0000320193"

    def test_phase1_runner_accepts_default_watchlist(self) -> None:
        from scripts.run_live_sources_phase1 import _parse_args
        from unittest.mock import patch as up
        with up("sys.argv", ["prog", "--source", "sec_edgar", "--dry-run", "--sec-default-watchlist"]):
            args = _parse_args()
        assert args.sec_default_watchlist is True

    def test_phase1_runner_watchlist_default_false(self) -> None:
        from scripts.run_live_sources_phase1 import _parse_args
        from unittest.mock import patch as up
        with up("sys.argv", ["prog", "--write"]):
            args = _parse_args()
        assert args.sec_default_watchlist is False
