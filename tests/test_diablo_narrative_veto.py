"""Diablo narrative veto — dangerous combinations get a hard advisory veto.

Proves the weak-signal + strong-emotion + leverage combination fires, the
veto state is correct, recommended actions are only safe non-trading actions,
and a clean setup is not vetoed.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts import diablo_narrative_veto as veto


def test_weak_signal_emotion_leverage_triggers_veto():
    rep = veto.evaluate_veto(signal_strength=0.1, operator_emotion=0.9, leverage=0.9)
    assert rep["diablo_veto"] is True
    assert rep["veto_state"] == veto.VETO_DIABLO
    assert "weak_signal+strong_emotion+leverage" in rep["veto_reason"]


def test_viral_narrative_without_fundamentals_triggers_veto():
    rep = veto.evaluate_veto(narrative_virality=0.9, fundamental_support=0.1)
    assert rep["diablo_veto"] is True
    assert "viral_narrative+no_fundamental_support" in rep["veto_reason"]


def test_thin_polymarket_high_impact_is_review_not_hard_veto():
    rep = veto.evaluate_veto(polymarket_move_thinness=0.9, asset_impact=0.9)
    assert rep["veto_state"] == veto.VETO_REVIEW


def test_clean_setup_is_not_vetoed():
    rep = veto.evaluate_veto(
        signal_strength=0.8, operator_emotion=0.1, leverage=0.1,
        narrative_virality=0.3, fundamental_support=0.8,
        invalidation_clarity=0.8, crowding=0.2, liquidity=0.8,
    )
    assert rep["diablo_veto"] is False
    assert rep["veto_state"] == veto.VETO_NONE


def test_recommended_actions_are_safe_only():
    rep = veto.evaluate_veto(signal_strength=0.1, operator_emotion=0.9, leverage=0.9)
    action = rep["recommended_safe_action"].lower()
    for forbidden in ("buy", "sell", "execute", "place order", "submit order"):
        assert forbidden not in action


def test_advisory_stamps_present():
    rep = veto.evaluate_veto()
    assert rep["advisory_status"] == "ADVISORY_ONLY"
    assert rep["broker_api_called"] is False
    assert rep["ai_execution_count"] == 0
