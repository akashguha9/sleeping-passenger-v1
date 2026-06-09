"""Tests for the Signal Payoff-Capture Estimator (PC) — P3 value-capture module."""
from __future__ import annotations

from scripts.signal_payoff_capture_estimator import (
    GRADE_STRONG,
    GRADE_WEAK,
    score_signal_payoff_capture,
)

SESSION = "2026-06-08"
_STRONG_MARGINS = {"gross_margin": 0.85, "operating_margin": 0.45, "earnings_stability": 0.8, "debt_to_equity": 0.15}
_WEAK = {"gross_margin": 0.08, "operating_margin": 0.02, "earnings_stability": 0.2, "debt_to_equity": 0.95}


def _cand(**over):
    base = {
        "ticker": "PLTR", "country": "United States", "sector": "Software",
        "source_health": "VERIFIED_LIVE", "is_live": True,
        "evidence_type": "LIVE_FILING_EVENT", "live_evidence_count": 2,
        "last_live_seen_date": SESSION, "catalyst": "8-K contract award filed today",
    }
    base.update(over)
    return base


def test_A_monopoly_high_margin_is_strong_capture():
    r = score_signal_payoff_capture(
        _cand(), fundamentals=_STRONG_MARGINS, structure={"market_structure": "monopoly"}
    )
    assert r["capture_grade"] == GRADE_STRONG
    assert r["payoff_capture_risk"] <= 45.0
    assert r["advisory_only"] is True


def test_B_commodity_thin_margin_high_debt_is_weak_capture():
    r = score_signal_payoff_capture(
        _cand(evidence_type="LIVE_PRICE_MOVER"),
        fundamentals=_WEAK,
        structure={"market_structure": "commodity", "supplier_power": 0.8, "capex_intensity": 0.9},
    )
    assert r["capture_grade"] == GRADE_WEAK
    assert "weak_payoff_capture" in r["capture_flags"]
    assert r["payoff_capture_risk"] > 70.0


def test_C_gross_not_net_flag_when_thin_residual():
    r = score_signal_payoff_capture(
        _cand(evidence_type="LIVE_PRICE_MOVER"),
        fundamentals={"gross_margin": 0.05, "debt_to_equity": 0.9},
        structure={"market_structure": "commodity", "supplier_power": 0.9},
    )
    assert "gross_not_net" in r["capture_flags"]


def test_D_commodity_structure_flagged():
    r = score_signal_payoff_capture(
        _cand(), fundamentals=_STRONG_MARGINS, structure={"market_structure": "commodity competition"}
    )
    assert "commodity_structure" in r["capture_flags"]


def test_E_not_live_not_scored():
    r = score_signal_payoff_capture(
        _cand(source_health="UNVERIFIED", is_live=False, evidence_type="STATIC_UNIVERSE_FALLBACK")
    )
    assert "not_live_not_scored" in r["capture_flags"]


def test_F_missing_feeds_surfaced():
    r = score_signal_payoff_capture(_cand())  # no fundamentals/structure feeds
    assert "market_structure" in r["missing_fields"]
    assert "margins" in r["missing_fields"]


def test_G_toll_gate_lifts_structural_position():
    base = score_signal_payoff_capture(_cand(), fundamentals=_STRONG_MARGINS)
    toll = score_signal_payoff_capture(
        _cand(), fundamentals=_STRONG_MARGINS, structure={"switching_costs": 0.9, "distribution_control": 0.9}
    )
    assert toll["structural_position"] >= base["structural_position"]
    assert toll["payoff_capture_risk"] <= base["payoff_capture_risk"]


def test_H_advisory_only_keeps_ticker():
    r = score_signal_payoff_capture(_cand(ticker="ZIM"), fundamentals=_STRONG_MARGINS)
    assert r["ticker"] == "ZIM"
    assert r["advisory_only"] is True


# --- Auditable diagnostic layer (2026-06-09 reflection) ---------------------

def _diag(fundamentals=None, structure=None, **cand_over):
    return score_signal_payoff_capture(
        _cand(**cand_over), fundamentals=fundamentals, structure=structure
    )["diagnostic"]


