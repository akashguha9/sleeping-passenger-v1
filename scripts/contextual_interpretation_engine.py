from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

try:
    from scripts.runtime_common import (
        CONTEXTUAL_INTERPRETATION_REPORT_PATH,
        build_truth_context,
        classify_operating_mode,
        get_run_id,
        repo_relative,
        utc_timestamp,
        write_json_atomic,
    )
except ModuleNotFoundError:
    from runtime_common import (  # type: ignore[no-redef]
        CONTEXTUAL_INTERPRETATION_REPORT_PATH,
        build_truth_context,
        classify_operating_mode,
        get_run_id,
        repo_relative,
        utc_timestamp,
        write_json_atomic,
    )


EPSILON = 1e-9


class _StringEnum(str, Enum):
    def __str__(self) -> str:
        return str(self.value)


class MeaningType(_StringEnum):
    LUCK = "LUCK"
    SKILL = "SKILL"
    LEARNING_VELOCITY = "LEARNING_VELOCITY"
    HIDDEN_CAPABILITY = "HIDDEN_CAPABILITY"
    CONSTRAINT_NAVIGATION = "CONSTRAINT_NAVIGATION"
    RECEIVER_FAILURE = "RECEIVER_FAILURE"
    CONTEXT_MISMATCH = "CONTEXT_MISMATCH"
    RANDOM_NOISE = "RANDOM_NOISE"
    STRUCTURAL_EDGE = "STRUCTURAL_EDGE"
    UNKNOWN = "UNKNOWN"


class SignalChannel(_StringEnum):
    VERBAL = "VERBAL"
    NON_VERBAL = "NON_VERBAL"
    PRICE = "PRICE"
    VOLUME = "VOLUME"
    TIMING = "TIMING"
    BEHAVIORAL = "BEHAVIORAL"
    STRUCTURAL = "STRUCTURAL"
    CONTEXTUAL = "CONTEXTUAL"
    FORMAL_CODE = "FORMAL_CODE"
    LOCAL_CODE = "LOCAL_CODE"
    PERFORMANCE_CHANNEL = "PERFORMANCE_CHANNEL"
    UNKNOWN = "UNKNOWN"


class CommunicationCodeType(_StringEnum):
    FORMAL_LANGUAGE = "FORMAL_LANGUAGE"
    HOME_SIGN = "HOME_SIGN"
    PERSONAL_SIGNAL = "PERSONAL_SIGNAL"
    PERFORMANCE_SIGNAL = "PERFORMANCE_SIGNAL"
    MARKET_CODE = "MARKET_CODE"
    SOCIAL_CODE = "SOCIAL_CODE"
    UNKNOWN = "UNKNOWN"


class LatentCapabilityState(_StringEnum):
    UNOBSERVED = "UNOBSERVED"
    WEAK_SIGNAL = "WEAK_SIGNAL"
    EMERGING = "EMERGING"
    STRONG = "STRONG"
    EXTRAORDINARY = "EXTRAORDINARY"


class InterpretationAction(_StringEnum):
    REJECT_AS_NOISE = "REJECT_AS_NOISE"
    HOLD_FOR_REPEATABILITY = "HOLD_FOR_REPEATABILITY"
    PRIORITY_WATCHLIST = "PRIORITY_WATCHLIST"
    VALIDATE_DURABILITY = "VALIDATE_DURABILITY"
    PROMOTE_TO_ACTIONABLE = "PROMOTE_TO_ACTIONABLE"
    CHAOS_HOLD = "CHAOS_HOLD"


class BullInterpretationState(_StringEnum):
    MIURA = "MIURA"
    HURACAN = "HURACAN"
    MURCIELAGO = "MURCIELAGO"
    AVENTADOR = "AVENTADOR"
    GALLARDO = "GALLARDO"
    DIABLO = "DIABLO"
    ISLERO = "ISLERO"


class HiddenMechanism(_StringEnum):
    RULE_COMPRESSION = "RULE_COMPRESSION"
    TABLE_READING = "TABLE_READING"
    MEMORY = "MEMORY"
    TIMING_DISCIPLINE = "TIMING_DISCIPLINE"
    REGIME_CONTROL = "REGIME_CONTROL"
    SOCIAL_CALIBRATION = "SOCIAL_CALIBRATION"
    EXPECTATION_BREAKING = "EXPECTATION_BREAKING"
    CONSTRAINT_NAVIGATION = "CONSTRAINT_NAVIGATION"
    RECEIVER_DEPENDENCE = "RECEIVER_DEPENDENCE"
    RANDOM_VARIANCE = "RANDOM_VARIANCE"
    STRUCTURAL_EDGE = "STRUCTURAL_EDGE"
    CONTEXT_MISMATCH = "CONTEXT_MISMATCH"
    ALTERNATIVE_CHANNEL_INTELLIGENCE = "ALTERNATIVE_CHANNEL_INTELLIGENCE"
    LABEL_BIAS_RISK = "LABEL_BIAS_RISK"


_NORMALIZED_FIELD_NAMES = {
    "signal_clarity",
    "context_completeness",
    "observed_performance",
    "expected_baseline",
    "exposure_time",
    "task_difficulty",
    "environment_complexity",
    "constraint_burden",
    "receiver_channel_match",
    "receiver_shared_context",
    "receiver_decoder_skill",
    "label_salience",
    "observer_assumption_strength",
    "repeatability",
    "stress_survival",
    "context_transferability",
    "alternative_explanation_strength",
    "randomness_risk",
    "sample_size_risk",
    "chaos_level",
    "shock_level",
}


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    if abs(float(denominator)) <= EPSILON:
        return float(default)
    return float(numerator) / float(denominator)


def weighted_sum(parts: dict[str, tuple[float, float]]) -> float:
    total_weight = sum(max(0.0, float(weight)) for _, weight in parts.values())
    if total_weight <= EPSILON:
        return 0.0
    total = sum(clamp01(value) * max(0.0, float(weight)) for value, weight in parts.values())
    return clamp01(total / total_weight)


