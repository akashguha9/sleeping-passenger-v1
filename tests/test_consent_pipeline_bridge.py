"""Consent-to-candidate bridge (A), decision ledger (G), jurisdiction map
(E), and dark-pattern chain (I) — the end-to-end integration proofs.

Doctrine under test: a financially attractive candidate with severe,
reliable consent/regulatory evidence must not receive a clean Buy; clean
evidence must not be punished; missing evidence stays neutral with an
insufficient_data warning; and every adjustment is recorded — no hidden
magic, no unexplained downgrade.
"""

from __future__ import annotations

import copy
import json

import pytest

from src.consent.dark_pattern_chain import detect_dark_pattern_chain
from src.consent.jurisdiction import build_jurisdiction_risk_map
from src.simulator.pipeline import evaluate_candidate_payload
from tests.test_simulator_cherry_pick_pipeline import STRONG_PAYLOAD

SEVERE_EVIDENCE = [
    {"text": "Trotz Kündigung weiter abgebucht, dann Mahngebühr und Inkasso über 90 Euro",
     "source": "portal_a", "source_type": "verified_review", "date": "2026-04-01"},
    {"text": "cannot cancel, written notice required, charged after cancel for 3 months",
     "source": "portal_b", "source_type": "verified_review", "date": "2026-03-15"},
    {"text": "pause requires a german only email, reply took a week, still charged 7.50",
     "source": "forum_x", "source_type": "forum_post", "date": "2026-02-20"},
    {"text": "sent to collections over 15 euro, late fee and default interest added",
     "source": "portal_c", "source_type": "verified_review", "date": "2026-05-02"},
    {"text": "auto renewal without notice, hidden fee of 9.90 on the final invoice",
     "source": "appstore", "source_type": "app_store_review", "date": "2026-01-10"},
]

CLEAN_EVIDENCE = [
    {"text": "cancelled in app with confirmation, easy to cancel, took 2 minutes",
     "source": "store_a", "source_type": "verified_review", "date": "2026-05-01"},
    {"text": "refund received within 24 hours, all fees explained upfront",
     "source": "store_b", "source_type": "verified_review", "date": "2026-04-12"},
    {"text": "human answered immediately, claim paid in full",
     "source": "portal_c", "source_type": "verified_review", "date": "2026-03-20"},
]

CLAIMS_EVIDENCE = [
    {"text": "never reimbursed a single claim, no formal rejection in 6 months",
     "source": "portal_a", "source_type": "verified_review", "date": "2026-04-01"},
    {"text": "Erstattungsantrag abgelehnt, Unterlagen fehlen angeblich, keine Rückerstattung",
     "source": "forum_de", "source_type": "verified_review", "date": "2026-03-01"},
    {"text": "claim ignored, automated bot says please email, no response after that",
     "source": "appstore", "source_type": "app_store_review", "date": "2026-02-01"},
    {"text": "regulator opened inquiry into claims handling of this provider",
     "source": "register", "source_type": "regulator_action", "date": "2026-05-01"},
]


def _run(extra: dict) -> dict:
    payload = copy.deepcopy(STRONG_PAYLOAD)
    payload.update(copy.deepcopy(extra))
    return evaluate_candidate_payload(payload)


BASE = evaluate_candidate_payload(copy.deepcopy(STRONG_PAYLOAD))
BASE_SCORE = BASE["decision"]["final_candidate_score"]
BASE_STATE = BASE["decision"]["final_state"]


def test_missing_evidence_is_neutral_with_warning() -> None:
    decision = BASE["decision"]
    ledger = BASE["consent_ledger"]
    assert decision["gate_results"]["consent_gate"] is True
    assert ledger["score_after_consent"] == ledger["score_before_consent"]
    assert any("insufficient_data" in w for w in ledger["warnings"])
    assert "CONSENT_EVIDENCE_ABSENT" in decision["reason_codes"]


