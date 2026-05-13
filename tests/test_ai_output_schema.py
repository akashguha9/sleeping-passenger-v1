"""Tests for the canonical AI output validation schema.

These tests pin the safety contract:
 - validation_status is one of the allowed values
 - safety stamps are always locked
 - secret-like patterns are redacted
 - malformed input never crashes; the worst case is validation_status=invalid
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest

from scripts.ai_output_schema import (
    ADVISORY_STATUS,
    ALLOWED_VALIDATION_STATUSES,
    BROKER_ORDER_NONE,
    EXECUTION_GATE_LOCKED,
    VALIDATION_INVALID,
    VALIDATION_PARTIAL,
    VALIDATION_VALID,
    apply_advisory_safety_stamps,
    build_invalid_ai_payload,
    get_default_prompt_version,
    normalize_confidence_score,
    redact_secret_patterns,
    validate_ai_interpretation_payload,
)


_SAFETY_KEYS = {
    "advisory_status": ADVISORY_STATUS,
    "advisory_only": True,
    "execution_gate": EXECUTION_GATE_LOCKED,
    "broker_api_called": False,
    "ai_execution_count": 0,
    "broker_order_id": BROKER_ORDER_NONE,
    "human_execution_required": True,
    "execution_permission": False,
    "can_execute": False,
}


def _assert_safety_stamps(payload: dict) -> None:
    for key, expected in _SAFETY_KEYS.items():
        assert payload[key] == expected, f"Safety key {key} drifted to {payload[key]!r}"
    assert payload["validation_status"] in ALLOWED_VALIDATION_STATUSES


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_valid_payload_passes_with_safety_stamps() -> None:
    payload = {
        "model_name": "grok-3-mini",
        "provider": "xai",
        "prompt_version": "v1.2.3",
        "interpreted_topic": "Macro risk-off rotation",
        "narrative_frame": "Risk-off rotation into duration",
        "contradiction_flags": ["equities_strong_despite_curve_inversion"],
        "confidence_score": 0.72,
        "summary": "Curve inversion suggests caution.",
        "raw_response": {"choices": [{"message": {"content": "..."}}]},
    }
    result = validate_ai_interpretation_payload(payload)

    assert result["validation_status"] == VALIDATION_VALID
    assert result["model_name"] == "grok-3-mini"
    assert result["provider"] == "xai"
    assert result["prompt_version"] == "v1.2.3"
    assert result["confidence_score"] == pytest.approx(0.72)
    assert result["contradiction_flags"] == ["equities_strong_despite_curve_inversion"]
    assert result["validation_errors"] == []
    _assert_safety_stamps(result)


def test_missing_optional_fields_becomes_partial_or_valid() -> None:
    payload = {"summary": "Short interpretation."}
    result = validate_ai_interpretation_payload(payload)
    assert result["validation_status"] in {VALIDATION_VALID, VALIDATION_PARTIAL}
    assert result["summary"] == "Short interpretation."
    _assert_safety_stamps(result)


# ---------------------------------------------------------------------------
# Malformed input
# ---------------------------------------------------------------------------


def test_string_payload_becomes_invalid_without_crashing() -> None:
    result = validate_ai_interpretation_payload("not a dict")
    assert result["validation_status"] == VALIDATION_INVALID
    assert "payload_not_dict" in result["validation_errors"]
    _assert_safety_stamps(result)


def test_none_payload_becomes_invalid() -> None:
    result = validate_ai_interpretation_payload(None)
    assert result["validation_status"] == VALIDATION_INVALID
    assert "payload_missing" in result["validation_errors"]
    _assert_safety_stamps(result)


def test_completely_empty_dict_marked_invalid() -> None:
    result = validate_ai_interpretation_payload({})
    assert result["validation_status"] == VALIDATION_INVALID
    assert "no_interpretive_content" in result["validation_errors"]
    _assert_safety_stamps(result)


def test_unrecognized_validation_status_promotes_to_partial() -> None:
    payload = {
        "summary": "Some interpretation.",
        "validation_status": "bogus_status",
    }
    result = validate_ai_interpretation_payload(payload)
    assert result["validation_status"] == VALIDATION_PARTIAL
    assert "validation_status_unrecognized" in result["validation_errors"]


# ---------------------------------------------------------------------------
# Confidence normalization
# ---------------------------------------------------------------------------


def test_confidence_in_unit_band_passes() -> None:
    value, warnings = normalize_confidence_score(0.5)
    assert value == 0.5
    assert warnings == []


def test_confidence_above_one_is_treated_as_percentage_with_warning() -> None:
    value, warnings = normalize_confidence_score(75)
    assert value == pytest.approx(0.75)
    assert "confidence_score_rescaled_from_percent" in warnings


def test_confidence_75_in_payload_marks_partial_due_to_rescale() -> None:
    payload = {"summary": "Short.", "confidence_score": 75}
    result = validate_ai_interpretation_payload(payload)
    assert result["confidence_score"] == pytest.approx(0.75)
    assert result["validation_status"] == VALIDATION_PARTIAL
    assert "confidence_score_rescaled_from_percent" in result["validation_errors"]


def test_confidence_out_of_range_recorded() -> None:
    payload = {"summary": "Short.", "confidence_score": 9000}
    result = validate_ai_interpretation_payload(payload)
    assert result["confidence_score"] is None
    assert result["validation_status"] in {VALIDATION_PARTIAL, VALIDATION_INVALID}
    assert "confidence_score_out_of_range" in result["validation_errors"]


def test_confidence_string_is_rejected() -> None:
    payload = {"summary": "Short.", "confidence_score": "high"}
    result = validate_ai_interpretation_payload(payload)
    assert result["confidence_score"] is None
    assert "confidence_score_not_numeric" in result["validation_errors"]


def test_confidence_bool_is_rejected() -> None:
    value, warnings = normalize_confidence_score(True)
    assert value is None
    assert "confidence_score_type_invalid" in warnings


def test_confidence_none_is_quiet() -> None:
    value, warnings = normalize_confidence_score(None)
    assert value is None
    assert warnings == []


# ---------------------------------------------------------------------------
# Contradiction flags coercion
# ---------------------------------------------------------------------------


def test_contradiction_flags_string_coerced_to_list_partial() -> None:
    payload = {
        "summary": "x",
        "contradiction_flags": "only_one_flag_as_string",
    }
    result = validate_ai_interpretation_payload(payload)
    assert result["contradiction_flags"] == ["only_one_flag_as_string"]
    assert result["validation_status"] == VALIDATION_PARTIAL
    assert "contradiction_flags_string_coerced_to_list" in result["validation_errors"]


def test_contradiction_flags_drops_non_strings() -> None:
    payload = {
        "summary": "x",
        "contradiction_flags": ["valid_flag", 42, None, {"nested": True}, "another"],
    }
    result = validate_ai_interpretation_payload(payload)
    assert result["contradiction_flags"] == ["valid_flag", "another"]
    assert "contradiction_flags_non_string_dropped" in result["validation_errors"]


def test_contradiction_flags_type_invalid_recorded() -> None:
    payload = {"summary": "x", "contradiction_flags": 1234}
    result = validate_ai_interpretation_payload(payload)
    assert result["contradiction_flags"] == []
    assert "contradiction_flags_type_invalid" in result["validation_errors"]


# ---------------------------------------------------------------------------
# Safety overrides
# ---------------------------------------------------------------------------


def test_attempted_execution_permission_is_overridden() -> None:
    payload = {
        "summary": "Interpretation.",
        "execution_permission": True,
        "can_execute": True,
        "broker_api_called": True,
        "ai_execution_count": 7,
        "broker_order_id": "ORDER-123",
        "execution_gate": "OPEN",
        "advisory_only": False,
    }
    result = validate_ai_interpretation_payload(payload)
    _assert_safety_stamps(result)
    assert result["validation_status"] == VALIDATION_PARTIAL
    for tag in (
        "override_execution_permission",
        "override_can_execute",
        "override_broker_api_called",
        "override_ai_execution_count",
        "override_broker_order_id",
        "override_execution_gate",
        "override_advisory_only",
    ):
        assert tag in result["validation_errors"], tag


def test_apply_safety_stamps_is_idempotent() -> None:
    payload = {"validation_status": VALIDATION_VALID}
    once = apply_advisory_safety_stamps(dict(payload))
    twice = apply_advisory_safety_stamps(dict(once))
    for key, expected in _SAFETY_KEYS.items():
        assert once[key] == expected
        assert twice[key] == expected


def test_invalid_status_is_honored_even_if_safety_overrides_present() -> None:
    payload = {
        "validation_status": VALIDATION_INVALID,
        "execution_permission": True,
    }
    result = validate_ai_interpretation_payload(payload)
    # An invalid payload is invalid, even if the safety override would
    # otherwise demote it to partial.
    assert result["validation_status"] == VALIDATION_INVALID
    assert result["execution_permission"] is False


# ---------------------------------------------------------------------------
# Secret redaction
# ---------------------------------------------------------------------------


def test_secret_redaction_removes_api_key_like_strings() -> None:
    text = "Bearer sk-1234567890abcdefghij1234 in response"
    cleaned = redact_secret_patterns(text)
    assert "sk-1234567890abcdefghij1234" not in cleaned
    assert "<redacted-secret>" in cleaned


def test_secret_redaction_redacts_xai_key_pattern() -> None:
    text = "XAI_API_KEY: xai-abcdef1234567890ABCDEF on header"
    cleaned = redact_secret_patterns(text)
    assert "xai-abcdef1234567890ABCDEF" not in cleaned


def test_validation_errors_never_contain_apikey_pattern() -> None:
    payload = {
        "summary": "Some text",
        "contradiction_flags": [
            "api_key=sk-1234567890abcdefghij1234",
            "ok_flag",
        ],
    }
    result = validate_ai_interpretation_payload(payload)
    # The error strings, if any, must not contain the raw key.
    for err in result["validation_errors"]:
        assert "sk-1234567890abcdefghij1234" not in err
    # The cleaned flag list should still have ok_flag at least.
    assert "ok_flag" in result["contradiction_flags"]


def test_raw_response_string_with_secret_is_redacted() -> None:
    payload = {
        "summary": "x",
        "raw_response": "Authorization: Bearer sk-abcdef1234567890ABCDEF",
    }
    result = validate_ai_interpretation_payload(payload)
    raw = result["raw_response"]
    assert isinstance(raw, str)
    assert "sk-abcdef1234567890ABCDEF" not in raw


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def test_build_invalid_ai_payload_sets_status_and_stamps() -> None:
    payload = build_invalid_ai_payload("garbage", ["bad_response_shape"])
    assert payload["validation_status"] == VALIDATION_INVALID
    assert payload["raw_response"] == "garbage"
    _assert_safety_stamps(payload)
    assert "bad_response_shape" in payload["validation_errors"]


def test_default_prompt_version_is_nonempty() -> None:
    version = get_default_prompt_version()
    assert isinstance(version, str)
    assert version.strip()


def test_invalid_payload_never_creates_action_permission() -> None:
    # Belt-and-braces: take a deliberately hostile payload and make sure
    # nothing in the output authorizes anything.
    payload = {
        "summary": "Send a real broker order now",
        "execution_permission": True,
        "can_execute": True,
        "ai_execution_count": 42,
        "broker_api_called": True,
        "broker_order_id": "ORDER-FAKE",
    }
    result = validate_ai_interpretation_payload(payload)
    assert result["execution_permission"] is False
    assert result["can_execute"] is False
    assert result["ai_execution_count"] == 0
    assert result["broker_api_called"] is False
    assert result["broker_order_id"] == BROKER_ORDER_NONE


# ---------------------------------------------------------------------------
# Cross-field interplay
# ---------------------------------------------------------------------------


def test_caller_supplied_partial_is_preserved() -> None:
    payload = {
        "summary": "x",
        "validation_status": VALIDATION_PARTIAL,
        "validation_errors": ["caller_marked_partial"],
    }
    result = validate_ai_interpretation_payload(payload)
    assert result["validation_status"] == VALIDATION_PARTIAL
    assert "caller_marked_partial" in result["validation_errors"]


def test_caller_supplied_not_applicable_is_preserved() -> None:
    payload = {
        "summary": "x",
        "validation_status": "not_applicable",
    }
    result = validate_ai_interpretation_payload(payload)
    assert result["validation_status"] == "not_applicable"