def _weighted_geometric_score(parts: dict[str, tuple[float, float]]) -> float:
    total_weight = sum(max(0.0, float(weight)) for _, weight in parts.values())
    if total_weight <= EPSILON:
        return 0.0
    weighted_log_sum = 0.0
    for value, weight in parts.values():
        safe_value = max(clamp01(value), EPSILON)
        weighted_log_sum += max(0.0, float(weight)) * math_log(safe_value)
    return clamp01(math_exp(weighted_log_sum / total_weight))


def math_log(value: float) -> float:
    import math

    return math.log(value)


def math_exp(value: float) -> float:
    import math

    return math.exp(value)


def _stable_signal_id(source: str, observed_event: str) -> str:
    digest = hashlib.sha256(f"{source}|{observed_event}".encode("utf-8")).hexdigest()
    return f"interp-{digest[:12]}"


def _coerce_channel(value: Any) -> SignalChannel:
    text = str(value or "").strip().upper()
    try:
        return SignalChannel(text)
    except ValueError:
        return SignalChannel.UNKNOWN


def _coerce_code_type(value: Any) -> CommunicationCodeType:
    text = str(value or "").strip().upper()
    try:
        return CommunicationCodeType(text)
    except ValueError:
        return CommunicationCodeType.UNKNOWN


@dataclass
class RawInterpretationInput:
    signal_id: str
    source: str
    observed_event: str
    channel: SignalChannel
    code_type: CommunicationCodeType = CommunicationCodeType.UNKNOWN
    signal_clarity: float = 0.5
    context_completeness: float = 0.5
    observed_performance: float = 0.5
    expected_baseline: float = 0.5
    exposure_time: float = 1.0
    task_difficulty: float = 0.5
    environment_complexity: float = 0.5
    constraint_burden: float = 0.0
    receiver_channel_match: float = 0.5
    receiver_shared_context: float = 0.5
    receiver_decoder_skill: float = 0.5
    label_salience: float = 0.0
    observer_assumption_strength: float = 0.0
    repeatability: float = 0.0
    stress_survival: float = 0.0
    context_transferability: float = 0.0
    alternative_explanation_strength: float = 0.5
    randomness_risk: float = 0.5
    sample_size_risk: float = 0.5
    chaos_level: float = 0.0
    shock_level: float = 0.0

    def __post_init__(self) -> None:
        self.source = str(self.source or "unknown_source").strip() or "unknown_source"
        self.observed_event = str(self.observed_event or "").strip()
        if not self.observed_event:
            raise ValueError("observed_event must not be empty")
        self.signal_id = str(self.signal_id or "").strip() or _stable_signal_id(
            self.source,
            self.observed_event,
        )
        self.channel = _coerce_channel(self.channel)
        self.code_type = _coerce_code_type(self.code_type)
        for field_name in _NORMALIZED_FIELD_NAMES:
            setattr(self, field_name, clamp01(getattr(self, field_name)))


@dataclass(frozen=True)
class EngineScore:
    name: str
    score: float
    state: str
    explanation: str
    components: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "score": clamp01(self.score),
            "state": self.state,
            "explanation": self.explanation,
            "components": {key: float(value) for key, value in self.components.items()},
        }


@dataclass(frozen=True)
class InterpretationResult:
    signal_id: str
    meaning_type: MeaningType
    meaning_confidence: float
    meaning_score: float
    learning_velocity_score: float
    latent_capability_score: float
    constraint_normalized_score: float
    receiver_sensitivity_score: float
    expression_value_score: float
    label_bias_risk: float
    alternative_explanation_risk: float
    durability_score: float
    hidden_information_edge_score: float
    timing_intelligence_score: float
    regime_control_score: float
    promotion_score: float
    latent_capability_state: LatentCapabilityState
    recommended_action: InterpretationAction
    bull_state: BullInterpretationState
    hidden_mechanism_scores: dict[str, float]
    diagnostics: list[EngineScore]
    audit_trail: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "meaning_type": self.meaning_type.value,
            "meaning_confidence": clamp01(self.meaning_confidence),
            "meaning_score": clamp01(self.meaning_score),
            "learning_velocity_score": clamp01(self.learning_velocity_score),
            "latent_capability_score": clamp01(self.latent_capability_score),
            "constraint_normalized_score": clamp01(self.constraint_normalized_score),
            "receiver_sensitivity_score": clamp01(self.receiver_sensitivity_score),
            "expression_value_score": clamp01(self.expression_value_score),
            "label_bias_risk": clamp01(self.label_bias_risk),
            "alternative_explanation_risk": clamp01(self.alternative_explanation_risk),
            "durability_score": clamp01(self.durability_score),
            "hidden_information_edge_score": clamp01(self.hidden_information_edge_score),
            "timing_intelligence_score": clamp01(self.timing_intelligence_score),
            "regime_control_score": clamp01(self.regime_control_score),
            "promotion_score": clamp01(self.promotion_score),
            "latent_capability_state": self.latent_capability_state.value,
            "recommended_action": self.recommended_action.value,
            "bull_state": self.bull_state.value,
            "hidden_mechanism_scores": {
                key: clamp01(value) for key, value in self.hidden_mechanism_scores.items()
            },
            "diagnostics": [row.to_dict() for row in self.diagnostics],
            "audit_trail": list(self.audit_trail),
        }


def _score_state(value: float, cutoffs: list[tuple[float, str]]) -> str:
    for threshold, state in cutoffs:
        if value < threshold:
            return state
    return cutoffs[-1][1]


def _learning_velocity_engine(raw: RawInterpretationInput, audit: list[str]) -> EngineScore:
    performance_gap = clamp01(raw.observed_performance - raw.expected_baseline + 0.5)
    low_exposure_bonus = clamp01(1.0 - raw.exposure_time)
    complexity_adjusted_learning = clamp01(
        raw.observed_performance
        * low_exposure_bonus
        * raw.task_difficulty
        * raw.environment_complexity
    )
    learning_velocity_score = clamp01(
        0.60 * complexity_adjusted_learning + 0.40 * performance_gap
    )
    if learning_velocity_score < 0.30:
        state = "LOW"
    elif learning_velocity_score < 0.55:
        state = "MODERATE"
    elif learning_velocity_score < 0.75:
        state = "HIGH"
    else:
        state = "EXCEPTIONAL"
    audit.append(
        "learning_velocity: performance was normalized against baseline, exposure window, task difficulty, and environment complexity."
    )
    return EngineScore(
        name="LearningVelocityEngine",
        score=learning_velocity_score,
        state=state,
        explanation="Experience Stock ≠ Adaptation Speed. Early high performance under difficulty can indicate fast learning rather than luck.",
        components={
            "performance_gap": performance_gap,
            "low_exposure_bonus": low_exposure_bonus,
            "complexity_adjusted_learning": complexity_adjusted_learning,
        },
    )


