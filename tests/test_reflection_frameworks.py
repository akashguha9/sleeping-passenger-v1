"""Tests for the reflection framework metadata helper.

Pin the safety contract for ``scripts/reflection_frameworks.py``:

- every component is present, with a professional engineering name
- no banned theatrical term appears in any professional name
- every component carries the canonical advisory-only safety stamps
- P0 includes the canonical safety-lock components
- the validator correctly rejects malformed / banned component blobs
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest

from scripts.reflection_frameworks import (
    BANNED_THEATRICAL_TERMS,
    FRAMEWORK_COMPONENTS,
    PROFESSIONAL_FIELD_NAMES,
    SAFETY_INVARIANT_FIELDS,
    VALID_PRIORITIES,
    VALID_STATUSES,
    classify_framework_priority,
    get_reflection_framework_scorecard,
    validate_framework_component_map,
)


# ---------------------------------------------------------------------------
# Inventory completeness
# ---------------------------------------------------------------------------

_EXPECTED_CONCEPT_FRAGMENTS = [
    "chaos pendulum",
    "higgs",
    "chaos magick",
    "termite",
    "sinoatrial",
    "penguin",
    "galton",
    "painkiller",
    "e-4b",
    "mitochondria",
    "sunflower",
    "botox",
]


def test_inventory_has_all_twelve_major_concepts():
    """All 12 reflection concepts are present in FRAMEWORK_COMPONENTS."""
    concepts = [c["concept"].lower() for c in FRAMEWORK_COMPONENTS]
    missing = [
        fragment
        for fragment in _EXPECTED_CONCEPT_FRAGMENTS
        if not any(fragment in concept for concept in concepts)
    ]
    assert not missing, f"missing concept fragments: {missing}"


def test_inventory_has_exactly_twelve_components():
    """The inventory does not silently grow or shrink."""
    assert len(FRAMEWORK_COMPONENTS) == 12


# ---------------------------------------------------------------------------
# Professional-name discipline
# ---------------------------------------------------------------------------

def test_every_component_has_professional_name():
    for component in FRAMEWORK_COMPONENTS:
        name = component.get("professional_name")
        assert isinstance(name, str) and name.strip(), (
            f"component {component} missing professional_name"
        )


@pytest.mark.parametrize("banned", BANNED_THEATRICAL_TERMS)
def test_no_professional_name_contains_banned_term(banned):
    """Theatrical metaphor words must never appear in professional names."""
    for component in FRAMEWORK_COMPONENTS:
        assert banned not in component["professional_name"].lower(), (
            f"component {component['concept']} uses banned term {banned!r} "
            f"in professional_name {component['professional_name']!r}"
        )


def test_professional_field_names_are_clean():
    """The canonical field-name list also contains no banned terms."""
    for field in PROFESSIONAL_FIELD_NAMES:
        for banned in BANNED_THEATRICAL_TERMS:
            assert banned not in field.lower(), (
                f"professional field name {field!r} contains banned term "
                f"{banned!r}"
            )


# ---------------------------------------------------------------------------
# Priority and status
# ---------------------------------------------------------------------------

def test_every_component_has_valid_priority():
    for component in FRAMEWORK_COMPONENTS:
        assert component["priority"] in VALID_PRIORITIES, (
            f"component {component['concept']} has invalid priority "
            f"{component['priority']!r}"
        )


def test_every_component_has_valid_status():
    for component in FRAMEWORK_COMPONENTS:
        assert component["status"] in VALID_STATUSES, (
            f"component {component['concept']} has invalid status "
            f"{component['status']!r}"
        )


def test_p0_includes_canonical_safety_locks():
    """boundary_condition_gate and reaction_inhibition_gate must be P0."""
    p0_names = {
        c["professional_name"]
        for c in FRAMEWORK_COMPONENTS
        if c["priority"] == "P0"
    }
    assert "boundary_condition_gate" in p0_names
    assert "reaction_inhibition_gate" in p0_names


def test_classify_framework_priority_returns_p0_for_safety_locks():
    assert classify_framework_priority("boundary_condition_gate") == "P0"
    assert classify_framework_priority("reaction_inhibition_gate") == "P0"


def test_classify_framework_priority_unknown_raises():
    with pytest.raises(KeyError):
        classify_framework_priority("nonexistent_component_xyz")


# ---------------------------------------------------------------------------
# Safety stamps
# ---------------------------------------------------------------------------

def test_every_component_has_advisory_only_stamp():
    for component in FRAMEWORK_COMPONENTS:
        assert component["advisory_status"] == "ADVISORY_ONLY"


def test_every_component_has_execution_gate_locked():
    for component in FRAMEWORK_COMPONENTS:
        assert component["execution_gate"] == "LOCKED"


def test_can_execute_is_false_for_every_component():
    for component in FRAMEWORK_COMPONENTS:
        assert component["can_execute"] is False


def test_broker_api_called_is_false_for_every_component():
    for component in FRAMEWORK_COMPONENTS:
        assert component["broker_api_called"] is False


def test_ai_execution_count_is_zero_for_every_component():
    for component in FRAMEWORK_COMPONENTS:
        assert component["ai_execution_count"] == 0


def test_execution_permission_is_false_for_every_component():
    for component in FRAMEWORK_COMPONENTS:
        assert component["execution_permission"] is False


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

def test_validator_accepts_canonical_inventory():
    result = validate_framework_component_map(FRAMEWORK_COMPONENTS)
    assert result["valid"] is True, result["errors"]
    assert result["errors"] == []


def test_validator_rejects_missing_professional_name():
    bad = [
        {
            "concept": "x",
            "professional_name": "",
            "priority": "P1",
            "status": "missing",
            **SAFETY_INVARIANT_FIELDS,
        }
    ]
    result = validate_framework_component_map(bad)
    assert result["valid"] is False
    assert any("missing professional_name" in e for e in result["errors"])


def test_validator_rejects_banned_theatrical_name():
    bad = [
        {
            "concept": "x",
            "professional_name": "higgs_engine",
            "priority": "P1",
            "status": "missing",
            **SAFETY_INVARIANT_FIELDS,
        }
    ]
    result = validate_framework_component_map(bad)
    assert result["valid"] is False
    assert any("banned theatrical term" in e for e in result["errors"])


def test_validator_rejects_invalid_priority():
    bad = [
        {
            "concept": "x",
            "professional_name": "some_clean_name",
            "priority": "P9",
            "status": "missing",
            **SAFETY_INVARIANT_FIELDS,
        }
    ]
    result = validate_framework_component_map(bad)
    assert result["valid"] is False
    assert any("invalid priority" in e for e in result["errors"])


def test_validator_rejects_invalid_status():
    bad = [
        {
            "concept": "x",
            "professional_name": "some_clean_name",
            "priority": "P1",
            "status": "ready_for_live",
            **SAFETY_INVARIANT_FIELDS,
        }
    ]
    result = validate_framework_component_map(bad)
    assert result["valid"] is False
    assert any("invalid status" in e for e in result["errors"])


def test_validator_rejects_attempted_execution_permission():
    bad_invariants = dict(SAFETY_INVARIANT_FIELDS)
    bad_invariants["execution_permission"] = True
    bad_invariants["can_execute"] = True
    bad = [
        {
            "concept": "x",
            "professional_name": "some_clean_name",
            "priority": "P1",
            "status": "missing",
            **bad_invariants,
        }
    ]
    result = validate_framework_component_map(bad)
    assert result["valid"] is False
    assert any("execution_permission" in e for e in result["errors"])
    assert any("can_execute" in e for e in result["errors"])


# ---------------------------------------------------------------------------
# Scorecard
# ---------------------------------------------------------------------------

def test_scorecard_returns_expected_shape():
    card = get_reflection_framework_scorecard()
    assert card["total_components"] == len(FRAMEWORK_COMPONENTS)
    assert set(card["counts_by_priority"]).issubset(VALID_PRIORITIES)
    assert set(card["counts_by_status"]).issubset(VALID_STATUSES)
    assert card["safety_invariants"] == dict(SAFETY_INVARIANT_FIELDS)
    assert card["banned_theatrical_terms"] == list(BANNED_THEATRICAL_TERMS)
    assert isinstance(card["doctrine"], str) and card["doctrine"].strip()


def test_scorecard_priority_counts_sum_to_total():
    card = get_reflection_framework_scorecard()
    assert sum(card["counts_by_priority"].values()) == card["total_components"]


def test_scorecard_status_counts_sum_to_total():
    card = get_reflection_framework_scorecard()
    assert sum(card["counts_by_status"].values()) == card["total_components"]
