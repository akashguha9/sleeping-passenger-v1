from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

try:
    from scripts.runtime_common import (
        REPO_ROOT,
        TENNIS_ARCHETYPE_REPORT_PATH,
        classify_operating_mode,
        get_run_id,
        get_source_mode,
        load_json_file,
        repo_relative,
        utc_timestamp,
        write_json_atomic,
    )
except ModuleNotFoundError:
    from runtime_common import (  # type: ignore[no-redef]
        REPO_ROOT,
        TENNIS_ARCHETYPE_REPORT_PATH,
        classify_operating_mode,
        get_run_id,
        get_source_mode,
        load_json_file,
        repo_relative,
        utc_timestamp,
        write_json_atomic,
    )


CONFIG_PATH = REPO_ROOT / "config" / "tennis_archetype_config.json"
SCHEMA_VERSION = "1.0"
EPSILON = 1e-6

THETA_CHAOS_VETO = 0.72
THETA_VALIDATION_FLOOR = 0.55
THETA_MOMENTUM = 0.65
THETA_FIRST_STRIKE = 0.70
THETA_AESTHETIC_GAP = 0.30
THETA_DURABILITY = 0.60
THETA_EXECUTION_READY = 0.65


class ExecutionStyle(str, Enum):
    FRICTIONLESS_CONTROL = "FRICTIONLESS_CONTROL"
    PRESSURE_DURABILITY = "PRESSURE_DURABILITY"
    CHAOS_ABSORPTION = "CHAOS_ABSORPTION"
    PATTERN_DISRUPTION = "PATTERN_DISRUPTION"
    FIRST_STRIKE = "FIRST_STRIKE"
    SINGLE_WEAPON_DOMINANCE = "SINGLE_WEAPON_DOMINANCE"
    HYBRID_FAST_TRACK = "HYBRID_FAST_TRACK"
    CONTROLLED_CHAOS = "CONTROLLED_CHAOS"
    EMOTIONAL_VOLATILITY = "EMOTIONAL_VOLATILITY"
    REPEATABLE_PRECISION = "REPEATABLE_PRECISION"
    MOMENTUM_SPIKE = "MOMENTUM_SPIKE"
    AESTHETIC_RAW_SIGNAL = "AESTHETIC_RAW_SIGNAL"
    HIGH_VARIANCE_SHOTMAKING = "HIGH_VARIANCE_SHOTMAKING"


PLAYER_MAP = {
    ExecutionStyle.FRICTIONLESS_CONTROL.value: "Federer",
    ExecutionStyle.PRESSURE_DURABILITY.value: "Nadal",
    ExecutionStyle.CHAOS_ABSORPTION.value: "Djokovic",
    ExecutionStyle.PATTERN_DISRUPTION.value: "Murray",
    ExecutionStyle.FIRST_STRIKE.value: "Roddick",
    ExecutionStyle.SINGLE_WEAPON_DOMINANCE.value: "Del Potro",
    ExecutionStyle.HYBRID_FAST_TRACK.value: "Alcaraz",
    ExecutionStyle.CONTROLLED_CHAOS.value: "Bublik",
    ExecutionStyle.EMOTIONAL_VOLATILITY.value: "Safin",
    ExecutionStyle.REPEATABLE_PRECISION.value: "Nishikori",
    ExecutionStyle.MOMENTUM_SPIKE.value: "Shelton",
    ExecutionStyle.AESTHETIC_RAW_SIGNAL.value: "Tsitsipas",
    ExecutionStyle.HIGH_VARIANCE_SHOTMAKING.value: "Verdasco",
}


class RecommendedAction(str, Enum):
    BLOCK_NO_NEW_RISK = "BLOCK_NO_NEW_RISK"
    KEEP_IN_MIURA_RAW_DETECTION = "KEEP_IN_MIURA_RAW_DETECTION"
    SEND_TO_MURCIELAGO_DURABILITY_VALIDATION = "SEND_TO_MURCIELAGO_DURABILITY_VALIDATION"
    PROMOTE_TO_AVENTADOR_ACTIONABLE_WATCHLIST = "PROMOTE_TO_AVENTADOR_ACTIONABLE_WATCHLIST"
    ALLOW_HURACAN_FAST_TRACK_WATCH = "ALLOW_HURACAN_FAST_TRACK_WATCH"
    READY_FOR_GALLARDO_EXECUTION_SIMULATION_ONLY = "READY_FOR_GALLARDO_EXECUTION_SIMULATION_ONLY"
    RECLASSIFY_ISLERO_PATTERN_SHOCK = "RECLASSIFY_ISLERO_PATTERN_SHOCK"


DEFAULT_THRESHOLDS = {
    "theta_chaos_veto": THETA_CHAOS_VETO,
    "theta_validation_floor": THETA_VALIDATION_FLOOR,
    "theta_momentum": THETA_MOMENTUM,
    "theta_first_strike": THETA_FIRST_STRIKE,
    "theta_aesthetic_gap": THETA_AESTHETIC_GAP,
    "theta_durability": THETA_DURABILITY,
    "theta_execution_ready": THETA_EXECUTION_READY,
}


