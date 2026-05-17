"""Phase 7 acceptance tests for EDINET / OpenDART wiring inside Asia Disclosure.

Covers the 30-point checklist from the implementation prompt:
  * Env / config — missing keys do not call the network
  * Mocked EDINET success, HTTP error, empty response, parse error,
    safety-stamp invariants
  * Mocked OpenDART success, HTTP error, empty response, parse error,
    safety-stamp invariants
  * refresh_live_signals integration: no more
    ``adapter_planned_not_implemented`` for asia_disclosure; partial
    success allowed; one failure does not crash the run; persisted rows
    only from real parsed API responses; no fake rows
  * Source-state/UI: 11 coverage rows; India excluded; missing-key states
    excluded from stale
  * Safety: ADVISORY_ONLY, HUMAN_REVIEW_REQUIRED, execution_gate=LOCKED,
    broker_api_called=false, ai_execution_count=0, no execution endpoints
    introduced
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_SUBSOURCE_ENV_KEYS = (
    "EDINET_API_KEY",
    "JAPAN_EDINET_API_KEY",
    "OPENDART_API_KEY",
    "KOREA_DART_API_KEY",
)


def _env_without_subsource_keys() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in _SUBSOURCE_ENV_KEYS}


def _env_with(**overrides: str) -> dict[str, str]:
    env = _env_without_subsource_keys()
    env.update(overrides)
    return env


def _mock_edinet_response(results=None):
    """Return a MagicMock matching the EDINET v2 ``documents.json`` shape."""
    if results is None:
        results = [
            {
                "docID": "S100ABCD",
                "filerName": "Toyota Motor Corporation",
                "docTypeCode": "120",
                "docDescription": "Annual Securities Report",
                "submitDateTime": "2026-05-17 09:00",
                "secCode": "7203",
                "periodStart": "2025-04-01",
                "periodEnd": "2026-03-31",
            }
        ]
    payload = {"metadata": {"status": "200"}, "results": results}
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = payload
    m.raise_for_status.return_value = None
    return m


def _mock_opendart_response(items=None):
    """Return a MagicMock matching the OpenDART ``list.json`` shape."""
    if items is None:
        items = [
            {
                "corp_code": "00126380",
                "corp_name": "Samsung Electronics",
                "stock_code": "005930",
                "report_nm": "Quarterly Report",
                "rcept_no": "20260515000001",
                "rcept_dt": "20260515",
                "flr_nm": "Samsung Electronics",
            }
        ]
    payload = {"status": "000", "message": "정상", "list": items}
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = payload
    m.raise_for_status.return_value = None
    return m


# ---------------------------------------------------------------------------
# 1-3 — env handling
# ---------------------------------------------------------------------------


class TestEnvHandling(unittest.TestCase):
    def test_missing_edinet_key_does_not_call_network(self):
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader

        env = _env_without_subsource_keys()
        with patch.dict("os.environ", env, clear=True):
            with patch("requests.get") as mock_get:
                loader = AsiaDisclosureLoader(providers=["edinet"])
                result = loader.safe_fetch()
        self.assertTrue(result.skipped)
        self.assertIn("optional_config_missing", result.skip_reason.lower())
        mock_get.assert_not_called()

    def test_missing_opendart_key_does_not_call_network(self):
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader

        env = _env_without_subsource_keys()
        with patch.dict("os.environ", env, clear=True):
            with patch("requests.get") as mock_get:
                loader = AsiaDisclosureLoader(providers=["opendart"])
                result = loader.safe_fetch()
        self.assertTrue(result.skipped)
        self.assertIn("optional_config_missing", result.skip_reason.lower())
        mock_get.assert_not_called()

    def test_env_example_contains_placeholders_only(self):
        text = (_REPO_ROOT / ".env.example").read_text(encoding="utf-8")
        # Each key must appear with an empty (=) placeholder, not a value.
        for key in (
            "EDINET_API_KEY",
            "JAPAN_EDINET_API_KEY",
            "OPENDART_API_KEY",
            "KOREA_DART_API_KEY",
        ):
            self.assertIn(f"{key}=", text)
            # Verify the value after the equals is empty/blank on the same line.
            for line in text.splitlines():
                if line.strip().startswith(f"{key}="):
                    value = line.split("=", 1)[1].strip()
                    self.assertEqual(
                        value, "", f"{key} placeholder leaked a value in .env.example",
                    )

    def test_alias_env_is_accepted_for_edinet(self):
        from scripts.ingestion.asia_disclosure_loader import _resolve_provider_key, _PROVIDER_CONFIGS

        env = _env_with(JAPAN_EDINET_API_KEY="placeholder")
        with patch.dict("os.environ", env, clear=True):
            value = _resolve_provider_key(_PROVIDER_CONFIGS["edinet"])
        self.assertEqual(value, "placeholder")

    def test_alias_env_is_accepted_for_opendart(self):
        from scripts.ingestion.asia_disclosure_loader import _resolve_provider_key, _PROVIDER_CONFIGS

        env = _env_with(KOREA_DART_API_KEY="placeholder")
        with patch.dict("os.environ", env, clear=True):
            value = _resolve_provider_key(_PROVIDER_CONFIGS["opendart"])
        self.assertEqual(value, "placeholder")

    def test_primary_env_wins_over_alias(self):
        from scripts.ingestion.asia_disclosure_loader import _resolve_provider_key, _PROVIDER_CONFIGS

        env = _env_with(EDINET_API_KEY="primary", JAPAN_EDINET_API_KEY="alias")
        with patch.dict("os.environ", env, clear=True):
            value = _resolve_provider_key(_PROVIDER_CONFIGS["edinet"])
        self.assertEqual(value, "primary")


# ---------------------------------------------------------------------------
# 4-8 — EDINET mocked behaviour
# ---------------------------------------------------------------------------


class TestEDINETAdapter(unittest.TestCase):
    def test_success_normalises_at_least_one_row(self):
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader

        env = _env_with(EDINET_API_KEY="placeholder")
        with patch.dict("os.environ", env, clear=True):
            with patch("requests.get", return_value=_mock_edinet_response()):
                loader = AsiaDisclosureLoader(providers=["edinet"])
                result = loader.safe_fetch()
        self.assertFalse(result.skipped)
        self.assertGreaterEqual(len(result.records), 1)
        rec = result.records[0]
        self.assertEqual(rec["country"], "Japan")
        self.assertEqual(rec["disclosure_system"], "EDINET")
        self.assertEqual(rec["source_class"], "official_api")
        self.assertEqual(rec["provider"], "edinet")
        self.assertEqual(rec["issuer_name"], "Toyota Motor Corporation")
        self.assertEqual(rec["doc_id"], "S100ABCD")

    def test_http_error_becomes_skipped_with_reason(self):
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader

        err_mock = MagicMock()
        err_mock.status_code = 503
        err_mock.raise_for_status.side_effect = Exception("HTTP 503")

        env = _env_with(EDINET_API_KEY="placeholder")
        with patch.dict("os.environ", env, clear=True):
            with patch("requests.get", return_value=err_mock):
                loader = AsiaDisclosureLoader(providers=["edinet"])
                result = loader.safe_fetch()
        self.assertTrue(result.skipped)
        self.assertIn(
            "http",
            result.skip_reason.lower(),
        )

    def test_rate_limit_status_429_becomes_skipped_with_reason(self):
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader

        rl_mock = MagicMock()
        rl_mock.status_code = 429
        rl_mock.raise_for_status.return_value = None
        rl_mock.json.return_value = {}

        env = _env_with(EDINET_API_KEY="placeholder")
        with patch.dict("os.environ", env, clear=True):
            with patch("requests.get", return_value=rl_mock):
                loader = AsiaDisclosureLoader(providers=["edinet"])
                result = loader.safe_fetch()
        self.assertTrue(result.skipped)
        self.assertIn("rate_limited", result.skip_reason.lower())

    def test_empty_response_is_no_rows_not_fake_healthy(self):
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader

        env = _env_with(EDINET_API_KEY="placeholder")
        with patch.dict("os.environ", env, clear=True):
            with patch("requests.get", return_value=_mock_edinet_response(results=[])):
                loader = AsiaDisclosureLoader(providers=["edinet"])
                result = loader.safe_fetch()
        self.assertFalse(result.skipped)
        self.assertEqual(len(result.records), 0)
        # The honest no_rows signal is carried in skip_reason for diagnostics.
        self.assertIn("no_rows", result.skip_reason.lower())

    def test_parse_error_becomes_parse_error_skipped(self):
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader

        bad_mock = MagicMock()
        bad_mock.status_code = 200
        bad_mock.raise_for_status.return_value = None
        bad_mock.json.side_effect = ValueError("not json")

        env = _env_with(EDINET_API_KEY="placeholder")
        with patch.dict("os.environ", env, clear=True):
            with patch("requests.get", return_value=bad_mock):
                loader = AsiaDisclosureLoader(providers=["edinet"])
                result = loader.safe_fetch()
        self.assertTrue(result.skipped)
        self.assertIn("parse_error", result.skip_reason.lower())

    def test_row_carries_advisory_safety_fields(self):
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader

        env = _env_with(EDINET_API_KEY="placeholder")
        with patch.dict("os.environ", env, clear=True):
            with patch("requests.get", return_value=_mock_edinet_response()):
                loader = AsiaDisclosureLoader(providers=["edinet"])
                result = loader.safe_fetch()
        rec = result.records[0]
        self.assertEqual(rec["advisory_status"], "ADVISORY_ONLY")
        self.assertTrue(rec["human_review_required"])
        self.assertEqual(rec["execution_gate"], "LOCKED")

    def test_does_not_leak_api_key_into_record(self):
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader

        secret = "EDINET_SECRET_PLACEHOLDER"
        env = _env_with(EDINET_API_KEY=secret)
        with patch.dict("os.environ", env, clear=True):
            with patch("requests.get", return_value=_mock_edinet_response()):
                loader = AsiaDisclosureLoader(providers=["edinet"])
                result = loader.safe_fetch()
        for rec in result.records:
            blob = json.dumps(rec)
            self.assertNotIn(secret, blob)


# ---------------------------------------------------------------------------
# 9-13 — OpenDART mocked behaviour
# ---------------------------------------------------------------------------


class TestOpenDARTAdapter(unittest.TestCase):
    def test_success_normalises_at_least_one_row(self):
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader

        env = _env_with(OPENDART_API_KEY="placeholder")
        with patch.dict("os.environ", env, clear=True):
            with patch("requests.get", return_value=_mock_opendart_response()):
                loader = AsiaDisclosureLoader(providers=["opendart"])
                result = loader.safe_fetch()
        self.assertFalse(result.skipped)
        self.assertGreaterEqual(len(result.records), 1)
        rec = result.records[0]
        self.assertEqual(rec["country"], "South Korea")
        self.assertEqual(rec["disclosure_system"], "OpenDART")
        self.assertEqual(rec["source_class"], "official_api")
        self.assertEqual(rec["provider"], "opendart")
        self.assertEqual(rec["issuer_name"], "Samsung Electronics")
        self.assertEqual(rec["receipt_no"], "20260515000001")
        # URL is constructed from the receipt number; no fabrication.
        self.assertTrue(
            rec["url"].startswith("https://dart.fss.or.kr/"),
            f"unexpected URL: {rec['url']!r}",
        )

    def test_http_error_becomes_skipped_with_reason(self):
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader

        err_mock = MagicMock()
        err_mock.status_code = 500
        err_mock.raise_for_status.side_effect = Exception("HTTP 500")

        env = _env_with(OPENDART_API_KEY="placeholder")
        with patch.dict("os.environ", env, clear=True):
            with patch("requests.get", return_value=err_mock):
                loader = AsiaDisclosureLoader(providers=["opendart"])
                result = loader.safe_fetch()
        self.assertTrue(result.skipped)
        self.assertIn("http", result.skip_reason.lower())

    def test_opendart_status_020_is_rate_limited(self):
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader

        rl_mock = MagicMock()
        rl_mock.status_code = 200
        rl_mock.raise_for_status.return_value = None
        rl_mock.json.return_value = {"status": "020", "message": "limit"}

        env = _env_with(OPENDART_API_KEY="placeholder")
        with patch.dict("os.environ", env, clear=True):
            with patch("requests.get", return_value=rl_mock):
                loader = AsiaDisclosureLoader(providers=["opendart"])
                result = loader.safe_fetch()
        self.assertTrue(result.skipped)
        self.assertIn("rate_limited", result.skip_reason.lower())

    def test_empty_response_is_no_rows_not_fake_healthy(self):
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader

        env = _env_with(OPENDART_API_KEY="placeholder")
        with patch.dict("os.environ", env, clear=True):
            with patch("requests.get", return_value=_mock_opendart_response(items=[])):
                loader = AsiaDisclosureLoader(providers=["opendart"])
                result = loader.safe_fetch()
        self.assertFalse(result.skipped)
        self.assertEqual(len(result.records), 0)
        self.assertIn("no_rows", result.skip_reason.lower())

    def test_opendart_status_013_no_data_is_no_rows(self):
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader

        no_data_mock = MagicMock()
        no_data_mock.status_code = 200
        no_data_mock.raise_for_status.return_value = None
        no_data_mock.json.return_value = {"status": "013", "message": "no data"}

        env = _env_with(OPENDART_API_KEY="placeholder")
        with patch.dict("os.environ", env, clear=True):
            with patch("requests.get", return_value=no_data_mock):
                loader = AsiaDisclosureLoader(providers=["opendart"])
                result = loader.safe_fetch()
        self.assertFalse(result.skipped)
        self.assertEqual(len(result.records), 0)

    def test_parse_error_becomes_parse_error_skipped(self):
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader

        bad_mock = MagicMock()
        bad_mock.status_code = 200
        bad_mock.raise_for_status.return_value = None
        bad_mock.json.side_effect = ValueError("not json")

        env = _env_with(OPENDART_API_KEY="placeholder")
        with patch.dict("os.environ", env, clear=True):
            with patch("requests.get", return_value=bad_mock):
                loader = AsiaDisclosureLoader(providers=["opendart"])
                result = loader.safe_fetch()
        self.assertTrue(result.skipped)
        self.assertIn("parse_error", result.skip_reason.lower())

    def test_row_carries_advisory_safety_fields(self):
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader

        env = _env_with(OPENDART_API_KEY="placeholder")
        with patch.dict("os.environ", env, clear=True):
            with patch("requests.get", return_value=_mock_opendart_response()):
                loader = AsiaDisclosureLoader(providers=["opendart"])
                result = loader.safe_fetch()
        rec = result.records[0]
        self.assertEqual(rec["advisory_status"], "ADVISORY_ONLY")
        self.assertTrue(rec["human_review_required"])
        self.assertEqual(rec["execution_gate"], "LOCKED")

    def test_does_not_leak_api_key_into_record(self):
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader

        secret = "OPENDART_SECRET_PLACEHOLDER"
        env = _env_with(OPENDART_API_KEY=secret)
        with patch.dict("os.environ", env, clear=True):
            with patch("requests.get", return_value=_mock_opendart_response()):
                loader = AsiaDisclosureLoader(providers=["opendart"])
                result = loader.safe_fetch()
        for rec in result.records:
            blob = json.dumps(rec)
            self.assertNotIn(secret, blob)


# ---------------------------------------------------------------------------
# 14-18 — refresh_live_signals integration
# ---------------------------------------------------------------------------


class TestRefreshIntegration(unittest.TestCase):
    def _isolated(self, tmp_db: Path):
        import scripts.persistence as p

        p.init_schema(tmp_db)
        return p

    def test_refresh_no_longer_returns_adapter_planned_not_implemented(self):
        """Asia Disclosure adapter is now implemented (partial); the legacy
        ``adapter_planned_not_implemented`` skip reason must not appear."""
        from scripts import refresh_live_signals as rls

        env = _env_without_subsource_keys()
        with patch.dict("os.environ", env, clear=True):
            summary = rls.run_refresh(
                source_keys=["asia_disclosure"], write_mode=False
            )
        entries = summary["entries"]
        self.assertEqual(len(entries), 1)
        asia = entries[0]
        self.assertNotEqual(asia["skipped_reason"], "adapter_planned_not_implemented")

    def test_partial_success_is_allowed(self):
        """If one sub-source returns rows and another fails, the parent
        loader still returns records and the runner reports ok."""
        from scripts.live_source_runner_phase2 import run_phase2

        env = _env_with(EDINET_API_KEY="placeholder", OPENDART_API_KEY="placeholder")

        def _side_effect(url, params=None, headers=None, timeout=None):
            target = str(url)
            if "edinet-fsa.go.jp" in target:
                return _mock_edinet_response()
            if "opendart.fss.or.kr" in target:
                err = MagicMock()
                err.status_code = 500
                err.raise_for_status.side_effect = Exception("HTTP 500")
                return err
            raise AssertionError(f"unexpected url: {target}")

        with patch.dict("os.environ", env, clear=True):
            with patch("requests.get", side_effect=_side_effect):
                report = run_phase2(dry_run=True, sources=["asia_disclosure"])
        asia = next(s for s in report.sources if s.source_name == "asia_disclosure")
        self.assertEqual(asia.status, "ok")
        self.assertGreaterEqual(asia.fetched_count, 1)

    def test_one_failure_does_not_crash_full_refresh(self):
        """A sub-source raising exceptions must NOT bubble into the
        refresh orchestrator."""
        from scripts import refresh_live_signals as rls

        env = _env_with(OPENDART_API_KEY="placeholder")

        def _side_effect(url, params=None, headers=None, timeout=None):
            raise RuntimeError("network down")

        with patch.dict("os.environ", env, clear=True):
            with patch("requests.get", side_effect=_side_effect):
                # Should not raise.
                summary = rls.run_refresh(
                    source_keys=["asia_disclosure"], write_mode=False
                )
        self.assertEqual(summary["operation"], "refresh_live_signals")
        self.assertEqual(len(summary["entries"]), 1)

    def test_persisted_rows_only_from_real_parsed_responses(self):
        """In write mode, only real parsed API rows reach signal_events.

        Persistence uses the live DB by default; rather than fight Python
        default-argument capture in ``insert_signal_event``, we verify the
        contract end-to-end by asserting that the normalized event payload
        produced from a real EDINET response carries the EDINET stamps
        and is exactly what ``_persist_events`` would write.
        """
        from scripts.live_source_runner_phase2 import (
            _normalize_asia_disclosure_record,
            run_phase2,
        )

        env = _env_with(EDINET_API_KEY="placeholder")
        captured_events: list[dict] = []

        def _capture(events, source_name, fetched_at):
            captured_events.extend(events)
            return len(events)

        with patch.dict("os.environ", env, clear=True):
            with patch("requests.get", return_value=_mock_edinet_response()):
                with patch(
                    "scripts.live_source_runner_phase2._persist_events",
                    side_effect=_capture,
                ):
                    with patch(
                        "scripts.live_source_runner_phase2._log_run"
                    ):
                        report = run_phase2(
                            dry_run=False, sources=["asia_disclosure"]
                        )

        # Real parsed API rows reached the persist boundary.
        self.assertGreaterEqual(len(captured_events), 1)
        for ev in captured_events:
            self.assertEqual(ev["source_name"], "asia_disclosure")
            self.assertEqual(ev["disclosure_system"], "EDINET")
            self.assertEqual(ev["country"], "Japan")
            self.assertEqual(ev["source_class"], "official_api")
            self.assertEqual(ev["advisory_status"], "ADVISORY_ONLY")
            self.assertEqual(ev["execution_gate"], "LOCKED")
            self.assertFalse(ev["broker_api_called"])
            self.assertEqual(ev["ai_execution_count"], 0)
        # Runner reports ok with non-zero events_persisted.
        asia = next(
            s for s in report.sources if s.source_name == "asia_disclosure"
        )
        self.assertEqual(asia.status, "ok")
        self.assertGreaterEqual(asia.events_persisted, 1)

    def test_no_fake_rows_when_keys_missing(self):
        """Without keys, _persist_events is never called for asia_disclosure
        and no HTTP fetch occurs.  Equivalent to "no fake rows reach the
        DB boundary"."""
        from scripts.live_source_runner_phase2 import run_phase2

        env = _env_without_subsource_keys()
        with patch.dict("os.environ", env, clear=True):
            with patch("requests.get") as mock_get:
                with patch(
                    "scripts.live_source_runner_phase2._persist_events"
                ) as mock_persist:
                    with patch(
                        "scripts.live_source_runner_phase2._log_run"
                    ):
                        run_phase2(dry_run=False, sources=["asia_disclosure"])
        mock_get.assert_not_called()
        mock_persist.assert_not_called()


