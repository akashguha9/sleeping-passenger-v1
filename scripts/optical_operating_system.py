from __future__ import annotations

"""Optical Operating System diagnostics layer.

This module keeps the MVP on the suggestion side of the boundary. It models
controlled perception, validation depth, and execution-lock discipline without
adding any brokerage behavior or autonomous order placement.

Preserved doctrine / formulas:
    CurtainOutcome = Fabric × Thickness × Stitch × Opacity
    Opacity = 1 - LightTransmission
    PerceivedReality = RawInformation × (1 - Opacity)
    Signal = Narrative × FilterSurvival × TimePersistence × Actionability
    Perception = Input × (1 - Opacity) × ApertureFocus
    Exposure = Aperture × ShutterSpeed
    ActNow ⇔ OpportunityHalfLife < ValidationTime
    Wait ⇔ InformationGain > DelayCost
    DistortedSignal = RawSignal × MirrorEffect
    PerceivedReality = Reality × LensFunction
    ValidatedSignal = Signal × MicrostructureSurvival
    OptimalFocalLength = f(SignalStrength, Stability, HalfLife)
    ExecutionQuality = SignalQuality × LensLock
    PerceivedReality = TotalReality × ReductionFunction
    DecisionQuality = SignalQuality × OperatorStateFit
    ActionAllowed = SignalValid ∧ OperatorSafe ∧ PolicyClear
    Outcome = Reality × Consciousness × Lens × Mirror × (1 - Opacity)
              × Aperture × Shutter
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


LENS_SEQUENCE = [
    "FISHEYE",
    "WIDE",
    "STANDARD",
    "TELEPHOTO",
    "MACRO",
    "LEICA",
    "EXECUTION_LOCK",
]
LENS_FUNCTION = {
    "FISHEYE": 0.35,
    "WIDE": 0.55,
    "STANDARD": 0.72,
    "TELEPHOTO": 0.82,
    "SUPER_TELEPHOTO": 0.78,
    "MACRO": 0.9,
    "LEICA": 1.0,
    "EXECUTION_LOCK": 1.0,
}
MIRROR_MULTIPLIERS = {
    "CONVEX": 0.85,
    "NEUTRAL": 1.0,
    "CONCAVE": 1.1,
    "WARPED": 1.25,
}
APERTURE_FOCUS = {
    "WIDE": 0.55,
    "MODERATE": 0.75,
    "NARROW": 0.9,
    "PINHOLE": 0.95,
}
SHUTTER_EXPOSURE = {
    "ACT_NOW": 0.95,
    "WAIT": 0.7,
    "ABORT": 0.0,
}
VALVE_FACTORS = {
    "TOO_OPEN": 0.45,
    "BALANCED": 1.0,
    "TOO_CLOSED": 0.6,
}
OPERATOR_COLORS = {
    "GREEN": 1.0,
    "YELLOW": 0.65,
    "RED": 0.2,
}
EXECUTION_LENSES = {"MACRO", "LEICA", "EXECUTION_LOCK"}


def _clamp(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, numeric))


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _text(value: Any, default: str = "") -> str:
    return str(value or default).strip()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class OpticalOperatingSystemResult:
    opacity_state: str
    opacity_score: float
    aperture_state: str
    attention_width_score: float
    attention_depth_score: float
    shutter_state: str
    mirror_mode: str
    mirror_multiplier: float
    lens_mode: str
    target_lens_mode: str
    lens_transition_state: str
    lens_lock: bool
    lens_switch_blocked: bool
    valve_state: str
    operator_state: str
    operator_band: str
    operator_state_fit: float
    macro_pass: bool
    leica_clearance: bool
    optical_bull_state: str
    action_allowed: bool
    final_recommendation: str
    blocking_reason: str
    minimum_validation_passed: bool
    fast_track_eligible: bool
    chaos_veto_active: bool
    shock_override_active: bool
    perceived_reality_score: float
    decision_quality_score: float
    investable_signal_score: float
    opportunity_half_life: float
    validation_time: float
    information_gain: float
    delay_cost: float
    failed_gates: list[str] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)
    optical_state_log: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_opacity_state(
    *,
    chaos_score: Any,
    policy_state: Any,
    validation_quality: Any,
    operator_state_fit: Any,
    regime_stress: Any,
) -> tuple[str, float]:
    policy_blocked = _text(policy_state, "UNKNOWN").upper() in {
        "RESTRICTED",
        "BLOCKED",
        "DO_NOT_DEPLOY",
        "NOT_READY",
    }
    opacity_score = round(
        _clamp(
            (0.35 * _clamp(chaos_score))
            + (0.25 * (1.0 if policy_blocked else 0.0))
            + (0.20 * (1.0 - _clamp(validation_quality)))
            + (0.10 * (1.0 - _clamp(operator_state_fit)))
            + (0.10 * _clamp(regime_stress))
        ),
        3,
    )
    if _clamp(chaos_score) >= 0.85 or policy_blocked and opacity_score >= 0.7:
        return "BLACKOUT", opacity_score
    if opacity_score >= 0.65:
        return "HIGH_OPACITY", opacity_score
    if opacity_score >= 0.35:
        return "MEDIUM_OPACITY", opacity_score
    return "LOW_OPACITY", opacity_score


def classify_aperture_state(
    *,
    candidate_count: Any,
    emergency_mode: Any,
    active_blockers: Any = 0,
) -> tuple[str, float, float]:
    candidates = max(0, int(candidate_count or 0))
    blockers = max(0, int(active_blockers or 0))
    emergency = _truthy(emergency_mode)
    if emergency or blockers >= 2:
        state = "PINHOLE"
        width = 0.1
    elif candidates >= 6:
        state = "WIDE"
        width = 0.95
    elif candidates >= 3:
        state = "MODERATE"
        width = 0.55
    else:
        state = "NARROW"
        width = 0.25
    depth = round(_clamp(1.0 - (width * 0.6)), 3)
    return state, round(width, 3), depth


def evaluate_shutter_controller(
    *,
    opportunity_half_life: Any,
    validation_time: Any,
    information_gain: Any,
    delay_cost: Any,
    minimum_validation_passed: Any,
    risk_clear: Any,
    policy_clear: Any,
    chaos_clear: Any,
    operator_safe: Any,
) -> tuple[str, list[str]]:
    half_life = _clamp(opportunity_half_life)
    validation = _clamp(validation_time)
    info_gain = _clamp(information_gain)
    cost = _clamp(delay_cost)
    minimum_validation = _truthy(minimum_validation_passed)
    risk_ok = _truthy(risk_clear)
    policy_ok = _truthy(policy_clear)
    chaos_ok = _truthy(chaos_clear)
    operator_ok = _truthy(operator_safe)
    rationale: list[str] = []

    if not (risk_ok and policy_ok and chaos_ok and operator_ok):
        rationale.append("Abort state triggered by policy, chaos, risk, or operator veto.")
        return "ABORT", rationale
    if half_life < validation and minimum_validation and risk_ok:
        rationale.append("Opportunity half-life is shorter than validation time, so act-now timing dominates.")
        return "ACT_NOW", rationale
    if info_gain > cost and half_life >= max(validation * 0.5, 0.1):
        rationale.append("Waiting is justified because information gain exceeds delay cost.")
        return "WAIT", rationale
    if not minimum_validation:
        rationale.append("Validation floor is not satisfied, so the shutter remains in wait mode.")
        return "WAIT", rationale
    rationale.append("No timing advantage exists, so the shutter defaults to wait.")
    return "WAIT", rationale


def evaluate_mirror_distortion(
    *,
    objective_importance: Any,
    narrative_confidence: Any,
    validation_quality: Any,
    persistence: Any,
    execution_phase: Any,
    chaos_veto_active: Any,
) -> tuple[str, float, list[str]]:
    objective = _clamp(objective_importance)
    narrative = _clamp(narrative_confidence)
    validation = _clamp(validation_quality)
    persistence_score = _clamp(persistence)
    execution_phase_active = _truthy(execution_phase)
    chaos_active = _truthy(chaos_veto_active)
    rationale: list[str] = []

    if chaos_active or (narrative >= 0.85 and validation <= 0.35):
        rationale.append("Mirror is warped because urgency or chaos is overwhelming validated structure.")
        return "WARPED", MIRROR_MULTIPLIERS["WARPED"], rationale
    if narrative - validation >= 0.2:
        rationale.append("Mirror is concave because conviction exceeds validation depth.")
        return "CONCAVE", MIRROR_MULTIPLIERS["CONCAVE"], rationale
    if objective <= 0.35 or persistence_score <= 0.3:
        if execution_phase_active:
            rationale.append("Execution-phase convex distortion risks diluting conviction.")
        else:
            rationale.append("Convex mode is acceptable during exploration because the signal is still broad and weak.")
        return "CONVEX", MIRROR_MULTIPLIERS["CONVEX"], rationale
    rationale.append("Mirror is neutral because objective importance and validation remain aligned.")
    return "NEUTRAL", MIRROR_MULTIPLIERS["NEUTRAL"], rationale


def classify_lens_mode(
    *,
    signal_strength: Any,
    persistence: Any,
    convergence: Any,
    validation_quality: Any,
    execution_survivability: Any,
    source_quality: Any,
    volatility: Any,
    opportunity_half_life: Any,
    minimum_validation_passed: Any,
) -> str:
    strength = _clamp(signal_strength)
    persistence_score = _clamp(persistence)
    convergence_score = _clamp(convergence)
    validation = _clamp(validation_quality)
    execution = _clamp(execution_survivability)
    source = _clamp(source_quality)
    volatility_score = _clamp(volatility)
    half_life = _clamp(opportunity_half_life)
    minimum_validation = _truthy(minimum_validation_passed)

    if strength < 0.25:
        return "FISHEYE"
    if validation >= 0.75 and source >= 0.65 and execution >= 0.6:
        return "LEICA"
    if persistence_score < 0.35:
        return "WIDE"
    if convergence_score < 0.45:
        return "STANDARD"
    if strength >= 0.8 and volatility_score <= 0.35 and half_life <= 0.25:
        return "SUPER_TELEPHOTO"
    if validation < 0.65 or not minimum_validation:
        return "TELEPHOTO"
    if validation >= 0.65 and execution < 0.75:
        return "MACRO"
    return "MACRO"


def evaluate_huxley_valve(
    *,
    operator_state: Any,
    operator_state_fit: Any,
    urgency_spike: Any,
    confidence_surge: Any,
    evidence_strength: Any,
    narrative_confidence: Any,
    cognitive_load: Any,
) -> tuple[str, str, float, list[str]]:
    state = _text(operator_state, "UNKNOWN").upper()
    fit = _clamp(operator_state_fit)
    urgency = _truthy(urgency_spike)
    confidence = _truthy(confidence_surge)
    evidence = _clamp(evidence_strength)
    narrative = _clamp(narrative_confidence)
    load = _clamp(cognitive_load)
    rationale: list[str] = []

    if state in {"RED", "INTOXICATED"} or fit < 0.4:
        rationale.append("Operator stability is too low for new risk.")
        return "TOO_OPEN", "RED", fit, rationale
    if urgency and confidence and narrative > evidence:
        rationale.append("Operator valve is too open because symbolic over-reading exceeds evidence.")
        return "TOO_OPEN", "YELLOW", fit, rationale
    if load >= 0.8 or state == "TOO_CLOSED":
        rationale.append("Operator valve is too closed because cognitive rigidity dominates.")
        return "TOO_CLOSED", "YELLOW", fit, rationale
    if fit < 0.7 or state in {"STRESSED", "FATIGUED", "EUPHORIC", "UNKNOWN", "YELLOW"}:
        rationale.append("Operator can observe and validate, but expansion should remain limited.")
        return "BALANCED", "YELLOW", fit, rationale
    rationale.append("Operator state is balanced enough for manual review authority.")
    return "BALANCED", "GREEN", fit, rationale


def transition_lens_mode(
    *,
    current_lens_mode: Any,
    target_lens_mode: Any,
    lens_lock_active: Any,
    hard_override: Any,
) -> tuple[str, str, bool]:
    current = _text(current_lens_mode, "WIDE").upper()
    target = _text(target_lens_mode, current).upper()
    lock_active = _truthy(lens_lock_active)
    override = _truthy(hard_override)

    if target == "SUPER_TELEPHOTO":
        target = "TELEPHOTO"
    if target == "FISHEYE":
        return "FISHEYE", "OVERRIDE", False
    if current not in LENS_SEQUENCE:
        current = "WIDE"
    if target not in LENS_SEQUENCE:
        target = current
    if lock_active and not override:
        return current, "LOCKED_HOLD", True
    if override:
        return target, "OVERRIDE", False
    current_index = LENS_SEQUENCE.index(current)
    target_index = LENS_SEQUENCE.index(target)
    if current_index == target_index:
        return current, "HOLD", False
    step = 1 if target_index > current_index else -1
    next_lens = LENS_SEQUENCE[current_index + step]
    return next_lens, "ADVANCE" if step > 0 else "RETREAT", False


def evaluate_optical_operating_system(context: dict[str, Any] | None) -> dict[str, Any]:
    payload = context if isinstance(context, dict) else {}
    operator_state = _text(payload.get("operator_state"), "UNKNOWN").upper()
    signal_id = payload.get("signal_id")
    asset = payload.get("asset") or payload.get("ticker")
    run_id = payload.get("run_id")
    timestamp = _text(payload.get("timestamp")) or _utc_now()

    detection = _clamp(payload.get("detection_strength"))
    validation_quality = _clamp(payload.get("validation_quality"))
    durability = _clamp(payload.get("durability_score"))
    execution_survivability = _clamp(payload.get("execution_survivability"))
    source_quality = _clamp(payload.get("source_quality"))
    signal_strength = _clamp(payload.get("signal_strength", detection))
    evidence_strength = _clamp(payload.get("evidence_strength", validation_quality))
    narrative_confidence = _clamp(payload.get("narrative_confidence"))
    opportunity_half_life = _clamp(payload.get("opportunity_half_life"))
    validation_time = _clamp(payload.get("validation_time"))
    information_gain = _clamp(payload.get("information_gain"))
    delay_cost = _clamp(payload.get("delay_cost"))
    current_lens_mode = _text(payload.get("current_lens_mode"), "WIDE").upper()
    momentum_score = _clamp(payload.get("momentum_score"))
    persistence = _clamp(payload.get("persistence"))
    convergence = _clamp(payload.get("convergence"))
    volatility = _clamp(payload.get("volatility"))
    risk_score = _clamp(payload.get("risk_score"))
    regime_stress = _clamp(payload.get("regime_stress"))
    candidate_count = int(payload.get("candidate_count", 0) or 0)
    active_blockers = len(payload.get("active_blockers", [])) if isinstance(payload.get("active_blockers"), list) else int(payload.get("active_blocker_count", 0) or 0)
    chaos_veto_active = _truthy(payload.get("chaos_veto_active"))
    shock_override_active = _truthy(payload.get("shock_override_active"))
    policy_clear = _truthy(payload.get("policy_clear"))
    risk_clear = _truthy(payload.get("risk_clear"))
    signal_valid = _truthy(payload.get("signal_valid"))
    minimum_validation_passed = _truthy(payload.get("minimum_validation_passed"))
    urgency_spike = _truthy(payload.get("urgency_spike"))
    confidence_surge = _truthy(payload.get("confidence_surge"))
    cognitive_load = _clamp(payload.get("cognitive_load"))
    requested_lens_change = _truthy(payload.get("requested_lens_change"))

    valve_state, operator_band, operator_state_fit, valve_rationale = evaluate_huxley_valve(
        operator_state=operator_state,
        operator_state_fit=payload.get("operator_state_fit"),
        urgency_spike=urgency_spike,
        confidence_surge=confidence_surge,
        evidence_strength=evidence_strength,
        narrative_confidence=narrative_confidence,
        cognitive_load=cognitive_load,
    )
    operator_safe = operator_band != "RED"
    opacity_state, opacity_score = classify_opacity_state(
        chaos_score=1.0 if chaos_veto_active else regime_stress,
        policy_state=payload.get("policy_state"),
        validation_quality=validation_quality,
        operator_state_fit=operator_state_fit,
        regime_stress=regime_stress,
    )
    aperture_state, attention_width_score, attention_depth_score = classify_aperture_state(
        candidate_count=candidate_count,
        emergency_mode=chaos_veto_active or shock_override_active or operator_band == "RED",
        active_blockers=active_blockers,
    )
    mirror_mode, mirror_multiplier, mirror_rationale = evaluate_mirror_distortion(
        objective_importance=max(signal_strength, validation_quality),
        narrative_confidence=narrative_confidence,
        validation_quality=validation_quality,
        persistence=persistence,
        execution_phase=current_lens_mode in EXECUTION_LENSES,
        chaos_veto_active=chaos_veto_active,
    )
    target_lens_mode = classify_lens_mode(
        signal_strength=signal_strength,
        persistence=persistence,
        convergence=convergence,
        validation_quality=validation_quality,
        execution_survivability=execution_survivability,
        source_quality=source_quality,
        volatility=volatility,
        opportunity_half_life=opportunity_half_life,
        minimum_validation_passed=minimum_validation_passed,
    )
    macro_pass = bool(
        validation_quality >= 0.65
        and source_quality >= 0.55
        and execution_survivability >= 0.45
        and signal_valid
    )
    leica_clearance = bool(
        macro_pass
        and mirror_mode == "NEUTRAL"
        and source_quality >= 0.65
        and execution_survivability >= 0.6
        and operator_safe
    )
    lens_lock_precondition = _truthy(payload.get("lens_lock_active"))
    hard_override = bool(
        shock_override_active
        or chaos_veto_active
        or not policy_clear
        or operator_band == "RED"
        or _truthy(payload.get("data_integrity_failure"))
        or execution_survivability < 0.35
    )
    lens_mode, lens_transition_state, lens_switch_blocked = transition_lens_mode(
        current_lens_mode=current_lens_mode,
        target_lens_mode=target_lens_mode,
        lens_lock_active=lens_lock_precondition,
        hard_override=hard_override,
    )
    if target_lens_mode == "LEICA" and current_lens_mode not in {"MACRO", "LEICA", "EXECUTION_LOCK"}:
        lens_mode = "MACRO"
        lens_transition_state = "ADVANCE"
    if lens_mode == "LEICA" and not leica_clearance:
        lens_mode = "MACRO"
        lens_transition_state = "RETREAT"
    lens_lock = bool(
        (
            lens_lock_precondition
            and lens_mode in {"LEICA", "EXECUTION_LOCK"}
            and leica_clearance
        )
        or (
            lens_mode == "LEICA"
            and leica_clearance
            and signal_valid
            and policy_clear
            and risk_clear
            and operator_safe
        )
    )
    if lens_lock and not hard_override:
        lens_mode = "EXECUTION_LOCK" if leica_clearance else lens_mode

    shutter_state, shutter_rationale = evaluate_shutter_controller(
        opportunity_half_life=opportunity_half_life,
        validation_time=validation_time,
        information_gain=information_gain,
        delay_cost=delay_cost,
        minimum_validation_passed=minimum_validation_passed,
        risk_clear=risk_clear,
        policy_clear=policy_clear,
        chaos_clear=not chaos_veto_active,
        operator_safe=operator_safe,
    )

    fast_track_eligible = bool(
        momentum_score >= 0.75
        and validation_quality >= 0.55
        and risk_score <= 0.35
        and operator_safe
        and policy_clear
        and not chaos_veto_active
    )
    if chaos_veto_active:
        optical_bull_state = "DIABLO"
    elif shock_override_active:
        optical_bull_state = "ISLERO"
    elif fast_track_eligible:
        optical_bull_state = "HURACAN"
    elif lens_mode in {"FISHEYE", "WIDE", "STANDARD", "TELEPHOTO"}:
        optical_bull_state = "MIURA"
    elif lens_mode == "MACRO":
        optical_bull_state = "MURCIELAGO"
    elif lens_mode == "LEICA":
        optical_bull_state = "AVENTADOR"
    else:
        optical_bull_state = "GALLARDO"

    failed_gates: list[str] = []
    rationale: list[str] = [*valve_rationale, *mirror_rationale, *shutter_rationale]
    if not policy_clear:
        failed_gates.append("policy_veto")
    if chaos_veto_active:
        failed_gates.append("chaos_veto")
    if shock_override_active:
        failed_gates.append("shock_reclassification")
    if operator_band == "RED":
        failed_gates.append("operator_red")
    if lens_mode == "FISHEYE":
        failed_gates.append("fisheye_not_executable")
        rationale.append("Fisheye is detection-only and cannot become direct action.")
    if target_lens_mode == "LEICA" and not macro_pass:
        failed_gates.append("macro_required_before_leica")
        rationale.append("Macro validation must pass before Leica clearance can exist.")
    if mirror_mode == "WARPED":
        failed_gates.append("mirror_warped")
    if mirror_mode == "CONCAVE" and not minimum_validation_passed:
        failed_gates.append("concave_before_validation")
    if current_lens_mode in EXECUTION_LENSES and mirror_mode == "CONVEX":
        failed_gates.append("convex_dilution_during_execution")
    if lens_switch_blocked and requested_lens_change and not hard_override:
        failed_gates.append("lens_switch_blocked_by_lock")
        rationale.append("Execution lens lock blocked mid-course re-selection.")
    if shutter_state == "ABORT":
        failed_gates.append("shutter_abort")

    lens_lock_clear = not lens_switch_blocked and mirror_mode != "WARPED"
    action_allowed = bool(
        policy_clear
        and not chaos_veto_active
        and risk_clear
        and operator_safe
        and signal_valid
        and lens_lock_clear
        and lens_mode not in {"FISHEYE", "WIDE"}
        and minimum_validation_passed
        and not shock_override_active
    )

    if failed_gates:
        blocking_reason = failed_gates[0]
    else:
        blocking_reason = ""

    if optical_bull_state == "DIABLO":
        final_recommendation = "BLOCK"
    elif optical_bull_state == "ISLERO":
        final_recommendation = "RECLASSIFY"
    elif not action_allowed and shutter_state == "WAIT":
        final_recommendation = "WAIT"
    elif not action_allowed:
        final_recommendation = "OBSERVE_ONLY" if lens_mode in {"FISHEYE", "WIDE", "STANDARD"} else "BLOCK"
    else:
        final_recommendation = "MANUAL_REVIEW"

    perceived_reality_score = round(
        _clamp(
            signal_strength
            * VALVE_FACTORS.get(valve_state, 0.6)
            * LENS_FUNCTION.get(lens_mode, 0.55)
            * min(1.0, mirror_multiplier)
            * (1.0 - opacity_score)
            * APERTURE_FOCUS.get(aperture_state, 0.75)
            * SHUTTER_EXPOSURE.get(shutter_state, 0.0)
        ),
        3,
    )
    decision_quality_score = round(
        _clamp(signal_strength * operator_state_fit * validation_quality * execution_survivability),
        3,
    )
    investable_signal_score = round(
        _clamp(detection * validation_quality * durability * execution_survivability * operator_state_fit),
        3,
    )

    optical_state_log = {
        "timestamp": timestamp,
        "run_id": run_id,
        "asset": asset,
        "signal_id": signal_id,
        "bull_archetype_state": optical_bull_state,
        "lens_mode": lens_mode,
        "mirror_mode": mirror_mode,
        "opacity_state": opacity_state,
        "opacity_score": opacity_score,
        "aperture_state": aperture_state,
        "shutter_state": shutter_state,
        "opportunity_half_life": round(opportunity_half_life, 3),
        "validation_time": round(validation_time, 3),
        "information_gain": round(information_gain, 3),
        "delay_cost": round(delay_cost, 3),
        "operator_state": operator_state,
        "operator_state_fit": round(operator_state_fit, 3),
        "valve_state": valve_state,
        "macro_pass": macro_pass,
        "leica_clearance": leica_clearance,
        "lens_lock": lens_lock,
        "action_allowed": action_allowed,
        "blocking_reason": blocking_reason or None,
        "final_recommendation": final_recommendation,
    }

    return OpticalOperatingSystemResult(
        opacity_state=opacity_state,
        opacity_score=opacity_score,
        aperture_state=aperture_state,
        attention_width_score=attention_width_score,
        attention_depth_score=attention_depth_score,
        shutter_state=shutter_state,
        mirror_mode=mirror_mode,
        mirror_multiplier=mirror_multiplier,
        lens_mode=lens_mode,
        target_lens_mode=target_lens_mode,
        lens_transition_state=lens_transition_state,
        lens_lock=lens_lock,
        lens_switch_blocked=lens_switch_blocked,
        valve_state=valve_state,
        operator_state=operator_state,
        operator_band=operator_band,
        operator_state_fit=round(operator_state_fit, 3),
        macro_pass=macro_pass,
        leica_clearance=leica_clearance,
        optical_bull_state=optical_bull_state,
        action_allowed=action_allowed,
        final_recommendation=final_recommendation,
        blocking_reason=blocking_reason,
        minimum_validation_passed=minimum_validation_passed,
        fast_track_eligible=fast_track_eligible,
        chaos_veto_active=chaos_veto_active,
        shock_override_active=shock_override_active,
        perceived_reality_score=perceived_reality_score,
        decision_quality_score=decision_quality_score,
        investable_signal_score=investable_signal_score,
        opportunity_half_life=round(opportunity_half_life, 3),
        validation_time=round(validation_time, 3),
        information_gain=round(information_gain, 3),
        delay_cost=round(delay_cost, 3),
        failed_gates=failed_gates,
        rationale=rationale,
        optical_state_log=optical_state_log,
    ).to_dict()