def test_clean_evidence_does_not_punish_a_strong_candidate() -> None:
    out = _run({"customer_reviews": CLEAN_EVIDENCE})
    assert out["decision"]["final_state"] == BASE_STATE
    assert out["decision"]["final_candidate_score"] == pytest.approx(
        BASE_SCORE, abs=0.5
    )
    multipliers = out["consent_ledger"]["multipliers_applied"]
    assert multipliers["revenue_quality_multiplier"] >= 0.99
    assert multipliers["consent_safety_multiplier"] >= 0.99


def test_severe_extraction_evidence_downgrades_same_candidate() -> None:
    out = _run({
        "complaint_evidence": SEVERE_EVIDENCE,
        "jurisdiction": "de",
        "customer_segment": "international_students",
    })
    decision = out["decision"]
    ledger = out["consent_ledger"]
    assert decision["final_candidate_score"] < BASE_SCORE * 0.5
    assert decision["final_state"] in ("reject", "archive", "watchlist")
    assert "CONSENT_EVIDENCE_EVALUATED" in decision["reason_codes"]
    # The crash wall received the factors automatically.
    assert "extractive_revenue" in out["breakdown"]["crash"]["individual_risks"]
    assert ledger["evidence_reliability_score"] > 6.0


def test_claims_non_payment_evidence_downgrades_candidate() -> None:
    out = _run({"complaint_evidence": CLAIMS_EVIDENCE})
    assert out["decision"]["final_candidate_score"] < BASE_SCORE
    ledger = out["consent_ledger"]
    assert ledger["penalties_applied"]["claims_failure_penalty"] > 0
    assert ledger["layer_scores"]["claims_non_payment"] > 5.0
    # Regulator evidence drives reliability up.
    assert ledger["reliability_band"] in ("medium", "high")


def test_friction_revenue_evidence_downgrades_candidate() -> None:
    out = _run({
        "complaint_texts": [
            "pause requires email, processed once per week, still charged",
            "german only letter, had to translate, no english support",
            "automated bot, please email, no response for weeks",
            "refund pending for three weeks while billing continued",
        ]
    })
    assert out["decision"]["final_candidate_score"] < BASE_SCORE
    assert out["consent_ledger"]["penalties_applied"][
        "friction_revenue_penalty"
    ] > 0


def test_consent_effect_is_in_rationale_and_reason() -> None:
    out = _run({"complaint_evidence": SEVERE_EVIDENCE})
    ledger = out["consent_ledger"]
    assert any("consent adjustment" in r for r in ledger["rationale"])
    joined = " ".join(ledger["rationale"])
    assert "->" in joined  # before -> after recorded


def test_low_reliability_severe_evidence_is_warning_with_mild_cap() -> None:
    # One vague anonymous rant: severe-sounding but unreliable.
    out = _run({
        "complaint_texts": [
            "terrible scam, charged after cancel, worst company ever, never again"
        ]
    })
    ledger = out["consent_ledger"]
    assert ledger["reliability_band"] == "low"
    # Mild effect: score moves less than the reliable-severe case.
    reliable = _run({"complaint_evidence": SEVERE_EVIDENCE})
    assert (
        out["decision"]["final_candidate_score"]
        > reliable["decision"]["final_candidate_score"]
    )


def test_precomputed_consent_profile_is_reused() -> None:
    from src.consent.revenue_quality import evaluate_consent_profile

    profile = evaluate_consent_profile(
        {"complaint_texts": [r["text"] for r in SEVERE_EVIDENCE]}
    )
    out = _run({"consent_profile": profile})
    assert out["decision"]["final_candidate_score"] < BASE_SCORE
    assert out["consent_ledger"]["input_summary"]["precomputed_profile"] is True


# ---------------------------------------------------------------------------
# Upgrade G — ledger determinism and completeness
# ---------------------------------------------------------------------------


