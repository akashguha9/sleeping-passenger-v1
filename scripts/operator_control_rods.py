"""Operator control rods + meltdown risk — pure, deterministic, advisory-only.

Engineering translation of the reflection's "control rods", "meltdown
risk", and "psychedelic perception" metaphors. The module separates
operator heat from evidence and never authorizes broker execution.

The metaphor is translated, never inserted. Runtime names describe what
the code measures: operator emotional heat, process compliance,
containment capacity, and the difference between perception and action.

Note: this module is intentionally distinct from
``scripts/operator_control.py``, which manages manual work-block and
operator-state logging. The two do not import each other.

Safety contract on every public output

    output["safety"]["advisory_status"]     == "ADVISORY_ONLY"
    output["safety"]["execution_gate"]      == "LOCKED"
    output["safety"]["broker_api_called"]   is False
    output["safety"]["ai_execution_count"]  == 0
    output["safety"]["execution_permission"] is False
    output["safety"]["can_execute"]         is False

Public API

    compute_operator_heat(operator_state)               -> dict
    compute_containment_capacity(signal_context)        -> dict
    classify_meltdown_risk(operator_state, signal_ctx)  -> dict
    insert_control_rods(operator_state, signal_ctx)     -> dict
"""

from __future__ import annotations

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
}

CONTROL_ROD_REASONS: tuple[str, ...] = (
    "altered_perception",
    "emotional_heat",
    "process_non_compliance",
    "leverage_temptation",
    "recent_loss_revenge",
    "sleep_deficit",
    "thesis_attachment",
    "external_chaos",
)

ALLOWED_ACTION_KEYS: tuple[str, ...] = (
    "observe",
    "journal",
    "review_later",
    "manual_trade_logging_allowed",
    "broker_execute",
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


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "altered"}
    if isinstance(value, (int, float)):
        return value != 0
    return False


def compute_operator_heat(operator_state: Any) -> dict[str, Any]:
    data = operator_state if isinstance(operator_state, dict) else {}
    fomo = _clamp(data.get("fomo") or data.get("fomo_level"))
    revenge = _clamp(data.get("revenge") or data.get("revenge_level"))
    anger = _clamp(data.get("anger") or data.get("anger_level"))
    euphoria = _clamp(data.get("euphoria") or data.get("euphoria_level"))
    urgency = _clamp(data.get("urgency") or data.get("urgency_level"))
    leverage_temptation = _clamp(data.get("leverage_temptation"))
    thesis_attachment = _clamp(data.get("thesis_attachment"))
    panic = _clamp(data.get("panic") or data.get("panic_level"))
    overconfidence = _clamp(data.get("overconfidence") or data.get("overconfidence_level"))
    emotional_state_raw = _text(data.get("emotional_state"))

    emotional_state_score = 0.0
    if emotional_state_raw in {"fomo", "revenge", "anger", "euphoria", "panic"}:
        emotional_state_score = 0.6

    emotion_max = max(fomo, revenge, anger, panic, euphoria)
    emotion_avg = (fomo + revenge + anger + panic + euphoria) / 5.0
    raw_heat = (
        0.35 * emotion_max
        + 0.15 * emotion_avg
        + 0.15 * urgency
        + 0.15 * leverage_temptation
        + 0.10 * thesis_attachment
        + 0.05 * overconfidence
        + 0.05 * emotional_state_score
    )
    operator_heat_score = _clamp(raw_heat)

    return _stamp({
        "operator_heat_score": round(operator_heat_score, 4),
        "fomo": round(fomo, 4),
        "revenge": round(revenge, 4),
        "anger": round(anger, 4),
        "urgency": round(urgency, 4),
        "leverage_temptation": round(leverage_temptation, 4),
        "thesis_attachment": round(thesis_attachment, 4),
        "panic": round(panic, 4),
        "overconfidence": round(overconfidence, 4),
        "emotional_state": emotional_state_raw,
    })


def compute_containment_capacity(signal_context: Any) -> dict[str, Any]:
    data = signal_context if isinstance(signal_context, dict) else {}
    containment_strength = _clamp(data.get("containment_strength"), 0.0, 1.0)
    volatility = _clamp(data.get("volatility"))
    chaos_risk = _clamp(data.get("chaos_risk"))
    contradiction = _clamp(data.get("contradiction") or data.get("contradiction_score"))
    narrative_charge = _clamp(data.get("narrative_charge"))
    signal_heat = _clamp(data.get("signal_heat"))

    reaction_heat = _clamp(
        0.4 * signal_heat
        + 0.25 * volatility
        + 0.2 * narrative_charge
        + 0.15 * chaos_risk
    )

    containment_capacity = _clamp(
        0.6 * containment_strength
        - 0.2 * contradiction
        - 0.2 * chaos_risk
        + 0.4 * (1.0 - volatility)
    )

    return _stamp({
        "reaction_heat": round(reaction_heat, 4),
        "containment_capacity": round(containment_capacity, 4),
        "containment_strength": round(containment_strength, 4),
        "volatility": round(volatility, 4),
        "chaos_risk": round(chaos_risk, 4),
    })