def _latent_capability_engine(
    raw: RawInterpretationInput,
    learning_velocity_score: float,
    audit: list[str],
) -> tuple[EngineScore, LatentCapabilityState]:
    latent_capability_score = clamp01(
        raw.observed_performance
        * raw.task_difficulty
        * learning_velocity_score
        * (1.0 + raw.constraint_burden)
        / (1.0 + raw.exposure_time)
    )
    if latent_capability_score < 0.25:
        state = LatentCapabilityState.UNOBSERVED
    elif latent_capability_score < 0.45:
        state = LatentCapabilityState.WEAK_SIGNAL
    elif latent_capability_score < 0.65:
        state = LatentCapabilityState.EMERGING
    elif latent_capability_score < 0.85:
        state = LatentCapabilityState.STRONG
    else:
        state = LatentCapabilityState.EXTRAORDINARY
    audit.append(
        f"latent_capability: score {latent_capability_score:.3f} mapped to {state.value} after adjusting for difficulty, exposure, and constraints."
    )
    return (
        EngineScore(
            name="LatentCapabilityEngine",
            score=latent_capability_score,
            state=state.value,
            explanation="Latent capability is performance under difficulty compressed through low exposure and constraint load.",
            components={
                "observed_performance": raw.observed_performance,
                "task_difficulty": raw.task_difficulty,
                "learning_velocity_score": learning_velocity_score,
                "constraint_burden": raw.constraint_burden,
                "exposure_time": raw.exposure_time,
            },
        ),
        state,
    )


def _constraint_normalization_engine(
    raw: RawInterpretationInput,
    audit: list[str],
) -> tuple[EngineScore, float]:
    expected_under_constraint = max(
        raw.expected_baseline * (1.0 - raw.constraint_burden),
        EPSILON,
    )
    constraint_ratio = safe_divide(raw.observed_performance, expected_under_constraint)
    constraint_normalized_score = clamp01(constraint_ratio / 2.0)
    constraint_adjusted_strength = clamp01(
        raw.observed_performance * (1.0 + raw.constraint_burden) * raw.task_difficulty
    )
    audit.append(
        "constraint_normalization: observed output was normalized against expected output under constraints."
    )
    return (
        EngineScore(
            name="ConstraintNormalizationEngine",
            score=constraint_normalized_score,
            state="ABOVE_EXPECTATION" if constraint_normalized_score >= 0.55 else "NEUTRAL_OR_LOW",
            explanation="Constraint-Normalized Performance = Observed Output / Expected Output Under Constraints.",
            components={
                "expected_under_constraint": clamp01(expected_under_constraint),
                "constraint_ratio": clamp01(constraint_ratio / 2.0),
                "constraint_adjusted_strength": constraint_adjusted_strength,
            },
        ),
        constraint_adjusted_strength,
    )


def _receiver_sensitivity_engine(raw: RawInterpretationInput, audit: list[str]) -> tuple[EngineScore, float]:
    receiver_sensitivity_score = clamp01(
        raw.receiver_channel_match
        * raw.receiver_shared_context
        * raw.receiver_decoder_skill
    )
    receiver_failure_risk = clamp01(1.0 - receiver_sensitivity_score)
    audit.append(
        "receiver_sensitivity: channel match, shared context, and decoder skill were combined. Low decoder fit does not erase the signal."
    )
    return (
        EngineScore(
            name="ReceiverSensitivityEngine",
            score=receiver_sensitivity_score,
            state="LOW_MATCH" if receiver_sensitivity_score < 0.30 else "MATCHING",
            explanation="Receiver Sensitivity = Channel Match × Shared Context × Decoder Skill.",
            components={
                "receiver_channel_match": raw.receiver_channel_match,
                "receiver_shared_context": raw.receiver_shared_context,
                "receiver_decoder_skill": raw.receiver_decoder_skill,
                "receiver_failure_risk": receiver_failure_risk,
            },
        ),
        receiver_failure_risk,
    )


def _channel_weight(channel: SignalChannel) -> float:
    weights = {
        SignalChannel.VERBAL: 1.00,
        SignalChannel.NON_VERBAL: 1.10,
        SignalChannel.PRICE: 1.00,
        SignalChannel.VOLUME: 1.00,
        SignalChannel.TIMING: 1.15,
        SignalChannel.BEHAVIORAL: 1.10,
        SignalChannel.STRUCTURAL: 1.20,
        SignalChannel.CONTEXTUAL: 1.10,
        SignalChannel.FORMAL_CODE: 1.00,
        SignalChannel.LOCAL_CODE: 1.15,
        SignalChannel.PERFORMANCE_CHANNEL: 1.20,
        SignalChannel.UNKNOWN: 0.80,
    }
    return weights.get(channel, 0.80)


def _alternative_expression_decoder(
    raw: RawInterpretationInput,
    receiver_sensitivity_score: float,
    audit: list[str],
) -> EngineScore:
    channel_weight = _channel_weight(raw.channel)
    expression_value_score = clamp01(
        raw.signal_clarity
        * receiver_sensitivity_score
        * raw.context_completeness
        * channel_weight
    )
    audit.append(
        f"alternative_expression_decoder: channel {raw.channel.value} used weight {channel_weight:.2f} to value non-standard expression paths."
    )
    return EngineScore(
        name="AlternativeExpressionDecoder",
        score=expression_value_score,
        state="EXPRESSIVE" if expression_value_score >= 0.50 else "LOW_VISIBILITY",
        explanation="Signal Visibility ≠ Signal Existence. Expression Value = Channel-Specific Signal Strength × Decoder Fit × Context Relevance.",
        components={
            "signal_clarity": raw.signal_clarity,
            "receiver_sensitivity_score": receiver_sensitivity_score,
            "context_completeness": raw.context_completeness,
            "channel_weight": channel_weight,
        },
    )


