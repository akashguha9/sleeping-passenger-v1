from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

try:
    from scripts.runtime_common import (
        REPO_ROOT,
        STRUCTURAL_ADMISSION_REPORT_PATH,
        build_runtime_state_from_scm_report_payload,
        get_run_id,
        load_json_file,
        get_source_mode,
        repo_relative,
        utc_timestamp,
        write_json_atomic,
    )
    from scripts.signal_conversion_monitor import build_signal_conversion_report
except ModuleNotFoundError:
    from runtime_common import (  # type: ignore[no-redef]
        REPO_ROOT,
        STRUCTURAL_ADMISSION_REPORT_PATH,
        build_runtime_state_from_scm_report_payload,
        get_run_id,
        load_json_file,
        get_source_mode,
        repo_relative,
        utc_timestamp,
        write_json_atomic,
    )
    from signal_conversion_monitor import build_signal_conversion_report  # type: ignore[no-redef]


DEFAULT_THRESHOLD_DESIGN_INTEGRITY = 0.55
DEFAULT_THRESHOLD_MATERIAL = 0.45
DEFAULT_THRESHOLD_HARMONY = 0.55
DEFAULT_THRESHOLD_DISSONANCE = 0.35
DEFAULT_THRESHOLD_TRAPDOOR = 0.65
DEFAULT_THRESHOLD_TRUST = 0.55
DEFAULT_THRESHOLD_OPERATOR_CLARITY = 0.45
DEFAULT_MAX_VALIDATION_AGE_HOURS = 24.0
STRUCTURAL_ADMISSION_CONFIG_PATH = REPO_ROOT / "config" / "structural_admission_config.json"
DEFAULT_THRESHOLDS = {
    "domain_fit_threshold": 1.0,
    "environment_fit_threshold": 0.45,
    "material_durability_threshold": DEFAULT_THRESHOLD_MATERIAL,
    "signal_harmony_threshold": DEFAULT_THRESHOLD_HARMONY,
    "transition_quality_threshold": 0.55,
    "validation_strength_threshold": 0.55,
    "trust_observability_threshold": DEFAULT_THRESHOLD_TRUST,
    "operator_clarity_threshold": DEFAULT_THRESHOLD_OPERATOR_CLARITY,
    "reality_alignment_threshold": 0.45,
    "primitive_understanding_threshold": 0.55,
    "use_case_fit_threshold": 0.45,
    "buyer_alignment_threshold": 0.5,
    "execution_survivability_threshold": 0.5,
    "trapdoor_risk_max": DEFAULT_THRESHOLD_TRAPDOOR,
    "fast_track_momentum_threshold": 0.75,
    "fast_track_validation_threshold": 0.7,
    "source_confirmation_threshold": 0.55,
    "maintenance_survival_threshold": 0.5,
}


class RejectionReason(str, Enum):
    DOMAIN_MISMATCH = "DOMAIN_MISMATCH"
    ENVIRONMENT_MISMATCH = "ENVIRONMENT_MISMATCH"
    LOW_DURABILITY_SIGNAL = "LOW_DURABILITY_SIGNAL"
    SIGNAL_DISSONANCE = "SIGNAL_DISSONANCE"
    INVALID_PROGRESSION = "INVALID_PROGRESSION"
    TRAPDOOR_EVENT = "TRAPDOOR_EVENT"
    LOW_TRUST_OBSERVABILITY = "LOW_TRUST_OBSERVABILITY"
    LOW_OPERATOR_CLARITY = "LOW_OPERATOR_CLARITY"
    DRIFT_FROM_REALITY = "DRIFT_FROM_REALITY"
    NO_PRIMITIVE_UNDERSTANDING = "NO_PRIMITIVE_UNDERSTANDING"
    MISUSED_GENERALIST = "MISUSED_GENERALIST"
    UTILITY_WITHOUT_STRUCTURE = "UTILITY_WITHOUT_STRUCTURE"
    LOW_BUYER_ALIGNMENT = "LOW_BUYER_ALIGNMENT"
    LOW_EXECUTION_SURVIVABILITY = "LOW_EXECUTION_SURVIVABILITY"
    SOURCE_CREDIBILITY_WITHOUT_VALIDATION = "SOURCE_CREDIBILITY_WITHOUT_VALIDATION"
    SURFACE_ONLY_IMPROVEMENT = "SURFACE_ONLY_IMPROVEMENT"
    COSMETIC_SKIN_ONLY = "COSMETIC_SKIN_ONLY"
    PEAK_MOMENT_WITHOUT_TOTAL_QUALITY = "PEAK_MOMENT_WITHOUT_TOTAL_QUALITY"
    LOW_MAINTENANCE_SURVIVAL = "LOW_MAINTENANCE_SURVIVAL"
    FORCE_FLOW_BREAK = "FORCE_FLOW_BREAK"
    ACTOR_RESPONSE_UNCLEAR = "ACTOR_RESPONSE_UNCLEAR"


class RegimeClass(str, Enum):
    NORMAL = "NORMAL"
    VOLATILE = "VOLATILE"
    CHAOS = "CHAOS"
    LOW_LIQUIDITY = "LOW_LIQUIDITY"
    HIGH_SPREAD = "HIGH_SPREAD"
    NEWS_SHOCK = "NEWS_SHOCK"
    UNKNOWN = "UNKNOWN"


class EngineClass(str, Enum):
    BIC_ENGINE = "BIC_ENGINE"
    ZIPPO_ENGINE = "ZIPPO_ENGINE"
    MATCHBOX_ENGINE = "MATCHBOX_ENGINE"


class SignalMaterialClass(str, Enum):
    WOOD_SIGNAL = "WOOD_SIGNAL"
    WAX_SIGNAL = "WAX_SIGNAL"
    HYBRID_SIGNAL = "HYBRID_SIGNAL"
    FOAM_SIGNAL = "FOAM_SIGNAL"
    UNKNOWN_MATERIAL = "UNKNOWN_MATERIAL"


class TransitionClass(str, Enum):
    LINEAR = "LINEAR"
    CURVED = "CURVED"
    OSCILLATING = "OSCILLATING"
    TRAPDOOR = "TRAPDOOR"
    RESOLVED = "RESOLVED"
    FAILED_RESOLUTION = "FAILED_RESOLUTION"
    FALSE_BREAKOUT = "FALSE_BREAKOUT"
    ACCUMULATION = "ACCUMULATION"
    DISTRIBUTION = "DISTRIBUTION"
    UNKNOWN = "UNKNOWN"


class AdmissionClass(str, Enum):
    ADMIT_EXECUTION_CANDIDATE = "ADMIT_EXECUTION_CANDIDATE"
    ADMIT_WATCHLIST_ONLY = "ADMIT_WATCHLIST_ONLY"
    OBSERVE_ONLY = "OBSERVE_ONLY"
    REJECT = "REJECT"
    CHAOS_VETO = "CHAOS_VETO"
    NEEDS_REVALIDATION = "NEEDS_REVALIDATION"


class SeverityLevel(str, Enum):
    HARD = "HARD"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class BuyerClass(str, Enum):
    RETAIL_MOMENTUM = "RETAIL_MOMENTUM"
    INSTITUTIONAL_QUALITY = "INSTITUTIONAL_QUALITY"
    PASSIVE_ALLOCATION = "PASSIVE_ALLOCATION"
    VENTURE_OPTIONALITY = "VENTURE_OPTIONALITY"
    INCOME_INVESTOR = "INCOME_INVESTOR"
    HEDGER = "HEDGER"
    NARRATIVE_SPECULATOR = "NARRATIVE_SPECULATOR"
    EVENT_DRIVEN = "EVENT_DRIVEN"
    DISTRESSED_VALUE = "DISTRESSED_VALUE"
    MACRO_ROTATION = "MACRO_ROTATION"
    INSIDER_SIGNAL_FOLLOWER = "INSIDER_SIGNAL_FOLLOWER"
    UNKNOWN = "UNKNOWN"


class SkinClass(str, Enum):
    COSMETIC_SKIN = "COSMETIC_SKIN"
    FUNCTIONAL_SKIN = "FUNCTIONAL_SKIN"
    BEHAVIORAL_SKIN = "BEHAVIORAL_SKIN"
    STRUCTURAL_SKIN = "STRUCTURAL_SKIN"


class RecoveryClass(str, Enum):
    SURFACE_ONLY = "SURFACE_ONLY"
    OPERATIONAL = "OPERATIONAL"
    FINANCIAL = "FINANCIAL"
    STRATEGIC = "STRATEGIC"
    RISK_REDUCING = "RISK_REDUCING"
    STRUCTURAL = "STRUCTURAL"


class BullState(str, Enum):
    MIURA = "MIURA"
    MURCIELAGO = "MURCIELAGO"
    AVENTADOR = "AVENTADOR"
    GALLARDO = "GALLARDO"
    ISLERO = "ISLERO"
    DIABLO = "DIABLO"
    HURACAN = "HURACAN"
    UNKNOWN = "UNKNOWN"


@dataclass(slots=True)
class DesignIntegrityInput:
    readability_score: float = 0.0
    structure_score: float = 0.0
    traceability_score: float = 0.0
    risk_visibility_score: float = 0.0
    execution_clarity_score: float = 0.0
    utility_high: bool = False
    threshold: float = DEFAULT_THRESHOLD_DESIGN_INTEGRITY


@dataclass(slots=True)
class DomainInstrumentInput:
    instrument_domain: str = ""
    required_variable_domain: str = ""


@dataclass(slots=True)
class EnvironmentInput:
    volatility: float = 0.0
    liquidity: float = 0.0
    spread: float = 0.0
    news_intensity: float = 0.0
    correlation_break: float = 0.0
    execution_friction: float = 0.0
    selected_engine: EngineClass = EngineClass.BIC_ENGINE
    regime_hint: str = ""


@dataclass(slots=True)
class BurnProfile:
    ignition_speed: float = 0.0
    duration_score: float = 0.0
    stability_score: float = 0.0
    environment_resistance_score: float = 0.0
    decay_rate: float = 0.0


@dataclass(slots=True)
class SignalGraphInput:
    node_values: dict[str, float] = field(default_factory=dict)
    expected_edges: list[tuple[str, str]] = field(default_factory=list)
    observed_edges: list[tuple[str, str, str]] = field(default_factory=list)


@dataclass(slots=True)
class ProgressionInput:
    observed_sequence: list[str] = field(default_factory=list)
    required_sequence: list[str] = field(
        default_factory=lambda: ["EVENT", "NEWS", "SENTIMENT", "VOLUME", "PRICE", "OPTIONS"]
    )
    required_confirmations: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TransitionInput:
    curvature: float = 0.0
    oscillation: float = 0.0
    resolution_strength: float = 0.0
    trapdoor_risk: float = 0.0


@dataclass(slots=True)
class TrapdoorInput:
    expected_path_deviation: float = 0.0
    impact: float = 0.0
    speed: float = 0.0
    threshold: float = DEFAULT_THRESHOLD_TRAPDOOR


@dataclass(slots=True)
class TrustInput:
    observability: float = 0.0
    auditability: float = 0.0
    explainability: float = 0.0
    high_stakes: bool = True
    threshold: float = DEFAULT_THRESHOLD_TRUST


@dataclass(slots=True)
class OperatorClarityInput:
    dashboard_readability: float = 0.0
    noise: float = 0.0
    cognitive_load: float = 0.0
    alert_overload: float = 0.0
    ambiguity: float = 0.0
    threshold: float = DEFAULT_THRESHOLD_OPERATOR_CLARITY


@dataclass(slots=True)
class RealityAnchorInput:
    freshness: float = 0.0
    external_confirmation: float = 0.0
    regime_consistency: float = 0.0
    time_since_validation_hours: float = 0.0
    max_validation_age_hours: float = DEFAULT_MAX_VALIDATION_AGE_HOURS