@dataclass(slots=True)
class TennisSignal:
    signal_id: str
    detection_score: float = 0.0
    output_quality: float = 0.0
    energy_cost: float = 0.0
    timing_quality: float = 0.0
    error_control: float = 0.0
    performance_after_stress: float = 0.0
    performance_before_stress: float = 1.0
    signal_strength: float = 0.0
    stress_survival: float = 0.0
    repeatability: float = 0.0
    volatility_tolerance: float = 0.0
    recovery_speed: float = 0.0
    pressure_absorbed: float = 0.0
    timing: float = 0.0
    pattern_dependence: float = 0.0
    disruption_timing: float = 0.0
    opponent_adjustment_lag: float = 0.0
    initial_shock: float = 0.0
    reaction_delay: float = 0.0
    timing_window: float = 0.0
    minimum_validation: float = 0.0
    weapon_strength: float = 0.0
    access_frequency: float = 0.0
    pressure_access: float = 0.0
    dominant_variable: float = 0.0
    momentum: float = 0.0
    discipline_score: float = 0.0
    chaos_score: float = 0.0
    unpredictability: float = 0.0
    executability: float = 0.0
    control: float = 0.0
    emotional_instability: float = 0.0
    decision_impact: float = 0.0
    raw_skill: float = 0.0
    velocity: float = 0.0
    confidence: float = 0.0
    external_energy: float = 0.0
    aesthetic_appeal: float = 0.0
    structural_reliability: float = 0.0
    upside: float = 0.0
    variance_penalty: float = 0.0
    low_repeatability: float = 0.0
    chaos_exposure: float = 0.0
    validation_score: float = 0.0
    durability_score: float = 0.0
    execution_survivability: float = 0.0
    heat_score: float = 0.0
    risk_guard_score: float = 0.0
    policy_veto: bool = False
    can_deploy_capital: bool = False
    risk_cap_active: bool = False
    entry_defined: bool = False
    invalidation_defined: bool = False
    sizing_defined: bool = False
    exit_defined: bool = False
    review_defined: bool = False
    pattern_shock: bool = False
    source: str = "synthetic"


def clamp01(x: Any) -> float:
    try:
        value = float(x)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, value))


def safe_div(a: Any, b: Any, default: float = 0.0) -> float:
    numerator = clamp01(a)
    try:
        denominator = float(b)
    except (TypeError, ValueError):
        return default
    if abs(denominator) < EPSILON:
        return default
    return clamp01(numerator / denominator)


def weighted_mean(parts: dict[str, tuple[float, float]]) -> float:
    total_weight = 0.0
    weighted_total = 0.0
    for value, weight in parts.values():
        total_weight += float(weight)
        weighted_total += clamp01(value) * float(weight)
    if total_weight <= 0.0:
        return 0.0
    return clamp01(weighted_total / total_weight)


def load_thresholds() -> dict[str, float]:
    payload = load_json_file(CONFIG_PATH, default={})
    thresholds = dict(DEFAULT_THRESHOLDS)
    if isinstance(payload, dict):
        for key, default in DEFAULT_THRESHOLDS.items():
            thresholds[key] = clamp01(payload.get(key, default))
    return thresholds


def _to_signal(signal: dict[str, Any]) -> TennisSignal:
    data = dict(signal)
    signal_id = str(data.get("signal_id") or data.get("ticker") or data.get("name") or "UNKNOWN")
    return TennisSignal(signal_id=signal_id, **{k: v for k, v in data.items() if k != "signal_id" and k != "ticker" and k != "name"})


def _execution_friction(output_quality: float, energy_cost: float) -> float:
    return clamp01(safe_div(energy_cost, max(clamp01(output_quality), EPSILON)))


def _frictionless_score(signal: TennisSignal) -> float:
    """ExecutionFriction = EnergyCost / max(OutputQuality, ε)
    FrictionlessScore = OutputQuality × TimingQuality × ErrorControl × (1 − ExecutionFrictionBounded)
    """
    friction = _execution_friction(signal.output_quality, signal.energy_cost)
    return clamp01(
        clamp01(signal.output_quality)
        * clamp01(signal.timing_quality)
        * clamp01(signal.error_control)
        * (1.0 - friction)
        * 2.5
    )


def _durability_score(signal: TennisSignal) -> float:
    """Durability = PerformanceAfterStress / max(PerformanceBeforeStress, ε)
    DurableSignal = SignalStrength × StressSurvival × Repeatability
    """
    durability = safe_div(signal.performance_after_stress, max(float(signal.performance_before_stress), EPSILON))
    durable_signal = clamp01(
        clamp01(signal.signal_strength)
        * clamp01(signal.stress_survival)
        * clamp01(signal.repeatability)
        * 2.0
    )
    return clamp01(weighted_mean({"durability": (durability, 0.45), "durable_signal": (durable_signal, 0.55)}))


def _chaos_absorption_score(signal: TennisSignal) -> float:
    """ChaosAbsorption = VolatilityTolerance × RecoverySpeed × ErrorReduction
    Conversion = PressureAbsorbed × ErrorReduction × Timing
    """
    absorption = clamp01(
        clamp01(signal.volatility_tolerance)
        * clamp01(signal.recovery_speed)
        * clamp01(signal.error_control)
        * 2.0
    )
    conversion = clamp01(
        clamp01(signal.pressure_absorbed)
        * clamp01(signal.error_control)
        * clamp01(signal.timing)
        * 2.0
    )
    return weighted_mean({"absorption": (absorption, 0.5), "conversion": (conversion, 0.5)})


