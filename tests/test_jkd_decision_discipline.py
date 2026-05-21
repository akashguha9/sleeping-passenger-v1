"""JKD decision-discipline — score, penalties, and state consequence.

Proves the Jeet Kune Do score computes from the documented weights, that the
penalties (noise / greed / chaos) pull it down, that high chaos or operator
heat forces DIABLO_NO_NEW_RISK, and that every state maps to a concrete
advisory action constraint (a state without consequence would be decorative).
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts import jkd_decision_discipline as jkd


def test_score_computes_from_weights():
    rep = jkd.compute_jkd(
        interception=10, directness=10, adaptability=10, economy=10,
        reality_confirmation=10, noise=0, greed_ego=0, chaos_risk=0,
    )
    # All virtues maxed, no penalty -> positive weight ceiling 0.86 * 10 = 8.6.
    assert rep["jkd_score"] == 8.6
    assert rep["advisory_state"] == jkd.STATE_AVENTADOR
    assert rep["action_constraint"] == jkd.CONSTRAINT_HUMAN_REVIEW


def test_high_interception_raises_score():
    low = jkd.compute_jkd(interception=2, directness=7, adaptability=7, economy=7,
                          reality_confirmation=7, noise=1, greed_ego=1, chaos_risk=1)
    high = jkd.compute_jkd(interception=9, directness=7, adaptability=7, economy=7,
                           reality_confirmation=7, noise=1, greed_ego=1, chaos_risk=1)
    assert high["jkd_score"] > low["jkd_score"]


def test_high_noise_lowers_score():
    quiet = jkd.compute_jkd(interception=8, directness=8, adaptability=8, economy=8,
                            reality_confirmation=8, noise=0, greed_ego=0, chaos_risk=0)
    noisy = jkd.compute_jkd(interception=8, directness=8, adaptability=8, economy=8,
                            reality_confirmation=8, noise=10, greed_ego=0, chaos_risk=0)
    assert noisy["jkd_score"] < quiet["jkd_score"]


def test_high_chaos_forces_diablo():
    rep = jkd.compute_jkd(interception=9, directness=9, adaptability=9, economy=9,
                          reality_confirmation=9, noise=0, greed_ego=0, chaos_risk=9)
    assert rep["advisory_state"] == jkd.STATE_DIABLO
    assert rep["action_constraint"] == jkd.CONSTRAINT_RECONCILE


def test_high_operator_heat_triggers_diablo_no_new_risk():
    rep = jkd.compute_jkd(interception=9, directness=9, adaptability=9, economy=9,
                          reality_confirmation=9, noise=0, greed_ego=9, chaos_risk=0)
    assert rep["advisory_state"] == jkd.STATE_DIABLO
    assert rep["action_constraint"] == jkd.CONSTRAINT_RECONCILE


def test_state_maps_to_constraint_across_bands():
    # MURCIELAGO band (positive ceiling 6.88 with virtues at 8, no penalty)
    mid = jkd.compute_jkd(interception=8, directness=8, adaptability=8, economy=8,
                          reality_confirmation=8, noise=0, greed_ego=0, chaos_risk=0)
    assert 6.5 <= mid["jkd_score"] < 8.0
    assert mid["advisory_state"] == jkd.STATE_MURCIELAGO
    assert mid["action_constraint"] == jkd.CONSTRAINT_WATCHLIST
    # WAIT band
    low = jkd.compute_jkd(interception=2, directness=2, adaptability=2, economy=2,
                          reality_confirmation=2, noise=3, greed_ego=2, chaos_risk=2)
    assert low["jkd_score"] < 5.0
    assert low["advisory_state"] == jkd.STATE_WAIT
    assert low["action_constraint"] == jkd.CONSTRAINT_NO_NEW_RISK


def test_uninvalidatable_thesis_is_capped():
    """A signal that cannot be invalidated is useless — low directness caps
    the score and forbids AVENTADOR promotion."""
    rep = jkd.compute_jkd(interception=10, directness=1, adaptability=10, economy=10,
                          reality_confirmation=10, noise=0, greed_ego=0, chaos_risk=0)
    assert rep["invalidation_capped"] is True
    assert rep["jkd_score"] <= jkd.LOW_DIRECTNESS_CAP
    assert rep["advisory_state"] != jkd.STATE_AVENTADOR


def test_interception_volume_and_consensus():
    """High narrative acceleration without volume confirmation raises a
    false-positive warning; volume + delayed consensus is the real signal."""
    headfake = jkd.compute_interception(0.2, 0.9, 0.1, 0.2)
    confirmed = jkd.compute_interception(0.7, 0.7, 0.8, 0.7)
    assert headfake["false_positive_warning"] is True
    assert confirmed["false_positive_warning"] is False
    assert confirmed["interception_score"] > headfake["interception_score"]


def test_directness_invalidation_dominates():
    with_inval = jkd.compute_directness(1.0, 0.5, 0.5, 0.5, 0.5)
    without_inval = jkd.compute_directness(0.0, 0.5, 0.5, 0.5, 0.5)
    assert with_inval["directness_score"] > without_inval["directness_score"]


def test_advisory_only_stamps_present():
    rep = jkd.compute_jkd(interception=5, directness=5, adaptability=5, economy=5,
                          reality_confirmation=5, noise=0, greed_ego=0, chaos_risk=0)
    assert rep["advisory_status"] == "ADVISORY_ONLY"
    assert rep["broker_api_called"] is False
    assert rep["ai_execution_count"] == 0
    assert rep["human_review_required"] is True
