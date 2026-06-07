"""Tests for Adverse Regime Stress Test (ARST)."""
from __future__ import annotations

from scripts.adverse_regime_stress_test import (
    GRADE_INSUFFICIENT,
    GRADE_ROBUST,
    stress_test_candidate,
)

SESSION = "2026-06-07"

_STRONG = {
    "debt_to_equity": 0.2,
    "gross_margin": 0.85,
    "current_ratio": 2.5,
    "earnings_stability": 0.8,
    "interest_coverage": 10,
}


def _cand(**over):
    base = {
        "ticker": "PLTR",
        "country": "United States",
        "sector": "Utilities",
        "theme": "Defensive",
        "source_health": "VERIFIED_LIVE",
        "is_live": True,
        "last_live_seen_date": SESSION,
    }
    base.update(over)
    return base


def test_A_data_rich_robust():
    r = stress_test_candidate(_cand(), fundamentals=_STRONG)
    assert r["grade"] == GRADE_ROBUST
    assert r["survival_score"] >= 1.25
    assert r["advisory_only"] is True


def test_B_missing_fundamentals_insufficient_data():
    r = stress_test_candidate(_cand())
    assert r["grade"] == GRADE_INSUFFICIENT
    assert r["stress_failure_risk"] >= 60


def test_C_high_leverage_increases_failure_risk():
    low = stress_test_candidate(_cand(), fundamentals=dict(_STRONG, leverage=1.0))
    high = stress_test_candidate(_cand(), fundamentals=dict(_STRONG, leverage=4.0))
    assert high["stress_failure_risk"] >= low["stress_failure_risk"]
    assert any("leverage" in f for f in high["stress_flags"])


def test_D_crowded_ai_theme_increases_load():
    calm = stress_test_candidate(_cand(sector="Utilities", theme="Defensive"), fundamentals=_STRONG)
    crowded = stress_test_candidate(_cand(sector="Software", theme="AI"), fundamentals=_STRONG)
    assert crowded["stress_load"] >= calm["stress_load"]
    assert "crowded_or_high_beta_theme" in crowded["stress_flags"]


def test_E_semis_defense_sector_flags():
    semis = stress_test_candidate(_cand(sector="Semiconductors", theme="Chips"), fundamentals=_STRONG)
    assert "sector_regulatory_exposure" in semis["stress_flags"]
    assert "supply_chain_exposure" in semis["stress_flags"]
    defense = stress_test_candidate(_cand(sector="Defense", theme="Defense"), fundamentals=_STRONG)
    assert "geopolitical_exposure" in defense["stress_flags"]


def test_F_stale_never_robust():
    r = stress_test_candidate(_cand(is_live=False, source_health="UNVERIFIED"), fundamentals=_STRONG)
    assert r["grade"] != GRADE_ROBUST
    assert r["grade"] == GRADE_INSUFFICIENT


def test_G_advisory_only_always_true():
    assert stress_test_candidate(_cand(), fundamentals=_STRONG)["advisory_only"] is True
    assert stress_test_candidate(_cand())["advisory_only"] is True


def test_scenarios_present():
    r = stress_test_candidate(_cand(), fundamentals=_STRONG)
    for scenario in ("recession", "liquidity_shock", "margin_compression",
                     "rate_shock", "regulatory_shock", "geopolitical_shock"):
        assert scenario in r["stress_scenarios"]