def _pattern_break_score(signal: TennisSignal) -> float:
    """PatternBreakValue = PatternDependence × DisruptionTiming × OpponentAdjustmentLag"""
    return clamp01(
        clamp01(signal.pattern_dependence)
        * clamp01(signal.disruption_timing)
        * clamp01(signal.opponent_adjustment_lag)
        * 2.5
    )


def _first_strike_score(signal: TennisSignal) -> float:
    """FirstStrikeScore = InitialShock × ReactionDelay × TimingWindow"""
    return clamp01(
        clamp01(signal.initial_shock)
        * clamp01(signal.reaction_delay)
        * clamp01(signal.timing_window)
        * 2.5
    )


def _dominance_score(signal: TennisSignal) -> float:
    """DominanceScore = WeaponStrength × AccessFrequency × PressureAccess
    Conviction = DominantVariable × RepeatableAccess
    """
    dominance = clamp01(
        clamp01(signal.weapon_strength)
        * clamp01(signal.access_frequency)
        * clamp01(signal.pressure_access)
        * 2.5
    )
    conviction = clamp01(clamp01(signal.dominant_variable) * clamp01(signal.access_frequency) * 1.5)
    return weighted_mean({"dominance": (dominance, 0.65), "conviction": (conviction, 0.35)})


def _hybrid_fast_track_score(signal: TennisSignal) -> float:
    """FastTrack = Momentum × MinimumValidation × DisciplineScore"""
    return clamp01(
        clamp01(signal.momentum)
        * clamp01(signal.minimum_validation)
        * clamp01(signal.discipline_score)
        * 2.5
    )


def _controlled_chaos_score(signal: TennisSignal) -> float:
    """InnovationValue = Unpredictability × Executability
    UsefulChaos = Chaos × Control
    """
    innovation = clamp01(clamp01(signal.unpredictability) * clamp01(signal.executability) * 1.7)
    useful = clamp01(clamp01(signal.chaos_score) * clamp01(signal.control) * 1.7)
    return weighted_mean({"innovation": (innovation, 0.5), "useful": (useful, 0.5)})


def _emotional_volatility_penalty(signal: TennisSignal) -> float:
    """VolatilityPenalty = EmotionalInstability × DecisionImpact
    UsableTalent = RawSkill − VolatilityCost
    """
    return clamp01(clamp01(signal.emotional_instability) * clamp01(signal.decision_impact) * 1.8)


def _repeatable_precision_score(signal: TennisSignal) -> float:
    """ExecutionQuality = Timing × Repeatability × ErrorControl"""
    return clamp01(
        clamp01(signal.timing)
        * clamp01(signal.repeatability)
        * clamp01(signal.error_control)
        * 2.5
    )


def _momentum_spike_score(signal: TennisSignal) -> float:
    """MomentumSpike = Velocity × Confidence × ExternalEnergy
    MomentumSignal = MomentumSpike × ValidationFloor
    """
    spike = clamp01(
        clamp01(signal.velocity)
        * clamp01(signal.confidence)
        * clamp01(signal.external_energy)
        * 2.5
    )
    return clamp01(spike * max(clamp01(signal.minimum_validation), 0.5))


def _aesthetic_trap_risk(signal: TennisSignal) -> float:
    """AdmissibleBeauty = AestheticSignal × StructuralReliability
    BeautyReliabilityGap = AestheticAppeal − StructuralReliability
    """
    beauty_gap = max(0.0, clamp01(signal.aesthetic_appeal) - clamp01(signal.structural_reliability))
    return clamp01(weighted_mean({"gap": (beauty_gap, 0.7), "low_reliability": (1.0 - clamp01(signal.structural_reliability), 0.3)}))


def _high_variance_risk(signal: TennisSignal) -> float:
    """NetValue = Upside − VariancePenalty
    HighVarianceRisk = Variance × LowRepeatability × ChaosExposure
    """
    return clamp01(
        clamp01(signal.variance_penalty)
        * clamp01(signal.low_repeatability)
        * clamp01(signal.chaos_exposure)
        * 2.5
    )


def _execution_readiness_score(signal: TennisSignal, scores: dict[str, float]) -> float:
    return weighted_mean(
        {
            "validation": (signal.validation_score, 0.18),
            "durability": (signal.durability_score or scores["durability_score"], 0.18),
            "survivability": (signal.execution_survivability, 0.16),
            "discipline": (signal.discipline_score, 0.12),
            "error_control": (signal.error_control, 0.12),
            "timing": (signal.timing_quality, 0.12),
            "structure": (1.0 - scores["aesthetic_trap_risk"], 0.12),
        }
    )


def _scores(signal: TennisSignal) -> dict[str, float]:
    scores = {
        "frictionless_score": _frictionless_score(signal),
        "durability_score": _durability_score(signal),
        "chaos_absorption_score": _chaos_absorption_score(signal),
        "pattern_break_score": _pattern_break_score(signal),
        "first_strike_score": _first_strike_score(signal),
        "dominance_score": _dominance_score(signal),
        "hybrid_fast_track_score": _hybrid_fast_track_score(signal),
        "controlled_chaos_score": _controlled_chaos_score(signal),
        "emotional_volatility_penalty": _emotional_volatility_penalty(signal),
        "repeatable_precision_score": _repeatable_precision_score(signal),
        "momentum_spike_score": _momentum_spike_score(signal),
        "aesthetic_trap_risk": _aesthetic_trap_risk(signal),
        "high_variance_risk": _high_variance_risk(signal),
    }
    scores["execution_readiness_score"] = _execution_readiness_score(signal, scores)
    return {key: round(clamp01(value), 4) for key, value in scores.items()}


