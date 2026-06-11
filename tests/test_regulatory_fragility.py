"""Regulatory fragility, enforcement asymmetry, narrative gap,
subscription extraction, claims non-payment, premium promise, segment fit."""

from __future__ import annotations

import pytest

from src.consent.claims_non_payment import score_claims_non_payment
from src.consent.enforcement_asymmetry import score_enforcement_asymmetry
from src.consent.narrative_gap import score_narrative_gap
from src.consent.premium_promise import score_premium_promise_failure
from src.consent.regulatory_fragility import score_regulatory_fragility
from src.consent.segment_fit import score_segment_fit
from src.consent.subscription_extraction import score_subscription_extraction


def test_insurer_with_zero_paid_claims_is_severe() -> None:
    result = score_claims_non_payment(
        claims_submitted=6, claims_paid=0, formal_decisions_issued=0
    )
    assert result.score == 10.0
    assert result.label == "severe"
    assert any("hard-data mode" in r for r in result.rationale)


def test_formal_rejections_count_as_decisions() -> None:
    silent = score_claims_non_payment(
        claims_submitted=10, claims_paid=2, formal_decisions_issued=0
    )
    explained = score_claims_non_payment(
        claims_submitted=10, claims_paid=2, formal_decisions_issued=8
    )
    assert explained.score < silent.score  # rejection-with-reason enables appeal


def test_claims_evidence_mode_without_hard_data() -> None:
    result = score_claims_non_payment(
        complaint_texts=[
            "never reimbursed a single claim",
            "claim ignored, no formal rejection",
            "automated bot says please email",
        ]
    )
    assert result.score > 5.0
    assert any("evidence mode" in w for w in result.missing_data_warnings)


def test_premium_price_with_stolen_property_and_no_support() -> None:
    result = score_premium_promise_failure(
        price_premium=0.8,
        complaint_texts=[
            "sneakers stolen from the locker, front desk did not help",
            "no support at all, poor service for the price",
            "restricted access, not all equipment available, trainer required",
        ],
    )
    assert result.score >= 6.0
    assert "stolen" in result.evidence_terms


def test_ryanair_rule_budget_positioning_keeps_coherence() -> None:
    budget = score_premium_promise_failure(
        price_premium=0.1,
        service_failure_rate=0.7,
    )
    premium = score_premium_promise_failure(
        price_premium=0.9,
        service_failure_rate=0.7,
    )
    assert budget.score < 1.0
    assert premium.score > budget.score
    assert any("Ryanair" in r for r in budget.rationale)


def test_subscription_extraction_needs_all_legs() -> None:
    trapped = score_subscription_extraction(
        recurring_billing_dependency=0.9,
        exit_friction=0.9,
        billing_ambiguity=0.8,
        penalty_escalation=0.8,
    )
    no_recurring = score_subscription_extraction(
        recurring_billing_dependency=0.0,
        exit_friction=0.0,
        billing_ambiguity=0.0,
        penalty_escalation=0.0,
    )
    assert trapped.score >= 7.0
    assert no_recurring.score == 0.0


def test_extraction_evidence_overrides_self_report() -> None:
    result = score_subscription_extraction(
        complaint_texts=[
            "charged after cancel was confirmed",
            "cannot cancel, written notice required",
            "sent to collections over a small fee",
        ]
    )
    assert result.score > 4.0
    assert "charged after cancel" in result.evidence_terms


def test_enforcement_asymmetry_fast_collect_slow_resolve() -> None:
    asymmetric = score_enforcement_asymmetry(
        collection_speed=0.9,
        penalty_strength=0.8,
        debit_precision=0.9,
        resolution_speed=0.2,
        refund_speed=0.1,
        human_accountability=0.2,
    )
    fair = score_enforcement_asymmetry(
        collection_speed=0.9,
        penalty_strength=0.5,
        debit_precision=0.9,
        resolution_speed=0.9,
        refund_speed=0.8,
        human_accountability=0.9,
    )
    assert asymmetric.score >= 6.0
    assert fair.score < 2.0
    assert any("tracks money better than outcomes" in r
               for r in asymmetric.rationale)


def test_narrative_gap_contradicted_promises() -> None:
    result = score_narrative_gap(
        official_promises=["flexible", "easy_cancellation", "digital_first"],
        complaint_texts=[
            "cannot cancel without written notice",
            "charged after cancellation",
            "cancelling only by email although the app takes payment",
        ],
    )
    assert result.score >= 5.0
    assert any("contradicted" in r for r in result.rationale)


def test_no_promises_means_no_gap() -> None:
    result = score_narrative_gap(
        official_promises=[],
        complaint_texts=["cannot cancel", "hidden fee"],
    )
    assert result.score == 0.0
    assert any("no official promise vector" in w
               for w in result.missing_data_warnings)


def test_vulnerable_segment_amplifies_misfit() -> None:
    inputs = dict(
        pricing_fit=0.4, flexibility_fit=0.3, language_fit=0.2,
        digital_self_service_fit=0.3, cancellation_pause_fit=0.3,
        payment_predictability=0.4, contract_rigidity=0.7,
        processing_delay=0.6, support_friction=0.6,
    )
    student = score_segment_fit(segment="international_students", **inputs)
    general = score_segment_fit(segment="general", **inputs)
    assert student.score <= general.score
    assert student.raw_components["vulnerable_segment"] == 1.0


def test_regulatory_fragility_multiplies_vulnerability() -> None:
    exposed = score_regulatory_fragility(
        complaint_severity=0.8,
        vulnerable_user_exposure=0.8,
        legal_ambiguity=0.7,
    )
    same_severity_no_vulnerable = score_regulatory_fragility(
        complaint_severity=0.8,
        vulnerable_user_exposure=0.0,
        legal_ambiguity=0.7,
    )
    assert exposed.score > same_severity_no_vulnerable.score
    assert exposed.score >= 6.0
    assert any("not legal guilt" in r for r in exposed.rationale)


def test_fragility_evidence_mode_from_complaints() -> None:
    result = score_regulatory_fragility(
        complaint_texts=[
            "charged after cancel",
            "claim denied with no explanation",
            "german only legal letter",
            "sent to collections",
        ]
    )
    assert result.score > 2.0
    assert result.raw_components["vulnerable_user_exposure"] > 0.0
