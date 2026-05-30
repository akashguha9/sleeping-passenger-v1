"""Phase 4 — capital-rotation / capacity guard affects live advisory output.

Proves ``evaluate_capacity`` is wired into ``run_live_decision_path``: a missing
stop or unknown capital blocks/downgrades, cash_required is surfaced, country
caps bite, and every sizing field uses advisory (not order) language.
"""
from __future__ import annotations

import json

from scripts.live_decision_path import run_live_decision_path

_AXES = {"EMS": 0.7, "EQS": 0.7, "DS": 0.7, "LS": 0.7, "EFS": 0.7, "APS": 0.7}


def _kwargs(**overrides):
    base = dict(
        signal_id="SIG_CAP",
        axes=_AXES,
        ticker="RELIANCE.NS",
        country="India",
        api_health_status="OK",
        rows_added=5,
        canonical_age_hours=1.0,
        state="HURACAN",
        chaos_risk=0.1,
        capital=1_000_000.0,
        cash_available=500_000.0,
        entry_price=100.0,
        hard_stop_price=95.0,
        leverage=1.0,
        leverage_valid=True,
        db_path=None,
    )
    base.update(overrides)
    return base


def test_missing_stop_blocks_live_candidate_capacity():
    out = run_live_decision_path(**_kwargs(hard_stop_price=None))
    cap = out["capacity_result"]
    assert cap["position_size_allowed"] is False
    assert cap["downside_risk_pct"] is None
    assert out["capacity_ok"] is False
    # admission gate must not promote a no-capacity candidate
    assert out["final_advisory_class"] != "ADVISORY_CANDIDATE_FOR_HUMAN_REVIEW"


def test_capacity_unknown_blocks_or_downgrades_candidate():
    out = run_live_decision_path(**_kwargs(capital=None, cash_available=None))
    assert out["capacity_status"] == "CAPACITY_UNKNOWN"
    assert out["capacity_ok"] is False
    assert out["final_advisory_class"] != "ADVISORY_CANDIDATE_FOR_HUMAN_REVIEW"


def test_cash_required_visible_in_advisory_metadata():
    out = run_live_decision_path(**_kwargs())
    cap = out["capacity_result"]
    assert "cash_required" in cap
    assert "risk_budget" in cap
    assert "position_notional" in cap
    assert cap["cash_required"] is not None


def test_country_cap_blocks_live_candidate():
    # Non-India cap is 25%; pre-load exposure beyond the cap so any new
    # notional breaches it.
    out = run_live_decision_path(
        **_kwargs(country="USA", ticker="AAPL", existing_country_exposure=260_000.0)
    )
    cap = out["capacity_result"]
    assert cap["country_cap"] == 0.25
    assert cap["country_cap_ok"] is False
    assert out["capacity_ok"] is False


def test_leverage_invalid_blocks_capacity():
    out = run_live_decision_path(**_kwargs(leverage_valid=False))
    cap = out["capacity_result"]
    assert cap["portfolio_capacity_ok"] is False
    assert out["capacity_ok"] is False
    assert out["final_advisory_class"] != "ADVISORY_CANDIDATE_FOR_HUMAN_REVIEW"


def test_capacity_ok_allows_gate_to_continue_but_not_execute():
    out = run_live_decision_path(**_kwargs())
    assert out["capacity_ok"] is True
    # Capacity OK lets the gate proceed, but execution stays locked.
    assert out["execution_gate"] == "LOCKED"
    assert out["broker_api_called"] is False
    assert out["ai_execution_count"] == 0


def test_capacity_output_uses_advisory_language_not_order_language():
    out = run_live_decision_path(**_kwargs())
    cap = out["capacity_result"]
    # Advisory alias present; no order-quantity framing.
    assert "suggested_paper_notional" in cap
    blob = json.dumps(cap).lower()
    for bad in ("order_quantity", "order quantity", "place_order", "buy_now",
                "sell_now", "shares_to_buy", "submit_order"):
        assert bad not in blob
    assert cap["executes_trade"] is False