def insert_control_rods(operator_state: Any, signal_context: Any | None = None) -> dict[str, Any]:
    data = operator_state if isinstance(operator_state, dict) else {}
    heat_payload = compute_operator_heat(data)
    containment_payload = compute_containment_capacity(signal_context)

    sleep_quality = _clamp(data.get("sleep_quality"))
    process_compliance = _clamp(data.get("process_compliance"))
    journal_complete = _bool(data.get("journal_complete"))
    cooldown_minutes = _clamp(data.get("cooldown_minutes_since_last_trade") or 0.0, 0.0, 1e9)
    perception_mode = _text(data.get("perception_mode"))
    substance_or_altered = _bool(data.get("substance_or_altered_state_flag"))
    recent_loss = _bool(data.get("recent_loss"))

    rods: list[str] = []

    if substance_or_altered or perception_mode in {"altered", "psychedelic", "intoxicated", "fatigued_severe"}:
        rods.append("altered_perception")
    if heat_payload["operator_heat_score"] >= 0.6:
        rods.append("emotional_heat")
    if process_compliance < 0.5 or not journal_complete:
        rods.append("process_non_compliance")
    if heat_payload["leverage_temptation"] >= 0.6:
        rods.append("leverage_temptation")
    if recent_loss and heat_payload["revenge"] >= 0.4:
        rods.append("recent_loss_revenge")
    if sleep_quality > 0.0 and sleep_quality < 0.4:
        rods.append("sleep_deficit")
    if heat_payload["thesis_attachment"] >= 0.7:
        rods.append("thesis_attachment")
    if containment_payload["chaos_risk"] >= 0.7 and containment_payload["containment_capacity"] < 0.4:
        rods.append("external_chaos")

    # control rod insertion = fraction of rods relative to a sane upper bound
    rod_insertion = _clamp(len(rods) / max(len(CONTROL_ROD_REASONS), 1))

    raw_reactivity = heat_payload["operator_heat_score"]
    reaction_after_control = _clamp(raw_reactivity * (1.0 - rod_insertion))

    return _stamp({
        "control_rod_insertion": round(rod_insertion, 4),
        "control_rods_inserted": rods,
        "reaction_after_control": round(reaction_after_control, 4),
        "raw_reactivity": round(raw_reactivity, 4),
    })


def classify_meltdown_risk(
    operator_state: Any,
    signal_context: Any | None = None,
) -> dict[str, Any]:
    data = operator_state if isinstance(operator_state, dict) else {}
    heat_payload = compute_operator_heat(data)
    containment_payload = compute_containment_capacity(signal_context)
    rods_payload = insert_control_rods(data, signal_context)

    process_compliance = _clamp(data.get("process_compliance"))
    sleep_quality = _clamp(data.get("sleep_quality"))
    impulse_control = _clamp(data.get("impulse_control"), 0.0, 1.0)
    patience = _clamp(data.get("patience"), 0.0, 1.0)
    risk_discipline = _clamp(data.get("risk_discipline"), 0.0, 1.0)
    emotional_neutrality = 1.0 - heat_payload["operator_heat_score"]

    operator_clearance_score = _clamp(
        (
            (0.5 + 0.5 * sleep_quality)
            * (0.5 + 0.5 * emotional_neutrality)
            * (0.5 + 0.5 * (patience if patience > 0 else 0.5))
            * (0.5 + 0.5 * (risk_discipline if risk_discipline > 0 else 0.5))
            * (0.5 + 0.5 * (impulse_control if impulse_control > 0 else 0.5))
            * (0.25 + 0.75 * process_compliance)
        )
    )

    operator_distortion_score = _clamp(
        0.5 * heat_payload["operator_heat_score"]
        + 0.3 * (1.0 - process_compliance)
        + 0.2 * (1.0 - sleep_quality if sleep_quality > 0 else 0.0)
    )
    perception_clearance = _clamp(1.0 - operator_distortion_score)

    reaction_heat = containment_payload["reaction_heat"]
    containment_capacity = containment_payload["containment_capacity"]
    meltdown_risk_score = _clamp(reaction_heat - containment_capacity + 0.5 * heat_payload["operator_heat_score"])

    rods = rods_payload["control_rods_inserted"]
    gallardo_block = bool(
        "altered_perception" in rods
        or "emotional_heat" in rods
        or "process_non_compliance" in rods
        or "recent_loss_revenge" in rods
        or meltdown_risk_score >= 0.7
    )

    allowed_actions: dict[str, bool] = {
        "observe": True,
        "journal": True,
        "review_later": True,
        "manual_trade_logging_allowed": (not gallardo_block) and process_compliance >= 0.5,
        "broker_execute": False,
    }

    return _stamp({
        "operator_heat_score": heat_payload["operator_heat_score"],
        "operator_clearance_score": round(operator_clearance_score, 4),
        "operator_distortion_score": round(operator_distortion_score, 4),
        "perception_clearance": round(perception_clearance, 4),
        "containment_capacity": containment_payload["containment_capacity"],
        "reaction_heat": containment_payload["reaction_heat"],
        "meltdown_risk_score": round(meltdown_risk_score, 4),
        "control_rod_insertion": rods_payload["control_rod_insertion"],
        "control_rods_inserted": rods,
        "gallardo_block": gallardo_block,
        "allowed_actions": allowed_actions,
        "operator_action": "human_review_only" if gallardo_block else "watch",
    })


__all__ = [
    "ADVISORY_STATUS",
    "EXECUTION_GATE_LOCKED",
    "SAFETY_STAMPS",
    "CONTROL_ROD_REASONS",
    "ALLOWED_ACTION_KEYS",
    "compute_operator_heat",
    "compute_containment_capacity",
    "insert_control_rods",
    "classify_meltdown_risk",
]