def classify_execution_style(signal: dict) -> dict:
    item = _to_signal(signal)
    scores = _scores(item)
    beauty_signal = clamp01(weighted_mean({"appeal": (item.aesthetic_appeal, 0.6), "gap": (scores["aesthetic_trap_risk"], 0.4)}))
    pressure_durability_signal = weighted_mean(
        {
            "durability": (scores["durability_score"], 0.35),
            "stress_survival": (item.stress_survival, 0.25),
            "pressure_absorbed": (item.pressure_absorbed, 0.15),
            "repeatability": (item.repeatability, 0.15),
            "signal_strength": (item.signal_strength, 0.10),
        }
    )
    chaos_control_signal = weighted_mean(
        {
            "controlled_chaos": (scores["controlled_chaos_score"], 0.4),
            "unpredictability": (item.unpredictability, 0.2),
            "control": (item.control, 0.2),
            "executability": (item.executability, 0.2),
        }
    )
    aesthetic_signal = weighted_mean(
        {
            "appeal": (item.aesthetic_appeal, 0.25),
            "beauty_gap": (scores["aesthetic_trap_risk"], 0.45),
            "low_reliability": (1.0 - item.structural_reliability, 0.30),
        }
    )
    variance_signal = weighted_mean(
        {
            "variance_risk": (scores["high_variance_risk"], 0.6),
            "upside": (item.upside, 0.15),
            "chaos_exposure": (item.chaos_exposure, 0.15),
            "low_repeatability": (item.low_repeatability, 0.10),
        }
    )
    weighted_styles = {
        ExecutionStyle.FRICTIONLESS_CONTROL.value: weighted_mean(
            {
                "frictionless": (scores["frictionless_score"], 0.55),
                "timing": (item.timing_quality, 0.2),
                "error_control": (item.error_control, 0.15),
                "output_quality": (item.output_quality, 0.10),
            }
        ),
        ExecutionStyle.PRESSURE_DURABILITY.value: pressure_durability_signal,
        ExecutionStyle.CHAOS_ABSORPTION.value: weighted_mean(
            {
                "chaos_absorption": (scores["chaos_absorption_score"], 0.55),
                "volatility_tolerance": (item.volatility_tolerance, 0.15),
                "recovery_speed": (item.recovery_speed, 0.15),
                "pressure_absorbed": (item.pressure_absorbed, 0.15),
            }
        ),
        ExecutionStyle.PATTERN_DISRUPTION.value: scores["pattern_break_score"],
        ExecutionStyle.FIRST_STRIKE.value: weighted_mean(
            {
                "first_strike": (scores["first_strike_score"], 0.75),
                "shock": (item.initial_shock, 0.25),
            }
        ),
        ExecutionStyle.SINGLE_WEAPON_DOMINANCE.value: scores["dominance_score"],
        ExecutionStyle.HYBRID_FAST_TRACK.value: weighted_mean(
            {
                "hybrid": (scores["hybrid_fast_track_score"], 0.6),
                "momentum": (item.momentum, 0.25),
                "discipline": (item.discipline_score, 0.15),
            }
        ),
        ExecutionStyle.CONTROLLED_CHAOS.value: chaos_control_signal,
        ExecutionStyle.EMOTIONAL_VOLATILITY.value: clamp01(scores["emotional_volatility_penalty"] * 1.2),
        ExecutionStyle.REPEATABLE_PRECISION.value: weighted_mean(
            {
                "precision": (scores["repeatable_precision_score"], 0.55),
                "repeatability": (item.repeatability, 0.20),
                "error_control": (item.error_control, 0.15),
                "timing": (item.timing, 0.10),
            }
        ),
        ExecutionStyle.MOMENTUM_SPIKE.value: weighted_mean(
            {
                "spike": (scores["momentum_spike_score"], 0.7),
                "velocity": (item.velocity, 0.15),
                "external_energy": (item.external_energy, 0.15),
            }
        ),
        ExecutionStyle.AESTHETIC_RAW_SIGNAL.value: weighted_mean(
            {
                "beauty_signal": (beauty_signal, 0.25),
                "aesthetic_signal": (aesthetic_signal, 0.55),
                "detection": (item.detection_score, 0.20),
            }
        ),
        ExecutionStyle.HIGH_VARIANCE_SHOTMAKING.value: variance_signal,
    }
    if scores["aesthetic_trap_risk"] > THETA_AESTHETIC_GAP and item.structural_reliability <= 0.5:
        execution_style = ExecutionStyle.AESTHETIC_RAW_SIGNAL.value
    elif scores["high_variance_risk"] >= 0.6 and item.chaos_exposure >= 0.5:
        execution_style = ExecutionStyle.HIGH_VARIANCE_SHOTMAKING.value
    elif chaos_control_signal >= 0.72 and item.chaos_score >= 0.45 and item.control >= 0.7:
        execution_style = ExecutionStyle.CONTROLLED_CHAOS.value
    elif pressure_durability_signal >= 0.82 and item.stress_survival >= 0.85:
        execution_style = ExecutionStyle.PRESSURE_DURABILITY.value
    else:
        execution_style = max(weighted_styles.items(), key=lambda kv: kv[1])[0]
    return {
        "signal_id": item.signal_id,
        "execution_style": execution_style,
        "player_archetype": PLAYER_MAP[execution_style],
        "style_score": round(weighted_styles[execution_style], 4),
        "scores": scores,
    }