# ---------------------------------------------------------------------------
# 19-24 — source-state / UI truthfulness
# ---------------------------------------------------------------------------


class TestSourceStateAndUI(unittest.TestCase):
    def test_coverage_rows_remain_exactly_11(self):
        from scripts.ingestion.asia_disclosure_loader import (
            get_asia_disclosure_country_rows,
        )

        rows = get_asia_disclosure_country_rows()
        self.assertEqual(len(rows), 11)

    def test_india_excluded_from_asia_disclosure(self):
        from scripts.ingestion.asia_disclosure_loader import (
            get_asia_disclosure_countries,
        )

        countries = get_asia_disclosure_countries()
        self.assertNotIn("India", countries)

    def test_india_family_remains_implemented(self):
        from scripts.live_source_registry import get_source_family, ALL_SOURCE_KEYS

        self.assertIn("india", ALL_SOURCE_KEYS)
        india = get_source_family("india")
        self.assertEqual(india["adapter_status"], "implemented")

    def test_missing_keys_excluded_from_stale(self):
        """When EDINET/OpenDART are missing, asia_disclosure is excluded
        from the stale count with reason optional_config_missing."""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "ui.db"
            import scripts.persistence as p

            p.init_schema(db_path)
            with patch.object(p, "DB_PATH", db_path):
                env = _env_without_subsource_keys()
                with patch.dict("os.environ", env, clear=True):
                    from scripts.api_server import _build_live_sources_status

                    payload = _build_live_sources_status(
                        now_iso="2026-05-17T17:00:00+00:00"
                    )
                self.assertNotIn("asia_disclosure", payload["stale_sources"])
                excluded = {
                    (e["source"], e["reason"])
                    for e in payload.get("excluded_from_stale", [])
                }
                self.assertIn(
                    ("asia_disclosure", "optional_config_missing"), excluded
                )

    def test_configured_failures_surface_as_degraded(self):
        """When keys are configured and a refresh records an error, the
        source must surface a real error message rather than fake healthy."""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "ui.db"
            import scripts.persistence as p

            p.init_schema(db_path)
            with patch.object(p, "DB_PATH", db_path):
                p.record_live_source_refresh_run(
                    run_id="r1",
                    source_name="asia_disclosure",
                    attempted=True,
                    success=False,
                    skipped=False,
                    started_at="2026-05-10T17:00:00+00:00",
                    finished_at="2026-05-10T17:00:01+00:00",
                    duration_seconds=1.0,
                    rows_before=0,
                    rows_after=0,
                    rows_added=0,
                    error_message="HTTP 503 from edinet",
                    db_path=db_path,
                )
                env = _env_with(EDINET_API_KEY="placeholder")
                with patch.dict("os.environ", env, clear=True):
                    from scripts.api_server import _build_live_sources_status

                    payload = _build_live_sources_status(
                        now_iso="2026-05-17T17:00:00+00:00"
                    )
                entry = payload["sources"]["asia_disclosure"]
                # Configured + last refresh was a failure days ago → stale.
                self.assertTrue(entry["is_stale"])
                # Error must be surfaced honestly.
                self.assertIn(
                    "503",
                    payload.get("source_errors", {}).get("asia_disclosure", ""),
                )

    def test_fresh_api_rows_only_when_within_freshness_threshold(self):
        """A successful refresh row newer than the threshold marks the
        source fresh; an older one does not flip to fake current_live."""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "ui.db"
            import scripts.persistence as p

            p.init_schema(db_path)
            with patch.object(p, "DB_PATH", db_path):
                # Recent OK log → fresh.
                p.log_source_run(
                    source_name="asia_disclosure",
                    status="ok",
                    fetched_count=3,
                    skipped_reason="",
                    error_message="",
                    timestamp_utc="2026-05-17T16:55:00+00:00",
                    duration_ms=20,
                    db_path=db_path,
                )
                p.record_live_source_refresh_run(
                    run_id="r1",
                    source_name="asia_disclosure",
                    attempted=True,
                    success=True,
                    skipped=False,
                    started_at="2026-05-17T16:55:00+00:00",
                    finished_at="2026-05-17T16:55:01+00:00",
                    duration_seconds=1.0,
                    rows_before=0,
                    rows_after=3,
                    rows_added=3,
                    db_path=db_path,
                )
                p.insert_signal_event(
                    event_id="asia_disclosure_test_1",
                    source_name="asia_disclosure",
                    raw_payload={"title": "EDINET test", "disclosure_system": "EDINET"},
                    fetched_at="2026-05-17T16:55:00+00:00",
                    db_path=db_path,
                )

                env = _env_with(EDINET_API_KEY="placeholder")
                with patch.dict("os.environ", env, clear=True):
                    from scripts.api_server import _build_live_sources_status

                    payload = _build_live_sources_status(
                        now_iso="2026-05-17T17:00:00+00:00"
                    )
                entry = payload["sources"]["asia_disclosure"]
                self.assertTrue(entry["is_current_live"])
                self.assertFalse(entry["is_stale"])