def _label_bias_guard(raw: RawInterpretationInput, audit: list[str]) -> EngineScore:
    label_bias_risk = clamp01(raw.label_salience * raw.observer_assumption_strength)
    if label_bias_risk >= 0.40:
        audit.append(
            "label_bias_guard: behavioural evidence must outrank category-based explanation"
        )
    else:
        audit.append("label_bias_guard: label influence remains below override risk.")
    return EngineScore(
        name="LabelBiasGuard",
        score=label_bias_risk,
        state="BIAS_RISK" if label_bias_risk >= 0.40 else "CONTROLLED",
        explanation="Performance Evidence > Label-Based Assumption.",
        components={
            "label_salience": raw.label_salience,
            "observer_assumption_strength": raw.observer_assumption_strength,
        },
    )


def _durability_validator(raw: RawInterpretationInput, audit: list[str]) -> EngineScore:
    durability_score = clamp01(
        0.45 * raw.repeatability
        + 0.35 * raw.stress_survival
        + 0.20 * raw.context_transferability
    )
    if durability_score < 0.25:
        state = "ONE_OFF"
    elif durability_score < 0.50:
        state = "EARLY_SIGNAL"
    elif durability_score < 0.75:
        state = "VALIDATING"
    else:
        state = "DURABLE"
    audit.append(f"durability: state {state} derived from repeatability, stress survival, and context transferability.")
    return EngineScore(
        name="RepeatabilityDurabilityValidator",
        score=durability_score,
        state=state,
        explanation="Validated Signal = Initial Strength × Repeatability × Stress Survival.",
        components={
            "repeatability": raw.repeatability,
            "stress_survival": raw.stress_survival,
            "context_transferability": raw.context_transferability,
        },
    )


def infer_hidden_mechanisms(
    raw: RawInterpretationInput,
    learning_velocity_score: float,
    latent_capability_score: float,
    constraint_normalized_score: float,
    receiver_sensitivity_score: float,
    expression_value_score: float,
    label_bias_risk: float,
    durability_score: float,
) -> dict[str, float]:
    timing_channel_bonus = {
        SignalChannel.TIMING: 1.0,
        SignalChannel.NON_VERBAL: 0.90,
        SignalChannel.BEHAVIORAL: 0.90,
        SignalChannel.PERFORMANCE_CHANNEL: 0.90,
        SignalChannel.STRUCTURAL: 0.80,
        SignalChannel.CONTEXTUAL: 0.80,
        SignalChannel.LOCAL_CODE: 0.80,
    }.get(raw.channel, 0.65)
    timing_discipline = clamp01(timing_channel_bonus * raw.signal_clarity * raw.observed_performance)
    regime_control = clamp01(
        raw.environment_complexity * timing_discipline * raw.observed_performance
    )
    return {
        HiddenMechanism.RULE_COMPRESSION.value: clamp01(
            learning_velocity_score * (1.0 - raw.exposure_time)
        ),
        HiddenMechanism.TABLE_READING.value: clamp01(
            raw.environment_complexity * raw.observed_performance * raw.context_completeness
        ),
        HiddenMechanism.MEMORY.value: clamp01(
            raw.environment_complexity * raw.task_difficulty * raw.observed_performance
        ),
        HiddenMechanism.TIMING_DISCIPLINE.value: timing_discipline,
        HiddenMechanism.REGIME_CONTROL.value: regime_control,
        HiddenMechanism.SOCIAL_CALIBRATION.value: clamp01(
            receiver_sensitivity_score * expression_value_score * raw.context_completeness
        ),
        HiddenMechanism.EXPECTATION_BREAKING.value: clamp01(
            raw.observed_performance - raw.expected_baseline + 0.5
        ),
        HiddenMechanism.CONSTRAINT_NAVIGATION.value: clamp01(
            raw.constraint_burden * raw.observed_performance * raw.task_difficulty
        ),
        HiddenMechanism.RECEIVER_DEPENDENCE.value: clamp01(
            raw.signal_clarity * (1.0 - receiver_sensitivity_score)
        ),
        HiddenMechanism.RANDOM_VARIANCE.value: clamp01(
            raw.randomness_risk * raw.sample_size_risk * (1.0 - raw.repeatability)
        ),
        HiddenMechanism.STRUCTURAL_EDGE.value: clamp01(
            raw.observed_performance
            * raw.environment_complexity
            * max(durability_score, 0.25)
        ),
        HiddenMechanism.CONTEXT_MISMATCH.value: clamp01(
            raw.signal_clarity * (1.0 - raw.context_completeness)
        ),
        HiddenMechanism.ALTERNATIVE_CHANNEL_INTELLIGENCE.value: clamp01(
            expression_value_score * (1.0 + raw.constraint_burden) / 2.0
        ),
        HiddenMechanism.LABEL_BIAS_RISK.value: label_bias_risk,
    }


def _alternative_explanation_checker(raw: RawInterpretationInput, audit: list[str]) -> tuple[EngineScore, list[str]]:
    alternative_explanation_risk = clamp01(
        0.40 * raw.randomness_risk
        + 0.30 * raw.sample_size_risk
        + 0.30 * raw.alternative_explanation_strength
    )
    flags: list[str] = []
    if raw.randomness_risk >= 0.65:
        flags.append("HIGH_RANDOMNESS_RISK")
    if raw.sample_size_risk >= 0.65:
        flags.append("SMALL_SAMPLE_RISK")
    if raw.alternative_explanation_strength >= 0.65:
        flags.append("COMPETING_EXPLANATION_RISK")
    if raw.observed_performance >= 0.70 and raw.repeatability < 0.40:
        flags.append("WATCHLIST_NOT_TRUTH")
    if flags:
        audit.append("alternative_explanation: " + ", ".join(flags))
    else:
        audit.append("alternative_explanation: competing explanations remain contained.")
    return (
        EngineScore(
            name="AlternativeExplanationChecker",
            score=alternative_explanation_risk,
            state="RISKY" if alternative_explanation_risk >= 0.70 else "MANAGEABLE",
            explanation="One-off anomalies must not be promoted as truth without repeatability.",
            components={
                "randomness_risk": raw.randomness_risk,
                "sample_size_risk": raw.sample_size_risk,
                "alternative_explanation_strength": raw.alternative_explanation_strength,
            },
        ),
        flags,
    )


