"""Tests for Metric Regime Transfer Risk (MTR)."""
from __future__ import annotations

from scripts.metric_regime_transfer_risk import (
    GRADE_LOW,
    GRADE_UNRELIABLE,
    score_metric_regime_transfer_risk,
)

SESSION = "2026-06-07"


def _cand(**over):
    base = {
        "ticker": "PLTR",
        "country": "United States",
        "region": "US",
        "sector": "Software",
        "theme": "AI",
        "currency": "USD",
        "evidence_type": "LIVE_PRICE_MOVER",
        "source_health": "VERIFIED_LIVE",
        "is_live": True,
        "last_live_seen_date": SESSION,
        "from_cache": False,
        "from_moltbook": False,
        "from_trade_log": False,
        "catalyst": "Live gap + volume today",
    }
    base.update(over)
    return base


def test_A_same_regime_rich_low_risk():
    ref = {"geography": "UNITED STATES", "sector": "SOFTWARE", "currency": "USD", "leverage": 1.0}
    r = score_metric_regime_transfer_risk(_cand(), reference_regime=ref, run_date=SESSION)
    assert r["grade"] == GRADE_LOW
    assert r["metric_regime_transfer_risk"] <= 25
    assert r["advisory_only"] is True


def test_B_us_ai_into_india_leverage_high_risk():
    ref = {"geography": "INDIA", "sector": "FINANCIALS", "currency": "INR", "leverage": 4.0}
    r = score_metric_regime_transfer_risk(_cand(), reference_regime=ref, run_date=SESSION)
    assert r["grade"] in ("HIGH", GRADE_UNRELIABLE)
    assert r["metric_regime_transfer_risk"] >= 51
    assert "geography_mismatch" in r["regime_shift_flags"]


def test_C_structural_no_catalyst_high_risk():
    r = score_metric_regime_transfer_risk(_cand(catalyst="", evidence_type="LIVE_PRICE_MOVER"), run_date=SESSION)
    assert r["metric_regime_transfer_risk"] >= 51


def test_D_missing_geography_sector_unreliable():
    r = score_metric_regime_transfer_risk(
        _cand(country="UNKNOWN", region="UNKNOWN", sector="UNKNOWN"), run_date=SESSION
    )
    assert r["grade"] == GRADE_UNRELIABLE
    assert r["metric_regime_transfer_risk"] >= 76


def test_E_live_filing_with_sector_beats_generic_price_mover():
    filing = score_metric_regime_transfer_risk(
        _cand(evidence_type="LIVE_FILING_EVENT", catalyst=""), run_date=SESSION
    )
    generic = score_metric_regime_transfer_risk(
        _cand(evidence_type="LIVE_PRICE_MOVER", sector="UNKNOWN", catalyst=""), run_date=SESSION
    )
    assert filing["metric_regime_transfer_risk"] < generic["metric_regime_transfer_risk"]


def test_F_does_not_promote_keeps_ticker():
    r = score_metric_regime_transfer_risk(_cand(ticker="RHM.DE"), run_date=SESSION)
    assert r["ticker"] == "RHM.DE"


def test_G_advisory_only_always_true():
    assert score_metric_regime_transfer_risk(_cand(), run_date=SESSION)["advisory_only"] is True
