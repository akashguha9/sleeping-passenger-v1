from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, fields
from enum import Enum
from pathlib import Path
from typing import Any

try:
    from scripts.runtime_common import (
        CHESS_ARCHETYPE_REPORT_PATH,
        REPO_ROOT,
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
        CHESS_ARCHETYPE_REPORT_PATH,
        REPO_ROOT,
        classify_operating_mode,
        get_run_id,
        get_source_mode,
        load_json_file,
        repo_relative,
        utc_timestamp,
        write_json_atomic,
    )


CONFIG_PATH = REPO_ROOT / "config" / "chess_archetype_config.json"
SCHEMA_VERSION = "1.0"
EPSILON = 1e-6


class ChessArchetype(str, Enum):
    MORPHY = "morphy_tempo_fast_track"
    STEINITZ = "steinitz_positional_justification"
    LASKER = "lasker_practical_discomfort"
    CAPABLANCA = "capablanca_simplification"
    ALEKHINE = "alekhine_prepared_attack"
    BOTVINNIK = "botvinnik_process_review"
    TAL = "tal_chaos_generation"
    PETROSIAN = "petrosian_hidden_risk"
    FISCHER = "fischer_forced_line"
    SPASSKY = "spassky_adaptive_balance"
    KARPOV = "karpov_durability_validation"
    KRAMNIK = "kramnik_neutralization"
    ANAND = "anand_adaptive_speed"
    KASPAROV = "kasparov_initiative_promotion"
    CARLSEN = "carlsen_conversion"
    CARUANA = "caruana_precision_validation"
    DING = "ding_recovery_stability"


class PositionState(str, Enum):
    RAW_SIGNAL = "RAW_SIGNAL"
    EQUAL_POSITION = "EQUAL_POSITION"
    POSITIONAL_EDGE = "POSITIONAL_EDGE"
    INITIATIVE = "INITIATIVE"
    CHAOS = "CHAOS"
    FORCED_LINE = "FORCED_LINE"
    DURABLE_SIGNAL = "DURABLE_SIGNAL"
    ACTIONABLE_SIGNAL = "ACTIONABLE_SIGNAL"
    EXECUTABLE_SIGNAL = "EXECUTABLE_SIGNAL"
    RECOVERY_STATE = "RECOVERY_STATE"
    NO_NEW_RISK = "NO_NEW_RISK"
    VETOED = "VETOED"


class DecisionState(str, Enum):
    WAIT = "WAIT"
    WATCH = "WATCH"
    VALIDATE = "VALIDATE"
    PROMOTE = "PROMOTE"
    EXECUTE = "EXECUTE"
    SIMPLIFY = "SIMPLIFY"
    RECOVER = "RECOVER"
    VETO = "VETO"


DEFAULT_THRESHOLDS = {
    "theta_shock": 0.74,
    "theta_durability": 0.60,
    "theta_hidden_risk": 0.60,
    "theta_precision_margin": 0.10,
    "theta_validation_floor": 0.55,
    "theta_operator_veto": 0.70,
    "theta_fast_track": 0.60,
    "theta_execution_feasibility": 0.65,
    "theta_state_actionable": 0.62,
    "theta_initiative": 0.60,
}


@dataclass(slots=True)
class ChessSignal:
    signal_id: str
    detection_score: float = 0.0
    signal_strength: float = 0.0
    evidence_depth: float = 0.0
    volatility: float = 0.0
    contradiction_level: float = 0.0
    timing_window: float = 0.0
    liquidity_risk: float = 0.0
    operator_readiness: float = 0.0
    external_confirmation: float = 0.0
    hidden_risk_score: float = 0.0
    control_score: float = 0.0
    chaos_score: float = 0.0
    collapse_risk: float = 0.0
    operator_confusion: float = 0.0
    policy_risk: float = 0.0
    structural_edge: float = 0.0
    narrative_heat: float = 0.0
    performance_after_stress: float = 0.0
    performance_before_stress: float = 1.0
    stress_survival: float = 0.0
    counterplay_reduction: float = 0.0
    persistence: float = 0.0
    confirmation_depth: float = 0.0
    maintenance_cost: float = 0.0
    execution_survivability: float = 0.0
    initiative: float = 0.0
    feasibility: float = 0.0
    asymmetry: float = 0.0
    residual_risk: float = 0.0
    minimum_validation: float = 0.0
    momentum_spike: float = 0.0
    risk_cap: float = 0.0
    freshness: float = 0.0
    repricing_lag: float = 0.0
    crowd_saturation: float = 0.0
    anomaly: float = 0.0
    narrative_instability: float = 0.0
    sentiment_divergence: float = 0.0
    volume_shock: float = 0.0
    opponent_overload_potential: float = 0.0
    self_collapse_risk: float = 0.0
    option_margin: float = 0.5
    analysis_depth: float = 0.0
    error_suppression: float = 0.0
    complexity_cost: float = 0.0
    information_gain: float = 0.0
    optionality_loss: float = 0.0
    shock_event_score: float = 0.0
    event_certainty: float = 0.0
    repricing_probability: float = 0.0
    structural_impact: float = 0.0
    preparation: float = 0.0
    target_weakness: float = 0.0
    exposure_cost: float = 0.0
    review_depth: float = 0.0
    method_update: float = 0.0
    cognitive_load: float = 0.0
    time_pressure: float = 0.0
    ambiguity: float = 0.0
    crowding: float = 0.0
    incentive_conflict: float = 0.0
    battlefield_choice: float = 0.0
    opponent_strength_neutralization: float = 0.0
    adaptive_speed: float = 0.0
    style_flexibility: float = 0.0
    style_drift: float = 0.0
    low_error_rate: float = 0.0
    execution_quality: float = 0.0
    exit_quality: float = 0.0
    counterplay: float = 0.0
    friction_cost: float = 0.0
    operator_misfit: float = 0.0
    drawdown: float = 0.0
    uncertainty: float = 0.0
    operator_stress: float = 0.0
    entry_defined: bool = False
    sizing_defined: bool = False
    invalidation_defined: bool = False
    exit_defined: bool = False
    review_defined: bool = False
    policy_veto: bool = False
    can_deploy_capital: bool = False
    risk_cap_passed: bool = False
    source: str = "synthetic"