def test_ledger_is_deterministic_for_same_input() -> None:
    payload = {
        "complaint_evidence": SEVERE_EVIDENCE,
        "jurisdiction": "de",
        "customer_segment": "international_students",
    }
    first = _run(payload)["consent_ledger"]
    second = _run(payload)["consent_ledger"]
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_ledger_contains_required_fields() -> None:
    out = _run({"complaint_evidence": SEVERE_EVIDENCE, "jurisdiction": "de"})
    ledger = out["consent_ledger"]
    for key in (
        "input_summary", "evidence_sources", "deduplication_summary",
        "detected_terms", "layer_scores", "evidence_reliability_score",
        "multipliers_applied", "risk_caps_applied", "simulator_factors_added",
        "recommendation_before_consent", "recommendation_after_consent",
        "score_before_consent", "score_after_consent", "warnings",
        "rationale", "advisory_only_notice",
    ):
        assert key in ledger, f"ledger missing {key}"
    assert "ADVISORY_ONLY" in ledger["advisory_only_notice"]


def test_ledger_survives_missing_evidence_and_leaks_nothing() -> None:
    ledger = BASE["consent_ledger"]
    serialized = json.dumps(ledger).lower()
    assert "password" not in serialized
    assert "token" not in serialized
    assert ledger["recommendation_before_consent"] == (
        ledger["recommendation_after_consent"]
    )


# ---------------------------------------------------------------------------
# Upgrade E — jurisdiction map
# ---------------------------------------------------------------------------


def test_german_debit_and_mahnung_trigger_directdebit_and_subscription() -> None:
    risk_map = build_jurisdiction_risk_map(
        complaint_texts=[
            "Trotz Kündigung weiter abgebucht, Mahngebühr und Verzugszinsen",
            "sofort abgebucht aber kundigung nicht moglich",
        ],
        jurisdiction="de",
    )
    assert risk_map.jurisdiction_recognized
    assert "direct_debit_billing_risk" in risk_map.active_domains
    assert "consumer_subscription_risk" in risk_map.active_domains


def test_claims_evidence_triggers_insurance_domain() -> None:
    risk_map = build_jurisdiction_risk_map(
        complaint_texts=["claim denied, never reimbursed, no formal rejection"],
        jurisdiction="de",
    )
    assert "insurance_claims_risk" in risk_map.active_domains
    assert "not legal advice" in risk_map.disclaimer


def test_vulnerable_segment_with_german_only_evidence() -> None:
    risk_map = build_jurisdiction_risk_map(
        complaint_texts=["german only letter, had to translate, kein englisch"],
        jurisdiction="de",
        segment="international_students",
    )
    assert "language_accessibility_risk" in risk_map.active_domains
    assert "vulnerable_user_risk" in risk_map.active_domains


def test_jurisdiction_map_appears_in_pipeline_ledger() -> None:
    out = _run({
        "complaint_evidence": SEVERE_EVIDENCE, "jurisdiction": "de",
    })
    assert out["consent_ledger"]["jurisdiction_domains"]


# ---------------------------------------------------------------------------
# Upgrade I — dark-pattern chain (eureka)
# ---------------------------------------------------------------------------


def test_complete_chain_scores_superlinearly_vs_fragments() -> None:
    chain_texts = [
        "auto renewal started instantly, sofort abgebucht",        # stage 1
        "cannot cancel, pause requires a german only email",        # stage 2
        "reply took a week, processed once per week",               # stage 3
        "still charged while waiting, charged after cancel",        # stage 4
        "late fee and default interest added",                      # stage 5
        "sent to collections, inkasso letter arrived",              # stage 6
    ]
    full = detect_dark_pattern_chain(
        complaint_texts=chain_texts, reliability_factor=0.9,
    )
    fragments = detect_dark_pattern_chain(
        complaint_texts=[chain_texts[0], chain_texts[4]],
        reliability_factor=0.9,
    )
    assert full.longest_consecutive_run == 6
    assert full.chain_complete
    assert full.score >= 6.0
    assert fragments.longest_consecutive_run <= 2
    assert full.score > fragments.score * 2  # superlinear, not additive


