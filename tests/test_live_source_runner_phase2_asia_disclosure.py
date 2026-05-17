"""
Tests for Phase C.8 — Asia Disclosure source integration.

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
    _normalize_asia_disclosure_record,
    _stable_event_id,
    run_phase2,
)
from scripts.ingestion.base_loader import LoaderResult


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

def _asia_item(**kw):
    base = {
        "issuer_name": "Tencent Holdings",
        "ticker": "0700",
        "title": "Annual Results Announcement",
        "description": "Tencent Holdings annual results for fiscal year 2026",
        "url": "https://www.hkex.com.hk/announcements/tencent_ar_2026.pdf",
        "published_at": "2026-05-10",
        "language": "en",
    }
    base.update(kw)
    return base


def _mock_asia_response(items=None):
    if items is None:
        items = [
            _asia_item(),
            _asia_item(
                issuer_name="Alibaba Group",
                ticker="9988",
                title="Quarterly Disclosure",
                url="https://www.hkex.com.hk/announcements/alibaba_q1_2026.pdf",
            ),
        ]
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = items
    mock.raise_for_status.return_value = None
    return mock


def _mock_asia_response_dict(items=None):
    if items is None:
        items = [_asia_item()]
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = {"data": items}
    mock.raise_for_status.return_value = None
    return mock


def _mock_loader_result(records=None):
    """Return a successful LoaderResult with mock asia_disclosure records."""
    if records is None:
        rec = {
            "issuer_name": "Tencent Holdings",
            "ticker_or_identifier": "0700",
            "exchange_or_regulator": "HKEX",
            "jurisdiction": "HK",
            "disclosure_type": "regulatory_disclosure",
            "published_at": "2026-05-10",
            "url": "https://www.hkex.com.hk/announcements/tencent_ar_2026.pdf",
            "title": "Annual Results Announcement",
            "summary": "Tencent Holdings annual results for fiscal year 2026",
            "provider": "hkex",
            "language": "en",
            "raw_payload": {"issuer_name": "Tencent Holdings"},
            "advisory_status": "ADVISORY_ONLY",
            "human_review_required": True,
            "execution_gate": "LOCKED",
        }
        records = [rec]
    return LoaderResult(source_name="asia_disclosure", records=records)


# ---------------------------------------------------------------------------
# Normalized record fixture
# ---------------------------------------------------------------------------

def _asia_rec(**kw):
    base = {
        "issuer_name": "Tencent Holdings",
        "ticker_or_identifier": "0700",
        "exchange_or_regulator": "HKEX",
        "jurisdiction": "HK",
        "disclosure_type": "regulatory_disclosure",
        "published_at": "2026-05-10",
        "url": "https://www.hkex.com.hk/announcements/tencent_ar_2026.pdf",
        "title": "Annual Results Announcement",
        "summary": "Tencent Holdings annual results for fiscal year 2026",
        "provider": "hkex",
        "language": "en",
        "raw_payload": {"issuer_name": "Tencent Holdings"},
        "advisory_status": "ADVISORY_ONLY",
        "human_review_required": True,
        "execution_gate": "LOCKED",
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# Normalization tests
# ---------------------------------------------------------------------------

class TestNormalizationAsiaDisclosure(unittest.TestCase):

    def test_event_id_stable(self):
        rec = _asia_rec()
        self.assertEqual(
            _normalize_asia_disclosure_record(rec)["event_id"],
            _normalize_asia_disclosure_record(rec)["event_id"],
        )

    def test_event_id_starts_with_asia_disclosure(self):
        r = _normalize_asia_disclosure_record(_asia_rec())
        self.assertTrue(r["event_id"].startswith("asia_disclosure_"))

    def test_source_name(self):
        r = _normalize_asia_disclosure_record(_asia_rec())
        self.assertEqual(r["source_name"], "asia_disclosure")

    def test_signal_type(self):
        r = _normalize_asia_disclosure_record(_asia_rec())
        self.assertEqual(r["signal_type"], "asia_regulatory_disclosure")

    def test_title_includes_issuer_name(self):
        r = _normalize_asia_disclosure_record(_asia_rec())
        self.assertIn("Tencent Holdings", r["title"])

    def test_title_includes_ticker(self):
        r = _normalize_asia_disclosure_record(_asia_rec())
        self.assertIn("0700", r["title"])

    def test_title_includes_disclosure_type(self):
        r = _normalize_asia_disclosure_record(_asia_rec())
        self.assertIn("Regulatory Disclosure", r["title"])

    def test_title_fallback_to_title_raw(self):
        r = _normalize_asia_disclosure_record(_asia_rec(
            issuer_name="", ticker_or_identifier="", disclosure_type="",
            title="Some Asia Announcement", summary="",
        ))
        self.assertEqual(r["title"], "Some Asia Announcement")

    def test_title_fallback_to_summary(self):
        r = _normalize_asia_disclosure_record(_asia_rec(
            issuer_name="", ticker_or_identifier="", disclosure_type="",
            title="", summary="Quarterly summary",
        ))
        self.assertEqual(r["title"], "Quarterly summary")

    def test_title_ultimate_fallback(self):
        r = _normalize_asia_disclosure_record(_asia_rec(
            issuer_name="", ticker_or_identifier="", disclosure_type="",
            title="", summary="",
        ))
        self.assertEqual(r["title"], "Asia Regulatory Disclosure")

    def test_issuer_name_preserved(self):
        r = _normalize_asia_disclosure_record(_asia_rec())
        self.assertEqual(r["issuer_name"], "Tencent Holdings")

    def test_ticker_preserved(self):
        r = _normalize_asia_disclosure_record(_asia_rec())
        self.assertEqual(r["ticker_or_identifier"], "0700")

    def test_exchange_or_regulator_preserved(self):
        r = _normalize_asia_disclosure_record(_asia_rec())
        self.assertEqual(r["exchange_or_regulator"], "HKEX")

    def test_jurisdiction_preserved(self):
        r = _normalize_asia_disclosure_record(_asia_rec())
        self.assertEqual(r["jurisdiction"], "HK")

    def test_disclosure_type_preserved(self):
        r = _normalize_asia_disclosure_record(_asia_rec())
        self.assertEqual(r["disclosure_type"], "regulatory_disclosure")

    def test_disclosure_type_default_when_empty(self):
        r = _normalize_asia_disclosure_record(_asia_rec(disclosure_type=""))
        self.assertEqual(r["disclosure_type"], "asia_regulatory_disclosure")

    def test_published_at_preserved(self):
        r = _normalize_asia_disclosure_record(_asia_rec())
        self.assertEqual(r["published_at"], "2026-05-10")

    def test_url_preserved(self):
        r = _normalize_asia_disclosure_record(_asia_rec())
        self.assertIn("hkex.com.hk", r["url"])

    def test_summary_preserved(self):
        r = _normalize_asia_disclosure_record(_asia_rec())
        self.assertIn("Tencent Holdings", r["summary"])

    def test_provider_preserved(self):
        r = _normalize_asia_disclosure_record(_asia_rec())
        self.assertEqual(r["provider"], "hkex")

    def test_language_preserved(self):
        r = _normalize_asia_disclosure_record(_asia_rec())
        self.assertEqual(r["language"], "en")

    def test_raw_payload_preserved(self):
        payload = {"issuer_name": "Tencent", "extra": "data"}
        r = _normalize_asia_disclosure_record(_asia_rec(raw_payload=payload))
        self.assertEqual(r["raw_payload"]["issuer_name"], "Tencent")

    def test_raw_payload_none_becomes_empty_dict(self):
        r = _normalize_asia_disclosure_record(_asia_rec(raw_payload=None))
        self.assertIsInstance(r["raw_payload"], dict)

    def test_advisory_status(self):
        r = _normalize_asia_disclosure_record(_asia_rec())
        self.assertEqual(r["advisory_status"], "ADVISORY_ONLY")

    def test_human_review_required(self):
        r = _normalize_asia_disclosure_record(_asia_rec())
        self.assertTrue(r["human_review_required"])

    def test_execution_gate_locked(self):
        r = _normalize_asia_disclosure_record(_asia_rec())
        self.assertEqual(r["execution_gate"], "LOCKED")

    def test_ai_execution_count_zero(self):
        r = _normalize_asia_disclosure_record(_asia_rec())
        self.assertEqual(r["ai_execution_count"], 0)

    def test_broker_api_called_false(self):
        r = _normalize_asia_disclosure_record(_asia_rec())
        self.assertFalse(r["broker_api_called"])

    def test_broker_order_id_none_string(self):
        r = _normalize_asia_disclosure_record(_asia_rec())
        self.assertEqual(r["broker_order_id"], "NONE")

    def test_different_tickers_different_event_ids(self):
        r1 = _normalize_asia_disclosure_record(_asia_rec(ticker_or_identifier="0700"))
        r2 = _normalize_asia_disclosure_record(_asia_rec(ticker_or_identifier="9988"))
        self.assertNotEqual(r1["event_id"], r2["event_id"])

    def test_different_providers_different_event_ids(self):
        r1 = _normalize_asia_disclosure_record(_asia_rec(provider="hkex"))
        r2 = _normalize_asia_disclosure_record(_asia_rec(provider="sse"))
        self.assertNotEqual(r1["event_id"], r2["event_id"])

    def test_default_provider_when_missing(self):
        rec = _asia_rec()
        del rec["provider"]
        r = _normalize_asia_disclosure_record(rec)
        self.assertEqual(r["provider"], "asia_disclosure")

    def test_cn_jurisdiction(self):
        r = _normalize_asia_disclosure_record(_asia_rec(jurisdiction="CN", exchange_or_regulator="SSE"))
        self.assertEqual(r["jurisdiction"], "CN")
        self.assertEqual(r["exchange_or_regulator"], "SSE")

    def test_jp_jurisdiction(self):
        r = _normalize_asia_disclosure_record(_asia_rec(jurisdiction="JP", exchange_or_regulator="TDnet"))
        self.assertEqual(r["jurisdiction"], "JP")

    def test_kr_jurisdiction(self):
        r = _normalize_asia_disclosure_record(_asia_rec(jurisdiction="KR", exchange_or_regulator="DART"))
        self.assertEqual(r["jurisdiction"], "KR")

    def test_sg_jurisdiction(self):
        r = _normalize_asia_disclosure_record(_asia_rec(jurisdiction="SG", exchange_or_regulator="SGX"))
        self.assertEqual(r["jurisdiction"], "SG")


# ---------------------------------------------------------------------------
# Loader init tests
# ---------------------------------------------------------------------------

class TestAsiaDisclosureLoaderInit(unittest.TestCase):

    def _loader(self):
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader
        return AsiaDisclosureLoader

    def test_source_name(self):
        self.assertEqual(self._loader().source_name, "asia_disclosure")

    def test_requires_key_false(self):
        self.assertFalse(self._loader().requires_key)

    def test_default_providers_none(self):
        loader = self._loader()()
        self.assertIsNone(loader._providers)

    def test_default_query_none(self):
        loader = self._loader()()
        self.assertIsNone(loader._query)

    def test_default_jurisdiction_none(self):
        loader = self._loader()()
        self.assertIsNone(loader._jurisdiction)

    def test_default_max_items(self):
        loader = self._loader()()
        self.assertEqual(loader._max_items, 50)

    def test_custom_params_stored(self):
        loader = self._loader()(
            providers=["hkex"],
            query="earnings",
            jurisdiction="HK",
            max_items=10,
        )
        self.assertEqual(loader._providers, ["hkex"])
        self.assertEqual(loader._query, "earnings")
        self.assertEqual(loader._jurisdiction, "HK")
        self.assertEqual(loader._max_items, 10)

    def test_query_lowercased(self):
        loader = self._loader()(query="Tencent Annual")
        self.assertEqual(loader._query, "tencent annual")

    def test_jurisdiction_uppercased(self):
        loader = self._loader()(jurisdiction="hk")
        self.assertEqual(loader._jurisdiction, "HK")

    def test_empty_query_becomes_none(self):
        loader = self._loader()(query="   ")
        self.assertIsNone(loader._query)

    def test_empty_jurisdiction_becomes_none(self):
        loader = self._loader()(jurisdiction="   ")
        self.assertIsNone(loader._jurisdiction)


# ---------------------------------------------------------------------------
# Missing requests library
# ---------------------------------------------------------------------------

class TestAsiaDisclosureLoaderMissingRequests(unittest.TestCase):

    def test_skips_when_requests_missing(self):
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader
        loader = AsiaDisclosureLoader(providers=["hkex"])
        with patch.dict(sys.modules, {"requests": None}):
            result = loader.safe_fetch()
        self.assertTrue(result.skipped)
        self.assertIn("requests", result.skip_reason.lower())

    def test_skip_reason_non_empty(self):
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader
        loader = AsiaDisclosureLoader(providers=["hkex"])
        with patch.dict(sys.modules, {"requests": None}):
            result = loader.safe_fetch()
        self.assertGreater(len(result.skip_reason), 0)


# ---------------------------------------------------------------------------
# Provider skip tests — all providers are placeholders
# ---------------------------------------------------------------------------

class TestAsiaDisclosureProviderSkips(unittest.TestCase):

    def _loader(self, **kw):
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader
        return AsiaDisclosureLoader(**kw)

    _NO_KEY_ENV: dict[str, str] = {}

    def _env_without_subsource_keys(self):
        import os as _os
        stripped = {
            k: v
            for k, v in _os.environ.items()
            if k
            not in {
                "EDINET_API_KEY",
                "JAPAN_EDINET_API_KEY",
                "OPENDART_API_KEY",
                "KOREA_DART_API_KEY",
            }
        }
        return patch.dict("os.environ", stripped, clear=True)

    def test_hkex_placeholder_skips(self):
        loader = self._loader(providers=["hkex"])
        result = loader.safe_fetch()
        self.assertTrue(result.skipped)
        self.assertIn("placeholder", result.skip_reason.lower())

    def test_sse_placeholder_skips(self):
        loader = self._loader(providers=["sse"])
        result = loader.safe_fetch()
        self.assertTrue(result.skipped)

    def test_szse_placeholder_skips(self):
        loader = self._loader(providers=["szse"])
        result = loader.safe_fetch()
        self.assertTrue(result.skipped)

    def test_tdnet_placeholder_skips(self):
        loader = self._loader(providers=["tdnet"])
        result = loader.safe_fetch()
        self.assertTrue(result.skipped)

    def test_sgx_placeholder_skips(self):
        loader = self._loader(providers=["sgx"])
        result = loader.safe_fetch()
        self.assertTrue(result.skipped)

    def test_dart_placeholder_skips(self):
        loader = self._loader(providers=["dart"])
        result = loader.safe_fetch()
        self.assertTrue(result.skipped)

    def test_unknown_provider_skips(self):
        loader = self._loader(providers=["nonexistent_exchange"])
        result = loader.safe_fetch()
        self.assertTrue(result.skipped)

    def test_empty_provider_list_skips(self):
        loader = self._loader(providers=[])
        result = loader.safe_fetch()
        self.assertTrue(result.skipped)

    def test_unknown_jurisdiction_skips(self):
        loader = self._loader(jurisdiction="XX")
        result = loader.safe_fetch()
        self.assertTrue(result.skipped)

    def test_cn_jurisdiction_skips_all_placeholder(self):
        loader = self._loader(jurisdiction="CN")
        result = loader.safe_fetch()
        self.assertTrue(result.skipped)

    def test_hk_jurisdiction_skips_all_placeholder(self):
        loader = self._loader(jurisdiction="HK")
        result = loader.safe_fetch()
        self.assertTrue(result.skipped)

    def test_jp_jurisdiction_skips_without_keys(self):
        """Japan now has EDINET active; without EDINET_API_KEY/alias it must
        still skip cleanly with optional_config_missing."""
        loader = self._loader(jurisdiction="JP")
        with self._env_without_subsource_keys():
            result = loader.safe_fetch()
        self.assertTrue(result.skipped)

    def test_sg_jurisdiction_skips_all_placeholder(self):
        loader = self._loader(jurisdiction="SG")
        result = loader.safe_fetch()
        self.assertTrue(result.skipped)

    def test_kr_jurisdiction_skips_without_keys(self):
        """Korea now has OpenDART active; without OPENDART_API_KEY/alias it
        must still skip cleanly with optional_config_missing."""
        loader = self._loader(jurisdiction="KR")
        with self._env_without_subsource_keys():
            result = loader.safe_fetch()
        self.assertTrue(result.skipped)

    def test_all_providers_default_skip_without_keys(self):
        """With no filter, all providers selected; EDINET/OpenDART need
        keys, rest are placeholders.  Without keys the loader must skip."""
        loader = self._loader()
        with self._env_without_subsource_keys():
            result = loader.safe_fetch()
        self.assertTrue(result.skipped)


# ---------------------------------------------------------------------------
# Mocked HTTP tests — patch _PROVIDER_CONFIGS to enable one provider
# ---------------------------------------------------------------------------

class TestAsiaDisclosureLoaderMockedHTTP(unittest.TestCase):
    """Tests that activate one provider via patched config and mock the HTTP call."""

    def _active_hkex_conf(self):
        from scripts.ingestion.asia_disclosure_loader import _PROVIDER_CONFIGS
        return {
            **_PROVIDER_CONFIGS["hkex"],
            "active": True,
            "url": "https://mock.hkex.test/api/announcements",
        }

    def _run_with_active_hkex(self, side_effects, **loader_kw):
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader, _PROVIDER_CONFIGS
        patched_configs = {**_PROVIDER_CONFIGS, "hkex": self._active_hkex_conf()}
        loader = AsiaDisclosureLoader(providers=["hkex"], **loader_kw)
        with patch("scripts.ingestion.asia_disclosure_loader._PROVIDER_CONFIGS", patched_configs):
            with patch("requests.get", side_effect=side_effects):
                return loader.safe_fetch()

    def test_successful_fetch_returns_records(self):
        result = self._run_with_active_hkex([_mock_asia_response()])
        self.assertFalse(result.skipped)
        self.assertGreater(len(result.records), 0)

    def test_source_name_on_result(self):
        result = self._run_with_active_hkex([_mock_asia_response()])
        self.assertEqual(result.source_name, "asia_disclosure")

    def test_records_have_issuer_name(self):
        result = self._run_with_active_hkex([_mock_asia_response()])
        for rec in result.records:
            self.assertIn("issuer_name", rec)

    def test_records_have_ticker(self):
        result = self._run_with_active_hkex([_mock_asia_response()])
        for rec in result.records:
            self.assertIn("ticker_or_identifier", rec)

    def test_records_have_jurisdiction_hk(self):
        result = self._run_with_active_hkex([_mock_asia_response()])
        for rec in result.records:
            self.assertEqual(rec.get("jurisdiction"), "HK")

    def test_records_have_exchange_hkex(self):
        result = self._run_with_active_hkex([_mock_asia_response()])
        for rec in result.records:
            self.assertEqual(rec.get("exchange_or_regulator"), "HKEX")

    def test_advisory_stamps_on_all_records(self):
        result = self._run_with_active_hkex([_mock_asia_response()])
        for rec in result.records:
            self.assertEqual(rec.get("advisory_status"), "ADVISORY_ONLY")
            self.assertTrue(rec.get("human_review_required"))
            self.assertEqual(rec.get("execution_gate"), "LOCKED")

    def test_provider_field_on_records(self):
        result = self._run_with_active_hkex([_mock_asia_response()])
        for rec in result.records:
            self.assertEqual(rec.get("provider"), "hkex")

    def test_raw_payload_on_records(self):
        result = self._run_with_active_hkex([_mock_asia_response()])
        for rec in result.records:
            self.assertIn("raw_payload", rec)
            self.assertIsInstance(rec["raw_payload"], dict)

    def test_response_as_dict_with_data_key(self):
        result = self._run_with_active_hkex([_mock_asia_response_dict()])
        self.assertFalse(result.skipped)
        self.assertEqual(len(result.records), 1)

    def test_response_as_list_directly(self):
        result = self._run_with_active_hkex([_mock_asia_response()])
        self.assertFalse(result.skipped)
        self.assertEqual(len(result.records), 2)

    def test_max_items_respected(self):
        many_items = [_asia_item(issuer_name=f"Company{i}", ticker=f"C{i:04d}") for i in range(30)]
        result = self._run_with_active_hkex([_mock_asia_response(many_items)], max_items=5)
        self.assertLessEqual(len(result.records), 5)

    def test_query_filter_matches(self):
        result = self._run_with_active_hkex([_mock_asia_response()], query="tencent")
        self.assertFalse(result.skipped)
        matched = [r for r in result.records if "tencent" in r.get("issuer_name", "").lower()]
        self.assertGreater(len(matched), 0)

    def test_query_filter_no_match_returns_empty(self):
        result = self._run_with_active_hkex([_mock_asia_response()], query="ZZNOTFOUND999")
        self.assertFalse(result.skipped)
        self.assertEqual(len(result.records), 0)

    def test_network_error_loader_skips(self):
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader, _PROVIDER_CONFIGS
        patched_configs = {**_PROVIDER_CONFIGS, "hkex": self._active_hkex_conf()}
        loader = AsiaDisclosureLoader(providers=["hkex"])
        with patch("scripts.ingestion.asia_disclosure_loader._PROVIDER_CONFIGS", patched_configs):
            with patch("requests.get", side_effect=Exception("network down")):
                result = loader.safe_fetch()
        self.assertTrue(result.skipped)
        self.assertIn("unreachable", result.skip_reason.lower())

    def test_http_error_loader_skips(self):
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader, _PROVIDER_CONFIGS
        patched_configs = {**_PROVIDER_CONFIGS, "hkex": self._active_hkex_conf()}
        loader = AsiaDisclosureLoader(providers=["hkex"])
        err_mock = MagicMock()
        err_mock.raise_for_status.side_effect = Exception("HTTP 503")
        with patch("scripts.ingestion.asia_disclosure_loader._PROVIDER_CONFIGS", patched_configs):
            with patch("requests.get", return_value=err_mock):
                result = loader.safe_fetch()
        self.assertTrue(result.skipped)

    def test_non_dict_items_skipped(self):
        mock = MagicMock()
        mock.status_code = 200
        mock.json.return_value = ["not_a_dict", 42, None]
        mock.raise_for_status.return_value = None
        result = self._run_with_active_hkex([mock])
        self.assertFalse(result.skipped)
        self.assertEqual(len(result.records), 0)

    def test_empty_items_list_no_crash(self):
        mock = MagicMock()
        mock.status_code = 200
        mock.json.return_value = []
        mock.raise_for_status.return_value = None
        result = self._run_with_active_hkex([mock])
        self.assertFalse(result.skipped)
        self.assertEqual(len(result.records), 0)

    def test_two_items_two_records(self):
        items = [
            _asia_item(issuer_name="Tencent", ticker="0700"),
            _asia_item(issuer_name="Alibaba", ticker="9988"),
        ]
        result = self._run_with_active_hkex([_mock_asia_response(items)])
        self.assertEqual(len(result.records), 2)

    def test_alternate_field_names_company_name(self):
        item = {"company_name": "Meituan", "stock_code": "3690", "link": "http://example.com/meituan.pdf"}
        mock = MagicMock()
        mock.status_code = 200
        mock.json.return_value = [item]
        mock.raise_for_status.return_value = None
        result = self._run_with_active_hkex([mock])
        self.assertFalse(result.skipped)
        rec = result.records[0]
        self.assertEqual(rec["issuer_name"], "Meituan")
        self.assertEqual(rec["ticker_or_identifier"], "3690")
        self.assertEqual(rec["url"], "http://example.com/meituan.pdf")

    def test_issuer_name_from_name_field(self):
        item = _asia_item()
        del item["issuer_name"]
        item["name"] = "Ping An Insurance"
        result = self._run_with_active_hkex([_mock_asia_response([item])])
        rec = result.records[0]
        self.assertEqual(rec["issuer_name"], "Ping An Insurance")

    def test_missing_key_for_keyed_provider_skips(self):
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader, _PROVIDER_CONFIGS
        dart_active = {
            **_PROVIDER_CONFIGS["dart"],
            "active": True,
            "url": "https://mock.dart.test/api",
        }
        patched_configs = {**_PROVIDER_CONFIGS, "dart": dart_active}
        loader = AsiaDisclosureLoader(providers=["dart"])
        import os
        env_without_dart = {k: v for k, v in os.environ.items() if k != "DART_API_KEY"}
        with patch("scripts.ingestion.asia_disclosure_loader._PROVIDER_CONFIGS", patched_configs):
            with patch.dict("os.environ", env_without_dart, clear=True):
                result = loader.safe_fetch()
        # Should skip because DART_API_KEY is missing and no records collected
        self.assertTrue(result.skipped)

    def test_partial_failure_tolerance(self):
        """One provider fails, another succeeds — records from successful provider returned."""
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader, _PROVIDER_CONFIGS
        sse_active = {**_PROVIDER_CONFIGS["sse"], "active": True, "url": "https://mock.sse.test/api"}
        hkex_active = self._active_hkex_conf()
        patched_configs = {**_PROVIDER_CONFIGS, "sse": sse_active, "hkex": hkex_active}
        loader = AsiaDisclosureLoader(providers=["sse", "hkex"])
        # sse fails, hkex succeeds
        with patch("scripts.ingestion.asia_disclosure_loader._PROVIDER_CONFIGS", patched_configs):
            with patch(
                "requests.get",
                side_effect=[Exception("SSE network error"), _mock_asia_response()],
            ):
                result = loader.safe_fetch()
        self.assertFalse(result.skipped)
        self.assertGreater(len(result.records), 0)


# ---------------------------------------------------------------------------
# Phase 2 runner integration
# ---------------------------------------------------------------------------

class TestPhase2RunnerAsiaDisclosure(unittest.TestCase):

    def _run_with_mocked_loader(self, dry_run=True, records=None, **kw):
        """Run run_phase2 with asia_disclosure, patching the loader's fetch to return mock records."""
        mock_result = _mock_loader_result(records)
        with patch(
            "scripts.ingestion.asia_disclosure_loader.AsiaDisclosureLoader.fetch",
            return_value=mock_result,
        ):
            return run_phase2(dry_run=dry_run, sources=["asia_disclosure"], **kw)

    def test_returns_phase2_run_report(self):
        self.assertIsInstance(self._run_with_mocked_loader(), Phase2RunReport)

    def test_report_has_asia_disclosure_source(self):
        report = self._run_with_mocked_loader()
        names = [s.source_name for s in report.sources]
        self.assertIn("asia_disclosure", names)

    def test_status_ok_when_records_returned(self):
        report = self._run_with_mocked_loader()
        asia = next(s for s in report.sources if s.source_name == "asia_disclosure")
        self.assertEqual(asia.status, "ok")

    def test_fetched_count_nonzero(self):
        report = self._run_with_mocked_loader()
        asia = next(s for s in report.sources if s.source_name == "asia_disclosure")
        self.assertGreater(asia.fetched_count, 0)

    def test_dry_run_no_persist(self):
        report = self._run_with_mocked_loader(dry_run=True)
        self.assertEqual(report.total_persisted, 0)

    def test_dry_run_flag_on_report(self):
        report = self._run_with_mocked_loader(dry_run=True)
        self.assertTrue(report.dry_run)

    def test_advisory_status_on_report(self):
        self.assertEqual(self._run_with_mocked_loader().advisory_status, "ADVISORY_ONLY")

    def test_broker_api_false_on_report(self):
        self.assertFalse(self._run_with_mocked_loader().broker_api_called)

    def test_ai_execution_zero_on_report(self):
        self.assertEqual(self._run_with_mocked_loader().ai_execution_count, 0)

    def test_execution_gate_locked(self):
        self.assertEqual(self._run_with_mocked_loader().execution_gate, "LOCKED")

    def test_human_review_required(self):
        self.assertTrue(self._run_with_mocked_loader().human_review_required)

    def test_to_dict_json_serializable(self):
        d = self._run_with_mocked_loader().to_dict()
        json.dumps(d)

    def test_skipped_when_no_keys_configured(self):
        """Without EDINET / OpenDART keys the parent loader skips cleanly
        with optional_config_missing — never crashes, never fakes rows."""
        import os as _os
        stripped = {
            k: v
            for k, v in _os.environ.items()
            if k
            not in {
                "EDINET_API_KEY",
                "JAPAN_EDINET_API_KEY",
                "OPENDART_API_KEY",
                "KOREA_DART_API_KEY",
            }
        }
        with patch.dict("os.environ", stripped, clear=True):
            report = run_phase2(dry_run=True, sources=["asia_disclosure"])
        asia = next(s for s in report.sources if s.source_name == "asia_disclosure")
        self.assertIn(asia.status, ("skipped", "placeholder", "http_error"))
        reason = asia.skipped_reason.lower()
        self.assertTrue(
            "optional_config_missing" in reason
            or "placeholder" in reason,
            f"unexpected skip reason: {asia.skipped_reason!r}",
        )

    def test_unknown_source_ignored(self):
        report = self._run_with_mocked_loader()
        report2 = run_phase2(
            dry_run=True,
            sources=["asia_disclosure", "nonexistent"],
        )
        names = [s.source_name for s in report2.sources]
        self.assertNotIn("nonexistent", names)

    def test_asia_providers_param_passed(self):
        report = self._run_with_mocked_loader(
            dry_run=True,
            asia_disclosure_providers=["hkex"],
        )
        asia = next(s for s in report.sources if s.source_name == "asia_disclosure")
        self.assertEqual(asia.status, "ok")

    def test_asia_jurisdiction_param_passed(self):
        report = self._run_with_mocked_loader(
            dry_run=True,
            asia_disclosure_jurisdiction="HK",
        )
        asia = next(s for s in report.sources if s.source_name == "asia_disclosure")
        self.assertIn(asia.status, {"ok", "skipped", "placeholder"})

    def test_asia_max_items_param(self):
        two_records = [_mock_loader_result().records[0]] * 5
        report = self._run_with_mocked_loader(
            dry_run=True,
            asia_disclosure_max_items=2,
            records=two_records,
        )
        asia = next(s for s in report.sources if s.source_name == "asia_disclosure")
        self.assertLessEqual(asia.fetched_count, 5)

    def test_duration_ms_set(self):
        report = self._run_with_mocked_loader()
        asia = next(s for s in report.sources if s.source_name == "asia_disclosure")
        self.assertGreaterEqual(asia.duration_ms, 0)

    def test_run_at_set(self):
        report = self._run_with_mocked_loader()
        self.assertGreater(len(report.run_at), 0)


