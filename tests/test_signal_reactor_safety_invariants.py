"""Cross-module safety invariant tests for the signal-reactor modules.

These tests exercise every public function on every new module added in the
Signal Reactor sprint and assert that the canonical safety stamps are
preserved, that no nested output anywhere claims execution permission,
and that the module source code does not contain forbidden execution
constructs.
"""

from __future__ import annotations

from pathlib import Path

from scripts import (
    adaptive_signal_router,
    echo_risk_engine,
    fission_branch_mapper,
    fusion_thesis_engine,
    operator_control_rods,
    signal_decay_waste,
    signal_field_geometry,
    signal_reactor,
)

CANONICAL_SAFETY_STAMPS = {
    "advisory_status": "ADVISORY_ONLY",
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "ai_execution_count": 0,
    "execution_permission": False,
    "can_execute": False,
}

EXECUTION_KEY_BLACKLIST = {
    "execution_permission",
    "can_execute",
    "broker_api_called",
    "broker_execute",
}

# Top-level (non-nested) tokens that must not appear in any new module's
# source. Function/class names live at the start of a line with `def`/`class`
# and never inside docstrings; we therefore scan for these tokens directly.
FORBIDDEN_RUNTIME_TOKENS = (
    "place_order(",
    "execute_order(",
    "submit_order(",
    "broker_execute(",
    "= True  # broker_execute",
)

# Theatrical metaphor terms that must never appear in *module-level* code
# (function names, class names, top-level identifiers). They are allowed in
# docstrings and comments for translation explanations only.
BANNED_THEATRICAL_TOKENS = (
    "def magic", "def magick", "def spell", "def sigil", "def occult",
    "def psychedelic", "def lsd", "def dmt", "def mushroom", "def ayahuasca",
    "def oracle", "def prophecy", "def divine", "def supernatural",
    "def cosmic", "class Magic", "class Spell", "class Occult",
    "class Psychedelic", "class Oracle", "class Prophecy",
)

NEW_MODULES = (
    signal_field_geometry,
    echo_risk_engine,
    signal_decay_waste,
    fission_branch_mapper,
    fusion_thesis_engine,
    operator_control_rods,
    adaptive_signal_router,
    signal_reactor,
)


def _walk(payload, visitor):
    visitor(payload)
    if isinstance(payload, dict):
        for v in payload.values():
            _walk(v, visitor)
    elif isinstance(payload, list):
        for item in payload:
            _walk(item, visitor)


def _assert_no_execution_anywhere(payload):
    def visit(node):
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            lkey = key.lower()
            if lkey == "ai_execution_count":
                assert value == 0, f"ai_execution_count={value!r} in {key}"
            if lkey == "advisory_status":
                assert value == "ADVISORY_ONLY", f"advisory_status={value!r}"
            if lkey == "execution_gate":
                assert value == "LOCKED", f"execution_gate={value!r}"
            if lkey == "broker_order_id":
                assert value == "NONE", f"broker_order_id={value!r}"
            if lkey in EXECUTION_KEY_BLACKLIST:
                assert value is False, f"{key}={value!r} unexpected True"
    _walk(payload, visit)


def _has_full_safety_stamp(payload) -> bool:
    if not isinstance(payload, dict):
        return False
    safety = payload.get("safety")
    if not isinstance(safety, dict):
        return False
    for k, v in CANONICAL_SAFETY_STAMPS.items():
        if safety.get(k) != v:
            return False
    return True


def test_signal_field_geometry_outputs_safety_stamped():
    p = signal_field_geometry.classify_signal_trace({"narrative_intensity": 0.3})
    assert _has_full_safety_stamp(p)
    _assert_no_execution_anywhere(p)

    p = signal_field_geometry.compute_phase_alignment([
        {"direction": 1, "intensity": 0.5}, {"direction": 1, "intensity": 0.6}
    ])
    assert _has_full_safety_stamp(p)
    _assert_no_execution_anywhere(p)

    p = signal_field_geometry.compute_resonance_score([
        {"direction": 1, "intensity": 0.5, "narrative_charge": 0.7}
    ])
    assert _has_full_safety_stamp(p)
    _assert_no_execution_anywhere(p)

    p = signal_field_geometry.compute_damping_score({"age_hours": 10.0})
    assert _has_full_safety_stamp(p)
    _assert_no_execution_anywhere(p)

    p = signal_field_geometry.classify_field_geometry([
        {"direction": 1, "intensity": 0.4, "source_name": "A"}
    ])
    assert _has_full_safety_stamp(p)
    _assert_no_execution_anywhere(p)


def test_echo_risk_engine_outputs_safety_stamped():
    items = [{"source_name": "A", "url": "u1"}]
    for fn in (
        echo_risk_engine.compute_source_independence,
        echo_risk_engine.compute_echo_risk,
        echo_risk_engine.classify_confirmation_quality,
    ):
        p = fn(items)
        assert _has_full_safety_stamp(p), fn.__name__
        _assert_no_execution_anywhere(p)


def test_signal_decay_waste_outputs_safety_stamped():
    assert _has_full_safety_stamp(signal_decay_waste.compute_signal_half_life({"signal_type": "news"}))
    assert _has_full_safety_stamp(signal_decay_waste.classify_signal_waste({"signal_type": "news"}))
    assert _has_full_safety_stamp(signal_decay_waste.summarize_waste_load({"total_signal_count": 0}))
    _assert_no_execution_anywhere(
        signal_decay_waste.classify_signal_waste({"signal_type": "social_hype", "age_hours": 100})
    )


