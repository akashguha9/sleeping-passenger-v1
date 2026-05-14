"""Signal reactor — pure, deterministic, advisory-only orchestrator.

Combines the new diagnostic modules into a single advisory payload.
This module is the composite "criticality monitor" that the doctrine
in ``docs/SIGNAL_REACTOR_MODEL.md`` describes. It never executes
trades, never calls a broker, never produces an order payload.

Public API

    evaluate_signal_reactor(signal_or_cluster, operator_state=None,
                             event_context=None, system_state=None,
                             waste_state=None, now=None)
        -> dict with structured advisory output

Optional CLI

    python scripts/signal_reactor.py --example --json

Decision rules (in order of precedence)

    1. operator gallardo_block          -> OPERATOR_CONTROL_RODS
    2. high echo risk                   -> ECHO_SUPPRESSED
    3. high waste / stale               -> WASTE_DECAY
    4. fission_event + low clarity      -> FISSION_MAP_ONLY
    5. valid fusion + decent containment -> FUSION_REVIEW_CANDIDATE
    6. meltdown_risk high               -> HOT_CONTAINMENT_REQUIRED
    7. moderate clean evidence          -> WARM_WATCH
    8. otherwise                        -> COLD_OBSERVE

The orchestrator tolerates missing components: every helper is wrapped
in a defensive try/except so that a single subcomponent failure
downgrades the reactor to ``insufficient_data`` rather than crashing
the caller.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

ADVISORY_STATUS = "ADVISORY_ONLY"
EXECUTION_GATE_LOCKED = "LOCKED"

SAFETY_STAMPS: dict[str, Any] = {
    "advisory_status": ADVISORY_STATUS,
    "execution_gate": EXECUTION_GATE_LOCKED,
    "broker_api_called": False,
    "ai_execution_count": 0,
    "execution_permission": False,
    "can_execute": False,
    "broker_order_id": "NONE",
    "human_review_required": True,
}

REACTOR_STATES: tuple[str, ...] = (
    "COLD_OBSERVE",
    "WARM_WATCH",
    "FUSION_REVIEW_CANDIDATE",
    "FISSION_MAP_ONLY",
    "HOT_CONTAINMENT_REQUIRED",
    "WASTE_DECAY",
    "ECHO_SUPPRESSED",
    "OPERATOR_CONTROL_RODS",
)

RECOMMENDATIONS: tuple[str, ...] = (
    "observe",
    "watch",
    "review_later",
    "review_candidate",
    "map_branches",
    "quarantine",
    "decay_archive",
    "human_review_only",
    "cool_down",
)


def _stamp(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    out["safety"] = dict(SAFETY_STAMPS)
    out.setdefault("advisory_status", ADVISORY_STATUS)
    out.setdefault("execution_gate", EXECUTION_GATE_LOCKED)
    return out


def _clamp(value: Any, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return lo
    if x != x:
        return lo
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def _as_cluster(signal_or_cluster: Any) -> list[dict[str, Any]]:
    if isinstance(signal_or_cluster, list):
        return [s for s in signal_or_cluster if isinstance(s, dict)]
    if isinstance(signal_or_cluster, dict):
        return [signal_or_cluster]
    return []


def _safe_call(fn, *args, default: dict[str, Any] | None = None, **kwargs) -> dict[str, Any]:
    try:
        result = fn(*args, **kwargs)
    except Exception:
        return default or {}
    if not isinstance(result, dict):
        return default or {}
    return result


def evaluate_signal_reactor(
    signal_or_cluster: Any,
    operator_state: dict[str, Any] | None = None,
    event_context: dict[str, Any] | None = None,
    system_state: dict[str, Any] | None = None,
    waste_state: dict[str, Any] | None = None,
    *,
    now: Any = None,
) -> dict[str, Any]:
    cluster = _as_cluster(signal_or_cluster)
    operator_state = operator_state if isinstance(operator_state, dict) else {}
    event_context = event_context if isinstance(event_context, dict) else {}
    system_state = system_state if isinstance(system_state, dict) else {}
    waste_state = waste_state if isinstance(waste_state, dict) else {}

    components: dict[str, dict[str, Any]] = {}

    try:
        try:
            from scripts.signal_field_geometry import (
                classify_field_geometry,
                classify_signal_trace,
            )
        except ModuleNotFoundError:
            from signal_field_geometry import (
                classify_field_geometry,
                classify_signal_trace,
            )
        components["field_geometry"] = _safe_call(classify_field_geometry, cluster)
        if cluster:
            components["lead_trace"] = _safe_call(classify_signal_trace, cluster[0])
    except Exception:
        components["field_geometry"] = {}

    try:
        try:
            from scripts.echo_risk_engine import classify_confirmation_quality
        except ModuleNotFoundError:
            from echo_risk_engine import classify_confirmation_quality
        components["echo_quality"] = _safe_call(classify_confirmation_quality, cluster)
    except Exception:
        components["echo_quality"] = {}

    try:
        try:
            from scripts.signal_decay_waste import (
                classify_signal_waste,
                summarize_waste_load,
            )
        except ModuleNotFoundError:
            from signal_decay_waste import (
                classify_signal_waste,
                summarize_waste_load,
            )
        if cluster:
            components["lead_waste"] = _safe_call(classify_signal_waste, cluster[0], now=now)
        if waste_state:
            components["waste_load"] = _safe_call(summarize_waste_load, waste_state, now=now)
        else:
            components["waste_load"] = _safe_call(summarize_waste_load, cluster, now=now)
    except Exception:
        components["waste_load"] = {}

    try:
        try:
            from scripts.fission_branch_mapper import map_fission_branches
        except ModuleNotFoundError:
            from fission_branch_mapper import map_fission_branches
        if event_context:
            components["fission"] = _safe_call(map_fission_branches, event_context)
        else:
            components["fission"] = {}
    except Exception:
        components["fission"] = {}

    try:
        try:
            from scripts.fusion_thesis_engine import classify_fusion_candidate
        except ModuleNotFoundError:
            from fusion_thesis_engine import classify_fusion_candidate
        components["fusion"] = _safe_call(classify_fusion_candidate, cluster)
    except Exception:
        components["fusion"] = {}

    try:
        try:
            from scripts.operator_control_rods import classify_meltdown_risk
        except ModuleNotFoundError:
            from operator_control_rods import classify_meltdown_risk
        components["operator"] = _safe_call(
            classify_meltdown_risk,
            operator_state,
            event_context or (cluster[0] if cluster else {}),
        )
    except Exception:
        components["operator"] = {}

    try:
        try:
            from scripts.adaptive_signal_router import classify_route_state
        except ModuleNotFoundError:
            from adaptive_signal_router import classify_route_state
        if cluster:
            route_input = dict(cluster[0])
            if system_state:
                route_input.setdefault("legal_risk", system_state.get("legal_risk"))
                route_input.setdefault("liquidity_risk", system_state.get("liquidity_risk"))
                route_input.setdefault("operator_risk", system_state.get("operator_risk"))
                route_input.setdefault("source_risk", system_state.get("source_risk"))
            components["route"] = _safe_call(classify_route_state, route_input)
        else:
            components["route"] = {}
    except Exception:
        components["route"] = {}

    field_geometry = components.get("field_geometry") or {}
    echo_quality = components.get("echo_quality") or {}
    waste_load = components.get("waste_load") or {}
    fission = components.get("fission") or {}
    fusion = components.get("fusion") or {}
    operator = components.get("operator") or {}
    route = components.get("route") or {}
    lead_trace = components.get("lead_trace") or {}
    lead_waste = components.get("lead_waste") or {}

    signal_energy = _clamp(
        lead_trace.get("signal_energy")
        or field_geometry.get("phase_alignment_score")
        or 0.0
    )
    evidence_density = _clamp(fusion.get("evidence_density"))
    echo_risk_score = _clamp(echo_quality.get("echo_risk_score"))
    waste_load_score = _clamp(waste_load.get("waste_load_score"))
    fusion_thesis_strength = _clamp(fusion.get("fusion_thesis_strength"))
    fusion_validity = fusion.get("fusion_validity", "insufficient_data")
    fission_branch_clarity = _clamp(fission.get("branch_clarity_score"))
    fission_event = bool(fission.get("fission_event"))
    meltdown_risk_score = _clamp(operator.get("meltdown_risk_score"))
    containment_strength = _clamp(operator.get("containment_capacity"))
    operator_clearance = _clamp(operator.get("operator_clearance_score"))
    operator_heat_score = _clamp(operator.get("operator_heat_score"))
    control_rod_insertion = _clamp(operator.get("control_rod_insertion"))
    gallardo_block = bool(operator.get("gallardo_block"))
    confirmation_quality = echo_quality.get("confirmation_quality", "insufficient_data")
    stale_signal = bool(lead_waste.get("stale_signal"))
    decay_factor = _clamp(lead_waste.get("decay_factor"), 0.0, 1.0)

    criticality_control = _clamp(
        0.5 * containment_strength
        + 0.5 * (1.0 - control_rod_insertion)
    )

    fusion_validity_score = {
        "valid_fusion": 1.0,
        "weak_fusion": 0.4,
        "echo_not_fusion": 0.1,
        "overheated_uncontained": 0.1,
        "insufficient_data": 0.0,
    }.get(fusion_validity, 0.0)

    decision_grade_energy = _clamp(
        signal_energy
        * (0.5 + 0.5 * evidence_density)
        * (0.5 + 0.5 * criticality_control)
        * (0.5 + 0.5 * fusion_validity_score)
        * (0.5 + 0.5 * (fission_branch_clarity if fission_event else 1.0))
        * (0.5 + 0.5 * containment_strength)
        * (0.5 + 0.5 * operator_clearance)
        - 0.3 * waste_load_score
        - 0.3 * meltdown_risk_score
        - 0.3 * echo_risk_score
    )

    # Decision rules in precedence order
    vetoes: list[str] = []
    reasons: list[str] = []

    if gallardo_block or operator_heat_score >= 0.7:
        reactor_state = "OPERATOR_CONTROL_RODS"
        recommendation = "human_review_only"
        vetoes.append("operator_gallardo_block")
    elif echo_risk_score >= 0.6 or confirmation_quality == "echo_amplification":
        reactor_state = "ECHO_SUPPRESSED"
        recommendation = "decay_archive"
        vetoes.append("echo_dominated")
    elif waste_load_score >= 0.5 or stale_signal:
        reactor_state = "WASTE_DECAY"
        recommendation = "decay_archive"
        reasons.append("waste_or_stale")
    elif fission_event and fission_branch_clarity < 0.4:
        reactor_state = "FISSION_MAP_ONLY"
        recommendation = "map_branches"
        reasons.append("fission_with_low_branch_clarity")
    elif (
        fusion_validity == "valid_fusion"
        and containment_strength >= 0.4
        and meltdown_risk_score < 0.6
    ):
        reactor_state = "FUSION_REVIEW_CANDIDATE"
        recommendation = "review_candidate"
        reasons.append("valid_fusion_with_containment")
    elif meltdown_risk_score >= 0.6:
        reactor_state = "HOT_CONTAINMENT_REQUIRED"
        recommendation = "cool_down"
        vetoes.append("hot_containment_required")
    elif (
        signal_energy >= 0.3
        or evidence_density >= 0.3
        or decision_grade_energy >= 0.25
    ):
        reactor_state = "WARM_WATCH"
        recommendation = "watch"
        reasons.append("moderate_clean_evidence")
    else:
        reactor_state = "COLD_OBSERVE"
        recommendation = "observe"
        reasons.append("insufficient_evidence")

    # Allowed actions — broker_execute is always False.
    operator_actions = operator.get("allowed_actions", {}) or {}
    manual_trade_logging_allowed = bool(
        operator_actions.get("manual_trade_logging_allowed", False)
    ) and reactor_state not in {
        "OPERATOR_CONTROL_RODS",
        "ECHO_SUPPRESSED",
        "HOT_CONTAINMENT_REQUIRED",
        "FISSION_MAP_ONLY",
    }
    allowed_actions = {
        "observe": True,
        "journal": True,
        "review_later": reactor_state in {
            "WARM_WATCH",
            "FUSION_REVIEW_CANDIDATE",
            "WASTE_DECAY",
            "FISSION_MAP_ONLY",
        },
        "manual_trade_logging_allowed": manual_trade_logging_allowed,
        "broker_execute": False,
    }

    return _stamp({
        "signal_reactor_state": reactor_state,
        "decision_grade_energy": round(decision_grade_energy, 4),
        "signal_energy": round(signal_energy, 4),
        "evidence_density": round(evidence_density, 4),
        "echo_risk_score": round(echo_risk_score, 4),
        "confirmation_quality": confirmation_quality,
        "waste_load_score": round(waste_load_score, 4),
        "stale_signal": stale_signal,
        "decay_factor": round(decay_factor, 4),
        "fusion_thesis_strength": round(fusion_thesis_strength, 4),
        "fusion_validity": fusion_validity,
        "fission_event": fission_event,
        "fission_branch_clarity": round(fission_branch_clarity, 4),
        "meltdown_risk_score": round(meltdown_risk_score, 4),
        "operator_clearance_score": round(operator_clearance, 4),
        "operator_heat_score": round(operator_heat_score, 4),
        "containment_strength": round(containment_strength, 4),
        "control_rod_insertion": round(control_rod_insertion, 4),
        "gallardo_block": gallardo_block,
        "criticality_control": round(criticality_control, 4),
        "field_geometry_label": field_geometry.get("field_geometry_label", "INSUFFICIENT_DATA"),
        "phase_alignment_score": _clamp(field_geometry.get("phase_alignment_score")),
        "route_state": route.get("route_state"),
        "route_confidence": _clamp(route.get("route_confidence")),
        "recommendation": recommendation,
        "operator_action": recommendation,
        "vetoes": vetoes,
        "reasons": reasons,
        "allowed_actions": allowed_actions,
        "component_outputs": components,
    })


def _example_payload() -> dict[str, Any]:
    cluster = [
        {
            "source_name": "Reuters", "source_family": "news",
            "direction": 1, "intensity": 0.55, "reliability": 0.85,
            "freshness_score": 0.8, "narrative_intensity": 0.4,
            "market_confirmation": 0.4, "independence_score": 0.85,
            "evidence_strength": 0.55, "echo_risk_score": 0.1,
            "durability_score": 0.6, "signal_type": "news",
            "age_hours": 4.0, "initial_strength": 0.6,
        },
        {
            "source_name": "Bloomberg", "source_family": "news",
            "direction": 1, "intensity": 0.5, "reliability": 0.8,
            "freshness_score": 0.7, "narrative_intensity": 0.4,
            "market_confirmation": 0.5, "independence_score": 0.8,
            "evidence_strength": 0.55, "echo_risk_score": 0.1,
            "durability_score": 0.6, "signal_type": "news",
            "age_hours": 5.0, "initial_strength": 0.6,
        },
    ]
    operator = {
        "fomo": 0.1, "urgency": 0.2, "process_compliance": 0.8,
        "journal_complete": True, "sleep_quality": 0.7,
    }
    return evaluate_signal_reactor(
        cluster,
        operator_state=operator,
        event_context={
            "event_type": "earnings", "event_severity": 0.4,
            "market_sensitivity": 0.5, "uncertainty": 0.4,
            "source_reliability": 0.8,
        },
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Signal reactor advisory CLI.")
    parser.add_argument("--example", action="store_true",
                        help="Emit an example reactor output.")
    parser.add_argument("--json", action="store_true",
                        help="Emit JSON (default).")
    args = parser.parse_args(argv)

    if args.example:
        payload = _example_payload()
    else:
        payload = _stamp({
            "signal_reactor_state": "COLD_OBSERVE",
            "recommendation": "observe",
            "note": "no input provided — use --example to see a worked example",
        })

    print(json.dumps(payload, indent=2, default=str))
    return 0


__all__ = [
    "ADVISORY_STATUS",
    "EXECUTION_GATE_LOCKED",
    "SAFETY_STAMPS",
    "REACTOR_STATES",
    "RECOMMENDATIONS",
    "evaluate_signal_reactor",
]


if __name__ == "__main__":
    raise SystemExit(main())
