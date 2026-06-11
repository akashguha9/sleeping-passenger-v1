"""Consent Quality Score and shared evidence-extraction tests."""

from __future__ import annotations

from src.consent.customer_consent import score_consent_quality
from src.consent.evidence import (
    extract_evidence,
    evidence_confidence,
    evidence_intensity,
)

CLEAN_INPUTS = dict(
    clarity_of_terms=0.9,
    billing_predictability=0.9,
    cancellation_clarity=0.9,
    refund_accessibility=0.8,
    dispute_fairness=0.8,
    human_escalation=0.9,
)


def test_extraction_is_deterministic_counting() -> None:
    hits = extract_evidence(
        [
            "charged after cancel and a hidden fee appeared",
            "german only letter, had to translate",
        ]
    )
    assert hits["charged_after_cancellation"].count == 1
    assert hits["hidden_fees"].count == 1
    assert hits["language_burden"].count == 2  # two phrases in one text
    assert "german only" in hits["language_burden"].matched_terms
    assert hits["claims_non_payment"].count == 0


def test_evidence_intensity_and_confidence_bounds() -> None:
    hits = extract_evidence(["cannot cancel"] * 4)
    assert evidence_intensity(hits["cannot_cancel"], 4) == 1.0
    assert evidence_intensity(hits["cannot_cancel"], 0) == 0.0
    assert evidence_confidence(0) == 0.0
    assert evidence_confidence(100) == 1.0


def test_clean_structured_inputs_score_high() -> None:
    result = score_consent_quality(**CLEAN_INPUTS)
    assert result.score >= 8.0
    assert result.label == "strong"
    assert result.higher_is_worse is False


def test_unknown_company_scores_low_with_warning_not_harm_claim() -> None:
    result = score_consent_quality()
    assert result.score == 0.0
    assert any("absence of proof" in w for w in result.missing_data_warnings)
    assert result.confidence == 0.0


def test_complaint_evidence_worsens_but_praise_cannot_improve() -> None:
    complained = score_consent_quality(
        **CLEAN_INPUTS,
        complaint_texts=[
            "charged after cancel",
            "cannot cancel the membership",
            "german only correspondence",
        ],
    )
    clean = score_consent_quality(**CLEAN_INPUTS)
    assert complained.score < clean.score
    assert complained.evidence_terms

    praised = score_consent_quality(
        complaint_texts=["easy to cancel", "refunded quickly"] * 3
    )
    # Praise alone cannot manufacture consent quality.
    assert praised.score == 0.0


def test_lock_in_and_billing_after_cancellation_drive_score_down() -> None:
    result = score_consent_quality(
        **CLEAN_INPUTS,
        billing_after_cancellation_risk=0.9,
        lock_in_risk=0.8,
        cancellation_friction=0.7,
    )
    assert result.score < 5.0


def test_score_contract_fields_present_and_serializable() -> None:
    import json

    payload = score_consent_quality(**CLEAN_INPUTS).to_dict()
    for key in (
        "score", "label", "confidence", "evidence_terms", "rationale",
        "missing_data_warnings", "raw_components", "advisory_status",
    ):
        assert key in payload
    assert payload["advisory_status"] == "ADVISORY_ONLY"
    json.dumps(payload)
