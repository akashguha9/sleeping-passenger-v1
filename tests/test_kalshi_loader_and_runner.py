"""
Kalshi loader + Phase-1 runner + persistence tests.

No live network.  HTTP is patched throughout; persistence writes go to a
temp SQLite under tmp_path.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.ingestion.base_loader import SkipLoader


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def kalshi_payload():
    return {
        "markets": [
            {
                "ticker": "BTCMAY-2026",
                "title": "How high will Bitcoin get in May?",
                "subtitle": "Bitcoin May market",
                "rules_primary": "Settles to BTC/USD print on Coinbase.",
                "category": "Crypto",
                "tags": ["bitcoin"],
                "yes_ask": 0.42,
                "no_ask": 0.58,
                "volume": 1250,
                "open_interest": 800,
                "close_time": "2026-05-31T23:59:00Z",
            },
            {
                "ticker": "FED-CUT-JUN-2026",
                "title": "Will the Fed cut rates at the June 2026 meeting?",
                "category": "Economics",
                "yes_ask": 0.31,
                "no_ask": 0.69,
                "volume": 4200,
                "close_time": "2026-06-18T18:00:00Z",
            },
            # rejected by the allowlist — must not enter persistence
            {
                "ticker": "NBA-FINALS-2026",
                "title": "Will the Lakers win the NBA Finals?",
                "category": "Sports",
                "yes_ask": 0.20,
            },
        ]
    }


def _mock_response(payload, status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


# ---------------------------------------------------------------------------
# Loader — HTTP path
# ---------------------------------------------------------------------------


class TestKalshiLoader:
    def test_fetch_parses_mocked_response_and_keeps_rejected_for_runner_to_filter(
        self, kalshi_payload
    ):
        from scripts.ingestion.kalshi_loader import KalshiLoader

        loader = KalshiLoader(limit=5, max_pages=1)
        with patch("requests.get", return_value=_mock_response(kalshi_payload)):
            result = loader.safe_fetch()

        assert not result.skipped
        # Loader returns raw market records (allowlist applied at runner
        # level via normalize_kalshi_market).  All three rows should survive
        # the loader's minimum-identifier filter.
        assert len(result.records) == 3
        assert {r["ticker"] for r in result.records} == {
            "BTCMAY-2026",
            "FED-CUT-JUN-2026",
            "NBA-FINALS-2026",
        }

    def test_network_failure_yields_clean_skip(self):
        from scripts.ingestion.kalshi_loader import KalshiLoader

        loader = KalshiLoader(limit=5, max_pages=1)
        with patch("requests.get", side_effect=Exception("network down")):
            result = loader.safe_fetch()

        assert result.skipped
        assert "unreachable" in result.skip_reason.lower() or "kalshi" in result.skip_reason.lower()

    def test_mock_fixtures_mode_returns_deterministic_records(self):
        from scripts.ingestion.kalshi_loader import KalshiLoader

        loader = KalshiLoader(use_mock_fixtures=True)
        result = loader.safe_fetch()

        assert not result.skipped
        assert len(result.records) >= 4
        tickers = {r["ticker"] for r in result.records}
        # Approved + the deliberately rejected sports row are both in raw
        # loader output; the rejection happens in normalization.
        assert "BTCMAY-2026" in tickers
        assert "NBA-FINALS-2026" in tickers
        for rec in result.records:
            assert rec["advisory_status"] == "ADVISORY_ONLY"
            assert rec["execution_gate"] == "LOCKED"


# ---------------------------------------------------------------------------
# Phase-1 runner — dry-run + write path
# ---------------------------------------------------------------------------


class TestKalshiPhase1Runner:
    def test_dry_run_filters_rejected_categories(self, kalshi_payload):
        from scripts.live_source_runner import run_phase1

        with patch("requests.get", return_value=_mock_response(kalshi_payload)):
            report = run_phase1(dry_run=True, sources=["kalshi"], kalshi_limit=5)

        ks = next(s for s in report.sources if s.source_name == "kalshi")
        assert ks.status in ("ok", "ok_filtered")
        assert ks.fetched_count == 3
        assert ks.accepted_count == 2  # Crypto + Economics
        assert ks.rejected_count == 1  # NBA Sports
        assert ks.events_persisted == 0  # dry-run never persists
        assert report.advisory_status == "ADVISORY_ONLY"
        assert report.execution_gate == "LOCKED"
        assert report.broker_api_called is False if hasattr(report, "broker_api_called") else True
        assert report.ai_execution_count == 0

    def test_dry_run_never_calls_persist(self, kalshi_payload):
        from scripts.live_source_runner import run_phase1

        with patch("requests.get", return_value=_mock_response(kalshi_payload)):
            with patch("scripts.live_source_runner._persist_events") as persist_mock:
                run_phase1(dry_run=True, sources=["kalshi"], kalshi_limit=5)
                persist_mock.assert_not_called()

    def test_write_mode_calls_persist_with_only_approved_categories(
        self, kalshi_payload
    ):
        """In write-mode the runner upserts each approved-category row.

        The Kalshi refresh path delegates to
        ``scripts.kalshi_phase1_runner._upsert`` (which fans out to
        ``persistence.upsert_signal_event_observation``).  The contract
        the original assertion was protecting — "only approved categories
        reach persistence" — is preserved; the implementation hook moved.
        """
        from scripts.live_source_runner import run_phase1
        import scripts.kalshi_phase1_runner as kpr

        upsert_calls: list[dict] = []

        def _fake_upsert(payload, fetched_at, *, db_path):
            upsert_calls.append(payload)
            return (1, 0)

        with patch("requests.get", return_value=_mock_response(kalshi_payload)):
            with (
                patch.object(kpr, "_upsert", side_effect=_fake_upsert),
                patch("scripts.live_source_runner._log_run"),
            ):
                report = run_phase1(dry_run=False, sources=["kalshi"], kalshi_limit=5)

        assert len(upsert_calls) == 2
        categories = {e["category"] for e in upsert_calls}
        assert categories == {"Crypto", "Economics"}
        for ev in upsert_calls:
            assert ev["source"] == "kalshi"
            assert ev["source_label"] == "Kalshi"
            assert ev["execution_permission"] == "ADVISORY_ONLY"
            assert ev["broker_api_called"] is False
            assert ev["ai_execution_count"] == 0
            assert isinstance(ev.get("semantic_text"), str)
            assert "Title:" in ev["semantic_text"]
        ks = next(s for s in report.sources if s.source_name == "kalshi")
        assert ks.events_persisted == 2

    def test_approved_kalshi_persists_into_canonical_sqlite(
        self, tmp_path: Path
    ):
        """Direct persistence-layer test: an approved Kalshi payload lands
        in signal_events; the row reads back with the safety stamps."""
        from scripts.kalshi_normalizer import normalize_kalshi_market
        from scripts.persistence import (
            get_signal_events,
            init_schema,
            insert_signal_event,
        )

        db_path = tmp_path / "kalshi_direct.db"
        init_schema(db_path)
        payload = normalize_kalshi_market(
            {
                "source": "Kalshi",
                "source_market_id": "BTCMAY-2026",
                "title": "How high will Bitcoin get in May?",
                "category": "Crypto",
                "yes_price": 0.42,
                "close_time_utc": "2026-05-31T23:59:00Z",
            },
            fetched_at_utc="2026-05-24T00:00:00Z",
        )
        assert payload is not None
        inserted = insert_signal_event(
            event_id=payload["event_id"],
            source_name="kalshi",
            raw_payload=payload,
            fetched_at="2026-05-24T00:00:00Z",
            db_path=db_path,
        )
        assert inserted is True

        rows = get_signal_events(source_name="kalshi", db_path=db_path)
        assert len(rows) == 1
        row = rows[0]
        assert row["source_name"] == "kalshi"
        assert row["advisory_status"] == "ADVISORY_ONLY"
        assert row["human_review_required"] is True
        assert row["ai_execution_count"] == 0
        rp = row["raw_payload"]
        assert rp["source"] == "kalshi"
        assert rp["source_label"] == "Kalshi"
        assert rp["category"] == "Crypto"
        assert rp["execution_permission"] == "ADVISORY_ONLY"
        assert rp["broker_api_called"] is False

    def test_rejected_kalshi_category_does_not_persist(
        self, kalshi_payload, tmp_path: Path
    ):
        """Direct test: a rejected category yields no normalized payload,
        therefore there is nothing to insert."""
        from scripts.kalshi_normalizer import normalize_kalshi_market
        from scripts.persistence import get_signal_events, init_schema

        db_path = tmp_path / "kalshi_reject.db"
        init_schema(db_path)
        sports_row = kalshi_payload["markets"][2]
        normalized = normalize_kalshi_market(
            {
                "source": "Kalshi",
                "source_market_id": sports_row["ticker"],
                "title": sports_row["title"],
                "category": sports_row["category"],
            }
        )
        assert normalized is None  # the gate dropped it
        # And the SQLite table is empty.
        rows = get_signal_events(source_name="kalshi", db_path=db_path)
        assert rows == []

    def test_runner_rejected_only_payload_yields_ok_filtered(self, kalshi_payload):
        """Source responds, runner filters every row by the allowlist."""
        from scripts.live_source_runner import run_phase1

        sports_only = {"markets": [kalshi_payload["markets"][2]]}
        with patch("requests.get", return_value=_mock_response(sports_only)):
            with (
                patch("scripts.live_source_runner._persist_events", return_value=0),
                patch("scripts.live_source_runner._log_run"),
            ):
                report = run_phase1(dry_run=False, sources=["kalshi"], kalshi_limit=5)
        ks = next(s for s in report.sources if s.source_name == "kalshi")
        assert ks.status == "ok_filtered"
        assert ks.accepted_count == 0
        assert ks.events_persisted == 0

    def test_kalshi_not_in_default_sources_tuple(self):
        """Default run_phase1() must NOT touch Kalshi to avoid surprising
        existing operators or breaking unmocked test fixtures."""
        from scripts.live_source_runner import run_phase1

        with (
            patch("scripts.ingestion.polymarket_loader.PolymarketLoader.fetch", side_effect=SkipLoader("skip")),
            patch("scripts.ingestion.gdelt_loader.GDELTLoader.fetch", side_effect=SkipLoader("skip")),
            patch("scripts.ingestion.sec_edgar_loader.SECEdgarLoader.fetch", side_effect=SkipLoader("skip")),
            patch("scripts.ingestion.kalshi_loader.KalshiLoader.fetch", side_effect=AssertionError("kalshi must not run by default")),
        ):
            report = run_phase1(dry_run=True)
        names = {s.source_name for s in report.sources}
        assert "kalshi" not in names