def score_tennis_archetype(signal: dict) -> dict:
    item = _to_signal(signal)
    classified = classify_execution_style(signal)
    scores = classified["scores"]
    return {
        "signal_id": item.signal_id,
        "execution_style": classified["execution_style"],
        "player_archetype": classified["player_archetype"],
        "scores": scores,
        "detected_signal_score": round(clamp01(item.detection_score), 4),
        "investable_signal_score": round(
            clamp01(item.detection_score)
            * clamp01(item.validation_score)
            * clamp01(item.durability_score or scores["durability_score"])
            * clamp01(item.execution_survivability)
            * (0.0 if item.policy_veto else 1.0),
            4,
        ),
    }


def apply_tennis_execution_gates(signal: dict, policy: dict | None = None) -> dict:
    item = _to_signal(signal)
    thresholds = load_thresholds()
    effective_policy = policy if isinstance(policy, dict) else {}
    policy_allowed = not bool(item.policy_veto or not effective_policy.get("allow_new_risk", not item.policy_veto))
    scored = score_tennis_archetype(signal)
    scores = scored["scores"]
    chaos_veto = clamp01(item.chaos_score) >= thresholds["theta_chaos_veto"]
    validation_floor_met = clamp01(item.minimum_validation or item.validation_score) >= thresholds["theta_validation_floor"]
    durability_met = clamp01(item.durability_score or scores["durability_score"]) >= thresholds["theta_durability"]
    fast_track_allowed = (
        clamp01(item.momentum) >= thresholds["theta_momentum"]
        and validation_floor_met
        and not chaos_veto
        and policy_allowed
        and bool(item.risk_cap_active)
    )
    execution_ready = (
        policy_allowed
        and not chaos_veto
        and validation_floor_met
        and durability_met
        and scores["execution_readiness_score"] >= thresholds["theta_execution_ready"]
        and item.entry_defined
        and item.invalidation_defined
        and item.sizing_defined
        and item.exit_defined
        and item.review_defined
    )

    bull_state = "MIURA"
    recommended_action = RecommendedAction.KEEP_IN_MIURA_RAW_DETECTION.value
    diagnosis_parts: list[str] = []

    if bool(item.pattern_shock) or scores["pattern_break_score"] >= 0.8:
        bull_state = "ISLERO"
        recommended_action = RecommendedAction.RECLASSIFY_ISLERO_PATTERN_SHOCK.value
        diagnosis_parts.append("Pattern shock override is active.")
    elif not policy_allowed:
        bull_state = "DIABLO"
        recommended_action = RecommendedAction.BLOCK_NO_NEW_RISK.value
        diagnosis_parts.append("Policy veto still outranks every tennis archetype.")
    elif chaos_veto:
        bull_state = "DIABLO"
        recommended_action = RecommendedAction.BLOCK_NO_NEW_RISK.value
        diagnosis_parts.append("Chaos veto blocks fast-track and execution readiness.")
    elif scores["emotional_volatility_penalty"] >= 0.65:
        bull_state = "DIABLO"
        recommended_action = RecommendedAction.BLOCK_NO_NEW_RISK.value
        diagnosis_parts.append("Emotional volatility is being treated as risk, not conviction.")
    elif scores["aesthetic_trap_risk"] > thresholds["theta_aesthetic_gap"] and not durability_met:
        bull_state = "MIURA"
        recommended_action = RecommendedAction.KEEP_IN_MIURA_RAW_DETECTION.value
        diagnosis_parts.append("Aesthetic appeal exceeds structural reliability.")
    elif not validation_floor_met:
        bull_state = "MIURA"
        recommended_action = RecommendedAction.KEEP_IN_MIURA_RAW_DETECTION.value
        diagnosis_parts.append("DetectedSignal != ExecutableSignal without validation floor.")
    elif durability_met and not execution_ready:
        bull_state = "MURCIELAGO"
        recommended_action = RecommendedAction.SEND_TO_MURCIELAGO_DURABILITY_VALIDATION.value
        diagnosis_parts.append("Signal survived durability review but is not execution-disciplined yet.")
        if fast_track_allowed and scored["execution_style"] in {
            ExecutionStyle.HYBRID_FAST_TRACK.value,
            ExecutionStyle.MOMENTUM_SPIKE.value,
            ExecutionStyle.FIRST_STRIKE.value,
        }:
            bull_state = "HURACAN"
            recommended_action = RecommendedAction.ALLOW_HURACAN_FAST_TRACK_WATCH.value
            diagnosis_parts.append("Momentum is usable only because validation floor and risk caps are active.")
        elif (
            scores["execution_readiness_score"] >= thresholds["theta_execution_ready"] * 0.9
            and item.entry_defined
            and item.invalidation_defined
            and item.sizing_defined
            and item.exit_defined
        ):
            bull_state = "AVENTADOR"
            recommended_action = RecommendedAction.PROMOTE_TO_AVENTADOR_ACTIONABLE_WATCHLIST.value
            diagnosis_parts.append("Promoted to actionable watchlist pending full execution discipline.")
    elif execution_ready:
        bull_state = "GALLARDO"
        recommended_action = RecommendedAction.READY_FOR_GALLARDO_EXECUTION_SIMULATION_ONLY.value
        diagnosis_parts.append("Execution discipline is complete, but this remains simulation-only.")
    else:
        bull_state = "AVENTADOR"
        recommended_action = RecommendedAction.PROMOTE_TO_AVENTADOR_ACTIONABLE_WATCHLIST.value
        diagnosis_parts.append("Actionable watchlist promotion is allowed but not execution authority.")

    if bull_state == "HURACAN" and not validation_floor_met:
        bull_state = "MIURA"
        recommended_action = RecommendedAction.KEEP_IN_MIURA_RAW_DETECTION.value
        diagnosis_parts.append("Momentum cannot override validation floor.")
    if scored["execution_style"] == ExecutionStyle.FIRST_STRIKE.value and chaos_veto:
        bull_state = "DIABLO"
        recommended_action = RecommendedAction.BLOCK_NO_NEW_RISK.value
    if scored["execution_style"] == ExecutionStyle.AESTHETIC_RAW_SIGNAL.value and bull_state == "GALLARDO":
        bull_state = "MURCIELAGO"
        recommended_action = RecommendedAction.SEND_TO_MURCIELAGO_DURABILITY_VALIDATION.value
        diagnosis_parts.append("Aesthetic raw signal cannot jump from MIURA to GALLARDO without deeper validation.")

    gates = {
        "policy_allowed": policy_allowed,
        "chaos_veto": chaos_veto,
        "validation_floor_met": validation_floor_met,
        "durability_met": durability_met,
        "fast_track_allowed": fast_track_allowed,
        "execution_ready": execution_ready and bull_state == "GALLARDO",
    }
    diagnosis = " ".join(diagnosis_parts) or "Execution style classified conservatively."
    return {
        "signal_id": item.signal_id,
        "execution_style": scored["execution_style"],
        "player_archetype": scored["player_archetype"],
        "bull_state": bull_state,
        "scores": scores,
        "gates": gates,
        "diagnosis": diagnosis,
        "recommended_action": recommended_action,
    }


