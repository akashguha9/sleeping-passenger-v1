"""
Tests for Phase C.7 — Global Filings / Disclosure source integration.

All HTTP calls are mocked — no live network requests.
"""
from __future__ import annotations

import ast
import importlib.util
import inspect
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.live_source_runner_phase2 import (
    Phase2RunReport,
    SourceRunResult,
    _normalize_global_filings_record,
    _stable_event_id,
    run_phase2,
)


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

def _asx_item(**kw):
    base = {
        "id": "00519786",
        "document_date": "2026-05-10",
        "issuer_code": "BHP",
        "issuer_short_name": "BHP Group Limited",
        "description": "Appendix 4C - Quarterly cash flow report",
        "url": "https://www.asx.com.au/asxpdf/20260510/pdf/test.pdf",
        "number_of_pages": 5,
    }
    base.update(kw)
    return base


def _mock_asx_response(items=None):
    if items is None:
        items = [_asx_item(), _asx_item(issuer_code="CBA", issuer_short_name="Commonwealth Bank", description="Appendix 4E")]
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = items
    mock.raise_for_status.return_value = None
    return mock


def _mock_asx_response_dict(items=None):
    """ASX response wrapped in a 'data' key."""
    if items is None:
        items = [_asx_item()]
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = {"data": items}
    mock.raise_for_status.return_value = None
    return mock


# ---------------------------------------------------------------------------
# Helper: a normalized record fixture
# ---------------------------------------------------------------------------

