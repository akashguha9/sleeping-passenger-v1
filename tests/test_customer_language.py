"""Tests for scripts.customer_language — internal->customer translation.

These tests are the contract: every documented internal engine state
must translate to the exact customer-facing action label, unknown /
None / empty input must degrade to ``Review``, and no translation
output may contain any forbidden trading-instruction phrase.
"""
from __future__ import annotations

import pytest

from scripts.customer_language import (
    CUSTOMER_LABEL_AVOID_EXIT_RISK,
    CUSTOMER_LABEL_ENTER_ADD,
    CUSTOMER_LABEL_HOLD_MANAGE,
    CUSTOMER_LABEL_MOMENTUM_ALERT,
    CUSTOMER_LABEL_REVIEW,
    CUSTOMER_LABEL_SHOCK_ALERT,
    CUSTOMER_LABEL_STRONG_WATCH,
    CUSTOMER_LABEL_WATCH,
    FORBIDDEN_CUSTOMER_PHRASES,
    KNOWN_CUSTOMER_LABELS,
    explain_state_for_customer,
    get_customer_action_label,
    get_customer_risk_tone,
    get_full_translation_table,
    is_customer_safe_action_label,
    list_known_internal_states,
    normalize_internal_state,
    translate_internal_state_to_customer_label,
)


@pytest.mark.parametrize(
    "internal_state, expected_label",
    [
        ("MIURA", CUSTOMER_LABEL_WATCH),
        ("MURCIÉLAGO", CUSTOMER_LABEL_STRONG_WATCH),
        ("MURCIELAGO", CUSTOMER_LABEL_STRONG_WATCH),
        ("AVENTADOR", CUSTOMER_LABEL_ENTER_ADD),
        ("GALLARDO", CUSTOMER_LABEL_HOLD_MANAGE),
        ("HURACÁN", CUSTOMER_LABEL_MOMENTUM_ALERT),
        ("HURACAN", CUSTOMER_LABEL_MOMENTUM_ALERT),
        ("ISLERO", CUSTOMER_LABEL_SHOCK_ALERT),
        ("DIABLO", CUSTOMER_LABEL_AVOID_EXIT_RISK),
    ],
)
def test_every_known_state_maps_to_correct_label(internal_state, expected_label):
    assert get_customer_action_label(internal_state) == expected_label


@pytest.mark.parametrize(
    "raw, expected_label",
    [
        ("miura", CUSTOMER_LABEL_WATCH),
        ("Aventador", CUSTOMER_LABEL_ENTER_ADD),
        ("  GALLARDO  ", CUSTOMER_LABEL_HOLD_MANAGE),
        ("diablo", CUSTOMER_LABEL_AVOID_EXIT_RISK),
    ],
)
def test_lowercase_and_whitespace_are_tolerated(raw, expected_label):
    assert get_customer_action_label(raw) == expected_label


@pytest.mark.parametrize("state", [None, "", "   ", "UNKNOWN_STATE", "FOO_BAR"])
def test_unknown_state_maps_to_review(state):
    record = translate_internal_state_to_customer_label(state)
    assert record["customer_label"] == CUSTOMER_LABEL_REVIEW
    assert "research" in record["risk_tone"].lower()


def test_normalize_internal_state_handles_edge_cases():
    assert normalize_internal_state(None) == ""
    assert normalize_internal_state("") == ""
    assert normalize_internal_state("  miura  ") == "MIURA"
    assert normalize_internal_state("MURCIÉLAGO") == "MURCIELAGO"


def test_translation_returns_fresh_dict_per_call():
    a = translate_internal_state_to_customer_label("MIURA")
    a["customer_label"] = "TAMPERED"
    b = translate_internal_state_to_customer_label("MIURA")
    assert b["customer_label"] == CUSTOMER_LABEL_WATCH


def test_explain_state_for_customer_is_human_readable():
    s = explain_state_for_customer("AVENTADOR")
    assert s.startswith(CUSTOMER_LABEL_ENTER_ADD)
    assert "model" in s.lower()


def test_get_customer_risk_tone_uses_known_states():
    assert get_customer_risk_tone("DIABLO").lower().startswith("defensive")


def test_is_customer_safe_action_label_rejects_internal_states():
    for label in KNOWN_CUSTOMER_LABELS:
        assert is_customer_safe_action_label(label) is True
    for state in list_known_internal_states():
        assert is_customer_safe_action_label(state) is False
    assert is_customer_safe_action_label(None) is False
    assert is_customer_safe_action_label("") is False


def test_no_translation_output_contains_forbidden_phrases():
    table = get_full_translation_table()
    table.append(translate_internal_state_to_customer_label("UNKNOWN"))
    for record in table:
        haystack = " ".join(str(v) for v in record.values()).lower()
        for phrase in FORBIDDEN_CUSTOMER_PHRASES:
            assert phrase not in haystack, (
                f"forbidden phrase {phrase!r} found in record {record}"
            )


def test_translation_table_covers_all_known_internal_states():
    table = get_full_translation_table()
    labels = {r["customer_label"] for r in table}
    # All seven internal states map to the seven non-Review labels.
    assert CUSTOMER_LABEL_WATCH in labels
    assert CUSTOMER_LABEL_STRONG_WATCH in labels
    assert CUSTOMER_LABEL_ENTER_ADD in labels
    assert CUSTOMER_LABEL_HOLD_MANAGE in labels
    assert CUSTOMER_LABEL_MOMENTUM_ALERT in labels
    assert CUSTOMER_LABEL_SHOCK_ALERT in labels
    assert CUSTOMER_LABEL_AVOID_EXIT_RISK in labels
    assert len(table) == 7
