"""End-to-end: Kalshi runner → SQLite → /live-signals API.

Mocked HTTP only — never touches the network and never pollutes
``runtime/mvp_local.db`` (the canonical runtime DB).  This test stitches
together the three layers proved separately in the existing Kalshi
suite:

1. ``scripts.live_source_runner.run_phase1`` with HTTP patched
2. ``scripts.persistence`` writes the approved rows to a temp SQLite
3. ``scripts.api_server._get_live_signals`` reads them back

It also verifies the API's source-filter contracts:
- ``?source=kalshi`` returns only persisted Kalshi rows
- ``?source=polymarket`` excludes Kalshi rows
- ``?source=`` (all sources) includes Kalshi rows alongside Polymarket
- rejected categories never persist
- every layer preserves the advisory-only safety stamps
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _mock_response(payload, status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


@pytest.fixture()
def kalshi_payload():
    """Three live-shaped markets: two approved, one Sports (rejected)."""
    return {
        "markets": [
            {
                "ticker": "BTCMAY-2026",
                "event_ticker": "BTC-2026",
                "title": "How high will Bitcoin get in May?",
                "subtitle": "BTC May market",
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
                "event_ticker": "FED-2026-JUN",
                "title": "Will the Fed cut rates at the June 2026 meeting?",
                "category": "Economics",
                "yes_ask": 0.31,
                "no_ask": 0.69,
                "volume": 4200,
                "open_interest": 2400,
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


@pytest.fixture()
def kalshi_payload_with_category_enrichment():
    """A live market with NO category field — should still be rescued
    into Crypto via the title keyword anchor inference."""
    return {
        "markets": [
            {
                "ticker": "BTCMAY-2026",
                "event_ticker": "BTC-2026",
                "title": "How high will Bitcoin get in May?",
                "category": None,  # missing — enrichment should rescue
                "yes_ask": 0.42,
                "close_time": "2026-05-31T23:59:00Z",
            },
        ]
    }


@pytest.fixture()
def temp_runtime_db(tmp_path: Path, monkeypatch):
    """Initialise a temp SQLite, point persistence + api_server at it.

    Both ``scripts.persistence.DB_PATH`` and any cached module-level
    references in ``scripts.api_server`` need to resolve to the tmp path
    so the runner persists into it and ``_get_live_signals`` reads from
    the same file.  ``get_signal_events`` resolves ``DB_PATH`` lazily, so
    monkeypatching the module attribute is sufficient.
    """
    from scripts import persistence

    db_path = tmp_path / "mvp_local_e2e.db"
    persistence.init_schema(db_path)
    monkeypatch.setattr(persistence, "DB_PATH", db_path, raising=False)
    return db_path


# ---------------------------------------------------------------------------
# E2E: runner → SQLite → API
# ---------------------------------------------------------------------------


class TestKalshiRunnerSQLiteAPIE2E:
    def test_full_path_persists_only_approved_and_api_returns_them(
        self, kalshi_payload, temp_runtime_db, monkeypatch
    ):
        from scripts import live_source_runner
        from scripts.api_server import _get_live_signals

        # Stub _log_run so the runner does not try to write to the
        # source_run_log table in a way unrelated to the assertions we
        # care about here.  Persistence of signal_events is left REAL so
        # the API read truly reflects the runner's write.
        monkeypatch.setattr(
            live_source_runner, "_log_run", lambda *a, **kw: None
        )

        with patch("requests.get", return_value=_mock_response(kalshi_payload)):
            report = live_source_runner.run_phase1(
                dry_run=False, sources=["kalshi"], kalshi_limit=5
            )

        # Runner report contract.
        ks = next(s for s in report.sources if s.source_name == "kalshi")
        assert ks.status in ("ok", "ok_filtered")
        assert ks.fetched_count == 3
        assert ks.accepted_count == 2  # Crypto + Economics
        assert ks.rejected_count == 1  # Sports
        assert ks.events_persisted == 2
        assert report.advisory_status == "ADVISORY_ONLY"
        assert report.execution_gate == "LOCKED"
        assert report.ai_execution_count == 0

        # API read — Kalshi source filter returns exactly the two
        # approved rows.
        kalshi_response = _get_live_signals(source_name="kalshi", limit=50)
        assert kalshi_response["advisory_status"] == "ADVISORY_ONLY"
        assert kalshi_response["human_review_required"] is True
        assert kalshi_response["ai_execution_count"] == 0
        events = kalshi_response["live_signal_events"]
        assert len(events) == 2
        categories = {ev["raw_payload"]["category"] for ev in events}
        assert categories == {"Crypto", "Economics"}
        # Rejected category never persisted → cannot appear in the API.
        for ev in events:
            assert ev["raw_payload"]["category"] != "Sports"
            assert ev["raw_payload"]["source"] == "kalshi"
            assert ev["raw_payload"]["source_label"] == "Kalshi"

    def test_safety_invariants_survive_full_path(
        self, kalshi_payload, temp_runtime_db, monkeypatch
    ):
        from scripts import live_source_runner
        from scripts.api_server import _get_live_signals

        monkeypatch.setattr(
            live_source_runner, "_log_run", lambda *a, **kw: None
        )

        with patch("requests.get", return_value=_mock_response(kalshi_payload)):
            live_source_runner.run_phase1(
                dry_run=False, sources=["kalshi"], kalshi_limit=5
            )

        response = _get_live_signals(source_name="kalshi", limit=50)
        for ev in response["live_signal_events"]:
            payload = ev["raw_payload"]
            assert payload["execution_permission"] == "ADVISORY_ONLY"
            assert payload["execution_gate"] == "LOCKED"
            assert payload["human_review_required"] is True
            assert payload["advisory_only"] is True
            assert payload["broker_api_called"] is False
            assert payload["ai_execution_count"] == 0
            assert ev["advisory_status"] == "ADVISORY_ONLY"
            # The persistence layer also re-stamps these — verify the row.
            assert ev["source_name"] == "kalshi"

    def test_polymarket_filter_excludes_kalshi(
        self, kalshi_payload, temp_runtime_db, monkeypatch
    ):
        from scripts import live_source_runner, persistence
        from scripts.api_server import _get_live_signals

        monkeypatch.setattr(
            live_source_runner, "_log_run", lambda *a, **kw: None
        )

        # Persist Kalshi via the runner.
        with patch("requests.get", return_value=_mock_response(kalshi_payload)):
            live_source_runner.run_phase1(
                dry_run=False, sources=["kalshi"], kalshi_limit=5
            )

        # Seed one Polymarket row directly (no need to mock the
        # Polymarket pipeline for this contract test).
        persistence.insert_signal_event(
            event_id="polymarket_test_e2e",
            source_name="polymarket",
            raw_payload={
                "event_id": "polymarket_test_e2e",
                "source_name": "polymarket",
                "title": "Will Apple announce a foldable iPhone in 2026?",
                "market_id": "poly-e2e-001",
            },
            fetched_at="2026-05-24T00:00:00Z",
            db_path=temp_runtime_db,
        )

        # source=polymarket: Kalshi rows must NOT appear.
        poly = _get_live_signals(source_name="polymarket", limit=50)
        poly_events = poly["live_signal_events"]
        assert len(poly_events) == 1
        for ev in poly_events:
            assert ev["source_name"] == "polymarket"
            assert ev["source_name"] != "kalshi"

        # source=None (all sources): both Polymarket and Kalshi rows present.
        every = _get_live_signals(source_name=None, limit=50)
        sources_returned = {ev["source_name"] for ev in every["live_signal_events"]}
        assert "kalshi" in sources_returned
        assert "polymarket" in sources_returned

    def test_rejected_category_does_not_persist(
        self, temp_runtime_db, monkeypatch
    ):
        """A Sports-only payload yields zero persisted Kalshi rows AND
        the API returns an empty Kalshi event list."""
        from scripts import live_source_runner
        from scripts.api_server import _get_live_signals

        monkeypatch.setattr(
            live_source_runner, "_log_run", lambda *a, **kw: None
        )

        sports_only = {
            "markets": [
                {
                    "ticker": "NBA-FINALS-2026",
                    "title": "Will the Lakers win the NBA Finals?",
                    "category": "Sports",
                    "yes_ask": 0.20,
                },
            ]
        }
        with patch("requests.get", return_value=_mock_response(sports_only)):
            report = live_source_runner.run_phase1(
                dry_run=False, sources=["kalshi"], kalshi_limit=5
            )
        ks = next(s for s in report.sources if s.source_name == "kalshi")
        assert ks.events_persisted == 0
        response = _get_live_signals(source_name="kalshi", limit=50)
        assert response["live_signal_events"] == []

    def test_live_enrichment_rescues_missing_category_into_persistence(
        self, kalshi_payload_with_category_enrichment, temp_runtime_db, monkeypatch
    ):
        """A live Kalshi market without a populated category field should
        still persist when the title carries an unambiguous category
        signal (Bitcoin → Crypto via keyword anchor)."""
        from scripts import live_source_runner
        from scripts.api_server import _get_live_signals

        monkeypatch.setattr(
            live_source_runner, "_log_run", lambda *a, **kw: None
        )

        with patch(
            "requests.get",
            return_value=_mock_response(kalshi_payload_with_category_enrichment),
        ):
            live_source_runner.run_phase1(
                dry_run=False, sources=["kalshi"], kalshi_limit=5
            )

        response = _get_live_signals(source_name="kalshi", limit=50)
        events = response["live_signal_events"]
        assert len(events) == 1
        payload = events[0]["raw_payload"]
        assert payload["category"] == "Crypto"
        assert payload.get("category_source") == "inferred"
        assert payload.get("category_reason", "").startswith(
            ("keyword_anchor:", "ticker_prefix:")
        )
        # Safety invariants still stamped.
        assert payload["execution_permission"] == "ADVISORY_ONLY"
        assert payload["broker_api_called"] is False
        assert payload["ai_execution_count"] == 0

    def test_runtime_db_not_polluted_by_e2e_test(self, temp_runtime_db):
        """Belt-and-braces: the canonical runtime DB path must not equal
        the temp path used by this test, AND the temp path must live
        outside the project tree.  Catches accidental monkeypatch loss."""
        from scripts import persistence

        # persistence.DB_PATH should be the tmp_path version, NOT the
        # repo's runtime/mvp_local.db.
        assert persistence.DB_PATH == temp_runtime_db
        assert "Temp" in str(temp_runtime_db) or "tmp" in str(temp_runtime_db).lower()