@dataclass(slots=True)
class PrimitiveCompetenceInput:
    primitive_understanding: float = 0.0
    interface_leverage: float = 0.0
    signal_defined: bool = False
    variable_defined: bool = False
    instrument_validity_explained: bool = False
    invalidation_defined: bool = False
    regime_defined: bool = False
    wrong_proof_defined: bool = False
    fallback_defined: bool = False


@dataclass(slots=True)
class UseCaseFitInput:
    task_context: str = ""
    tool_class: str = "SPECIALIST_TOOL"
    specialization_match: float = 0.0
    generalist_output_used_for_execution: bool = False


@dataclass(slots=True)
class BuyerTypeInput:
    asset_class: str = "UNKNOWN"
    objective: str = "UNKNOWN"
    risk_tolerance: float = 0.0
    time_horizon_days: float = 0.0
    identity_fit: float = 0.0
    narrative_strength: float = 0.0
    income_relevance: float = 0.0
    optionality: float = 0.0
    hedge_need: float = 0.0
    event_catalyst_strength: float = 0.0
    quality_bias: float = 0.0
    passive_fit: float = 0.0
    threshold: float = 0.5


@dataclass(slots=True)
class ExecutionSurvivabilityInput:
    volatility: float = 0.0
    spread: float = 0.0
    slippage: float = 0.0
    latency: float = 0.0
    data_gaps: float = 0.0
    false_positive_rate: float = 0.0
    news_reversal_risk: float = 0.0
    liquidity_gap_risk: float = 0.0
    operator_confusion: float = 0.0
    external_confirmation_failure: float = 0.0
    threshold: float = 0.5


@dataclass(slots=True)
class SourceValidationInput:
    source_credibility: float = 0.0
    external_confirmation: float = 0.0
    consistency: float = 0.0
    wrapper_uncertainty: float = 0.0
    threshold: float = 0.55


@dataclass(slots=True)
class PeakMomentInput:
    novelty: float = 0.0
    emotional_intensity: float = 0.0
    recall_frequency: float = 0.0
    total_quality: float = 0.0


@dataclass(slots=True)
class AnchorFeatureInput:
    top_feature_mentions: float = 0.0
    total_feature_mentions: float = 0.0
    baseline_competence: float = 0.0


@dataclass(slots=True)
class BehavioralSkinInput:
    appearance: float = 0.0
    behavior: float = 0.0
    feature_access: float = 0.0
    system_tuning: float = 0.0


@dataclass(slots=True)
class MaintenanceCostInput:
    performance_after_stress: float = 0.0
    performance_before_stress: float = 1.0
    desire: float = 0.0
    maintenance_cost: float = 0.0
    failure_friction: float = 0.0
    threshold: float = 0.5


@dataclass(slots=True)
class RecoveryQualityInput:
    surface_recovery: float = 0.0
    structural_integrity: float = 0.0


@dataclass(slots=True)
class ForceFlowInput:
    signal_force: float = 0.0
    transmission_path: float = 0.0
    buyer_sensitivity: float = 0.0
    damping: float = 0.0


@dataclass(slots=True)
class ActorResponseInput:
    buyer_probabilities: dict[str, float] = field(default_factory=dict)
    capital_weights: dict[str, float] = field(default_factory=dict)
    reaction_speed: float = 0.0
    conviction: float = 0.0
    threshold: float = 0.5


@dataclass(slots=True)
class StructuralAdmissionInput:
    design_integrity: DesignIntegrityInput = field(default_factory=DesignIntegrityInput)
    domain_instrument: DomainInstrumentInput = field(default_factory=DomainInstrumentInput)
    environment: EnvironmentInput = field(default_factory=EnvironmentInput)
    burn_profile: BurnProfile = field(default_factory=BurnProfile)
    signal_graph: SignalGraphInput = field(default_factory=SignalGraphInput)
    progression: ProgressionInput = field(default_factory=ProgressionInput)
    transition: TransitionInput = field(default_factory=TransitionInput)
    trapdoor: TrapdoorInput = field(default_factory=TrapdoorInput)
    trust: TrustInput = field(default_factory=TrustInput)
    operator_clarity: OperatorClarityInput = field(default_factory=OperatorClarityInput)
    reality_anchor: RealityAnchorInput = field(default_factory=RealityAnchorInput)
    primitive_competence: PrimitiveCompetenceInput = field(default_factory=PrimitiveCompetenceInput)
    use_case_fit: UseCaseFitInput = field(default_factory=UseCaseFitInput)
    buyer_type: BuyerTypeInput = field(default_factory=BuyerTypeInput)
    execution_survivability: ExecutionSurvivabilityInput = field(default_factory=ExecutionSurvivabilityInput)
    source_validation: SourceValidationInput = field(default_factory=SourceValidationInput)
    peak_moment: PeakMomentInput = field(default_factory=PeakMomentInput)
    anchor_feature: AnchorFeatureInput = field(default_factory=AnchorFeatureInput)
    behavioral_skin: BehavioralSkinInput = field(default_factory=BehavioralSkinInput)
    maintenance_cost: MaintenanceCostInput = field(default_factory=MaintenanceCostInput)
    recovery_quality: RecoveryQualityInput = field(default_factory=RecoveryQualityInput)
    force_flow: ForceFlowInput = field(default_factory=ForceFlowInput)
    actor_response: ActorResponseInput = field(default_factory=ActorResponseInput)
    validation_strength: float = 0.0
    fast_track_momentum: float = 0.0
    chaos_veto: bool = False
    policy_veto: bool = False
    system_name: str = "UNKNOWN"
    source: str = "DEFAULT_STRUCTURAL_ADMISSION"


@dataclass(slots=True)
class ComponentScore:
    component: str
    score: float
    threshold: float | None
    passed: bool
    hard_reject: bool
    explanation: str


@dataclass(slots=True)
class RejectionRecord:
    code: str
    severity: str
    blocking_weight: float
    explanation: str
    failed_component: str
    observed_value: float | str | None
    threshold: float | str | None
    timestamp: str | None = None
    run_id: str | None = None


@dataclass(slots=True)
class StructuralAdmissionResult:
    admission_score: float
    diagnostic_score: float
    admission_class: str
    passed: bool
    bottleneck_layer: str
    hard_reject: bool
    chaos_veto: bool
    recommended_engine: str
    regime_class: str
    material_class: str
    transition_class: str
    buyer_type: dict[str, Any]
    materiality: dict[str, Any]
    transition: dict[str, Any]
    source_validation: dict[str, Any]
    actor_response: dict[str, Any]
    bull_state: str
    next_required_action: str
    component_scores: dict[str, float]
    layer_scores: dict[str, dict[str, Any]]
    rejection_reasons: list[dict[str, Any]]
    operator_summary: str
    operator_summary_payload: dict[str, str]


