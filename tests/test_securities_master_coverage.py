"""Tests for securities-master coverage metrics + explicit seeding."""
from __future__ import annotations

import math

import pytest

from scripts import securities_master_coverage as smc
from scripts import leverage_governance as lg


def test_load_seed_universe_dedupes():
    uni = smc.load_seed_universe()
    syms = [e["symbol"] for e in uni]
    assert len(syms) == len(set(syms))  # de-duplicated
    assert "AAPL" in syms and "RELIANCE" in syms and "HSBA" in syms


def test_coverage_score_formula_exact():
    universe = [
        {"symbol": "AAA", "exchange": "NASDAQ", "country": "US", "currency": "USD", "name": "A", "asset_type": "EQUITY"},
        {"symbol": "BBB", "exchange": "NSE", "country": "IN", "currency": "INR", "name": "B", "asset_type": "EQUITY"},
    ]
    master = {
        "AAA": {"canonical_symbol": "AAA", "exchange_code": "NASDAQ", "country": "US", "currency": "USD", "name": "A", "asset_type": "EQUITY"},
        # BBB missing from master
    }
    rep = smc.compute_coverage(universe, lambda s: master.get(s))
    # C = 1/2 = 0.5; completeness of AAA = 1.0, BBB missing 0 -> M = 0.5
    # J: AAA resolves ROW -> 1; BBB missing -> 0 -> J = 0.5
    # S = 0.5*0.5 + 0.3*0.5 + 0.2*0.5 = 0.5
    assert math.isclose(rep["coverage"], 0.5)
    assert math.isclose(rep["mean_completeness"], 0.5)
    assert math.isclose(rep["jurisdiction_resolvable"], 0.5)
    assert math.isclose(rep["score"], 0.5)
    assert rep["gaps"] == ["BBB"]


def test_missing_country_lowers_completeness():
    universe = [{"symbol": "AAA", "exchange": "NASDAQ", "country": "US"}]
    full = {"AAA": {"canonical_symbol": "AAA", "exchange_code": "NASDAQ", "country": "US", "currency": "USD", "name": "A", "asset_type": "EQUITY"}}
    no_country = {"AAA": {"canonical_symbol": "AAA", "exchange_code": "NASDAQ", "country": "", "currency": "USD", "name": "A", "asset_type": "EQUITY"}}
    r_full = smc.compute_coverage(universe, lambda s: full.get(s))
    r_missing = smc.compute_coverage(universe, lambda s: no_country.get(s))
    assert r_missing["mean_completeness"] < r_full["mean_completeness"]


def test_seeded_universe_makes_key_tickers_resolvable(tmp_path):
    db = tmp_path / "cov.db"
    universe = smc.load_seed_universe()
    n = smc.seed_universe(universe, db)
    assert n > 30
    from scripts import persistence
    for sym in ["AAPL", "MSFT", "RELIANCE", "BHARTIARTL", "HSBA", "8306", "003550"]:
        row = persistence.get_global_security(sym, db_path=db)
        assert row is not None, f"{sym} should be resolvable after seeding"


def test_leverage_governance_uses_master_for_seeded_bare_ticker(tmp_path):
    db = tmp_path / "cov.db"
    smc.seed_universe(smc.load_seed_universe(), db)
    from scripts import persistence

    def lookup(sym):
        return persistence.get_global_security(sym, db_path=db)

    # Bare AAPL has no India/ROW suffix -> only the master can classify it ROW.
    res = lg.validate_leverage_policy(ticker="AAPL", leverage=2.0, securities_lookup=lookup)
    assert res["jurisdiction_group"] == lg.REST_OF_WORLD
    assert res["jurisdiction_resolution_source"] == lg.SRC_SECURITIES_MASTER
    assert res["breach"] is True

    # Bare RELIANCE -> India via master, 4x allowed.
    res2 = lg.validate_leverage_policy(ticker="RELIANCE", leverage=4.0, securities_lookup=lookup)
    assert res2["jurisdiction_group"] == lg.INDIA
    assert res2["jurisdiction_resolution_source"] == lg.SRC_SECURITIES_MASTER
    assert res2["breach"] is False


def test_unknown_ticker_stays_fail_closed(tmp_path):
    db = tmp_path / "cov.db"
    smc.seed_universe(smc.load_seed_universe(), db)
    from scripts import persistence

    def lookup(sym):
        return persistence.get_global_security(sym, db_path=db)

    res = lg.validate_leverage_policy(ticker="ZZZUNLISTED", leverage=3.0, securities_lookup=lookup)
    assert res["jurisdiction_group"] == lg.UNKNOWN
    assert res["jurisdiction_resolution_source"] == lg.SRC_UNKNOWN_FAIL_CLOSED
    assert res["breach"] is True


def test_seeded_coverage_is_strong_or_better(tmp_path):
    db = tmp_path / "cov.db"
    smc.seed_universe(smc.load_seed_universe(), db)
    rep = smc.build_coverage_report(db_path=db)
    assert rep["score"] >= 0.80
    assert rep["status"] in {smc.STRONG, smc.COMPLETE_ENOUGH}


def test_empty_master_is_critical(tmp_path):
    # A fresh DB with no seeded securities -> nothing resolvable -> CRITICAL.
    db = tmp_path / "empty.db"
    rep = smc.build_coverage_report(db_path=db)
    assert rep["status"] == smc.CRITICAL
    assert rep["resolvable"] == 0


def test_no_write_without_explicit_seed(tmp_path):
    # build_coverage_report must not create securities rows.
    db = tmp_path / "ro.db"
    rep = smc.build_coverage_report(db_path=db)
    from scripts import persistence
    assert persistence.get_global_security("AAPL", db_path=db) is None
    assert rep["resolvable"] == 0


def test_advisory_stamps_present(tmp_path):
    rep = smc.build_coverage_report(db_path=tmp_path / "x.db")
    assert rep["advisory_status"] == "ADVISORY_ONLY"
    assert rep["broker_api_called"] is False
