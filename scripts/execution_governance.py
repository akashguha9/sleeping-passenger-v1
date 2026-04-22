from __future__ import annotations

from typing import Any

try:
    from scripts.runtime_common import EXECUTION_GOVERNANCE_CONFIG_PATH, load_json_file
except ModuleNotFoundError:
    from runtime_common import EXECUTION_GOVERNANCE_CONFIG_PATH, load_json_file


DEFAULT_CONFIG: dict[str, Any] = {
    "fpeg": {
        "pass_threshold": 0.8,
        "review_threshold": 0.6,
        "weights": {
            "why_this_move": 0.25,
            "trigger": 0.20,
            "invalidation": 0.25,
            "regime": 0.15,
            "why_now": 0.15,
        },
        "critical_requirements": [
            "why_this_move",
            "trigger",
            "invalidation",
            "regime",
            "why_now",
        ],
    },
    "cvg": {
        "pass_threshold": 0.7,
        "review_threshold": 0.55,
        "weights": {
            "formal_learning_score": 0.25,
            "applied_experience_score": 0.25,
            "logged_accuracy_score": 0.25,
            "setup_familiarity_score": 0.15,
            "review_discipline_score": 0.10,
        },
        "critical_fields": [
            "formal_learning_score",
            "applied_experience_score",
            "logged_accuracy_score",
        ],
    },
    "slg": {
        "pass_threshold": 0.7,
        "review_threshold": 0.55,
        "weights": {
            "structured_learning_score": 0.35,
            "disciplined_practice_score": 0.25,
            "multi_domain_training_score": 0.20,
            "review_evidence_score": 0.20,
        },
        "critical_fields": [
            "structured_learning_score",
            "disciplined_practice_score",
        ],
    },
    "interaction": {
        "good_threshold": 0.75,
        "watch_threshold": 0.55,
    },
    "automation_readiness": {
        "minimum_reconciled_trades": 20,
        "minimum_override_samples": 10,
        "minimum_interaction_quality": 0.7,
        "minimum_fpeg_pass_rate": 0.8,
    },
}