# ---------------------------------------------------------------------------
# 25-30 — safety invariants
# ---------------------------------------------------------------------------


class TestSafetyInvariants(unittest.TestCase):
    def test_records_are_advisory_only(self):
        from scripts.ingestion.asia_disclosure_loader import AsiaDisclosureLoader

        env = _env_with(EDINET_API_KEY="placeholder", OPENDART_API_KEY="placeholder")
        with patch.dict("os.environ", env, clear=True):
            def _side(url, **_kw):
                return (
                    _mock_edinet_response()
                    if "edinet-fsa.go.jp" in str(url)
                    else _mock_opendart_response()
                )

            with patch("requests.get", side_effect=_side):
                loader = AsiaDisclosureLoader(providers=["edinet", "opendart"])
                result = loader.safe_fetch()
        self.assertFalse(result.skipped)
        for rec in result.records:
            self.assertEqual(rec["advisory_status"], "ADVISORY_ONLY")
            self.assertTrue(rec["human_review_required"])
            self.assertEqual(rec["execution_gate"], "LOCKED")

    def test_normalized_records_have_safety_stamps(self):
        from scripts.live_source_runner_phase2 import _normalize_asia_disclosure_record

        rec = _normalize_asia_disclosure_record(
            {
                "issuer_name": "Toyota",
                "ticker_or_identifier": "7203",
                "exchange_or_regulator": "EDINET",
                "jurisdiction": "JP",
                "country": "Japan",
                "disclosure_system": "EDINET",
                "source_class": "official_api",
                "disclosure_type": "edinet_filing",
                "published_at": "2026-05-17",
                "url": "",
                "title": "Annual Securities Report",
                "summary": "",
                "provider": "edinet",
                "doc_id": "S100ABCD",
                "raw_payload": {},
            }
        )
        self.assertEqual(rec["advisory_status"], "ADVISORY_ONLY")
        self.assertTrue(rec["human_review_required"])
        self.assertEqual(rec["execution_gate"], "LOCKED")
        self.assertEqual(rec["ai_execution_count"], 0)
        self.assertFalse(rec["broker_api_called"])
        self.assertFalse(rec["execution_permission"])
        self.assertFalse(rec["can_execute"])
        self.assertEqual(rec["broker_order_id"], "NONE")

    def test_phase2_report_safety_stamps(self):
        from scripts.live_source_runner_phase2 import run_phase2

        env = _env_with(EDINET_API_KEY="placeholder")
        with patch.dict("os.environ", env, clear=True):
            with patch("requests.get", return_value=_mock_edinet_response()):
                report = run_phase2(dry_run=True, sources=["asia_disclosure"])
        self.assertEqual(report.advisory_status, "ADVISORY_ONLY")
        self.assertEqual(report.execution_gate, "LOCKED")
        self.assertFalse(report.broker_api_called)
        self.assertEqual(report.ai_execution_count, 0)
        self.assertTrue(report.human_review_required)

    def test_no_execution_endpoints_introduced(self):
        from scripts import api_server

        forbidden = (
            "place_order",
            "submit_order",
            "broker_execute",
            "send_to_broker",
            "trade_execute",
            "live_trade_execute",
            "broker.connect",
            "broker.place",
        )
        text = Path(api_server.__file__).read_text(encoding="utf-8")
        for token in forbidden:
            self.assertNotIn(token, text, f"forbidden token {token!r} introduced")

    def test_loader_module_has_no_execution_methods(self):
        import ast

        path = _REPO_ROOT / "scripts" / "ingestion" / "asia_disclosure_loader.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        forbidden = {
            "place_order",
            "submit_order",
            "create_order",
            "send_order",
            "execute_trade",
            "buy",
            "sell",
            "transfer",
            "send_transaction",
            "sign_transaction",
            "broadcast_transaction",
        }
        attrs = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertEqual(attrs & forbidden, set())


if __name__ == "__main__":
    unittest.main()
