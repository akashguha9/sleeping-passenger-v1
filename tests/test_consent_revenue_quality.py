"""Adjusted revenue quality, case-study fixtures, API contract, and the
crash-simulator bridge — the composite proofs for the consent engine."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.consent_api import consent_doctrine, evaluate_consent_candidate
from src.consent.revenue_quality import (
    REVENUE_QUALITY_LABELS,
    evaluate_consent_profile,
    to_simulator_risk_factors,
)

FIXTURES = json.loads(
    (
        Path(__file__).resolve().parent / "fixtures" / "consent_case_studies.json"
    ).read_text(encoding="utf-8")
)

REQUIRED_STAMPS = {
    "advisory_status": "ADVISORY_ONLY",
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "ai_execution_count": 0,
}


def _profile(case: str) -> dict:
    return evaluate_consent_profile(dict(FIXTURES[case]))


def test_clean_company_outscores_extractive_cases() -> None:
    clean = _profile("clean_saas")
    gym = _profile("premium_gym")
    ticket = _profile("deutschland_ticket")
    insurer = _profile("insurer_claims")

    clean_score = clean["adjusted_revenue_quality"]["score"]
    for extractive in (gym, ticket, insurer):
        assert clean_score > extractive["adjusted_revenue_quality"]["score"]

    assert clean["revenue_quality_label"] in ("clean", "mostly_clean")
    assert gym["revenue_quality_label"] in ("fragile", "extractive_risk")
    assert insurer["revenue_quality_label"] in ("fragile", "extractive_risk")


def test_gym_case_premium_promise_failure_is_high() -> None:
    gym = _profile("premium_gym")
    assert gym["premium_promise_failure"]["score"] >= 6.0
    assert gym["pause_friction"]["score"] >= 6.0
    assert gym["delay_revenue"]["score"] > 0.0
    # The €7.50 monetized week is in the rationale.
    assert any(
        "7.50" in r for r in gym["pause_friction"]["rationale"]
    )
    # International-student segment with German-only burden.
    assert gym["friction_tax"]["raw_components"]["translation_burden"] > 0.0


def test_deutschland_ticket_backend_mismatch_case() -> None:
    ticket = _profile("deutschland_ticket")
    assert ticket["subscription_extraction"]["score"] >= 5.0
    assert ticket["enforcement_asymmetry"]["score"] >= 6.0
    assert ticket["narrative_experience_gap"]["score"] >= 4.0
    assert "app says cancelled" in ticket["evidence_terms"]
    assert ticket["regulatory_fragility"]["score"] >= 4.0


def test_mawista_style_claims_case() -> None:
    insurer = _profile("insurer_claims")
    assert insurer["claims_non_payment"]["score"] == 10.0
    gap = insurer["narrative_experience_gap"]
    assert gap["score"] >= 5.0  # promised "reimbursed", evidence says never


def test_asymmetric_app_case_digital_relief_gap() -> None:
    app = _profile("asymmetric_app")
    asymmetry = app["digital_asymmetry"]
    assert asymmetry["digital_collection_score"] == 10.0
    assert asymmetry["digital_relief_gap"] >= 7.0
    assert asymmetry["digital_asymmetry_risk"] >= 7.0


def test_adjusted_revenue_quality_decreases_with_bad_layers() -> None:
    good = evaluate_consent_profile(
        {
            "reported_revenue_quality": 8.0,
            "service_fulfilment": 0.9,
            "consent": FIXTURES["clean_saas"]["consent"],
            "complaint_texts": FIXTURES["clean_saas"]["complaint_texts"],
        }
    )
    degraded = evaluate_consent_profile(
        {
            "reported_revenue_quality": 8.0,  # same reported revenue!
            "service_fulfilment": 0.2,
            "complaint_texts": FIXTURES["premium_gym"]["complaint_texts"],
            "subscription": {"recurring_billing_dependency": 0.9},
        }
    )
    assert (
        degraded["adjusted_revenue_quality"]["score"]
        < good["adjusted_revenue_quality"]["score"]
    )
    # Same reported revenue, different consent reality, different verdict.
    assert degraded["adjusted_revenue_quality"]["base_revenue_quality"] == 8.0
    assert good["adjusted_revenue_quality"]["base_revenue_quality"] == 8.0


def test_empty_payload_refuses_to_classify() -> None:
    profile = evaluate_consent_profile({})
    assert profile["revenue_quality_label"] == "insufficient_data"
    assert profile["revenue_quality_label"] in REVENUE_QUALITY_LABELS


def test_every_layer_ships_full_score_contract() -> None:
    gym = _profile("premium_gym")
    layers = (
        "consent_quality", "pause_friction", "delay_revenue",
        "subscription_extraction", "claims_non_payment",
        "premium_promise_failure", "segment_fit", "enforcement_asymmetry",
        "friction_tax", "narrative_experience_gap", "regulatory_fragility",
    )
    for layer in layers:
        body = gym[layer]
        for key in ("score", "label", "confidence", "evidence_terms",
                    "rationale", "missing_data_warnings"):
            assert key in body, f"{layer} missing {key}"
    json.dumps(gym)  # whole profile serializable


def test_simulator_bridge_produces_known_crash_factors() -> None:
    from src.simulator.crash_simulator import (
        RISK_FACTOR_CATEGORIES,
        simulate_crash_cases,
    )

    gym = _profile("premium_gym")
    factors = to_simulator_risk_factors(gym)
    assert factors  # extraction evidence must surface as crash vectors
    for name in factors:
        assert name in RISK_FACTOR_CATEGORIES, f"unregistered factor {name}"
    # And they flow into the crash simulator with valuation interaction.
    report = simulate_crash_cases({**factors, "high_valuation": 0.8})
    assert report.crash_risk_score > 0.0


def test_consent_api_is_stamped_and_bounded() -> None:
    result = evaluate_consent_candidate(dict(FIXTURES["premium_gym"]))
    for key, expected in REQUIRED_STAMPS.items():
        assert result.get(key) == expected
    assert "simulator_risk_factors" in result
    assert "generated_at" in result

    hostile = evaluate_consent_candidate(
        {"complaint_texts": ["cannot cancel"] * 10_000}
    )
    assert hostile["evidence_text_count"] <= 200

    for garbage in (None, [], "x", 7):
        out = evaluate_consent_candidate(garbage)  # type: ignore[arg-type]
        assert out["revenue_quality_label"] == "insufficient_data"

    doctrine = consent_doctrine()
    assert "personal anecdotes are not statistical proof" in doctrine["limitations"]
    for key, expected in REQUIRED_STAMPS.items():
        assert doctrine.get(key) == expected


# ---------------------------------------------------------------------------
# HTTP routes
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


def test_http_consent_evaluate_and_doctrine(client) -> None:
    response = client.post(
        "/consent/evaluate", json=dict(FIXTURES["asymmetric_app"])
    )
    assert response.status_code == 200
    body = response.json()
    for key, expected in REQUIRED_STAMPS.items():
        assert body.get(key) == expected
    assert body["digital_asymmetry"]["digital_asymmetry_risk"] >= 7.0

    doctrine = client.get("/consent/doctrine")
    assert doctrine.status_code == 200
    assert "doctrine" in doctrine.json()


def test_http_consent_routes_never_execution_shaped(client) -> None:
    for forbidden in ("/consent/execute", "/consent/order", "/consent/buy"):
        response = client.post(forbidden, json={})
        assert response.status_code in (404, 405)