def _gf_rec(**kw):
    base = {
        "issuer_name": "BHP Group Limited",
        "ticker_or_identifier": "BHP",
        "exchange_or_regulator": "ASX",
        "jurisdiction": "AU",
        "disclosure_type": "company_announcement",
        "published_at": "2026-05-10",
        "url": "https://www.asx.com.au/asxpdf/20260510/pdf/test.pdf",
        "summary": "Appendix 4C - Quarterly cash flow report",
        "provider": "asx",
        "raw_payload": {"issuer_code": "BHP"},
        "advisory_status": "ADVISORY_ONLY",
        "human_review_required": True,
        "execution_gate": "LOCKED",
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# Normalization tests
# ---------------------------------------------------------------------------

class TestNormalizationGlobalFilings(unittest.TestCase):

    def test_event_id_stable(self):
        rec = _gf_rec()
        self.assertEqual(
            _normalize_global_filings_record(rec)["event_id"],
            _normalize_global_filings_record(rec)["event_id"],
        )

    def test_event_id_starts_with_global_filings(self):
        r = _normalize_global_filings_record(_gf_rec())
        self.assertTrue(r["event_id"].startswith("global_filings_"))

    def test_source_name(self):
        r = _normalize_global_filings_record(_gf_rec())
        self.assertEqual(r["source_name"], "global_filings")

    def test_signal_type(self):
        r = _normalize_global_filings_record(_gf_rec())
        self.assertEqual(r["signal_type"], "regulatory_disclosure")

    def test_title_includes_issuer_name(self):
        r = _normalize_global_filings_record(_gf_rec())
        self.assertIn("BHP Group Limited", r["title"])

    def test_title_includes_ticker(self):
        r = _normalize_global_filings_record(_gf_rec())
        self.assertIn("BHP", r["title"])

    def test_title_includes_disclosure_type(self):
        r = _normalize_global_filings_record(_gf_rec())
        self.assertIn("Company Announcement", r["title"])

    def test_title_fallback_no_issuer(self):
        r = _normalize_global_filings_record(_gf_rec(issuer_name="", ticker_or_identifier="", disclosure_type="", summary="Test Filing"))
        self.assertEqual(r["title"], "Test Filing")

    def test_title_ultimate_fallback(self):
        r = _normalize_global_filings_record(_gf_rec(issuer_name="", ticker_or_identifier="", disclosure_type="", summary=""))
        self.assertEqual(r["title"], "Global Regulatory Filing")

    def test_issuer_name_preserved(self):
        r = _normalize_global_filings_record(_gf_rec())
        self.assertEqual(r["issuer_name"], "BHP Group Limited")

    def test_ticker_preserved(self):
        r = _normalize_global_filings_record(_gf_rec())
        self.assertEqual(r["ticker_or_identifier"], "BHP")

    def test_exchange_or_regulator_preserved(self):
        r = _normalize_global_filings_record(_gf_rec())
        self.assertEqual(r["exchange_or_regulator"], "ASX")

    def test_jurisdiction_preserved(self):
        r = _normalize_global_filings_record(_gf_rec())
        self.assertEqual(r["jurisdiction"], "AU")

    def test_disclosure_type_preserved(self):
        r = _normalize_global_filings_record(_gf_rec())
        self.assertEqual(r["disclosure_type"], "company_announcement")

    def test_published_at_preserved(self):
        r = _normalize_global_filings_record(_gf_rec())
        self.assertEqual(r["published_at"], "2026-05-10")

    def test_url_preserved(self):
        r = _normalize_global_filings_record(_gf_rec())
        self.assertIn("asx.com.au", r["url"])

    def test_summary_preserved(self):
        r = _normalize_global_filings_record(_gf_rec())
        self.assertIn("Appendix 4C", r["summary"])

    def test_provider_preserved(self):
        r = _normalize_global_filings_record(_gf_rec())
        self.assertEqual(r["provider"], "asx")

    def test_raw_payload_preserved(self):
        payload = {"issuer_code": "BHP", "extra": "data"}
        r = _normalize_global_filings_record(_gf_rec(raw_payload=payload))
        self.assertEqual(r["raw_payload"]["issuer_code"], "BHP")

    def test_raw_payload_none_becomes_empty_dict(self):
        r = _normalize_global_filings_record(_gf_rec(raw_payload=None))
        self.assertIsInstance(r["raw_payload"], dict)

    def test_advisory_status(self):
        r = _normalize_global_filings_record(_gf_rec())
        self.assertEqual(r["advisory_status"], "ADVISORY_ONLY")

    def test_human_review_required(self):
        r = _normalize_global_filings_record(_gf_rec())
        self.assertTrue(r["human_review_required"])

    def test_execution_gate_locked(self):
        r = _normalize_global_filings_record(_gf_rec())
        self.assertEqual(r["execution_gate"], "LOCKED")

    def test_ai_execution_count_zero(self):
        r = _normalize_global_filings_record(_gf_rec())
        self.assertEqual(r["ai_execution_count"], 0)

    def test_broker_api_called_false(self):
        r = _normalize_global_filings_record(_gf_rec())
        self.assertFalse(r["broker_api_called"])

    def test_broker_order_id_none_string(self):
        r = _normalize_global_filings_record(_gf_rec())
        self.assertEqual(r["broker_order_id"], "NONE")

    def test_different_tickers_different_event_ids(self):
        r1 = _normalize_global_filings_record(_gf_rec(ticker_or_identifier="BHP"))
        r2 = _normalize_global_filings_record(_gf_rec(ticker_or_identifier="CBA"))
        self.assertNotEqual(r1["event_id"], r2["event_id"])

    def test_different_providers_different_event_ids(self):
        r1 = _normalize_global_filings_record(_gf_rec(provider="asx"))
        r2 = _normalize_global_filings_record(_gf_rec(provider="hkex"))
        self.assertNotEqual(r1["event_id"], r2["event_id"])

    def test_default_provider_when_missing(self):
        rec = _gf_rec()
        del rec["provider"]
        r = _normalize_global_filings_record(rec)
        self.assertEqual(r["provider"], "global_filings")


# ---------------------------------------------------------------------------
# Loader init tests
# ---------------------------------------------------------------------------

class TestGlobalFilingsLoaderInit(unittest.TestCase):

    def _loader(self):
        from scripts.ingestion.global_filings_loader import GlobalFilingsLoader
        return GlobalFilingsLoader

    def test_source_name(self):
        self.assertEqual(self._loader().source_name, "global_filings")

    def test_requires_key_false(self):
        self.assertFalse(self._loader().requires_key)

    def test_default_providers_none(self):
        loader = self._loader()()
        self.assertIsNone(loader._providers)

    def test_default_query_none(self):
        loader = self._loader()()
        self.assertIsNone(loader._query)

    def test_default_region_none(self):
        loader = self._loader()()
        self.assertIsNone(loader._region)

    def test_default_max_items(self):
        loader = self._loader()()
        self.assertEqual(loader._max_items, 50)

    def test_custom_params_stored(self):
        loader = self._loader()(
            providers=["asx"],
            query="quarterly",
            region="AU",
            max_items=10,
        )
        self.assertEqual(loader._providers, ["asx"])
        self.assertEqual(loader._query, "quarterly")
        self.assertEqual(loader._region, "AU")
        self.assertEqual(loader._max_items, 10)

    def test_query_lowercased(self):
        loader = self._loader()(query="BHP Quarterly")
        self.assertEqual(loader._query, "bhp quarterly")

    def test_region_uppercased(self):
        loader = self._loader()(region="au")
        self.assertEqual(loader._region, "AU")

    def test_empty_query_becomes_none(self):
        loader = self._loader()(query="   ")
        self.assertIsNone(loader._query)


# ---------------------------------------------------------------------------
# Missing requests library
# ---------------------------------------------------------------------------

class TestGlobalFilingsLoaderMissingRequests(unittest.TestCase):

    def test_skips_when_requests_missing(self):
        import scripts.ingestion.global_filings_loader as _gf_mod
        from scripts.ingestion.global_filings_loader import GlobalFilingsLoader
        loader = GlobalFilingsLoader(providers=["asx"])
        with patch.dict(_gf_mod._PROVIDER_CONFIGS["asx"], {"active": True}):
            with patch.dict(sys.modules, {"requests": None}):
                result = loader.safe_fetch()
        self.assertTrue(result.skipped)
        self.assertIn("requests", result.skip_reason.lower())

    def test_skip_reason_non_empty(self):
        import scripts.ingestion.global_filings_loader as _gf_mod
        from scripts.ingestion.global_filings_loader import GlobalFilingsLoader
        loader = GlobalFilingsLoader(providers=["asx"])
        with patch.dict(_gf_mod._PROVIDER_CONFIGS["asx"], {"active": True}):
            with patch.dict(sys.modules, {"requests": None}):
                result = loader.safe_fetch()
        self.assertGreater(len(result.skip_reason), 0)


# ---------------------------------------------------------------------------
# Provider skip tests
# ---------------------------------------------------------------------------

class TestProviderSkips(unittest.TestCase):

    def _loader(self, **kw):
        from scripts.ingestion.global_filings_loader import GlobalFilingsLoader
        return GlobalFilingsLoader(**kw)

    def test_inactive_provider_hkex_skips(self):
        loader = self._loader(providers=["hkex"])
        result = loader.safe_fetch()
        self.assertTrue(result.skipped)
        self.assertIn("placeholder", result.skip_reason.lower())

    def test_unknown_provider_skips(self):
        loader = self._loader(providers=["nonexistent_exchange"])
        result = loader.safe_fetch()
        self.assertTrue(result.skipped)

    def test_empty_provider_list_skips(self):
        # providers=[] means _select_providers returns [] → SkipLoader
        loader = self._loader(providers=[])
        result = loader.safe_fetch()
        self.assertTrue(result.skipped)

    def test_sgx_placeholder_skips(self):
        loader = self._loader(providers=["sgx"])
        result = loader.safe_fetch()
        self.assertTrue(result.skipped)

    def test_unknown_region_skips(self):
        loader = self._loader(region="XX")
        result = loader.safe_fetch()
        self.assertTrue(result.skipped)

    def test_all_placeholder_region_skips(self):
        # JP → tdnet (inactive); AU → asx (now inactive too)
        for region in ("JP", "AU"):
            loader = self._loader(region=region)
            result = loader.safe_fetch()
            self.assertTrue(result.skipped, f"Expected skipped for region={region}")


# ---------------------------------------------------------------------------
# Mocked HTTP tests
# ---------------------------------------------------------------------------

class TestGlobalFilingsLoaderMockedHTTP(unittest.TestCase):
    """Tests for GlobalFilingsLoader with mocked HTTP.

    ASX is marked inactive in production (endpoint returns 404).
    Tests that exercise the HTTP path temporarily re-enable it via patch.dict,
    providing a mock URL so the fetch code can proceed to the HTTP call.
    sec_efts is disabled in these tests to isolate ASX behaviour.
    """

    def _run(self, side_effects, **loader_kw):
        import scripts.ingestion.global_filings_loader as _gf_mod
        from scripts.ingestion.global_filings_loader import GlobalFilingsLoader
        loader = GlobalFilingsLoader(**loader_kw)
        with patch.dict(_gf_mod._PROVIDER_CONFIGS["asx"], {"active": True, "url": "https://mock.asx.test/"}):
            with patch.dict(_gf_mod._PROVIDER_CONFIGS["sec_efts"], {"active": False}):
                with patch("requests.get", side_effect=side_effects):
                    return loader.safe_fetch()

    def test_successful_fetch_returns_records(self):
        result = self._run([_mock_asx_response()], providers=["asx"])
        self.assertFalse(result.skipped)
        self.assertGreater(len(result.records), 0)

    def test_source_name_on_result(self):
        result = self._run([_mock_asx_response()], providers=["asx"])
        self.assertEqual(result.source_name, "global_filings")

    def test_records_have_issuer_name(self):
        result = self._run([_mock_asx_response()], providers=["asx"])
        for rec in result.records:
            self.assertIn("issuer_name", rec)

    def test_records_have_ticker(self):
        result = self._run([_mock_asx_response()], providers=["asx"])
        for rec in result.records:
            self.assertIn("ticker_or_identifier", rec)

    def test_records_have_jurisdiction(self):
        result = self._run([_mock_asx_response()], providers=["asx"])
        for rec in result.records:
            self.assertEqual(rec.get("jurisdiction"), "AU")

    def test_records_have_exchange(self):
        result = self._run([_mock_asx_response()], providers=["asx"])
        for rec in result.records:
            self.assertEqual(rec.get("exchange_or_regulator"), "ASX")

    def test_advisory_stamps_on_all_records(self):
        result = self._run([_mock_asx_response()], providers=["asx"])
        for rec in result.records:
            self.assertEqual(rec.get("advisory_status"), "ADVISORY_ONLY")
            self.assertTrue(rec.get("human_review_required"))
            self.assertEqual(rec.get("execution_gate"), "LOCKED")

    def test_provider_field_on_records(self):
        result = self._run([_mock_asx_response()], providers=["asx"])
        for rec in result.records:
            self.assertEqual(rec.get("provider"), "asx")

    def test_raw_payload_on_records(self):
        result = self._run([_mock_asx_response()], providers=["asx"])
        for rec in result.records:
            self.assertIn("raw_payload", rec)
            self.assertIsInstance(rec["raw_payload"], dict)

    def test_response_as_dict_with_data_key(self):
        result = self._run([_mock_asx_response_dict()], providers=["asx"])
        self.assertFalse(result.skipped)
        self.assertEqual(len(result.records), 1)

    def test_response_as_list_directly(self):
        result = self._run([_mock_asx_response()], providers=["asx"])
        self.assertFalse(result.skipped)
        self.assertEqual(len(result.records), 2)

    def test_max_items_respected(self):
        many_items = [_asx_item(issuer_code=f"CO{i}") for i in range(30)]
        result = self._run([_mock_asx_response(many_items)], providers=["asx"], max_items=5)
        self.assertLessEqual(len(result.records), 5)

    def test_query_filter_matches(self):
        result = self._run([_mock_asx_response()], providers=["asx"], query="bhp")
        self.assertFalse(result.skipped)
        matched = [r for r in result.records if "bhp" in r.get("issuer_name", "").lower()]
        self.assertGreater(len(matched), 0)

    def test_query_filter_no_match_returns_empty(self):
        result = self._run([_mock_asx_response()], providers=["asx"], query="ZZNOTFOUND123")
        self.assertFalse(result.skipped)
        self.assertEqual(len(result.records), 0)

    def test_region_au_selects_asx(self):
        result = self._run([_mock_asx_response()], region="AU")
        self.assertFalse(result.skipped)

    def test_network_error_loader_skips(self):
        import scripts.ingestion.global_filings_loader as _gf_mod
        from scripts.ingestion.global_filings_loader import GlobalFilingsLoader
        loader = GlobalFilingsLoader(providers=["asx"])
        with patch.dict(_gf_mod._PROVIDER_CONFIGS["asx"], {"active": True}):
            with patch("requests.get", side_effect=Exception("network down")):
                result = loader.safe_fetch()
        self.assertTrue(result.skipped)
        self.assertIn("unreachable", result.skip_reason.lower())

    def test_http_error_loader_skips(self):
        import scripts.ingestion.global_filings_loader as _gf_mod
        from scripts.ingestion.global_filings_loader import GlobalFilingsLoader
        loader = GlobalFilingsLoader(providers=["asx"])
        err_mock = MagicMock()
        err_mock.raise_for_status.side_effect = Exception("HTTP 503")
        with patch.dict(_gf_mod._PROVIDER_CONFIGS["asx"], {"active": True}):
            with patch("requests.get", return_value=err_mock):
                result = loader.safe_fetch()
        self.assertTrue(result.skipped)

    def test_issuer_name_from_issuer_short_name(self):
        item = _asx_item(issuer_short_name="Rio Tinto", issuer_code="RIO")
        result = self._run([_mock_asx_response([item])], providers=["asx"])
        rec = result.records[0]
        self.assertEqual(rec["issuer_name"], "Rio Tinto")

    def test_ticker_from_issuer_code(self):
        item = _asx_item(issuer_code="RIO")
        result = self._run([_mock_asx_response([item])], providers=["asx"])
        rec = result.records[0]
        self.assertEqual(rec["ticker_or_identifier"], "RIO")

    def test_summary_from_description(self):
        item = _asx_item(description="Half-year results announcement")
        result = self._run([_mock_asx_response([item])], providers=["asx"])
        rec = result.records[0]
        self.assertEqual(rec["summary"], "Half-year results announcement")

    def test_url_from_url_field(self):
        item = _asx_item(url="https://www.asx.com.au/asxpdf/test.pdf")
        result = self._run([_mock_asx_response([item])], providers=["asx"])
        rec = result.records[0]
        self.assertIn("asx.com.au", rec["url"])

    def test_published_at_from_document_date(self):
        item = _asx_item(document_date="2026-05-10")
        result = self._run([_mock_asx_response([item])], providers=["asx"])
        rec = result.records[0]
        self.assertEqual(rec["published_at"], "2026-05-10")

    def test_non_dict_items_skipped(self):
        mock = MagicMock()
        mock.status_code = 200
        mock.json.return_value = ["not_a_dict", 42, None]
        mock.raise_for_status.return_value = None
        result = self._run([mock], providers=["asx"])
        self.assertFalse(result.skipped)
        self.assertEqual(len(result.records), 0)

    def test_empty_items_list_no_crash(self):
        mock = MagicMock()
        mock.status_code = 200
        mock.json.return_value = []
        mock.raise_for_status.return_value = None
        result = self._run([mock], providers=["asx"])
        self.assertFalse(result.skipped)
        self.assertEqual(len(result.records), 0)

    def test_two_items_two_records(self):
        items = [_asx_item(issuer_code="BHP"), _asx_item(issuer_code="CBA")]
        result = self._run([_mock_asx_response(items)], providers=["asx"])
        self.assertEqual(len(result.records), 2)

    def test_alternate_field_names_title(self):
        item = {"title": "Some announcement", "symbol": "XYZ", "link": "http://example.com"}
        mock = MagicMock()
        mock.status_code = 200
        mock.json.return_value = [item]
        mock.raise_for_status.return_value = None
        result = self._run([mock], providers=["asx"])
        self.assertFalse(result.skipped)
        rec = result.records[0]
        self.assertEqual(rec["summary"], "Some announcement")
        self.assertEqual(rec["ticker_or_identifier"], "XYZ")
        self.assertEqual(rec["url"], "http://example.com")


# ---------------------------------------------------------------------------
# Phase 2 runner integration
# ---------------------------------------------------------------------------

class TestPhase2RunnerGlobalFilings(unittest.TestCase):
    """Phase 2 runner tests for global_filings.

    ASX is inactive in production.  Tests that need a working provider
    temporarily reactivate ASX via patch.dict with a mock URL.
    sec_efts is disabled to isolate ASX behaviour.
    """

    def _run(self, dry_run=True, **kw):
        import scripts.ingestion.global_filings_loader as _gf_mod
        with patch.dict(_gf_mod._PROVIDER_CONFIGS["asx"], {"active": True, "url": "https://mock.asx.test/"}):
            with patch.dict(_gf_mod._PROVIDER_CONFIGS["sec_efts"], {"active": False}):
                with patch("requests.get", return_value=_mock_asx_response()):
                    return run_phase2(dry_run=dry_run, sources=["global_filings"], **kw)

    def test_returns_phase2_run_report(self):
        self.assertIsInstance(self._run(), Phase2RunReport)

    def test_report_has_global_filings_source(self):
        report = self._run()
        names = [s.source_name for s in report.sources]
        self.assertIn("global_filings", names)

    def test_status_ok(self):
        report = self._run()
        gf = next(s for s in report.sources if s.source_name == "global_filings")
        self.assertEqual(gf.status, "ok")

    def test_fetched_count_nonzero(self):
        report = self._run()
        gf = next(s for s in report.sources if s.source_name == "global_filings")
        self.assertGreater(gf.fetched_count, 0)

    def test_dry_run_no_persist(self):
        report = self._run(dry_run=True)
        self.assertEqual(report.total_persisted, 0)

    def test_dry_run_flag_on_report(self):
        report = self._run(dry_run=True)
        self.assertTrue(report.dry_run)

    def test_advisory_status_on_report(self):
        self.assertEqual(self._run().advisory_status, "ADVISORY_ONLY")

    def test_broker_api_false_on_report(self):
        self.assertFalse(self._run().broker_api_called)

    def test_ai_execution_zero_on_report(self):
        self.assertEqual(self._run().ai_execution_count, 0)

    def test_execution_gate_locked(self):
        self.assertEqual(self._run().execution_gate, "LOCKED")

    def test_human_review_required(self):
        self.assertTrue(self._run().human_review_required)

    def test_to_dict_json_serializable(self):
        d = self._run().to_dict()
        json.dumps(d)

    def test_skipped_when_no_active_providers(self):
        # All providers inactive (ASX now inactive) → non-ok status
        import scripts.ingestion.global_filings_loader as _gf_mod
        with patch.dict(_gf_mod._PROVIDER_CONFIGS["sec_efts"], {"active": False}):
            report = run_phase2(dry_run=True, sources=["global_filings"])
        gf = next(s for s in report.sources if s.source_name == "global_filings")
        self.assertIn(gf.status, ("skipped", "placeholder", "http_error"))

    def test_unknown_source_ignored(self):
        report = self._run()
        names = [s.source_name for s in report.sources]
        self.assertIn("global_filings", names)

    def test_global_provider_param_passed(self):
        import scripts.ingestion.global_filings_loader as _gf_mod
        with patch.dict(_gf_mod._PROVIDER_CONFIGS["asx"], {"active": True, "url": "https://mock.asx.test/"}):
            with patch("requests.get", return_value=_mock_asx_response()):
                report = run_phase2(
                    dry_run=True,
                    sources=["global_filings"],
                    global_filings_providers=["asx"],
                )
        gf = next(s for s in report.sources if s.source_name == "global_filings")
        self.assertEqual(gf.status, "ok")

    def test_global_region_param_passed(self):
        import scripts.ingestion.global_filings_loader as _gf_mod
        with patch.dict(_gf_mod._PROVIDER_CONFIGS["asx"], {"active": True, "url": "https://mock.asx.test/"}):
            with patch("requests.get", return_value=_mock_asx_response()):
                report = run_phase2(
                    dry_run=True,
                    sources=["global_filings"],
                    global_filings_region="AU",
                )
        gf = next(s for s in report.sources if s.source_name == "global_filings")
        self.assertIn(gf.status, {"ok", "skipped", "placeholder"})

    def test_global_max_items_param(self):
        import scripts.ingestion.global_filings_loader as _gf_mod
        with patch.dict(_gf_mod._PROVIDER_CONFIGS["asx"], {"active": True}):
            with patch("requests.get", return_value=_mock_asx_response()):
                report = run_phase2(
                    dry_run=True,
                    sources=["global_filings"],
                    global_filings_max_items=1,
                )
        gf = next(s for s in report.sources if s.source_name == "global_filings")
        self.assertLessEqual(gf.fetched_count, 1)

    def test_duration_ms_set(self):
        report = self._run()
        gf = next(s for s in report.sources if s.source_name == "global_filings")
        self.assertGreaterEqual(gf.duration_ms, 0)

    def test_run_at_set(self):
        report = self._run()
        self.assertGreater(len(report.run_at), 0)


# ---------------------------------------------------------------------------
# Write mode
# ---------------------------------------------------------------------------

class TestGlobalFilingsWriteMode(unittest.TestCase):

    def _with_active_asx(self):
        import scripts.ingestion.global_filings_loader as _gf_mod
        from contextlib import ExitStack
        stack = ExitStack()
        stack.enter_context(patch.dict(_gf_mod._PROVIDER_CONFIGS["asx"], {"active": True, "url": "https://mock.asx.test/"}))
        stack.enter_context(patch.dict(_gf_mod._PROVIDER_CONFIGS["sec_efts"], {"active": False}))
        return stack

    def test_write_mode_calls_persist(self):
        with self._with_active_asx():
            with patch("requests.get", return_value=_mock_asx_response()):
                with patch("scripts.live_source_runner_phase2._persist_events", return_value=2) as mock_p:
                    with patch("scripts.live_source_runner_phase2._log_run") as mock_l:
                        report = run_phase2(dry_run=False, sources=["global_filings"])
        mock_p.assert_called_once()
        mock_l.assert_called_once()
        gf = next(s for s in report.sources if s.source_name == "global_filings")
        self.assertEqual(gf.events_persisted, 2)

    def test_dry_run_does_not_call_persist(self):
        with self._with_active_asx():
            with patch("requests.get", return_value=_mock_asx_response()):
                with patch("scripts.live_source_runner_phase2._persist_events") as mock_p:
                    run_phase2(dry_run=True, sources=["global_filings"])
        mock_p.assert_not_called()

    def test_dry_run_does_not_call_log_run(self):
        with self._with_active_asx():
            with patch("requests.get", return_value=_mock_asx_response()):
                with patch("scripts.live_source_runner_phase2._log_run") as mock_l:
                    run_phase2(dry_run=True, sources=["global_filings"])
        mock_l.assert_not_called()

    def test_write_mode_placeholder_source_still_logged(self):
        # When all providers are inactive, still logs the run
        with patch("scripts.live_source_runner_phase2._log_run") as mock_l:
            run_phase2(dry_run=False, sources=["global_filings"])
        mock_l.assert_called_once()


# ---------------------------------------------------------------------------
# Safety invariants
# ---------------------------------------------------------------------------

class TestGlobalFilingsSafetyInvariants(unittest.TestCase):

    def _records(self):
        recs = [
            _gf_rec(ticker_or_identifier="BHP", issuer_name="BHP Group Limited"),
            _gf_rec(ticker_or_identifier="CBA", issuer_name="Commonwealth Bank", provider="asx"),
            _gf_rec(ticker_or_identifier="RIO", issuer_name="Rio Tinto Limited", jurisdiction="AU"),
        ]
        return [_normalize_global_filings_record(r) for r in recs]

    def test_all_advisory_only(self):
        for r in self._records():
            self.assertEqual(r["advisory_status"], "ADVISORY_ONLY")

    def test_all_human_review_required(self):
        for r in self._records():
            self.assertTrue(r["human_review_required"])

    def test_all_execution_gate_locked(self):
        for r in self._records():
            self.assertEqual(r["execution_gate"], "LOCKED")

    def test_all_ai_execution_zero(self):
        for r in self._records():
            self.assertEqual(r["ai_execution_count"], 0)

    def test_all_broker_api_false(self):
        for r in self._records():
            self.assertFalse(r["broker_api_called"])

    def test_all_broker_order_id_none_string(self):
        for r in self._records():
            self.assertEqual(r["broker_order_id"], "NONE")

    def test_source_name_always_global_filings(self):
        for r in self._records():
            self.assertEqual(r["source_name"], "global_filings")

    def test_no_order_keys(self):
        forbidden = {"order_id", "trade_id", "broker_order", "execution_id", "fill_price"}
        for r in self._records():
            self.assertEqual(set(r.keys()) & forbidden, set())

    def _run_report(self):
        import scripts.ingestion.global_filings_loader as _gf_mod
        with patch.dict(_gf_mod._PROVIDER_CONFIGS["asx"], {"active": True}):
            with patch("requests.get", return_value=_mock_asx_response()):
                return run_phase2(dry_run=True, sources=["global_filings"])

    def test_phase2_report_advisory_only(self):
        report = self._run_report()
        self.assertEqual(report.advisory_status, "ADVISORY_ONLY")

    def test_phase2_report_broker_false(self):
        report = self._run_report()
        self.assertFalse(report.broker_api_called)

    def test_phase2_report_ai_zero(self):
        report = self._run_report()
        self.assertEqual(report.ai_execution_count, 0)


# ---------------------------------------------------------------------------
# AST — forbidden method check
# ---------------------------------------------------------------------------

class TestGlobalFilingsNoForbiddenMethods(unittest.TestCase):

    _FORBIDDEN = {
        "place_order", "submit_order", "create_order",
        "send_order", "execute_trade", "buy", "sell",
        "transfer", "send_transaction", "sign_transaction",
        "broadcast_transaction",
    }

    def _attr_calls(self, path: Path) -> set[str]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        return {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }

    def test_global_filings_loader_no_forbidden_methods(self):
        found = (
            self._attr_calls(_REPO_ROOT / "scripts" / "ingestion" / "global_filings_loader.py")
            & self._FORBIDDEN
        )
        self.assertEqual(found, set(), f"Forbidden methods found: {found}")

    def test_runner_no_forbidden_methods(self):
        found = (
            self._attr_calls(_REPO_ROOT / "scripts" / "live_source_runner_phase2.py")
            & self._FORBIDDEN
        )
        self.assertEqual(found, set(), f"Forbidden methods found: {found}")

    def test_cli_no_forbidden_methods(self):
        found = (
            self._attr_calls(_REPO_ROOT / "scripts" / "run_live_sources_phase2.py")
            & self._FORBIDDEN
        )
        self.assertEqual(found, set(), f"Forbidden methods found: {found}")


# ---------------------------------------------------------------------------
# CLI / module structure
# ---------------------------------------------------------------------------

class TestGlobalFilingsCLIStructure(unittest.TestCase):

    def _load_cli_module(self):
        path = _REPO_ROOT / "scripts" / "run_live_sources_phase2.py"
        spec = importlib.util.spec_from_file_location("run_live_sources_phase2", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_global_filings_in_supported_sources(self):
        mod = self._load_cli_module()
        self.assertIn("global_filings", mod._SUPPORTED_SOURCES)

    def test_run_phase2_has_global_filings_providers_param(self):
        sig = inspect.signature(run_phase2)
        self.assertIn("global_filings_providers", sig.parameters)

    def test_run_phase2_has_global_filings_query_param(self):
        sig = inspect.signature(run_phase2)
        self.assertIn("global_filings_query", sig.parameters)

    def test_run_phase2_has_global_filings_region_param(self):
        sig = inspect.signature(run_phase2)
        self.assertIn("global_filings_region", sig.parameters)

    def test_run_phase2_has_global_filings_max_items_param(self):
        sig = inspect.signature(run_phase2)
        self.assertIn("global_filings_max_items", sig.parameters)

    def test_normalize_global_filings_record_exported(self):
        from scripts.live_source_runner_phase2 import __all__
        self.assertIn("_normalize_global_filings_record", __all__)

    def test_global_filings_loader_importable(self):
        from scripts.ingestion.global_filings_loader import GlobalFilingsLoader
        self.assertIsNotNone(GlobalFilingsLoader)

    def test_run_phase2_dry_run_mocked(self):
        import scripts.ingestion.global_filings_loader as _gf_mod
        with patch.dict(_gf_mod._PROVIDER_CONFIGS["asx"], {"active": True, "url": "https://mock.asx.test/"}):
            with patch("requests.get", return_value=_mock_asx_response()):
                report = run_phase2(
                    dry_run=True,
                    sources=["global_filings"],
                    global_filings_providers=["asx"],
                    global_filings_query=None,
                    global_filings_region=None,
                    global_filings_max_items=10,
                )
        self.assertIsInstance(report, Phase2RunReport)
        gf = next(s for s in report.sources if s.source_name == "global_filings")
        self.assertIn(gf.status, {"ok", "skipped", "placeholder"})

    def test_report_to_dict_has_required_keys(self):
        with patch("requests.get", return_value=_mock_asx_response()):
            report = run_phase2(dry_run=True, sources=["global_filings"])
        d = report.to_dict()
        self.assertIn("sources", d)
        self.assertIn("advisory_status", d)
        self.assertIn("broker_api_called", d)
        self.assertIn("ai_execution_count", d)

    def test_provider_configs_has_asx(self):
        from scripts.ingestion.global_filings_loader import _PROVIDER_CONFIGS
        self.assertIn("asx", _PROVIDER_CONFIGS)
        # ASX is present but inactive — endpoint returns 404 (marked as placeholder)
        self.assertIn("asx", _PROVIDER_CONFIGS)

    def test_provider_configs_placeholders_inactive(self):
        from scripts.ingestion.global_filings_loader import _PROVIDER_CONFIGS
        # All providers are now inactive (ASX endpoint returns 404)
        for name in ["asx", "hkex", "sgx", "uk_rns", "esma", "sedar", "tdnet"]:
            self.assertFalse(
                _PROVIDER_CONFIGS[name]["active"],
                f"{name} should be inactive (placeholder)",
            )


if __name__ == "__main__":
    unittest.main()