def _hidden_information_table_model(raw: RawInterpretationInput, audit: list[str]) -> EngineScore:
    if raw.channel == SignalChannel.TIMING:
        timing_proxy = 1.0
    elif raw.channel in {
        SignalChannel.BEHAVIORAL,
        SignalChannel.NON_VERBAL,
        SignalChannel.PERFORMANCE_CHANNEL,
    }:
        timing_proxy = 0.75
    else:
        timing_proxy = 0.50
    hidden_information_edge_score = clamp01(
        0.30 * raw.environment_complexity
        + 0.25 * raw.signal_clarity
        + 0.20 * timing_proxy
        + 0.15 * raw.context_completeness
        + 0.10 * raw.observed_performance
        - 0.20 * raw.randomness_risk
    )
    audit.append(
        "hidden_information_table_model: hidden structure scored through complexity, clarity, timing, context, and randomness."
    )
    return EngineScore(
        name="HiddenInformationTableModel",
        score=hidden_information_edge_score,
        state="EDGE" if hidden_information_edge_score >= 0.55 else "LIMITED",
        explanation="Experts observe preconditions; amateurs observe outcomes.",
        components={
            "environment_complexity": raw.environment_complexity,
            "signal_clarity": raw.signal_clarity,
            "timing_proxy": timing_proxy,
            "context_completeness": raw.context_completeness,
            "observed_performance": raw.observed_performance,
            "randomness_risk": raw.randomness_risk,
        },
    )


def _timing_intelligence_module(raw: RawInterpretationInput, audit: list[str]) -> EngineScore:
    channel_timing_weight = {
        SignalChannel.TIMING: 1.25,
        SignalChannel.NON_VERBAL: 1.15,
        SignalChannel.BEHAVIORAL: 1.10,
        SignalChannel.PERFORMANCE_CHANNEL: 1.20,
        SignalChannel.STRUCTURAL: 1.10,
    }.get(raw.channel, 1.00)
    timing_intelligence_score = clamp01(
        channel_timing_weight
        * raw.signal_clarity
        * raw.observed_performance
        * raw.context_completeness
    )
    audit.append(
        "timing_intelligence: sequencing quality was estimated from channel timing weight, clarity, performance, and context."
    )
    return EngineScore(
        name="TimingIntelligenceModule",
        score=timing_intelligence_score,
        state="TIMING_EDGE" if timing_intelligence_score >= 0.55 else "TIMING_WEAK",
        explanation="Calm execution is pre-processed awareness.",
        components={
            "channel_timing_weight": channel_timing_weight,
            "signal_clarity": raw.signal_clarity,
            "observed_performance": raw.observed_performance,
            "context_completeness": raw.context_completeness,
        },
    )


def _regime_control_module(
    raw: RawInterpretationInput,
    timing_intelligence_score: float,
    audit: list[str],
) -> EngineScore:
    regime_control_score = clamp01(
        0.40 * raw.environment_complexity
        + 0.30 * timing_intelligence_score
        + 0.30 * raw.observed_performance
    )
    if raw.channel == SignalChannel.UNKNOWN:
        regime_control_score = clamp01(regime_control_score * 0.92)
    audit.append("regime_control: environment complexity, timing intelligence, and observed performance were fused.")
    return EngineScore(
        name="RegimeControlModule",
        score=regime_control_score,
        state="CONTROLLED" if regime_control_score >= 0.55 else "WEAK_CONTROL",
        explanation="Surface Simplicity ≠ Structural Simplicity.",
        components={
            "environment_complexity": raw.environment_complexity,
            "timing_intelligence_score": timing_intelligence_score,
            "observed_performance": raw.observed_performance,
            "unknown_channel_penalty": 0.08 if raw.channel == SignalChannel.UNKNOWN else 0.0,
        },
    )