def test_unreliable_chain_is_hypothesis_not_finding() -> None:
    texts = [
        "cannot cancel", "took a week", "still charged",
        "late fee added", "sent to collections",
    ]
    reliable = detect_dark_pattern_chain(
        complaint_texts=texts, reliability_factor=0.9
    )
    unreliable = detect_dark_pattern_chain(
        complaint_texts=texts, reliability_factor=0.2
    )
    assert unreliable.score < reliable.score
    assert any("hypothesis" in r for r in unreliable.rationale)


def test_vulnerable_segment_amplifies_chain() -> None:
    texts = ["cannot cancel", "still charged", "late fee", "inkasso"]
    general = detect_dark_pattern_chain(
        complaint_texts=texts, reliability_factor=0.8,
    )
    vulnerable = detect_dark_pattern_chain(
        complaint_texts=texts, reliability_factor=0.8, vulnerable_segment=True,
    )
    assert vulnerable.score >= general.score
    assert vulnerable.vulnerable_multiplier == 1.25


def test_chain_appears_in_ledger_and_crash_factors() -> None:
    out = _run({
        "complaint_evidence": SEVERE_EVIDENCE,
        "customer_segment": "international_students",
    })
    ledger = out["consent_ledger"]
    assert ledger["dark_pattern_chain"]["longest_consecutive_run"] >= 3
    assert "dark_pattern_chain" in ledger["simulator_factors_added"]
    assert "dark_pattern_chain" in out["breakdown"]["crash"]["individual_risks"]


def test_no_evidence_no_chain() -> None:
    report = detect_dark_pattern_chain(complaint_texts=[], reliability_factor=1.0)
    assert report.score == 0.0
    assert report.label == "none"


# ---------------------------------------------------------------------------
# API safety
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    try:
        from fastapi.testclient import TestClient
    except ModuleNotFoundError:  # pragma: no cover
        pytest.skip("fastapi not installed")
    from scripts import api_server

    if not getattr(api_server, "_FASTAPI_AVAILABLE", False):
        pytest.skip("fastapi not available")
    return TestClient(api_server.app)


def test_http_simulator_evaluate_exposes_consent_ledger(client) -> None:
    response = client.post(
        "/simulator/evaluate",
        json={
            "ticker": "GRIDCO",
            "opportunity_quality": 0.8,
            "complaint_texts": [r["text"] for r in SEVERE_EVIDENCE],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["advisory_status"] == "ADVISORY_ONLY"
    assert "consent_ledger" in body
    assert body["consent_ledger"]["advisory_only_notice"]


def test_cap_fires_directly_when_state_outranks_it() -> None:
    """Unit-level proof: if a severe+reliable candidate somehow reached
    high conviction, the cap itself demotes it to watchlist."""
    from src.consent.pipeline_bridge import (
        apply_consent_adjustment,
        prepare_consent_context,
    )
    from src.simulator.threshold_ladder import LADDER_STATES

    context = prepare_consent_context(
        {"ticker": "X", "complaint_evidence": SEVERE_EVIDENCE}
    )
    ledger = apply_consent_adjustment(
        context=context,
        score_before=90.0,
        state_before="high_conviction_candidate",
        ladder_states=LADDER_STATES,
    )
    assert ledger.recommendation_after_consent == "watchlist"
    assert ledger.risk_caps_applied
    assert ledger.score_after_consent < 90.0


def test_interrupt_states_pass_through_consent_untouched() -> None:
    from src.consent.pipeline_bridge import (
        apply_consent_adjustment,
        prepare_consent_context,
    )
    from src.simulator.threshold_ladder import LADDER_STATES

    context = prepare_consent_context(
        {"ticker": "X", "complaint_evidence": SEVERE_EVIDENCE}
    )
    ledger = apply_consent_adjustment(
        context=context,
        score_before=50.0,
        state_before="black_flag",
        ladder_states=LADDER_STATES,
    )
    # Driver-layer interrupts outrank consent: state unchanged.
    assert ledger.recommendation_after_consent == "black_flag"
    assert not ledger.risk_caps_applied
