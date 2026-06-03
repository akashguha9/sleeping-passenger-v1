"""Diversification cap — tiebreaker, not quota."""
from __future__ import annotations

from scripts.portfolio_diversification_cap import (
    apply_diversification_cap,
    load_diversification_config,
)


def _c(t: str, country: str, sector: str, s: float) -> dict:
    return {"ticker": t, "country": country, "sector": sector, "composite_score": s}


def test_country_cap_drops_third_us_name() -> None:
    ranked = [
        _c("AAPL", "US", "Tech", 0.90),
        _c("MSFT", "US", "Tech", 0.88),
        _c("NVDA", "US", "Semi", 0.86),  # 3rd US — must be dropped
        _c("SAP.DE", "DE", "Software", 0.84),
    ]
    cfg = dict(load_diversification_config())
    cfg["max_picks_per_country"] = 2
    cfg["max_picks_per_sector"] = 5
    cfg["max_picks_per_day"] = 10
    out = apply_diversification_cap(ranked, config=cfg)
    tickers = [p["ticker"] for p in out["picks"]]
    assert tickers == ["AAPL", "MSFT", "SAP.DE"]
    assert {d["ticker"]: d["reason"] for d in out["dropped"]} == {"NVDA": "country_cap"}


def test_sector_cap_drops_excess_in_same_sector() -> None:
    ranked = [
        _c("AAPL", "US", "Tech", 0.90),
        _c("MSFT", "US", "Tech", 0.88),
        _c("SAP.DE", "DE", "Tech", 0.86),  # 3rd Tech — dropped
        _c("RY.TO", "CA", "Bank", 0.84),
    ]
    cfg = dict(load_diversification_config())
    cfg["max_picks_per_country"] = 5
    cfg["max_picks_per_sector"] = 2
    out = apply_diversification_cap(ranked, config=cfg)
    tickers = [p["ticker"] for p in out["picks"]]
    assert tickers == ["AAPL", "MSFT", "RY.TO"]
    assert {d["ticker"]: d["reason"] for d in out["dropped"]} == {"SAP.DE": "sector_cap"}


def test_day_cap_emits_at_most_max_picks() -> None:
    ranked = [_c(f"T{i}", "DE" if i % 2 else "FR", f"S{i}", 0.9 - i * 0.01) for i in range(12)]
    cfg = dict(load_diversification_config())
    cfg["max_picks_per_country"] = 99
    cfg["max_picks_per_sector"] = 99
    cfg["max_picks_per_day"] = 5
    out = apply_diversification_cap(ranked, config=cfg)
    assert len(out["picks"]) == 5
    assert all(d["reason"] == "day_cap" for d in out["dropped"])


def test_ineligible_country_is_excluded() -> None:
    ranked = [
        _c("AAPL", "US", "Tech", 0.90),
        _c("GAZP.RU", "RU", "Energy", 0.85),  # RU excluded
        _c("SAP.DE", "DE", "Tech", 0.80),
    ]
    out = apply_diversification_cap(ranked)
    tickers = [p["ticker"] for p in out["picks"]]
    assert "GAZP.RU" not in tickers
    drop = next(d for d in out["dropped"] if d["ticker"] == "GAZP.RU")
    assert drop["reason"] == "country_not_eligible"


def test_no_min_country_injection_when_quality_is_thin() -> None:
    """If only one country produces quality candidates, do NOT inject weaker
    names from other countries to satisfy a target. Emit fewer picks instead.
    """
    ranked = [
        _c("AAPL", "US", "Tech", 0.90),
        _c("MSFT", "US", "Soft", 0.88),
    ]
    cfg = dict(load_diversification_config())
    cfg["target_distinct_countries"] = 5  # aspirational, must not inject
    out = apply_diversification_cap(ranked, config=cfg)
    assert [p["ticker"] for p in out["picks"]] == ["AAPL", "MSFT"]
    assert out["distribution"]["distinct_countries"] == 1
    assert out["distribution"]["target_distinct_countries_met"] is False


def test_distribution_report_is_emitted() -> None:
    ranked = [
        _c("AAPL", "US", "Tech", 0.90),
        _c("SAP.DE", "DE", "Tech", 0.88),
        _c("TM.JP", "JP", "Auto", 0.86),
        _c("BHP.AX", "AU", "Mat", 0.84),
        _c("D05.SI", "SG", "Bank", 0.82),
    ]
    out = apply_diversification_cap(ranked)
    d = out["distribution"]
    assert d["distinct_countries"] == 5
    assert d["picks_per_country"] == {"US": 1, "DE": 1, "JP": 1, "AU": 1, "SG": 1}
    assert d["target_distinct_countries_met"] is True


def test_disabled_cap_is_passthrough() -> None:
    ranked = [_c(f"T{i}", "US", "X", 0.9 - i * 0.01) for i in range(8)]
    cfg = dict(load_diversification_config())
    cfg["enabled"] = False
    out = apply_diversification_cap(ranked, config=cfg)
    assert len(out["picks"]) == 8
    assert out["dropped"] == []


def test_higher_score_preserved_after_caps() -> None:
    # Verify caps respect input order (which the caller has set by composite score).
    ranked = [
        _c("HIGH_US", "US", "Tech", 0.95),
        _c("HIGH_FR", "FR", "Tech", 0.94),  # blocked by sector cap (=2)
        _c("MID_US", "US", "Bank", 0.80),
        _c("LOW_US", "US", "Bank", 0.70),   # blocked by US country cap=2
    ]
    cfg = dict(load_diversification_config())
    cfg["max_picks_per_country"] = 2
    cfg["max_picks_per_sector"] = 1
    out = apply_diversification_cap(ranked, config=cfg)
    tickers = [p["ticker"] for p in out["picks"]]
    assert tickers == ["HIGH_US", "MID_US"]
