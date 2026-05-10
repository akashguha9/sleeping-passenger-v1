"""
Tests for Phase C.6 — India Source (NSE/RBI/SEBI) integration.

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
    _normalize_india_record,
    _stable_event_id,
    run_phase2,
)


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

def _mock_nse_response(indices=None):
    indices = indices or [
        {"index": "NIFTY 50", "last": 22500.0, "change": 150.0, "percentChange": 0.67},
        {"index": "NIFTY BANK", "last": 48000.0, "change": -200.0, "percentChange": -0.41},
        {"index": "INDIA VIX", "last": 12.5, "change": -0.3, "percentChange": -2.34},
    ]
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = {"data": indices}
    mock.raise_for_status.return_value = None
    return mock


def _mock_rbi_response():
    mock = MagicMock()
    mock.status_code = 200
    mock.raise_for_status.return_value = None
    return mock


def _mock_sebi_response():
    mock = MagicMock()
    mock.status_code = 200
    mock.raise_for_status.return_value = None
    return mock


def _all_mocks():
    return [_mock_nse_response(), _mock_rbi_response(), _mock_sebi_response()]


# ---------------------------------------------------------------------------
# Normalization tests
# ---------------------------------------------------------------------------

class TestNormalizationIndia(unittest.TestCase):

    def _nse_rec(self, **kw):
        base = {
            "index_name": "NIFTY 50",
            "last_price": 22500.0,
            "change": 150.0,
            "percent_change": 0.67,
            "regulatory_source": "india_nse",
            "regulatory_url": "https://www.nseindia.com/api/allIndices",
            "regulatory_note": None,
        }
        base.update(kw)
        return base

    def _rbi_rec(self, **kw):
        base = {
            "index_name": "RBI Press Releases",
            "last_price": None,
            "change": None,
            "percent_change": None,
            "regulatory_source": "india_rbi",
            "regulatory_url": "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx",
            "regulatory_note": "RBI press release page fetched (read-only)",
        }
        base.update(kw)
        return base

    def test_event_id_stable(self):
        rec = self._nse_rec()
        self.assertEqual(_normalize_india_record(rec)["event_id"],
                         _normalize_india_record(rec)["event_id"])

    def test_event_id_starts_with_india(self):
        r = _normalize_india_record(self._nse_rec())
        self.assertTrue(r["event_id"].startswith("india_"))

    def test_source_name_india(self):
        r = _normalize_india_record(self._nse_rec())
        self.assertEqual(r["source_name"], "india")

    def test_signal_type(self):
        r = _normalize_india_record(self._nse_rec())
        self.assertEqual(r["signal_type"], "india_market_signal")

    def test_title_includes_index_name(self):
        r = _normalize_india_record(self._nse_rec())
        self.assertIn("NIFTY 50", r["title"])

    def test_title_includes_price(self):
        r = _normalize_india_record(self._nse_rec())
        self.assertIn("22500", r["title"])

    def test_title_includes_positive_pct(self):
        r = _normalize_india_record(self._nse_rec(percent_change=0.67))
        self.assertIn("+0.67%", r["title"])

    def test_title_includes_negative_pct(self):
        r = _normalize_india_record(self._nse_rec(percent_change=-0.41))
        self.assertIn("-0.41%", r["title"])

    def test_null_price_no_crash(self):
        r = _normalize_india_record(self._nse_rec(last_price=None, percent_change=None))
        self.assertIsNone(r["last_price"])
        self.assertIsNone(r["percent_change"])

    def test_rbi_source_name(self):
        r = _normalize_india_record(self._rbi_rec())
        self.assertEqual(r["source_name"], "india")

    def test_rbi_regulatory_source(self):
        r = _normalize_india_record(self._rbi_rec())
        self.assertEqual(r["regulatory_source"], "india_rbi")

    def test_rbi_title_contains_rbi(self):
        r = _normalize_india_record(self._rbi_rec())
        self.assertIn("RBI", r["title"])

    def test_regulatory_note_preserved(self):
        r = _normalize_india_record(self._rbi_rec())
        self.assertIn("read-only", r["regulatory_note"])

    def test_regulatory_url_preserved(self):
        r = _normalize_india_record(self._nse_rec())
        self.assertIn("nseindia.com", r["regulatory_url"])

    def test_index_name_preserved(self):
        r = _normalize_india_record(self._nse_rec())
        self.assertEqual(r["index_name"], "NIFTY 50")

    def test_different_sources_different_event_ids(self):
        r1 = _normalize_india_record(self._nse_rec(regulatory_source="india_nse", index_name="NIFTY 50"))
        r2 = _normalize_india_record(self._rbi_rec())
        self.assertNotEqual(r1["event_id"], r2["event_id"])

    def test_different_indices_different_event_ids(self):
        r1 = _normalize_india_record(self._nse_rec(index_name="NIFTY 50"))
        r2 = _normalize_india_record(self._nse_rec(index_name="NIFTY BANK"))
        self.assertNotEqual(r1["event_id"], r2["event_id"])

    def test_advisory_status(self):
        r = _normalize_india_record(self._nse_rec())
        self.assertEqual(r["advisory_status"], "ADVISORY_ONLY")

    def test_human_review_required(self):
        r = _normalize_india_record(self._nse_rec())
        self.assertTrue(r["human_review_required"])

    def test_execution_gate_locked(self):
        r = _normalize_india_record(self._nse_rec())
        self.assertEqual(r["execution_gate"], "LOCKED")

    def test_ai_execution_count_zero(self):
        r = _normalize_india_record(self._nse_rec())
        self.assertEqual(r["ai_execution_count"], 0)

    def test_broker_api_called_false(self):
        r = _normalize_india_record(self._nse_rec())
        self.assertFalse(r["broker_api_called"])

    def test_change_field_preserved(self):
        r = _normalize_india_record(self._nse_rec(change=150.0))
        self.assertEqual(r["change"], 150.0)

    def test_sebi_event_id_unique(self):
        sebi_rec = {
            "index_name": "SEBI Regulatory Listings",
            "last_price": None, "change": None, "percent_change": None,
            "regulatory_source": "india_sebi",
            "regulatory_url": "https://www.sebi.gov.in/sebiweb/home/HomeAction.do",
            "regulatory_note": "SEBI listing page fetched (read-only)",
        }
        r1 = _normalize_india_record(self._rbi_rec())
        r2 = _normalize_india_record(sebi_rec)
        self.assertNotEqual(r1["event_id"], r2["event_id"])


# ---------------------------------------------------------------------------
# Loader init tests
# ---------------------------------------------------------------------------

class TestIndiaLoaderInit(unittest.TestCase):

    def test_default_source_name(self):
        from scripts.ingestion.india_loader import IndiaLoader
        self.assertEqual(IndiaLoader.source_name, "india")

    def test_requires_key_false(self):
        from scripts.ingestion.india_loader import IndiaLoader
        self.assertFalse(IndiaLoader.requires_key)

    def test_default_symbols_none(self):
        from scripts.ingestion.india_loader import IndiaLoader
        loader = IndiaLoader()
        self.assertIsNone(loader._symbols)

    def test_custom_symbols(self):
        from scripts.ingestion.india_loader import IndiaLoader
        loader = IndiaLoader(symbols=["NIFTY 50"])
        self.assertEqual(loader._symbols, ["NIFTY 50"])

    def test_max_items_default(self):
        from scripts.ingestion.india_loader import IndiaLoader
        loader = IndiaLoader()
        self.assertEqual(loader._max_items, 50)

    def test_max_items_custom(self):
        from scripts.ingestion.india_loader import IndiaLoader
        loader = IndiaLoader(max_items=5)
        self.assertEqual(loader._max_items, 5)

    def test_date_stored(self):
        from scripts.ingestion.india_loader import IndiaLoader
        loader = IndiaLoader(date="2026-05-10")
        self.assertEqual(loader._date, "2026-05-10")

    def test_date_none_by_default(self):
        from scripts.ingestion.india_loader import IndiaLoader
        loader = IndiaLoader()
        self.assertIsNone(loader._date)


# ---------------------------------------------------------------------------
# Missing requests library
# ---------------------------------------------------------------------------

class TestIndiaLoaderMissingRequests(unittest.TestCase):

    def test_skips_when_requests_missing(self):
        from scripts.ingestion.india_loader import IndiaLoader
        loader = IndiaLoader()
        with patch.dict(sys.modules, {"requests": None}):
            result = loader.safe_fetch()
        self.assertTrue(result.skipped)
        self.assertIn("requests", result.skip_reason.lower())

    def test_skip_reason_non_empty(self):
        from scripts.ingestion.india_loader import IndiaLoader
        loader = IndiaLoader()
        with patch.dict(sys.modules, {"requests": None}):
            result = loader.safe_fetch()
        self.assertTrue(len(result.skip_reason) > 0)


# ---------------------------------------------------------------------------
# Mocked HTTP tests
# ---------------------------------------------------------------------------

class TestIndiaLoaderMockedHTTP(unittest.TestCase):

    def _run_with_mocks(self, side_effects, **loader_kwargs):
        from scripts.ingestion.india_loader import IndiaLoader
        loader = IndiaLoader(**loader_kwargs)
        with patch("requests.get", side_effect=side_effects):
            return loader.safe_fetch()

    def test_successful_fetch_all_three(self):
        result = self._run_with_mocks(_all_mocks())
        self.assertFalse(result.skipped)
        # 3 NSE indices + 1 RBI + 1 SEBI
        self.assertEqual(len(result.records), 5)

    def test_source_name_on_result(self):
        result = self._run_with_mocks(_all_mocks())
        self.assertEqual(result.source_name, "india")

    def test_records_have_regulatory_source(self):
        result = self._run_with_mocks(_all_mocks())
        for rec in result.records:
            self.assertIn("regulatory_source", rec)
            self.assertIn("india", rec["regulatory_source"])

    def test_nse_records_have_index_name(self):
        result = self._run_with_mocks(_all_mocks())
        nse_recs = [r for r in result.records if "nse" in r.get("regulatory_source", "")]
        self.assertTrue(len(nse_recs) > 0)
        for rec in nse_recs:
            self.assertIn("index_name", rec)

    def test_rbi_record_present(self):
        result = self._run_with_mocks(_all_mocks())
        rbi = [r for r in result.records if r.get("regulatory_source") == "india_rbi"]
        self.assertEqual(len(rbi), 1)

    def test_sebi_record_present(self):
        result = self._run_with_mocks(_all_mocks())
        sebi = [r for r in result.records if r.get("regulatory_source") == "india_sebi"]
        self.assertEqual(len(sebi), 1)

    def test_advisory_stamps_on_all_records(self):
        result = self._run_with_mocks(_all_mocks())
        for rec in result.records:
            # _stamp_record() sets these three; ai_execution_count/broker_api_called
            # are added by the normalizer, not the loader.
            self.assertEqual(rec.get("advisory_status"), "ADVISORY_ONLY")
            self.assertTrue(rec.get("human_review_required"))
            self.assertEqual(rec.get("execution_gate"), "LOCKED")

    def test_nse_failure_rbi_sebi_still_fetched(self):
        from scripts.ingestion.india_loader import IndiaLoader
        loader = IndiaLoader()

        def side_effect(url, **kw):
            if "nseindia" in url:
                raise Exception("NSE down")
            if "rbi.org" in url:
                return _mock_rbi_response()
            return _mock_sebi_response()

        with patch("requests.get", side_effect=side_effect):
            result = loader.safe_fetch()

        self.assertFalse(result.skipped)
        self.assertEqual(len(result.records), 2)
        sources = {r["regulatory_source"] for r in result.records}
        self.assertIn("india_rbi", sources)
        self.assertIn("india_sebi", sources)

    def test_rbi_failure_nse_sebi_still_fetched(self):
        from scripts.ingestion.india_loader import IndiaLoader
        loader = IndiaLoader()

        def side_effect(url, **kw):
            if "rbi.org" in url:
                raise Exception("RBI down")
            if "nseindia" in url:
                return _mock_nse_response()
            return _mock_sebi_response()

        with patch("requests.get", side_effect=side_effect):
            result = loader.safe_fetch()

        self.assertFalse(result.skipped)
        sources = {r["regulatory_source"] for r in result.records}
        self.assertIn("india_nse", sources)
        self.assertIn("india_sebi", sources)
        self.assertNotIn("india_rbi", sources)

    def test_all_endpoints_fail_skips_cleanly(self):
        from scripts.ingestion.india_loader import IndiaLoader
        loader = IndiaLoader()
        with patch("requests.get", side_effect=Exception("network down")):
            result = loader.safe_fetch()
        self.assertTrue(result.skipped)
        self.assertIn("unreachable", result.skip_reason.lower())

    def test_max_items_respected(self):
        many = [
            {"index": f"IDX{i}", "last": float(i * 100), "change": 1.0, "percentChange": 0.1}
            for i in range(20)
        ]
        from scripts.ingestion.india_loader import IndiaLoader
        loader = IndiaLoader(
            symbols=[f"IDX{i}" for i in range(20)],
            max_items=3,
        )
        with patch("requests.get", side_effect=[
            _mock_nse_response(many),
            _mock_rbi_response(),
            _mock_sebi_response(),
        ]):
            result = loader.safe_fetch()
        self.assertLessEqual(len(result.records), 3)

    def test_custom_symbols_filtered(self):
        from scripts.ingestion.india_loader import IndiaLoader
        loader = IndiaLoader(symbols=["NIFTY 50"])
        with patch("requests.get", side_effect=_all_mocks()):
            result = loader.safe_fetch()
        nse_recs = [r for r in result.records if "nse" in r.get("regulatory_source", "")]
        index_names = [r["index_name"] for r in nse_recs]
        self.assertIn("NIFTY 50", index_names)
        self.assertNotIn("NIFTY BANK", index_names)
        self.assertNotIn("INDIA VIX", index_names)

    def test_nse_data_values_present(self):
        result = self._run_with_mocks(_all_mocks())
        nse_recs = [r for r in result.records if "nse" in r.get("regulatory_source", "")]
        nifty = next((r for r in nse_recs if r.get("index_name") == "NIFTY 50"), None)
        self.assertIsNotNone(nifty)
        self.assertEqual(nifty["last_price"], 22500.0)
        self.assertEqual(nifty["change"], 150.0)
        self.assertAlmostEqual(nifty["percent_change"], 0.67)

    def test_rbi_url_in_record(self):
        result = self._run_with_mocks(_all_mocks())
        rbi = next(r for r in result.records if r.get("regulatory_source") == "india_rbi")
        self.assertIn("rbi.org", rbi["regulatory_url"])

    def test_sebi_url_in_record(self):
        result = self._run_with_mocks(_all_mocks())
        sebi = next(r for r in result.records if r.get("regulatory_source") == "india_sebi")
        self.assertIn("sebi.gov", sebi["regulatory_url"])

    def test_http_error_on_nse_treated_as_partial(self):
        from scripts.ingestion.india_loader import IndiaLoader
        loader = IndiaLoader()
        nse_err = MagicMock()
        nse_err.raise_for_status.side_effect = Exception("HTTP 503")

        with patch("requests.get", side_effect=[nse_err, _mock_rbi_response(), _mock_sebi_response()]):
            result = loader.safe_fetch()

        self.assertFalse(result.skipped)
        self.assertEqual(len(result.records), 2)


# ---------------------------------------------------------------------------
# Phase 2 runner integration
# ---------------------------------------------------------------------------

class TestPhase2RunnerIndia(unittest.TestCase):

    def _run(self, dry_run=True):
        with patch("requests.get", side_effect=_all_mocks()):
            return run_phase2(dry_run=dry_run, sources=["india"])

    def test_returns_phase2_run_report(self):
        self.assertIsInstance(self._run(), Phase2RunReport)

    def test_report_has_india_source(self):
        report = self._run()
        names = [s.source_name for s in report.sources]
        self.assertIn("india", names)

    def test_status_ok(self):
        report = self._run()
        india = next(s for s in report.sources if s.source_name == "india")
        self.assertEqual(india.status, "ok")

    def test_fetched_count_nonzero(self):
        report = self._run()
        india = next(s for s in report.sources if s.source_name == "india")
        self.assertGreater(india.fetched_count, 0)

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

    def test_skipped_when_all_fail(self):
        with patch("requests.get", side_effect=Exception("all down")):
            report = run_phase2(dry_run=True, sources=["india"])
        india = next(s for s in report.sources if s.source_name == "india")
        self.assertEqual(india.status, "skipped")

    def test_unknown_source_ignored(self):
        with patch("requests.get", side_effect=_all_mocks()):
            report = run_phase2(dry_run=True, sources=["india", "nonexistent"])
        names = [s.source_name for s in report.sources]
        self.assertIn("india", names)
        self.assertNotIn("nonexistent", names)

    def test_india_custom_symbols_passed(self):
        with patch("requests.get", side_effect=_all_mocks()):
            report = run_phase2(
                dry_run=True,
                sources=["india"],
                india_symbols=["NIFTY 50"],
            )
        india = next(s for s in report.sources if s.source_name == "india")
        self.assertEqual(india.status, "ok")

    def test_india_max_items_param(self):
        with patch("requests.get", side_effect=_all_mocks()):
            report = run_phase2(
                dry_run=True,
                sources=["india"],
                india_max_items=2,
            )
        india = next(s for s in report.sources if s.source_name == "india")
        self.assertLessEqual(india.fetched_count, 2)

    def test_duration_ms_set(self):
        report = self._run()
        india = next(s for s in report.sources if s.source_name == "india")
        self.assertGreaterEqual(india.duration_ms, 0)

    def test_run_at_set(self):
        report = self._run()
        self.assertTrue(len(report.run_at) > 0)


# ---------------------------------------------------------------------------
# Write mode
# ---------------------------------------------------------------------------

class TestIndiaWriteMode(unittest.TestCase):

    def test_write_mode_calls_persist(self):
        with patch("requests.get", side_effect=_all_mocks()):
            with patch("scripts.live_source_runner_phase2._persist_events", return_value=5) as mock_p:
                with patch("scripts.live_source_runner_phase2._log_run") as mock_l:
                    report = run_phase2(dry_run=False, sources=["india"])
        mock_p.assert_called_once()
        mock_l.assert_called_once()
        india = next(s for s in report.sources if s.source_name == "india")
        self.assertEqual(india.events_persisted, 5)

    def test_dry_run_does_not_call_persist(self):
        with patch("requests.get", side_effect=_all_mocks()):
            with patch("scripts.live_source_runner_phase2._persist_events") as mock_p:
                run_phase2(dry_run=True, sources=["india"])
        mock_p.assert_not_called()

    def test_dry_run_does_not_call_log_run(self):
        with patch("requests.get", side_effect=_all_mocks()):
            with patch("scripts.live_source_runner_phase2._log_run") as mock_l:
                run_phase2(dry_run=True, sources=["india"])
        mock_l.assert_not_called()

    def test_write_mode_skipped_source_still_logged(self):
        with patch("requests.get", side_effect=Exception("all down")):
            with patch("scripts.live_source_runner_phase2._log_run") as mock_l:
                run_phase2(dry_run=False, sources=["india"])
        mock_l.assert_called_once()


# ---------------------------------------------------------------------------
# Safety invariants
# ---------------------------------------------------------------------------

class TestIndiaSafetyInvariants(unittest.TestCase):

    def _records(self):
        recs = [
            {
                "index_name": "NIFTY 50",
                "last_price": 22500.0,
                "change": 150.0,
                "percent_change": 0.67,
                "regulatory_source": "india_nse",
                "regulatory_url": "https://www.nseindia.com/api/allIndices",
                "regulatory_note": None,
            },
            {
                "index_name": "RBI Press Releases",
                "last_price": None,
                "change": None,
                "percent_change": None,
                "regulatory_source": "india_rbi",
                "regulatory_url": "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx",
                "regulatory_note": "RBI press release page fetched (read-only)",
            },
            {
                "index_name": "SEBI Regulatory Listings",
                "last_price": None,
                "change": None,
                "percent_change": None,
                "regulatory_source": "india_sebi",
                "regulatory_url": "https://www.sebi.gov.in/sebiweb/home/HomeAction.do",
                "regulatory_note": "SEBI listing page fetched (read-only)",
            },
        ]
        return [_normalize_india_record(r) for r in recs]

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

    def test_source_name_always_india(self):
        for r in self._records():
            self.assertEqual(r["source_name"], "india")

    def test_no_order_keys(self):
        forbidden_keys = {"order_id", "trade_id", "broker_order", "execution_id", "fill_price"}
        for r in self._records():
            self.assertEqual(set(r.keys()) & forbidden_keys, set())

    def test_phase2_report_advisory_only(self):
        with patch("requests.get", side_effect=_all_mocks()):
            report = run_phase2(dry_run=True, sources=["india"])
        self.assertEqual(report.advisory_status, "ADVISORY_ONLY")

    def test_phase2_report_broker_false(self):
        with patch("requests.get", side_effect=_all_mocks()):
            report = run_phase2(dry_run=True, sources=["india"])
        self.assertFalse(report.broker_api_called)

    def test_phase2_report_ai_zero(self):
        with patch("requests.get", side_effect=_all_mocks()):
            report = run_phase2(dry_run=True, sources=["india"])
        self.assertEqual(report.ai_execution_count, 0)


# ---------------------------------------------------------------------------
# AST — forbidden method check
# ---------------------------------------------------------------------------

class TestIndiaNoForbiddenMethods(unittest.TestCase):

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

    def test_india_loader_no_forbidden_methods(self):
        found = self._attr_calls(_REPO_ROOT / "scripts" / "ingestion" / "india_loader.py") & self._FORBIDDEN
        self.assertEqual(found, set(), f"Forbidden methods found: {found}")

    def test_runner_no_forbidden_methods(self):
        found = self._attr_calls(_REPO_ROOT / "scripts" / "live_source_runner_phase2.py") & self._FORBIDDEN
        self.assertEqual(found, set(), f"Forbidden methods found: {found}")

    def test_cli_no_forbidden_methods(self):
        found = self._attr_calls(_REPO_ROOT / "scripts" / "run_live_sources_phase2.py") & self._FORBIDDEN
        self.assertEqual(found, set(), f"Forbidden methods found: {found}")


# ---------------------------------------------------------------------------
# CLI / module structure
# ---------------------------------------------------------------------------

class TestIndiaCLIStructure(unittest.TestCase):

    def _load_cli_module(self):
        path = _REPO_ROOT / "scripts" / "run_live_sources_phase2.py"
        spec = importlib.util.spec_from_file_location("run_live_sources_phase2", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_india_in_supported_sources(self):
        mod = self._load_cli_module()
        self.assertIn("india", mod._SUPPORTED_SOURCES)

    def test_run_phase2_has_india_symbols_param(self):
        sig = inspect.signature(run_phase2)
        self.assertIn("india_symbols", sig.parameters)

    def test_run_phase2_has_india_date_param(self):
        sig = inspect.signature(run_phase2)
        self.assertIn("india_date", sig.parameters)

    def test_run_phase2_has_india_max_items_param(self):
        sig = inspect.signature(run_phase2)
        self.assertIn("india_max_items", sig.parameters)

    def test_normalize_india_record_exported(self):
        from scripts.live_source_runner_phase2 import __all__
        self.assertIn("_normalize_india_record", __all__)

    def test_india_loader_importable(self):
        from scripts.ingestion.india_loader import IndiaLoader
        self.assertIsNotNone(IndiaLoader)

    def test_run_phase2_dry_run_mocked(self):
        with patch("requests.get", side_effect=_all_mocks()):
            report = run_phase2(
                dry_run=True,
                sources=["india"],
                india_symbols=["NIFTY 50", "NIFTY BANK"],
                india_date="2026-05-10",
                india_max_items=10,
            )
        self.assertIsInstance(report, Phase2RunReport)
        india = next(s for s in report.sources if s.source_name == "india")
        self.assertIn(india.status, {"ok", "skipped"})

    def test_report_to_dict_has_sources_key(self):
        with patch("requests.get", side_effect=_all_mocks()):
            report = run_phase2(dry_run=True, sources=["india"])
        d = report.to_dict()
        self.assertIn("sources", d)
        self.assertIn("advisory_status", d)
        self.assertIn("broker_api_called", d)
        self.assertIn("ai_execution_count", d)


if __name__ == "__main__":
    unittest.main()