def _meaning_attribution_layer(
    raw: RawInterpretationInput,
    learning_velocity_score: float,
    latent_capability_score: float,
    constraint_normalized_score: float,
    receiver_sensitivity_score: float,
    label_bias_risk: float,
    durability_score: float,
    hidden_information_edge_score: float,
    alternative_explanation_risk: float,
    audit: list[str],
) -> tuple[EngineScore, MeaningType, float]:
    luck_score = clamp01(raw.randomness_risk * raw.sample_size_risk * (1.0 - raw.repeatability))
    skill_score = clamp01(
        raw.observed_performance
        * raw.task_difficulty
        * max(raw.repeatability, durability_score)
    )
    learning_velocity_candidate = clamp01(
        learning_velocity_score * (1.0 - raw.exposure_time) * raw.observed_performance
    )
    hidden_capability_candidate = clamp01(
        latent_capability_score * max(constraint_normalized_score, learning_velocity_score)
    )
    constraint_navigation_candidate = clamp01(
        raw.constraint_burden * raw.observed_performance * raw.task_difficulty
    )
    receiver_failure_candidate = clamp01(
        raw.signal_clarity * (1.0 - receiver_sensitivity_score)
    )
    context_mismatch_candidate = clamp01(
        raw.signal_clarity * (1.0 - raw.context_completeness)
    )
    random_noise_candidate = clamp01(
        raw.alternative_explanation_strength * raw.randomness_risk * (1.0 - raw.signal_clarity)
    )
    structural_edge_candidate = clamp01(
        raw.observed_performance
        * raw.environment_complexity
        * max(durability_score, hidden_information_edge_score)
    )
    candidates = {
        MeaningType.LUCK: luck_score,
        MeaningType.SKILL: skill_score,
        MeaningType.LEARNING_VELOCITY: learning_velocity_candidate,
        MeaningType.HIDDEN_CAPABILITY: hidden_capability_candidate,
        MeaningType.CONSTRAINT_NAVIGATION: constraint_navigation_candidate,
        MeaningType.RECEIVER_FAILURE: receiver_failure_candidate,
        MeaningType.CONTEXT_MISMATCH: context_mismatch_candidate,
        MeaningType.RANDOM_NOISE: random_noise_candidate,
        MeaningType.STRUCTURAL_EDGE: structural_edge_candidate,
    }
    if receiver_failure_candidate >= 0.55 and receiver_sensitivity_score < 0.30 and raw.signal_clarity >= 0.55:
        candidates[MeaningType.RANDOM_NOISE] = min(
            candidates[MeaningType.RANDOM_NOISE],
            clamp01(raw.signal_clarity * 0.25),
        )
    if hidden_capability_candidate >= 0.55 and label_bias_risk >= 0.40:
        candidates[MeaningType.HIDDEN_CAPABILITY] = clamp01(
            max(hidden_capability_candidate, raw.observed_performance * 0.75)
        )
    if structural_edge_candidate >= 0.55 and durability_score < 0.35:
        candidates[MeaningType.STRUCTURAL_EDGE] = clamp01(structural_edge_candidate * 0.85)
    meaning_type, best_explanation_fit = max(candidates.items(), key=lambda item: item[1], default=(MeaningType.UNKNOWN, 0.0))
    meaning_confidence = clamp01(
        best_explanation_fit
        - 0.35 * alternative_explanation_risk
        - 0.20 * label_bias_risk
        + 0.15 * raw.context_completeness
    )
    meaning_score = clamp01(
        raw.signal_clarity
        * raw.context_completeness
        * best_explanation_fit
        * receiver_sensitivity_score
        * max(constraint_normalized_score, 0.25)
        * max(durability_score, 0.25)
        - 0.20 * alternative_explanation_risk
        - 0.20 * label_bias_risk
        - 0.40 * raw.chaos_level
    )
    audit.append(
        f"meaning_attribution: strongest explanation was {meaning_type.value} with fit {best_explanation_fit:.3f}."
    )
    return (
        EngineScore(
            name="MeaningAttributionLayer",
            score=meaning_score,
            state=meaning_type.value,
            explanation="Raw Signal ≠ Meaning. Meaning = Signal × Context × Hidden Structure × Receiver Sensitivity × Constraint Adjustment.",
            components={meaning.value.lower(): score for meaning, score in candidates.items()},
        ),
        meaning_type,
        meaning_confidence,
    )


def _promotion_gate(
    raw: RawInterpretationInput,
    meaning_confidence: float,
    constraint_normalized_score: float,
    receiver_sensitivity_score: float,
    alternative_explanation_risk: float,
    durability_score: float,
    learning_velocity_score: float,
    audit: list[str],
) -> tuple[EngineScore, InterpretationAction]:
    repeatability_floor = 0.20 if learning_velocity_score >= 0.75 else raw.repeatability
    promotion_score = clamp01(
        meaning_confidence
        * raw.context_completeness
        * constraint_normalized_score
        * max(raw.repeatability, repeatability_floor)
        * receiver_sensitivity_score
        - 0.25 * alternative_explanation_risk
        - 0.50 * raw.chaos_level
    )
    if raw.chaos_level >= 0.70:
        action = InterpretationAction.CHAOS_HOLD
    elif raw.shock_level >= 0.75:
        action = InterpretationAction.VALIDATE_DURABILITY
    elif (
        promotion_score >= 0.75
        and durability_score >= 0.60
        and meaning_confidence >= 0.70
    ):
        action = InterpretationAction.PROMOTE_TO_ACTIONABLE
    elif (
        learning_velocity_score >= 0.75
        and meaning_confidence >= 0.55
        and raw.chaos_level < 0.40
    ):
        action = InterpretationAction.PRIORITY_WATCHLIST
    elif meaning_confidence >= 0.55:
        action = InterpretationAction.VALIDATE_DURABILITY
    elif alternative_explanation_risk >= 0.70 or raw.sample_size_risk >= 0.65:
        action = InterpretationAction.HOLD_FOR_REPEATABILITY
    elif raw.signal_clarity < 0.30 and meaning_confidence < 0.35:
        action = InterpretationAction.REJECT_AS_NOISE
    else:
        action = InterpretationAction.HOLD_FOR_REPEATABILITY
    audit.append(
        f"promotion_gate: action {action.value} selected from promotion score {promotion_score:.3f} with chaos {raw.chaos_level:.3f}."
    )
    return (
        EngineScore(
            name="PromotionGate",
            score=promotion_score,
            state=action.value,
            explanation="Detection finds events. Interpretation assigns meaning. Promotion requires durability.",
            components={
                "meaning_confidence": meaning_confidence,
                "context_completeness": raw.context_completeness,
                "constraint_normalized_score": constraint_normalized_score,
                "repeatability_or_floor": max(raw.repeatability, repeatability_floor),
                "receiver_sensitivity_score": receiver_sensitivity_score,
                "alternative_explanation_risk": alternative_explanation_risk,
                "chaos_level": raw.chaos_level,
            },
        ),
        action,
    )


def _bull_archetype_mapper(
    raw: RawInterpretationInput,
    promotion_score: float,
    durability_score: float,
    meaning_confidence: float,
    learning_velocity_score: float,
    audit: list[str],
) -> BullInterpretationState:
    if raw.chaos_level >= 0.70:
        bull_state = BullInterpretationState.DIABLO
    elif raw.shock_level >= 0.75:
        bull_state = BullInterpretationState.ISLERO
    elif (
        promotion_score >= 0.75
        and durability_score >= 0.60
        and meaning_confidence >= 0.70
    ):
        bull_state = BullInterpretationState.AVENTADOR
    elif (
        learning_velocity_score >= 0.75
        and meaning_confidence >= 0.55
        and raw.chaos_level < 0.40
    ):
        bull_state = BullInterpretationState.HURACAN
    elif meaning_confidence >= 0.55 or durability_score >= 0.35:
        bull_state = BullInterpretationState.MURCIELAGO
    else:
        bull_state = BullInterpretationState.MIURA
    audit.append(f"bull_archetype: mapped to {bull_state.value}.")
    return bull_state


