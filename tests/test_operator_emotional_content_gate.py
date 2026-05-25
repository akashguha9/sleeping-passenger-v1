"""Operator emotional content gate — heat is a sizing/risk variable.

Proves FOMO/revenge/urgency raise heat, heat shrinks effective size, heat
above the threshold triggers DIABLO_NO_NEW_RISK, recommended actions are
always non-trading, and no medical/therapeutic language leaks in.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts import operator_emotional_content_gate as gate


def test_fomo_revenge_urgency_raise_heat():
    cool = gate.compute_operator_heat()
    hot = gate.compute_operator_heat(fomo=0.9, revenge=0.9, urgency=0.9)
    assert hot["operator_heat"] > cool["operator_heat"]
    assert cool["operator_heat"] == 0.0


def test_heat_reduces_effective_size():
    rep = gate.compute_operator_heat(fomo=1.0, base_size=10.0)
    # EffectivePositionSize = BaseSize * (1 - heat); fomo weight 0.30 -> heat 0.30.
    assert rep["operator_heat"] == 0.30
    assert rep["effective_position_size"] == 7.0
    assert rep["size_adjustment"] == -3.0


def test_high_heat_triggers_diablo():
    rep = gate.compute_operator_heat(
        fomo=1.0, revenge=1.0, overconfidence=1.0, urgency=1.0, identity_attachment=1.0,
    )
    assert rep["operator_heat"] == 1.0
    assert rep["diablo_no_new_risk"] is True
    assert rep["heat_bucket"] == "HOT"


def test_dominant_emotion_reported():
    rep = gate.compute_operator_heat(fomo=0.2, revenge=0.9)
    assert rep["dominant_emotion"] == "Revenge"


def test_recommended_actions_are_non_trading():
    rep = gate.compute_operator_heat(fomo=1.0, revenge=1.0, urgency=1.0)
    action = rep["recommended_operator_action"].lower()
    for forbidden in ("buy", "sell", "execute", "place order", "submit"):
        assert forbidden not in action


def test_no_medical_language_in_recommended_action():
    """The recommended action must be pure decision-discipline, with no
    therapeutic/medical framing.  (The disclaimer is allowed to *disclaim*
    medical framing, e.g. "not a diagnosis" — that is a guardrail, not a
    claim, so it is excluded from this check.)"""
    rep = gate.compute_operator_heat(fomo=0.9, revenge=0.9)
    action = rep["recommended_operator_action"].lower()
    for med in ("diagnos", "therapy", "therapeutic", "disorder", "medical", "anxiety"):
        assert med not in action


def test_advisory_stamps_present():
    rep = gate.compute_operator_heat(fomo=0.5)
    assert rep["advisory_status"] == "ADVISORY_ONLY"
    assert rep["broker_api_called"] is False
    assert rep["ai_execution_count"] == 0