def test_fission_branch_mapper_outputs_safety_stamped():
    event = {"event_type": "central_bank", "event_severity": 0.8, "market_sensitivity": 0.7}
    p = fission_branch_mapper.map_fission_branches(event)
    assert _has_full_safety_stamp(p)
    _assert_no_execution_anywhere(p)
    p = fission_branch_mapper.classify_fission_event(event)
    assert _has_full_safety_stamp(p)
    _assert_no_execution_anywhere(p)
    p = fission_branch_mapper.score_branch_energy(event, {"branch_family": "rates", "relevance": 0.8})
    assert _has_full_safety_stamp(p)
    _assert_no_execution_anywhere(p)


def test_fusion_thesis_engine_outputs_safety_stamped():
    signals = [
        {"source_name": "A", "direction": 1, "intensity": 0.5, "reliability": 0.7,
         "independence_score": 0.6, "evidence_strength": 0.5},
        {"source_name": "B", "direction": 1, "intensity": 0.5, "reliability": 0.7,
         "independence_score": 0.6, "evidence_strength": 0.5},
    ]
    for fn in (
        fusion_thesis_engine.compute_evidence_density,
        fusion_thesis_engine.compute_fusion_thesis_strength,
        fusion_thesis_engine.classify_fusion_candidate,
    ):
        p = fn(signals)
        assert _has_full_safety_stamp(p), fn.__name__
        _assert_no_execution_anywhere(p)


def test_operator_control_rods_outputs_safety_stamped():
    state = {"fomo": 0.4, "process_compliance": 0.7, "journal_complete": True}
    ctx = {"containment_strength": 0.5, "volatility": 0.3}
    for fn in (
        operator_control_rods.compute_operator_heat,
        operator_control_rods.compute_containment_capacity,
    ):
        p = fn(state if fn is operator_control_rods.compute_operator_heat else ctx)
        assert _has_full_safety_stamp(p), fn.__name__
        _assert_no_execution_anywhere(p)
    for fn in (
        operator_control_rods.insert_control_rods,
        operator_control_rods.classify_meltdown_risk,
    ):
        p = fn(state, ctx)
        assert _has_full_safety_stamp(p), fn.__name__
        _assert_no_execution_anywhere(p)


def test_adaptive_signal_router_outputs_safety_stamped():
    signal = {"reliability": 0.7, "relevance": 0.6, "freshness": 0.6,
              "independence": 0.6, "echo_risk": 0.1, "contradiction": 0.0,
              "legal_risk": 0.0, "liquidity_risk": 0.0,
              "operator_risk": 0.0, "source_risk": 0.0}
    route = {"current_weight": 0.4}
    p = adaptive_signal_router.compute_nutrient_value(signal)
    assert _has_full_safety_stamp(p)
    p = adaptive_signal_router.compute_terrain_penalty(signal)
    assert _has_full_safety_stamp(p)
    p = adaptive_signal_router.update_route_weight(route, signal)
    assert _has_full_safety_stamp(p)
    p = adaptive_signal_router.classify_route_state({**route, **signal})
    assert _has_full_safety_stamp(p)
    _assert_no_execution_anywhere(p)
    p = adaptive_signal_router.summarize_routes([{**route, **signal}])
    assert _has_full_safety_stamp(p)


def test_signal_reactor_orchestrator_safety_stamped_and_no_execution():
    cluster = [
        {"source_name": "A", "direction": 1, "intensity": 0.5, "reliability": 0.7,
         "evidence_strength": 0.5, "independence_score": 0.6, "durability_score": 0.5},
    ]
    p = signal_reactor.evaluate_signal_reactor(
        cluster,
        operator_state={"process_compliance": 0.8, "journal_complete": True,
                        "sleep_quality": 0.7},
        event_context={"event_type": "earnings", "event_severity": 0.5},
    )
    assert _has_full_safety_stamp(p)
    _assert_no_execution_anywhere(p)
    assert p["allowed_actions"]["broker_execute"] is False


def test_module_source_has_no_forbidden_execution_tokens():
    for module in NEW_MODULES:
        source = Path(module.__file__).read_text(encoding="utf-8")
        for token in FORBIDDEN_RUNTIME_TOKENS:
            assert token not in source, f"{module.__name__} contains {token!r}"


def test_module_source_has_no_banned_theatrical_runtime_names():
    for module in NEW_MODULES:
        source = Path(module.__file__).read_text(encoding="utf-8")
        for token in BANNED_THEATRICAL_TOKENS:
            assert token not in source, f"{module.__name__} contains {token!r}"


def test_orchestrator_components_carry_safety_when_present():
    p = signal_reactor.evaluate_signal_reactor(
        [{"source_name": "A", "direction": 1, "intensity": 0.5}],
        operator_state={"process_compliance": 0.8, "journal_complete": True},
    )
    for name, comp in p["component_outputs"].items():
        if isinstance(comp, dict) and "safety" in comp:
            assert comp["safety"]["advisory_status"] == "ADVISORY_ONLY", name
            assert comp["safety"]["execution_gate"] == "LOCKED", name
            assert comp["safety"]["broker_api_called"] is False, name
            assert comp["safety"]["execution_permission"] is False, name
            assert comp["safety"]["can_execute"] is False, name
            assert comp["safety"]["ai_execution_count"] == 0, name
