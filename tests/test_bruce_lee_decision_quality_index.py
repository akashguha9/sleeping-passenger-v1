"""Bruce Lee Decision Quality Index — synthesis score and consequences.

Proves high survival/reality raises BLDQI, high operator heat or diablo risk
caps it into DIABLO, and the component sub-formulas behave as documented
(signal efficiency rewards low assumptions; survival utility weights survival
over raw return).
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts import bruce_lee_decision_quality_index as bldqi


def test_high_survival_and_reality_raise_score():
    weak = bldqi.compute_bldqi(
        interception=3, directness=3, adaptability=3, economy=3,
        reality_confirmation=2, signal_efficiency=3, broken_rhythm=3,
        anti_dogma=3, survival_utility=2, operator_heat=1, diablo_risk=1,
    )
    strong = bldqi.compute_bldqi(
        interception=8, directness=8, adaptability=8, economy=8,
        reality_confirmation=9, signal_efficiency=8, broken_rhythm=8,
        anti_dogma=8, survival_utility=9, operator_heat=1, diablo_risk=1,
    )
    assert strong["bldqi_score"] > weak["bldqi_score"]


def test_high_heat_caps_into_diablo():
    rep = bldqi.compute_bldqi(
        interception=9, directness=9, adaptability=9, economy=9,
        reality_confirmation=9, signal_efficiency=9, broken_rhythm=9,
        anti_dogma=9, survival_utility=9, operator_heat=9, diablo_risk=1,
    )
    assert rep["state_recommendation"] == "DIABLO_NO_NEW_RISK"
    assert rep["action_constraint"] == "RECONCILE_OR_WAIT"
    assert rep["moltbook_feedback_required"] is True


def test_high_diablo_risk_caps_into_diablo():
    rep = bldqi.compute_bldqi(
        interception=9, directness=9, adaptability=9, economy=9,
        reality_confirmation=9, signal_efficiency=9, broken_rhythm=9,
        anti_dogma=9, survival_utility=9, operator_heat=1, diablo_risk=9,
    )
    assert rep["state_recommendation"] == "DIABLO_NO_NEW_RISK"


def test_signal_efficiency_rewards_low_assumptions():
    clean = bldqi.compute_signal_efficiency(
        expected_value=2.0, confidence=0.8, survival_quality=0.8,
        assumptions=0.5, data_fragility=0.2, operational_complexity=0.2)
    stacked = bldqi.compute_signal_efficiency(
        expected_value=2.0, confidence=0.8, survival_quality=0.8,
        assumptions=5.0, data_fragility=3.0, operational_complexity=3.0)
    assert clean > stacked


def test_survival_utility_weights_survival_over_return():
    return_heavy = bldqi.compute_survival_utility(
        return_potential=1.0, survival_quality=0.0, feedback_value=0.0,
        invalidation_clarity=0.0, liquidity=0.0, chaos_risk=0.0)
    survival_heavy = bldqi.compute_survival_utility(
        return_potential=0.0, survival_quality=1.0, feedback_value=0.0,
        invalidation_clarity=0.0, liquidity=0.0, chaos_risk=0.0)
    assert survival_heavy > return_heavy


def test_anti_dogma_penalises_single_source_dependence():
    flexible = bldqi.compute_anti_dogma(
        adaptability=8, invalidation_clarity=0.8, single_source_dependence=0.1)
    rigid = bldqi.compute_anti_dogma(
        adaptability=8, invalidation_clarity=0.8, single_source_dependence=0.9)
    assert flexible > rigid


def test_advisory_stamps_present():
    rep = bldqi.compute_bldqi(
        interception=5, directness=5, adaptability=5, economy=5,
        reality_confirmation=5, signal_efficiency=5, broken_rhythm=5,
        anti_dogma=5, survival_utility=5, operator_heat=1, diablo_risk=1,
    )
    assert rep["advisory_status"] == "ADVISORY_ONLY"
    assert rep["broker_api_called"] is False
    assert rep["ai_execution_count"] == 0
