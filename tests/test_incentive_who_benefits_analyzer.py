"""Tests for the Incentive / Who-Benefits Analyzer."""
from __future__ import annotations

from scripts.incentive_who_benefits_analyzer import (
    GRADE_EXIT_LIQUIDITY,
    score_incentive_who_benefits,
)

SESSION = "2026-06-07"


def _cand(**over):
    base = {
        "ticker": "PLTR", "country": "United States", "sector": "Software", "theme": "AI",
        "source_health": "VERIFIED_LIVE", "is_live": True, "evidence_type": "LIVE_PRICE_MOVER",
        "live_evidence_count": 1, "last_live_seen_date": SESSION, "catalyst": "",
    }
    base.update(over)
    return base


def test_A_high_hype_no_substance_missing_ownership_high_risk():
    r = score_incentive_who_benefits(
        _cand(),
        distribution={"distribution_amplification_score": 90.0},
        narrative_gap={"narrative_substance_gap": 70.0, "substance_strength": 0.1},
    )
    assert r["grade"] in ("HIGH", GRADE_EXIT_LIQUIDITY)
    assert "ownership_insider_data" in r["missing_fields"]
    assert r["advisory_only"] is True


def test_B_filing_backed_low_hype_low_or_medium():
    r = score_incentive_who_benefits(
        _cand(evidence_type="LIVE_FILING_EVENT", catalyst="8-K filed"),
        distribution={"distribution_amplification_score": 15.0},
        narrative_gap={"narrative_substance_gap": -40.0, "substance_strength": 0.8},
        ownership={"insider_concentration": 0.1},
        liquidity={"fragility": 0.1},
    )
    assert r["grade"] in ("LOW", "MEDIUM")


def test_C_missing_ownership_not_fabricated():
    r = score_incentive_who_benefits(_cand(), distribution={"distribution_amplification_score": 50.0})
    assert r["beneficiary_map"]["insiders"] == "unknown"
    assert "ownership_insider_data" in r["missing_fields"]


def test_D_static_blocked():
    r = score_incentive_who_benefits(_cand(source_health="UNVERIFIED", is_live=False))
    assert "not_live_not_scored" in r["asymmetry_flags"]


def test_E_exit_liquidity_from_hype_low_substance():
    r = score_incentive_who_benefits(
        _cand(),
        distribution={"distribution_amplification_score": 85.0},
        narrative_gap={"narrative_substance_gap": 65.0, "substance_strength": 0.1},
    )
    assert r["grade"] == GRADE_EXIT_LIQUIDITY
    assert any("exit_liquidity" in f for f in r["exit_liquidity_flags"])


def test_F_advisory_only():
    assert score_incentive_who_benefits(_cand())["advisory_only"] is True
