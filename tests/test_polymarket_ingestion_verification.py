"""
Phase C.9 — Polymarket Ingestion Verification.

Verifies the full Polymarket ingestion path end-to-end:
  loader fetch → normalization → SQLite persistence → source_run_log → GET /live-signals filter.

Principles
----------
- Zero live network calls. All HTTP intercepted with unittest.mock.patch.
- Advisory contract enforced on every output: ADVISORY_ONLY, LOCKED, AI=0, BROKER=false.
- No authenticated Polymarket trading, no CLOB, no order placement.
- Polymarket uses only public read-only endpoints (no API key required).
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
    return tmp_path / "test_polymarket_verify.db"


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
        {
            "id": "mkt-003",
            "question": "Will S&P 500 exceed 6000 by end of 2026?",
            "volume": 200_000.0,
            "liquidity": 80_000.0,
            "endDate": "2026-12-31",
            "active": True,
        },
    ]


def _mock_response(payload: object) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


# ---------------------------------------------------------------------------
# 1. Polymarket normalization — SignalEvent-compatible rows
# ---------------------------------------------------------------------------


class TestPolymarketNormalization:
    def test_normalized_event_has_all_signal_event_fields(self) -> None:
        from scripts.live_source_runner import _normalize_polymarket_record

        rec = {
            "market_id": "mkt-001",
            "question": "Will inflation exceed 3% in 2026?",
            "volume": 100_000.0,
            "liquidity": 50_000.0,
            "end_date": "2026-12-31",
            "active": True,
            "source": "polymarket",
        }
        out = _normalize_polymarket_record(rec)
        required = {"event_id", "source_name", "signal_type", "title", "market_id",
                    "advisory_status", "human_review_required", "execution_gate",
                    "ai_execution_count"}
        assert required <= set(out.keys()), f"Missing fields: {required - set(out.keys())}"

    def test_source_name_is_polymarket(self) -> None:
        from scripts.live_source_runner import _normalize_polymarket_record

        out = _normalize_polymarket_record({"market_id": "x", "question": "S&P 500 end of Q3 2026?"})
        assert out["source_name"] == "polymarket"

    def test_signal_type_is_prediction_market(self) -> None:
        from scripts.live_source_runner import _normalize_polymarket_record

        out = _normalize_polymarket_record({"market_id": "x", "question": "S&P 500 end of Q3 2026?"})
        assert out["signal_type"] == "prediction_market"

    def test_title_comes_from_question(self) -> None:
        from scripts.live_source_runner import _normalize_polymarket_record

        out = _normalize_polymarket_record({"market_id": "x", "question": "Will the Fed cut rates in 2026?"})
        assert out["title"] == "Will the Fed cut rates in 2026?"

    def test_market_id_preserved(self) -> None:
        from scripts.live_source_runner import _normalize_polymarket_record

        out = _normalize_polymarket_record({"market_id": "mkt-abc", "question": "Fed rate decision in 2026?"})
        assert out["market_id"] == "mkt-abc"

    def test_volume_and_liquidity_preserved(self) -> None:
        from scripts.live_source_runner import _normalize_polymarket_record

        out = _normalize_polymarket_record(
            {"market_id": "x", "question": "Will the Fed cut rates in 2026?", "volume": 42.5, "liquidity": 10.0}
        )
        assert out["volume"] == 42.5
        assert out["liquidity"] == 10.0

    def test_end_date_preserved(self) -> None:
        from scripts.live_source_runner import _normalize_polymarket_record

        out = _normalize_polymarket_record(
            {"market_id": "x", "question": "Will the Fed cut rates in 2026?", "end_date": "2026-12-31"}
        )
        assert out["end_date"] == "2026-12-31"

    def test_event_id_is_stable_and_prefixed(self) -> None:
        from scripts.live_source_runner import _normalize_polymarket_record

        out = _normalize_polymarket_record({"market_id": "mkt-abc", "question": "Fed rate decision in 2026?"})
        assert out["event_id"].startswith("polymarket_")
        assert len(out["event_id"]) == len("polymarket_") + 16

    def test_event_id_deterministic(self) -> None:
        from scripts.live_source_runner import _normalize_polymarket_record

        rec = {"market_id": "mkt-xyz", "question": "Fed Decision in June 2026?"}
        out1 = _normalize_polymarket_record(rec)
        out2 = _normalize_polymarket_record(rec)
        assert out1["event_id"] == out2["event_id"]

    def test_event_id_unique_per_market(self) -> None:
        from scripts.live_source_runner import _normalize_polymarket_record

        out1 = _normalize_polymarket_record({"market_id": "mkt-001", "question": "Will the Fed cut rates?"})
        out2 = _normalize_polymarket_record({"market_id": "mkt-002", "question": "S&P 500 end of May 2026?"})
        assert out1["event_id"] != out2["event_id"]

    def test_missing_market_id_produces_valid_event_id(self) -> None:
        from scripts.live_source_runner import _normalize_polymarket_record

        out = _normalize_polymarket_record({"question": "Will oil prices rise in 2026?"})
        assert out["event_id"].startswith("polymarket_")

    def test_all_payload_records_normalized(self, polymarket_payload: list) -> None:
        from scripts.live_source_runner import _normalize_polymarket_record

        for raw in polymarket_payload:
            rec = {**raw, "market_id": raw["id"], "end_date": raw.get("endDate"), "source": "polymarket"}
            out = _normalize_polymarket_record(rec)
            assert out["source_name"] == "polymarket"
            assert out["signal_type"] == "prediction_market"


# ---------------------------------------------------------------------------
# 2. Advisory contract on all Polymarket events
# ---------------------------------------------------------------------------


class TestPolymarketAdvisoryContract:
    def test_advisory_status_is_advisory_only(self) -> None:
        from scripts.live_source_runner import _normalize_polymarket_record

        out = _normalize_polymarket_record({"market_id": "x", "question": "Will the Fed cut rates in 2026?"})
        assert out["advisory_status"] == "ADVISORY_ONLY"

    def test_human_review_required_is_true(self) -> None:
        from scripts.live_source_runner import _normalize_polymarket_record

        out = _normalize_polymarket_record({"market_id": "x", "question": "Will the Fed cut rates in 2026?"})
        assert out["human_review_required"] is True

    def test_execution_gate_is_locked(self) -> None:
        from scripts.live_source_runner import _normalize_polymarket_record

        out = _normalize_polymarket_record({"market_id": "x", "question": "Will the Fed cut rates in 2026?"})
        assert out["execution_gate"] == "LOCKED"

    def test_ai_execution_count_is_zero(self) -> None:
        from scripts.live_source_runner import _normalize_polymarket_record

        out = _normalize_polymarket_record({"market_id": "x", "question": "Will the Fed cut rates in 2026?"})
        assert out["ai_execution_count"] == 0

    def test_no_broker_api_called_field_or_false(self) -> None:
        from scripts.live_source_runner import _normalize_polymarket_record

        out = _normalize_polymarket_record({"market_id": "x", "question": "Will the Fed cut rates in 2026?"})
        # broker_api_called must either not be present or be False
        assert out.get("broker_api_called", False) is False

    def test_no_trade_fields_in_normalized_record(self) -> None:
        from scripts.live_source_runner import _normalize_polymarket_record

        out = _normalize_polymarket_record({"market_id": "x", "question": "Will the Fed cut rates in 2026?"})
        forbidden = {"order_id", "broker_order_id", "trade_id", "executed", "buy", "sell"}
        assert not forbidden & set(out.keys())

    def test_phase1_report_advisory_fields(self) -> None:
        from scripts.live_source_runner import Phase1RunReport

        r = Phase1RunReport(dry_run=True, run_at="t")
        assert r.advisory_status == "ADVISORY_ONLY"
        assert r.execution_gate == "LOCKED"
        assert r.ai_execution_count == 0
        assert r.human_review_required is True

    def test_all_payload_records_advisory_stamped(self, polymarket_payload: list) -> None:
        from scripts.live_source_runner import _normalize_polymarket_record

        for raw in polymarket_payload:
            rec = {**raw, "market_id": raw["id"], "end_date": raw.get("endDate"), "source": "polymarket"}
            out = _normalize_polymarket_record(rec)
            assert out["advisory_status"] == "ADVISORY_ONLY"
            assert out["human_review_required"] is True
            assert out["execution_gate"] == "LOCKED"
            assert out["ai_execution_count"] == 0


# ---------------------------------------------------------------------------
# 3. Polymarket loader — mocked HTTP
# ---------------------------------------------------------------------------


class TestPolymarketLoaderMocked:
    def test_loader_fetches_correct_count(self, polymarket_payload: list) -> None:
        with patch("requests.get", return_value=_mock_response(polymarket_payload)):
            from scripts.ingestion.polymarket_loader import PolymarketLoader

            loader = PolymarketLoader()
            result = loader.fetch()

        assert result.skipped is False
        assert len(result.records) == 3
        assert result.source_name == "polymarket"

    def test_loader_records_advisory_stamped(self, polymarket_payload: list) -> None:
        with patch("requests.get", return_value=_mock_response(polymarket_payload)):
            from scripts.ingestion.polymarket_loader import PolymarketLoader

            loader = PolymarketLoader()
            result = loader.fetch()

        for rec in result.records:
            assert rec["advisory_status"] == "ADVISORY_ONLY"
            assert rec["human_review_required"] is True
            assert rec["execution_gate"] == "LOCKED"

    def test_loader_records_have_expected_fields(self, polymarket_payload: list) -> None:
        with patch("requests.get", return_value=_mock_response(polymarket_payload)):
            from scripts.ingestion.polymarket_loader import PolymarketLoader

            loader = PolymarketLoader()
            result = loader.fetch()

        for rec in result.records:
            assert "market_id" in rec
            assert "question" in rec
            assert rec["source"] == "polymarket"

    def test_loader_result_advisory_status(self) -> None:
        with patch("requests.get", side_effect=Exception("network down")):
            from scripts.ingestion.polymarket_loader import PolymarketLoader

            loader = PolymarketLoader()
            result = loader.safe_fetch()

        assert result.advisory_status == "ADVISORY_ONLY"
        assert result.human_review_required is True
        assert result.execution_gate == "LOCKED"

    def test_network_error_skips_cleanly(self) -> None:
        with patch("requests.get", side_effect=Exception("timeout")):
            from scripts.ingestion.polymarket_loader import PolymarketLoader

            loader = PolymarketLoader()
            result = loader.safe_fetch()

        assert result.skipped is True
        assert "unreachable" in result.skip_reason.lower()

    def test_empty_list_response_returns_zero_records(self) -> None:
        with patch("requests.get", return_value=_mock_response([])):
            from scripts.ingestion.polymarket_loader import PolymarketLoader

            loader = PolymarketLoader()
            result = loader.fetch()

        assert result.records == []
        assert result.skipped is False

    def test_non_dict_market_skipped(self) -> None:
        with patch("requests.get", return_value=_mock_response(["not-a-dict", None, 42])):
            from scripts.ingestion.polymarket_loader import PolymarketLoader

            loader = PolymarketLoader()
            result = loader.fetch()

        assert result.records == []

    def test_loader_does_not_require_api_key(self) -> None:
        os.environ.pop("POLYMARKET_API_KEY", None)
        from scripts.ingestion.polymarket_loader import PolymarketLoader

        loader = PolymarketLoader()
        assert loader.requires_key is False


# ---------------------------------------------------------------------------
# 4. Polymarket ingestion via run_phase1 (mocked HTTP)
# ---------------------------------------------------------------------------


class TestPolymarketRunPhase1Mocked:
    def test_dry_run_polymarket_only(self, polymarket_payload: list) -> None:
        from scripts.ingestion.base_loader import SkipLoader

        with patch("requests.get", return_value=_mock_response(polymarket_payload)):
            from scripts.live_source_runner import run_phase1
            with (
                patch("scripts.ingestion.gdelt_loader.GDELTLoader.fetch", side_effect=SkipLoader("skip")),
                patch("scripts.ingestion.sec_edgar_loader.SECEdgarLoader.fetch", side_effect=SkipLoader("skip")),
            ):
                report = run_phase1(dry_run=True, sources=["polymarket"])

        assert len(report.sources) == 1
        poly = report.sources[0]
        assert poly.source_name == "polymarket"
        assert poly.status == "ok"
        assert poly.fetched_count == 3
        assert poly.events_persisted == 0
        assert report.advisory_status == "ADVISORY_ONLY"
        assert report.ai_execution_count == 0

    def test_source_filter_polymarket_only_excludes_others(self, polymarket_payload: list) -> None:
        with patch("requests.get", return_value=_mock_response(polymarket_payload)):
            from scripts.live_source_runner import run_phase1

            report = run_phase1(dry_run=True, sources=["polymarket"])

        source_names = {s.source_name for s in report.sources}
        assert source_names == {"polymarket"}
        assert "gdelt" not in source_names
        assert "sec_edgar" not in source_names

    def test_write_mode_persists_polymarket_events(self, polymarket_payload: list) -> None:
        from scripts.ingestion.base_loader import SkipLoader

        with patch("requests.get", return_value=_mock_response(polymarket_payload)):
            from scripts.live_source_runner import run_phase1
            with (
                patch("scripts.ingestion.gdelt_loader.GDELTLoader.fetch", side_effect=SkipLoader("skip")),
                patch("scripts.ingestion.sec_edgar_loader.SECEdgarLoader.fetch", side_effect=SkipLoader("skip")),
                patch("scripts.live_source_runner._persist_events", return_value=3) as persist_mock,
                patch("scripts.live_source_runner._log_run"),
            ):
                report = run_phase1(dry_run=False, sources=["polymarket"])
                persist_mock.assert_called_once()

        poly = next(s for s in report.sources if s.source_name == "polymarket")
        assert poly.events_persisted == 3

    def test_write_mode_logs_polymarket_run(self, polymarket_payload: list) -> None:
        from scripts.ingestion.base_loader import SkipLoader

        with patch("requests.get", return_value=_mock_response(polymarket_payload)):
            from scripts.live_source_runner import run_phase1
            with (
                patch("scripts.ingestion.gdelt_loader.GDELTLoader.fetch", side_effect=SkipLoader("skip")),
                patch("scripts.ingestion.sec_edgar_loader.SECEdgarLoader.fetch", side_effect=SkipLoader("skip")),
                patch("scripts.live_source_runner._persist_events", return_value=3),
                patch("scripts.live_source_runner._log_run") as log_mock,
            ):
                run_phase1(dry_run=False, sources=["polymarket"])
                assert log_mock.call_count >= 1

    def test_dry_run_never_calls_persist(self, polymarket_payload: list) -> None:
        from scripts.ingestion.base_loader import SkipLoader

        with patch("requests.get", return_value=_mock_response(polymarket_payload)):
            from scripts.live_source_runner import run_phase1
            with (
                patch("scripts.ingestion.gdelt_loader.GDELTLoader.fetch", side_effect=SkipLoader("skip")),
                patch("scripts.ingestion.sec_edgar_loader.SECEdgarLoader.fetch", side_effect=SkipLoader("skip")),
                patch("scripts.live_source_runner._persist_events") as persist_mock,
            ):
                run_phase1(dry_run=True, sources=["polymarket"])
                persist_mock.assert_not_called()


# ---------------------------------------------------------------------------
# 5. SQLite persistence — Polymarket events stored and filtered
# ---------------------------------------------------------------------------


class TestPolymarketSQLitePersistence:
    def test_insert_and_retrieve_polymarket_events(self, tmp_db: Path) -> None:
        from scripts.persistence import get_signal_events, init_schema, insert_signal_event

        init_schema(tmp_db)
        payload = {
            "event_id": "polymarket_abc123",
            "source_name": "polymarket",
            "signal_type": "prediction_market",
            "title": "Will inflation exceed 3%?",
            "market_id": "mkt-001",
            "advisory_status": "ADVISORY_ONLY",
            "human_review_required": True,
            "execution_gate": "LOCKED",
            "ai_execution_count": 0,
        }
        inserted = insert_signal_event(
            "polymarket_abc123", "polymarket", payload,
            "2026-05-10T09:00:00+00:00", db_path=tmp_db
        )
        assert inserted is True
        events = get_signal_events(source_name="polymarket", db_path=tmp_db)
        assert len(events) == 1
        assert events[0]["source_name"] == "polymarket"
        assert events[0]["event_id"] == "polymarket_abc123"

    def test_filter_by_source_returns_only_polymarket(self, tmp_db: Path) -> None:
        from scripts.persistence import get_signal_events, init_schema, insert_signal_event

        init_schema(tmp_db)
        insert_signal_event("poly-1", "polymarket", {"title": "Q1"}, "2026-05-10T09:00:00+00:00", db_path=tmp_db)
        insert_signal_event("poly-2", "polymarket", {"title": "Q2"}, "2026-05-10T09:00:00+00:00", db_path=tmp_db)
        insert_signal_event("gdelt-1", "gdelt", {"title": "News"}, "2026-05-10T09:00:00+00:00", db_path=tmp_db)
        insert_signal_event("er-1", "event_registry", {"title": "ER"}, "2026-05-10T09:00:00+00:00", db_path=tmp_db)

        poly_events = get_signal_events(source_name="polymarket", db_path=tmp_db)
        assert len(poly_events) == 2
        assert all(e["source_name"] == "polymarket" for e in poly_events)

    def test_advisory_invariants_enforced_on_read(self, tmp_db: Path) -> None:
        from scripts.persistence import get_signal_events, init_schema, insert_signal_event

        init_schema(tmp_db)
        insert_signal_event("poly-x", "polymarket", {}, "2026-05-10T09:00:00+00:00", db_path=tmp_db)
        ev = get_signal_events(source_name="polymarket", db_path=tmp_db)[0]
        assert ev["advisory_status"] == "ADVISORY_ONLY"
        assert ev["ai_execution_count"] == 0
        assert ev["human_review_required"] is True

    def test_raw_payload_roundtrip_for_polymarket(self, tmp_db: Path) -> None:
        from scripts.persistence import get_signal_events, init_schema, insert_signal_event

        init_schema(tmp_db)
        payload = {"market_id": "mkt-001", "volume": 100_000.0, "title": "Will X?"}
        insert_signal_event("poly-roundtrip", "polymarket", payload, "2026-05-10T09:00:00+00:00", db_path=tmp_db)
        events = get_signal_events(source_name="polymarket", db_path=tmp_db)
        assert events[0]["raw_payload"] == payload

    def test_duplicate_market_not_inserted_twice(self, tmp_db: Path) -> None:
        from scripts.persistence import get_signal_events, init_schema, insert_signal_event

        init_schema(tmp_db)
        insert_signal_event("poly-dup", "polymarket", {}, "2026-05-10T09:00:00+00:00", db_path=tmp_db)
        second = insert_signal_event("poly-dup", "polymarket", {}, "2026-05-10T10:00:00+00:00", db_path=tmp_db)
        assert second is False
        assert len(get_signal_events(source_name="polymarket", db_path=tmp_db)) == 1

    def test_multiple_markets_stored_correctly(self, tmp_db: Path, polymarket_payload: list) -> None:
        from scripts.persistence import get_signal_events, init_schema, insert_signal_event
        from scripts.live_source_runner import _normalize_polymarket_record

        init_schema(tmp_db)
        for raw in polymarket_payload:
            rec = {**raw, "market_id": raw["id"], "end_date": raw.get("endDate"), "source": "polymarket"}
            norm = _normalize_polymarket_record(rec)
            insert_signal_event(
                norm["event_id"], "polymarket", norm,
                "2026-05-10T09:00:00+00:00", db_path=tmp_db
            )

        events = get_signal_events(source_name="polymarket", db_path=tmp_db)
        assert len(events) == 3
        assert all(e["source_name"] == "polymarket" for e in events)


# ---------------------------------------------------------------------------
# 6. Source run log for Polymarket
# ---------------------------------------------------------------------------


class TestPolymarketSourceRunLog:
    def test_log_polymarket_run(self, tmp_db: Path) -> None:
        from scripts.persistence import get_source_run_log, init_schema, log_source_run

        init_schema(tmp_db)
        log_source_run(
            source_name="polymarket",
            status="ok",
            fetched_count=20,
            skipped_reason="",
            error_message="",
            timestamp_utc="2026-05-10T09:00:00+00:00",
            duration_ms=420,
            db_path=tmp_db,
        )
        logs = get_source_run_log(db_path=tmp_db)
        assert len(logs) == 1
        assert logs[0]["source_name"] == "polymarket"
        assert logs[0]["fetched_count"] == 20
        assert logs[0]["advisory_status"] == "ADVISORY_ONLY"

    def test_skipped_polymarket_logged(self, tmp_db: Path) -> None:
        from scripts.persistence import get_source_run_log, init_schema, log_source_run

        init_schema(tmp_db)
        log_source_run(
            source_name="polymarket",
            status="skipped",
            fetched_count=0,
            skipped_reason="Polymarket API unreachable: timeout",
            error_message="",
            timestamp_utc="2026-05-10T09:00:00+00:00",
            duration_ms=10_000,
            db_path=tmp_db,
        )
        logs = get_source_run_log(db_path=tmp_db)
        assert logs[0]["status"] == "skipped"
        assert "unreachable" in logs[0]["skipped_reason"]

    def test_run_result_logged_correctly_in_write_mode(self, polymarket_payload: list) -> None:
        from scripts.ingestion.base_loader import SkipLoader

        log_calls = []

        def capture_log(result):  # type: ignore[no-untyped-def]
            log_calls.append(result)

        with patch("requests.get", return_value=_mock_response(polymarket_payload)):
            from scripts.live_source_runner import run_phase1
            with (
                patch("scripts.ingestion.gdelt_loader.GDELTLoader.fetch", side_effect=SkipLoader("skip")),
                patch("scripts.ingestion.sec_edgar_loader.SECEdgarLoader.fetch", side_effect=SkipLoader("skip")),
                patch("scripts.live_source_runner._persist_events", return_value=3),
                patch("scripts.live_source_runner._log_run", side_effect=capture_log),
            ):
                run_phase1(dry_run=False, sources=["polymarket"])

        assert len(log_calls) == 1
        assert log_calls[0].source_name == "polymarket"
        assert log_calls[0].fetched_count == 3
        assert log_calls[0].status == "ok"


# ---------------------------------------------------------------------------
# 7. API endpoint — GET /live-signals?source=polymarket
# ---------------------------------------------------------------------------


class TestPolymarketAPIEndpoint:
    def test_get_live_signals_polymarket_filter(self, tmp_db: Path) -> None:
        from scripts.persistence import get_signal_events, init_schema, insert_signal_event

        init_schema(tmp_db)
        insert_signal_event("poly-api-1", "polymarket", {"title": "Q1", "market_id": "m1"}, "2026-05-10T09:00:00+00:00", db_path=tmp_db)
        insert_signal_event("poly-api-2", "polymarket", {"title": "Q2", "market_id": "m2"}, "2026-05-10T09:00:00+00:00", db_path=tmp_db)
        insert_signal_event("gdelt-api-1", "gdelt", {"title": "News"}, "2026-05-10T09:00:00+00:00", db_path=tmp_db)

        events = get_signal_events(source_name="polymarket", db_path=tmp_db)
        assert len(events) == 2
        assert all(e["source_name"] == "polymarket" for e in events)

    def test_get_live_signals_returns_advisory_fields(self, tmp_db: Path) -> None:
        from scripts.persistence import get_signal_events, init_schema, insert_signal_event

        init_schema(tmp_db)
        insert_signal_event("poly-adv", "polymarket", {"title": "Advisory Test"}, "2026-05-10T09:00:00+00:00", db_path=tmp_db)

        events = get_signal_events(source_name="polymarket", db_path=tmp_db)
        ev = events[0]
        assert ev["advisory_status"] == "ADVISORY_ONLY"
        assert ev["human_review_required"] is True
        assert ev["execution_gate"] == "LOCKED"
        assert ev["ai_execution_count"] == 0

    def test_api_response_structure_matches_frontend_expectations(self, tmp_db: Path) -> None:
        from scripts.persistence import get_signal_events, init_schema, insert_signal_event

        init_schema(tmp_db)
        payload = {
            "event_id": "poly-struct",
            "source_name": "polymarket",
            "signal_type": "prediction_market",
            "title": "Will X?",
            "market_id": "mkt-struct",
            "volume": 50000.0,
        }
        insert_signal_event("poly-struct", "polymarket", payload, "2026-05-10T09:00:00+00:00", db_path=tmp_db)

        events = get_signal_events(source_name="polymarket", db_path=tmp_db)
        ev = events[0]
        # Fields the frontend LiveSignalEvent interface expects
        assert "event_id" in ev
        assert "source_name" in ev
        assert "raw_payload" in ev
        assert "fetched_at" in ev
        assert "advisory_status" in ev
        assert "human_review_required" in ev
        assert "execution_gate" in ev
        assert "ai_execution_count" in ev
        assert ev["source_name"] == "polymarket"
        # raw_payload contains the original market data
        assert ev["raw_payload"]["market_id"] == "mkt-struct"


# ---------------------------------------------------------------------------
# 8. No-execution safety
# ---------------------------------------------------------------------------


class TestPolymarketNoExecutionSafety:
    def test_polymarket_loader_no_forbidden_methods(self) -> None:
        loader_path = REPO_ROOT / "scripts" / "ingestion" / "polymarket_loader.py"
        source = loader_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        forbidden = {"place_order", "execute_trade", "submit_order", "auto_buy", "auto_sell",
                     "cancel_order", "modify_order"}
        defined = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert not defined & forbidden

    def test_live_source_runner_no_forbidden_methods(self) -> None:
        runner_path = REPO_ROOT / "scripts" / "live_source_runner.py"
        source = runner_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        forbidden = {"place_order", "execute_trade", "submit_order", "auto_buy", "auto_sell",
                     "cancel_order", "modify_order"}
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

    def test_phase1_report_no_trade_fields(self) -> None:
        from scripts.live_source_runner import Phase1RunReport

        d = Phase1RunReport(dry_run=True, run_at="t").to_dict()
        forbidden = {"trade_id", "broker_order_id", "executed", "order_id", "buy", "sell"}
        assert not forbidden & set(d.keys())

    def test_normalized_polymarket_event_no_execution_fields(self) -> None:
        from scripts.live_source_runner import _normalize_polymarket_record

        out = _normalize_polymarket_record({"market_id": "x", "question": "Will the Fed cut rates in 2026?"})
        forbidden = {"order_id", "broker_order_id", "trade_id", "executed"}
        assert not forbidden & set(out.keys())


# ---------------------------------------------------------------------------
# 9. Duration tracking for Polymarket
# ---------------------------------------------------------------------------


class TestPolymarketDurationTracking:
    def test_duration_ms_non_negative_on_success(self, polymarket_payload: list) -> None:
        from scripts.ingestion.base_loader import SkipLoader

        with patch("requests.get", return_value=_mock_response(polymarket_payload)):
            from scripts.live_source_runner import run_phase1
            with (
                patch("scripts.ingestion.gdelt_loader.GDELTLoader.fetch", side_effect=SkipLoader("skip")),
                patch("scripts.ingestion.sec_edgar_loader.SECEdgarLoader.fetch", side_effect=SkipLoader("skip")),
            ):
                report = run_phase1(dry_run=True, sources=["polymarket"])

        for src in report.sources:
            assert src.duration_ms >= 0

    def test_duration_ms_non_negative_on_network_error(self) -> None:
        with patch("requests.get", side_effect=Exception("timeout")):
            from scripts.live_source_runner import run_phase1

            report = run_phase1(dry_run=True, sources=["polymarket"])

        for src in report.sources:
            assert src.duration_ms >= 0
