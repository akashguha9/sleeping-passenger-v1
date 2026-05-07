from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

try:
    from scripts.runtime_common import (
        FALSE_NEGATIVE_CASINO_MONOPOLY_REPORT_PATH,
        build_runtime_state_from_scm_report_payload,
        get_source_mode,
        repo_relative,
        write_json_atomic,
    )
    from scripts.signal_conversion_monitor import build_signal_conversion_report
except ModuleNotFoundError:
    from runtime_common import (  # type: ignore[no-redef]
        FALSE_NEGATIVE_CASINO_MONOPOLY_REPORT_PATH,
        build_runtime_state_from_scm_report_payload,
        get_source_mode,
        repo_relative,
        write_json_atomic,
    )
    from signal_conversion_monitor import build_signal_conversion_report  # type: ignore[no-redef]


EPSILON = 1e-9

STRUCTURAL_STABILIZER_WEIGHTS = {
    "coverage": 0.20,
    "availability": 0.20,
    "continuity": 0.20,
    "low_error_rate": 0.20,
    "friction_reduction": 0.20,
}

ROLE_REQUIREMENTS = {
    "STABILIZER": {
        "continuity": 1.0,
        "discipline": 0.9,
        "coverage": 0.8,
        "friction_reduction": 0.9,
        "stability": 0.8,
    },
    "SCOUT": {
        "novelty": 0.9,
        "asymmetry": 1.0,
        "timing": 0.8,
        "attention": 0.7,
        "truth": 0.5,
    },
    "FINISHER": {
        "validation": 1.0,
        "execution": 1.0,
        "follow_through": 0.9,
        "discipline": 0.8,
        "truth": 0.7,
    },
    "SENTINEL": {
        "discipline": 1.0,
        "rule_awareness": 1.0,
        "truth": 0.8,
        "stability": 0.8,
        "coverage": 0.6,
    },
}

CURRENT_ROLE_MAP = {
    "WATCHLIST": "SCOUT",
    "PROMOTABLE_WATCHLIST": "SCOUT",
    "CLEAN_READY_PENDING_TRIGGER": "FINISHER",
    "CLEAN_ENTRY_ELIGIBLE": "FINISHER",
    "EXECUTED_CHAOS": "SCOUT",
    "CHAOS_ENTRY": "SCOUT",
    "VALIDATED": "FINISHER",
    "NEEDS_CONFIRMATION": "STABILIZER",
}


