"""End-to-end: Polymarket × Kalshi rows in SQLite → disagreement scanner →
SQLite signal_events → /live-signals API.

The flow under test:

1. Seed a temp SQLite with one Polymarket row and one Kalshi row
   describing the SAME real-world event.
2. Run the scanner with ``--write`` so the triggered alert lands in
   ``signal_events`` under ``source_name="prediction_market_disagreement"``.
3. Read back through the live-signals API and prove the alert is visible
   via ``source=prediction_market_disagreement`` AND via the all-source
   view, but NOT via the ``polymarket`` or ``kalshi`` filters (no
   cross-contamination across source filters).
4. Verify the persisted payload carries both venue titles, both
   probabilities, the gap, the pair type, the resolution mismatch list,
   and the safety stamps.

Also covered:
- Dry-run never persists.
- Write mode persists ONLY triggered alerts (not WATCH or DIAGNOSTIC).

Never touches the canonical runtime DB; always operates on a tmp_path
SQLite that ``persistence.DB_PATH`` is monkeypatched onto.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import persistence
from scripts.prediction_market_disagreement_scanner import (
    CROSS_VENUE_SIGNAL_CLASS,
    CUSTOMER_LABEL,
    PERSISTENCE_SOURCE_NAME,
    run as run_scanner,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def temp_runtime_db(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "mvp_local_disagree_e2e.db"
    persistence.init_schema(db_path)
    monkeypatch.setattr(persistence, "DB_PATH", db_path, raising=False)
    return db_path


def _seed_poly(db_path: Path) -> None:
    """Seed a Polymarket row for the BTC-May paraphrase pair."""
    persistence.insert_signal_event(
        event_id="polymarket_btc_may_high_e2e",
        source_name="polymarket",
        raw_payload={
            "event_id": "polymarket_btc_may_high_e2e",
            "source_name": "polymarket",
            "market_id": "poly-btc-may-high-e2e",
            "title": "What price will Bitcoin hit in May?",
            "category": "crypto",
            "implied_probability": 0.62,
            "implied_probability_source": "implied_probability",
            # Intentionally use a minimal semantic_text so the rules
            # text doesn't add false resolution-style verbs.
            "semantic_text": (
                "Title: What price will Bitcoin hit in May?\n"
                "Category: crypto"
            ),
        },
        fetched_at="2026-05-24T00:00:00Z",
        db_path=db_path,
    )


def _seed_kalshi(db_path: Path) -> None:
    """Seed a Kalshi row that semantically pairs with the Polymarket row."""
    persistence.insert_signal_event(
        event_id="kalshi_btc_may_high_e2e",
        source_name="kalshi",
        raw_payload={
            "event_id": "kalshi_btc_may_high_e2e",
            "source_name": "kalshi",
            "source": "kalshi",
            "source_market_id": "BTCMAY-E2E",
            "title": "How high will Bitcoin get in May?",
            "category": "Crypto",
            "implied_probability": 0.54,
            "semantic_text": (
                "Title: How high will Bitcoin get in May?\n"
                "Category: Crypto"
            ),
        },
        fetched_at="2026-05-24T00:00:00Z",
        db_path=db_path,
    )


# ---------------------------------------------------------------------------
# E2E: scanner → SQLite → API
# ---------------------------------------------------------------------------


class TestDisagreementScannerSqliteApiE2E:
    def test_triggered_alert_persists_and_is_visible_via_source_filter(
        self, temp_runtime_db
    ):
        from scripts.api_server import _get_live_signals

        _seed_poly(temp_runtime_db)
        _seed_kalshi(temp_runtime_db)

        rc = run_scanner(["--write", "--limit", "10", "--json"])
        assert rc == 0

        response = _get_live_signals(
            source_name=PERSISTENCE_SOURCE_NAME, limit=50
        )
        events = response["live_signal_events"]
        assert len(events) >= 1

        # Every alert row carries both venues' titles + probabilities + gap
        # + pair_type + safety stamps.
        for ev in events:
            payload = ev["raw_payload"]
            assert payload["signal_class"] == CROSS_VENUE_SIGNAL_CLASS
            assert payload["customer_label"] == CUSTOMER_LABEL
            assert payload["disagreement_triggered"] is True
            assert payload["polymarket_title"]
            assert payload["kalshi_title"]
            assert payload["polymarket_probability"] is not None
            assert payload["kalshi_probability"] is not None
            assert payload["probability_gap"] is not None
            assert payload["pair_type"]
            # Provenance + components + mismatch list always present.
            assert payload["probability_source_polymarket"]
            assert payload["probability_source_kalshi"]
            assert isinstance(payload["pair_score_components"], dict)
            assert isinstance(payload["resolution_mismatch_reasons"], list)
            # Safety stamps stay locked.
            assert payload["execution_permission"] == "ADVISORY_ONLY"
            assert payload["advisory_status"] == "ADVISORY_ONLY"
            assert payload["execution_gate"] == "LOCKED"
            assert payload["broker_api_called"] is False
            assert payload["ai_execution_count"] == 0

    def test_all_source_view_includes_disagreement_alert(self, temp_runtime_db):
        from scripts.api_server import _get_live_signals

        _seed_poly(temp_runtime_db)
        _seed_kalshi(temp_runtime_db)
        rc = run_scanner(["--write", "--limit", "10", "--json"])
        assert rc == 0

        every = _get_live_signals(source_name=None, limit=50)
        sources = {ev["source_name"] for ev in every["live_signal_events"]}
        assert PERSISTENCE_SOURCE_NAME in sources
        assert "polymarket" in sources
        assert "kalshi" in sources

    def test_polymarket_filter_does_not_show_disagreement_alerts(
        self, temp_runtime_db
    ):
        from scripts.api_server import _get_live_signals

        _seed_poly(temp_runtime_db)
        _seed_kalshi(temp_runtime_db)
        rc = run_scanner(["--write", "--limit", "10", "--json"])
        assert rc == 0

        poly_view = _get_live_signals(source_name="polymarket", limit=50)
        for ev in poly_view["live_signal_events"]:
            assert ev["source_name"] == "polymarket"
            assert ev["source_name"] != PERSISTENCE_SOURCE_NAME

    def test_kalshi_filter_does_not_show_disagreement_alerts(
        self, temp_runtime_db
    ):
        from scripts.api_server import _get_live_signals

        _seed_poly(temp_runtime_db)
        _seed_kalshi(temp_runtime_db)
        rc = run_scanner(["--write", "--limit", "10", "--json"])
        assert rc == 0

        kalshi_view = _get_live_signals(source_name="kalshi", limit=50)
        for ev in kalshi_view["live_signal_events"]:
            assert ev["source_name"] == "kalshi"
            assert ev["source_name"] != PERSISTENCE_SOURCE_NAME

    def test_dry_run_persists_nothing(self, temp_runtime_db):
        _seed_poly(temp_runtime_db)
        _seed_kalshi(temp_runtime_db)
        rc = run_scanner(["--dry-run", "--limit", "10", "--json"])
        assert rc == 0
        rows = persistence.get_signal_events(
            source_name=PERSISTENCE_SOURCE_NAME, limit=50, db_path=temp_runtime_db
        )
        assert rows == []

    def test_write_mode_does_not_persist_resolution_mismatch_pairs(
        self, temp_runtime_db
    ):
        """SAME_EVENT_DIFFERENT_THRESHOLD pairs must NEVER be persisted as a
        clean alert, even with a large probability gap."""
        persistence.insert_signal_event(
            event_id="polymarket_btc_hit_150k_e2e",
            source_name="polymarket",
            raw_payload={
                "event_id": "polymarket_btc_hit_150k_e2e",
                "source_name": "polymarket",
                "market_id": "poly-btc-hit-150k-e2e",
                "title": "Will Bitcoin hit $150k in May?",
                "category": "crypto",
                "implied_probability": 0.80,
                "semantic_text": (
                    "Title: Will Bitcoin hit $150k in May?\n"
                    "Rules: Resolves YES if BTC trades at or above $150k at "
                    "any point in May.\nCategory: crypto"
                ),
            },
            fetched_at="2026-05-24T00:00:00Z",
            db_path=temp_runtime_db,
        )
        persistence.insert_signal_event(
            event_id="kalshi_btc_close_100k_e2e",
            source_name="kalshi",
            raw_payload={
                "event_id": "kalshi_btc_close_100k_e2e",
                "source_name": "kalshi",
                "source": "kalshi",
                "source_market_id": "BTC-CLOSE-100K-E2E",
                "title": "Will Bitcoin close above $100k on May 31?",
                "category": "Crypto",
                "implied_probability": 0.18,
                "semantic_text": (
                    "Title: Will Bitcoin close above $100k on May 31?\n"
                    "Rules: Settles to BTC/USD close on Coinbase on "
                    "2026-05-31.\nCategory: Crypto"
                ),
            },
            fetched_at="2026-05-24T00:00:00Z",
            db_path=temp_runtime_db,
        )
        rc = run_scanner(["--write", "--limit", "10", "--json"])
        assert rc == 0
        rows = persistence.get_signal_events(
            source_name=PERSISTENCE_SOURCE_NAME, limit=50, db_path=temp_runtime_db
        )
        # The pair has a 62pp gap but a clear resolution-style mismatch
        # (hit/touch vs close/settle) — must not persist.
        assert rows == []
