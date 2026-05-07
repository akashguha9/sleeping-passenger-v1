from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

try:
    from scripts.runtime_common import (
        STRUCTURAL_ADMISSION_REPORT_PATH,
        build_runtime_state_from_scm_report_payload,
        get_run_id,
        get_source_mode,
        repo_relative,
        utc_timestamp,
        write_json_atomic,
    )
    from scripts.signal_conversion_monitor import build_signal_conversion_report
except ModuleNotFoundError:
    from runtime_common import (  # type: ignore[no-redef]
        STRUCTURAL_ADMISSION_REPORT_PATH,
        build_runtime_state_from_scm_report_payload,
        get_run_id,
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
    validation_strength: float = 0.0
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
    hard_reject: bool
    chaos_veto: bool
    recommended_engine: str
    regime_class: str
    material_class: str
    transition_class: str
    component_scores: dict[str, float]
    rejection_reasons: list[dict[str, Any]]
    operator_summary: str


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


def evaluate_structural_admission(
    payload: StructuralAdmissionInput,
) -> StructuralAdmissionResult:
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
    serialized_reasons = [asdict(reason) for reason in all_reasons]
    return StructuralAdmissionResult(
        admission_score=round(admission_score, 4),
        diagnostic_score=round(diagnostic_score, 4),
        admission_class=admission_class.value,
        hard_reject=hard_reject,
        chaos_veto=chaos_veto,
        recommended_engine=recommended_engine.value,
        regime_class=regime_class.value,
        material_class=material_class.value,
        transition_class=transition_class.value,
        component_scores={key: round(value, 4) for key, value in component_scores.items()},
        rejection_reasons=serialized_reasons,
        operator_summary=_operator_summary(
            admission_class=admission_class,
            reasons=all_reasons[:3],
            recommended_engine=recommended_engine,
            regime_class=regime_class,
        ),
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
    input_payload = StructuralAdmissionInput(
        design_integrity=DesignIntegrityInput(
            readability_score=clamp01(float(perception_control_report.get("average_signal_lux", 0.0) or 0.0)),
            structure_score=clamp01(float(perception_row.get("structural_relevance", 0.0) or 0.0)),
            traceability_score=source_quality,
            risk_visibility_score=clamp01(1.0 - float(validation_row.get("blocker_clearance_score", 0.0) or 0.0)),
            execution_clarity_score=clamp01(float(perception_row.get("readiness_compatibility", 0.0) or 0.0)),
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
            ignition_speed=clamp01(float(validation_row.get("novelty_score", 0.0) or 0.0)),
            duration_score=clamp01(float(validation_row.get("first_order_score", 0.0) or 0.0)),
            stability_score=clamp01(float(perception_row.get("survival_score", 0.0) or 0.0)),
            environment_resistance_score=clamp01(float(validation_row.get("blocker_clearance_score", 0.0) or 0.0)),
            decay_rate=clamp01(1.0 - float(perception_control_report.get("signal_survival_rate", 0.0) or 0.0)),
        ),
        signal_graph=SignalGraphInput(
            node_values={
                "PRICE": clamp01(float(validation_row.get("validation_score", 0.0) or 0.0)),
                "VOLUME": clamp01(float(validation_row.get("first_order_score", 0.0) or 0.0)),
                "NEWS": clamp01(float(attention_proxy_report.get("attention_proxy_score", 0.0) or 0.0)),
                "LIQUIDITY": source_quality,
                "EVENT_PRIOR": clamp01(float(validation_row.get("repricing_headroom_score", 0.0) or 0.0)),
                "TECHNICAL": clamp01(float(runtime_state.get("signal_summary", {}).get("scm_rate", 0.0) or 0.0)),
            },
            expected_edges=[("PRICE", "VOLUME"), ("NEWS", "PRICE"), ("LIQUIDITY", "PRICE")],
            observed_edges=[
                ("PRICE", "VOLUME", "confirm" if float(validation_row.get("first_order_score", 0.0) or 0.0) >= 0.45 else "conflict"),
                ("NEWS", "PRICE", "confirm" if float(attention_proxy_report.get("attention_proxy_score", 0.0) or 0.0) <= 0.65 else "conflict"),
                ("LIQUIDITY", "PRICE", "confirm" if source_quality >= 0.45 else "conflict"),
            ],
        ),
        progression=ProgressionInput(
            observed_sequence=progression_sequence,
            required_confirmations=["PRICE", "VOLUME"],
        ),
        transition=TransitionInput(
            curvature=clamp01(float(validation_row.get("novelty_score", 0.0) or 0.0)),
            oscillation=clamp01(float(attention_proxy_report.get("narrative_heat_score", 0.0) or 0.0)),
            resolution_strength=clamp01(float(validation_row.get("first_order_score", 0.0) or 0.0)),
            trapdoor_risk=clamp01(1.0 - float(validation_row.get("blocker_clearance_score", 0.0) or 0.0)),
        ),
        trapdoor=TrapdoorInput(
            expected_path_deviation=clamp01(1.0 - float(validation_row.get("blocker_clearance_score", 0.0) or 0.0)),
            impact=volatility,
            speed=clamp01(float(attention_proxy_report.get("attention_proxy_score", 0.0) or 0.0)),
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
            regime_consistency=1.0 if str(runtime_state.get("temporal_integrity", {}).get("temporal_integrity_state", "CLEAN")).upper() == "CLEAN" else 0.25,
            time_since_validation_hours=0.0,
        ),
        primitive_competence=PrimitiveCompetenceInput(
            primitive_understanding=clamp01(float(validation_row.get("validation_score", 0.0) or 0.0)),
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
        validation_strength=clamp01(float(validation_row.get("validation_score", 0.0) or 0.0)),
        chaos_veto=chaos_veto,
        policy_veto=not allow_new_risk,
        system_name=str(validation_row.get("ticker") or "PIPELINE"),
        source="DEFAULT_STRUCTURAL_ADMISSION",
    )
    result = evaluate_structural_admission(input_payload)
    report = asdict(result)
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