def clamp01(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def mean_score(*values: float) -> float:
    if not values:
        return 0.0
    return clamp01(sum(clamp01(value) for value in values) / len(values))


def weighted_sum(values: dict[str, float], weights: dict[str, float]) -> float:
    total = 0.0
    for key, weight in weights.items():
        total += weight * clamp01(values.get(key, 0.0))
    return clamp01(total)


def load_structural_admission_thresholds() -> dict[str, float]:
    payload = load_json_file(STRUCTURAL_ADMISSION_CONFIG_PATH, default={})
    if not isinstance(payload, dict):
        return dict(DEFAULT_THRESHOLDS)
    thresholds = dict(DEFAULT_THRESHOLDS)
    for key, default in DEFAULT_THRESHOLDS.items():
        thresholds[key] = clamp01(payload.get(key, default)) if key != "domain_fit_threshold" else float(payload.get(key, default))
    return thresholds


def _threshold(thresholds: dict[str, float], key: str) -> float:
    value = thresholds.get(key, DEFAULT_THRESHOLDS[key])
    if key == "domain_fit_threshold":
        return float(value)
    return clamp01(value)


def _make_rejection(
    *,
    code: RejectionReason,
    severity: SeverityLevel,
    blocking_weight: float,
    explanation: str,
    failed_component: str,
    observed_value: float | str | None,
    threshold: float | str | None,
) -> RejectionRecord:
    return RejectionRecord(
        code=code.value,
        severity=severity.value,
        blocking_weight=blocking_weight,
        explanation=explanation,
        failed_component=failed_component,
        observed_value=observed_value,
        threshold=threshold,
        timestamp=utc_timestamp(),
        run_id=get_run_id(),
    )


def evaluate_design_integrity(
    payload: DesignIntegrityInput,
) -> tuple[ComponentScore, list[RejectionRecord]]:
    score = mean_score(
        payload.readability_score,
        payload.structure_score,
        payload.traceability_score,
        payload.risk_visibility_score,
        payload.execution_clarity_score,
    )
    passed = not (payload.utility_high and score < payload.threshold)
    reasons: list[RejectionRecord] = []
    if not passed:
        reasons.append(
            _make_rejection(
                code=RejectionReason.UTILITY_WITHOUT_STRUCTURE,
                severity=SeverityLevel.HARD,
                blocking_weight=1.0,
                explanation=(
                    "Signal shows utility or attraction, but structure, readability, "
                    "or execution clarity remain below the admission floor."
                ),
                failed_component="design_integrity",
                observed_value=round(score, 4),
                threshold=payload.threshold,
            )
        )
    return (
        ComponentScore(
            component="design_integrity",
            score=score,
            threshold=payload.threshold,
            passed=passed,
            hard_reject=not passed,
            explanation="SystemAdmission = Utility * Structure * Readability * ContextFit",
        ),
        reasons,
    )


def evaluate_domain_fit(
    payload: DomainInstrumentInput,
) -> tuple[ComponentScore, list[RejectionRecord]]:
    score = (
        1.0
        if str(payload.instrument_domain).strip().upper()
        == str(payload.required_variable_domain).strip().upper()
        and str(payload.instrument_domain).strip()
        else 0.0
    )
    passed = score == 1.0
    reasons: list[RejectionRecord] = []
    if not passed:
        reasons.append(
            _make_rejection(
                code=RejectionReason.DOMAIN_MISMATCH,
                severity=SeverityLevel.HARD,
                blocking_weight=1.0,
                explanation=(
                    "The instrument domain does not measure the required variable domain. "
                    "CorrectInference = CorrectVariable * CorrectInstrument."
                ),
                failed_component="domain_fit",
                observed_value=str(payload.instrument_domain or "UNKNOWN"),
                threshold=str(payload.required_variable_domain or "UNKNOWN"),
            )
        )
    return (
        ComponentScore(
            component="domain_fit",
            score=score,
            threshold=1.0,
            passed=passed,
            hard_reject=not passed,
            explanation="CorrectInference = CorrectVariable * CorrectInstrument",
        ),
        reasons,
    )


def classify_regime(payload: EnvironmentInput) -> RegimeClass:
    if payload.regime_hint:
        hinted = str(payload.regime_hint).strip().upper()
        for regime in RegimeClass:
            if regime.value == hinted:
                return regime
    volatility = clamp01(payload.volatility)
    liquidity = clamp01(payload.liquidity)
    spread = clamp01(payload.spread)
    news_intensity = clamp01(payload.news_intensity)
    correlation_break = clamp01(payload.correlation_break)
    execution_friction = clamp01(payload.execution_friction)
    if max(volatility, news_intensity, correlation_break, execution_friction) >= 0.85:
        return RegimeClass.CHAOS
    if liquidity <= 0.25:
        return RegimeClass.LOW_LIQUIDITY
    if spread >= 0.70:
        return RegimeClass.HIGH_SPREAD
    if news_intensity >= 0.70:
        return RegimeClass.NEWS_SHOCK
    if max(volatility, execution_friction, correlation_break) >= 0.55:
        return RegimeClass.VOLATILE
    if max(volatility, liquidity, spread, news_intensity, correlation_break, execution_friction) == 0.0:
        return RegimeClass.UNKNOWN
    return RegimeClass.NORMAL


def select_engine(regime_class: RegimeClass) -> EngineClass:
    if regime_class == RegimeClass.NORMAL:
        return EngineClass.BIC_ENGINE
    if regime_class == RegimeClass.VOLATILE:
        return EngineClass.ZIPPO_ENGINE
    return EngineClass.MATCHBOX_ENGINE


def evaluate_environment_fit(
    payload: EnvironmentInput,
) -> tuple[ComponentScore, RegimeClass, EngineClass, list[RejectionRecord]]:
    regime = classify_regime(payload)
    recommended_engine = select_engine(regime)
    selected_engine = payload.selected_engine
    reasons: list[RejectionRecord] = []
    if regime == RegimeClass.NORMAL:
        score = 1.0 if selected_engine == EngineClass.BIC_ENGINE else 0.35
    elif regime == RegimeClass.VOLATILE:
        score = 0.8 if selected_engine == EngineClass.ZIPPO_ENGINE else 0.3
    elif regime in {RegimeClass.CHAOS, RegimeClass.UNKNOWN}:
        score = 0.45 if selected_engine == EngineClass.MATCHBOX_ENGINE else 0.0
    elif regime in {RegimeClass.LOW_LIQUIDITY, RegimeClass.HIGH_SPREAD, RegimeClass.NEWS_SHOCK}:
        score = 0.6 if selected_engine in {EngineClass.ZIPPO_ENGINE, EngineClass.MATCHBOX_ENGINE} else 0.2
    else:
        score = 0.0
    passed = selected_engine == recommended_engine or (
        regime in {RegimeClass.LOW_LIQUIDITY, RegimeClass.HIGH_SPREAD, RegimeClass.NEWS_SHOCK}
        and selected_engine in {EngineClass.ZIPPO_ENGINE, EngineClass.MATCHBOX_ENGINE}
    )
    if not passed:
        reasons.append(
            _make_rejection(
                code=RejectionReason.ENVIRONMENT_MISMATCH,
                severity=SeverityLevel.HARD if regime == RegimeClass.CHAOS else SeverityLevel.MEDIUM,
                blocking_weight=1.0 if regime == RegimeClass.CHAOS else 0.75,
                explanation=(
                    "Selected engine is not valid for the current regime. "
                    "ToolPerformance = f(Environment, Pressure, Oxygen, Constraint)."
                ),
                failed_component="environment_fit",
                observed_value=selected_engine.value,
                threshold=recommended_engine.value,
            )
        )
    return (
        ComponentScore(
            component="environment_fit",
            score=clamp01(score),
            threshold=None,
            passed=passed,
            hard_reject=not passed and regime == RegimeClass.CHAOS,
            explanation="ToolPerformance = f(Environment, Pressure, Oxygen, Constraint)",
        ),
        regime,
        recommended_engine,
        reasons,
    )


def estimate_burn_profile(payload: BurnProfile) -> tuple[BurnProfile, float]:
    duration_score = clamp01(payload.duration_score)
    stability_score = clamp01(payload.stability_score)
    environment_resistance_score = clamp01(payload.environment_resistance_score)
    material_durability = clamp01(
        duration_score
        * stability_score
        * environment_resistance_score
        * (1.0 - clamp01(payload.decay_rate))
    )
    return (
        BurnProfile(
            ignition_speed=clamp01(payload.ignition_speed),
            duration_score=duration_score,
            stability_score=stability_score,
            environment_resistance_score=environment_resistance_score,
            decay_rate=clamp01(payload.decay_rate),
        ),
        material_durability,
    )


def classify_materiality(payload: BurnProfile) -> tuple[SignalMaterialClass, float]:
    normalized, material_durability = estimate_burn_profile(payload)
    if (
        normalized.ignition_speed >= 0.70
        and (normalized.duration_score < 0.45 or normalized.environment_resistance_score < 0.45)
    ):
        return SignalMaterialClass.WOOD_SIGNAL, material_durability
    if (
        normalized.duration_score >= 0.70
        and normalized.stability_score >= 0.70
        and normalized.environment_resistance_score >= 0.65
    ):
        return SignalMaterialClass.WAX_SIGNAL, material_durability
    if (
        normalized.ignition_speed >= 0.55
        and normalized.duration_score >= 0.55
        and normalized.stability_score >= 0.55
    ):
        return SignalMaterialClass.HYBRID_SIGNAL, material_durability
    if normalized.ignition_speed >= 0.45 and normalized.environment_resistance_score < 0.35:
        return SignalMaterialClass.FOAM_SIGNAL, material_durability
    return SignalMaterialClass.UNKNOWN_MATERIAL, material_durability


def evaluate_material_durability(
    payload: BurnProfile,
) -> tuple[ComponentScore, SignalMaterialClass, list[RejectionRecord]]:
    material_class, score = classify_materiality(payload)
    passed = score >= DEFAULT_THRESHOLD_MATERIAL and material_class != SignalMaterialClass.FOAM_SIGNAL
    reasons: list[RejectionRecord] = []
    if not passed:
        reasons.append(
            _make_rejection(
                code=RejectionReason.LOW_DURABILITY_SIGNAL,
                severity=SeverityLevel.MEDIUM,
                blocking_weight=0.85,
                explanation=(
                    "Signal burn profile is too fragile for admission. "
                    "Fast ignition alone does not justify deployment."
                ),
                failed_component="material_durability",
                observed_value=round(score, 4),
                threshold=DEFAULT_THRESHOLD_MATERIAL,
            )
        )
    return (
        ComponentScore(
            component="material_durability",
            score=score,
            threshold=DEFAULT_THRESHOLD_MATERIAL,
            passed=passed,
            hard_reject=False,
            explanation="SignalBurnProfile = IgnitionSpeed * Duration * Stability * EnvironmentResistance",
        ),
        material_class,
        reasons,
    )


def evaluate_signal_harmony(
    payload: SignalGraphInput,
) -> tuple[ComponentScore, float, list[RejectionRecord]]:
    expected = max(len(payload.expected_edges), 1)
    observed = max(len(payload.observed_edges), 1)
    valid_edges = sum(1 for _, _, relation in payload.observed_edges if relation == "confirm")
    conflicting_edges = sum(1 for _, _, relation in payload.observed_edges if relation == "conflict")
    harmony_score = clamp01(valid_edges / expected)
    dissonance_score = clamp01(conflicting_edges / observed)
    passed = harmony_score >= DEFAULT_THRESHOLD_HARMONY and dissonance_score <= DEFAULT_THRESHOLD_DISSONANCE
    reasons: list[RejectionRecord] = []
    if not passed:
        reasons.append(
            _make_rejection(
                code=RejectionReason.SIGNAL_DISSONANCE,
                severity=SeverityLevel.MEDIUM,
                blocking_weight=0.8,
                explanation=(
                    "Observed signal edges conflict or fail to confirm expected relationships. "
                    "SignalMeaning = NodeValue * RelationshipStrength."
                ),
                failed_component="signal_harmony",
                observed_value=f"harmony={harmony_score:.3f};dissonance={dissonance_score:.3f}",
                threshold=f"harmony>={DEFAULT_THRESHOLD_HARMONY};dissonance<={DEFAULT_THRESHOLD_DISSONANCE}",
            )
        )
    return (
        ComponentScore(
            component="signal_harmony",
            score=harmony_score,
            threshold=DEFAULT_THRESHOLD_HARMONY,
            passed=passed,
            hard_reject=False,
            explanation="SignalMeaning = NodeValue * RelationshipStrength",
        ),
        dissonance_score,
        reasons,
    )


def validate_progression(
    payload: ProgressionInput,
) -> tuple[ComponentScore, list[RejectionRecord]]:
    if not payload.observed_sequence:
        return (
            ComponentScore(
                component="progression",
                score=0.0,
                threshold=None,
                passed=False,
                hard_reject=False,
                explanation="No progression evidence available.",
            ),
            [
                _make_rejection(
                    code=RejectionReason.INVALID_PROGRESSION,
                    severity=SeverityLevel.MEDIUM,
                    blocking_weight=0.7,
                    explanation="Observed progression is missing; required confirmation chain is absent.",
                    failed_component="progression",
                    observed_value="MISSING",
                    threshold="SEQUENCED_CONFIRMATION",
                )
            ],
        )
    order = {token: index for index, token in enumerate(payload.required_sequence)}
    normalized = [token.upper() for token in payload.observed_sequence]
    in_order_pairs = 0
    checked_pairs = 0
    reversed_pairs = 0
    for index in range(1, len(normalized)):
        previous = normalized[index - 1]
        current = normalized[index]
        if previous in order and current in order:
            checked_pairs += 1
            if order[previous] <= order[current]:
                in_order_pairs += 1
            else:
                reversed_pairs += 1
    confirmation_pass = all(token.upper() in normalized for token in payload.required_confirmations)
    sequence_score = clamp01(in_order_pairs / max(checked_pairs, 1))
    score = clamp01((sequence_score * 0.7) + (0.3 if confirmation_pass else 0.0))
    passed = score >= 0.55 and confirmation_pass and reversed_pairs == 0
    reasons: list[RejectionRecord] = []
    if not passed:
        reasons.append(
            _make_rejection(
                code=RejectionReason.INVALID_PROGRESSION,
                severity=SeverityLevel.MEDIUM,
                blocking_weight=0.7,
                explanation=(
                    "Signal order is reversed, suspicious, or missing required confirmation. "
                    "Do not force a progression that the signal cannot support."
                ),
                failed_component="progression",
                observed_value="->".join(normalized),
                threshold="VALID_PROGRESSIVE_SEQUENCE",
            )
        )
    return (
        ComponentScore(
            component="progression",
            score=score,
            threshold=0.55,
            passed=passed,
            hard_reject=False,
            explanation="ValidProgression ~= ordered confirmation chain appropriate to the signal type",
        ),
        reasons,
    )


def detect_trapdoor(
    payload: TrapdoorInput,
) -> tuple[float, list[RejectionRecord]]:
    risk = clamp01(
        clamp01(payload.expected_path_deviation)
        * clamp01(payload.impact)
        * clamp01(payload.speed)
        * 1.8
    )
    reasons: list[RejectionRecord] = []
    if risk > payload.threshold:
        reasons.append(
            _make_rejection(
                code=RejectionReason.TRAPDOOR_EVENT,
                severity=SeverityLevel.HARD,
                blocking_weight=1.0,
                explanation=(
                    "Trapdoor risk is too high. Expected path, impact, and speed imply a hidden break "
                    "that should override normal promotion."
                ),
                failed_component="trapdoor",
                observed_value=round(risk, 4),
                threshold=payload.threshold,
            )
        )
    return risk, reasons


def evaluate_transition_quality(
    payload: TransitionInput,
) -> tuple[ComponentScore, TransitionClass, list[RejectionRecord]]:
    curvature = clamp01(payload.curvature)
    oscillation = clamp01(payload.oscillation)
    resolution_strength = clamp01(payload.resolution_strength)
    trapdoor_risk = clamp01(payload.trapdoor_risk)
    score = clamp01((curvature + oscillation + resolution_strength - trapdoor_risk) / 3.0)
    if trapdoor_risk >= DEFAULT_THRESHOLD_TRAPDOOR:
        transition_class = TransitionClass.TRAPDOOR
    elif resolution_strength >= 0.75 and trapdoor_risk <= 0.30:
        transition_class = TransitionClass.RESOLVED
    elif oscillation >= 0.65 and resolution_strength < 0.50:
        transition_class = TransitionClass.OSCILLATING
    elif curvature >= 0.60 and oscillation < 0.55:
        transition_class = TransitionClass.CURVED
    elif resolution_strength < 0.35 and max(curvature, oscillation) >= 0.35:
        transition_class = TransitionClass.FAILED_RESOLUTION
    elif max(curvature, oscillation, resolution_strength) <= 0.25:
        transition_class = TransitionClass.LINEAR
    else:
        transition_class = TransitionClass.UNKNOWN
    passed = transition_class in {TransitionClass.RESOLVED, TransitionClass.CURVED, TransitionClass.LINEAR}
    reasons: list[RejectionRecord] = []
    if transition_class == TransitionClass.TRAPDOOR:
        reasons.append(
            _make_rejection(
                code=RejectionReason.TRAPDOOR_EVENT,
                severity=SeverityLevel.HARD,
                blocking_weight=1.0,
                explanation="Trapdoor transition overrides normal promotion. Trade the resolution after the curve.",
                failed_component="transition_quality",
                observed_value=round(trapdoor_risk, 4),
                threshold=DEFAULT_THRESHOLD_TRAPDOOR,
            )
        )
    elif not passed:
        reasons.append(
            _make_rejection(
                code=RejectionReason.INVALID_PROGRESSION,
                severity=SeverityLevel.MEDIUM,
                blocking_weight=0.65,
                explanation="Transition remains unresolved or oscillatory; resolution strength is insufficient.",
                failed_component="transition_quality",
                observed_value=transition_class.value,
                threshold="RESOLVED",
            )
        )
    return (
        ComponentScore(
            component="transition_quality",
            score=score,
            threshold=0.55,
            passed=passed,
            hard_reject=transition_class == TransitionClass.TRAPDOOR,
            explanation="SignalValidity = FinalState * TransitionQuality * ResolutionStrength",
        ),
        transition_class,
        reasons,
    )


def evaluate_trust(
    payload: TrustInput,
) -> tuple[ComponentScore, list[RejectionRecord]]:
    score = clamp01(
        clamp01(payload.observability)
        * clamp01(payload.auditability)
        * clamp01(payload.explainability)
        * 1.6
    )
    passed = score >= payload.threshold and min(
        clamp01(payload.observability),
        clamp01(payload.auditability),
        clamp01(payload.explainability),
    ) >= 0.45
    reasons: list[RejectionRecord] = []
    if payload.high_stakes and not passed:
        reasons.append(
            _make_rejection(
                code=RejectionReason.LOW_TRUST_OBSERVABILITY,
                severity=SeverityLevel.HARD,
                blocking_weight=0.95,
                explanation="High-stakes decision lacks enough visible observability, auditability, or explainability.",
                failed_component="trust_observability",
                observed_value=round(score, 4),
                threshold=payload.threshold,
            )
        )
    return (
        ComponentScore(
            component="trust_observability",
            score=score,
            threshold=payload.threshold,
            passed=passed,
            hard_reject=payload.high_stakes and not passed,
            explanation="DecisionTrust = Observability * Auditability * Explainability",
        ),
        reasons,
    )


def evaluate_operator_clarity(
    payload: OperatorClarityInput,
) -> tuple[ComponentScore, list[RejectionRecord]]:
    score = clamp01(
        clamp01(payload.dashboard_readability)
        - mean_score(
            payload.noise,
            payload.cognitive_load,
            payload.alert_overload,
            payload.ambiguity,
        )
    )
    passed = score >= payload.threshold
    reasons: list[RejectionRecord] = []
    if not passed:
        reasons.append(
            _make_rejection(
                code=RejectionReason.LOW_OPERATOR_CLARITY,
                severity=SeverityLevel.MEDIUM,
                blocking_weight=0.8,
                explanation="Operator-facing output is too noisy or ambiguous for clear action review.",
                failed_component="operator_clarity",
                observed_value=round(score, 4),
                threshold=payload.threshold,
            )
        )
    return (
        ComponentScore(
            component="operator_clarity",
            score=score,
            threshold=payload.threshold,
            passed=passed,
            hard_reject=False,
            explanation="DecisionQuality = SignalQuality * OperatorClarity * EnvironmentQuality",
        ),
        reasons,
    )


def evaluate_reality_alignment(
    payload: RealityAnchorInput,
) -> tuple[ComponentScore, list[RejectionRecord]]:
    score = clamp01(
        clamp01(payload.freshness)
        * clamp01(payload.external_confirmation)
        * clamp01(payload.regime_consistency)
        * 1.6
    )
    stale = payload.time_since_validation_hours > payload.max_validation_age_hours
    passed = (
        not stale
        and clamp01(payload.external_confirmation) >= 0.45
        and clamp01(payload.regime_consistency) >= 0.45
        and score >= 0.45
    )
    reasons: list[RejectionRecord] = []
    if not passed:
        reasons.append(
            _make_rejection(
                code=RejectionReason.DRIFT_FROM_REALITY,
                severity=SeverityLevel.MEDIUM,
                blocking_weight=0.85,
                explanation="Validation freshness or external confirmation drifted away from current regime reality.",
                failed_component="reality_alignment",
                observed_value=round(score, 4),
                threshold=0.45,
            )
        )
    return (
        ComponentScore(
            component="reality_alignment",
            score=score,
            threshold=0.45,
            passed=passed,
            hard_reject=False,
            explanation="AlignmentScore = Freshness * ExternalConfirmation * RegimeConsistency",
        ),
        reasons,
    )


def evaluate_primitive_competence(
    payload: PrimitiveCompetenceInput,
) -> tuple[ComponentScore, list[RejectionRecord]]:
    explanation_completeness = (
        sum(
            1
            for flag in [
                payload.signal_defined,
                payload.variable_defined,
                payload.instrument_validity_explained,
                payload.invalidation_defined,
                payload.regime_defined,
                payload.wrong_proof_defined,
                payload.fallback_defined,
            ]
            if flag
        )
        / 7.0
    )
    score = clamp01(
        clamp01(payload.primitive_understanding)
        * clamp01(payload.interface_leverage)
        * clamp01(explanation_completeness)
        * 1.8
    )
    passed = explanation_completeness >= 1.0 and score >= 0.55
    reasons: list[RejectionRecord] = []
    if not passed:
        reasons.append(
            _make_rejection(
                code=RejectionReason.NO_PRIMITIVE_UNDERSTANDING,
                severity=SeverityLevel.MEDIUM,
                blocking_weight=0.8,
                explanation="Primitive explanation is incomplete. Tools amplify primitives; they do not replace them.",
                failed_component="primitive_understanding",
                observed_value=round(score, 4),
                threshold=0.55,
            )
        )
    return (
        ComponentScore(
            component="primitive_understanding",
            score=score,
            threshold=0.55,
            passed=passed,
            hard_reject=False,
            explanation="ToolPower = PrimitiveUnderstanding * InterfaceLeverage",
        ),
        reasons,
    )


def evaluate_use_case_fit(
    payload: UseCaseFitInput,
) -> tuple[ComponentScore, list[RejectionRecord]]:
    task_context = str(payload.task_context or "").strip().upper()
    tool_class = str(payload.tool_class or "").strip().upper()
    specialization_match = clamp01(payload.specialization_match)
    if tool_class == "GENERALIST_TOOL" and task_context in {"EXECUTION", "FINAL_ADMISSION"}:
        score = clamp01(specialization_match * 0.2)
    else:
        score = specialization_match
    passed = not payload.generalist_output_used_for_execution and score >= 0.45
    reasons: list[RejectionRecord] = []
    if not passed:
        reasons.append(
            _make_rejection(
                code=RejectionReason.MISUSED_GENERALIST,
                severity=SeverityLevel.HARD,
                blocking_weight=0.95,
                explanation="Generalist output is being used too close to execution without specialist validation.",
                failed_component="use_case_fit",
                observed_value=tool_class,
                threshold="SPECIALIST_TOOL_FOR_FINAL_ADMISSION",
            )
        )
    return (
        ComponentScore(
            component="use_case_fit",
            score=score,
            threshold=0.45,
            passed=passed,
            hard_reject=not passed and payload.generalist_output_used_for_execution,
            explanation="ToolFit = TaskContext * SpecializationMatch",
        ),
        reasons,
    )


def classify_buyer_type(payload: BuyerTypeInput) -> dict[str, Any]:
    scores = {
        BuyerClass.RETAIL_MOMENTUM.value: clamp01(
            0.35 * payload.narrative_strength + 0.25 * payload.risk_tolerance + 0.20 * payload.identity_fit + 0.20 * clamp01(1.0 - min(payload.time_horizon_days, 365.0) / 365.0)
        ),
        BuyerClass.INSTITUTIONAL_QUALITY.value: clamp01(
            0.40 * payload.quality_bias + 0.25 * clamp01(payload.time_horizon_days / 365.0) + 0.20 * clamp01(1.0 - payload.risk_tolerance) + 0.15 * payload.identity_fit
        ),
        BuyerClass.PASSIVE_ALLOCATION.value: clamp01(
            0.50 * payload.passive_fit + 0.25 * clamp01(payload.time_horizon_days / 365.0) + 0.25 * clamp01(1.0 - payload.risk_tolerance)
        ),
        BuyerClass.VENTURE_OPTIONALITY.value: clamp01(
            0.50 * payload.optionality + 0.25 * payload.risk_tolerance + 0.25 * payload.narrative_strength
        ),
        BuyerClass.INCOME_INVESTOR.value: clamp01(
            0.55 * payload.income_relevance + 0.25 * clamp01(1.0 - payload.risk_tolerance) + 0.20 * clamp01(payload.time_horizon_days / 365.0)
        ),
        BuyerClass.HEDGER.value: clamp01(
            0.60 * payload.hedge_need + 0.20 * clamp01(1.0 - payload.risk_tolerance) + 0.20 * payload.identity_fit
        ),
        BuyerClass.NARRATIVE_SPECULATOR.value: clamp01(
            0.45 * payload.narrative_strength + 0.35 * payload.risk_tolerance + 0.20 * payload.identity_fit
        ),
        BuyerClass.EVENT_DRIVEN.value: clamp01(
            0.55 * payload.event_catalyst_strength + 0.25 * payload.risk_tolerance + 0.20 * clamp01(1.0 - min(payload.time_horizon_days, 90.0) / 90.0)
        ),
        BuyerClass.DISTRESSED_VALUE.value: clamp01(
            0.40 * payload.optionality + 0.30 * payload.quality_bias + 0.30 * clamp01(payload.time_horizon_days / 365.0)
        ),
        BuyerClass.MACRO_ROTATION.value: clamp01(
            0.35 * payload.hedge_need + 0.35 * payload.passive_fit + 0.30 * payload.event_catalyst_strength
        ),
        BuyerClass.INSIDER_SIGNAL_FOLLOWER.value: clamp01(
            0.45 * payload.event_catalyst_strength + 0.30 * payload.narrative_strength + 0.25 * payload.risk_tolerance
        ),
    }
    buyer_type = max(scores.items(), key=lambda item: item[1])[0] if scores else BuyerClass.UNKNOWN.value
    confidence = scores.get(buyer_type, 0.0)
    return {
        "buyer_type": buyer_type,
        "confidence": round(confidence, 4),
        "objective": payload.objective,
        "time_horizon": round(max(payload.time_horizon_days, 0.0), 4),
        "risk_profile": round(clamp01(payload.risk_tolerance), 4),
        "likely_action_probability": round(clamp01(confidence * 0.9), 4),
        "capital_weight": round(clamp01(0.5 * confidence + 0.5 * payload.quality_bias), 4),
        "evaluation_model": route_evaluation_model(payload.asset_class, buyer_type),
    }


def route_evaluation_model(asset_class: str, buyer_type: str) -> str:
    normalized_asset = str(asset_class or "UNKNOWN").strip().lower()
    if normalized_asset == "crypto":
        return "CRYPTO_MOMENTUM_LIQUIDITY_NARRATIVE_MODEL"
    if normalized_asset == "etf":
        return "ETF_ALLOCATION_RISK_MACRO_MODEL"
    if normalized_asset in {"stock", "blue_chip_stock", "equity"}:
        return "BLUE_CHIP_FUNDAMENTALS_MOAT_MODEL"
    if normalized_asset == "startup":
        return "STARTUP_OPTIONALITY_SURVIVAL_MODEL"
    if normalized_asset == "event_trade" or buyer_type == BuyerClass.EVENT_DRIVEN.value:
        return "EVENT_CATALYST_REPRICING_MODEL"
    return "GENERIC_SPECIALIST_VALIDATION_MODEL"


def evaluate_buyer_alignment(
    payload: BuyerTypeInput,
    *,
    use_case_score: float,
) -> tuple[ComponentScore, dict[str, Any], list[RejectionRecord]]:
    buyer_result = classify_buyer_type(payload)
    score = clamp01(
        buyer_result["confidence"] * 0.55
        + clamp01(use_case_score) * 0.25
        + clamp01(buyer_result["capital_weight"]) * 0.20
    )
    passed = score >= payload.threshold
    reasons: list[RejectionRecord] = []
    if not passed:
        reasons.append(
            _make_rejection(
                code=RejectionReason.LOW_BUYER_ALIGNMENT,
                severity=SeverityLevel.MEDIUM,
                blocking_weight=0.85,
                explanation="Signal does not map cleanly to a buyer type, objective, and time horizon.",
                failed_component="buyer_alignment",
                observed_value=round(score, 4),
                threshold=payload.threshold,
            )
        )
    return (
        ComponentScore(
            component="buyer_alignment",
            score=score,
            threshold=payload.threshold,
            passed=passed,
            hard_reject=False,
            explanation="AssetValue = BuyerFit * UseCaseFit * TimingFit",
        ),
        buyer_result,
        reasons,
    )


def evaluate_execution_survivability(
    payload: ExecutionSurvivabilityInput,
    *,
    thresholds: dict[str, float],
) -> tuple[ComponentScore, dict[str, Any], list[RejectionRecord]]:
    survival_score = clamp01(
        1.0
        - mean_score(
            payload.volatility,
            payload.spread,
            payload.slippage,
            payload.latency,
            payload.data_gaps,
            payload.false_positive_rate,
            payload.news_reversal_risk,
            payload.liquidity_gap_risk,
            payload.operator_confusion,
            payload.external_confirmation_failure,
        )
    )
    passed = survival_score >= max(payload.threshold, _threshold(thresholds, "execution_survivability_threshold"))
    reasons: list[RejectionRecord] = []
    if not passed:
        reasons.append(
            _make_rejection(
                code=RejectionReason.LOW_EXECUTION_SURVIVABILITY,
                severity=SeverityLevel.MEDIUM,
                blocking_weight=0.9,
                explanation="Execution path does not survive current friction, spread, latency, or confirmation risk.",
                failed_component="execution_survivability",
                observed_value=round(survival_score, 4),
                threshold=max(payload.threshold, _threshold(thresholds, "execution_survivability_threshold")),
            )
        )
    return (
        ComponentScore(
            component="execution_survivability",
            score=survival_score,
            threshold=max(payload.threshold, _threshold(thresholds, "execution_survivability_threshold")),
            passed=passed,
            hard_reject=False,
            explanation="SurvivalScore = PerformanceAfterStress / PerformanceBeforeStress",
        ),
        {
            "survival_score": round(survival_score, 4),
            "maintenance_survival_threshold": round(
                max(payload.threshold, _threshold(thresholds, "execution_survivability_threshold")), 4
            ),
        },
        reasons,
    )


def evaluate_source_validation(
    payload: SourceValidationInput,
    *,
    thresholds: dict[str, float],
) -> tuple[dict[str, Any], list[RejectionRecord]]:
    source_credibility = clamp01(payload.source_credibility)
    external_confirmation = clamp01(payload.external_confirmation)
    consistency = clamp01(payload.consistency)
    wrapper_uncertainty = clamp01(payload.wrapper_uncertainty)
    validated_direction = clamp01(
        source_credibility * external_confirmation * consistency * (1.0 - wrapper_uncertainty) * 1.8
    )
    confidence = clamp01(
        0.4 * source_credibility + 0.35 * external_confirmation + 0.25 * consistency - 0.25 * wrapper_uncertainty
    )
    reasons: list[RejectionRecord] = []
    threshold = max(payload.threshold, _threshold(thresholds, "source_confirmation_threshold"))
    if source_credibility >= 0.7 and external_confirmation < threshold:
        reasons.append(
            _make_rejection(
                code=RejectionReason.SOURCE_CREDIBILITY_WITHOUT_VALIDATION,
                severity=SeverityLevel.MEDIUM,
                blocking_weight=0.75,
                explanation="Credible wrapper exists, but external confirmation depth is still below admission standard.",
                failed_component="source_validation",
                observed_value=round(external_confirmation, 4),
                threshold=threshold,
            )
        )
    return (
        {
            "source_credibility": round(source_credibility, 4),
            "external_confirmation": round(external_confirmation, 4),
            "consistency": round(consistency, 4),
            "wrapper_uncertainty": round(wrapper_uncertainty, 4),
            "validated_direction": round(validated_direction, 4),
            "validated_product_or_event": external_confirmation >= threshold and consistency >= 0.55,
            "confidence": round(confidence, 4),
        },
        reasons,
    )


def evaluate_peak_moment(payload: PeakMomentInput) -> tuple[dict[str, Any], list[RejectionRecord]]:
    peak_moment_score = clamp01(
        clamp01(payload.novelty) * clamp01(payload.emotional_intensity) * clamp01(payload.recall_frequency) * 1.8
    )
    reasons: list[RejectionRecord] = []
    if peak_moment_score >= 0.65 and clamp01(payload.total_quality) < 0.55:
        reasons.append(
            _make_rejection(
                code=RejectionReason.PEAK_MOMENT_WITHOUT_TOTAL_QUALITY,
                severity=SeverityLevel.LOW,
                blocking_weight=0.45,
                explanation="Peak moment is memorable, but total product quality is not yet strong enough for admission.",
                failed_component="peak_moment",
                observed_value=round(peak_moment_score, 4),
                threshold=0.55,
            )
        )
    return (
        {
            "memory_imprint": round(peak_moment_score, 4),
            "peak_moment_score": round(peak_moment_score, 4),
            "novelty": round(clamp01(payload.novelty), 4),
            "emotional_intensity": round(clamp01(payload.emotional_intensity), 4),
            "recall_frequency": round(clamp01(payload.recall_frequency), 4),
        },
        reasons,
    )


def evaluate_anchor_feature(payload: AnchorFeatureInput) -> dict[str, Any]:
    denominator = max(float(payload.total_feature_mentions or 0.0), 1.0)
    concentration = clamp01(float(payload.top_feature_mentions or 0.0) / denominator)
    return {
        "anchor_concentration": round(concentration, 4),
        "product_position": round(clamp01(concentration * 0.6 + clamp01(payload.baseline_competence) * 0.4), 4),
    }


def evaluate_behavioral_skin(
    payload: BehavioralSkinInput,
) -> tuple[dict[str, Any], list[RejectionRecord]]:
    cosmetic = clamp01(payload.appearance)
    behavior = clamp01(payload.behavior)
    capability = mean_score(payload.feature_access, payload.system_tuning)
    if capability >= 0.75 and behavior >= 0.7:
        skin_class = SkinClass.STRUCTURAL_SKIN
    elif behavior >= 0.55 or capability >= 0.55:
        skin_class = SkinClass.BEHAVIORAL_SKIN
    elif capability >= 0.35:
        skin_class = SkinClass.FUNCTIONAL_SKIN
    else:
        skin_class = SkinClass.COSMETIC_SKIN
    depth_score = clamp01(0.3 * cosmetic + 0.35 * behavior + 0.35 * capability)
    reasons: list[RejectionRecord] = []
    if skin_class == SkinClass.COSMETIC_SKIN and cosmetic >= 0.6:
        reasons.append(
            _make_rejection(
                code=RejectionReason.COSMETIC_SKIN_ONLY,
                severity=SeverityLevel.LOW,
                blocking_weight=0.4,
                explanation="Visible wrapper changed appearance more than behavior, capability, or system tuning.",
                failed_component="behavioral_skin",
                observed_value=skin_class.value,
                threshold=SkinClass.BEHAVIORAL_SKIN.value,
            )
        )
    return (
        {
            "skin_class": skin_class.value,
            "skin_depth_score": round(depth_score, 4),
            "strategic_skin": round(clamp01(cosmetic * 0.2 + behavior * 0.4 + capability * 0.4), 4),
        },
        reasons,
    )


def evaluate_maintenance_survival(
    payload: MaintenanceCostInput,
    *,
    thresholds: dict[str, float],
) -> tuple[dict[str, Any], list[RejectionRecord]]:
    before = max(float(payload.performance_before_stress or 0.0), 0.0001)
    survival_score = clamp01(float(payload.performance_after_stress or 0.0) / before)
    adoption_score = clamp01(
        clamp01(payload.desire) - 0.5 * clamp01(payload.maintenance_cost) - 0.5 * clamp01(payload.failure_friction)
    )
    threshold = max(payload.threshold, _threshold(thresholds, "maintenance_survival_threshold"))
    reasons: list[RejectionRecord] = []
    if survival_score < threshold:
        reasons.append(
            _make_rejection(
                code=RejectionReason.LOW_MAINTENANCE_SURVIVAL,
                severity=SeverityLevel.MEDIUM,
                blocking_weight=0.75,
                explanation="Signal or module degrades too sharply after stress, maintenance cost, or failure friction.",
                failed_component="maintenance_survival",
                observed_value=round(survival_score, 4),
                threshold=threshold,
            )
        )
    return (
        {
            "survival_score": round(survival_score, 4),
            "adoption_score": round(adoption_score, 4),
        },
        reasons,
    )


def evaluate_recovery_quality(
    payload: RecoveryQualityInput,
) -> tuple[dict[str, Any], list[RejectionRecord]]:
    surface = clamp01(payload.surface_recovery)
    structural = clamp01(payload.structural_integrity)
    if structural >= 0.75:
        recovery_class = RecoveryClass.STRUCTURAL
    elif structural >= 0.6:
        recovery_class = RecoveryClass.RISK_REDUCING
    elif surface >= 0.65 and structural < 0.45:
        recovery_class = RecoveryClass.SURFACE_ONLY
    elif surface >= 0.55:
        recovery_class = RecoveryClass.OPERATIONAL
    else:
        recovery_class = RecoveryClass.FINANCIAL
    reasons: list[RejectionRecord] = []
    if recovery_class == RecoveryClass.SURFACE_ONLY:
        reasons.append(
            _make_rejection(
                code=RejectionReason.SURFACE_ONLY_IMPROVEMENT,
                severity=SeverityLevel.LOW,
                blocking_weight=0.4,
                explanation="Observed recovery is mostly cosmetic or operational. Structural resilience is still weak.",
                failed_component="recovery_quality",
                observed_value=round(surface, 4),
                threshold=0.45,
            )
        )
    return (
        {
            "recovery_class": recovery_class.value,
            "recovery_quality": round(clamp01(0.45 * surface + 0.55 * structural), 4),
        },
        reasons,
    )


def evaluate_force_flow(
    payload: ForceFlowInput,
) -> tuple[dict[str, Any], list[RejectionRecord]]:
    price_pressure = clamp01(
        clamp01(payload.signal_force)
        * clamp01(payload.transmission_path)
        * clamp01(payload.buyer_sensitivity)
        * (1.0 - clamp01(payload.damping))
        * 1.8
    )
    reasons: list[RejectionRecord] = []
    if clamp01(payload.transmission_path) < 0.35 or price_pressure < 0.25:
        reasons.append(
            _make_rejection(
                code=RejectionReason.FORCE_FLOW_BREAK,
                severity=SeverityLevel.LOW,
                blocking_weight=0.45,
                explanation="Signal force is not transmitting cleanly through the expected market architecture.",
                failed_component="force_flow",
                observed_value=round(price_pressure, 4),
                threshold=0.25,
            )
        )
    return (
        {
            "price_pressure": round(price_pressure, 4),
            "system_response": round(clamp01(price_pressure * (1.0 - clamp01(payload.damping))), 4),
        },
        reasons,
    )


def evaluate_actor_response(
    payload: ActorResponseInput,
) -> tuple[dict[str, Any], list[RejectionRecord]]:
    expected_move = 0.0
    reaction_detail: dict[str, float] = {}
    for buyer_class, probability in payload.buyer_probabilities.items():
        capital_weight = clamp01(payload.capital_weights.get(buyer_class, 0.0))
        contribution = clamp01(probability) * capital_weight
        reaction_detail[buyer_class] = round(contribution, 4)
        expected_move += contribution
    expected_move = clamp01(expected_move)
    conviction = clamp01(payload.conviction)
    reaction_speed = clamp01(payload.reaction_speed)
    clarity_score = clamp01(expected_move * 0.5 + conviction * 0.3 + reaction_speed * 0.2)
    reasons: list[RejectionRecord] = []
    if clarity_score < payload.threshold:
        reasons.append(
            _make_rejection(
                code=RejectionReason.ACTOR_RESPONSE_UNCLEAR,
                severity=SeverityLevel.MEDIUM,
                blocking_weight=0.75,
                explanation="The system cannot yet identify who is likely to act, how quickly, or with enough capital weight.",
                failed_component="actor_response",
                observed_value=round(clarity_score, 4),
                threshold=payload.threshold,
            )
        )
    return (
        {
            "expected_move": round(expected_move, 4),
            "buyer_classes": sorted(reaction_detail.keys()),
            "probability_action_by_class": {key: round(clamp01(value), 4) for key, value in payload.buyer_probabilities.items()},
            "capital_weight_by_class": {key: round(clamp01(value), 4) for key, value in payload.capital_weights.items()},
            "estimated_reaction_speed": round(reaction_speed, 4),
            "conviction_score": round(conviction, 4),
            "clarity_score": round(clarity_score, 4),
        },
        reasons,
    )


def compute_bull_state(
    *,
    chaos_veto: bool,
    policy_veto: bool,
    trapdoor_risk: float,
    validation_strength: float,
    material_durability: float,
    buyer_alignment: float,
    execution_survivability: float,
    primitive_understanding: float,
    fast_track_momentum: float,
    thresholds: dict[str, float],
) -> tuple[str, str]:
    if policy_veto or chaos_veto:
        return BullState.DIABLO.value, "Policy veto or chaos veto outranks all admission logic."
    if trapdoor_risk >= _threshold(thresholds, "trapdoor_risk_max"):
        return BullState.ISLERO.value, "Trapdoor risk remains too high for normal promotion."
    fast_track = (
        clamp01(fast_track_momentum) >= _threshold(thresholds, "fast_track_momentum_threshold")
        and clamp01(validation_strength) >= _threshold(thresholds, "fast_track_validation_threshold")
        and trapdoor_risk < _threshold(thresholds, "trapdoor_risk_max")
        and primitive_understanding >= _threshold(thresholds, "primitive_understanding_threshold")
    )
    if fast_track and execution_survivability >= _threshold(thresholds, "execution_survivability_threshold"):
        return BullState.HURACAN.value, "Momentum fast-track is allowed only because validation and risk caps remain clean."
    if material_durability >= _threshold(thresholds, "material_durability_threshold") and validation_strength >= _threshold(thresholds, "validation_strength_threshold"):
        if buyer_alignment >= _threshold(thresholds, "buyer_alignment_threshold") and execution_survivability >= _threshold(thresholds, "execution_survivability_threshold"):
            return BullState.AVENTADOR.value, "Signal survived durability, buyer-fit, and execution-survivability review."
        return BullState.MURCIELAGO.value, "Signal is durable and validated, but buyer or execution fit still needs work."
    if validation_strength >= 0.45:
        return BullState.MIURA.value, "Signal remains in raw or partially validated detection mode."
    return BullState.UNKNOWN.value, "Admission logic does not support promotion yet."


def _next_required_action(
    *,
    admission_class: AdmissionClass,
    reasons: list[RejectionRecord],
) -> str:
    if admission_class == AdmissionClass.CHAOS_VETO:
        return "WAIT_FOR_POLICY_AND_CHAOS_CLEARANCE"
    if any(reason.code == RejectionReason.DRIFT_FROM_REALITY.value for reason in reasons):
        return "RECHECK_EXTERNAL_CONFIRMATION"
    if any(reason.code == RejectionReason.NO_PRIMITIVE_UNDERSTANDING.value for reason in reasons):
        return "COMPLETE_PRIMITIVE_CHECKLIST"
    if any(reason.code == RejectionReason.LOW_BUYER_ALIGNMENT.value for reason in reasons):
        return "MAP_SIGNAL_TO_BUYER_AND_USE_CASE"
    if admission_class == AdmissionClass.ADMIT_WATCHLIST_ONLY:
        return "PROMOTE_TO_WATCHLIST"
    if admission_class == AdmissionClass.ADMIT_EXECUTION_CANDIDATE:
        return "KEEP_HUMAN_REVIEW_REQUIRED"
    return "OBSERVE_AND_REVALIDATE"


def _admission_class(
    *,
    admission_score: float,
    trust_observability: float,
    reality_alignment: float,
    hard_reject: bool,
    chaos_veto: bool,
) -> AdmissionClass:
    if chaos_veto:
        return AdmissionClass.CHAOS_VETO
    if hard_reject:
        return AdmissionClass.REJECT
    if admission_score >= 0.80 and trust_observability >= 0.75 and reality_alignment >= 0.75:
        return AdmissionClass.ADMIT_EXECUTION_CANDIDATE
    if admission_score >= 0.60:
        return AdmissionClass.ADMIT_WATCHLIST_ONLY
    if reality_alignment < 0.50:
        return AdmissionClass.NEEDS_REVALIDATION
    return AdmissionClass.OBSERVE_ONLY


def _operator_summary(
    *,
    admission_class: AdmissionClass,
    reasons: list[RejectionRecord],
    recommended_engine: EngineClass,
    regime_class: RegimeClass,
) -> str:
    if admission_class == AdmissionClass.CHAOS_VETO:
        return (
            "Signal is not admissible for execution review. Existing policy or chaos veto still dominates. "
            f"Recommended engine: {recommended_engine.value}. Regime: {regime_class.value}. "
            "Required action: observe, reduce complexity, and do not add new risk."
        )
    if not reasons:
        return (
            f"Signal passed structural admission review. Recommended class: {admission_class.value}. "
            f"Recommended engine: {recommended_engine.value}. Regime: {regime_class.value}."
        )
    top_reasons = "; ".join(reason.code for reason in reasons[:3])
    return (
        "Signal rejected or downgraded. The signal may be attractive, but it fails structural admission due to "
        f"{top_reasons}. Recommended state: {admission_class.value}. "
        f"Required fix: revalidate with the correct instrument, confirm regime fit, and wait for cleaner resolution. "
        f"Recommended engine: {recommended_engine.value}. Regime: {regime_class.value}."
    )


def _operator_summary_payload(
    *,
    admission_class: AdmissionClass,
    summary_text: str,
    next_required_action: str,
) -> dict[str, str]:
    state_map = {
        AdmissionClass.ADMIT_EXECUTION_CANDIDATE: "EXECUTE",
        AdmissionClass.ADMIT_WATCHLIST_ONLY: "PROMOTE",
        AdmissionClass.NEEDS_REVALIDATION: "RECHECK_REALITY",
        AdmissionClass.CHAOS_VETO: "CHAOS_VETO",
        AdmissionClass.REJECT: "REJECT",
        AdmissionClass.OBSERVE_ONLY: "WAIT",
    }
    state = state_map.get(admission_class, "BLOCK")
    do_not_do = (
        "Do not execute automatically."
        if admission_class != AdmissionClass.ADMIT_EXECUTION_CANDIDATE
        else "Do not bypass policy, chaos, or human review."
    )
    return {
        "state": state,
        "plain_english_reason": summary_text,
        "do_next": next_required_action,
        "do_not_do": do_not_do,
    }


def evaluate_structural_admission(
    payload: StructuralAdmissionInput,
) -> StructuralAdmissionResult:
    thresholds = load_structural_admission_thresholds()
    design_integrity, design_reasons = evaluate_design_integrity(payload.design_integrity)
    domain_fit, domain_reasons = evaluate_domain_fit(payload.domain_instrument)
    environment_fit, regime_class, recommended_engine, environment_reasons = evaluate_environment_fit(
        payload.environment
    )
    material_durability, material_class, material_reasons = evaluate_material_durability(
        payload.burn_profile
    )
    signal_harmony, _, harmony_reasons = evaluate_signal_harmony(payload.signal_graph)
    progression_score, progression_reasons = validate_progression(payload.progression)
    trapdoor_risk, trapdoor_reasons = detect_trapdoor(payload.trapdoor)
    transition_score, transition_class, transition_reasons = evaluate_transition_quality(
        TransitionInput(
            curvature=payload.transition.curvature,
            oscillation=payload.transition.oscillation,
            resolution_strength=payload.transition.resolution_strength,
            trapdoor_risk=max(payload.transition.trapdoor_risk, trapdoor_risk),
        )
    )
    trust_observability, trust_reasons = evaluate_trust(payload.trust)
    operator_clarity, clarity_reasons = evaluate_operator_clarity(payload.operator_clarity)
    reality_alignment, reality_reasons = evaluate_reality_alignment(payload.reality_anchor)
    primitive_understanding, primitive_reasons = evaluate_primitive_competence(
        payload.primitive_competence
    )
    use_case_fit, use_case_reasons = evaluate_use_case_fit(payload.use_case_fit)
    buyer_alignment, buyer_type_result, buyer_reasons = evaluate_buyer_alignment(
        payload.buyer_type,
        use_case_score=use_case_fit.score,
    )
    execution_survivability, execution_survivability_detail, execution_reasons = (
        evaluate_execution_survivability(payload.execution_survivability, thresholds=thresholds)
    )
    source_validation_result, source_validation_reasons = evaluate_source_validation(
        payload.source_validation,
        thresholds=thresholds,
    )
    peak_moment_result, peak_moment_reasons = evaluate_peak_moment(payload.peak_moment)
    anchor_feature_result = evaluate_anchor_feature(payload.anchor_feature)
    behavioral_skin_result, behavioral_skin_reasons = evaluate_behavioral_skin(
        payload.behavioral_skin
    )
    maintenance_survival_result, maintenance_survival_reasons = evaluate_maintenance_survival(
        payload.maintenance_cost,
        thresholds=thresholds,
    )
    recovery_quality_result, recovery_quality_reasons = evaluate_recovery_quality(
        payload.recovery_quality
    )
    force_flow_result, force_flow_reasons = evaluate_force_flow(payload.force_flow)
    actor_response_result, actor_response_reasons = evaluate_actor_response(
        payload.actor_response
    )

    component_scores = {
        "domain_fit": domain_fit.score,
        "environment_fit": environment_fit.score,
        "material_durability": material_durability.score,
        "signal_harmony": signal_harmony.score,
        "transition_quality": transition_score.score,
        "validation_strength": clamp01(payload.validation_strength),
        "trust_observability": trust_observability.score,
        "operator_clarity": operator_clarity.score,
        "reality_alignment": reality_alignment.score,
        "primitive_understanding": primitive_understanding.score,
        "use_case_fit": use_case_fit.score,
        "buyer_alignment": buyer_alignment.score,
        "execution_survivability": execution_survivability.score,
    }
    admission_score = min(component_scores.values())
    diagnostic_score = weighted_sum(
        component_scores,
        {
            "domain_fit": 0.10,
            "environment_fit": 0.10,
            "material_durability": 0.10,
            "signal_harmony": 0.10,
            "transition_quality": 0.10,
            "validation_strength": 0.15,
            "trust_observability": 0.10,
            "operator_clarity": 0.10,
            "reality_alignment": 0.10,
            "primitive_understanding": 0.075,
            "use_case_fit": 0.075,
            "buyer_alignment": 0.075,
            "execution_survivability": 0.075,
        },
    )
    all_reasons = (
        design_reasons
        + domain_reasons
        + environment_reasons
        + material_reasons
        + harmony_reasons
        + progression_reasons
        + trapdoor_reasons
        + transition_reasons
        + trust_reasons
        + clarity_reasons
        + reality_reasons
        + primitive_reasons
        + use_case_reasons
        + buyer_reasons
        + execution_reasons
        + source_validation_reasons
        + peak_moment_reasons
        + behavioral_skin_reasons
        + maintenance_survival_reasons
        + recovery_quality_reasons
        + force_flow_reasons
        + actor_response_reasons
    )
    hard_reject = any(reason.severity == SeverityLevel.HARD.value for reason in all_reasons)
    chaos_veto = bool(payload.chaos_veto or payload.policy_veto)
    admission_class = _admission_class(
        admission_score=admission_score,
        trust_observability=component_scores["trust_observability"],
        reality_alignment=component_scores["reality_alignment"],
        hard_reject=hard_reject,
        chaos_veto=chaos_veto,
    )
    if payload.policy_veto and not any(
        reason.code == RejectionReason.ENVIRONMENT_MISMATCH.value for reason in all_reasons
    ):
        all_reasons.append(
            _make_rejection(
                code=RejectionReason.ENVIRONMENT_MISMATCH,
                severity=SeverityLevel.HARD,
                blocking_weight=1.0,
                explanation="Existing policy state already forbids new risk; structural admission cannot override it.",
                failed_component="policy_hierarchy",
                observed_value="allow_new_risk=false",
                threshold="allow_new_risk=true",
            )
        )
    bull_state, bull_reason = compute_bull_state(
        chaos_veto=bool(payload.chaos_veto),
        policy_veto=bool(payload.policy_veto),
        trapdoor_risk=trapdoor_risk,
        validation_strength=clamp01(payload.validation_strength),
        material_durability=material_durability.score,
        buyer_alignment=buyer_alignment.score,
        execution_survivability=execution_survivability.score,
        primitive_understanding=primitive_understanding.score,
        fast_track_momentum=payload.fast_track_momentum,
        thresholds=thresholds,
    )
    bottleneck_layer = min(component_scores, key=component_scores.get)
    passed = admission_class in {
        AdmissionClass.ADMIT_EXECUTION_CANDIDATE.value,
        AdmissionClass.ADMIT_WATCHLIST_ONLY.value,
    }
    next_required_action = _next_required_action(
        admission_class=admission_class,
        reasons=all_reasons,
    )
    operator_summary_text = _operator_summary(
        admission_class=admission_class,
        reasons=all_reasons[:3],
        recommended_engine=recommended_engine,
        regime_class=regime_class,
    )
    operator_summary_payload = _operator_summary_payload(
        admission_class=admission_class,
        summary_text=operator_summary_text,
        next_required_action=next_required_action,
    )
    serialized_reasons = [asdict(reason) for reason in all_reasons]
    layer_scores = {
        design_integrity.component: asdict(design_integrity),
        domain_fit.component: asdict(domain_fit),
        environment_fit.component: asdict(environment_fit),
        material_durability.component: asdict(material_durability),
        signal_harmony.component: asdict(signal_harmony),
        transition_score.component: asdict(transition_score),
        trust_observability.component: asdict(trust_observability),
        operator_clarity.component: asdict(operator_clarity),
        reality_alignment.component: asdict(reality_alignment),
        primitive_understanding.component: asdict(primitive_understanding),
        use_case_fit.component: asdict(use_case_fit),
        buyer_alignment.component: asdict(buyer_alignment),
        execution_survivability.component: asdict(execution_survivability),
        "progression": asdict(progression_score),
    }
    return StructuralAdmissionResult(
        admission_score=round(admission_score, 4),
        diagnostic_score=round(diagnostic_score, 4),
        admission_class=admission_class.value,
        passed=passed,
        bottleneck_layer=bottleneck_layer,
        hard_reject=hard_reject,
        chaos_veto=chaos_veto,
        recommended_engine=recommended_engine.value,
        regime_class=regime_class.value,
        material_class=material_class.value,
        transition_class=transition_class.value,
        buyer_type=buyer_type_result,
        materiality={
            "material_class": material_class.value,
            "ignition_speed": round(clamp01(payload.burn_profile.ignition_speed), 4),
            "duration": round(clamp01(payload.burn_profile.duration_score), 4),
            "stability": round(clamp01(payload.burn_profile.stability_score), 4),
            "environment_resistance": round(clamp01(payload.burn_profile.environment_resistance_score), 4),
            "decay_rate": round(clamp01(payload.burn_profile.decay_rate), 4),
            "durability_score": round(material_durability.score, 4),
        },
        transition={
            "transition_class": transition_class.value,
            "curvature": round(clamp01(payload.transition.curvature), 4),
            "oscillation": round(clamp01(payload.transition.oscillation), 4),
            "resolution_strength": round(clamp01(payload.transition.resolution_strength), 4),
            "trapdoor_risk": round(clamp01(max(payload.transition.trapdoor_risk, trapdoor_risk)), 4),
            "transition_quality": round(transition_score.score, 4),
            "passed": transition_score.passed,
        },
        source_validation=source_validation_result,
        actor_response=actor_response_result,
        bull_state=bull_state,
        next_required_action=next_required_action,
        component_scores={key: round(value, 4) for key, value in component_scores.items()},
        layer_scores=layer_scores,
        rejection_reasons=serialized_reasons,
        operator_summary=operator_summary_text,
        operator_summary_payload=operator_summary_payload,
    )


def _top_validation_row(signal_refinery_report: dict[str, Any] | None = None) -> dict[str, Any]:
    rows = (
        signal_refinery_report.get("validation_engine", {}).get("signals", [])
        if isinstance(signal_refinery_report, dict)
        else []
    )
    if not isinstance(rows, list):
        return {}
    for row in rows:
        if isinstance(row, dict):
            return row
    return {}


def _top_perception_row(perception_control_report: dict[str, Any] | None = None) -> dict[str, Any]:
    rows = perception_control_report.get("signals", []) if isinstance(perception_control_report, dict) else []
    if not isinstance(rows, list):
        return {}
    for row in rows:
        if isinstance(row, dict):
            return row
    return {}


def build_structural_admission_report(
    *,
    runtime_state: dict[str, Any],
    signal_refinery_report: dict[str, Any],
    attention_proxy_report: dict[str, Any],
    perception_control_report: dict[str, Any],
    friction_report: dict[str, Any] | None = None,
    trend_report: dict[str, Any] | None = None,
    output_path: Path | None = None,
    write_runtime: bool = False,
) -> dict[str, Any]:
    validation_row = _top_validation_row(signal_refinery_report)
    perception_row = _top_perception_row(perception_control_report)
    active_blockers = runtime_state.get("active_blockers", [])
    if not isinstance(active_blockers, list):
        active_blockers = []
    policy = runtime_state.get("execution_policy", {})
    allow_new_risk = bool(policy.get("allow_new_risk", False))
    chaos_veto = "REALM_BIS" in [str(item).upper() for item in active_blockers]
    friction_band = str((friction_report or {}).get("friction_band") or "HIGH_FRICTION").upper()
    volatility = max(
        clamp01(float(attention_proxy_report.get("narrative_heat_score", 0.0) or 0.0)),
        1.0 if chaos_veto else 0.0,
    )
    source_quality = clamp01(
        float(validation_row.get("source_quality_score", perception_row.get("source_quality", 0.0)) or 0.0)
    )
    selected_engine = (
        EngineClass.MATCHBOX_ENGINE
        if chaos_veto or not allow_new_risk
        else EngineClass.ZIPPO_ENGINE if friction_band == "MEDIUM_FRICTION" or volatility >= 0.55 else EngineClass.BIC_ENGINE
    )
    progression_sequence = ["EVENT", "NEWS", "SENTIMENT", "VOLUME", "PRICE"]
    if float(validation_row.get("cross_source_confirmation_score", 0.0) or 0.0) >= 0.45:
        progression_sequence.append("OPTIONS")
    validation_strength = clamp01(float(validation_row.get("validation_score", 0.0) or 0.0))
    cross_confirmation = clamp01(float(validation_row.get("cross_source_confirmation_score", 0.0) or 0.0))
    blocker_clearance = clamp01(float(validation_row.get("blocker_clearance_score", 0.0) or 0.0))
    novelty_score = clamp01(float(validation_row.get("novelty_score", 0.0) or 0.0))
    first_order_score = clamp01(float(validation_row.get("first_order_score", 0.0) or 0.0))
    repricing_headroom = clamp01(float(validation_row.get("repricing_headroom_score", 0.0) or 0.0))
    readiness_compatibility = clamp01(float(perception_row.get("readiness_compatibility", 0.0) or 0.0))
    survival_score = clamp01(float(perception_row.get("survival_score", 0.0) or 0.0))
    attention_score = clamp01(float(attention_proxy_report.get("attention_proxy_score", 0.0) or 0.0))
    narrative_heat = clamp01(float(attention_proxy_report.get("narrative_heat_score", 0.0) or 0.0))
    temporal_clean = (
        str(runtime_state.get("temporal_integrity", {}).get("temporal_integrity_state", "CLEAN")).upper()
        == "CLEAN"
    )
    input_payload = StructuralAdmissionInput(
        design_integrity=DesignIntegrityInput(
            readability_score=clamp01(float(perception_control_report.get("average_signal_lux", 0.0) or 0.0)),
            structure_score=clamp01(float(perception_row.get("structural_relevance", 0.0) or 0.0)),
            traceability_score=source_quality,
            risk_visibility_score=clamp01(1.0 - float(validation_row.get("blocker_clearance_score", 0.0) or 0.0)),
            execution_clarity_score=readiness_compatibility,
            utility_high=bool(runtime_state.get("signal_summary", {}).get("signals_above_ce_threshold", 0) or 0),
        ),
        domain_instrument=DomainInstrumentInput(
            instrument_domain="MARKET_STRUCTURE" if validation_row else "UNKNOWN",
            required_variable_domain="MARKET_STRUCTURE" if validation_row else "UNKNOWN",
        ),
        environment=EnvironmentInput(
            volatility=volatility,
            liquidity=source_quality,
            spread=clamp01(1.0 - source_quality),
            news_intensity=clamp01(float(attention_proxy_report.get("attention_proxy_score", 0.0) or 0.0)),
            correlation_break=clamp01(1.0 - float((trend_report or {}).get("policy_improvement_trend", {}).get("latest", 0) or 0) / 4.0),
            execution_friction=1.0 if friction_band == "HIGH_FRICTION" else 0.5 if friction_band == "MEDIUM_FRICTION" else 0.2,
            selected_engine=selected_engine,
        ),
        burn_profile=BurnProfile(
            ignition_speed=novelty_score,
            duration_score=first_order_score,
            stability_score=survival_score,
            environment_resistance_score=blocker_clearance,
            decay_rate=clamp01(1.0 - float(perception_control_report.get("signal_survival_rate", 0.0) or 0.0)),
        ),
        signal_graph=SignalGraphInput(
            node_values={
                "PRICE": validation_strength,
                "VOLUME": first_order_score,
                "NEWS": attention_score,
                "LIQUIDITY": source_quality,
                "EVENT_PRIOR": repricing_headroom,
                "TECHNICAL": clamp01(float(runtime_state.get("signal_summary", {}).get("scm_rate", 0.0) or 0.0)),
                "BUYER_TYPE": clamp01(float(runtime_state.get("position_truth_summary", {}).get("position_count", 0) or 0) / 5.0),
            },
            expected_edges=[("PRICE", "VOLUME"), ("NEWS", "PRICE"), ("LIQUIDITY", "PRICE"), ("PRICE", "BUYER_TYPE")],
            observed_edges=[
                ("PRICE", "VOLUME", "confirm" if first_order_score >= 0.45 else "conflict"),
                ("NEWS", "PRICE", "confirm" if attention_score <= 0.65 else "conflict"),
                ("LIQUIDITY", "PRICE", "confirm" if source_quality >= 0.45 else "conflict"),
                ("PRICE", "BUYER_TYPE", "confirm" if validation_strength >= 0.45 else "conflict"),
            ],
        ),
        progression=ProgressionInput(
            observed_sequence=progression_sequence,
            required_confirmations=["PRICE", "VOLUME"],
        ),
        transition=TransitionInput(
            curvature=novelty_score,
            oscillation=narrative_heat,
            resolution_strength=first_order_score,
            trapdoor_risk=clamp01(1.0 - blocker_clearance),
        ),
        trapdoor=TrapdoorInput(
            expected_path_deviation=clamp01(1.0 - blocker_clearance),
            impact=volatility,
            speed=attention_score,
        ),
        trust=TrustInput(
            observability=clamp01(float(perception_control_report.get("noise_suppression_ratio", 0.0) or 0.0)),
            auditability=1.0 if validation_row else 0.0,
            explainability=1.0 if validation_row and perception_row else 0.0,
            high_stakes=True,
        ),
        operator_clarity=OperatorClarityInput(
            dashboard_readability=clamp01(float(perception_control_report.get("average_signal_lux", 0.0) or 0.0)),
            noise=clamp01(1.0 - float(perception_control_report.get("noise_suppression_ratio", 0.0) or 0.0)),
            cognitive_load=clamp01(len(active_blockers) / 4.0),
            alert_overload=clamp01(float(runtime_state.get("signal_summary", {}).get("signals_above_ce_threshold", 0) or 0) / 10.0),
            ambiguity=clamp01(1.0 - float(validation_row.get("validation_score", 0.0) or 0.0)),
        ),
        reality_anchor=RealityAnchorInput(
            freshness=1.0,
            external_confirmation=0.45 if runtime_state.get("truth_origin") == "external" else 0.35,
            regime_consistency=1.0 if temporal_clean else 0.25,
            time_since_validation_hours=0.0,
        ),
        primitive_competence=PrimitiveCompetenceInput(
            primitive_understanding=validation_strength,
            interface_leverage=1.0 if validation_row else 0.0,
            signal_defined=bool(validation_row),
            variable_defined=bool(validation_row),
            instrument_validity_explained=bool(validation_row),
            invalidation_defined=bool(validation_row.get("blocker_clearance_score") is not None),
            regime_defined=True,
            wrong_proof_defined=bool(validation_row),
            fallback_defined=True,
        ),
        use_case_fit=UseCaseFitInput(
            task_context="FINAL_ADMISSION",
            tool_class="SPECIALIST_TOOL",
            specialization_match=1.0 if validation_row else 0.0,
            generalist_output_used_for_execution=False,
        ),
        buyer_type=BuyerTypeInput(
            asset_class=str(validation_row.get("asset_class") or runtime_state.get("asset_class") or "stock"),
            objective="EXECUTION_CANDIDATE_REVIEW",
            risk_tolerance=narrative_heat,
            time_horizon_days=max(5.0, float(runtime_state.get("signal_summary", {}).get("avg_hold_days", 5.0) or 5.0)),
            identity_fit=clamp01(float(runtime_state.get("signal_summary", {}).get("scm_rate", 0.0) or 0.0)),
            narrative_strength=attention_score,
            income_relevance=clamp01(float(validation_row.get("cashflow_quality_score", 0.0) or 0.0)),
            optionality=repricing_headroom,
            hedge_need=clamp01(float(len(active_blockers)) / 5.0),
            event_catalyst_strength=novelty_score,
            quality_bias=validation_strength,
            passive_fit=source_quality,
        ),
        execution_survivability=ExecutionSurvivabilityInput(
            volatility=volatility,
            spread=clamp01(1.0 - source_quality),
            slippage=1.0 if friction_band == "HIGH_FRICTION" else 0.5 if friction_band == "MEDIUM_FRICTION" else 0.2,
            latency=clamp01(1.0 - float(perception_control_report.get("noise_suppression_ratio", 0.0) or 0.0)),
            data_gaps=clamp01(1.0 - source_quality),
            false_positive_rate=clamp01(1.0 - validation_strength),
            news_reversal_risk=attention_score,
            liquidity_gap_risk=clamp01(1.0 - source_quality),
            operator_confusion=clamp01(len(active_blockers) / 5.0),
            external_confirmation_failure=clamp01(1.0 - cross_confirmation),
        ),
        source_validation=SourceValidationInput(
            source_credibility=source_quality,
            external_confirmation=cross_confirmation,
            consistency=validation_strength,
            wrapper_uncertainty=clamp01(1.0 - source_quality),
        ),
        peak_moment=PeakMomentInput(
            novelty=novelty_score,
            emotional_intensity=attention_score,
            recall_frequency=narrative_heat,
            total_quality=validation_strength,
        ),
        anchor_feature=AnchorFeatureInput(
            top_feature_mentions=float(runtime_state.get("signal_summary", {}).get("signals_above_ce_threshold", 0) or 0),
            total_feature_mentions=float(max(runtime_state.get("signal_summary", {}).get("total_signals", 0) or 0, 1)),
            baseline_competence=validation_strength,
        ),
        behavioral_skin=BehavioralSkinInput(
            appearance=attention_score,
            behavior=readiness_compatibility,
            feature_access=validation_strength,
            system_tuning=survival_score,
        ),
        maintenance_cost=MaintenanceCostInput(
            performance_after_stress=blocker_clearance,
            performance_before_stress=max(validation_strength, 0.0001),
            desire=attention_score,
            maintenance_cost=clamp01(1.0 - blocker_clearance),
            failure_friction=1.0 if friction_band == "HIGH_FRICTION" else 0.5 if friction_band == "MEDIUM_FRICTION" else 0.2,
        ),
        recovery_quality=RecoveryQualityInput(
            surface_recovery=attention_score,
            structural_integrity=blocker_clearance,
        ),
        force_flow=ForceFlowInput(
            signal_force=validation_strength,
            transmission_path=source_quality,
            buyer_sensitivity=attention_score,
            damping=clamp01(len(active_blockers) / 5.0),
        ),
        actor_response=ActorResponseInput(
            buyer_probabilities={
                BuyerClass.RETAIL_MOMENTUM.value: attention_score,
                BuyerClass.INSTITUTIONAL_QUALITY.value: validation_strength,
                BuyerClass.EVENT_DRIVEN.value: novelty_score,
            },
            capital_weights={
                BuyerClass.RETAIL_MOMENTUM.value: 0.35,
                BuyerClass.INSTITUTIONAL_QUALITY.value: 0.75 if allow_new_risk else 0.25,
                BuyerClass.EVENT_DRIVEN.value: 0.5,
            },
            reaction_speed=attention_score,
            conviction=validation_strength,
        ),
        validation_strength=validation_strength,
        fast_track_momentum=clamp01(float(runtime_state.get("signal_summary", {}).get("scm_rate", 0.0) or 0.0)),
        chaos_veto=chaos_veto,
        policy_veto=not allow_new_risk,
        system_name=str(validation_row.get("ticker") or "PIPELINE"),
        source="DEFAULT_STRUCTURAL_ADMISSION",
    )
    peak_moment_result, _ = evaluate_peak_moment(input_payload.peak_moment)
    anchor_feature_result = evaluate_anchor_feature(input_payload.anchor_feature)
    behavioral_skin_result, _ = evaluate_behavioral_skin(input_payload.behavioral_skin)
    maintenance_survival_result, _ = evaluate_maintenance_survival(
        input_payload.maintenance_cost,
        thresholds=load_structural_admission_thresholds(),
    )
    recovery_quality_result, _ = evaluate_recovery_quality(input_payload.recovery_quality)
    force_flow_result, _ = evaluate_force_flow(input_payload.force_flow)
    result = evaluate_structural_admission(input_payload)
    report = asdict(result)
    report["peak_moment"] = peak_moment_result
    report["anchor_feature"] = anchor_feature_result
    report["behavioral_skin"] = behavioral_skin_result
    report["maintenance_survival"] = maintenance_survival_result
    report["recovery_quality"] = recovery_quality_result
    report["force_flow"] = force_flow_result
    report["thresholds"] = load_structural_admission_thresholds()
    report["input_summary"] = {
        "system_name": input_payload.system_name,
        "source": input_payload.source,
        "policy_state": str(policy.get("policy_state", "UNKNOWN")),
        "selected_engine": selected_engine.value,
    }
    report["source_mode"] = get_source_mode()
    report["report_path"] = repo_relative(output_path or STRUCTURAL_ADMISSION_REPORT_PATH)
    if write_runtime:
        write_json_atomic(output_path or STRUCTURAL_ADMISSION_REPORT_PATH, report, stamp=True)
    return report


def format_structural_admission_summary(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Structural Admission Layer",
            f"admission_class={report.get('admission_class', AdmissionClass.OBSERVE_ONLY.value)}",
            f"admission_score={report.get('admission_score', 0.0)}",
            f"diagnostic_score={report.get('diagnostic_score', 0.0)}",
            f"regime_class={report.get('regime_class', RegimeClass.UNKNOWN.value)}",
            f"recommended_engine={report.get('recommended_engine', EngineClass.MATCHBOX_ENGINE.value)}",
            f"bull_state={report.get('bull_state', BullState.UNKNOWN.value)}",
            f"next_required_action={report.get('next_required_action', 'OBSERVE_AND_REVALIDATE')}",
        ]
    )


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate the structural admission layer."
    )
    parser.add_argument("--summary", action="store_true", help="Emit a compact summary.")
    parser.add_argument("--write-runtime", action="store_true", help="Persist runtime artifact.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    runtime_state = build_runtime_state_from_scm_report_payload(build_signal_conversion_report())
    report = build_structural_admission_report(
        runtime_state=runtime_state,
        signal_refinery_report={},
        attention_proxy_report={},
        perception_control_report={},
        write_runtime=args.write_runtime,
    )
    if args.summary:
        print(format_structural_admission_summary(report))
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
