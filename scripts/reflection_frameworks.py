"""
Reflection framework metadata helper (advisory-only, metadata-only).

Purpose
-------
This module is the *structured-metadata* companion to:

- ``docs/REFLECTION_FRAMEWORKS.md``
- ``docs/FRAMEWORK_COMPONENT_MAP.md``
- ``docs/DIAGNOSTIC_FRAMEWORK_ROADMAP.md``

It exposes the framework component inventory as plain Python data, plus a
tiny pure-Python API for classification, validation, and a scorecard.

It is deliberately:

- deterministic — no live API calls, no AI calls, no broker calls
- side-effect-free — no DB writes, no filesystem writes, no network
- safety-stamped — every component metadata blob carries the canonical
  advisory-only safety invariants
- decoupled — nothing in ``scripts/api_server.py`` or ``scripts/persistence.py``
  imports this module; it is a metadata registry, not a runtime hook

Safety contract (must hold for every component metadata blob)
-------------------------------------------------------------

    ∀ component ∈ FRAMEWORK_COMPONENTS:
        component["can_execute"]           = false
        component["execution_permission"]  = false
        component["advisory_status"]       = "ADVISORY_ONLY"
        component["execution_gate"]        = "LOCKED"
        component["broker_api_called"]     = false
        component["ai_execution_count"]    = 0

Public API
----------
- ``FRAMEWORK_COMPONENTS``     -- list of component metadata dicts
- ``SAFETY_INVARIANT_FIELDS``  -- canonical safety stamp keys
- ``PROFESSIONAL_FIELD_NAMES`` -- canonical engineering field names
- ``BANNED_THEATRICAL_TERMS``  -- substrings forbidden in professional names
- ``classify_framework_priority(component_name)``
- ``validate_framework_component_map(component_map)``
- ``get_reflection_framework_scorecard()``
"""

from __future__ import annotations

from typing import Any, Dict, List


SAFETY_INVARIANT_FIELDS: Dict[str, Any] = {
    "advisory_status": "ADVISORY_ONLY",
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "ai_execution_count": 0,
    "execution_permission": False,
    "can_execute": False,
}


PROFESSIONAL_FIELD_NAMES: List[str] = [
    "chaos_sensitivity_score",
    "classification_stability_score",
    "narrative_resonance_score",
    "amplification_risk_score",
    "cross_frame_stability_score",
    "operator_desire_distortion_score",
    "source_failure_resilience_score",
    "signal_path_redundancy_count",
    "signal_rhythm_integrity_score",
    "arrhythmia_risk_score",
    "boundary_violation",
    "distribution_shift_score",
    "pattern_emergence_score",
    "amplification_pathway_score",
    "continuity_mode_active",
    "last_known_good_drift_score",
    "signal_metabolism_score",
    "stale_signal_decay_score",
    "cross_source_rescue_score",
    "contamination_score",
    "toxic_quarantine_state",
    "reaction_inhibition_active",
    "perception_not_permission",
]


BANNED_THEATRICAL_TERMS: List[str] = [
    "higgs",
    "magick",
    "spell",
    "occult",
    "botox",
    "penguin",
    "termite",
    "sunflower",
    "ritual",
    "sigil",
    "phytoremediation",
    "mitochondria",
    "neurotoxin",
    "sinoatrial",
    "nightwatch",
    "painkiller",
    "nsaid",
]


VALID_PRIORITIES = {"P0", "P1", "P2", "P3"}
VALID_STATUSES = {
    "existing",
    "existing_canonical",
    "existing_partial",
    "partial",
    "missing",
    "future",
}


def _stamp(blob: Dict[str, Any]) -> Dict[str, Any]:
    """Return ``blob`` augmented with the canonical safety invariants."""
    stamped = dict(blob)
    for k, v in SAFETY_INVARIANT_FIELDS.items():
        stamped[k] = v
    return stamped