def _clamp(value: Any, minimum: float = 0.0, maximum: float = 1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return minimum
    return max(minimum, min(maximum, number))


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(mean(values))


def _round(value: float) -> float:
    return round(_clamp(value), 4)


def _safe_upper(value: Any, default: str = "UNKNOWN") -> str:
    text = str(value or "").strip()
    return text.upper() if text else default


def _soft_state(score: float, low: float, high: float, labels: tuple[str, str, str]) -> str:
    if score < low:
        return labels[0]
    if score < high:
        return labels[1]
    return labels[2]


def compute_structural_stabilizer(
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = metrics if isinstance(metrics, dict) else {}
    weighted = {
        name: _clamp(source.get(name))
        for name in STRUCTURAL_STABILIZER_WEIGHTS
    }
    score = sum(weighted[name] * weight for name, weight in STRUCTURAL_STABILIZER_WEIGHTS.items())
    state = "UNKNOWN"
    if weighted:
        if score >= 0.82 and weighted["friction_reduction"] >= 0.8 and weighted["continuity"] >= 0.75:
            state = "GLUE_ASSET"
        elif score >= 0.72:
            state = "HIGH_STRUCTURAL_VALUE"
        elif score >= 0.48:
            state = "MODERATE_STRUCTURAL_VALUE"
        else:
            state = "LOW_STRUCTURAL_VALUE"
    return {
        "visible_output": _round(_clamp(source.get("visible_output"))),
        "structural_stabilizer_inputs": weighted,
        "structural_stabilizer_score": round(score, 4),
        "structural_stabilizer_state": state,
        "system_value_score": round(_clamp(_clamp(source.get("visible_output")) + score), 4),
        "formula": (
            "StabilizerScore = 0.20*coverage + 0.20*availability + 0.20*continuity + "
            "0.20*low_error_rate + 0.20*friction_reduction"
        ),
    }


def _role_dot(capability_vector: dict[str, float], requirement: dict[str, float]) -> float:
    numerator = 0.0
    denominator = 0.0
    for key, weight in requirement.items():
        numerator += _clamp(capability_vector.get(key)) * weight
        denominator += weight
    return _clamp(numerator / max(denominator, EPSILON))


def compute_role_capability_fit(
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    capability_vector = {
        "coverage": _clamp(source.get("coverage")),
        "continuity": _clamp(source.get("continuity")),
        "friction_reduction": _clamp(source.get("friction_reduction")),
        "validation": _clamp(source.get("validation")),
        "execution": _clamp(source.get("execution")),
        "follow_through": _clamp(source.get("follow_through")),
        "discipline": _clamp(source.get("discipline")),
        "truth": _clamp(source.get("truth")),
        "stability": _clamp(source.get("stability")),
        "novelty": _clamp(source.get("novelty")),
        "asymmetry": _clamp(source.get("asymmetry")),
        "timing": _clamp(source.get("timing")),
        "attention": _clamp(source.get("attention")),
        "rule_awareness": _clamp(source.get("rule_awareness")),
    }
    ranked = sorted(
        (
            {
                "role": role,
                "fit_score": round(_role_dot(capability_vector, requirement), 4),
            }
            for role, requirement in ROLE_REQUIREMENTS.items()
        ),
        key=lambda item: (-item["fit_score"], item["role"]),
    )
    current_role_name = CURRENT_ROLE_MAP.get(_safe_upper(source.get("current_role")), "STABILIZER")
    current_role_fit = next(
        (item["fit_score"] for item in ranked if item["role"] == current_role_name),
        0.0,
    )
    best_role = ranked[0]["role"] if ranked else "UNKNOWN"
    best_score = ranked[0]["fit_score"] if ranked else 0.0
    capability_strength = _mean([value for value in capability_vector.values()])
    role_misfit_risk = _clamp(capability_strength - current_role_fit)
    if current_role_fit >= 0.72:
        state = "GOOD_FIT"
    elif current_role_fit >= 0.5:
        state = "PARTIAL_FIT"
    elif role_misfit_risk >= 0.3:
        state = "SEVERE_MISCAST"
    else:
        state = "MISCAST"
    return {
        "role_capability_fit_score": round(current_role_fit, 4),
        "current_role_fit_state": state,
        "current_role": current_role_name,
        "best_role": best_role,
        "best_role_fit_score": round(best_score, 4),
        "role_misfit_risk": round(role_misfit_risk, 4),
        "capability_strength": round(capability_strength, 4),
        "alternative_role_candidates": ranked[:3],
        "formula": "RoleMisfitRisk = CapabilityStrength - CurrentRoleFit",
    }


def compute_false_negative_risk(
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    components = {
        "role_misfit": _clamp(source.get("role_misfit")),
        "context_misfit": _clamp(source.get("context_misfit")),
        "metric_blindness": _clamp(source.get("metric_blindness")),
        "structural_value_unmeasured": _clamp(source.get("structural_value_unmeasured")),
        "asymmetric_upside": _clamp(source.get("asymmetric_upside")),
    }
    score = _mean(list(components.values()))
    if score >= 0.72:
        state = "LIKELY_FALSE_NEGATIVE"
    elif score >= 0.55:
        state = "RECHECK_REQUIRED"
    elif score >= 0.30:
        state = "WATCH_REJECTION"
    else:
        state = "NO_FN_RISK"
    review_path = (
        "ContextRecheck -> Reclassify"
        if state in {"RECHECK_REQUIRED", "LIKELY_FALSE_NEGATIVE"}
        else "ConfirmReject"
    )
    return {
        "false_negative_components": components,
        "false_negative_risk": round(score, 4),
        "false_negative_state": state,
        "rejected_signal_review_path": review_path,
        "formula": (
            "FalseNegativeRisk = role_misfit + context_misfit + metric_blindness + "
            "structural_value_unmeasured + asymmetric_upside"
        ),
    }


def compute_blind_spot_risk(
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    detected = max(int(source.get("detected_signals", 0) or 0), 0)
    possible = max(int(source.get("possible_signals", 0) or 0), 0)
    if possible <= 0:
        return {
            "detection_coverage": 0.0,
            "blind_spot_risk": 0.0,
            "blind_spot_state": "UNKNOWN",
            "formula": "BlindSpotRisk = 1 - (DetectedSignals / PossibleSignals)",
        }
    coverage = _clamp(detected / max(possible, 1))
    risk = _clamp(1.0 - coverage)
    return {
        "detection_coverage": round(coverage, 4),
        "blind_spot_risk": round(risk, 4),
        "blind_spot_state": _soft_state(
            risk,
            0.25,
            0.55,
            ("LOW_BLIND_SPOT_RISK", "MODERATE_BLIND_SPOT_RISK", "HIGH_BLIND_SPOT_RISK"),
        ),
        "formula": "BlindSpotRisk = 1 - DetectionCoverage",
    }


def compute_double_blind_guard(
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    confidence = _clamp(source.get("confidence"))
    evidence_quality = _clamp(source.get("evidence_quality"))
    misperception = _clamp(source.get("misperception", 1.0 - evidence_quality))
    overconfidence = _clamp(confidence - evidence_quality)
    risk = _clamp(misperception * max(overconfidence, 0.0) + overconfidence * 0.5)
    if confidence > 0.75 and evidence_quality < 0.50:
        state = "DANGEROUS_CONFIDENCE"
    elif risk >= 0.55:
        state = "HIGH_OVERCONFIDENCE"
    elif risk >= 0.20:
        state = "MILD_OVERCONFIDENCE"
    else:
        state = "CALIBRATED"
    return {
        "double_blind_risk": round(risk, 4),
        "double_blind_state": state,
        "overconfidence_risk": round(overconfidence, 4),
        "formula": "DoubleBlind = Misperception * Overconfidence",
    }


def compute_decision_quality_splitter(
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    decision_quality = _clamp(source.get("decision_quality_score"))
    outcome = _clamp(source.get("outcome_score"))
    divergence = round(abs(decision_quality - outcome), 4)
    if decision_quality >= 0.6 and outcome >= 0.55:
        state = "GOOD_PROCESS_GOOD_OUTCOME"
    elif decision_quality >= 0.6:
        state = "GOOD_PROCESS_BAD_OUTCOME"
    elif outcome >= 0.55:
        state = "BAD_PROCESS_GOOD_OUTCOME"
    else:
        state = "BAD_PROCESS_BAD_OUTCOME"
    return {
        "decision_quality_score": round(decision_quality, 4),
        "outcome_score": round(outcome, 4),
        "process_outcome_divergence": divergence,
        "decision_quality_state": state,
        "variance_explanation": source.get(
            "variance_explanation",
            "Result = DecisionQuality + Variance; short-term outcome does not override process quality.",
        ),
    }


def compute_casino_role_classifier(
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    information_advantage = _clamp(source.get("information_advantage"))
    capital_strength = _clamp(source.get("capital_strength"))
    timing_advantage = _clamp(source.get("timing_advantage"))
    discipline = _clamp(source.get("discipline"))
    rule_awareness = _clamp(source.get("rule_awareness"))
    food_chain_rank = _clamp(
        0.25 * information_advantage
        + 0.20 * capital_strength
        + 0.20 * timing_advantage
        + 0.20 * discipline
        + 0.15 * rule_awareness
    )
    edge_availability = _clamp(source.get("edge_availability"))
    predator_density = _clamp(source.get("predator_density"))
    table_quality = _clamp((edge_availability - predator_density + 1.0) / 2.0)
    if food_chain_rank >= 0.82 and rule_awareness >= 0.7:
        role = "CASINO"
    elif food_chain_rank >= 0.66 and discipline >= 0.65:
        role = "CASINO_AWARE_OPERATOR"
    elif information_advantage >= 0.58 and discipline >= 0.5:
        role = "TABLE_READER"
    elif food_chain_rank >= 0.4:
        role = "PLAYER"
    elif food_chain_rank >= 0.22:
        role = "CHIPS"
    elif food_chain_rank > 0.0:
        role = "PREY"
    else:
        role = "UNKNOWN"
    return {
        "casino_role": role,
        "food_chain_rank": round(food_chain_rank, 4),
        "table_quality_score": round(table_quality, 4),
        "predator_density": round(predator_density, 4),
        "edge_availability": round(edge_availability, 4),
        "formula": (
            "FoodChainRank = 0.25*information_advantage + 0.20*capital_strength + "
            "0.20*timing_advantage + 0.20*discipline + 0.15*rule_awareness"
        ),
    }


def compute_table_context(
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    volatility = _clamp(source.get("volatility"))
    liquidity = _clamp(source.get("liquidity"))
    crowding = _clamp(source.get("crowding"))
    participant_quality = _clamp(source.get("participant_quality"))
    deception_risk = _clamp(source.get("deception_risk"))
    regime_stability = _clamp(source.get("regime_stability"))
    chaos_level = _clamp(source.get("chaos_level"))
    policy_restriction = _clamp(source.get("policy_restriction"))
    prior_false_break_count = max(int(source.get("prior_false_break_count", 0) or 0), 0)
    false_break_penalty = _clamp(prior_false_break_count / 5.0)
    score = _clamp(
        0.16 * (1.0 - volatility)
        + 0.16 * liquidity
        + 0.10 * (1.0 - crowding)
        + 0.12 * participant_quality
        + 0.14 * (1.0 - deception_risk)
        + 0.12 * regime_stability
        + 0.10 * (1.0 - chaos_level)
        + 0.05 * (1.0 - policy_restriction)
        + 0.05 * (1.0 - false_break_penalty)
    )
    if chaos_level >= 0.75 or policy_restriction >= 0.75 or deception_risk >= 0.8:
        state = "NO_PLAY_TABLE"
    elif score < 0.32:
        state = "DANGEROUS_TABLE"
    elif score < 0.55:
        state = "PLAYABLE_TABLE"
    else:
        state = "FAVORABLE_TABLE"
    if score == 0.0 and prior_false_break_count == 0 and liquidity == 0.0 and volatility == 0.0:
        state = "UNKNOWN"
    return {
        "table_context_score": round(score, 4),
        "table_context_state": state,
        "prior_false_break_count": prior_false_break_count,
    }


def compute_monopoly_cluster(
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    asset_count = max(int(source.get("asset_count", 0) or 0), 0)
    synergy = _clamp(source.get("synergy"))
    control = _clamp(source.get("control"))
    persistence = _clamp(source.get("persistence"))
    cashflow_potential = _clamp(source.get("cashflow_potential"))
    asset_count_factor = _clamp(asset_count / 5.0)
    cluster_power = _clamp(
        asset_count_factor * synergy * control * persistence * cashflow_potential * 3.0
    )
    if asset_count <= 1 or cluster_power < 0.15:
        cluster_state = "NO_CLUSTER"
    elif cluster_power < 0.35:
        cluster_state = "WEAK_CLUSTER"
    elif cluster_power < 0.58:
        cluster_state = "EMERGING_CLUSTER"
    elif cluster_power < 0.78:
        cluster_state = "CONTROLLED_CLUSTER"
    else:
        cluster_state = "DOMINANT_CLUSTER"
    validation = _clamp(source.get("validation"))
    durability = _clamp(source.get("durability"))
    execution_survivability = _clamp(source.get("execution_survivability"))
    scale_permission = _clamp(
        validation * control * cashflow_potential * durability * execution_survivability * 2.5
    )
    if scale_permission >= 0.75:
        scale_state = "FULL_SCALE_ALLOWED"
    elif scale_permission >= 0.48:
        scale_state = "CONTROLLED_SCALE"
    elif scale_permission >= 0.22:
        scale_state = "PROBE_SCALE"
    else:
        scale_state = "NO_SCALE"
    return {
        "asset_cluster_score": round(cluster_power, 4),
        "cluster_control_state": cluster_state,
        "scale_permission_score": round(scale_permission, 4),
        "scale_permission_state": scale_state,
        "formula": (
            "ClusterPower = asset_count * synergy * control * persistence * cashflow_potential; "
            "ScalePermission = validation * control * cashflow_potential * durability * execution_survivability"
        ),
    }


def compute_false_break(
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    persistence = _clamp(source.get("persistence"))
    follow_through = _clamp(source.get("follow_through"))
    stability = _clamp(source.get("stability"))
    participation_quality = _clamp(source.get("participation_quality"))
    contradiction_resistance = _clamp(source.get("contradiction_resistance"))
    initial_signal_strength = _clamp(source.get("initial_signal_strength"))
    deception_risk = _clamp(source.get("deception_risk"))
    chaos = _clamp(source.get("chaos"))
    break_quality = _clamp(
        _mean(
            [
                persistence,
                follow_through,
                stability,
                participation_quality,
                contradiction_resistance,
            ]
        )
    )
    false_break_risk = _clamp(
        (
            initial_signal_strength
            - follow_through
            + deception_risk
            + chaos
            + (1.0 - participation_quality)
        )
        / 4.0
    )
    if initial_signal_strength < 0.2:
        state = "NO_BREAK"
    elif follow_through >= 0.7 and break_quality >= 0.68 and false_break_risk < 0.35:
        state = "CONFIRMED_BREAK"
    elif follow_through < 0.3 and initial_signal_strength >= 0.45:
        state = "FALSE_BREAK_RISK"
    elif follow_through < 0.2 and persistence < 0.2:
        state = "FAILED_BREAK"
    else:
        state = "UNCONFIRMED_BREAK"
    return {
        "false_break_risk": round(false_break_risk, 4),
        "break_quality_score": round(break_quality, 4),
        "false_break_state": state,
    }


def compute_bluff_truth_estimator(
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    aggression = _clamp(source.get("aggression"))
    foundation = _clamp(source.get("foundation"))
    follow_through = _clamp(source.get("follow_through"))
    incentive_to_mislead = _clamp(source.get("incentive_to_mislead"))
    information_asymmetry = _clamp(source.get("information_asymmetry"))
    declared_observed_gap = _clamp(source.get("declared_observed_gap"))
    observed_true_gap_estimate = _clamp(source.get("observed_true_gap_estimate"))
    bluff_risk = _clamp(
        (
            aggression
            - foundation
            - follow_through
            + incentive_to_mislead
            + information_asymmetry
            + declared_observed_gap
        )
        / 3.0
    )
    truth_probability = _clamp(
        foundation * 0.35
        + follow_through * 0.30
        + (1.0 - declared_observed_gap) * 0.20
        + (1.0 - observed_true_gap_estimate) * 0.15
        - bluff_risk * 0.35
    )
    if bluff_risk >= 0.72:
        truth_state = "LIKELY_BLUFF"
    elif bluff_risk >= 0.50:
        truth_state = "POSSIBLE_BLUFF"
    elif truth_probability >= 0.65:
        truth_state = "LIKELY_TRUE"
    elif truth_probability > 0.0:
        truth_state = "UNCERTAIN"
    else:
        truth_state = "UNKNOWN"
    return {
        "bluff_risk": round(bluff_risk, 4),
        "truth_probability": round(truth_probability, 4),
        "declared_observed_gap": round(declared_observed_gap, 4),
        "observed_true_gap_estimate": round(observed_true_gap_estimate, 4),
        "truth_state": truth_state,
    }


def compute_joker_shock(
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    surprise = _clamp(source.get("surprise"))
    impact = _clamp(source.get("impact"))
    rule_change = _clamp(source.get("rule_change"))
    shock_score = _clamp(surprise * impact * rule_change * 1.5)
    joker_event = bool(source.get("joker_event_detected", False)) or shock_score >= 0.82
    prior_model_validity = _clamp(1.0 - shock_score)
    if joker_event and shock_score >= 0.92:
        shock_state = "MODEL_RESET_REQUIRED"
    elif joker_event:
        shock_state = "JOKER_EVENT"
    elif shock_score >= 0.55:
        shock_state = "MAJOR_SHOCK"
    elif shock_score >= 0.25:
        shock_state = "MINOR_SHOCK"
    else:
        shock_state = "NO_SHOCK"
    return {
        "joker_event_detected": joker_event,
        "shock_score": round(shock_score, 4),
        "prior_model_validity": round(prior_model_validity, 4),
        "shock_state": shock_state,
    }


def compute_jail_mode(
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    reasons: list[str] = []
    chaos = _clamp(source.get("chaos"))
    overexposure = _clamp(source.get("overexposure"))
    edge_compression = _clamp(source.get("edge_compression"))
    model_uncertainty = _clamp(source.get("model_uncertainty"))
    policy_restriction = bool(source.get("policy_restriction"))
    high_false_break_risk = bool(source.get("high_false_break_risk"))
    dangerous_table = bool(source.get("dangerous_table"))
    dangerous_confidence = bool(source.get("dangerous_confidence"))
    hard_veto = bool(source.get("hard_veto"))
    if chaos > 0.65:
        reasons.append("CHAOS")
    if overexposure > 0.65:
        reasons.append("OVEREXPOSURE")
    if edge_compression > 0.65:
        reasons.append("EDGE_COMPRESSION")
    if model_uncertainty > 0.6:
        reasons.append("MODEL_UNCERTAINTY")
    if policy_restriction:
        reasons.append("POLICY_RESTRICTION")
    if high_false_break_risk:
        reasons.append("HIGH_FALSE_BREAK_RISK")
    if dangerous_table:
        reasons.append("DANGEROUS_TABLE")
    if dangerous_confidence:
        reasons.append("DANGEROUS_CONFIDENCE")
    if hard_veto:
        reasons.append("HARD_VETO")
    jail_mode_active = len(reasons) > 0
    if hard_veto or policy_restriction or chaos > 0.82:
        state = "FORCED_RESTRAINT"
    elif dangerous_table or high_false_break_risk or dangerous_confidence:
        state = "NO_NEW_RISK"
    elif jail_mode_active:
        state = "PROTECT_EXISTING_EDGE"
    else:
        state = "OFF"
    if not jail_mode_active and max(chaos, model_uncertainty, edge_compression) >= 0.45:
        state = "WATCH"
    optimal_inactivity = round(
        _clamp(_clamp(source.get("existing_cashflow")) - _clamp(source.get("movement_risk"))),
        4,
    )
    return {
        "jail_mode_active": jail_mode_active,
        "jail_mode_reason": reasons,
        "jail_mode_state": state,
        "optimal_inactivity_score": optimal_inactivity,
    }


def compute_reentry_state(
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    state_before = _safe_upper(source.get("state_before"), "JAIL")
    jail_mode_active = bool(source.get("jail_mode_active"))
    policy_clear = bool(source.get("policy_clear"))
    signal_strength = _clamp(source.get("signal_strength"))
    stability = _clamp(source.get("stability"))
    probe_success = _clamp(source.get("probe_success"))
    follow_through = _clamp(source.get("follow_through"))
    chaos = _clamp(source.get("chaos"))
    deception_risk = _clamp(source.get("deception_risk"))
    false_break_risk = _clamp(source.get("false_break_risk"))
    reentry_score = _clamp(
        (
            signal_strength
            + stability
            + probe_success
            + follow_through
            - chaos
            - deception_risk
            - false_break_risk
        )
        / 4.0
    )
    if jail_mode_active or not policy_clear:
        state = "STAY_IN_JAIL"
        state_after = "JAIL"
    elif state_before == "JAIL" and reentry_score >= 0.78 and probe_success >= 0.8:
        state = "CONFIRMATION_REQUIRED"
        state_after = "CONFIRM"
    elif reentry_score >= 0.72 and follow_through >= 0.68 and false_break_risk < 0.35:
        state = "DEPLOY_ALLOWED"
        state_after = "DEPLOY"
    elif reentry_score >= 0.45:
        state = "PROBE_ALLOWED"
        state_after = "PROBE"
    else:
        state = "STAY_IN_JAIL"
        state_after = "JAIL"
    if state_before == "JAIL" and state_after == "DEPLOY":
        state = "CONFIRMATION_REQUIRED"
        state_after = "CONFIRM"
    return {
        "reentry_score": round(reentry_score, 4),
        "reentry_state": state,
        "reentry_state_before": state_before,
        "reentry_state_after": state_after,
    }


def compute_forced_transition(
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    state_before = _safe_upper(source.get("state_before"), "UNKNOWN")
    if bool(source.get("joker_event_detected")):
        command = "JOKER"
        reason = "Shock override triggered model reset."
        state_after = "ISLERO"
    elif bool(source.get("policy_restriction")):
        command = "SKIP"
        reason = "Policy restriction denies new risk."
        state_after = "JAIL"
    elif _clamp(source.get("chaos")) >= 0.75:
        command = "DRAW"
        reason = "Chaos increased exposure cost."
        state_after = "DIABLO"
    elif bool(source.get("rule_override")):
        command = "WILD"
        reason = "Rule regime changed."
        state_after = "ISLERO"
    elif bool(source.get("trend_reversal")):
        command = "REVERSE"
        reason = "Trend/regime reversal detected."
        state_after = "MIURA"
    else:
        command = "NONE"
        reason = "No forced transition."
        state_after = state_before
    return {
        "forced_transition_command": command,
        "forced_transition_reason": reason,
        "state_before": state_before,
        "state_after": state_after,
    }


def compute_bull_state(
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    policy_veto = bool(source.get("policy_veto"))
    chaos = _clamp(source.get("chaos"))
    joker = bool(source.get("joker_event_detected"))
    jail_mode_active = bool(source.get("jail_mode_active"))
    validation = _clamp(source.get("validation"))
    durability = _clamp(source.get("durability"))
    execution_survivability = _clamp(source.get("execution_survivability"))
    momentum = _clamp(source.get("momentum"))
    novelty = _clamp(source.get("novelty"))
    policy_clear = bool(source.get("policy_clear"))
    actionable = bool(source.get("actionable"))
    previous = _safe_upper(source.get("previous_bull_state"), "UNKNOWN")
    if policy_veto:
        bull_state = "DIABLO" if chaos >= 0.75 else "JAIL"
        reason = "Policy veto outranks every downstream state."
    elif chaos >= 0.75:
        bull_state = "DIABLO"
        reason = "Chaos veto outranks momentum and novelty."
    elif joker:
        bull_state = "ISLERO"
        reason = "Joker shock reclassified the prior model."
    elif jail_mode_active:
        bull_state = "JAIL"
        reason = "Strategic restraint active."
    elif novelty >= 0.72 and validation < 0.5:
        bull_state = "MIURA"
        reason = "Raw novelty outruns validation."
    elif validation >= 0.72 and durability >= 0.72 and execution_survivability >= 0.68 and actionable:
        bull_state = "GALLARDO"
        reason = "Actionable signal with controlled execution path."
    elif validation >= 0.72 and durability >= 0.72 and execution_survivability >= 0.6:
        bull_state = "AVENTADOR"
        reason = "Validated, durable, and survivable."
    elif validation >= 0.68 and durability >= 0.68:
        bull_state = "MURCIELAGO"
        reason = "Signal survives durability stress."
    elif momentum >= 0.78 and validation >= 0.55 and chaos < 0.35 and policy_clear:
        bull_state = "HURACAN"
        reason = "Velocity fast-track remains inside rule guardrails."
    else:
        bull_state = "UNKNOWN"
        reason = "No archetype cleared."
    transition = f"{previous}->{bull_state}"
    return {
        "bull_state": bull_state,
        "bull_state_reason": reason,
        "bull_state_transition": transition,
        "previous_bull_state": previous,
        "transition_validity": bull_state != "UNKNOWN",
        "policy_veto_respected": (bull_state in {"JAIL", "DIABLO"}) if policy_veto else True,
    }


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def compute_number_theory_recurrence(
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    intervals = source.get("intervals")
    if not isinstance(intervals, list):
        timestamps = source.get("timestamps")
        parsed: list[datetime] = []
        if isinstance(timestamps, list):
            for item in timestamps:
                parsed_value = _parse_timestamp(item)
                if parsed_value is not None:
                    parsed.append(parsed_value)
        intervals = []
        for index in range(1, len(parsed)):
            delta = parsed[index] - parsed[index - 1]
            intervals.append(delta.total_seconds())
    cleaned = [max(float(item), 0.0) for item in intervals if isinstance(item, (int, float)) and float(item) > 0]
    if len(cleaned) < 4:
        return {
            "recurrence_score": 0.0,
            "cycle_strength": 0.0,
            "cycle_state": "INSUFFICIENT_DATA",
            "gcd_interval": None,
            "sample_size": len(cleaned),
        }
    rounded = [max(int(round(item)), 1) for item in cleaned]
    gcd_value = rounded[0]
    for item in rounded[1:]:
        gcd_value = math.gcd(gcd_value, item)
    residue_counts = Counter(item % max(gcd_value, 1) for item in rounded)
    modular_consistency = max(residue_counts.values()) / len(rounded)
    repeated_interval_ratio = max(Counter(rounded).values()) / len(rounded)
    average_interval = sum(cleaned) / len(cleaned)
    interval_variance = pstdev(cleaned) if len(cleaned) > 1 else 0.0
    coeff_variation = interval_variance / max(average_interval, EPSILON)
    low_interval_variance = _clamp(1.0 - coeff_variation)
    gcd_consistency = _clamp((gcd_value * repeated_interval_ratio) / max(average_interval, 1.0))
    cycle_strength = _clamp(
        0.35 * gcd_consistency
        + 0.25 * low_interval_variance
        + 0.20 * repeated_interval_ratio
        + 0.20 * modular_consistency
    )
    if cycle_strength >= 0.78:
        cycle_state = "STRONG_RECURRENCE"
    elif cycle_strength >= 0.55:
        cycle_state = "MODERATE_RECURRENCE"
    elif cycle_strength >= 0.28:
        cycle_state = "WEAK_RECURRENCE"
    else:
        cycle_state = "NO_RECURRENCE"
    return {
        "recurrence_score": round(cycle_strength, 4),
        "cycle_strength": round(cycle_strength, 4),
        "cycle_state": cycle_state,
        "gcd_interval": gcd_value,
        "coefficient_of_variation": round(coeff_variation, 4),
        "repeated_interval_ratio": round(repeated_interval_ratio, 4),
        "modular_consistency": round(modular_consistency, 4),
        "sample_size": len(cleaned),
    }


def compute_investable_signal_adjustment(
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    policy_veto = bool(source.get("policy_veto"))
    detection = _clamp(source.get("detection"))
    validation = _clamp(source.get("validation"))
    durability = _clamp(source.get("durability"))
    execution_survivability = _clamp(source.get("execution_survivability"))
    table_quality = _clamp(source.get("table_quality"))
    truth_probability = _clamp(source.get("truth_probability"))
    role_fit = _clamp(source.get("role_fit"))
    cluster_power = _clamp(source.get("cluster_power"))
    chaos_penalty = _clamp(source.get("chaos_penalty"))
    deception_penalty = _clamp(source.get("deception_penalty"))
    false_break_penalty = _clamp(source.get("false_break_penalty"))
    overconfidence_penalty = _clamp(source.get("overconfidence_penalty"))
    multiplicative = (
        detection
        * validation
        * durability
        * execution_survivability
        * table_quality
        * truth_probability
        * role_fit
        * cluster_power
        * 12.0
    )
    adjusted = _clamp(
        multiplicative
        - chaos_penalty
        - deception_penalty
        - false_break_penalty
        - overconfidence_penalty
    )
    if policy_veto:
        adjusted = 0.0
    return {
        "investable_signal_adjusted_score": round(adjusted, 4),
        "can_deploy_capital": False if policy_veto else adjusted >= 0.6,
        "allow_new_risk": False if policy_veto else adjusted >= 0.6,
        "formula": (
            "InvestableSignal = Detection * Validation * Durability * ExecutionSurvivability * "
            "TableQuality * TruthProbability * RoleFit * ClusterPower - ChaosPenalty - "
            "DeceptionPenalty - FalseBreakPenalty - OverconfidencePenalty"
        ),
    }


def _derive_recurrence_intervals_from_trend(trend_report: dict[str, Any] | None = None) -> list[float]:
    report = trend_report if isinstance(trend_report, dict) else {}
    snapshots = report.get("snapshots") or []
    if not isinstance(snapshots, list):
        return []
    timestamps: list[datetime] = []
    for row in snapshots:
        if not isinstance(row, dict):
            continue
        parsed = _parse_timestamp(row.get("timestamp"))
        if parsed is not None:
            timestamps.append(parsed)
    intervals: list[float] = []
    for index in range(1, len(timestamps)):
        intervals.append((timestamps[index] - timestamps[index - 1]).total_seconds())
    return intervals


def build_false_negative_casino_monopoly_report(
    *,
    runtime_state: dict[str, Any],
    signal_refinery_report: dict[str, Any],
    attention_proxy_report: dict[str, Any],
    action_report: dict[str, Any],
    trend_report: dict[str, Any] | None,
    reflection_context: dict[str, Any],
    narrative_filter_report: dict[str, Any],
    busquets_audit_report: dict[str, Any],
    execution_integrity_report: dict[str, Any],
    asset_durability_report: dict[str, Any],
    temporal_integrity: dict[str, Any],
    position_truth_summary: dict[str, Any],
    operator_control_report: dict[str, Any],
    output_path: Path | None = None,
    write_runtime: bool = False,
) -> dict[str, Any]:
    validation_row = reflection_context.get("validation_row", {})
    launch_row = reflection_context.get("launch_row", {})
    primary_packet = reflection_context.get("primary_packet", {})
    per_signal_rows = runtime_state.get("per_signal_attribution", [])
    signal_count = len(per_signal_rows) if isinstance(per_signal_rows, list) else 0
    watchlist_diag = runtime_state.get("watchlist_diagnostics", {})
    watchlist_count = int(watchlist_diag.get("watchlist_count", 0) or 0)
    promotable_count = int(watchlist_diag.get("promotable_watchlist_count", 0) or 0)
    possible_signals = max(
        signal_count,
        int(runtime_state.get("signal_summary", {}).get("signals_above_ce_threshold", 0) or 0),
        signal_count + max(promotable_count, 0),
    )

    structural = compute_structural_stabilizer(
        {
            "coverage": validation_row.get("cross_source_confirmation_score", 0.0),
            "availability": validation_row.get("source_quality_score", 0.0),
            "continuity": max(
                validation_row.get("first_order_score", 0.0),
                1.0 - float(validation_row.get("novelty_score", 0.0) or 0.0),
            ),
            "low_error_rate": 1.0 - float(narrative_filter_report.get("hallucination_risk", 0.0) or 0.0),
            "friction_reduction": validation_row.get("blocker_clearance_score", 0.0),
            "visible_output": validation_row.get("validation_score", 0.0),
        }
    )
    role_fit = compute_role_capability_fit(
        {
            "coverage": validation_row.get("cross_source_confirmation_score", 0.0),
            "continuity": validation_row.get("first_order_score", 0.0),
            "friction_reduction": validation_row.get("blocker_clearance_score", 0.0),
            "validation": validation_row.get("validation_score", 0.0),
            "execution": execution_integrity_report.get("execution_integrity_score", 0.0),
            "follow_through": launch_row.get("validation_score", validation_row.get("validation_score", 0.0)),
            "discipline": narrative_filter_report.get("operator_stability_score", 0.0),
            "truth": 1.0 - float(narrative_filter_report.get("hallucination_risk", 0.0) or 0.0),
            "stability": 1.0 - float(attention_proxy_report.get("narrative_heat_score", 0.0) or 0.0),
            "novelty": validation_row.get("novelty_score", 0.0),
            "asymmetry": validation_row.get("repricing_headroom_score", 0.0),
            "timing": validation_row.get("price_lead_score", 0.0),
            "attention": attention_proxy_report.get("attention_proxy_score", 0.0),
            "rule_awareness": 1.0 if busquets_audit_report.get("risk_clearance", False) else 0.3,
            "current_role": primary_packet.get("target_pre_entry_state")
            or primary_packet.get("source_pre_entry_state")
            or validation_row.get("validation_state"),
        }
    )
    blind_spot = compute_blind_spot_risk(
        {
            "detected_signals": signal_count,
            "possible_signals": max(possible_signals, signal_count + watchlist_count),
        }
    )
    double_blind = compute_double_blind_guard(
        {
            "confidence": reflection_context.get("narrative_confidence", 0.0),
            "evidence_quality": reflection_context.get("evidence_strength", 0.0),
            "misperception": blind_spot["blind_spot_risk"],
        }
    )
    decision_quality = compute_decision_quality_splitter(
        {
            "decision_quality_score": _mean(
                [
                    float(validation_row.get("validation_score", 0.0) or 0.0),
                    float(reflection_context.get("evidence_strength", 0.0) or 0.0),
                    float(execution_integrity_report.get("execution_integrity_score", 0.0) or 0.0),
                ]
            ),
            "outcome_score": moltbook_feedback_score(signal_refinery_report, runtime_state),
            "variance_explanation": (
                "Process quality is derived from validation, evidence, and execution integrity; "
                "outcome score reflects current feedback and realized follow-through."
            ),
        }
    )
    bluff_truth = compute_bluff_truth_estimator(
        {
            "aggression": attention_proxy_report.get("narrative_heat_score", 0.0),
            "foundation": reflection_context.get("evidence_strength", 0.0),
            "follow_through": validation_row.get("first_order_score", 0.0),
            "incentive_to_mislead": 1.0 - float(validation_row.get("source_quality_score", 0.0) or 0.0),
            "information_asymmetry": 1.0 - float(validation_row.get("cross_source_confirmation_score", 0.0) or 0.0),
            "declared_observed_gap": double_blind["overconfidence_risk"],
            "observed_true_gap_estimate": blind_spot["blind_spot_risk"],
        }
    )
    false_break = compute_false_break(
        {
            "persistence": validation_row.get("first_order_score", 0.0),
            "follow_through": validation_row.get("cross_source_confirmation_score", 0.0),
            "stability": 1.0 - float(validation_row.get("novelty_score", 0.0) or 0.0),
            "participation_quality": validation_row.get("source_quality_score", 0.0),
            "contradiction_resistance": execution_integrity_report.get("execution_integrity_score", 0.0),
            "initial_signal_strength": reflection_context.get("narrative_confidence", 0.0),
            "deception_risk": bluff_truth["bluff_risk"],
            "chaos": 1.0 if reflection_context.get("chaos_veto_active", False) else 0.0,
        }
    )
    casino_role = compute_casino_role_classifier(
        {
            "information_advantage": validation_row.get("cross_source_confirmation_score", 0.0),
            "capital_strength": 0.75 if runtime_state.get("execution_policy", {}).get("allow_new_risk", False) else 0.35,
            "timing_advantage": validation_row.get("price_lead_score", 0.0),
            "discipline": narrative_filter_report.get("operator_stability_score", 0.0),
            "rule_awareness": 1.0 if runtime_state.get("execution_policy", {}).get("policy_state") not in {"UNKNOWN", ""} else 0.0,
            "edge_availability": validation_row.get("repricing_headroom_score", 0.0),
            "predator_density": max(
                float(attention_proxy_report.get("narrative_heat_score", 0.0) or 0.0),
                1.0 if reflection_context.get("chaos_veto_active", False) else 0.0,
            ),
        }
    )
    table_context = compute_table_context(
        {
            "volatility": attention_proxy_report.get("narrative_heat_score", 0.0),
            "liquidity": validation_row.get("source_quality_score", 0.0),
            "crowding": 1.0 if _safe_upper(validation_row.get("crowding_state")) in {"CROWDED", "ALREADY_EXTENDED"} else 0.2,
            "participant_quality": bluff_truth["truth_probability"],
            "deception_risk": bluff_truth["bluff_risk"],
            "regime_stability": 0.0 if reflection_context.get("chaos_veto_active", False) else 0.75,
            "chaos_level": 1.0 if reflection_context.get("chaos_veto_active", False) else float(attention_proxy_report.get("narrative_heat_score", 0.0) or 0.0) * 0.5,
            "policy_restriction": 1.0 if not runtime_state.get("execution_policy", {}).get("allow_new_risk", False) else 0.0,
            "prior_false_break_count": 1 if false_break["false_break_state"] in {"FALSE_BREAK_RISK", "FAILED_BREAK"} else 0,
        }
    )
    monopoly_cluster = compute_monopoly_cluster(
        {
            "asset_count": max(int(position_truth_summary.get("canonical_position_count", 0) or 0), signal_count),
            "synergy": validation_row.get("cross_source_confirmation_score", 0.0),
            "control": execution_integrity_report.get("execution_integrity_score", 0.0),
            "persistence": validation_row.get("first_order_score", 0.0),
            "cashflow_potential": validation_row.get("repricing_headroom_score", 0.0),
            "validation": validation_row.get("validation_score", 0.0),
            "durability": asset_durability_report.get("hundred_wash_score", 0.0),
            "execution_survivability": execution_integrity_report.get("execution_integrity_score", 0.0),
        }
    )
    false_negative = compute_false_negative_risk(
        {
            "role_misfit": role_fit["role_misfit_risk"],
            "context_misfit": 1.0 - table_context["table_context_score"],
            "metric_blindness": blind_spot["blind_spot_risk"],
            "structural_value_unmeasured": max(
                0.0,
                structural["structural_stabilizer_score"] - structural["visible_output"],
            ),
            "asymmetric_upside": validation_row.get("repricing_headroom_score", 0.0),
        }
    )
    joker_shock = compute_joker_shock(
        {
            "surprise": 1.0 if temporal_integrity.get("temporal_integrity_state") == "FAILED" else false_break["false_break_risk"],
            "impact": 1.0 if position_truth_summary.get("divergence_severity") == "CRITICAL" else 0.55 if reflection_context.get("chaos_veto_active", False) else 0.25,
            "rule_change": 1.0 if not runtime_state.get("execution_policy", {}).get("allow_new_risk", False) else 0.45,
            "joker_event_detected": temporal_integrity.get("temporal_integrity_state") == "FAILED"
            or position_truth_summary.get("divergence_severity") == "CRITICAL",
        }
    )
    jail_mode = compute_jail_mode(
        {
            "chaos": 1.0 if reflection_context.get("chaos_veto_active", False) else 0.0,
            "overexposure": float(operator_control_report.get("active_work_block", {}).get("reopened_decision_count", 0) or 0) / 4.0,
            "edge_compression": 1.0 - float(validation_row.get("repricing_headroom_score", 0.0) or 0.0),
            "model_uncertainty": 1.0 - bluff_truth["truth_probability"],
            "policy_restriction": not runtime_state.get("execution_policy", {}).get("allow_new_risk", False),
            "high_false_break_risk": false_break["false_break_state"] in {"FALSE_BREAK_RISK", "FAILED_BREAK"},
            "dangerous_table": table_context["table_context_state"] == "NO_PLAY_TABLE",
            "dangerous_confidence": double_blind["double_blind_state"] == "DANGEROUS_CONFIDENCE",
            "hard_veto": busquets_audit_report.get("busquets_state") == "HARD_VETO",
            "existing_cashflow": validation_row.get("source_quality_score", 0.0),
            "movement_risk": attention_proxy_report.get("narrative_heat_score", 0.0),
        }
    )
    reentry = compute_reentry_state(
        {
            "state_before": "JAIL" if jail_mode["jail_mode_active"] else "PROBE",
            "jail_mode_active": jail_mode["jail_mode_active"],
            "policy_clear": runtime_state.get("execution_policy", {}).get("allow_new_risk", False),
            "signal_strength": validation_row.get("validation_score", 0.0),
            "stability": asset_durability_report.get("hundred_wash_score", 0.0),
            "probe_success": validation_row.get("cross_source_confirmation_score", 0.0),
            "follow_through": validation_row.get("first_order_score", 0.0),
            "chaos": 1.0 if reflection_context.get("chaos_veto_active", False) else 0.0,
            "deception_risk": bluff_truth["bluff_risk"],
            "false_break_risk": false_break["false_break_risk"],
        }
    )
    forced_transition = compute_forced_transition(
        {
            "state_before": reentry["reentry_state_before"],
            "joker_event_detected": joker_shock["joker_event_detected"],
            "policy_restriction": not runtime_state.get("execution_policy", {}).get("allow_new_risk", False),
            "chaos": 1.0 if reflection_context.get("chaos_veto_active", False) else 0.0,
            "rule_override": joker_shock["shock_state"] in {"JOKER_EVENT", "MODEL_RESET_REQUIRED"},
            "trend_reversal": false_break["false_break_state"] == "FAILED_BREAK",
        }
    )
    recurrence = compute_number_theory_recurrence(
        {"intervals": _derive_recurrence_intervals_from_trend(trend_report)}
    )
    bull_state = compute_bull_state(
        {
            "policy_veto": not runtime_state.get("execution_policy", {}).get("allow_new_risk", False),
            "chaos": 1.0 if reflection_context.get("chaos_veto_active", False) else 0.0,
            "joker_event_detected": joker_shock["joker_event_detected"],
            "jail_mode_active": jail_mode["jail_mode_active"],
            "validation": validation_row.get("validation_score", 0.0),
            "durability": asset_durability_report.get("hundred_wash_score", 0.0),
            "execution_survivability": execution_integrity_report.get("execution_integrity_score", 0.0),
            "momentum": validation_row.get("price_lead_score", 0.0),
            "novelty": validation_row.get("novelty_score", 0.0),
            "policy_clear": runtime_state.get("execution_policy", {}).get("allow_new_risk", False),
            "actionable": bool(primary_packet),
            "previous_bull_state": runtime_state.get("signal_metabolism", {}).get("top_bull_state", "UNKNOWN"),
        }
    )
    investable = compute_investable_signal_adjustment(
        {
            "policy_veto": not runtime_state.get("execution_policy", {}).get("allow_new_risk", False),
            "detection": reflection_context.get("evidence_strength", 0.0),
            "validation": validation_row.get("validation_score", 0.0),
            "durability": asset_durability_report.get("hundred_wash_score", 0.0),
            "execution_survivability": execution_integrity_report.get("execution_integrity_score", 0.0),
            "table_quality": table_context["table_context_score"],
            "truth_probability": bluff_truth["truth_probability"],
            "role_fit": role_fit["role_capability_fit_score"],
            "cluster_power": monopoly_cluster["asset_cluster_score"],
            "chaos_penalty": 1.0 if reflection_context.get("chaos_veto_active", False) else 0.0,
            "deception_penalty": bluff_truth["bluff_risk"],
            "false_break_penalty": false_break["false_break_risk"],
            "overconfidence_penalty": double_blind["double_blind_risk"],
        }
    )

    report = {
        "source_mode": get_source_mode(),
        "report_path": repo_relative(output_path or FALSE_NEGATIVE_CASINO_MONOPOLY_REPORT_PATH),
        "structural": structural,
        "role_capability": role_fit,
        "false_negative": false_negative,
        "blind_spot": blind_spot,
        "double_blind": double_blind,
        "decision_quality": decision_quality,
        "casino_role_classifier": casino_role,
        "table_context": table_context,
        "monopoly_cluster": monopoly_cluster,
        "jail_mode": jail_mode,
        "reentry": reentry,
        "false_break": false_break,
        "bluff_truth": bluff_truth,
        "joker_shock": joker_shock,
        "forced_transition": forced_transition,
        "bull_archetype": bull_state,
        "recurrence": recurrence,
        "investable_signal": investable,
        "policy_veto_outranks_layer": not runtime_state.get("execution_policy", {}).get("allow_new_risk", False),
        "safety_state_intact": (
            not investable["allow_new_risk"]
            if not runtime_state.get("execution_policy", {}).get("allow_new_risk", False)
            else True
        ),
    }
    if write_runtime:
        write_json_atomic(output_path or FALSE_NEGATIVE_CASINO_MONOPOLY_REPORT_PATH, report, stamp=True)
    return report


def moltbook_feedback_score(
    signal_refinery_report: dict[str, Any],
    runtime_state: dict[str, Any],
) -> float:
    feedback = runtime_state.get("moltbook_feedback", {})
    success_rate = feedback.get("feedback_success_rate")
    if isinstance(success_rate, (int, float)):
        return _clamp(success_rate)
    summary = signal_refinery_report.get("decision_engine_summary", {})
    return _clamp(float(summary.get("usable_signal_output", 0.0) or 0.0) / max(len(runtime_state.get("per_signal_attribution", [])) or 1, 1))


def format_false_negative_casino_monopoly_summary(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "False Negative Casino Monopoly Layer",
            f"structural_stabilizer_score={report['structural']['structural_stabilizer_score']}",
            f"structural_stabilizer_state={report['structural']['structural_stabilizer_state']}",
            f"role_capability_fit_score={report['role_capability']['role_capability_fit_score']}",
            f"current_role_fit_state={report['role_capability']['current_role_fit_state']}",
            f"false_negative_risk={report['false_negative']['false_negative_risk']}",
            f"false_negative_state={report['false_negative']['false_negative_state']}",
            f"blind_spot_risk={report['blind_spot']['blind_spot_risk']}",
            f"double_blind_risk={report['double_blind']['double_blind_risk']}",
            f"double_blind_state={report['double_blind']['double_blind_state']}",
            f"decision_quality_state={report['decision_quality']['decision_quality_state']}",
            f"casino_role={report['casino_role_classifier']['casino_role']}",
            f"food_chain_rank={report['casino_role_classifier']['food_chain_rank']}",
            f"table_context_state={report['table_context']['table_context_state']}",
            f"asset_cluster_score={report['monopoly_cluster']['asset_cluster_score']}",
            f"cluster_control_state={report['monopoly_cluster']['cluster_control_state']}",
            f"scale_permission_state={report['monopoly_cluster']['scale_permission_state']}",
            f"jail_mode_active={str(report['jail_mode']['jail_mode_active']).lower()}",
            f"jail_mode_state={report['jail_mode']['jail_mode_state']}",
            f"reentry_state={report['reentry']['reentry_state']}",
            f"false_break_risk={report['false_break']['false_break_risk']}",
            f"bluff_risk={report['bluff_truth']['bluff_risk']}",
            f"truth_probability={report['bluff_truth']['truth_probability']}",
            f"joker_event_detected={str(report['joker_shock']['joker_event_detected']).lower()}",
            f"shock_state={report['joker_shock']['shock_state']}",
            f"forced_transition_command={report['forced_transition']['forced_transition_command']}",
            f"bull_state={report['bull_archetype']['bull_state']}",
            f"recurrence_score={report['recurrence']['recurrence_score']}",
            f"cycle_state={report['recurrence']['cycle_state']}",
            f"investable_signal_adjusted_score={report['investable_signal']['investable_signal_adjusted_score']}",
            f"policy_veto_outranks_layer={str(report['policy_veto_outranks_layer']).lower()}",
            f"safety_state_intact={str(report['safety_state_intact']).lower()}",
        ]
    )


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the false negative / casino / monopoly advisory layer."
    )
    parser.add_argument("--summary", action="store_true", help="Emit a compact summary.")
    parser.add_argument("--write-runtime", action="store_true", help="Persist runtime artifact.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    state = build_runtime_state_from_scm_report_payload(build_signal_conversion_report())
    report = build_false_negative_casino_monopoly_report(
        runtime_state=state,
        signal_refinery_report={},
        attention_proxy_report={},
        action_report={},
        trend_report={},
        reflection_context={
            "validation_row": {},
            "launch_row": {},
            "primary_packet": {},
            "evidence_strength": 0.0,
            "narrative_confidence": 0.0,
            "chaos_veto_active": False,
        },
        narrative_filter_report={},
        busquets_audit_report={},
        execution_integrity_report={},
        asset_durability_report={},
        temporal_integrity={},
        position_truth_summary={},
        operator_control_report={},
        write_runtime=args.write_runtime,
    )
    if args.summary:
        print(format_false_negative_casino_monopoly_summary(report))
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
