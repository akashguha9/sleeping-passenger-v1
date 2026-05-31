"""Phase 3 — OHLCV ingestion for scored tickers missing entry price (offline)."""
from __future__ import annotations

import sqlite3

import pytest

from scripts import persistence
from scripts.ensure_ohlcv_for_scored_tickers import (
    OHLCV_SOURCE_TAG,
    ensure_ohlcv_for_scored_tickers,
    missing_entry_price_symbols,
    scored_symbols,
)
from scripts.real_price_outcome_evidence import load_price_series
from tests._forward_snapshot_helpers import init_db, seed_market_bar, seed_score_vector


def _fixture_loader(close: float = 200.0):
    """Deterministic offline loader: a few real bars for any symbol."""

    def _loader(symbol):
        return [
            ("2026-05-20 00:00:00-04:00", close),
            ("2026-05-21 00:00:00-04:00", close + 1.0),
            ("2026-05-22 00:00:00-04:00", close + 2.0),
        ]

    return _loader


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "t.db"
    init_db(p)
    # Two scored sec_edgar rows for NVDA (via company name) WITHOUT OHLCV...
    seed_score_vector(p, event_id="e_nvda_1", source_name="sec_edgar", ticker="NVIDIA CORP")
    seed_score_vector(p, event_id="e_nvda_2", source_name="sec_edgar", ticker="NVIDIA CORP")
    # ...and one scored row for SPY that DOES already have OHLCV.
    seed_score_vector(p, event_id="e_spy_1", source_name="market_data", ticker="SPY")
    seed_market_bar(p, symbol="SPY", timestamp="2026-05-20 00:00:00-04:00", close=500.0)
    return p


def test_identifies_tickers_missing_entry_price(db):
    missing = missing_entry_price_symbols(db)
    assert "NVDA" in missing and missing["NVDA"] == 2
    # SPY already has a bar, so it is NOT missing.
    assert "SPY" not in missing


def test_fetches_ohlcv_for_missing_tickers_with_fixture_loader(db):
    out = ensure_ohlcv_for_scored_tickers(
        db_path=db, ohlcv_loader=_fixture_loader(), write=True
    )
    assert "NVDA" in out["tickers_fetched"]
    assert out["bars_added"] == 3
    assert "NVDA" in load_price_series(db)


def test_persists_ohlcv_as_real_non_mock(db):
    ensure_ohlcv_for_scored_tickers(db_path=db, ohlcv_loader=_fixture_loader(), write=True)
    conn = sqlite3.connect(str(db))
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT raw_payload FROM signal_events WHERE source_name='market_data'"
        ).fetchall()
    finally:
        conn.close()
    import json

    nvda = [json.loads(r["raw_payload"]) for r in rows]
    nvda = [p for p in nvda if p.get("symbol") == "NVDA"]
    assert nvda, "NVDA bars must be persisted"
    assert all(p.get("mock_flag") is False for p in nvda)
    assert all(p.get("source") == OHLCV_SOURCE_TAG for p in nvda)


def test_does_not_call_broker_or_order_api(db):
    out = ensure_ohlcv_for_scored_tickers(db_path=db, ohlcv_loader=_fixture_loader(), write=True)
    assert out["broker_api_called"] is False
    assert out["ai_execution_count"] == 0
    assert out["execution_gate"] == "LOCKED"
    assert out["predictive_claim_allowed"] is False


def test_recheck_entry_price_after_ohlcv_ingest(db):
    before = missing_entry_price_symbols(db)
    assert "NVDA" in before
    out = ensure_ohlcv_for_scored_tickers(db_path=db, ohlcv_loader=_fixture_loader(), write=True)
    assert "NVDA" not in out["tickers_missing_ohlcv_after"]
    assert out["entry_price_recheck_count"] >= 1


def test_handles_fetch_failure_truthfully(db):
    def _boom(symbol):
        raise ConnectionError("network down")

    out = ensure_ohlcv_for_scored_tickers(db_path=db, ohlcv_loader=_boom, write=True)
    assert out["bars_added"] == 0
    assert "NVDA" in out["failures"]
    assert out["failures"]["NVDA"] == "ConnectionError"
    # Nothing fabricated — NVDA stays missing.
    assert "NVDA" in out["tickers_missing_ohlcv_after"]


def test_idempotent_second_run_does_not_duplicate_bars(db):
    first = ensure_ohlcv_for_scored_tickers(db_path=db, ohlcv_loader=_fixture_loader(), write=True)
    assert first["bars_added"] == 3
    second = ensure_ohlcv_for_scored_tickers(db_path=db, ohlcv_loader=_fixture_loader(), write=True)
    assert second["bars_added"] == 0
    assert second["bars_skipped"] == 0  # NVDA no longer a target after first run


def test_missing_entry_price_count_decreases_with_fixture(db):
    before = len(missing_entry_price_symbols(db))
    ensure_ohlcv_for_scored_tickers(db_path=db, ohlcv_loader=_fixture_loader(), write=True)
    after = len(missing_entry_price_symbols(db))
    assert after < before


def test_empty_loader_reports_no_bars(db):
    out = ensure_ohlcv_for_scored_tickers(db_path=db, ohlcv_loader=lambda s: [], write=True)
    assert out["failures"].get("NVDA") == "NO_BARS_RETURNED"
    assert out["bars_added"] == 0


def test_scored_symbols_resolves_company_names(db):
    syms = scored_symbols(db)
    assert syms.get("NVDA") == 2
    assert syms.get("SPY") == 1


def test_as_of_flags_stale_series(db):
    # SPY has a 2026-05-20 bar. As of 2026-06-05 (>7d later) it is STALE, so it
    # becomes a target even though a series exists.
    missing = missing_entry_price_symbols(db, as_of="2026-06-05T00:00:00Z")
    assert "SPY" in missing
    # As of a date within lookback, SPY is fine.
    near = missing_entry_price_symbols(db, as_of="2026-05-22T00:00:00Z")
    assert "SPY" not in near


def test_as_of_ingest_refreshes_stale_series(db):
    def _fresh_loader(symbol):
        return [("2026-06-04 00:00:00-04:00", 510.0)]

    out = ensure_ohlcv_for_scored_tickers(
        db_path=db, ohlcv_loader=_fresh_loader, write=True, as_of="2026-06-05T00:00:00Z"
    )
    # SPY was stale-as-of, got a fresh bar, no longer missing.
    assert "SPY" not in out["tickers_missing_ohlcv_after"]