def _artifact_payload(*, signals: list[dict[str, Any]], report: dict[str, Any], operating_mode: str) -> dict[str, Any]:
    return {
        "run_id": get_run_id(),
        "generated_at": utc_timestamp(),
        "module": "tennis_archetype_execution",
        "schema_version": SCHEMA_VERSION,
        "inputs": {
            "total_signal_inputs": len(signals),
            "data_quality": report["data_quality"],
            "live_ready": False,
        },
        "scores": {
            "chaos_veto_count": report["chaos_veto_count"],
            "fast_track_candidate_count": report["fast_track_candidate_count"],
            "durability_pass_count": report["durability_pass_count"],
            "execution_ready_simulation_only_count": report["execution_ready_simulation_only_count"],
        },
        "state": report["dominant_bull_state"],
        "vetoes": ["POLICY_RESTRICTED"] if report["policy_veto_observed"] else [],
        "recommendation": report["summary_recommendation"],
        "rationale": report["rationale"],
        "source_mode": get_source_mode(),
        "operating_mode": operating_mode,
        "truth_origin": report["truth_origin"],
        "data_quality": report["data_quality"],
        "live_ready": False,
        "distribution_by_execution_style": report["distribution_by_execution_style"],
        "distribution_by_player_archetype": report["distribution_by_player_archetype"],
        "distribution_by_bull_state": report["distribution_by_bull_state"],
        "classified_signals": report["signals"],
    }


def generate_tennis_archetype_report(
    signals: list[dict],
    policy: dict[str, Any] | None = None,
) -> dict:
    thresholds = load_thresholds()
    effective_policy = policy if isinstance(policy, dict) else None
    classified = [apply_tennis_execution_gates(signal, policy=effective_policy) for signal in signals]
    style_counts = Counter(item["execution_style"] for item in classified)
    player_counts = Counter(item["player_archetype"] for item in classified)
    bull_counts = Counter(item["bull_state"] for item in classified)
    chaos_veto_count = sum(1 for item in classified if item["gates"]["chaos_veto"] or not item["gates"]["policy_allowed"])
    fast_track_count = sum(1 for item in classified if item["gates"]["fast_track_allowed"])
    aesthetic_trap_count = sum(1 for item in classified if item["scores"]["aesthetic_trap_risk"] > thresholds["theta_aesthetic_gap"])
    high_variance_count = sum(1 for item in classified if item["scores"]["high_variance_risk"] >= 0.6)
    durability_pass_count = sum(1 for item in classified if item["gates"]["durability_met"])
    execution_ready_count = sum(1 for item in classified if item["recommended_action"] == RecommendedAction.READY_FOR_GALLARDO_EXECUTION_SIMULATION_ONLY.value)

    def top_n(predicate: Any, score_key: str) -> list[dict[str, Any]]:
        rows = [item for item in classified if predicate(item)]
        rows.sort(key=lambda row: row["scores"][score_key], reverse=True)
        return rows[:5]

    report = {
        "total_signals": len(classified),
        "signals": classified,
        "distribution_by_execution_style": dict(style_counts),
        "distribution_by_player_archetype": dict(player_counts),
        "distribution_by_bull_state": dict(bull_counts),
        "chaos_veto_count": chaos_veto_count,
        "fast_track_candidate_count": fast_track_count,
        "aesthetic_trap_count": aesthetic_trap_count,
        "high_variance_count": high_variance_count,
        "durability_pass_count": durability_pass_count,
        "execution_ready_simulation_only_count": execution_ready_count,
        "top_5_execution_ready_simulation_only": top_n(lambda item: item["recommended_action"] == RecommendedAction.READY_FOR_GALLARDO_EXECUTION_SIMULATION_ONLY.value, "execution_readiness_score"),
        "top_5_blocked_by_chaos": top_n(lambda item: item["recommended_action"] == RecommendedAction.BLOCK_NO_NEW_RISK.value, "chaos_absorption_score"),
        "top_5_aesthetic_traps": top_n(lambda item: item["scores"]["aesthetic_trap_risk"] > thresholds["theta_aesthetic_gap"], "aesthetic_trap_risk"),
        "top_5_first_strike_candidates": top_n(lambda item: item["execution_style"] == ExecutionStyle.FIRST_STRIKE.value, "first_strike_score"),
        "top_5_repeatable_precision_candidates": top_n(lambda item: item["execution_style"] == ExecutionStyle.REPEATABLE_PRECISION.value, "repeatable_precision_score"),
        "dominant_execution_style": style_counts.most_common(1)[0][0] if style_counts else ExecutionStyle.AESTHETIC_RAW_SIGNAL.value,
        "dominant_player_archetype": player_counts.most_common(1)[0][0] if player_counts else "UNKNOWN",
        "dominant_bull_state": bull_counts.most_common(1)[0][0] if bull_counts else "MIURA",
        "summary_recommendation": top_n(lambda item: True, "execution_readiness_score")[0]["recommended_action"] if classified else RecommendedAction.KEEP_IN_MIURA_RAW_DETECTION.value,
        "rationale": [
            "DetectedSignal != ExecutableSignal",
            "Validation floor outranks momentum",
            "Policy veto outranks execution style",
            "Aesthetic appeal cannot override durability",
        ],
        "policy_veto_observed": any(not item["gates"]["policy_allowed"] for item in classified),
        "data_quality": "synthetic_or_runtime_fallback" if any(str(item.get("source", "")).startswith("synthetic") for item in signals) else "runtime_proxy",
        "truth_origin": "seeded",
        "report_path": repo_relative(TENNIS_ARCHETYPE_REPORT_PATH),
    }
    return report