# ---------------------------------------------------------------------------
# Write mode
# ---------------------------------------------------------------------------

class TestAsiaDisclosureWriteMode(unittest.TestCase):

    def _patch_and_run(self, dry_run, records=None):
        mock_result = _mock_loader_result(records)
        with patch(
            "scripts.ingestion.asia_disclosure_loader.AsiaDisclosureLoader.fetch",
            return_value=mock_result,
        ):
            return run_phase2(dry_run=dry_run, sources=["asia_disclosure"])

    def test_write_mode_calls_persist(self):
        mock_result = _mock_loader_result()
        with patch(
            "scripts.ingestion.asia_disclosure_loader.AsiaDisclosureLoader.fetch",
            return_value=mock_result,
        ):
            with patch(
                "scripts.live_source_runner_phase2._persist_events", return_value=1
            ) as mock_p:
                with patch("scripts.live_source_runner_phase2._log_run") as mock_l:
                    report = run_phase2(dry_run=False, sources=["asia_disclosure"])
        mock_p.assert_called_once()
        mock_l.assert_called_once()
        asia = next(s for s in report.sources if s.source_name == "asia_disclosure")
        self.assertEqual(asia.events_persisted, 1)

    def test_dry_run_does_not_call_persist(self):
        mock_result = _mock_loader_result()
        with patch(
            "scripts.ingestion.asia_disclosure_loader.AsiaDisclosureLoader.fetch",
            return_value=mock_result,
        ):
            with patch("scripts.live_source_runner_phase2._persist_events") as mock_p:
                run_phase2(dry_run=True, sources=["asia_disclosure"])
        mock_p.assert_not_called()

    def test_dry_run_does_not_call_log_run(self):
        mock_result = _mock_loader_result()
        with patch(
            "scripts.ingestion.asia_disclosure_loader.AsiaDisclosureLoader.fetch",
            return_value=mock_result,
        ):
            with patch("scripts.live_source_runner_phase2._log_run") as mock_l:
                run_phase2(dry_run=True, sources=["asia_disclosure"])
        mock_l.assert_not_called()

    def test_write_mode_skipped_source_still_logged(self):
        # No patching of loader — without EDINET/OpenDART keys it skips
        # cleanly; log_run still called in write mode.
        import os as _os
        stripped = {
            k: v
            for k, v in _os.environ.items()
            if k
            not in {
                "EDINET_API_KEY",
                "JAPAN_EDINET_API_KEY",
                "OPENDART_API_KEY",
                "KOREA_DART_API_KEY",
            }
        }
        with patch.dict("os.environ", stripped, clear=True):
            with patch("scripts.live_source_runner_phase2._log_run") as mock_l:
                run_phase2(dry_run=False, sources=["asia_disclosure"])
        mock_l.assert_called_once()

    def test_source_run_log_entry_fields(self):
        mock_result = _mock_loader_result()
        logged_args = {}

        def capture_log(result):
            logged_args.update(result.to_dict())

        with patch(
            "scripts.ingestion.asia_disclosure_loader.AsiaDisclosureLoader.fetch",
            return_value=mock_result,
        ):
            with patch("scripts.live_source_runner_phase2._persist_events", return_value=1):
                with patch("scripts.live_source_runner_phase2._log_run", side_effect=capture_log):
                    run_phase2(dry_run=False, sources=["asia_disclosure"])

        self.assertEqual(logged_args.get("source_name"), "asia_disclosure")
        self.assertEqual(logged_args.get("status"), "ok")
        self.assertGreater(logged_args.get("fetched_count", 0), 0)


