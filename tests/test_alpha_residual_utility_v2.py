"""Residual utility v2: JTBD / failure-cost / substitution model."""

from __future__ import annotations

from src.alpha.residual_utility import (
    NECESSITY_TYPES,
    RESIDUAL_UTILITY_CLASSES,
    score_residual_utility_v2,
)


def _plumbing() -> dict:
    return score_residual_utility_v2(
        job_to_be_done="move clean water in and waste water out of every home",
        necessity_type="survival",
        failure_cost_score=90.0,
        substitution_risk_score=20.0,
        frequency_score=85.0,
        switching_cost_score=70.0,
        willingness_to_pay_score=75.0,
        boring_but_essential_score=95.0,
        narrative_dependency_score=15.0,
    )


def test_residential_plumbing_is_apex_necessity() -> None:
    result = _plumbing()
    assert result["residual_utility_class"] == "apex_necessity"
    assert result["residual_utility_score"] > 40.0


def test_ryanair_style_transport_is_durable_utility() -> None:
    result = score_residual_utility_v2(
        job_to_be_done="move me from A to B cheaply and safely",
        necessity_type="productivity",
        failure_cost_score=60.0,
        substitution_risk_score=50.0,
        frequency_score=60.0,
        switching_cost_score=20.0,
        willingness_to_pay_score=50.0,
        boring_but_essential_score=80.0,
        narrative_dependency_score=20.0,
    )
    assert result["residual_utility_class"] == "durable_utility"


def test_logo_sneaker_collab_is_status_or_weak() -> None:
    ugly = score_residual_utility_v2(
        job_to_be_done="signal brand affiliation on feet",
        necessity_type="status",
        failure_cost_score=5.0,
        substitution_risk_score=90.0,
        frequency_score=30.0,
        switching_cost_score=5.0,
        willingness_to_pay_score=60.0,
        boring_but_essential_score=5.0,
        narrative_dependency_score=90.0,
    )
    assert ugly["residual_utility_class"] == "weak_utility"
    well_formed = score_residual_utility_v2(
        job_to_be_done="signal brand affiliation with a genuinely good shoe",
        necessity_type="status",
        failure_cost_score=30.0,
        substitution_risk_score=50.0,
        frequency_score=60.0,
        switching_cost_score=30.0,
        willingness_to_pay_score=80.0,
        boring_but_essential_score=40.0,
        narrative_dependency_score=60.0,
    )
    assert well_formed["residual_utility_class"] == "status_utility"


def test_memecoin_is_speculative_utility() -> None:
    result = score_residual_utility_v2(
        job_to_be_done="number go up",
        necessity_type="speculation",
        failure_cost_score=5.0,
        substitution_risk_score=95.0,
        frequency_score=20.0,
        switching_cost_score=5.0,
        willingness_to_pay_score=40.0,
        boring_but_essential_score=0.0,
        narrative_dependency_score=95.0,
    )
    assert result["residual_utility_class"] == "speculative_utility"


def test_sticky_saas_is_durable_utility() -> None:
    result = score_residual_utility_v2(
        job_to_be_done="run payroll without errors",
        necessity_type="productivity",
        failure_cost_score=70.0,
        substitution_risk_score=35.0,
        frequency_score=90.0,
        switching_cost_score=85.0,
        willingness_to_pay_score=60.0,
        boring_but_essential_score=70.0,
        narrative_dependency_score=25.0,
    )
    assert result["residual_utility_class"] == "durable_utility"


def test_one_dead_factor_collapses_the_job() -> None:
    result = score_residual_utility_v2(
        job_to_be_done="x",
        necessity_type="survival",
        willingness_to_pay_score=0.0,
    )
    assert result["residual_utility_score"] == 0.0
    assert result["residual_utility_class"] == "weak_utility"


def test_substitution_and_narrative_reduce_score() -> None:
    clean = _plumbing()
    substitutable = score_residual_utility_v2(
        job_to_be_done="x",
        necessity_type="survival",
        failure_cost_score=90.0,
        substitution_risk_score=95.0,
        frequency_score=85.0,
        switching_cost_score=70.0,
        willingness_to_pay_score=75.0,
        boring_but_essential_score=95.0,
        narrative_dependency_score=95.0,
    )
    assert substitutable["residual_utility_score"] < clean["residual_utility_score"]


def test_unknown_necessity_type_degrades_safely() -> None:
    result = score_residual_utility_v2(
        job_to_be_done="x", necessity_type="vibes"
    )
    assert result["necessity_type"] == "convenience"
    assert any("vibes" in note for note in result["missing_inputs"])


def test_outputs_bounded_and_classes_known() -> None:
    for necessity_type in NECESSITY_TYPES:
        result = score_residual_utility_v2(
            job_to_be_done="x", necessity_type=necessity_type
        )
        assert 0.0 <= result["residual_utility_score"] <= 100.0
        assert result["residual_utility_class"] in RESIDUAL_UTILITY_CLASSES