def write_tennis_archetype_report(
    signals: list[dict[str, Any]],
    runtime_state: dict[str, Any] | None = None,
    output_path: Path | None = None,
    write_runtime: bool = True,
) -> dict[str, Any]:
    policy = (runtime_state or {}).get("execution_policy", {}) if isinstance(runtime_state, dict) else {}
    report = generate_tennis_archetype_report(signals, policy=policy)
    operating_mode = classify_operating_mode(runtime_state or {})
    payload = _artifact_payload(signals=signals, report=report, operating_mode=operating_mode)
    if write_runtime:
        write_json_atomic(output_path or TENNIS_ARCHETYPE_REPORT_PATH, payload, stamp=False)
    report["artifact"] = payload
    return report


def load_runtime_compatible_signals(
    *,
    runtime_state: dict[str, Any] | None = None,
    signal_refinery_report: dict[str, Any] | None = None,
    perception_control_report: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    state = runtime_state if isinstance(runtime_state, dict) else {}
    refinement = signal_refinery_report if isinstance(signal_refinery_report, dict) else {}
    perception = perception_control_report if isinstance(perception_control_report, dict) else {}
    validation_rows = refinement.get("validation_engine", {}).get("signals", [])
    if isinstance(validation_rows, list) and validation_rows:
        rows: list[dict[str, Any]] = []
        for index, row in enumerate(validation_rows):
            if not isinstance(row, dict):
                continue
            rows.append(
                {
                    "signal_id": str(row.get("ticker") or f"signal_{index}"),
                    "detection_score": row.get("validation_score", 0.0),
                    "output_quality": row.get("first_order_score", 0.0),
                    "energy_cost": 1.0 - float(row.get("blocker_clearance_score", 0.0) or 0.0),
                    "timing_quality": row.get("repricing_headroom_score", 0.0),
                    "error_control": row.get("blocker_clearance_score", 0.0),
                    "performance_after_stress": row.get("blocker_clearance_score", 0.0),
                    "performance_before_stress": row.get("validation_score", 1.0) or 1.0,
                    "signal_strength": row.get("validation_score", 0.0),
                    "stress_survival": perception.get("signal_survival_rate", 0.0),
                    "repeatability": perception.get("signal_survival_rate", 0.0),
                    "volatility_tolerance": state.get("signal_summary", {}).get("scm_rate", 0.0),
                    "recovery_speed": perception.get("noise_suppression_ratio", 0.0),
                    "pressure_absorbed": row.get("blocker_clearance_score", 0.0),
                    "timing": row.get("repricing_headroom_score", 0.0),
                    "pattern_dependence": row.get("novelty_score", 0.0),
                    "disruption_timing": row.get("novelty_score", 0.0),
                    "opponent_adjustment_lag": row.get("cross_source_confirmation_score", 0.0),
                    "initial_shock": row.get("novelty_score", 0.0),
                    "reaction_delay": row.get("repricing_headroom_score", 0.0),
                    "timing_window": row.get("repricing_headroom_score", 0.0),
                    "minimum_validation": row.get("validation_score", 0.0),
                    "weapon_strength": row.get("source_quality_score", 0.0),
                    "access_frequency": row.get("first_order_score", 0.0),
                    "pressure_access": row.get("blocker_clearance_score", 0.0),
                    "dominant_variable": row.get("source_quality_score", 0.0),
                    "momentum": state.get("signal_summary", {}).get("scm_rate", 0.0),
                    "discipline_score": perception.get("noise_suppression_ratio", 0.0),
                    "chaos_score": 1.0 if not state.get("execution_policy", {}).get("allow_new_risk", False) else 0.3,
                    "unpredictability": row.get("novelty_score", 0.0),
                    "executability": row.get("blocker_clearance_score", 0.0),
                    "control": perception.get("noise_suppression_ratio", 0.0),
                    "emotional_instability": state.get("signal_summary", {}).get("signals_above_ce_threshold", 0.0) / 10.0,
                    "decision_impact": row.get("validation_score", 0.0),
                    "raw_skill": row.get("validation_score", 0.0),
                    "velocity": row.get("novelty_score", 0.0),
                    "confidence": row.get("validation_score", 0.0),
                    "external_energy": row.get("cross_source_confirmation_score", 0.0),
                    "aesthetic_appeal": row.get("novelty_score", 0.0),
                    "structural_reliability": row.get("blocker_clearance_score", 0.0),
                    "upside": row.get("repricing_headroom_score", 0.0),
                    "variance_penalty": 1.0 - float(row.get("blocker_clearance_score", 0.0) or 0.0),
                    "low_repeatability": 1.0 - float(perception.get("signal_survival_rate", 0.0) or 0.0),
                    "chaos_exposure": 1.0 if not state.get("execution_policy", {}).get("allow_new_risk", False) else 0.3,
                    "validation_score": row.get("validation_score", 0.0),
                    "durability_score": row.get("blocker_clearance_score", 0.0),
                    "execution_survivability": row.get("blocker_clearance_score", 0.0),
                    "heat_score": 0.0,
                    "risk_guard_score": 1.0 if not state.get("execution_policy", {}).get("allow_new_risk", False) else 0.3,
                    "policy_veto": not state.get("execution_policy", {}).get("allow_new_risk", False),
                    "can_deploy_capital": bool(state.get("execution_policy", {}).get("allow_new_risk", False)),
                    "risk_cap_active": True,
                    "entry_defined": row.get("blocker_clearance_score", 0.0) >= 0.65,
                    "invalidation_defined": row.get("blocker_clearance_score", 0.0) >= 0.65,
                    "sizing_defined": bool(state.get("execution_policy", {}).get("policy_state")),
                    "exit_defined": row.get("blocker_clearance_score", 0.0) >= 0.65,
                    "review_defined": True,
                    "pattern_shock": False,
                    "source": "runtime_proxy",
                }
            )
        return rows
    return synthetic_signals()


def synthetic_signals() -> list[dict[str, Any]]:
    return [
        {
            "signal_id": "FEDERER_SYNTH",
            "detection_score": 0.75,
            "output_quality": 0.92,
            "energy_cost": 0.15,
            "timing_quality": 0.9,
            "error_control": 0.9,
            "performance_after_stress": 0.82,
            "performance_before_stress": 0.9,
            "signal_strength": 0.85,
            "stress_survival": 0.78,
            "repeatability": 0.9,
            "volatility_tolerance": 0.65,
            "recovery_speed": 0.8,
            "pressure_absorbed": 0.72,
            "timing": 0.88,
            "minimum_validation": 0.8,
            "validation_score": 0.8,
            "durability_score": 0.78,
            "execution_survivability": 0.82,
            "entry_defined": True,
            "invalidation_defined": True,
            "sizing_defined": True,
            "exit_defined": True,
            "review_defined": True,
            "can_deploy_capital": False,
            "risk_cap_active": True,
            "source": "synthetic",
        },
        {
            "signal_id": "NADAL_SYNTH",
            "signal_strength": 0.84,
            "performance_after_stress": 0.9,
            "performance_before_stress": 0.92,
            "stress_survival": 0.92,
            "repeatability": 0.85,
            "validation_score": 0.72,
            "durability_score": 0.85,
            "execution_survivability": 0.68,
            "minimum_validation": 0.72,
            "source": "synthetic",
        },
        {
            "signal_id": "BUBLIK_SYNTH",
            "chaos_score": 0.69,
            "unpredictability": 0.88,
            "executability": 0.72,
            "control": 0.74,
            "validation_score": 0.6,
            "minimum_validation": 0.6,
            "source": "synthetic",
        },
    ]


def format_tennis_archetype_summary(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Tennis Archetype Execution Layer",
            f"total_signals={report.get('total_signals', 0)}",
            f"strongest_archetype={report.get('dominant_player_archetype', 'UNKNOWN')}",
            f"most_common_execution_style={report.get('dominant_execution_style', 'UNKNOWN')}",
            f"chaos_veto_count={report.get('chaos_veto_count', 0)}",
            f"fast_track_candidates={report.get('fast_track_candidate_count', 0)}",
            f"execution_ready_simulation_only_count={report.get('execution_ready_simulation_only_count', 0)}",
            "warning=all inputs are seeded/synthetic"
            if report.get("data_quality") == "synthetic_or_runtime_fallback"
            else "warning=using runtime proxy inputs",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run tennis archetype execution diagnostics.")
    parser.add_argument("--summary", action="store_true", help="Emit concise summary.")
    args = parser.parse_args(argv)
    report = write_tennis_archetype_report(synthetic_signals(), runtime_state={})
    if args.summary:
        print(format_tennis_archetype_summary(report))
    else:
        print(json.dumps(report["artifact"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
