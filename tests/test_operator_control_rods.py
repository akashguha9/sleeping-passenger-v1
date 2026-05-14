"""Tests for scripts/operator_control_rods.py."""

from __future__ import annotations

from scripts.operator_control_rods import (
    ALLOWED_ACTION_KEYS,
    CONTROL_ROD_REASONS,
    SAFETY_STAMPS,
    classify_meltdown_risk,
    compute_containment_capacity,
    compute_operator_heat,
    insert_control_rods,
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
    assert SAFETY_STAMPS["execution_gate"] == "LOCKED"


def test_calm_operator_gives_low_heat():
    payload = compute_operator_heat({
        "fomo": 0.0,
        "revenge": 0.0,
        "anger": 0.0,
        "euphoria": 0.0,
        "urgency": 0.1,
        "leverage_temptation": 0.0,
        "thesis_attachment": 0.1,
        "panic": 0.0,
        "overconfidence": 0.0,
        "emotional_state": "calm",
    })
    _assert_safety(payload)
    assert payload["operator_heat_score"] < 0.25


def test_revenge_fomo_sleep_deprivation_high_heat():
    state = {
        "fomo": 0.9,
        "revenge": 0.9,
        "anger": 0.6,
        "urgency": 0.9,
        "leverage_temptation": 0.8,
        "emotional_state": "revenge",
        "sleep_quality": 0.2,
        "process_compliance": 0.2,
        "journal_complete": False,
        "recent_loss": True,
    }
    heat = compute_operator_heat(state)
    _assert_safety(heat)
    assert heat["operator_heat_score"] > 0.6

    risk = classify_meltdown_risk(state, {"narrative_charge": 0.5, "volatility": 0.5})
    _assert_safety(risk)
    assert risk["gallardo_block"] is True


def test_high_heat_triggers_gallardo_block_and_no_broker_execute():
    state = {
        "fomo": 0.95,
        "urgency": 0.95,
        "leverage_temptation": 0.9,
        "process_compliance": 0.2,
        "journal_complete": False,
    }
    risk = classify_meltdown_risk(state, {})
    _assert_safety(risk)
    assert risk["gallardo_block"] is True
    assert risk["allowed_actions"]["broker_execute"] is False


def test_altered_state_triggers_gallardo_block():
    state = {
        "substance_or_altered_state_flag": True,
        "process_compliance": 0.9,
        "journal_complete": True,
    }
    risk = classify_meltdown_risk(state, {})
    _assert_safety(risk)
    assert risk["gallardo_block"] is True
    assert "altered_perception" in risk["control_rods_inserted"]


def test_low_process_compliance_inserts_control_rod():
    rods = insert_control_rods(
        {"process_compliance": 0.2, "journal_complete": False},
        {},
    )
    _assert_safety(rods)
    assert "process_non_compliance" in rods["control_rods_inserted"]


def test_high_leverage_temptation_inserts_control_rod():
    rods = insert_control_rods(
        {"leverage_temptation": 0.95, "process_compliance": 0.9, "journal_complete": True},
        {},
    )
    _assert_safety(rods)
    assert "leverage_temptation" in rods["control_rods_inserted"]


def test_containment_reduces_meltdown_risk():
    state = {"fomo": 0.5, "urgency": 0.5, "process_compliance": 0.7, "journal_complete": True}
    high_containment = classify_meltdown_risk(
        state,
        {"containment_strength": 0.9, "volatility": 0.2, "chaos_risk": 0.1},
    )
    low_containment = classify_meltdown_risk(
        state,
        {"containment_strength": 0.1, "volatility": 0.9, "chaos_risk": 0.9},
    )
    _assert_safety(high_containment)
    _assert_safety(low_containment)
    assert high_containment["meltdown_risk_score"] <= low_containment["meltdown_risk_score"]


def test_broker_execute_always_false():
    for state in (
        {},
        {"fomo": 0.0, "process_compliance": 1.0, "journal_complete": True, "sleep_quality": 1.0},
        {"fomo": 0.9, "revenge": 0.9, "anger": 0.9},
        {"substance_or_altered_state_flag": True},
    ):
        payload = classify_meltdown_risk(state, {})
        _assert_safety(payload)
        assert payload["allowed_actions"]["broker_execute"] is False


def test_manual_trade_logging_disabled_when_gallardo_block():
    payload = classify_meltdown_risk(
        {"fomo": 0.95, "revenge": 0.9, "urgency": 0.95, "process_compliance": 0.2},
        {},
    )
    _assert_safety(payload)
    assert payload["gallardo_block"] is True
    assert payload["allowed_actions"]["manual_trade_logging_allowed"] is False


def test_manual_trade_logging_allowed_when_calm_compliant():
    payload = classify_meltdown_risk(
        {"fomo": 0.0, "urgency": 0.1, "process_compliance": 0.9, "journal_complete": True,
         "sleep_quality": 0.8},
        {"containment_strength": 0.9},
    )
    _assert_safety(payload)
    assert payload["gallardo_block"] is False
    assert payload["allowed_actions"]["manual_trade_logging_allowed"] is True


def test_missing_data_is_safe():
    for inputs in (None, {}, {"emotional_state": None}, "not a dict"):
        payload = classify_meltdown_risk(inputs, None)
        _assert_safety(payload)
        assert payload["allowed_actions"]["broker_execute"] is False


def test_compute_containment_capacity_clamped():
    payload = compute_containment_capacity({
        "containment_strength": 99,
        "volatility": -1,
        "chaos_risk": "bad",
    })
    _assert_safety(payload)
    assert 0.0 <= payload["containment_capacity"] <= 1.0
    assert 0.0 <= payload["reaction_heat"] <= 1.0


def test_no_execution_fields_in_top_level_keys():
    payload = classify_meltdown_risk({"fomo": 0.5}, {})
    _assert_safety(payload)
    for key in payload.keys():
        assert "broker" not in key.lower() or key == "safety"
        assert "place_order" not in key.lower()
        assert "execute_trade" not in key.lower()


def test_control_rod_reasons_set_complete():
    for reason in ("altered_perception", "emotional_heat", "process_non_compliance",
                   "leverage_temptation", "recent_loss_revenge", "sleep_deficit",
                   "thesis_attachment", "external_chaos"):
        assert reason in CONTROL_ROD_REASONS


def test_allowed_action_keys_set_complete():
    for key in ("observe", "journal", "review_later", "manual_trade_logging_allowed",
                "broker_execute"):
        assert key in ALLOWED_ACTION_KEYS


def test_deterministic_repeated_calls_equal():
    state = {"fomo": 0.5, "urgency": 0.5, "process_compliance": 0.5, "journal_complete": True}
    a = classify_meltdown_risk(state, {"containment_strength": 0.5})
    b = classify_meltdown_risk(state, {"containment_strength": 0.5})
    assert a == b