def test_diag_case1_high_revenue_weak_margin():
    d = _diag(
        fundamentals={"operating_margin": 0.04, "ocf_to_net_income": 1.0, "fcfe_to_net_income": 0.8},
        structure={"pricing_power": 0.8},
    )
    assert d["gross_to_margin_capture"] == "weak"
    assert d["primary_value_leak"] == "weak_margin_capture"
    assert d["explanatory_only"] is True
    assert "margin" in d["falsification_hint"].lower()


def test_diag_case2_high_profit_weak_cash():
    d = _diag(
        fundamentals={"operating_margin": 0.25, "ocf_to_net_income": 0.3, "fcfe_to_net_income": 0.8},
        structure={"pricing_power": 0.8},
    )
    assert d["profit_to_cash_capture"] == "weak"
    assert d["primary_value_leak"] == "weak_cash_conversion"


def test_diag_case2b_working_capital_drag():
    d = _diag(
        fundamentals={"operating_margin": 0.25, "ocf_to_net_income": 0.3,
                      "fcfe_to_net_income": 0.8, "receivable_days_change": 8.0},
        structure={"pricing_power": 0.8},
    )
    assert d["primary_value_leak"] == "working_capital_drag"


def test_diag_case3_strong_cash_high_capex_burden():
    d = _diag(
        fundamentals={"operating_margin": 0.25, "ocf_to_net_income": 1.0, "fcfe_to_net_income": 0.2},
        structure={"pricing_power": 0.8, "capex_intensity": 0.7},
    )
    assert d["cash_to_owner_capture"] == "weak"
    assert d["primary_value_leak"] == "capex_burden"


def test_diag_case3b_debt_burden():
    d = _diag(
        fundamentals={"operating_margin": 0.25, "ocf_to_net_income": 1.0,
                      "fcfe_to_net_income": 0.2, "debt_to_equity": 0.85},
        structure={"pricing_power": 0.8},
    )
    assert d["primary_value_leak"] == "debt_or_interest_burden"


def test_diag_case4_platform_toll_and_false_house():
    d = _diag(
        fundamentals={"operating_margin": 0.25, "ocf_to_net_income": 1.0, "fcfe_to_net_income": 0.8},
        structure={"pricing_power": 0.3, "platform_fee_dependence": 0.7,
                   "gmv": 0.9, "take_rate": 0.05, "incentive_intensity": 0.6},
    )
    assert d["bargaining_capture"] == "weak"
    assert d["primary_value_leak"] == "platform_or_intermediary_toll"
    assert d["false_house_risk"] == "high"


def test_diag_case5_insufficient_evidence():
    d = _diag()  # no fundamentals, no structure
    assert d["primary_value_leak"] == "insufficient_evidence"
    assert d["owner_capture_confidence"] == "low"
    assert d["false_house_risk"] == "not_evaluated"


def test_diag_confidence_scales_with_evidence():
    full = _diag(
        fundamentals={"operating_margin": 0.25, "ocf_to_net_income": 1.0, "fcfe_to_net_income": 0.8},
        structure={"pricing_power": 0.8},
    )
    assert full["owner_capture_confidence"] == "high"


def test_diag_not_live_is_insufficient():
    r = score_signal_payoff_capture(
        _cand(source_health="UNVERIFIED", is_live=False, evidence_type="STATIC_UNIVERSE_FALLBACK")
    )
    assert r["diagnostic"]["primary_value_leak"] == "insufficient_evidence"
    assert r["diagnostic"]["explanatory_only"] is True


def test_diag_does_not_change_risk_or_grade():
    # Diagnostic is explanatory-only: the score/grade come from the same inputs
    # and must be independent of the diagnostic fields' existence.
    r = score_signal_payoff_capture(
        _cand(), fundamentals=_STRONG_MARGINS, structure={"market_structure": "monopoly"}
    )
    assert r["capture_grade"] == GRADE_STRONG  # unchanged from test_A
    assert "diagnostic" in r and r["diagnostic"]["explanatory_only"] is True