def interpret_signal(raw: RawInterpretationInput) -> InterpretationResult:
    """
    Raw Signal ≠ Meaning.
    Meaning = Signal × Context × Hidden Structure × Receiver Sensitivity × Constraint Adjustment.

    Detection finds events. Interpretation assigns meaning. Promotion requires durability.
    """

    audit_trail = [f"input_received: signal {raw.signal_id} from {raw.source} on channel {raw.channel.value}."]
    diagnostics: list[EngineScore] = []

    learning_velocity = _learning_velocity_engine(raw, audit_trail)
    diagnostics.append(learning_velocity)

    latent_capability, latent_state = _latent_capability_engine(
        raw,
        learning_velocity.score,
        audit_trail,
    )
    diagnostics.append(latent_capability)

    constraint_normalization, constraint_adjusted_strength = _constraint_normalization_engine(
        raw,
        audit_trail,
    )
    diagnostics.append(constraint_normalization)

    receiver_sensitivity, receiver_failure_risk = _receiver_sensitivity_engine(
        raw,
        audit_trail,
    )
    diagnostics.append(receiver_sensitivity)

    expression_decoder = _alternative_expression_decoder(
        raw,
        receiver_sensitivity.score,
        audit_trail,
    )
    diagnostics.append(expression_decoder)

    label_bias_guard = _label_bias_guard(raw, audit_trail)
    diagnostics.append(label_bias_guard)

    durability = _durability_validator(raw, audit_trail)
    diagnostics.append(durability)

    hidden_mechanism_scores = infer_hidden_mechanisms(
        raw,
        learning_velocity.score,
        latent_capability.score,
        constraint_normalization.score,
        receiver_sensitivity.score,
        expression_decoder.score,
        label_bias_guard.score,
        durability.score,
    )
    audit_trail.append("behaviour_to_structure_inference: hidden mechanisms inferred from performance, context, timing, and decoder fit.")

    alternative_explanation, alternative_flags = _alternative_explanation_checker(
        raw,
        audit_trail,
    )
    diagnostics.append(alternative_explanation)

    hidden_information = _hidden_information_table_model(raw, audit_trail)
    diagnostics.append(hidden_information)

    timing_intelligence = _timing_intelligence_module(raw, audit_trail)
    diagnostics.append(timing_intelligence)

    regime_control = _regime_control_module(raw, timing_intelligence.score, audit_trail)
    diagnostics.append(regime_control)

    meaning_attribution, meaning_type, meaning_confidence = _meaning_attribution_layer(
        raw,
        learning_velocity.score,
        latent_capability.score,
        constraint_normalization.score,
        receiver_sensitivity.score,
        label_bias_guard.score,
        durability.score,
        hidden_information.score,
        alternative_explanation.score,
        audit_trail,
    )
    diagnostics.append(meaning_attribution)

    promotion_gate, recommended_action = _promotion_gate(
        raw,
        meaning_confidence,
        constraint_normalization.score,
        receiver_sensitivity.score,
        alternative_explanation.score,
        durability.score,
        learning_velocity.score,
        audit_trail,
    )
    diagnostics.append(promotion_gate)

    bull_state = _bull_archetype_mapper(
        raw,
        promotion_gate.score,
        durability.score,
        meaning_confidence,
        learning_velocity.score,
        audit_trail,
    )

    if alternative_flags:
        audit_trail.append("guardrails: " + ", ".join(alternative_flags))
    if receiver_failure_risk >= 0.70:
        audit_trail.append("receiver_sensitivity: receiver failure risk is elevated; absence of decoding does not imply absence of signal.")

    return InterpretationResult(
        signal_id=raw.signal_id,
        meaning_type=meaning_type,
        meaning_confidence=meaning_confidence,
        meaning_score=meaning_attribution.score,
        learning_velocity_score=learning_velocity.score,
        latent_capability_score=latent_capability.score,
        constraint_normalized_score=constraint_normalization.score,
        receiver_sensitivity_score=receiver_sensitivity.score,
        expression_value_score=expression_decoder.score,
        label_bias_risk=label_bias_guard.score,
        alternative_explanation_risk=alternative_explanation.score,
        durability_score=durability.score,
        hidden_information_edge_score=hidden_information.score,
        timing_intelligence_score=timing_intelligence.score,
        regime_control_score=regime_control.score,
        promotion_score=promotion_gate.score,
        latent_capability_state=latent_state,
        recommended_action=recommended_action,
        bull_state=bull_state,
        hidden_mechanism_scores=hidden_mechanism_scores,
        diagnostics=diagnostics,
        audit_trail=audit_trail,
    )


def _guess_channel(signal: dict[str, Any]) -> SignalChannel:
    raw_channel = signal.get("channel") or signal.get("signal_channel")
    if raw_channel:
        return _coerce_channel(raw_channel)
    if signal.get("price_move_intensity") is not None:
        return SignalChannel.PRICE
    if signal.get("momentum") is not None:
        return SignalChannel.TIMING
    if signal.get("liquidity_fragility") is not None:
        return SignalChannel.STRUCTURAL
    return SignalChannel.PERFORMANCE_CHANNEL


