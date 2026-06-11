"""Scrutineering bay tests: the simulator must be hard to fool.

A payload of self-consistent optimistic numbers must fail technical
inspection and hold a provisional (capped) verdict, while a genuinely
heterogeneous strong candidate passes.
"""

from __future__ import annotations

import copy

from src.simulator.pipeline import evaluate_candidate_payload
from src.simulator.scrutineering import (
    SUSPICION_FAIL_THRESHOLD,
    compute_humility_index,
    inspect_payload,
)
from tests.test_simulator_cherry_pick_pipeline import STRONG_PAYLOAD

# A fabricated dream candidate: everything maxed, nothing earned.
TOO_GOOD_PAYLOAD: dict = {
    "ticker": "SMOOTHCO",
    "theme": "ai_grid_buildout",
    "opportunity_quality": 0.9,
    "hard_evidence_score": 0.9,
    "confirmation_level": 0.95,
    # Large-cap so ladder thresholds are low and only scrutineering caps it.
    "circuit": {"market_cap_usd": 50_000_000_000},
    "narrative": {
        "mention_count": 2,
        "origin_count": 1,
        "independent_origin_count": 1,
        "source_quality": 0.9,
        "narrative_velocity": 0.9,
        "narrative_acceleration": 0.5,
    },
    "theme_assessment": {
        "policy_fit": 0.9, "macro_fit": 0.9, "sector_momentum": 0.9,
        "liquidity_support": 0.9, "valuation_heat": 0.1, "crowding": 0.1,
        "regulatory_friction": 0.1,
    },
    "exposure": {
        "revenue_exposure": 0.9, "margin_sensitivity": 0.9,
        "backlog_linkage": 0.9, "customer_linkage": 0.9,
        "geographic_fit": 0.9, "policy_fit": 0.9, "supply_chain_position": 0.9,
    },
    "aero": {
        "evidence": {
            "filing_evidence": 0.9, "cash_flow_quality": 0.9,
            "backlog_evidence": 0.9, "insider_alignment": 0.9,
            "primary_source_confirmation": 0.9,
        },
    },
    "risk_factors": {},
    # One fresh soft signal: grip passes, so scrutineering is the binding cap
    # (and hard_evidence 0.9 with a soft-only tyre stays a violation).
    "signals": [
        {"signal_type": "viral_article", "raw_strength": 90, "signal_age_hours": 1}
    ],
    "meal_box": {
        "thesis": "Everything is perfect on every axis simultaneously",
        "evidence": "",
        "catalyst": "Any day now, certainly soon",
        "invalidation": "It cannot fail so no invalidation is needed",
    },
    "driver": {"license_level": "team_principal"},
}


def test_honest_strong_payload_passes_inspection() -> None:
    report = inspect_payload(copy.deepcopy(STRONG_PAYLOAD))
    assert report.passed
    assert report.suspicion_score < SUSPICION_FAIL_THRESHOLD


def test_too_good_to_be_true_fails_inspection() -> None:
    report = inspect_payload(copy.deepcopy(TOO_GOOD_PAYLOAD))
    assert not report.passed
    assert report.suspicion_score >= SUSPICION_FAIL_THRESHOLD
    checks = {v.check for v in report.violations}
    assert "confirmation_without_origins" in checks
    assert "hard_evidence_without_hard_tyres" in checks
    assert "clean_crash_on_dirty_circuit" in checks
    assert "uniform_optimism" in checks
    assert "downforce_without_filings" in checks
    assert "DISQUALIFIED_PENDING_EVIDENCE" in report.reason_codes


def test_failed_scrutineering_caps_ladder_at_watchlist() -> None:
    out = evaluate_candidate_payload(copy.deepcopy(TOO_GOOD_PAYLOAD))
    decision = out["decision"]
    assert decision["gate_results"]["scrutineering_gate"] is False
    assert decision["final_state"] in ("reject", "archive", "watchlist")
    assert "scrutineering_gate" in decision["ladder"]["gate_caps"] or (
        decision["final_state"] in ("reject", "archive")
    )
    assert out["breakdown"]["scrutineering"]["passed"] is False


def test_passing_payload_keeps_scrutineering_gate_open() -> None:
    out = evaluate_candidate_payload(copy.deepcopy(STRONG_PAYLOAD))
    assert out["decision"]["gate_results"]["scrutineering_gate"] is True
    assert out["decision"]["suspicion_score"] < SUSPICION_FAIL_THRESHOLD


def test_humility_caps_unearned_confidence() -> None:
    thin = compute_humility_index(
        claimed_confidence=0.95,
        mention_count=1,
        independent_origin_count=1,
        tyre_count=0,
        meal_box_complete=False,
    )
    earned = compute_humility_index(
        claimed_confidence=0.7,
        mention_count=30,
        independent_origin_count=10,
        tyre_count=3,
        meal_box_complete=True,
    )
    assert thin < 0.5
    assert earned == 1.0


def test_humility_dampens_confirmation_in_final_score() -> None:
    honest = evaluate_candidate_payload(copy.deepcopy(STRONG_PAYLOAD))
    overclaimed = copy.deepcopy(STRONG_PAYLOAD)
    overclaimed["confirmation_level"] = 0.95
    overclaimed["narrative"]["mention_count"] = 2
    overclaimed["narrative"]["origin_count"] = 1
    overclaimed["narrative"]["independent_origin_count"] = 1
    capped = evaluate_candidate_payload(overclaimed)
    assert capped["decision"]["humility_index"] < 1.0
    assert (
        capped["decision"]["score_components"]["confirmation"]
        < honest["decision"]["score_components"]["confirmation"]
    )


def test_shock_without_narrative_is_flagged() -> None:
    payload = {
        "ticker": "GHOST",
        "prediction_market": {
            "market_name": "phantom event",
            "probability_before": 0.2,
            "probability_after": 0.6,
            "velocity": 0.9,
            "market_importance": 0.9,
            "market_liquidity": 0.8,
            "cross_source_confirmation": 0.8,
        },
        "narrative": {
            "mention_count": 0, "origin_count": 0,
            "independent_origin_count": 0, "source_quality": 0.0,
            "narrative_velocity": 0.0, "narrative_acceleration": 0.0,
        },
    }
    report = inspect_payload(payload)
    assert any(v.check == "shock_without_narrative" for v in report.violations)


def test_empty_payload_is_not_suspicious_just_empty() -> None:
    # Scrutineering targets fabricated optimism, not absence of claims.
    report = inspect_payload({})
    checks = {v.check for v in report.violations}
    assert "uniform_optimism" not in checks
    assert "confirmation_without_origins" not in checks