FRAMEWORK_COMPONENTS: List[Dict[str, Any]] = [
    _stamp({
        "concept": "Chaos pendulum / sensitive dependence",
        "professional_name": "signal_sensitivity_diagnostics",
        "priority": "P1",
        "status": "missing",
        "safety_relevance": (
            "reduces overconfidence in signals whose classification flips under "
            "small input perturbations; never grants execution"
        ),
    }),
    _stamp({
        "concept": "Higgs turbulent resonance (metaphor source)",
        "professional_name": "narrative_resonance_score",
        "priority": "P2",
        "status": "missing",
        "safety_relevance": (
            "flags amplification surface around a story; flag-only, "
            "never used to authorize action"
        ),
    }),
    _stamp({
        "concept": "Chaos Magick (epistemology source)",
        "professional_name": "paradigm_shift_audit",
        "priority": "P2",
        "status": "missing",
        "safety_relevance": (
            "discounts frame-dependent conviction; documentation-only at "
            "MVP stage"
        ),
    }),
    _stamp({
        "concept": "Termite mound resilience",
        "professional_name": "colony_resilience_score",
        "priority": "P2",
        "status": "partial",
        "safety_relevance": (
            "rolls up source-health into a single resilience score; "
            "diagnostic only"
        ),
    }),
    _stamp({
        "concept": "Sinoatrial node / signal pacemaker",
        "professional_name": "signal_rhythm_integrity",
        "priority": "P2",
        "status": "partial",
        "safety_relevance": (
            "rhythm-of-confirmation score over refresh cadence; never "
            "unlocks execution"
        ),
    }),
    _stamp({
        "concept": "Penguin / equator hard boundary",
        "professional_name": "boundary_condition_gate",
        "priority": "P0",
        "status": "existing_canonical",
        "safety_relevance": (
            "canonical advisory-only safety lock; outranks any opportunity "
            "signal"
        ),
    }),
    _stamp({
        "concept": "Galton board / distribution emergence",
        "professional_name": "distribution_shift_diagnostics",
        "priority": "P1",
        "status": "missing",
        "safety_relevance": (
            "histogram diff against baseline; never overclaims on small n"
        ),
    }),
    _stamp({
        "concept": "Painkiller / amplification pathway",
        "professional_name": "amplification_pathway_filter",
        "priority": "P1",
        "status": "missing",
        "safety_relevance": (
            "decomposes signal pain into event x pathway x sensitivity; "
            "flag-only"
        ),
    }),
    _stamp({
        "concept": "E-4B / continuity of command",
        "professional_name": "continuity_mode",
        "priority": "P1",
        "status": "partial",
        "safety_relevance": (
            "explicit degraded-safe operating mode; reduces conviction "
            "rather than increasing it under crisis"
        ),
    }),
    _stamp({
        "concept": "Mitochondria / signal metabolism",
        "professional_name": "signal_metabolism_diagnostics",
        "priority": "P2",
        "status": "missing",
        "safety_relevance": (
            "decay and fate logic so weak signals do not linger; diagnostic only"
        ),
    }),
    _stamp({
        "concept": "Sunflower phytoremediation / toxic quarantine",
        "professional_name": "toxic_signal_quarantine",
        "priority": "P1",
        "status": "missing",
        "safety_relevance": (
            "quarantine state machine for toxic signals; preserves data for "
            "learning, blocks promotion"
        ),
    }),
    _stamp({
        "concept": "Botox / targeted reaction inhibition",
        "professional_name": "reaction_inhibition_gate",
        "priority": "P0",
        "status": "existing_canonical",
        "safety_relevance": (
            "canonical separation between perception and action; perception "
            "is not permission"
        ),
    }),
]


def classify_framework_priority(component_name: str) -> str:
    """Return the priority (P0/P1/P2/P3) of a component by professional name.

    Raises ``KeyError`` if the name is unknown.
    """
    for component in FRAMEWORK_COMPONENTS:
        if component["professional_name"] == component_name:
            return component["priority"]
    raise KeyError(f"unknown framework component: {component_name}")


def validate_framework_component_map(component_map: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Validate a list of framework component metadata blobs.

    Returns a dict with ``valid`` (bool) and ``errors`` (list[str]).

    Validation rules:

    - every component has a non-empty ``concept`` and ``professional_name``
    - every component has a valid ``priority`` (P0..P3) and ``status``
    - every component carries every key in ``SAFETY_INVARIANT_FIELDS`` with the
      canonical value
    - no ``professional_name`` contains any term in ``BANNED_THEATRICAL_TERMS``
      (case-insensitive)
    """
    errors: List[str] = []
    for index, component in enumerate(component_map):
        prefix = f"component[{index}]"
        concept = component.get("concept")
        if not isinstance(concept, str) or not concept.strip():
            errors.append(f"{prefix}: missing concept")
        name = component.get("professional_name")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{prefix}: missing professional_name")
        else:
            lowered = name.lower()
            for banned in BANNED_THEATRICAL_TERMS:
                if banned in lowered:
                    errors.append(
                        f"{prefix}: professional_name '{name}' contains "
                        f"banned theatrical term '{banned}'"
                    )
        priority = component.get("priority")
        if priority not in VALID_PRIORITIES:
            errors.append(f"{prefix}: invalid priority {priority!r}")
        status = component.get("status")
        if status not in VALID_STATUSES:
            errors.append(f"{prefix}: invalid status {status!r}")
        for k, expected in SAFETY_INVARIANT_FIELDS.items():
            actual = component.get(k, "<missing>")
            if actual != expected:
                errors.append(
                    f"{prefix}: safety field {k!r} is {actual!r}, "
                    f"expected {expected!r}"
                )
    return {"valid": not errors, "errors": errors}


def get_reflection_framework_scorecard() -> Dict[str, Any]:
    """Return a compact metadata scorecard for the reflection frameworks.

    No live calls, no DB reads. Pure metadata aggregation.
    """
    counts_by_priority: Dict[str, int] = {p: 0 for p in VALID_PRIORITIES}
    counts_by_status: Dict[str, int] = {s: 0 for s in VALID_STATUSES}
    for component in FRAMEWORK_COMPONENTS:
        counts_by_priority[component["priority"]] = (
            counts_by_priority.get(component["priority"], 0) + 1
        )
        counts_by_status[component["status"]] = (
            counts_by_status.get(component["status"], 0) + 1
        )
    return {
        "total_components": len(FRAMEWORK_COMPONENTS),
        "counts_by_priority": counts_by_priority,
        "counts_by_status": counts_by_status,
        "safety_invariants": dict(SAFETY_INVARIANT_FIELDS),
        "banned_theatrical_terms": list(BANNED_THEATRICAL_TERMS),
        "professional_field_names": list(PROFESSIONAL_FIELD_NAMES),
        "doctrine": (
            "Observe everything, execute nothing, promote only what "
            "survives perturbation, distribution, boundary, and "
            "contamination checks."
        ),
    }