def raw_from_signal_dict(signal: dict[str, Any]) -> RawInterpretationInput:
    observed_event = str(
        signal.get("observed_event")
        or signal.get("question")
        or signal.get("ticker")
        or signal.get("signal_name")
        or signal.get("summary")
        or "runtime_signal"
    ).strip()
    return RawInterpretationInput(
        signal_id=str(signal.get("signal_id") or signal.get("ticker") or "").strip(),
        source=str(signal.get("source") or signal.get("source_name") or "runtime_signal_source"),
        observed_event=observed_event,
        channel=_guess_channel(signal),
        code_type=_coerce_code_type(signal.get("code_type")),
        signal_clarity=signal.get("signal_clarity", signal.get("minimum_validation", signal.get("validation_score", 0.5))),
        context_completeness=signal.get("context_completeness", signal.get("context_score", signal.get("truth_probability", 0.5))),
        observed_performance=signal.get("observed_performance", signal.get("detection_score", signal.get("truth_probability", 0.5))),
        expected_baseline=signal.get("expected_baseline", signal.get("baseline_score", 0.5)),
        exposure_time=signal.get("exposure_time", signal.get("novelty_score", 0.5)),
        task_difficulty=signal.get("task_difficulty", signal.get("difficulty_score", 0.5)),
        environment_complexity=signal.get("environment_complexity", signal.get("environment_complexity_score", signal.get("context_complexity", 0.5))),
        constraint_burden=signal.get("constraint_burden", signal.get("constraint_score", signal.get("friction_score", 0.0))),
        receiver_channel_match=signal.get("receiver_channel_match", signal.get("market_fit_score", 0.5)),
        receiver_shared_context=signal.get("receiver_shared_context", signal.get("shared_context_score", 0.5)),
        receiver_decoder_skill=signal.get("receiver_decoder_skill", signal.get("decoder_skill_score", signal.get("minimum_validation", 0.5))),
        label_salience=signal.get("label_salience", signal.get("narrative_acceleration", 0.0)),
        observer_assumption_strength=signal.get("observer_assumption_strength", signal.get("crowd_saturation", 0.0)),
        repeatability=signal.get("repeatability", signal.get("durability_score", 0.0)),
        stress_survival=signal.get("stress_survival", signal.get("stress_survival_score", signal.get("durability_score", 0.0))),
        context_transferability=signal.get("context_transferability", signal.get("transferability_score", 0.0)),
        alternative_explanation_strength=signal.get("alternative_explanation_strength", signal.get("ambiguity_score", 0.5)),
        randomness_risk=signal.get("randomness_risk", signal.get("noise_score", 0.5)),
        sample_size_risk=signal.get("sample_size_risk", signal.get("sample_risk_score", 0.5)),
        chaos_level=signal.get("chaos_level", signal.get("chaos_score", 0.0)),
        shock_level=signal.get("shock_level", signal.get("pattern_shock", signal.get("shock_override", 0.0))),
    )


def summarize_result(result: InterpretationResult) -> str:
    main_guardrail = "none"
    if result.recommended_action == InterpretationAction.CHAOS_HOLD:
        main_guardrail = "chaos_override"
    elif result.alternative_explanation_risk >= 0.70:
        main_guardrail = "alternative_explanation_risk"
    elif result.durability_score < 0.50:
        main_guardrail = "durability_not_proven"
    elif result.receiver_sensitivity_score < 0.30:
        main_guardrail = "receiver_decoder_mismatch"
    return (
        f"{result.signal_id}: meaning={result.meaning_type.value}, confidence={result.meaning_confidence:.3f}, "
        f"score={result.meaning_score:.3f}, action={result.recommended_action.value}, "
        f"bull={result.bull_state.value}, guardrail={main_guardrail}"
    )


def build_contextual_interpretation_report(
    signals: list[dict[str, Any]] | None = None,
    *,
    runtime_state: dict[str, Any] | None = None,
    write_runtime: bool = True,
    artifact_path: Path | None = None,
) -> dict[str, Any]:
    state = runtime_state if isinstance(runtime_state, dict) else {}
    rows = signals if isinstance(signals, list) else []
    results = [interpret_signal(raw_from_signal_dict(signal)).to_dict() for signal in rows]
    best = max(results, key=lambda item: item.get("meaning_confidence", 0.0), default=None)
    truth_context = build_truth_context(state)
    report = {
        "run_id": get_run_id(),
        "generated_at": utc_timestamp(),
        "module": "contextual_interpretation_engine",
        "schema_version": "1.0",
        "enabled": bool(rows),
        "signal_count": len(rows),
        "meaning_results": results,
        "contextual_meaning_type": best.get("meaning_type") if best else MeaningType.UNKNOWN.value,
        "contextual_meaning_confidence": best.get("meaning_confidence") if best else 0.0,
        "contextual_latent_capability_state": best.get("latent_capability_state") if best else LatentCapabilityState.UNOBSERVED.value,
        "contextual_recommended_action": best.get("recommended_action") if best else InterpretationAction.HOLD_FOR_REPEATABILITY.value,
        "contextual_bull_state": best.get("bull_state") if best else BullInterpretationState.MIURA.value,
        "contextual_main_guardrail": _main_guardrail_from_result(best) if best else "no_signals",
        "example_result": best,
        "operating_mode": classify_operating_mode(state),
        "truth_origin": truth_context["truth_origin"],
        "data_quality": "synthetic_or_runtime_fallback",
        "live_ready": False,
        "report_path": repo_relative(artifact_path or CONTEXTUAL_INTERPRETATION_REPORT_PATH),
    }
    if write_runtime:
        write_json_atomic(
            artifact_path or CONTEXTUAL_INTERPRETATION_REPORT_PATH,
            report,
            stamp=False,
        )
    return report


def _main_guardrail_from_result(result: dict[str, Any] | None) -> str:
    if not isinstance(result, dict):
        return "no_result"
    if result.get("recommended_action") == InterpretationAction.CHAOS_HOLD.value:
        return "chaos_override"
    if float(result.get("alternative_explanation_risk", 0.0) or 0.0) >= 0.70:
        return "alternative_explanation_risk"
    if float(result.get("durability_score", 0.0) or 0.0) < 0.50:
        return "durability_not_proven"
    if float(result.get("receiver_sensitivity_score", 0.0) or 0.0) < 0.30:
        return "receiver_decoder_mismatch"
    if float(result.get("label_bias_risk", 0.0) or 0.0) >= 0.40:
        return "label_bias_risk"
    return "meaning_validating"


__all__ = [
    "EPSILON",
    "BullInterpretationState",
    "CommunicationCodeType",
    "EngineScore",
    "HiddenMechanism",
    "InterpretationAction",
    "InterpretationResult",
    "LatentCapabilityState",
    "MeaningType",
    "RawInterpretationInput",
    "SignalChannel",
    "build_contextual_interpretation_report",
    "clamp01",
    "infer_hidden_mechanisms",
    "interpret_signal",
    "raw_from_signal_dict",
    "safe_divide",
    "summarize_result",
    "weighted_sum",
]
