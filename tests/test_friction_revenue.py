"""Delay revenue, friction tax, pause friction, and digital asymmetry tests."""

from __future__ import annotations

import pytest

from src.consent.digital_asymmetry import (
    score_digital_asymmetry,
    score_pause_friction,
)
from src.consent.friction_revenue import score_delay_revenue, score_friction_tax

FULL_COLLECTION = {
    "digital_signup": True,
    "digital_payment": True,
    "stored_payment_method": True,
    "auto_renewal": True,
    "instant_billing": True,
}
FULL_RELIEF = {
    "cancel_in_app": True,
    "pause_in_app": True,
    "refund_in_app": True,
    "dispute_in_app": True,
    "update_billing_in_app": True,
    "view_billing_period": True,
    "reach_human_support": True,
}


def test_app_payment_email_cancellation_is_high_asymmetry() -> None:
    report = score_digital_asymmetry(
        collection_capabilities=FULL_COLLECTION,
        relief_capabilities={"view_billing_period": True},
        complaint_texts=["cancelling is only by email", "had to email twice"],
    )
    assert report.digital_collection_score == 10.0
    assert report.digital_relief_score < 2.0
    assert report.digital_relief_gap > 8.0
    assert report.digital_asymmetry_risk >= 8.0
    assert "cancel_in_app" in report.relief_actions_missing


def test_symmetric_company_has_no_asymmetry_risk() -> None:
    report = score_digital_asymmetry(
        collection_capabilities=FULL_COLLECTION,
        relief_capabilities=FULL_RELIEF,
    )
    assert report.digital_relief_gap <= 0.0 + 10.0 * (1 - 1)  # gap <= 0
    assert report.digital_asymmetry_risk == 0.0


def test_complaints_override_claimed_relief_capabilities() -> None:
    claimed = score_digital_asymmetry(
        collection_capabilities=FULL_COLLECTION,
        relief_capabilities=FULL_RELIEF,
        complaint_texts=["cannot cancel", "email only support"] * 3,
    )
    assert claimed.digital_relief_score < 10.0
    assert any("experiences relief" in r for r in claimed.rationale)


def test_one_week_pause_delay_with_billing_is_nonzero_risk() -> None:
    result = score_pause_friction(
        manual_pause_burden=0.8,
        language_burden=0.8,
        processing_delay_days=7,
        billing_continues_during_delay=True,
        charge_per_week=7.50,
    )
    assert result.score > 5.0
    assert result.raw_components["estimated_delay_cost_eur"] == pytest.approx(7.50)
    assert any("€7.50" in r for r in result.rationale)


def test_pause_without_billing_continuation_scores_lower() -> None:
    with_billing = score_pause_friction(
        processing_delay_days=7, billing_continues_during_delay=True
    )
    without_billing = score_pause_friction(
        processing_delay_days=7, billing_continues_during_delay=False
    )
    assert without_billing.score < with_billing.score


def test_delay_revenue_quantitative_mode() -> None:
    result = score_delay_revenue(
        processing_delay_days=7,
        charge_rate_per_week=7.50,
        complaint_frequency=0.5,
        complaint_texts=["still charged while waiting for response"],
    )
    assert result.score > 0.0
    assert result.raw_components["estimated_delay_cost_per_user_eur"] == (
        pytest.approx(7.50)
    )
    assert result.label in ("moderate", "elevated", "high", "severe")


def test_delay_revenue_qualitative_fallback() -> None:
    result = score_delay_revenue(
        complaint_texts=[
            "refund pending for weeks",
            "took a week to reply, still charged",
            "processing delay every time",
        ]
    )
    assert result.score > 0.0
    assert any("qualitative" in w or "evidence mode" in w
               for w in result.missing_data_warnings)


def test_no_delay_evidence_scores_zero() -> None:
    assert score_delay_revenue().score == 0.0


def test_friction_tax_accumulates_burdens() -> None:
    light = score_friction_tax(time_burden=0.2)
    heavy = score_friction_tax(
        time_burden=0.8,
        translation_burden=0.9,
        proof_burden=0.7,
        call_queue_burden=0.8,
        email_burden=0.8,
        delay_burden=0.9,
        payment_burden=0.6,
        stress_burden=0.8,
    )
    assert heavy.score > light.score
    assert heavy.score >= 7.0


def test_german_only_letters_raise_friction_for_international_users() -> None:
    result = score_friction_tax(
        complaint_texts=[
            "german only letter, had to translate three pages",
            "no english support on the phone",
            "automated bot, please email",
        ]
    )
    assert result.raw_components["translation_burden"] > 0.5
    assert result.score > 0.0
    assert any("translation_burden" in r for r in result.rationale)