def clamp01(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def safe_div(a: Any, b: Any, default: float = 0.0) -> float:
    try:
        denominator = float(b)
    except (TypeError, ValueError):
        return default
    if abs(denominator) < EPSILON:
        return default
    try:
        numerator = float(a)
    except (TypeError, ValueError):
        return default
    return clamp01(numerator / denominator)


def weighted_mean(parts: dict[str, tuple[float, float]]) -> float:
    total_weight = 0.0
    weighted_total = 0.0
    for value, weight in parts.values():
        weighted_total += clamp01(value) * float(weight)
        total_weight += float(weight)
    if total_weight <= 0.0:
        return 0.0
    return clamp01(weighted_total / total_weight)


def load_thresholds() -> dict[str, float]:
    thresholds = dict(DEFAULT_THRESHOLDS)
    payload = load_json_file(CONFIG_PATH, default={})
    if isinstance(payload, dict):
        for key, default in DEFAULT_THRESHOLDS.items():
            thresholds[key] = clamp01(payload.get(key, default))
    return thresholds


def _to_signal(signal: dict[str, Any]) -> ChessSignal:
    raw = dict(signal)
    signal_id = str(raw.get("signal_id") or raw.get("ticker") or raw.get("name") or "UNKNOWN")
    incoming = {
        "signal_strength": raw.get("signal_strength", raw.get("detection_score", 0.0)),
        "evidence_depth": raw.get("evidence_depth", raw.get("validation_score", 0.0)),
        "volatility": raw.get("volatility", raw.get("chaos_score", 0.0)),
        "contradiction_level": raw.get("contradiction_level", raw.get("low_repeatability", 0.0)),
        "timing_window": raw.get("timing_window", raw.get("timing_quality", 0.0)),
        "liquidity_risk": raw.get("liquidity_risk", raw.get("chaos_exposure", 0.0)),
        "operator_readiness": raw.get("operator_readiness", raw.get("discipline_score", 0.0)),
        "external_confirmation": raw.get("external_confirmation", raw.get("external_energy", 0.0)),
        "hidden_risk_score": raw.get(
            "hidden_risk_score",
            weighted_mean(
                {
                    "variance": (raw.get("variance_penalty", 0.0), 0.35),
                    "chaos": (raw.get("chaos_exposure", 0.0), 0.35),
                    "fragility": (1.0 - raw.get("structural_reliability", 0.0), 0.30),
                }
            ),
        ),
        "control_score": raw.get("control_score", raw.get("control", 0.0)),
        "chaos_score": raw.get("chaos_score", 0.0),
        "collapse_risk": raw.get("collapse_risk", raw.get("variance_penalty", 0.0)),
        "operator_confusion": raw.get("operator_confusion", 1.0 - raw.get("discipline_score", 0.0)),
        "policy_risk": raw.get("policy_risk", 1.0 if raw.get("policy_veto", False) else 0.0),
        "structural_edge": raw.get("structural_edge", raw.get("structural_reliability", 0.0)),
        "narrative_heat": raw.get("narrative_heat", raw.get("external_energy", 0.0)),
        "performance_after_stress": raw.get("performance_after_stress", raw.get("durability_score", 0.0)),
        "performance_before_stress": raw.get("performance_before_stress", 1.0),
        "stress_survival": raw.get("stress_survival", raw.get("durability_score", 0.0)),
        "counterplay_reduction": raw.get("counterplay_reduction", raw.get("error_control", 0.0)),
        "persistence": raw.get("persistence", raw.get("repeatability", 0.0)),
        "confirmation_depth": raw.get("confirmation_depth", raw.get("validation_score", 0.0)),
        "maintenance_cost": raw.get("maintenance_cost", raw.get("friction_cost", raw.get("energy_cost", 0.0))),
        "execution_survivability": raw.get("execution_survivability", raw.get("execution_survivability", 0.0)),
        "initiative": raw.get("initiative", raw.get("momentum", 0.0)),
        "feasibility": raw.get("feasibility", raw.get("executability", 0.0)),
        "asymmetry": raw.get("asymmetry", raw.get("upside", 0.0)),
        "residual_risk": raw.get("residual_risk", raw.get("variance_penalty", 0.0)),
        "minimum_validation": raw.get("minimum_validation", raw.get("validation_score", 0.0)),
        "momentum_spike": raw.get("momentum_spike", raw.get("momentum", 0.0)),
        "risk_cap": raw.get("risk_cap", 1.0 if raw.get("risk_cap_active", False) else 0.0),
        "freshness": raw.get("freshness", raw.get("confidence", 0.0)),
        "repricing_lag": raw.get("repricing_lag", raw.get("reaction_delay", 0.0)),
        "crowd_saturation": raw.get("crowd_saturation", raw.get("crowding", 0.0)),
        "anomaly": raw.get("anomaly", raw.get("unpredictability", 0.0)),
        "narrative_instability": raw.get("narrative_instability", raw.get("chaos_score", 0.0)),
        "sentiment_divergence": raw.get("sentiment_divergence", raw.get("aesthetic_appeal", 0.0)),
        "volume_shock": raw.get("volume_shock", raw.get("initial_shock", 0.0)),
        "opponent_overload_potential": raw.get("opponent_overload_potential", raw.get("pressure_absorbed", 0.0)),
        "self_collapse_risk": raw.get("self_collapse_risk", raw.get("variance_penalty", 0.0)),
        "option_margin": raw.get("option_margin", 0.5),
        "analysis_depth": raw.get("analysis_depth", raw.get("validation_score", 0.0)),
        "error_suppression": raw.get("error_suppression", raw.get("error_control", 0.0)),
        "complexity_cost": raw.get("complexity_cost", raw.get("energy_cost", 0.0)),
        "information_gain": raw.get("information_gain", raw.get("signal_strength", raw.get("detection_score", 0.0))),
        "optionality_loss": raw.get("optionality_loss", 0.0),
        "shock_event_score": raw.get("shock_event_score", raw.get("pattern_break_score", 0.0)),
        "event_certainty": raw.get("event_certainty", raw.get("confidence", 0.0)),
        "repricing_probability": raw.get("repricing_probability", raw.get("repricing_lag", 0.0)),
        "structural_impact": raw.get("structural_impact", raw.get("structural_reliability", 0.0)),
        "preparation": raw.get("preparation", raw.get("review_depth", raw.get("validation_score", 0.0))),
        "target_weakness": raw.get("target_weakness", raw.get("dominant_variable", 0.0)),
        "exposure_cost": raw.get("exposure_cost", raw.get("liquidity_risk", raw.get("chaos_exposure", 0.0))),
        "review_depth": raw.get("review_depth", 1.0 if raw.get("review_defined", False) else raw.get("validation_score", 0.0)),
        "method_update": raw.get("method_update", raw.get("discipline_score", 0.0)),
        "cognitive_load": raw.get("cognitive_load", 1.0 - raw.get("discipline_score", 0.0)),
        "time_pressure": raw.get("time_pressure", raw.get("timing_window", 0.0)),
        "ambiguity": raw.get("ambiguity", raw.get("low_repeatability", 0.0)),
        "crowding": raw.get("crowding", raw.get("crowd_saturation", 0.0)),
        "incentive_conflict": raw.get("incentive_conflict", raw.get("chaos_exposure", 0.0)),
        "battlefield_choice": raw.get("battlefield_choice", 1.0 - raw.get("chaos_exposure", 0.0)),
        "opponent_strength_neutralization": raw.get("opponent_strength_neutralization", raw.get("control", 0.0)),
        "adaptive_speed": raw.get("adaptive_speed", raw.get("velocity", 0.0)),
        "style_flexibility": raw.get("style_flexibility", raw.get("control", 0.0)),
        "style_drift": raw.get("style_drift", raw.get("chaos_score", 0.0) * 0.5),
        "low_error_rate": raw.get("low_error_rate", raw.get("error_control", 0.0)),
        "execution_quality": raw.get("execution_quality", raw.get("timing_quality", 0.0)),
        "exit_quality": raw.get("exit_quality", raw.get("timing_quality", 0.0)),
        "counterplay": raw.get("counterplay", raw.get("chaos_exposure", 0.0)),
        "friction_cost": raw.get("friction_cost", raw.get("energy_cost", 0.0)),
        "operator_misfit": raw.get("operator_misfit", 1.0 - raw.get("discipline_score", 0.0)),
        "drawdown": raw.get("drawdown", 0.0),
        "uncertainty": raw.get("uncertainty", raw.get("low_repeatability", 0.0)),
        "operator_stress": raw.get("operator_stress", 1.0 - raw.get("discipline_score", 0.0)),
        "entry_defined": raw.get("entry_defined", False),
        "sizing_defined": raw.get("sizing_defined", False),
        "invalidation_defined": raw.get("invalidation_defined", False),
        "exit_defined": raw.get("exit_defined", False),
        "review_defined": raw.get("review_defined", False),
        "policy_veto": raw.get("policy_veto", False),
        "can_deploy_capital": raw.get("can_deploy_capital", False),
        "risk_cap_passed": raw.get("risk_cap_passed", raw.get("risk_cap_active", False)),
        "source": raw.get("source", "synthetic"),
        "detection_score": raw.get("detection_score", 0.0),
    }
    allowed = {field.name for field in fields(ChessSignal) if field.name != "signal_id"}
    filtered = {key: value for key, value in incoming.items() if key in allowed}
    return ChessSignal(signal_id=signal_id, **filtered)


def _state_classification_score(signal: ChessSignal) -> float:
    return weighted_mean(
        {
            "signal_strength": (signal.signal_strength, 0.15),
            "evidence_depth": (signal.evidence_depth, 0.15),
            "volatility_control": (1.0 - signal.volatility, 0.08),
            "contradiction_control": (1.0 - signal.contradiction_level, 0.10),
            "timing_window": (signal.timing_window, 0.10),
            "liquidity_control": (1.0 - signal.liquidity_risk, 0.10),
            "operator_readiness": (signal.operator_readiness, 0.10),
            "external_confirmation": (signal.external_confirmation, 0.12),
            "hidden_risk_clearance": (1.0 - signal.hidden_risk_score, 0.10),
        }
    )


def _tempo_advantage(signal: ChessSignal) -> dict[str, Any]:
    # FastTrack = MomentumSpike × MinimumValidation × RiskCap × Freshness × RepricingLag − CollapseRisk
    fast_track_score = clamp01(
        clamp01(signal.momentum_spike)
        * clamp01(signal.minimum_validation)
        * clamp01(signal.risk_cap)
        * clamp01(signal.freshness)
        * clamp01(signal.repricing_lag)
        * 6.0
        - clamp01(signal.collapse_risk) * 0.4
    )
    delay_cost = weighted_mean(
        {
            "momentum": (signal.momentum_spike, 0.35),
            "repricing": (signal.repricing_lag, 0.35),
            "freshness": (signal.freshness, 0.30),
        }
    )
    validation_benefit = weighted_mean(
        {
            "evidence": (signal.evidence_depth, 0.5),
            "hidden_risk_clearance": (1.0 - signal.hidden_risk_score, 0.5),
        }
    )
    return {
        "fast_track_candidate": False,
        "fast_track_score": round(fast_track_score, 4),
        "required_risk_cap": bool(signal.risk_cap_passed),
        "delay_cost": delay_cost,
        "validation_benefit": validation_benefit,
        "explanation": "Tempo only matters when minimum validation and risk caps are already present.",
    }


def _positional_justification(signal: ChessSignal) -> dict[str, Any]:
    structural_edge_score = weighted_mean(
        {
            "structural_edge": (signal.structural_edge, 0.40),
            "evidence_depth": (signal.evidence_depth, 0.30),
            "external_confirmation": (signal.external_confirmation, 0.20),
            "control": (signal.control_score, 0.10),
        }
    )
    reasons: list[str] = []
    if signal.structural_edge < 0.55:
        reasons.append("structural_edge_below_threshold")
    if signal.evidence_depth < 0.55:
        reasons.append("evidence_depth_below_threshold")
    if signal.narrative_heat > 0.75 and signal.structural_edge < 0.65:
        reasons.append("narrative_heat_without_structure")
    if signal.chaos_score > 0.6 and signal.control_score < 0.5:
        reasons.append("chaos_without_control")
    return {
        "positional_justification_passed": not reasons,
        "structural_edge_score": round(structural_edge_score, 4),
        "missing_justification_reasons": reasons,
    }


def _chaos_hypothesis(signal: ChessSignal) -> dict[str, Any]:
    # ChaosHypothesis = Anomaly × NarrativeInstability × SentimentDivergence × VolumeShock × OpponentOverloadPotential
    raw_hypothesis_score = clamp01(
        clamp01(signal.anomaly)
        * clamp01(signal.narrative_instability)
        * clamp01(signal.sentiment_divergence)
        * clamp01(signal.volume_shock)
        * clamp01(signal.opponent_overload_potential)
        * 8.0
    )
    productive = clamp01(signal.opponent_overload_potential - signal.self_collapse_risk + raw_hypothesis_score * 0.5)
    pure_noise_probability = clamp01(
        weighted_mean(
            {
                "collapse": (signal.self_collapse_risk, 0.40),
                "contradiction": (signal.contradiction_level, 0.30),
                "low_confirmation": (1.0 - signal.external_confirmation, 0.30),
            }
        )
    )
    return {
        "raw_hypothesis": raw_hypothesis_score >= 0.35,
        "chaos_score": round(raw_hypothesis_score, 4),
        "productive_chaos_score": round(productive, 4),
        "pure_noise_probability": round(pure_noise_probability, 4),
        "required_validation_path": [
            "diablo_chaos_veto",
            "karpov_durability_validation",
            "steinitz_positional_justification",
        ],
    }


def _chaos_veto(signal: ChessSignal, *, policy_veto: bool, thresholds: dict[str, float]) -> dict[str, Any]:
    vetoed = bool(
        policy_veto
        or signal.chaos_score > signal.control_score
        or signal.collapse_risk > signal.opponent_overload_potential
        or signal.operator_confusion > thresholds["theta_operator_veto"]
        or signal.policy_risk > thresholds["theta_operator_veto"]
    )
    if policy_veto:
        reason = "policy_veto"
    elif signal.chaos_score > signal.control_score:
        reason = "chaos_exceeds_control"
    elif signal.collapse_risk > signal.opponent_overload_potential:
        reason = "collapse_risk_exceeds_overload_value"
    elif signal.operator_confusion > thresholds["theta_operator_veto"]:
        reason = "operator_confusion"
    elif signal.policy_risk > thresholds["theta_operator_veto"]:
        reason = "policy_risk"
    else:
        reason = "clear"
    return {
        "vetoed": vetoed,
        "veto_reason": reason,
        "chaos_control_gap": round(clamp01(signal.chaos_score - signal.control_score + 0.5), 4),
        "recommended_state": "NO_NEW_RISK" if vetoed else "WATCH",
    }


def _hidden_risk(signal: ChessSignal, thresholds: dict[str, float]) -> dict[str, Any]:
    risk_candidates = {
        "liquidity_fragility": clamp01(signal.liquidity_risk * signal.timing_window),
        "news_reversal_risk": clamp01(signal.narrative_heat * signal.contradiction_level),
        "crowding_risk": clamp01(signal.crowding * signal.volatility),
        "correlation_shock_risk": clamp01(signal.chaos_score * signal.collapse_risk),
        "execution_slippage_risk": clamp01(signal.friction_cost * signal.exposure_cost),
        "operator_overload_risk": clamp01(signal.operator_stress * signal.operator_confusion),
    }
    top = sorted(risk_candidates.items(), key=lambda kv: kv[1], reverse=True)[:3]
    hidden_risk_score = round(max(value for _, value in top), 4) if top else 0.0
    passed = hidden_risk_score < thresholds["theta_hidden_risk"]
    return {
        "hidden_risk_score": hidden_risk_score,
        "top_3_hidden_risks": top,
        "prophylaxis_action": "neutralize_before_promotion" if not passed else "risk_clear",
        "passed": passed,
    }


def _durability(signal: ChessSignal, thresholds: dict[str, float]) -> dict[str, Any]:
    # DurableSignal = Signal × StressSurvival × CounterplayReduction × Persistence × ConfirmationDepth
    durable_signal = clamp01(
        clamp01(signal.signal_strength)
        * clamp01(signal.stress_survival)
        * clamp01(signal.counterplay_reduction)
        * clamp01(signal.persistence)
        * clamp01(signal.confirmation_depth)
        * 6.0
    )
    durability = safe_div(signal.performance_after_stress, max(float(signal.performance_before_stress), EPSILON))
    durability_score = weighted_mean(
        {
            "durability": (durability, 0.35),
            "durable_signal": (durable_signal, 0.45),
            "survivability": (signal.execution_survivability, 0.20),
        }
    )
    return {
        "durability_score": round(durability_score, 4),
        "stress_survival_ratio": round(durability, 4),
        "counterplay_remaining": round(1.0 - clamp01(signal.counterplay_reduction), 4),
        "admission_decision": durability_score >= thresholds["theta_durability"],
    }


def _precision(signal: ChessSignal, thresholds: dict[str, float]) -> dict[str, Any]:
    precision_required = clamp01(signal.option_margin) < thresholds["theta_precision_margin"]
    precision_score = weighted_mean(
        {
            "analysis_depth": (signal.analysis_depth, 0.45),
            "error_suppression": (signal.error_suppression, 0.35),
            "external_confirmation": (signal.external_confirmation, 0.20),
        }
    )
    decisive_variable = "timing_window" if signal.timing_window >= signal.structural_edge else "structural_edge"
    confidence_interval = round(abs(signal.option_margin - precision_score), 4)
    return {
        "precision_required": precision_required,
        "precision_score": round(precision_score, 4),
        "decisive_variable": decisive_variable,
        "confidence_interval": confidence_interval,
    }


def _initiative_promotion(
    signal: ChessSignal,
    *,
    durability_passed: bool,
    positional_passed: bool,
    hidden_risk_clearance: bool,
    precision_passed: bool,
    chaos_clear: bool,
) -> dict[str, Any]:
    # ActionableSignal = ValidationDepth × Initiative × TimingWindow × Feasibility × Asymmetry − ResidualRisk
    promotion_score = clamp01(
        clamp01(signal.evidence_depth)
        * clamp01(signal.initiative)
        * clamp01(signal.timing_window)
        * clamp01(signal.feasibility)
        * clamp01(signal.asymmetry)
        * 5.0
        - clamp01(signal.residual_risk) * 0.4
    )
    promoted = all(
        [
            durability_passed,
            positional_passed,
            hidden_risk_clearance,
            precision_passed,
            chaos_clear,
            promotion_score >= DEFAULT_THRESHOLDS["theta_initiative"],
        ]
    )
    return {
        "promoted": promoted,
        "promotion_score": round(promotion_score, 4),
        "timing_window": round(clamp01(signal.timing_window), 4),
        "pressure_plan": (
            "validated_imbalance_can_be_promoted" if promoted else "hold_promotion_until_preconditions_clear"
        ),
    }


def _simplification(signal: ChessSignal) -> dict[str, Any]:
    # UsefulComplexity = InsightGain − FrictionCost; NetSimplification = ClarityGain − OptionalityLoss
    useful_complexity = clamp01(signal.information_gain - signal.complexity_cost + 0.5)
    net_simplification = clamp01((1.0 - signal.complexity_cost) - signal.optionality_loss + 0.5)
    simplify_now = signal.complexity_cost > signal.information_gain and signal.operator_confusion > 0.45
    return {
        "simplify_now": simplify_now,
        "variables_to_remove": ["narrative_heat", "weak_optional_factors"] if simplify_now else [],
        "simplified_decision_path": "reduce_low-signal variables before more analysis" if simplify_now else "complexity acceptable",
        "optionality_loss_warning": signal.optionality_loss > 0.5,
        "useful_complexity": round(useful_complexity, 4),
        "net_simplification": round(net_simplification, 4),
    }


def _forced_line(signal: ChessSignal, thresholds: dict[str, float]) -> dict[str, Any]:
    # ForcedPath = EventCertainty × RepricingProbability × StructuralImpact
    forced_line_score = clamp01(
        clamp01(signal.event_certainty)
        * clamp01(signal.repricing_probability)
        * clamp01(signal.structural_impact)
        * 2.5
    )
    shock_detected = max(clamp01(signal.shock_event_score), forced_line_score) >= thresholds["theta_shock"]
    return {
        "shock_detected": shock_detected,
        "forced_line_score": round(max(clamp01(signal.shock_event_score), forced_line_score), 4),
        "required_action": "REPRICE" if shock_detected else "WAIT",
    }


def _prepared_attack(signal: ChessSignal) -> dict[str, Any]:
    # AttackValue = Preparation × Initiative × TargetWeakness × Timing − ExposureCost
    attack_value = clamp01(
        clamp01(signal.preparation)
        * clamp01(signal.initiative)
        * clamp01(signal.target_weakness)
        * clamp01(signal.timing_window)
        * 4.0
        - clamp01(signal.exposure_cost) * 0.4
    )
    missing = []
    if not signal.entry_defined:
        missing.append("entry_condition")
    if not signal.invalidation_defined:
        missing.append("invalidation")
    if not signal.sizing_defined:
        missing.append("size_or_exposure")
    if not signal.exit_defined:
        missing.append("exit_logic")
    if not signal.review_defined:
        missing.append("review_trigger")
    return {
        "prepared_attack_plan": [
            "watch",
            "validate",
            "build thesis",
            "identify target weakness",
            "define invalidation",
            "promote",
            "execute",
            "manage",
            "exit",
            "review",
        ],
        "sequence_completeness": round(clamp01(1.0 - (len(missing) / 5.0)), 4),
        "missing_preparation_steps": missing,
        "attack_value": round(attack_value, 4),
    }


def _process_review(signal: ChessSignal, selected_archetype: str, final_state: str, decision: str, vetoes: dict[str, bool], scores: dict[str, float]) -> dict[str, Any]:
    # SystemImprovement = ErrorLogging × ReviewDepth × MethodUpdate
    method_update = clamp01(signal.review_depth * signal.method_update * 1.5)
    return {
        "signal_id": signal.signal_id,
        "timestamp": utc_timestamp(),
        "initial_state": PositionState.RAW_SIGNAL.value,
        "archetype_selected": selected_archetype,
        "scores": scores,
        "vetoes_triggered": vetoes,
        "action_taken": decision,
        "outcome": final_state,
        "error_type": "none_logged_yet",
        "missed_risk": "pending_outcome_review",
        "conversion_quality": scores["conversion"],
        "rule_update_suggestion": "increase evidence threshold" if method_update < 0.5 else "retain current method",
    }


def _practical_discomfort(signal: ChessSignal) -> dict[str, Any]:
    # OpponentErrorProbability = CognitiveLoad × TimePressure × Ambiguity × Crowding × IncentiveConflict
    likely_error = clamp01(
        clamp01(signal.cognitive_load)
        * clamp01(signal.time_pressure)
        * clamp01(signal.ambiguity)
        * clamp01(signal.crowding)
        * clamp01(signal.incentive_conflict)
        * 8.0
    )
    discomfort = clamp01(weighted_mean({"objective_edge": (signal.structural_edge, 0.45), "likely_error": (likely_error, 0.55)}))
    return {
        "discomfort_score": round(discomfort, 4),
        "likely_participant_error": round(likely_error, 4),
        "practical_edge_adjustment": round(discomfort - signal.structural_edge, 4),
    }


def _neutralization(signal: ChessSignal) -> dict[str, Any]:
    strategic_edge = clamp01(weighted_mean({"battlefield_choice": (signal.battlefield_choice, 0.5), "neutralization": (signal.opponent_strength_neutralization, 0.5)}))
    neutralization_required = signal.chaos_score > signal.control_score or signal.maintenance_cost > signal.information_gain
    return {
        "neutralization_required": neutralization_required,
        "regime_to_avoid": "crowded_chaos" if neutralization_required else "none",
        "safer_battlefield": "reduced-complexity watchlist" if neutralization_required else "current battlefield acceptable",
        "strategic_edge": round(strategic_edge, 4),
    }


def _recovery(signal: ChessSignal, thresholds: dict[str, float]) -> dict[str, Any]:
    # RecoveryMode = Drawdown × Uncertainty × OperatorStress
    recovery_quality = clamp01(
        clamp01(1.0 - signal.drawdown)
        * clamp01(1.0 - signal.uncertainty)
        * clamp01(1.0 - signal.operator_stress)
        * 2.5
    )
    recovery_mode = clamp01(signal.drawdown * signal.uncertainty * signal.operator_stress * 4.0)
    active = recovery_mode >= thresholds["theta_operator_veto"] or signal.operator_stress > thresholds["theta_operator_veto"]
    return {
        "recovery_mode_active": active,
        "allowed_actions": ["WAIT", "SIMPLIFY", "RECOVER"] if active else ["WATCH", "VALIDATE", "PROMOTE"],
        "blocked_actions": ["EXECUTE", "FAST_TRACK"] if active else [],
        "recovery_plan": "repair, simplify, and review before new risk" if active else "recovery mode not active",
        "recovery_quality": round(recovery_quality, 4),
    }


def _multi_order_consequence(signal: ChessSignal) -> dict[str, Any]:
    # ActionQuality = O1 + O2 + O3 + O4 − CollapseRisk − MaintenanceCost − PolicyRisk − OperatorMisfit
    o1 = round(weighted_mean({"edge": (signal.signal_strength, 0.6), "timing": (signal.timing_window, 0.4)}), 4)
    o2 = round(weighted_mean({"response_advantage": (signal.initiative, 0.6), "neutralization": (signal.opponent_strength_neutralization, 0.4)}), 4)
    o3 = round(weighted_mean({"structure": (signal.structural_edge, 0.7), "durability": (signal.stress_survival, 0.3)}), 4)
    o4 = round(weighted_mean({"future": (signal.external_confirmation, 0.4), "survivability": (signal.execution_survivability, 0.6)}), 4)
    total = clamp01(o1 + o2 + o3 + o4 - signal.collapse_risk - signal.maintenance_cost - signal.policy_risk - signal.operator_misfit)
    return {
        "o1_score": o1,
        "o2_score": o2,
        "o3_score": o3,
        "o4_score": o4,
        "collapse_risk": round(clamp01(signal.collapse_risk), 4),
        "maintenance_cost": round(clamp01(signal.maintenance_cost), 4),
        "total_action_quality": round(total, 4),
        "future_game_description": "future trajectory improves if counterplay stays suppressed" if total >= 0.55 else "future game quality is still unstable",
    }


def _conversion(signal: ChessSignal, multi: dict[str, Any], thresholds: dict[str, float]) -> dict[str, Any]:
    # Outcome = Edge × Time × LowErrorRate × ExecutionQuality × ExitQuality
    conversion_score = clamp01(
        clamp01(signal.structural_edge)
        * clamp01(signal.timing_window)
        * clamp01(signal.low_error_rate)
        * clamp01(signal.execution_quality)
        * clamp01(signal.exit_quality)
        * 4.0
    )
    packet = {
        "entry_condition": "defined" if signal.entry_defined else "missing",
        "size_or_exposure": "defined" if signal.sizing_defined else "missing",
        "invalidation": "defined" if signal.invalidation_defined else "missing",
        "exit_logic": "defined" if signal.exit_defined else "missing",
        "review_trigger": "defined" if signal.review_defined else "missing",
    }
    executable = (
        conversion_score >= thresholds["theta_execution_feasibility"]
        and multi["total_action_quality"] >= 0.55
        and all(value == "defined" for value in packet.values())
    )
    return {
        "executable_signal": executable,
        "conversion_score": round(conversion_score, 4),
        "execution_packet": packet,
        "risk_adjusted_recommendation": "simulation_only_execute" if executable else "wait_for_better_packet",
    }


def _adaptive_selector(archetype_scores: dict[str, float], signal: ChessSignal) -> dict[str, Any]:
    ranked = sorted(archetype_scores.items(), key=lambda kv: kv[1], reverse=True)
    selected = ranked[0][0] if ranked else ChessArchetype.BOTVINNIK.value
    secondary = [name for name, _ in ranked[1:3]]
    top = ranked[0][1] if ranked else 0.0
    next_best = ranked[1][1] if len(ranked) > 1 else 0.0
    style_confidence = round(clamp01(top - next_best + 0.5), 4)
    style_drift_warning = style_confidence < 0.58 or signal.style_drift > 0.55
    return {
        "selected_archetype": selected,
        "secondary_archetype": secondary[0] if secondary else ChessArchetype.BOTVINNIK.value,
        "secondary_archetypes": secondary,
        "style_confidence": style_confidence,
        "style_drift_warning": style_drift_warning,
    }


def evaluate_chess_signal(signal: dict[str, Any], policy: dict[str, Any] | None = None) -> dict[str, Any]:
    thresholds = load_thresholds()
    item = _to_signal(signal)
    effective_policy = policy if isinstance(policy, dict) else {}
    policy_veto = bool(item.policy_veto or not effective_policy.get("allow_new_risk", not item.policy_veto))
    state_classification_score = _state_classification_score(item)
    fast_track = _tempo_advantage(item)
    positional = _positional_justification(item)
    chaos_hypothesis = _chaos_hypothesis(item)
    chaos_veto = _chaos_veto(item, policy_veto=policy_veto, thresholds=thresholds)
    hidden_risk = _hidden_risk(item, thresholds)
    durability = _durability(item, thresholds)
    precision = _precision(item, thresholds)
    precision_passed = (not precision["precision_required"]) or precision["precision_score"] >= 0.6
    promotion = _initiative_promotion(
        item,
        durability_passed=bool(durability["admission_decision"]),
        positional_passed=bool(positional["positional_justification_passed"]),
        hidden_risk_clearance=bool(hidden_risk["passed"]),
        precision_passed=precision_passed,
        chaos_clear=not chaos_veto["vetoed"],
    )
    simplification = _simplification(item)
    forced_line = _forced_line(item, thresholds)
    attack = _prepared_attack(item)
    practical = _practical_discomfort(item)
    neutralization = _neutralization(item)
    recovery = _recovery(item, thresholds)
    multi = _multi_order_consequence(item)
    conversion = _conversion(item, multi, thresholds)

    fast_track_allowed = (
        fast_track["fast_track_score"] >= thresholds["theta_fast_track"]
        and item.minimum_validation >= thresholds["theta_validation_floor"]
        and bool(item.risk_cap_passed)
        and not chaos_veto["vetoed"]
        and not policy_veto
    )
    fast_track["fast_track_candidate"] = bool(
        fast_track_allowed and fast_track["delay_cost"] > fast_track["validation_benefit"]
    )

    if policy_veto:
        initial_state = final_state = PositionState.VETOED.value
        decision = DecisionState.VETO.value
    elif chaos_veto["vetoed"]:
        initial_state = PositionState.CHAOS.value
        final_state = PositionState.VETOED.value
        decision = DecisionState.VETO.value
    elif recovery["recovery_mode_active"]:
        initial_state = PositionState.RECOVERY_STATE.value
        final_state = PositionState.NO_NEW_RISK.value
        decision = DecisionState.RECOVER.value
    elif forced_line["shock_detected"]:
        initial_state = PositionState.FORCED_LINE.value
        final_state = PositionState.FORCED_LINE.value
        decision = DecisionState.VALIDATE.value
    elif chaos_hypothesis["raw_hypothesis"] and not durability["admission_decision"]:
        initial_state = PositionState.CHAOS.value
        final_state = PositionState.RAW_SIGNAL.value
        decision = DecisionState.VALIDATE.value
    elif not positional["positional_justification_passed"]:
        initial_state = PositionState.POSITIONAL_EDGE.value
        final_state = PositionState.EQUAL_POSITION.value
        decision = DecisionState.VALIDATE.value
    elif not hidden_risk["passed"]:
        initial_state = PositionState.POSITIONAL_EDGE.value
        final_state = PositionState.NO_NEW_RISK.value
        decision = DecisionState.WAIT.value
    elif not durability["admission_decision"]:
        initial_state = PositionState.POSITIONAL_EDGE.value
        final_state = PositionState.POSITIONAL_EDGE.value
        decision = DecisionState.VALIDATE.value
    elif precision["precision_required"] and not precision_passed:
        initial_state = PositionState.DURABLE_SIGNAL.value
        final_state = PositionState.DURABLE_SIGNAL.value
        decision = DecisionState.VALIDATE.value
    elif simplification["simplify_now"]:
        initial_state = PositionState.ACTIONABLE_SIGNAL.value
        final_state = PositionState.ACTIONABLE_SIGNAL.value
        decision = DecisionState.SIMPLIFY.value
    elif promotion["promoted"] and conversion["executable_signal"]:
        initial_state = PositionState.ACTIONABLE_SIGNAL.value
        final_state = PositionState.EXECUTABLE_SIGNAL.value
        decision = DecisionState.EXECUTE.value
    elif promotion["promoted"]:
        initial_state = PositionState.DURABLE_SIGNAL.value
        final_state = PositionState.ACTIONABLE_SIGNAL.value
        decision = DecisionState.PROMOTE.value if fast_track["fast_track_candidate"] else DecisionState.WATCH.value
    elif state_classification_score >= thresholds["theta_state_actionable"]:
        initial_state = PositionState.POSITIONAL_EDGE.value
        final_state = PositionState.DURABLE_SIGNAL.value
        decision = DecisionState.WATCH.value
    else:
        initial_state = PositionState.RAW_SIGNAL.value
        final_state = PositionState.RAW_SIGNAL.value
        decision = DecisionState.WAIT.value

    archetype_scores = {
        ChessArchetype.MORPHY.value: round(fast_track["fast_track_score"], 4),
        ChessArchetype.STEINITZ.value: positional["structural_edge_score"],
        ChessArchetype.LASKER.value: practical["discomfort_score"],
        ChessArchetype.CAPABLANCA.value: simplification["net_simplification"],
        ChessArchetype.ALEKHINE.value: attack["attack_value"],
        ChessArchetype.BOTVINNIK.value: round(weighted_mean({"review": (item.review_depth, 0.5), "method": (item.method_update, 0.5)}), 4),
        ChessArchetype.TAL.value: chaos_hypothesis["productive_chaos_score"],
        ChessArchetype.PETROSIAN.value: round(1.0 - hidden_risk["hidden_risk_score"], 4),
        ChessArchetype.FISCHER.value: forced_line["forced_line_score"],
        ChessArchetype.SPASSKY.value: round(weighted_mean({"flexibility": (item.style_flexibility, 0.5), "control": (item.control_score, 0.5)}), 4),
        ChessArchetype.KARPOV.value: durability["durability_score"],
        ChessArchetype.KRAMNIK.value: neutralization["strategic_edge"],
        ChessArchetype.ANAND.value: round(weighted_mean({"speed": (item.adaptive_speed, 0.6), "timing": (item.timing_window, 0.4)}), 4),
        ChessArchetype.KASPAROV.value: promotion["promotion_score"],
        ChessArchetype.CARLSEN.value: conversion["conversion_score"],
        ChessArchetype.CARUANA.value: precision["precision_score"],
        ChessArchetype.DING.value: recovery["recovery_quality"],
    }
    adaptive = _adaptive_selector(archetype_scores, item)
    selected = adaptive["selected_archetype"]
    if policy_veto:
        selected = ChessArchetype.PETROSIAN.value
    elif chaos_veto["vetoed"]:
        selected = ChessArchetype.TAL.value
    elif recovery["recovery_mode_active"]:
        selected = ChessArchetype.DING.value
    elif forced_line["shock_detected"]:
        selected = ChessArchetype.FISCHER.value

    scores = {
        "state_fit": round(state_classification_score, 4),
        "archetype_fit": round(archetype_scores.get(selected, 0.0), 4),
        "tempo_score": fast_track["fast_track_score"],
        "positional_justification": positional["structural_edge_score"],
        "chaos_score": round(chaos_hypothesis["chaos_score"], 4),
        "control_score": round(clamp01(item.control_score), 4),
        "hidden_risk": hidden_risk["hidden_risk_score"],
        "durability": durability["durability_score"],
        "initiative": promotion["promotion_score"],
        "precision": precision["precision_score"],
        "conversion": conversion["conversion_score"],
        "recovery": recovery["recovery_quality"],
        "multi_order_consequence": multi["total_action_quality"],
    }
    vetoes = {
        "policy_veto": policy_veto,
        "chaos_veto": bool(chaos_veto["vetoed"] and not policy_veto),
        "hidden_risk_veto": not hidden_risk["passed"],
        "operator_veto": recovery["recovery_mode_active"] or item.operator_confusion > thresholds["theta_operator_veto"],
    }
    review_record = _process_review(item, selected, final_state, decision, vetoes, scores)

    explanation = (
        f"{selected} selected. State {initial_state} -> {final_state}. "
        f"Policy veto={str(policy_veto).lower()}, chaos veto={str(chaos_veto['vetoed']).lower()}, "
        f"hidden risk={hidden_risk['hidden_risk_score']}, durability={durability['durability_score']}, "
        f"precision_required={str(precision['precision_required']).lower()}, decision={decision}. "
        "Any EXECUTE label remains diagnostic/simulation-only."
    )

    return {
        "signal_id": item.signal_id,
        "timestamp": utc_timestamp(),
        "initial_state": initial_state,
        "final_state": final_state,
        "selected_archetype": selected,
        "secondary_archetypes": adaptive["secondary_archetypes"],
        "scores": scores,
        "vetoes": vetoes,
        "multi_order_effects": {
            "o1_immediate": f"o1={multi['o1_score']}",
            "o2_response": f"o2={multi['o2_score']}",
            "o3_structure": f"o3={multi['o3_score']}",
            "o4_future_game": f"o4={multi['o4_score']}",
        },
        "decision": decision,
        "execution_packet": conversion["execution_packet"],
        "explanation": explanation,
        "review_required": True,
        "review_record": review_record,
        "tempo_advantage": fast_track,
        "positional_gate": positional,
        "chaos_hypothesis": chaos_hypothesis,
        "chaos_veto": chaos_veto,
        "hidden_risk": hidden_risk,
        "durability_validation": durability,
        "precision_validation": precision,
        "promotion": promotion,
        "simplification": simplification,
        "forced_line": forced_line,
        "prepared_attack": attack,
        "practical_discomfort": practical,
        "neutralization": neutralization,
        "recovery": recovery,
        "multi_order_consequence": multi,
        "conversion": conversion,
        "adaptive_selector": adaptive,
    }


def generate_chess_archetype_report(signals: list[dict[str, Any]], policy: dict[str, Any] | None = None) -> dict[str, Any]:
    results = [evaluate_chess_signal(signal, policy=policy) for signal in signals]
    archetypes = Counter(row["selected_archetype"] for row in results)
    decisions = Counter(row["decision"] for row in results)
    veto_counts = {
        "policy_veto_count": sum(1 for row in results if row["vetoes"]["policy_veto"]),
        "chaos_veto_count": sum(1 for row in results if row["vetoes"]["chaos_veto"]),
        "hidden_risk_veto_count": sum(1 for row in results if row["vetoes"]["hidden_risk_veto"]),
        "operator_veto_count": sum(1 for row in results if row["vetoes"]["operator_veto"]),
    }
    rejection_reason_counter = Counter(
        row["chaos_veto"]["veto_reason"]
        if row["vetoes"]["policy_veto"] or row["vetoes"]["chaos_veto"]
        else ("hidden_risk" if row["vetoes"]["hidden_risk_veto"] else row["decision"])
        for row in results
    )
    average_multi_order = round(
        sum(row["scores"]["multi_order_consequence"] for row in results) / max(len(results), 1),
        4,
    )
    durability_pass_rate = round(
        sum(1 for row in results if row["durability_validation"]["admission_decision"]) / max(len(results), 1),
        4,
    )
    system_readiness_impact = (
        "NEGATIVE_VETO_DRIFT"
        if veto_counts["policy_veto_count"] or veto_counts["chaos_veto_count"]
        else "NEUTRAL_REVIEW_ONLY"
    )
    return {
        "run_id": get_run_id(),
        "generated_at": utc_timestamp(),
        "module": "chess_archetype_decision_layer",
        "schema_version": SCHEMA_VERSION,
        "total_signals_evaluated": len(results),
        "signals": results,
        "archetype_distribution": dict(archetypes),
        "decision_distribution": dict(decisions),
        "veto_counts": veto_counts,
        "fast_track_candidates": sum(1 for row in results if row["tempo_advantage"]["fast_track_candidate"]),
        "chaos_hypotheses_generated": sum(1 for row in results if row["chaos_hypothesis"]["raw_hypothesis"]),
        "chaos_hypotheses_admitted": sum(
            1 for row in results if row["chaos_hypothesis"]["raw_hypothesis"] and row["decision"] in {DecisionState.WATCH.value, DecisionState.PROMOTE.value}
        ),
        "durability_pass_rate": durability_pass_rate,
        "precision_required_cases": sum(1 for row in results if row["precision_validation"]["precision_required"]),
        "simplification_cases": sum(1 for row in results if row["simplification"]["simplify_now"]),
        "forced_line_reclassifications": sum(1 for row in results if row["forced_line"]["shock_detected"]),
        "recovery_activations": sum(1 for row in results if row["recovery"]["recovery_mode_active"]),
        "average_multi_order_consequence_score": average_multi_order,
        "most_common_rejection_reason": rejection_reason_counter.most_common(1)[0][0] if rejection_reason_counter else "none",
        "system_readiness_impact": system_readiness_impact,
        "report_path": repo_relative(CHESS_ARCHETYPE_REPORT_PATH),
        "data_quality": "synthetic_or_runtime_fallback" if any(str(row.get("source", "")).startswith("synthetic") for row in signals) else "runtime_proxy",
        "truth_origin": "seeded",
        "source_mode": get_source_mode(),
        "operating_mode": "seeded",
    }


def write_chess_archetype_report(
    signals: list[dict[str, Any]],
    *,
    runtime_state: dict[str, Any] | None = None,
    output_path: Path | None = None,
    write_runtime: bool = True,
) -> dict[str, Any]:
    policy = (runtime_state or {}).get("execution_policy", {}) if isinstance(runtime_state, dict) else {}
    report = generate_chess_archetype_report(signals, policy=policy)
    report["operating_mode"] = classify_operating_mode(runtime_state or {})
    payload = {
        "run_id": report["run_id"],
        "generated_at": report["generated_at"],
        "module": report["module"],
        "schema_version": SCHEMA_VERSION,
        "inputs": {
            "total_signal_inputs": len(signals),
            "data_quality": report["data_quality"],
            "live_ready": False,
        },
        "scores": {
            "average_multi_order_consequence_score": report["average_multi_order_consequence_score"],
            "durability_pass_rate": report["durability_pass_rate"],
            "fast_track_candidates": report["fast_track_candidates"],
        },
        "state": report["signals"][0]["final_state"] if report["signals"] else PositionState.RAW_SIGNAL.value,
        "vetoes": report["veto_counts"],
        "recommendation": report["signals"][0]["decision"] if report["signals"] else DecisionState.WAIT.value,
        "rationale": [
            "Policy veto outranks every archetype.",
            "Chaos does not bypass veto clearance.",
            "Detection does not equal admission.",
        ],
        "classified_signals": report["signals"],
        "summary": report,
        "data_quality": report["data_quality"],
        "live_ready": False,
        "truth_origin": report["truth_origin"],
        "source_mode": report["source_mode"],
        "operating_mode": report["operating_mode"],
    }
    if write_runtime:
        write_json_atomic(output_path or CHESS_ARCHETYPE_REPORT_PATH, payload, stamp=False)
    report["artifact"] = payload
    return report