ACTION_AGGRESSION_ORDER = {
    "NO_EXECUTION": 0,
    "BLOCK_ENTRY": 1,
    "MONITOR": 2,
    "HOLD": 3,
    "REDUCE": 4,
    "REVIEW_FOR_ENTRY": 5,
    "EXIT_NOW": 6,
    "CLOSE_POSITION": 6,
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_execution_governance_config(path=None) -> dict[str, Any]:
    payload = load_json_file(path or EXECUTION_GOVERNANCE_CONFIG_PATH, default={})
    if not isinstance(payload, dict):
        payload = {}
    return _deep_merge(DEFAULT_CONFIG, payload)


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def _coerce_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _truthy_text(value: Any) -> bool:
    return bool(str(value or "").strip())


def _reason_text(action_row: dict[str, Any]) -> str:
    reasons = action_row.get("reasons", [])
    if not isinstance(reasons, list):
        return ""
    return " | ".join(str(item) for item in reasons if str(item).strip()).lower()


def _keyword_hit(text: str, *keywords: str) -> bool:
    lowered = str(text or "").lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def evaluate_first_principles_gate(
    action_row: dict[str, Any],
    signal_row: dict[str, Any] | None = None,
    position_row: dict[str, Any] | None = None,
    signal_refinery_row: dict[str, Any] | None = None,
    runtime_state: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    active = config or load_execution_governance_config()
    fpeg_config = active["fpeg"]
    reason_text = _reason_text(action_row)
    refinement_row = signal_refinery_row if isinstance(signal_refinery_row, dict) else {}
    position = position_row if isinstance(position_row, dict) else {}
    state = runtime_state if isinstance(runtime_state, dict) else {}

    why_this_move = _truthy_text(action_row.get("why_this_move")) or bool(reason_text)
    trigger = _truthy_text(action_row.get("trigger")) or bool(refinement_row) or bool(position) or _keyword_hit(
        reason_text,
        "reached",
        "breached",
        "trigger",
        "ready",
        "blocked",
    )
    invalidation = _truthy_text(action_row.get("invalidation")) or bool(
        position.get("stop_loss") is not None
        or position.get("take_profit") is not None
        or _keyword_hit(reason_text, "stop_loss", "stop", "risk", "invalid", "fail")
    )
    regime = _truthy_text(action_row.get("regime")) or bool(
        action_row.get("policy_state")
        or action_row.get("active_blockers")
        or state.get("execution_policy")
        or refinement_row.get("crowding_state")
    )
    why_now = _truthy_text(action_row.get("why_now")) or bool(
        refinement_row.get("validation_state")
        or refinement_row.get("time_to_valid_signal_hours") is not None
        or position
        or _keyword_hit(reason_text, "now", "ready", "reached", "breached", "active")
    )

    checklist = {
        "why_this_move": why_this_move,
        "trigger": trigger,
        "invalidation": invalidation,
        "regime": regime,
        "why_now": why_now,
    }
    weights = fpeg_config["weights"]
    score = 0.0
    for key, present in checklist.items():
        score += float(weights.get(key, 0.0)) * (1.0 if present else 0.0)
    missing = [key for key, present in checklist.items() if not present]
    critical = [
        item
        for item in fpeg_config.get("critical_requirements", [])
        if item in missing
    ]
    score = round(_clamp(score), 4)
    if score >= float(fpeg_config["pass_threshold"]) and not critical:
        state_name = "pass"
        disposition = "review_eligible_pending_human_approval"
    elif score >= float(fpeg_config["review_threshold"]) and why_this_move and trigger and regime:
        state_name = "review_only"
        disposition = "manual_checklist_required"
    else:
        state_name = "insufficient_reasoning"
        disposition = "block_execution_pending_reasoning"

    return {
        "schema_version": "FPEG_V1",
        "fpeg_score": score,
        "fpeg_state": state_name,
        "recommended_disposition": disposition,
        "suggestion_only": True,
        "human_execution_required": True,
        "checklist": checklist,
        "missing_requirements": missing,
        "critical_missing_requirements": critical,
        "note": (
            "No explanation, no trade: the system remains suggestion-only until "
            "first-principles reasoning is explicit and human approval is present."
        ),
    }


def _weighted_profile_score(
    profile: dict[str, Any] | None,
    weights: dict[str, float],
) -> tuple[float | None, list[str], list[str]]:
    data = profile if isinstance(profile, dict) else {}
    if not data:
        return None, list(weights), list(weights)
    weighted_sum = 0.0
    weight_used = 0.0
    present_fields: list[str] = []
    missing_fields: list[str] = []
    for field, weight in weights.items():
        value = _coerce_float(data.get(field))
        if value is None:
            missing_fields.append(field)
            continue
        weighted_sum += _clamp(value) * float(weight)
        weight_used += float(weight)
        present_fields.append(field)
    if weight_used <= 0:
        return None, [], list(weights)
    return round(weighted_sum / weight_used, 4), present_fields, missing_fields


def evaluate_competence_validation(
    operator_profile: dict[str, Any] | None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    active = config or load_execution_governance_config()
    cvg_config = active["cvg"]
    score, present_fields, missing_fields = _weighted_profile_score(
        operator_profile,
        cvg_config["weights"],
    )
    if score is None:
        state_name = "insufficient_profile"
        eligible = False
    elif any(field in missing_fields for field in cvg_config.get("critical_fields", [])):
        state_name = "incomplete_profile"
        eligible = False
    elif score >= float(cvg_config["pass_threshold"]):
        state_name = "pass"
        eligible = True
    elif score >= float(cvg_config["review_threshold"]):
        state_name = "review_only"
        eligible = False
    else:
        state_name = "fail"
        eligible = False
    return {
        "schema_version": "CVG_V1",
        "configured": bool(operator_profile),
        "cvg_score": score,
        "cvg_state": state_name,
        "eligible": eligible,
        "present_fields": present_fields,
        "missing_fields": missing_fields,
        "note": (
            "Competence is treated as formal learning + applied experience + "
            "logged accuracy + setup familiarity, not credentials alone."
        ),
    }


def evaluate_structured_learning_gate(
    operator_profile: dict[str, Any] | None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    active = config or load_execution_governance_config()
    slg_config = active["slg"]
    score, present_fields, missing_fields = _weighted_profile_score(
        operator_profile,
        slg_config["weights"],
    )
    if score is None:
        state_name = "insufficient_profile"
        eligible = False
    elif any(field in missing_fields for field in slg_config.get("critical_fields", [])):
        state_name = "incomplete_profile"
        eligible = False
    elif score >= float(slg_config["pass_threshold"]):
        state_name = "pass"
        eligible = True
    elif score >= float(slg_config["review_threshold"]):
        state_name = "review_only"
        eligible = False
    else:
        state_name = "fail"
        eligible = False
    return {
        "schema_version": "SLG_V1",
        "configured": bool(operator_profile),
        "slg_score": score,
        "slg_state": state_name,
        "eligible": eligible,
        "present_fields": present_fields,
        "missing_fields": missing_fields,
        "note": (
            "Structured learning remains a gate: if no trained basis is logged, "
            "execution cannot be treated as justified expertise."
        ),
    }


def evaluate_model_quality(
    action_row: dict[str, Any],
    signal_refinery_row: dict[str, Any] | None = None,
    fpeg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    refinement = signal_refinery_row if isinstance(signal_refinery_row, dict) else {}
    reasons = action_row.get("reasons", [])
    explanation_quality = 1.0 if isinstance(reasons, list) and reasons else 0.0
    traceability = 1.0 if _truthy_text(action_row.get("ticker")) else 0.0
    validation_support = 1.0 if _truthy_text(refinement.get("validation_state")) else 0.5
    regime_support = 1.0 if _truthy_text(action_row.get("policy_state")) else 0.0
    gate_bonus = 0.0
    if isinstance(fpeg, dict) and fpeg.get("fpeg_state") == "pass":
        gate_bonus = 0.1
    score = round(
        _clamp(
            (0.35 * explanation_quality)
            + (0.25 * traceability)
            + (0.25 * validation_support)
            + (0.15 * regime_support)
            + gate_bonus
        ),
        4,
    )
    if score >= 0.8:
        state_name = "clear"
    elif score >= 0.6:
        state_name = "adequate"
    else:
        state_name = "weak"
    return {
        "schema_version": "MODEL_QUALITY_V1",
        "model_quality_score": score,
        "model_quality_state": state_name,
        "components": {
            "explanation_quality": explanation_quality,
            "traceability": traceability,
            "validation_support": validation_support,
            "regime_support": regime_support,
        },
    }


def classify_override(
    suggested_action: str,
    override_action: str,
) -> dict[str, Any]:
    suggested = str(suggested_action or "UNKNOWN").upper()
    override = str(override_action or "UNKNOWN").upper()
    if override == suggested:
        return {
            "override_classification": "follow_model",
            "risk_direction": "neutral",
        }
    if suggested == "REVIEW_FOR_ENTRY" and override in {"MONITOR", "BLOCK_ENTRY", "NO_EXECUTION", "HOLD"}:
        return {
            "override_classification": "defer_execution",
            "risk_direction": "conservative",
        }
    if suggested in {"HOLD", "MONITOR", "REVIEW_FOR_ENTRY"} and override in {"REDUCE", "EXIT_NOW"}:
        return {
            "override_classification": "tighten_risk",
            "risk_direction": "conservative",
        }
    if override == "REVIEW_FOR_ENTRY" and suggested in {"MONITOR", "BLOCK_ENTRY", "HOLD"}:
        return {
            "override_classification": "escalate_risk",
            "risk_direction": "aggressive",
        }
    if override == "EXIT_NOW":
        return {
            "override_classification": "manual_exit",
            "risk_direction": "conservative",
        }
    return {
        "override_classification": "manual_reframe",
        "risk_direction": "neutral",
    }


def evaluate_operator_quality(
    override_payload: dict[str, Any],
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _ = config
    first_principles_fields = [
        "why_this_move",
        "trigger",
        "invalidation",
        "regime",
        "why_now",
    ]
    completeness = sum(
        1.0 for field in first_principles_fields if _truthy_text(override_payload.get(field))
    ) / len(first_principles_fields)
    emotion_text = str(override_payload.get("emotional_state") or "").strip().lower()
    if emotion_text in {"heated", "reactive", "angry", "provoked"}:
        discipline = 0.2
    elif emotion_text:
        discipline = 0.7
    else:
        discipline = 1.0
    classification = str(override_payload.get("override_classification") or "").lower()
    if classification in {"tighten_risk", "defer_execution", "follow_model"}:
        override_discipline = 1.0
    elif classification == "manual_reframe":
        override_discipline = 0.6
    elif classification == "escalate_risk":
        override_discipline = 0.25
    else:
        override_discipline = 0.4
    evidence_source = str(override_payload.get("confidence_source") or "").strip().lower()
    if evidence_source in {"internal_evidence", "logged_pattern", "paper_history"}:
        evidence_quality = 1.0
    elif evidence_source:
        evidence_quality = 0.6
    else:
        evidence_quality = 0.4
    score = round(
        _clamp(
            (0.45 * completeness)
            + (0.20 * discipline)
            + (0.20 * override_discipline)
            + (0.15 * evidence_quality)
        ),
        4,
    )
    if score >= 0.8:
        state_name = "disciplined"
    elif score >= 0.6:
        state_name = "watch"
    else:
        state_name = "weak"
    return {
        "schema_version": "OPERATOR_QUALITY_V1",
        "operator_quality_score": score,
        "operator_quality_state": state_name,
        "first_principles_completeness": round(completeness, 4),
        "emotional_discipline_score": round(discipline, 4),
        "override_discipline_score": round(override_discipline, 4),
        "evidence_quality_score": round(evidence_quality, 4),
    }


def evaluate_interaction_quality(
    override_payload: dict[str, Any],
    operator_quality: dict[str, Any],
    model_quality: dict[str, Any],
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    active = config or load_execution_governance_config()
    interaction_config = active["interaction"]
    classification = str(override_payload.get("override_classification") or "").lower()
    if classification in {"tighten_risk", "follow_model", "defer_execution"}:
        alignment = 1.0
    elif classification == "manual_reframe":
        alignment = 0.6
    elif classification == "escalate_risk":
        alignment = 0.2
    else:
        alignment = 0.4
    score = round(
        _clamp(
            (0.40 * float(operator_quality.get("operator_quality_score") or 0.0))
            + (0.35 * float(model_quality.get("model_quality_score") or 0.0))
            + (0.25 * alignment)
        ),
        4,
    )
    if score >= float(interaction_config["good_threshold"]):
        state_name = "good"
    elif score >= float(interaction_config["watch_threshold"]):
        state_name = "watch"
    else:
        state_name = "poor"
    return {
        "schema_version": "INTERACTION_QUALITY_V1",
        "interaction_quality_score": score,
        "interaction_quality_state": state_name,
        "alignment_score": round(alignment, 4),
    }


def evaluate_automation_readiness(
    gate_summary: dict[str, Any] | None = None,
    override_summary: dict[str, Any] | None = None,
    reconciliation_summary: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    active = config or load_execution_governance_config()
    readiness_config = active["automation_readiness"]
    gate = gate_summary if isinstance(gate_summary, dict) else {}
    override = override_summary if isinstance(override_summary, dict) else {}
    reconciliation = (
        reconciliation_summary if isinstance(reconciliation_summary, dict) else {}
    )
    blocking_reasons: list[str] = []
    if float(gate.get("fpeg_pass_rate") or 0.0) < float(
        readiness_config["minimum_fpeg_pass_rate"]
    ):
        blocking_reasons.append("fpeg_pass_rate_below_minimum")
    if int(override.get("total_override_count") or 0) < int(
        readiness_config["minimum_override_samples"]
    ):
        blocking_reasons.append("override_sample_too_small")
    if float(override.get("average_interaction_quality") or 0.0) < float(
        readiness_config["minimum_interaction_quality"]
    ):
        blocking_reasons.append("interaction_quality_below_minimum")
    if int(reconciliation.get("total_closed_paper_trades") or 0) < int(
        readiness_config["minimum_reconciled_trades"]
    ):
        blocking_reasons.append("paper_outcome_sample_too_small")
    blocking_reasons.append("manual_approval_required_by_design")
    return {
        "schema_version": "AUTOMATION_READINESS_V1",
        "current_stage": "suggestion_only",
        "eligible_for_limited_delegation": False,
        "blocking_reasons": blocking_reasons,
        "required_evidence": [
            "human_approval_coverage",
            "higher_fpeg_pass_rate",
            "override_value_evidence",
            "larger_reconciled_paper_sample",
        ],
        "note": (
            "This is a conservative stub. The MVP remains suggestion-only and "
            "human-executed regardless of local architecture maturity."
        ),
    }


def assess_action_governance(
    action_row: dict[str, Any],
    signal_row: dict[str, Any] | None = None,
    position_row: dict[str, Any] | None = None,
    signal_refinery_row: dict[str, Any] | None = None,
    operator_profile: dict[str, Any] | None = None,
    runtime_state: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    active = config or load_execution_governance_config()
    fpeg = evaluate_first_principles_gate(
        action_row=action_row,
        signal_row=signal_row,
        position_row=position_row,
        signal_refinery_row=signal_refinery_row,
        runtime_state=runtime_state,
        config=active,
    )
    cvg = evaluate_competence_validation(operator_profile, config=active)
    slg = evaluate_structured_learning_gate(operator_profile, config=active)
    model_quality = evaluate_model_quality(
        action_row=action_row,
        signal_refinery_row=signal_refinery_row,
        fpeg=fpeg,
    )
    return {
        "schema_version": "EXECUTION_GOVERNANCE_V1",
        "suggestion_only": True,
        "delegation_permitted": False,
        "fpeg": fpeg,
        "cvg": cvg,
        "slg": slg,
        "model_quality": model_quality,
        "human_execution_required": True,
        "approval_state": "PENDING_HUMAN_APPROVAL",
        "note": (
            "The model may rank and explain, but execution remains manual. "
            "Governance fields are advisory unless a human approves."
        ),
    }


def summarize_action_governance(action_rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(action_rows)
    fpeg_counts: dict[str, int] = {}
    cvg_states: dict[str, int] = {}
    slg_states: dict[str, int] = {}
    fpeg_scores: list[float] = []
    for row in action_rows:
        governance = row.get("execution_governance", {})
        if not isinstance(governance, dict):
            continue
        fpeg = governance.get("fpeg", {})
        cvg = governance.get("cvg", {})
        slg = governance.get("slg", {})
        fpeg_state = str(fpeg.get("fpeg_state") or "unknown")
        fpeg_counts[fpeg_state] = fpeg_counts.get(fpeg_state, 0) + 1
        cvg_state = str(cvg.get("cvg_state") or "unknown")
        cvg_states[cvg_state] = cvg_states.get(cvg_state, 0) + 1
        slg_state = str(slg.get("slg_state") or "unknown")
        slg_states[slg_state] = slg_states.get(slg_state, 0) + 1
        score = _coerce_float(fpeg.get("fpeg_score"))
        if score is not None:
            fpeg_scores.append(score)
    return {
        "total_action_count": total,
        "fpeg_state_counts": fpeg_counts,
        "average_fpeg_score": round(sum(fpeg_scores) / len(fpeg_scores), 4)
        if fpeg_scores
        else None,
        "fpeg_pass_rate": round(fpeg_counts.get("pass", 0) / total, 4) if total else 0.0,
        "human_execution_required_count": total,
        "cvg_state_counts": cvg_states,
        "slg_state_counts": slg_states,
    }
