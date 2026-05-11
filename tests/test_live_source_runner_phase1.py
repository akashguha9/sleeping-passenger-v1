"""
Tests for Phase 1 live source runner.

Principles
----------
- Zero live network calls. All HTTP is intercepted with unittest.mock.patch.
- Tests verify advisory contract, normalization, dry-run vs write-mode,
  missing-key skips (SEC EDGAR), persistence correctness, and no-execution safety.
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
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db(tmp_path: Path) -> Path:
    return tmp_path / "test_live.db"


@pytest.fixture()
def polymarket_payload() -> list[dict]:
    return [
        {
            "id": "mkt-001",
            "question": "Will inflation exceed 3% in 2026?",
            "volume": 100_000.0,
            "liquidity": 50_000.0,
            "endDate": "2026-12-31",
            "active": True,
        },
        {
            "id": "mkt-002",
            "question": "Will the Fed cut rates by Q3 2026?",
            "volume": 75_000.0,
            "liquidity": 30_000.0,
            "endDate": "2026-09-30",
            "active": True,
        },
    ]


@pytest.fixture()
def gdelt_payload() -> dict:
    return {
        "articles": [
            {
                "url": "https://example.com/article/1",
                "title": "Global markets rally on inflation data",
                "seendate": "2026-05-09T10:00:00Z",
                "domain": "example.com",
                "language": "English",
                "sourcecountry": "US",
            },
            {
                "url": "https://example.com/article/2",
                "title": "SEC investigates hedge fund activity",
                "seendate": "2026-05-09T09:00:00Z",
                "domain": "example.com",
                "language": "English",
                "sourcecountry": "US",
            },
        ]
    }


@pytest.fixture()
def sec_payload() -> dict:
    return {
        "filings": {
            "recent": {
                "form": ["10-K", "10-Q", "10-K"],
                "filingDate": ["2026-03-01", "2026-02-01", "2025-03-01"],
                "accessionNumber": [
                    "0001234567-26-000001",
                    "0001234567-26-000002",
                    "0001234567-25-000001",
                ],
            }
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
    def test_phase1_report_defaults(self) -> None:
        from scripts.live_source_runner import Phase1RunReport

        r = Phase1RunReport(dry_run=True, run_at="t")
        assert r.advisory_status == "ADVISORY_ONLY"
        assert r.execution_gate == "LOCKED"
        assert r.ai_execution_count == 0
        assert r.human_review_required is True

    def test_source_run_result_defaults(self) -> None:
        from scripts.live_source_runner import SourceRunResult

        s = SourceRunResult(source_name="polymarket", status="ok", timestamp_utc="t")
        assert s.advisory_status == "ADVISORY_ONLY"

    def test_report_to_dict_carries_advisory_fields(self) -> None:
        from scripts.live_source_runner import Phase1RunReport

        d = Phase1RunReport(dry_run=True, run_at="t").to_dict()
        assert d["advisory_status"] == "ADVISORY_ONLY"
        assert d["execution_gate"] == "LOCKED"
        assert d["ai_execution_count"] == 0
        assert d["human_review_required"] is True

    def test_report_to_dict_no_trade_or_broker_fields(self) -> None:
        from scripts.live_source_runner import Phase1RunReport

        d = Phase1RunReport(dry_run=True, run_at="t").to_dict()
        forbidden_keys = {"trade_id", "broker_order_id", "executed", "order_id"}
        assert not forbidden_keys & set(d.keys())


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


class TestNormalization:
    def test_normalize_polymarket(self) -> None:
        from scripts.live_source_runner import _normalize_polymarket_record

        rec = {
            "market_id": "mkt-abc",
            "question": "Will the Fed cut rates in 2026?",
            "volume": 100.0,
            "active": True,
            "source": "polymarket",
        }
        out = _normalize_polymarket_record(rec)
        assert out["source_name"] == "polymarket"
        assert out["signal_type"] == "prediction_market"
        assert out["title"] == "Will the Fed cut rates in 2026?"
        assert out["advisory_status"] == "ADVISORY_ONLY"
        assert out["human_review_required"] is True
        assert out["execution_gate"] == "LOCKED"
        assert out["ai_execution_count"] == 0
        assert out["event_id"].startswith("polymarket_")
        assert len(out["event_id"]) == len("polymarket_") + 16

    def test_normalize_gdelt(self) -> None:
        from scripts.live_source_runner import _normalize_gdelt_record

        rec = {"url": "https://x.com/a", "title": "News", "seendate": "2026-05-09"}
        out = _normalize_gdelt_record(rec)
        assert out["source_name"] == "gdelt"
        assert out["signal_type"] == "news_event"
        assert out["advisory_status"] == "ADVISORY_ONLY"
        assert out["event_id"].startswith("gdelt_")

    def test_normalize_sec_edgar(self) -> None:
        from scripts.live_source_runner import _normalize_sec_record

        rec = {
            "cik": "0000320193",
            "form_type": "10-K",
            "filing_date": "2026-03-01",
            "accession_number": "001-001",
        }
        out = _normalize_sec_record(rec)
        assert out["source_name"] == "sec_edgar"
        assert out["signal_type"] == "sec_filing"
        assert "10-K" in out["title"]
        assert out["advisory_status"] == "ADVISORY_ONLY"
        assert out["event_id"].startswith("sec_edgar_")

    def test_stable_event_id_deterministic(self) -> None:
        from scripts.live_source_runner import _stable_event_id

        assert _stable_event_id("polymarket", "mkt-001") == _stable_event_id(
            "polymarket", "mkt-001"
        )

    def test_stable_event_id_different_markets(self) -> None:
        from scripts.live_source_runner import _stable_event_id

        assert _stable_event_id("polymarket", "mkt-001") != _stable_event_id(
            "polymarket", "mkt-002"
        )

    def test_stable_event_id_different_sources(self) -> None:
        from scripts.live_source_runner import _stable_event_id

        assert _stable_event_id("polymarket", "x") != _stable_event_id("gdelt", "x")

    def test_all_normalized_records_advisory_stamped(self, polymarket_payload) -> None:
        from scripts.live_source_runner import _normalize_polymarket_record

        for raw in polymarket_payload:
            raw_with_market_id = {**raw, "market_id": raw["id"]}
            out = _normalize_polymarket_record(raw_with_market_id)
            assert out["advisory_status"] == "ADVISORY_ONLY"
            assert out["human_review_required"] is True
            assert out["execution_gate"] == "LOCKED"
            assert out["ai_execution_count"] == 0


# ---------------------------------------------------------------------------
# Polymarket — mocked HTTP
# ---------------------------------------------------------------------------


class TestPolymarketMocked:
    def test_dry_run_fetches_correct_count(self, polymarket_payload) -> None:
        from scripts.ingestion.base_loader import SkipLoader

        with patch("requests.get", return_value=_mock_response(polymarket_payload)):
            from scripts.live_source_runner import run_phase1
            with (
                patch("scripts.ingestion.gdelt_loader.GDELTLoader.fetch", side_effect=SkipLoader("skip")),
                patch("scripts.ingestion.sec_edgar_loader.SECEdgarLoader.fetch", side_effect=SkipLoader("skip")),
            ):
                report = run_phase1(dry_run=True)

        poly = next(s for s in report.sources if s.source_name == "polymarket")
        assert poly.status == "ok"
        assert poly.fetched_count == 2
        assert poly.events_persisted == 0  # dry-run → never persists
        assert report.advisory_status == "ADVISORY_ONLY"
        assert report.ai_execution_count == 0

    def test_dry_run_never_calls_persist(self, polymarket_payload) -> None:
        from scripts.ingestion.base_loader import SkipLoader

        with patch("requests.get", return_value=_mock_response(polymarket_payload)):
            from scripts.live_source_runner import run_phase1
            with (
                patch("scripts.ingestion.gdelt_loader.GDELTLoader.fetch", side_effect=SkipLoader("skip")),
                patch("scripts.ingestion.sec_edgar_loader.SECEdgarLoader.fetch", side_effect=SkipLoader("skip")),
                patch("scripts.live_source_runner._persist_events") as persist_mock,
            ):
                run_phase1(dry_run=True)
                persist_mock.assert_not_called()

    def test_network_error_yields_skipped_source(self) -> None:
        from scripts.ingestion.base_loader import SkipLoader

        with patch("requests.get", side_effect=Exception("network down")):
            from scripts.live_source_runner import run_phase1
            with (
                patch("scripts.ingestion.gdelt_loader.GDELTLoader.fetch", side_effect=SkipLoader("skip")),
                patch("scripts.ingestion.sec_edgar_loader.SECEdgarLoader.fetch", side_effect=SkipLoader("skip")),
            ):
                report = run_phase1(dry_run=True)

        poly = next(s for s in report.sources if s.source_name == "polymarket")
        assert poly.status == "skipped"
        assert poly.fetched_count == 0


# ---------------------------------------------------------------------------
# GDELT — mocked HTTP
# ---------------------------------------------------------------------------


class TestGDELTMocked:
    def test_dry_run_fetches_correct_count(self, gdelt_payload) -> None:
        from scripts.ingestion.base_loader import SkipLoader

        with patch("requests.get", return_value=_mock_response(gdelt_payload)):
            from scripts.live_source_runner import run_phase1
            with (
                patch("scripts.ingestion.polymarket_loader.PolymarketLoader.fetch", side_effect=SkipLoader("skip")),
                patch("scripts.ingestion.sec_edgar_loader.SECEdgarLoader.fetch", side_effect=SkipLoader("skip")),
            ):
                report = run_phase1(dry_run=True)

        gdelt = next(s for s in report.sources if s.source_name == "gdelt")
        assert gdelt.status == "ok"
        assert gdelt.fetched_count == 2
        assert gdelt.events_persisted == 0

    def test_gdelt_records_advisory_stamped(self, gdelt_payload) -> None:
        from scripts.ingestion.base_loader import SkipLoader

        with patch("requests.get", return_value=_mock_response(gdelt_payload)):
            from scripts.live_source_runner import _normalize_gdelt_record

        for art in gdelt_payload["articles"]:
            out = _normalize_gdelt_record(art)
            assert out["advisory_status"] == "ADVISORY_ONLY"
            assert out["human_review_required"] is True


# ---------------------------------------------------------------------------
# SEC EDGAR — skip without env var
# ---------------------------------------------------------------------------


class TestSECEdgarSkip:
    def test_skips_cleanly_without_env_var(self) -> None:
        os.environ.pop("SEC_USER_AGENT", None)
        from scripts.ingestion.base_loader import SkipLoader

        with patch("requests.get", side_effect=Exception("should not be called")):
            from scripts.live_source_runner import run_phase1
            with (
                patch("scripts.ingestion.polymarket_loader.PolymarketLoader.fetch", side_effect=SkipLoader("skip")),
                patch("scripts.ingestion.gdelt_loader.GDELTLoader.fetch", side_effect=SkipLoader("skip")),
            ):
                report = run_phase1(dry_run=True)

        sec = next(s for s in report.sources if s.source_name == "sec_edgar")
        assert sec.status == "skipped"
        assert sec.fetched_count == 0
        assert sec.skipped_reason  # non-empty

    def test_runs_with_env_var_set(self, sec_payload) -> None:
        os.environ["SEC_USER_AGENT"] = "TestAgent test@example.com"
        try:
            from scripts.ingestion.base_loader import SkipLoader

            with patch("requests.get", return_value=_mock_response(sec_payload)):
                from scripts.live_source_runner import run_phase1
                with (
                    patch("scripts.ingestion.polymarket_loader.PolymarketLoader.fetch", side_effect=SkipLoader("skip")),
                    patch("scripts.ingestion.gdelt_loader.GDELTLoader.fetch", side_effect=SkipLoader("skip")),
                ):
                    report = run_phase1(dry_run=True, sec_cik="0000320193")

            sec = next(s for s in report.sources if s.source_name == "sec_edgar")
            # 10-K filings only — 2 of the 3 rows match
            assert sec.status == "ok"
            assert sec.fetched_count == 2
        finally:
            os.environ.pop("SEC_USER_AGENT", None)


# ---------------------------------------------------------------------------
# Write-mode persistence
# ---------------------------------------------------------------------------


class TestWriteMode:
    def test_write_mode_calls_persist(self, polymarket_payload) -> None:
        from scripts.ingestion.base_loader import SkipLoader

        with patch("requests.get", return_value=_mock_response(polymarket_payload)):
            from scripts.live_source_runner import run_phase1
            with (
                patch("scripts.ingestion.gdelt_loader.GDELTLoader.fetch", side_effect=SkipLoader("skip")),
                patch("scripts.ingestion.sec_edgar_loader.SECEdgarLoader.fetch", side_effect=SkipLoader("skip")),
                patch("scripts.live_source_runner._persist_events", return_value=2) as persist_mock,
                patch("scripts.live_source_runner._log_run"),
            ):
                report = run_phase1(dry_run=False)
                persist_mock.assert_called_once()

        poly = next(s for s in report.sources if s.source_name == "polymarket")
        assert poly.events_persisted == 2
        assert report.total_persisted == 2

    def test_write_mode_logs_run(self, polymarket_payload) -> None:
        from scripts.ingestion.base_loader import SkipLoader

        with patch("requests.get", return_value=_mock_response(polymarket_payload)):
            from scripts.live_source_runner import run_phase1
            with (
                patch("scripts.ingestion.gdelt_loader.GDELTLoader.fetch", side_effect=SkipLoader("skip")),
                patch("scripts.ingestion.sec_edgar_loader.SECEdgarLoader.fetch", side_effect=SkipLoader("skip")),
                patch("scripts.live_source_runner._persist_events", return_value=2),
                patch("scripts.live_source_runner._log_run") as log_mock,
            ):
                run_phase1(dry_run=False)
                assert log_mock.call_count >= 1  # called per source


# ---------------------------------------------------------------------------
# Persistence layer — signal_events table
# ---------------------------------------------------------------------------


class TestSignalEventsPersistence:
    def test_insert_and_retrieve(self, tmp_db: Path) -> None:
        from scripts.persistence import get_signal_events, init_schema, insert_signal_event

        init_schema(tmp_db)
        payload = {"event_id": "poly_abc", "title": "Test Q", "advisory_status": "ADVISORY_ONLY"}
        inserted = insert_signal_event(
            "poly_abc", "polymarket", payload, "2026-05-09T10:00:00+00:00", db_path=tmp_db
        )
        assert inserted is True
        events = get_signal_events(db_path=tmp_db)
        assert len(events) == 1
        assert events[0]["event_id"] == "poly_abc"
        assert events[0]["advisory_status"] == "ADVISORY_ONLY"
        assert events[0]["ai_execution_count"] == 0

    def test_duplicate_is_ignored(self, tmp_db: Path) -> None:
        from scripts.persistence import get_signal_events, init_schema, insert_signal_event

        init_schema(tmp_db)
        insert_signal_event("ev-001", "gdelt", {}, "2026-05-09T10:00:00+00:00", db_path=tmp_db)
        second = insert_signal_event("ev-001", "gdelt", {}, "2026-05-09T11:00:00+00:00", db_path=tmp_db)
        assert second is False
        assert len(get_signal_events(db_path=tmp_db)) == 1

    def test_filter_by_source_name(self, tmp_db: Path) -> None:
        from scripts.persistence import get_signal_events, init_schema, insert_signal_event

        init_schema(tmp_db)
        insert_signal_event("ev-poly", "polymarket", {}, "2026-05-09T10:00:00+00:00", db_path=tmp_db)
        insert_signal_event("ev-gdelt", "gdelt", {}, "2026-05-09T10:00:00+00:00", db_path=tmp_db)
        poly_events = get_signal_events(source_name="polymarket", db_path=tmp_db)
        assert len(poly_events) == 1
        assert poly_events[0]["source_name"] == "polymarket"

    def test_raw_payload_roundtrip(self, tmp_db: Path) -> None:
        from scripts.persistence import get_signal_events, init_schema, insert_signal_event

        init_schema(tmp_db)
        payload = {"title": "Test", "volume": 42.5, "nested": {"a": 1}}
        insert_signal_event("ev-json", "polymarket", payload, "2026-05-09T10:00:00+00:00", db_path=tmp_db)
        events = get_signal_events(db_path=tmp_db)
        assert events[0]["raw_payload"] == payload

    def test_advisory_stamp_enforced_on_read(self, tmp_db: Path) -> None:
        from scripts.persistence import get_signal_events, init_schema, insert_signal_event

        init_schema(tmp_db)
        insert_signal_event("ev-x", "gdelt", {}, "2026-05-09T10:00:00+00:00", db_path=tmp_db)
        ev = get_signal_events(db_path=tmp_db)[0]
        assert ev["advisory_status"] == "ADVISORY_ONLY"
        assert ev["ai_execution_count"] == 0
        assert ev["human_review_required"] is True


# ---------------------------------------------------------------------------
# Source run log
# ---------------------------------------------------------------------------


class TestSourceRunLog:
    def test_log_and_retrieve(self, tmp_db: Path) -> None:
        from scripts.persistence import get_source_run_log, init_schema, log_source_run

        init_schema(tmp_db)
        log_source_run(
            source_name="polymarket",
            status="ok",
            fetched_count=20,
            skipped_reason="",
            error_message="",
            timestamp_utc="2026-05-09T10:00:00+00:00",
            duration_ms=350,
            db_path=tmp_db,
        )
        logs = get_source_run_log(db_path=tmp_db)
        assert len(logs) == 1
        assert logs[0]["source_name"] == "polymarket"
        assert logs[0]["fetched_count"] == 20
        assert logs[0]["advisory_status"] == "ADVISORY_ONLY"

    def test_skipped_source_logged_correctly(self, tmp_db: Path) -> None:
        from scripts.persistence import get_source_run_log, init_schema, log_source_run

        init_schema(tmp_db)
        log_source_run(
            source_name="sec_edgar",
            status="skipped",
            fetched_count=0,
            skipped_reason="Required env var 'SEC_USER_AGENT' is not set",
            error_message="",
            timestamp_utc="2026-05-09T10:00:00+00:00",
            duration_ms=0,
            db_path=tmp_db,
        )
        logs = get_source_run_log(db_path=tmp_db)
        assert logs[0]["status"] == "skipped"
        assert "SEC_USER_AGENT" in logs[0]["skipped_reason"]

    def test_multiple_sources_logged(self, tmp_db: Path) -> None:
        from scripts.persistence import get_source_run_log, init_schema, log_source_run

        init_schema(tmp_db)
        for src in ("polymarket", "gdelt", "sec_edgar"):
            log_source_run(src, "ok", 10, "", "", "2026-05-09T10:00:00+00:00", 100, db_path=tmp_db)
        logs = get_source_run_log(db_path=tmp_db)
        assert len(logs) == 3
        sources = {lg["source_name"] for lg in logs}
        assert sources == {"polymarket", "gdelt", "sec_edgar"}


# ---------------------------------------------------------------------------
# No-execution safety
# ---------------------------------------------------------------------------


class TestNoExecutionSafety:
    def test_runner_report_never_contains_trade_fields(self, polymarket_payload) -> None:
        from scripts.ingestion.base_loader import SkipLoader

        with patch("requests.get", return_value=_mock_response(polymarket_payload)):
            from scripts.live_source_runner import run_phase1
            with (
                patch("scripts.ingestion.gdelt_loader.GDELTLoader.fetch", side_effect=SkipLoader("skip")),
                patch("scripts.ingestion.sec_edgar_loader.SECEdgarLoader.fetch", side_effect=SkipLoader("skip")),
            ):
                report = run_phase1(dry_run=True)

        d = report.to_dict()
        forbidden = {"trade_id", "broker_order_id", "executed", "order_id", "buy", "sell"}
        assert not forbidden & set(d.keys())

    def test_live_source_runner_no_forbidden_methods(self) -> None:
        runner_path = REPO_ROOT / "scripts" / "live_source_runner.py"
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

    def test_run_phase1_cli_no_forbidden_methods(self) -> None:
        cli_path = REPO_ROOT / "scripts" / "run_live_sources_phase1.py"
        source = cli_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        forbidden = {"place_order", "execute_trade", "submit_order"}
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
        os.environ.pop("SEC_USER_AGENT", None)
        with patch("requests.get", side_effect=Exception("no network")):
            from scripts.live_source_runner import run_phase1

            report = run_phase1(dry_run=True)

        assert report.total_fetched == 0
        assert report.total_persisted == 0
        assert report.advisory_status == "ADVISORY_ONLY"
        assert all(s.status == "skipped" for s in report.sources)
        assert len(report.sources) == 3

    def test_all_skipped_sources_named(self) -> None:
        os.environ.pop("SEC_USER_AGENT", None)
        with patch("requests.get", side_effect=Exception("no network")):
            from scripts.live_source_runner import run_phase1

            report = run_phase1(dry_run=True)

        names = {s.source_name for s in report.sources}
        assert names == {"polymarket", "gdelt", "sec_edgar"}


# ---------------------------------------------------------------------------
# Duration tracking
# ---------------------------------------------------------------------------


class TestDurationTracking:
    def test_duration_ms_is_non_negative(self, polymarket_payload) -> None:
        from scripts.ingestion.base_loader import SkipLoader

        with patch("requests.get", return_value=_mock_response(polymarket_payload)):
            from scripts.live_source_runner import run_phase1
            with (
                patch("scripts.ingestion.gdelt_loader.GDELTLoader.fetch", side_effect=SkipLoader("skip")),
                patch("scripts.ingestion.sec_edgar_loader.SECEdgarLoader.fetch", side_effect=SkipLoader("skip")),
            ):
                report = run_phase1(dry_run=True)

        for src in report.sources:
            assert src.duration_ms >= 0
