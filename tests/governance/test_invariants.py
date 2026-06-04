"""Section 20 — invariants that must never break."""
from __future__ import annotations

import copy

import pytest


def test_1_non_H_ticker_never_gets_existing_holding_review(gov_result):
    H = set(gov_result.portfolio_truth.current_holdings_H)
    for r in gov_result.existing_holding_review_board:
        assert r.ticker in H
    for r in gov_result.reduce_exit_review_board:
        assert r.ticker in H


def test_2_closed_sold_donotmanage_always_quarantined(gov_result):
    truth = gov_result.portfolio_truth
    bad = set(truth.closed) | set(truth.sold) | set(truth.do_not_manage)
    quarantined = {b.ticker for b in gov_result.phantom_quarantine_board}
    assert bad <= quarantined


def test_3_source_failed_forbids_manual_add(gov_result):
    assert gov_result.source_health.status == "FAILED"
    assert gov_result.top_manual_add_consideration == []
    assert gov_result.manual_promotion_gate["manual_add_allowed"] is False


def test_4_low_why_today_forbids_manual_add(gov_result):
    for a in gov_result.candidate_quality_board:
        if a.why_today < 0.70:
            assert a.manual_add_consideration is False


def test_5_missing_prices_for_all_H_forces_no_new_risk(gov_result):
    assert gov_result.source_health.current_prices_missing_for_all_H is True
    assert gov_result.no_new_risk_day == "YES"


def test_6_4x_holding_missing_price_forces_no_new_risk(gov_result):
    assert gov_result.no_new_risk_day == "YES"


def test_7_wrong_date_model_cannot_create_action_permission(gov_result):
    assert gov_result.new_risk_permission is False
    mistral = next(m for m in gov_result.model_reliability if m.model == "mistral")
    assert mistral.action_calls_downgraded is True


def test_8_stale_candidate_without_fresh_catalyst_not_promoted(gov_result):
    board = {a.ticker: a for a in gov_result.candidate_quality_board}
    # nothing on a failed-source day is a manual add, including stale repeats
    assert all(not a.manual_add_consideration for a in board.values())


def test_9_diversity_underrepresentation_cannot_force_promotion(gov_inputs, evaluate):
    data = copy.deepcopy(gov_inputs)
    # add a lone weak candidate from an underrepresented country; it must not
    # be promoted to manual add just because its region is rare.
    data["model_candidate_votes"].append({
        "ticker": "WEAK.SA", "country": "BRAZIL", "models": ["claude"],
        "static_fallback_only": True, "evidence_strength": 0.1,
        "model_agreement": 0.1, "catalyst_freshness": 0.0, "theme_strength": 0.1,
        "risk_reward_clarity": 0.1, "data_freshness": 0.0,
    })
    res = evaluate(data)
    weak = next(a for a in res.candidate_quality_board if a.ticker == "WEAK.SA")
    assert weak.manual_add_consideration is False
    assert weak.classification != "MANUAL_ADD_CONSIDERATION"


def test_10_execution_gate_always_locked(gov_result):
    assert gov_result.execution_gate_status == "LOCKED"
    assert gov_result.broker_execution_allowed is False
    assert gov_result.human_execution_required is True
    assert gov_result.final_daily_decision_board["execution_gate_status"] == "LOCKED"


def test_healthy_day_unblocks_discovery(evaluate):
    """A clean live day flips new_risk_permission to True and lets a strong
    candidate climb to WATCH — proving the gate is fail-closed, not fail-stuck.

    Note: the spec's FCS positive weights sum to 0.84, so the literal
    manual_add_fcs_min of 0.85 is mathematically unreachable via the candidate
    FCS path. We honour the literal formula/threshold (maximally conservative
    about fresh adds), so even a perfect candidate tops out at WATCH while the
    day itself becomes a discovery day."""
    live = {"provider": "POLYGON", "is_live": True, "provider_quality": 1.0,
            "freshness": 1.0, "completeness": 1.0, "records": [{"x": 1}]}
    inputs = {
        "run_date": "2026-06-05",
        "verified_current_holdings": [{"ticker": "MSFT", "status": "OPEN", "leverage": 1,
                                       "stop_status": "set", "tp_status": "set"}],
        "closed_positions": [], "sold_positions": [], "not_owned_do_not_manage": [],
        "current_prices": {"MSFT": 100.0, "provider": "POLYGON", "provider_quality": 1.0, "freshness": 1.0},
        "today_market_snapshot": live,
        "today_price_movers": {**live, "movers": [{"x": 1}]},
        "today_news_events": {**live, "events": [{"x": 1}]},
        "today_filings_events": {**live, "events": [{"x": 1}]},
        "previous_candidates": [],
        "model_candidate_votes": [{
            "ticker": "GOOD", "country": "US", "models": ["claude", "gpt", "gemini", "grok", "mistral"],
            "live_price_trigger": 1.0, "live_news_catalyst": 1.0, "live_filing_catalyst": 1.0,
            "abnormal_volume_or_move": 1.0, "fresh_model_consensus": 1.0,
            "evidence_strength": 1.0, "model_agreement": 1.0, "catalyst_freshness": 1.0,
            "theme_strength": 1.0, "risk_reward_clarity": 1.0, "data_freshness": 1.0,
            "invalidation_clarity": 1.0, "liquidity_confidence": 1.0, "reconciliation_cleanliness": 1.0,
        }],
        "model_existing_holding_reviews": [], "trade_log": [],
        "config": {"models": [{"name": n} for n in ("claude", "gpt", "gemini", "grok", "mistral")]},
    }
    res = evaluate(inputs)
    assert res.source_health.status == "HIGH"
    good = next(a for a in res.candidate_quality_board if a.ticker == "GOOD")
    # strongest reachable tier for a fresh candidate is WATCH (FCS max 0.84).
    assert good.classification == "WATCH"
    assert good.why_today == 1.0
    # the day is no longer fail-stuck: discovery is permitted again ...
    assert res.no_new_risk_day == "NO"
    assert res.new_risk_permission is True
    # ... but the execution gate ALWAYS stays LOCKED and human execution required.
    assert res.execution_gate_status == "LOCKED"
    assert res.broker_execution_allowed is False