# ---------------------------------------------------------------------------
# Safety invariants
# ---------------------------------------------------------------------------

class TestAsiaDisclosureSafetyInvariants(unittest.TestCase):

    def _records(self):
        recs = [
            _asia_rec(ticker_or_identifier="0700", issuer_name="Tencent Holdings"),
            _asia_rec(ticker_or_identifier="9988", issuer_name="Alibaba Group", provider="sse"),
            _asia_rec(ticker_or_identifier="3690", issuer_name="Meituan", jurisdiction="CN"),
        ]
        return [_normalize_asia_disclosure_record(r) for r in recs]

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

    def test_source_name_always_asia_disclosure(self):
        for r in self._records():
            self.assertEqual(r["source_name"], "asia_disclosure")

    def test_no_order_keys(self):
        forbidden = {"order_id", "trade_id", "broker_order", "execution_id", "fill_price"}
        for r in self._records():
            self.assertEqual(set(r.keys()) & forbidden, set())

    def _hermetic_env(self):
        import os as _os
        stripped = {
            k: v
            for k, v in _os.environ.items()
            if k
            not in {
                "EDINET_API_KEY",
                "JAPAN_EDINET_API_KEY",
                "OPENDART_API_KEY",
                "KOREA_DART_API_KEY",
            }
        }
        return patch.dict("os.environ", stripped, clear=True)

    def test_phase2_report_advisory_only(self):
        with self._hermetic_env():
            report = run_phase2(dry_run=True, sources=["asia_disclosure"])
        self.assertEqual(report.advisory_status, "ADVISORY_ONLY")

    def test_phase2_report_broker_false(self):
        with self._hermetic_env():
            report = run_phase2(dry_run=True, sources=["asia_disclosure"])
        self.assertFalse(report.broker_api_called)

    def test_phase2_report_ai_zero(self):
        with self._hermetic_env():
            report = run_phase2(dry_run=True, sources=["asia_disclosure"])
        self.assertEqual(report.ai_execution_count, 0)

    def test_no_execution_path_in_normalized_record(self):
        r = _normalize_asia_disclosure_record(_asia_rec())
        # ai_execution_count, execution_gate, execution_permission, and
        # can_execute are *safety* fields (LOCKED / False) not execution
        # paths.  Their presence on every row is part of the advisory
        # contract.  Any other key containing "execut" or "trade" would
        # indicate an unsafe execution path.
        safe_keys = {
            "execution_gate",
            "ai_execution_count",
            "execution_permission",
            "can_execute",
        }
        execution_keys = {k for k in r if "execut" in k.lower()} - safe_keys
        self.assertEqual(execution_keys, set())
        # All safety fields must carry their safe defaults.
        self.assertEqual(r["execution_gate"], "LOCKED")
        self.assertEqual(r["ai_execution_count"], 0)
        self.assertFalse(r["execution_permission"])
        self.assertFalse(r["can_execute"])


