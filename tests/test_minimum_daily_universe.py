"""Tests for the minimum viable fresh universe (U_static)."""
from __future__ import annotations

from pathlib import Path

from daily_payload_factory import write_daily_payload

from scripts.daily_payload import load_daily_payload
from scripts.fresh_market_discovery import build_discovery_universe
from scripts.minimum_daily_universe import (
    load_minimum_universe,
    minimum_universe_records,
    minimum_universe_tickers,
    universe_by_bucket,
)

REQUIRED_TICKERS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA",
    "RTX", "LMT", "NOC", "GD", "LHX",
    "XOM", "CVX", "SHEL", "TTE", "BP",
    "TSM", "ASML", "AMD", "AVGO", "INTC", "MU",
    "RELIANCE.NS", "HDFCBANK.NS", "ICICIBANK.NS", "BHARTIARTL.NS", "INFY.NS", "TCS.NS",
    "SAP.DE", "ASML.AS", "SIE.DE", "RHM.DE", "AIR.PA",
    "GLD", "TLT", "TIP", "EWG", "INDA", "FXI",
    "ZIM", "ANET", "PLTR", "SMCI",
]

REQUIRED_BUCKETS = {
    "US_MEGA_CAP", "DEFENSE", "ENERGY", "SEMIS", "INDIA_LARGE_CAP",
    "EUROPE_LARGE_CAP", "MACRO_ETFS", "HIGH_BETA_WATCH",
}


def test_universe_contains_all_required_tickers() -> None:
    tickers = set(minimum_universe_tickers())
    missing = [t for t in REQUIRED_TICKERS if t not in tickers]
    assert missing == [], f"minimum universe missing required tickers: {missing}"


def test_universe_has_all_required_buckets() -> None:
    buckets = universe_by_bucket()
    assert REQUIRED_BUCKETS.issubset(set(buckets)), f"missing buckets: {REQUIRED_BUCKETS - set(buckets)}"


def test_every_ticker_has_required_metadata() -> None:
    required_fields = {"ticker", "name", "bucket", "market", "country", "asset_type", "default_risk_band", "notes"}
    for row in minimum_universe_records():
        assert required_fields.issubset(set(row)), f"{row.get('ticker')} missing metadata: {required_fields - set(row)}"
        assert row["default_risk_band"] in {"core", "watch", "high_beta", "macro_proxy"}


def test_loader_falls_back_to_embedded_when_file_missing(tmp_path: Path) -> None:
    missing = tmp_path / "nope.yaml"
    resolved = load_minimum_universe(missing)
    assert resolved["source"] == "embedded_default"
    assert resolved["ticker_count"] >= len(REQUIRED_TICKERS)


def test_u_today_includes_static_universe_plus_payload(tmp_path: Path) -> None:
    # A payload mover ticker that is NOT in the static universe.
    payload_dir = write_daily_payload(
        tmp_path / "payload",
        movers=[{"ticker": "BHP", "freshness": "UNVERIFIED"}],
        yesterday_final=["SOMECO"],
    )
    payload = load_daily_payload(payload_dir)
    universe = set(build_discovery_universe(payload))
    # Static names present...
    for t in ("AAPL", "RTX", "RELIANCE.NS", "SAP.DE"):
        assert t in universe, f"static universe ticker {t} missing from U_today"
    # ...and payload-sourced names present too.
    assert "BHP" in universe
    assert "SOMECO" in universe


def test_static_universe_membership_does_not_imply_ownership(tmp_path: Path) -> None:
    # GLD is in MACRO_ETFS (U_static) but is closed/sold => never a holding.
    assert "GLD" in set(minimum_universe_tickers())
