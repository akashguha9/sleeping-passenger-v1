"""Tests for scripts/fission_branch_mapper.py."""

from __future__ import annotations

from scripts.fission_branch_mapper import (
    BRANCH_FAMILIES,
    RECOMMENDED_STATES,
    SAFETY_STAMPS,
    classify_fission_event,
    map_fission_branches,
    score_branch_energy,
)


def _assert_safety(payload: dict) -> None:
    safety = payload["safety"]
    assert safety["advisory_status"] == "ADVISORY_ONLY"
    assert safety["execution_gate"] == "LOCKED"
    assert safety["broker_api_called"] is False
    assert safety["ai_execution_count"] == 0
    assert safety["execution_permission"] is False
    assert safety["can_execute"] is False


def test_safety_stamps_constants():
    assert SAFETY_STAMPS["advisory_status"] == "ADVISORY_ONLY"


def test_central_bank_shock_creates_multiple_branches():
    payload = map_fission_branches({
        "event_type": "central_bank",
        "event_severity": 0.9,
        "market_sensitivity": 0.8,
        "cross_asset_coupling": 0.8,
        "narrative_reach": 0.7,
        "liquidity_sensitivity": 0.8,
        "uncertainty": 0.2,
        "source_reliability": 0.9,
        "market_confirmation": 0.7,
        "time_propagation": 0.6,
        "narrative_intensity": 0.6,
    })
    _assert_safety(payload)
    assert payload["fission_event"] is True
    assert payload["branch_count"] >= 5
    assert payload["recommendation"] in {"watch_branches", "human_review_only"}


def test_low_severity_event_is_not_fission():
    payload = map_fission_branches({
        "event_type": "macro_print",
        "event_severity": 0.1,
        "market_sensitivity": 0.1,
    })
    _assert_safety(payload)
    assert payload["fission_event"] is False
    assert payload["recommendation"] == "do_not_promote"


def test_high_uncertainty_yields_map_only():
    payload = map_fission_branches({
        "event_type": "geopolitics",
        "event_severity": 0.9,
        "uncertainty": 0.95,
        "narrative_reach": 0.8,
        "source_reliability": 0.3,
        "market_sensitivity": 0.5,
        "cross_asset_coupling": 0.6,
        "liquidity_sensitivity": 0.5,
    })
    _assert_safety(payload)
    assert payload["fission_event"] is True
    assert payload["recommendation"] == "map_only"


def test_branch_energy_clamped_for_garbage():
    scored = score_branch_energy(
        {"event_severity": 5, "market_sensitivity": -1},
        {"branch_family": "equities", "sector_sensitivity": 99, "narrative_fit": -3,
         "liquidity_transmission": "wat", "relevance": "1.0"},
    )
    _assert_safety(scored)
    assert 0.0 <= scored["branch_energy"] <= 1.0


def test_no_execution_fields_anywhere_in_branches():
    payload = map_fission_branches({
        "event_type": "central_bank",
        "event_severity": 0.9,
        "market_sensitivity": 0.8,
    })
    _assert_safety(payload)
    for b in payload["branches"]:
        for k in b.keys():
            assert "execute" not in k.lower()
            assert "broker" not in k.lower()
            assert "buy" not in k.lower()
            assert "sell" not in k.lower()


def test_missing_fields_handled_safely():
    payload = map_fission_branches({})
    _assert_safety(payload)
    assert payload["fission_event"] is False


def test_classify_fission_event_returns_summary_only():
    payload = classify_fission_event({
        "event_type": "central_bank",
        "event_severity": 0.9,
        "market_sensitivity": 0.8,
        "source_reliability": 0.9,
        "market_confirmation": 0.7,
    })
    _assert_safety(payload)
    assert "fission_event" in payload
    assert "branch_clarity_score" in payload


def test_branch_family_set_complete():
    for f in ("equities", "sector", "rates", "fx", "commodities", "crypto",
              "policy", "geopolitics", "liquidity", "sentiment",
              "legal_regulatory", "operator_risk"):
        assert f in BRANCH_FAMILIES


def test_recommended_states_set_complete():
    for s in ("map_only", "watch_branches", "review_after_confirmation",
              "do_not_promote", "human_review_only"):
        assert s in RECOMMENDED_STATES


def test_explicit_branches_input_respected():
    payload = map_fission_branches({
        "event_type": "central_bank",
        "event_severity": 0.8,
        "market_sensitivity": 0.7,
        "uncertainty": 0.2,
        "source_reliability": 0.9,
        "branches": [
            {"branch_family": "rates", "relevance": 0.9, "sector_sensitivity": 0.9,
             "narrative_fit": 0.7, "liquidity_transmission": 0.8},
        ],
    })
    _assert_safety(payload)
    assert payload["branch_count"] == 1


def test_deterministic():
    event = {
        "event_type": "central_bank",
        "event_severity": 0.8,
        "market_sensitivity": 0.7,
    }
    a = map_fission_branches(event)
    b = map_fission_branches(event)
    assert a == b


def test_operator_action_never_implies_execution():
    payload = map_fission_branches({
        "event_type": "central_bank",
        "event_severity": 0.9,
        "market_sensitivity": 0.8,
    })
    _assert_safety(payload)
    action = payload["operator_action"]
    assert action in {"observe", "map_branches"}