# ---------------------------------------------------------------------------
# AST — forbidden method check
# ---------------------------------------------------------------------------

class TestAsiaDisclosureNoForbiddenMethods(unittest.TestCase):

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

    def test_asia_disclosure_loader_no_forbidden_methods(self):
        found = (
            self._attr_calls(_REPO_ROOT / "scripts" / "ingestion" / "asia_disclosure_loader.py")
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

class TestAsiaDisclosureCLIStructure(unittest.TestCase):

    def _load_cli_module(self):
        path = _REPO_ROOT / "scripts" / "run_live_sources_phase2.py"
        spec = importlib.util.spec_from_file_location("run_live_sources_phase2", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_asia_disclosure_in_supported_sources(self):
        mod = self._load_cli_module()
        self.assertIn("asia_disclosure", mod._SUPPORTED_SOURCES)

    def test_run_phase2_has_asia_providers_param(self):
        sig = inspect.signature(run_phase2)
        self.assertIn("asia_disclosure_providers", sig.parameters)

    def test_run_phase2_has_asia_query_param(self):
        sig = inspect.signature(run_phase2)
        self.assertIn("asia_disclosure_query", sig.parameters)

    def test_run_phase2_has_asia_jurisdiction_param(self):
        sig = inspect.signature(run_phase2)
        self.assertIn("asia_disclosure_jurisdiction", sig.parameters)

    def test_run_phase2_has_asia_max_items_param(self):
        sig = inspect.signature(run_phase2)
        self.assertIn("asia_disclosure_max_items", sig.parameters)

    def test_normalize_asia_disclosure_record_exported(self):
        from scripts.live_source_runner_phase2 import __all__
        self.assertIn("_normalize_asia_disclosure_record", __all__)

    def test_asia_disclosure_loader_importable(self):
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader
        self.assertIsNotNone(AsiaDisclosureLoader)

    def test_run_phase2_dry_run_mocked(self):
        mock_result = _mock_loader_result()
        with patch(
            "scripts.ingestion.asia_disclosure_loader.AsiaDisclosureLoader.fetch",
            return_value=mock_result,
        ):
            report = run_phase2(
                dry_run=True,
                sources=["asia_disclosure"],
                asia_disclosure_providers=["hkex"],
                asia_disclosure_query=None,
                asia_disclosure_jurisdiction=None,
                asia_disclosure_max_items=10,
            )
        self.assertIsInstance(report, Phase2RunReport)
        asia = next(s for s in report.sources if s.source_name == "asia_disclosure")
        self.assertIn(asia.status, {"ok", "skipped", "placeholder"})

    def test_report_to_dict_has_required_keys(self):
        import os as _os
        stripped = {
            k: v
            for k, v in _os.environ.items()
            if k
            not in {
                "EDINET_API_KEY",
                "JAPAN_EDINET_API_KEY",
                "OPENDART_API_KEY",
                "KOREA_DART_API_KEY",
            }
        }
        with patch.dict("os.environ", stripped, clear=True):
            report = run_phase2(dry_run=True, sources=["asia_disclosure"])
        d = report.to_dict()
        self.assertIn("sources", d)
        self.assertIn("advisory_status", d)
        self.assertIn("broker_api_called", d)
        self.assertIn("ai_execution_count", d)

    def test_provider_configs_has_all_legacy_asia_providers(self):
        from scripts.ingestion.asia_disclosure_loader import _PROVIDER_CONFIGS
        for name in ["sse", "szse", "hkex", "tdnet", "sgx", "dart"]:
            self.assertIn(name, _PROVIDER_CONFIGS, f"{name} missing from _PROVIDER_CONFIGS")

    def test_provider_configs_has_edinet_and_opendart(self):
        from scripts.ingestion.asia_disclosure_loader import _PROVIDER_CONFIGS
        for name in ["edinet", "opendart"]:
            self.assertIn(name, _PROVIDER_CONFIGS)
            self.assertTrue(_PROVIDER_CONFIGS[name]["active"])

    def test_legacy_provider_configs_inactive(self):
        from scripts.ingestion.asia_disclosure_loader import _PROVIDER_CONFIGS
        for name in ("sse", "szse", "hkex", "tdnet", "sgx", "dart"):
            self.assertFalse(
                _PROVIDER_CONFIGS[name]["active"],
                f"{name} should remain a placeholder (inactive)",
            )

    def test_provider_configs_jurisdictions_correct(self):
        from scripts.ingestion.asia_disclosure_loader import _PROVIDER_CONFIGS
        expected = {
            "sse": "CN", "szse": "CN", "hkex": "HK",
            "tdnet": "JP", "sgx": "SG", "dart": "KR",
            "edinet": "JP", "opendart": "KR",
        }
        for name, jur in expected.items():
            self.assertEqual(_PROVIDER_CONFIGS[name]["jurisdiction"], jur)

    def test_sgx_requires_key(self):
        from scripts.ingestion.asia_disclosure_loader import _PROVIDER_CONFIGS
        self.assertTrue(_PROVIDER_CONFIGS["sgx"]["requires_key"])
        self.assertEqual(_PROVIDER_CONFIGS["sgx"]["key_env"], "SGX_API_KEY")

    def test_legacy_dart_remains_placeholder(self):
        """Legacy ``dart`` placeholder retained for backward compat; the
        live Korean integration is the new ``opendart`` provider."""
        from scripts.ingestion.asia_disclosure_loader import _PROVIDER_CONFIGS
        self.assertTrue(_PROVIDER_CONFIGS["dart"]["requires_key"])
        self.assertFalse(_PROVIDER_CONFIGS["dart"]["active"])
        self.assertEqual(_PROVIDER_CONFIGS["dart"]["key_env"], "DART_API_KEY")

    def test_opendart_uses_correct_env(self):
        from scripts.ingestion.asia_disclosure_loader import _PROVIDER_CONFIGS
        self.assertTrue(_PROVIDER_CONFIGS["opendart"]["requires_key"])
        self.assertEqual(_PROVIDER_CONFIGS["opendart"]["key_env"], "OPENDART_API_KEY")
        self.assertIn(
            "KOREA_DART_API_KEY",
            _PROVIDER_CONFIGS["opendart"]["alt_key_envs"],
        )

    def test_edinet_uses_correct_env(self):
        from scripts.ingestion.asia_disclosure_loader import _PROVIDER_CONFIGS
        self.assertTrue(_PROVIDER_CONFIGS["edinet"]["requires_key"])
        self.assertEqual(_PROVIDER_CONFIGS["edinet"]["key_env"], "EDINET_API_KEY")
        self.assertIn(
            "JAPAN_EDINET_API_KEY",
            _PROVIDER_CONFIGS["edinet"]["alt_key_envs"],
        )


if __name__ == "__main__":
    unittest.main()
