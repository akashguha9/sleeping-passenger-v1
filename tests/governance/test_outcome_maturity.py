"""Section 10 — Outcome maturity rule."""
from __future__ import annotations

from scripts.governance.daily_gate import outcome_state, score_eligible


def test_open_two_days_pending():
    assert score_eligible({"trading_days_open": 2}) == 0
    assert outcome_state({"trading_days_open": 2}) == "PENDING_HORIZON"


def test_open_six_days_eligible():
    assert score_eligible({"trading_days_open": 6}) == 1
    assert outcome_state({"trading_days_open": 6}) == "SCORE_ELIGIBLE"


def test_exactly_five_days_eligible():
    assert score_eligible({"trading_days_open": 5}) == 1


def test_closed_eligible():
    assert score_eligible({"closed": True, "trading_days_open": 1}) == 1


def test_tp_and_stop_hits_eligible():
    assert score_eligible({"tp1_hit": True}) == 1
    assert score_eligible({"tp2_hit": True}) == 1
    assert score_eligible({"hard_stop_hit": True}) == 1
