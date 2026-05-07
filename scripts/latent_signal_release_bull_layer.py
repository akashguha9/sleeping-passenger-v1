from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

try:
    from scripts.runtime_common import (
        REPO_ROOT,
        AVENTADOR_PROMOTION_REPORT_PATH,
        BULL_STATE_REPORT_PATH,
        BULL_TRANSITION_LOG_PATH,
        COLLAPSE_ANALYSIS_REPORT_PATH,
        FALSE_CONVICTION_REPORT_PATH,
        GALLARDO_EXECUTION_REPORT_PATH,
        LATENT_SIGNAL_RELEASE_REPORT_PATH,
        MURCIELAGO_DURABILITY_REPORT_PATH,
        OPPORTUNITY_HALF_LIFE_REPORT_PATH,
        SIGNAL_TEXTURE_REPORT_PATH,
        SIGNAL_ZETA_REPORT_PATH,
        VALIDATION_BUFFER_REPORT_PATH,
        build_runtime_state_from_scm_report_payload,
        build_truth_context,
        classify_operating_mode,
        get_run_id,
        get_source_mode,
        load_json_file,
        repo_relative,
        utc_timestamp,
        write_json_atomic,
    )
    from scripts.signal_conversion_monitor import build_signal_conversion_report
except ModuleNotFoundError:
    from runtime_common import (  # type: ignore[no-redef]
        REPO_ROOT,
        AVENTADOR_PROMOTION_REPORT_PATH,
        BULL_STATE_REPORT_PATH,
        BULL_TRANSITION_LOG_PATH,
        COLLAPSE_ANALYSIS_REPORT_PATH,
        FALSE_CONVICTION_REPORT_PATH,
        GALLARDO_EXECUTION_REPORT_PATH,
        LATENT_SIGNAL_RELEASE_REPORT_PATH,
        MURCIELAGO_DURABILITY_REPORT_PATH,
        OPPORTUNITY_HALF_LIFE_REPORT_PATH,
        SIGNAL_TEXTURE_REPORT_PATH,
        SIGNAL_ZETA_REPORT_PATH,
        VALIDATION_BUFFER_REPORT_PATH,
        build_runtime_state_from_scm_report_payload,
        build_truth_context,
        classify_operating_mode,
        get_run_id,
        get_source_mode,
        load_json_file,
        repo_relative,
        utc_timestamp,
        write_json_atomic,
    )
    from signal_conversion_monitor import build_signal_conversion_report  # type: ignore[no-redef]


CONFIG_PATH = REPO_ROOT / "config" / "latent_signal_release_bull_config.json"
SCHEMA_VERSION = "1.0"
EPSILON = 1e-6


class BullSignalState(str, Enum):
    MIURA = "MIURA"
    COLLAPSE_ANALYSIS = "COLLAPSE_ANALYSIS"
    MURCIELAGO = "MURCIELAGO"
    AVENTADOR = "AVENTADOR"
    GALLARDO = "GALLARDO"
    ISLERO = "ISLERO"
    DIABLO = "DIABLO"
    HURACAN = "HURACAN"


class SystemMode(str, Enum):
    CONTINUOUS = "CONTINUOUS"
    TRIGGERED = "TRIGGERED"


DEFAULT_THRESHOLDS = {
    "theta_release": 0.65,
    "theta_trigger": 0.60,
    "theta_texture": 0.55,
    "theta_zeta_min": 0.60,
    "theta_false_conviction_max": 0.35,
    "theta_coherence": 0.60,
    "theta_durability": 0.70,
    "theta_stress": 0.65,
    "theta_chaos": 0.75,
    "theta_momentum": 0.80,
    "theta_min_validation": 0.50,
    "theta_separation_min": 0.50,
    "theta_validation": 0.60,
}


@dataclass(slots=True)
class SignalReleaseAtom:
    signal: float = 0.0
    weight: float = 0.0
    persistence: float = 0.0
    source_quality: float = 0.0


@dataclass(slots=True)
class ReleaseTriggerInput:
    signals: list[SignalReleaseAtom] = field(default_factory=list)
    event_proximity: float = 0.0
    narrative_acceleration: float = 0.0
    price_move_intensity: float = 0.0
    prediction_market_delta: float = 0.0
    source_burst: float = 0.0
    confidence: float = 0.0
    persistence: float = 0.0
    noise: float = 1.0
    initial_edge: float = 0.0
    decay_rate: float = 0.0
    elapsed_time: float = 0.0
    validation_time: float = 0.0
    minimum_validation: float = 0.0
    peak_alignment: float = 0.0
    time_decay: float = 0.0
    execution_delay_penalty: float = 0.0
    source_diversity: float = 0.0
    counter_signal_resistance: float = 0.0
    metadata_clarity: float = 0.0
    echo_chamber_penalty: float = 0.0
    source_independence: float = 0.0
    theme_distance: float = 0.0
    validation_depth: float = 0.0
    circular_citation_penalty: float = 0.0
    same_narrative_origin_penalty: float = 0.0
    cluster_density: float = 0.0
    volatility_delta: float = 0.0
    news_intensity: float = 0.0
    liquidity_stress: float = 0.0
    event_surprise: float = 0.0
    spread_expansion: float = 0.0
    theme_similarity: float = 0.0
    counter_signal_survival: float = 0.0
    stress_survival: float = 0.0
    plan_clarity: float = 0.0
    risk_control: float = 0.0
    invalidation_clarity: float = 0.0
    exit_discipline: float = 0.0
    review_discipline: float = 0.0
    execution_survivability: float = 0.0
    policy_permission: float = 0.0
    policy_veto: bool = False
    chaos_veto: bool = False
    irreversible_event_shock: bool = False
    momentum: float = 0.0
    risk_cap_active: bool = False
    execution_plan_complete: bool = False
    entry_defined: bool = False
    sizing_defined: bool = False
    exit_defined: bool = False
    review_defined: bool = False
    previous_state: str = BullSignalState.MIURA.value
    system_name: str = "PIPELINE"
    source: str = "synthetic_or_runtime_fallback"
    live_ready: bool = False


@dataclass(slots=True)
class LayerOutput:
    state: str
    recommendation: str
    rationale: list[str]
    scores: dict[str, Any]
    vetoes: list[str]


def clamp01(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def load_thresholds() -> dict[str, float]:
    payload = load_json_file(CONFIG_PATH, default={})
    if not isinstance(payload, dict):
        return dict(DEFAULT_THRESHOLDS)
    thresholds = dict(DEFAULT_THRESHOLDS)
    for key, default in DEFAULT_THRESHOLDS.items():
        thresholds[key] = clamp01(payload.get(key, default))
    return thresholds


def compute_release_pressure(signals: list[SignalReleaseAtom]) -> float:
    total = 0.0
    for atom in signals:
        total += (
            clamp01(atom.signal)
            * clamp01(atom.weight)
            * clamp01(atom.persistence)
            * clamp01(atom.source_quality)
        )
    return clamp01(total)


def compute_trigger_strength(payload: ReleaseTriggerInput) -> float:
    return clamp01(
        0.30 * clamp01(payload.event_proximity)
        + 0.25 * clamp01(payload.narrative_acceleration)
        + 0.20 * clamp01(payload.price_move_intensity)
        + 0.15 * clamp01(payload.prediction_market_delta)
        + 0.10 * clamp01(payload.source_burst)
    )


def compute_signal_texture(confidence: float, persistence: float, noise: float) -> float:
    return clamp01(clamp01(confidence) * clamp01(persistence) / max(clamp01(noise), EPSILON))


def compute_opportunity_half_life(initial_edge: float, decay_rate: float, elapsed_time: float) -> float:
    return clamp01(clamp01(initial_edge) * math.exp(-max(float(decay_rate), 0.0) * max(float(elapsed_time), 0.0)))


def compute_transient_value(peak_alignment: float, time_decay: float, execution_delay_penalty: float) -> float:
    return clamp01(clamp01(peak_alignment) - clamp01(time_decay) - clamp01(execution_delay_penalty))


def compute_validation_buffer(
    source_diversity: float,
    persistence: float,
    counter_signal_resistance: float,
    metadata_clarity: float,
    echo_chamber_penalty: float,
) -> float:
    return clamp01(
        (
            clamp01(source_diversity)
            + clamp01(persistence)
            + clamp01(counter_signal_resistance)
            + clamp01(metadata_clarity)
            - clamp01(echo_chamber_penalty)
        )
        / 4.0
    )


def compute_separation_strength(metadata_clarity: float, source_independence: float, theme_distance: float) -> float:
    return clamp01(clamp01(metadata_clarity) * clamp01(source_independence) * clamp01(theme_distance) * 2.0)


def compute_false_conviction_risk(cluster_density: float, source_independence: float) -> float:
    return clamp01(clamp01(cluster_density) / max(clamp01(source_independence), EPSILON))


def compute_signal_zeta(
    confidence: float,
    validation_depth: float,
    source_diversity: float,
    persistence: float,
    echo_chamber_penalty: float,
    circular_citation_penalty: float,
    same_narrative_origin_penalty: float,
) -> float:
    return clamp01(
        0.25 * clamp01(confidence)
        + 0.30 * clamp01(validation_depth)
        + 0.25 * clamp01(source_diversity)
        + 0.20 * clamp01(persistence)
        - 0.20 * clamp01(echo_chamber_penalty)
        - 0.15 * clamp01(circular_citation_penalty)
        - 0.15 * clamp01(same_narrative_origin_penalty)
    )


def compute_aggregation_risk(signal_zeta: float) -> float:
    return clamp01(1.0 - clamp01(signal_zeta))


def compute_shock_score(
    volatility_delta: float,
    news_intensity: float,
    liquidity_stress: float,
    event_surprise: float,
    spread_expansion: float,
) -> float:
    return clamp01(
        0.30 * clamp01(volatility_delta)
        + 0.25 * clamp01(news_intensity)
        + 0.20 * clamp01(liquidity_stress)
        + 0.15 * clamp01(event_surprise)
        + 0.10 * clamp01(spread_expansion)
    )


def compute_collapse_coherence(
    theme_similarity: float,
    source_diversity: float,
    persistence: float,
    counter_signal_survival: float,
) -> float:
    return clamp01(
        clamp01(theme_similarity)
        * clamp01(source_diversity)
        * clamp01(persistence)
        * clamp01(counter_signal_survival)
        * 4.0
    )


def compute_durable_cluster(
    collapse_coherence: float,
    stress_survival: float,
    source_diversity: float,
    persistence: float,
    signal_zeta: float,
) -> float:
    return clamp01(
        clamp01(collapse_coherence)
        * clamp01(stress_survival)
        * clamp01(source_diversity)
        * clamp01(persistence)
        * clamp01(signal_zeta)
        * 4.0
    )


def compute_execution_quality(
    plan_clarity: float,
    risk_control: float,
    invalidation_clarity: float,
    exit_discipline: float,
    review_discipline: float,
) -> float:
    return clamp01(
        clamp01(plan_clarity)
        * clamp01(risk_control)
        * clamp01(invalidation_clarity)
        * clamp01(exit_discipline)
        * clamp01(review_discipline)
        * 4.0
    )


def compute_investable_signal(
    detection: float,
    collapse_coherence: float,
    durability: float,
    execution_survivability: float,
    policy_permission: float,
) -> float:
    return clamp01(
        clamp01(detection)
        * clamp01(collapse_coherence)
        * clamp01(durability)
        * clamp01(execution_survivability)
        * clamp01(policy_permission)
        * 8.0
    )


def determine_system_mode(trigger_strength: float, release_pressure: float) -> str:
    return (
        SystemMode.TRIGGERED.value
        if trigger_strength >= release_pressure
        else SystemMode.CONTINUOUS.value
    )


def classify_bull_state(payload: ReleaseTriggerInput, thresholds: dict[str, float]) -> LayerOutput:
    release_pressure = compute_release_pressure(payload.signals)
    trigger_strength = compute_trigger_strength(payload)
    separation_strength = compute_separation_strength(
        payload.metadata_clarity,
        payload.source_independence,
        payload.theme_distance,
    )
    signal_texture = compute_signal_texture(payload.confidence, payload.persistence, payload.noise)
    opportunity_half_life = compute_opportunity_half_life(
        payload.initial_edge,
        payload.decay_rate,
        payload.elapsed_time,
    )
    transient_value = compute_transient_value(
        payload.peak_alignment,
        payload.time_decay,
        payload.execution_delay_penalty,
    )
    validation_buffer = compute_validation_buffer(
        payload.source_diversity,
        payload.persistence,
        payload.counter_signal_resistance,
        payload.metadata_clarity,
        payload.echo_chamber_penalty,
    )
    signal_zeta = compute_signal_zeta(
        payload.confidence,
        payload.validation_depth,
        payload.source_diversity,
        payload.persistence,
        payload.echo_chamber_penalty,
        payload.circular_citation_penalty,
        payload.same_narrative_origin_penalty,
    )
    aggregation_risk = compute_aggregation_risk(signal_zeta)
    false_conviction_risk = compute_false_conviction_risk(
        payload.cluster_density,
        payload.source_independence,
    )
    shock_score = compute_shock_score(
        payload.volatility_delta,
        payload.news_intensity,
        payload.liquidity_stress,
        payload.event_surprise,
        payload.spread_expansion,
    )
    collapse_coherence = compute_collapse_coherence(
        payload.theme_similarity,
        payload.source_diversity,
        payload.persistence,
        payload.counter_signal_survival,
    )
    durable_cluster = compute_durable_cluster(
        collapse_coherence,
        payload.stress_survival,
        payload.source_diversity,
        payload.persistence,
        signal_zeta,
    )
    execution_quality = compute_execution_quality(
        payload.plan_clarity,
        payload.risk_control,
        payload.invalidation_clarity,
        payload.exit_discipline,
        payload.review_discipline,
    )
    release_ready = release_pressure >= thresholds["theta_release"]
    smooth_signal_ready = signal_texture >= thresholds["theta_texture"]
    act_now = (
        opportunity_half_life < clamp01(payload.validation_time)
        and clamp01(payload.minimum_validation) >= thresholds["theta_min_validation"]
    )
    promotion_ready = (
        clamp01(payload.validation_depth) >= thresholds["theta_validation"]
        and durable_cluster >= thresholds["theta_durability"]
        and signal_zeta >= thresholds["theta_zeta_min"]
        and false_conviction_risk <= thresholds["theta_false_conviction_max"]
        and not payload.chaos_veto
        and not payload.policy_veto
    )
    execution_ready = (
        promotion_ready
        and payload.execution_plan_complete
        and payload.entry_defined
        and payload.invalidation_clarity >= 0.5
        and payload.sizing_defined
        and payload.exit_defined
        and payload.review_defined
    )
    system_mode = determine_system_mode(trigger_strength, release_pressure)
    vetoes: list[str] = []
    if payload.policy_veto:
        vetoes.append("POLICY_VETO")
    if payload.chaos_veto or shock_score >= thresholds["theta_chaos"]:
        vetoes.append("CHAOS_VETO")
    if payload.irreversible_event_shock:
        vetoes.append("IRREVERSIBLE_EVENT_SHOCK")

    state = BullSignalState.MIURA.value
    recommendation = "HOLD_MIURA_RAW"
    rationale = [
        "Detection != Admission",
        "Cluster != Validation",
        "Promotion != Execution",
    ]

    if payload.irreversible_event_shock:
        state = BullSignalState.ISLERO.value
        recommendation = "FORCE_ISLERO_RECLASSIFICATION"
        rationale.append("Irreversible shock overrides normal state progression.")
    elif payload.policy_veto or payload.chaos_veto or shock_score >= thresholds["theta_chaos"]:
        state = BullSignalState.DIABLO.value
        recommendation = "BLOCKED_BY_DIABLO"
        rationale.append("Policy or chaos veto outranks release, clustering, and promotion.")
    elif (
        payload.momentum >= thresholds["theta_momentum"]
        and clamp01(payload.minimum_validation) >= thresholds["theta_min_validation"]
        and payload.risk_cap_active
        and not payload.policy_veto
        and not payload.chaos_veto
    ):
        state = BullSignalState.HURACAN.value
        recommendation = "HURACAN_FAST_TRACK_REVIEW_ONLY"
        rationale.append("Fast-track review is allowed, but Gallardo still requires Aventador and execution discipline.")
    elif release_ready and trigger_strength >= thresholds["theta_trigger"] and separation_strength >= thresholds["theta_separation_min"]:
        state = BullSignalState.COLLAPSE_ANALYSIS.value
        recommendation = "RUN_COLLAPSE_ANALYSIS"
        rationale.append("Latent pressure and trigger are strong enough to justify controlled collapse analysis.")
        if (
            collapse_coherence >= thresholds["theta_coherence"]
            and signal_zeta >= thresholds["theta_zeta_min"]
            and false_conviction_risk <= thresholds["theta_false_conviction_max"]
        ):
            state = BullSignalState.MURCIELAGO.value
            recommendation = "SEND_TO_MURCIELAGO_DURABILITY"
            rationale.append("Collapse cluster held together with enough zeta stability and low false-conviction risk.")
            if (
                durable_cluster >= thresholds["theta_durability"]
                and clamp01(payload.stress_survival) >= thresholds["theta_stress"]
                and not payload.policy_veto
                and not payload.chaos_veto
            ):
                state = BullSignalState.AVENTADOR.value
                recommendation = "PROMOTE_TO_AVENTADOR"
                rationale.append("Durability and stress survival passed without policy or chaos veto.")
                if execution_ready:
                    state = BullSignalState.GALLARDO.value
                    recommendation = "PREPARE_GALLARDO_EXECUTION"
                    rationale.append("Execution discipline checks are complete. This remains human-review only.")

    if state == BullSignalState.COLLAPSE_ANALYSIS.value:
        execution_ready = False
        recommendation = "RUN_COLLAPSE_ANALYSIS"
        rationale.append("CollapseAnalysis != TradeSignal.")
    if state in {BullSignalState.MIURA.value, BullSignalState.COLLAPSE_ANALYSIS.value} and recommendation == "PREPARE_GALLARDO_EXECUTION":
        state = BullSignalState.MURCIELAGO.value
        recommendation = "SEND_TO_MURCIELAGO_DURABILITY"
        rationale.append("Direct jump to Gallardo is invalid from Miura or Collapse Analysis.")

    return LayerOutput(
        state=state,
        recommendation=recommendation,
        rationale=rationale,
        vetoes=vetoes,
        scores={
            "release_pressure": round(release_pressure, 4),
            "release_ready": release_ready,
            "trigger_strength": round(trigger_strength, 4),
            "system_mode": system_mode,
            "signal_texture": round(signal_texture, 4),
            "smooth_signal_ready": smooth_signal_ready,
            "opportunity_half_life": round(opportunity_half_life, 4),
            "act_now": act_now,
            "transient_value": round(transient_value, 4),
            "validation_buffer": round(validation_buffer, 4),
            "separation_strength": round(separation_strength, 4),
            "signal_zeta": round(signal_zeta, 4),
            "aggregation_risk": round(aggregation_risk, 4),
            "false_conviction_risk": round(false_conviction_risk, 4),
            "shock_score": round(shock_score, 4),
            "collapse_coherence": round(collapse_coherence, 4),
            "durable_cluster": round(durable_cluster, 4),
            "durability_score": round(durable_cluster, 4),
            "promotion_ready": promotion_ready,
            "execution_quality": round(execution_quality, 4),
            "execution_ready": execution_ready,
            "investable_signal": round(
                compute_investable_signal(
                    payload.confidence,
                    collapse_coherence,
                    durable_cluster,
                    payload.execution_survivability,
                    payload.policy_permission,
                ),
                4,
            ),
        },
    )


def _artifact(
    *,
    module: str,
    inputs: dict[str, Any],
    scores: dict[str, Any],
    state: str,
    vetoes: list[str],
    recommendation: str,
    rationale: list[str],
    operating_mode: str,
    truth_origin: str,
) -> dict[str, Any]:
    return {
        "run_id": get_run_id(),
        "generated_at": utc_timestamp(),
        "module": module,
        "schema_version": SCHEMA_VERSION,
        "inputs": inputs,
        "scores": scores,
        "state": state,
        "vetoes": vetoes,
        "recommendation": recommendation,
        "rationale": rationale,
        "data_quality": "synthetic_or_runtime_fallback",
        "live_ready": False,
        "source_mode": get_source_mode(),
        "operating_mode": operating_mode,
        "truth_origin": truth_origin,
    }


def _build_input_payload(
    *,
    runtime_state: dict[str, Any],
    signal_refinery_report: dict[str, Any],
    attention_proxy_report: dict[str, Any],
    perception_control_report: dict[str, Any],
    structural_admission_report: dict[str, Any],
    friction_report: dict[str, Any] | None = None,
) -> ReleaseTriggerInput:
    validation_rows = signal_refinery_report.get("validation_engine", {}).get("signals", [])
    top_row = validation_rows[0] if isinstance(validation_rows, list) and validation_rows and isinstance(validation_rows[0], dict) else {}
    active_blockers = runtime_state.get("active_blockers", [])
    if not isinstance(active_blockers, list):
        active_blockers = []
    source_quality = clamp01(float(top_row.get("source_quality_score", 0.0) or 0.0))
    persistence = clamp01(float(perception_control_report.get("signal_survival_rate", 0.0) or 0.0))
    validation = clamp01(float(top_row.get("validation_score", 0.0) or 0.0))
    novelty = clamp01(float(top_row.get("novelty_score", 0.0) or 0.0))
    first_order = clamp01(float(top_row.get("first_order_score", 0.0) or 0.0))
    cross_confirmation = clamp01(float(top_row.get("cross_source_confirmation_score", 0.0) or 0.0))
    blocker_clearance = clamp01(float(top_row.get("blocker_clearance_score", 0.0) or 0.0))
    attention = clamp01(float(attention_proxy_report.get("attention_proxy_score", 0.0) or 0.0))
    narrative_heat = clamp01(float(attention_proxy_report.get("narrative_heat_score", 0.0) or 0.0))
    average_lux = clamp01(float(perception_control_report.get("average_signal_lux", 0.0) or 0.0))
    noise = clamp01(1.0 - float(perception_control_report.get("noise_suppression_ratio", 0.0) or 0.0))
    friction_band = str((friction_report or {}).get("friction_band") or "HIGH_FRICTION").upper()
    policy = runtime_state.get("execution_policy", {})
    allow_new_risk = bool(policy.get("allow_new_risk", False))
    execution_survivability = structural_admission_report.get("component_scores", {}).get("execution_survivability", 0.0)
    momentum = clamp01(float(runtime_state.get("signal_summary", {}).get("scm_rate", 0.0) or 0.0))
    signals_above_threshold = float(runtime_state.get("signal_summary", {}).get("signals_above_ce_threshold", 0) or 0)
    total_signals = float(max(runtime_state.get("signal_summary", {}).get("total_signals", 0) or 0, 1))
    cluster_density = clamp01(signals_above_threshold / total_signals)
    policy_veto = not allow_new_risk
    chaos_veto = "REALM_BIS" in [str(item).upper() for item in active_blockers]
    shock_flag = narrative_heat >= 0.95 and blocker_clearance <= 0.1

    signals = [
        SignalReleaseAtom(signal=validation, weight=0.35, persistence=persistence, source_quality=source_quality),
        SignalReleaseAtom(signal=first_order, weight=0.25, persistence=persistence, source_quality=source_quality),
        SignalReleaseAtom(signal=novelty, weight=0.20, persistence=persistence, source_quality=source_quality),
        SignalReleaseAtom(signal=attention, weight=0.20, persistence=persistence, source_quality=source_quality),
    ]
    return ReleaseTriggerInput(
        signals=signals,
        event_proximity=novelty,
        narrative_acceleration=attention,
        price_move_intensity=first_order,
        prediction_market_delta=clamp01(float(runtime_state.get("signal_summary", {}).get("scm_rate", 0.0) or 0.0)),
        source_burst=source_quality,
        confidence=validation,
        persistence=persistence,
        noise=max(noise, 0.05),
        initial_edge=validation,
        decay_rate=clamp01(1.0 - persistence),
        elapsed_time=1.0,
        validation_time=0.65,
        minimum_validation=validation,
        peak_alignment=attention,
        time_decay=clamp01(1.0 - persistence),
        execution_delay_penalty=1.0 if friction_band == "HIGH_FRICTION" else 0.5 if friction_band == "MEDIUM_FRICTION" else 0.2,
        source_diversity=clamp01(cross_confirmation + 0.2),
        counter_signal_resistance=blocker_clearance,
        metadata_clarity=average_lux,
        echo_chamber_penalty=clamp01(1.0 - source_quality),
        source_independence=clamp01(cross_confirmation + 0.1),
        theme_distance=clamp01(0.5 + blocker_clearance / 2.0),
        validation_depth=validation,
        circular_citation_penalty=clamp01(1.0 - cross_confirmation),
        same_narrative_origin_penalty=clamp01(1.0 - source_quality),
        cluster_density=cluster_density,
        volatility_delta=max(narrative_heat, 1.0 if chaos_veto else 0.0),
        news_intensity=attention,
        liquidity_stress=clamp01(1.0 - source_quality),
        event_surprise=novelty,
        spread_expansion=1.0 if friction_band == "HIGH_FRICTION" else 0.5 if friction_band == "MEDIUM_FRICTION" else 0.2,
        theme_similarity=clamp01((validation + first_order) / 2.0),
        counter_signal_survival=blocker_clearance,
        stress_survival=clamp01(structural_admission_report.get("materiality", {}).get("durability_score", 0.0)),
        plan_clarity=clamp01(structural_admission_report.get("layer_scores", {}).get("use_case_fit", {}).get("score", 0.0)),
        risk_control=clamp01(structural_admission_report.get("layer_scores", {}).get("execution_survivability", {}).get("score", 0.0)),
        invalidation_clarity=blocker_clearance,
        exit_discipline=clamp01(float(perception_control_report.get("noise_suppression_ratio", 0.0) or 0.0)),
        review_discipline=1.0 if runtime_state.get("moltbook_feedback") else 0.5,
        execution_survivability=clamp01(execution_survivability),
        policy_permission=1.0 if allow_new_risk else 0.0,
        policy_veto=policy_veto,
        chaos_veto=chaos_veto,
        irreversible_event_shock=shock_flag,
        momentum=momentum,
        risk_cap_active=str(
            runtime_state.get("execution_policy", {}).get("policy_state", "")
        ).upper() in {"RESTRICTED", "LIMITED_DEPLOY", "REVIEW_READY"},
        execution_plan_complete=blocker_clearance >= 0.7,
        entry_defined=blocker_clearance >= 0.65,
        sizing_defined=bool(runtime_state.get("execution_policy", {}).get("policy_state")),
        exit_defined=blocker_clearance >= 0.65,
        review_defined=True,
        previous_state=str(structural_admission_report.get("bull_state") or BullSignalState.MIURA.value),
        system_name=str(top_row.get("ticker") or "PIPELINE"),
    )


def build_latent_signal_release_bull_report(
    *,
    runtime_state: dict[str, Any],
    signal_refinery_report: dict[str, Any],
    attention_proxy_report: dict[str, Any],
    perception_control_report: dict[str, Any],
    structural_admission_report: dict[str, Any],
    friction_report: dict[str, Any] | None = None,
    write_runtime: bool = False,
) -> dict[str, Any]:
    thresholds = load_thresholds()
    operating_mode = classify_operating_mode(runtime_state)
    truth_origin = build_truth_context(runtime_state).get("truth_origin", "seeded")
    payload = _build_input_payload(
        runtime_state=runtime_state,
        signal_refinery_report=signal_refinery_report,
        attention_proxy_report=attention_proxy_report,
        perception_control_report=perception_control_report,
        structural_admission_report=structural_admission_report,
        friction_report=friction_report,
    )
    layer = classify_bull_state(payload, thresholds)
    inputs = {
        "system_name": payload.system_name,
        "source": payload.source,
        "previous_state": payload.previous_state,
        "policy_veto": payload.policy_veto,
        "chaos_veto": payload.chaos_veto,
        "data_quality": "synthetic_or_runtime_fallback",
        "live_ready": False,
    }

    artifacts = {
        "latent_signal_release": _artifact(
            module="latent_signal_release_engine",
            inputs=inputs,
            scores={
                "release_pressure": layer.scores["release_pressure"],
                "release_ready": layer.scores["release_ready"],
                "trigger_strength": layer.scores["trigger_strength"],
                "system_mode": layer.scores["system_mode"],
            },
            state=layer.state,
            vetoes=layer.vetoes,
            recommendation=layer.recommendation,
            rationale=layer.rationale,
            operating_mode=operating_mode,
            truth_origin=truth_origin,
        ),
        "signal_texture": _artifact(
            module="signal_texture_engine",
            inputs=inputs,
            scores={
                "signal_texture": layer.scores["signal_texture"],
                "smooth_signal_ready": layer.scores["smooth_signal_ready"],
            },
            state=layer.state,
            vetoes=layer.vetoes,
            recommendation=layer.recommendation,
            rationale=layer.rationale,
            operating_mode=operating_mode,
            truth_origin=truth_origin,
        ),
        "opportunity_half_life": _artifact(
            module="opportunity_half_life_tracker",
            inputs=inputs,
            scores={
                "opportunity_half_life": layer.scores["opportunity_half_life"],
                "transient_value": layer.scores["transient_value"],
                "act_now": layer.scores["act_now"],
            },
            state=layer.state,
            vetoes=layer.vetoes,
            recommendation=layer.recommendation,
            rationale=layer.rationale,
            operating_mode=operating_mode,
            truth_origin=truth_origin,
        ),
        "validation_buffer": _artifact(
            module="validation_buffer_layer",
            inputs=inputs,
            scores={
                "validation_buffer": layer.scores["validation_buffer"],
                "separation_strength": layer.scores["separation_strength"],
            },
            state=layer.state,
            vetoes=layer.vetoes,
            recommendation=layer.recommendation,
            rationale=layer.rationale,
            operating_mode=operating_mode,
            truth_origin=truth_origin,
        ),
        "signal_zeta": _artifact(
            module="signal_zeta_score",
            inputs=inputs,
            scores={
                "signal_zeta": layer.scores["signal_zeta"],
                "aggregation_risk": layer.scores["aggregation_risk"],
            },
            state=layer.state,
            vetoes=layer.vetoes,
            recommendation=layer.recommendation,
            rationale=layer.rationale,
            operating_mode=operating_mode,
            truth_origin=truth_origin,
        ),
        "false_conviction": _artifact(
            module="false_conviction_detector",
            inputs=inputs,
            scores={
                "false_conviction_risk": layer.scores["false_conviction_risk"],
            },
            state=layer.state,
            vetoes=layer.vetoes,
            recommendation=layer.recommendation,
            rationale=layer.rationale,
            operating_mode=operating_mode,
            truth_origin=truth_origin,
        ),
        "collapse_analysis": _artifact(
            module="collapse_analysis_mode",
            inputs=inputs,
            scores={
                "collapse_coherence": layer.scores["collapse_coherence"],
                "collapse_mode_active": layer.state == BullSignalState.COLLAPSE_ANALYSIS.value,
                "collapse_cluster_count": 1 if layer.state in {BullSignalState.COLLAPSE_ANALYSIS.value, BullSignalState.MURCIELAGO.value, BullSignalState.AVENTADOR.value, BullSignalState.GALLARDO.value} else 0,
                "cascade": round(layer.scores["release_pressure"] * layer.scores["trigger_strength"] * layer.scores["collapse_coherence"], 4),
            },
            state=layer.state,
            vetoes=layer.vetoes,
            recommendation="RUN_COLLAPSE_ANALYSIS" if layer.state == BullSignalState.COLLAPSE_ANALYSIS.value else layer.recommendation,
            rationale=layer.rationale + ["CollapseAnalysis cannot directly produce execution permission."],
            operating_mode=operating_mode,
            truth_origin=truth_origin,
        ),
        "murcielago_durability": _artifact(
            module="murcielago_durability_validator",
            inputs=inputs,
            scores={
                "durability_score": layer.scores["durability_score"],
            },
            state=layer.state,
            vetoes=layer.vetoes,
            recommendation=layer.recommendation,
            rationale=layer.rationale,
            operating_mode=operating_mode,
            truth_origin=truth_origin,
        ),
        "aventador_promotion": _artifact(
            module="aventador_promotion_gate",
            inputs=inputs,
            scores={
                "promotion_ready": layer.scores["promotion_ready"],
                "validation_depth": payload.validation_depth,
            },
            state=layer.state,
            vetoes=layer.vetoes,
            recommendation=layer.recommendation,
            rationale=layer.rationale,
            operating_mode=operating_mode,
            truth_origin=truth_origin,
        ),
        "gallardo_execution": _artifact(
            module="gallardo_execution_module",
            inputs=inputs,
            scores={
                "execution_ready": layer.scores["execution_ready"],
                "execution_quality": layer.scores["execution_quality"],
            },
            state=layer.state,
            vetoes=layer.vetoes,
            recommendation=layer.recommendation,
            rationale=layer.rationale + ["Promotion != Execution."],
            operating_mode=operating_mode,
            truth_origin=truth_origin,
        ),
        "bull_state": _artifact(
            module="bull_state_classifier",
            inputs=inputs,
            scores=layer.scores,
            state=layer.state,
            vetoes=layer.vetoes,
            recommendation=layer.recommendation,
            rationale=layer.rationale,
            operating_mode=operating_mode,
            truth_origin=truth_origin,
        ),
        "bull_transition_log": _artifact(
            module="bull_transition_logger",
            inputs=inputs,
            scores={
                "state_before": payload.previous_state,
                "state_after": layer.state,
                "transition_allowed": not (payload.previous_state in {BullSignalState.MIURA.value, BullSignalState.COLLAPSE_ANALYSIS.value} and layer.state == BullSignalState.GALLARDO.value),
            },
            state=layer.state,
            vetoes=layer.vetoes,
            recommendation=layer.recommendation,
            rationale=layer.rationale,
            operating_mode=operating_mode,
            truth_origin=truth_origin,
        ),
        "regime_shock": _artifact(
            module="regime_shock_detector",
            inputs=inputs,
            scores={"shock_score": layer.scores["shock_score"]},
            state=layer.state,
            vetoes=layer.vetoes,
            recommendation=layer.recommendation,
            rationale=layer.rationale,
            operating_mode=operating_mode,
            truth_origin=truth_origin,
        ),
    }

    if write_runtime:
        write_json_atomic(LATENT_SIGNAL_RELEASE_REPORT_PATH, artifacts["latent_signal_release"], stamp=False)
        write_json_atomic(SIGNAL_TEXTURE_REPORT_PATH, artifacts["signal_texture"], stamp=False)
        write_json_atomic(OPPORTUNITY_HALF_LIFE_REPORT_PATH, artifacts["opportunity_half_life"], stamp=False)
        write_json_atomic(VALIDATION_BUFFER_REPORT_PATH, artifacts["validation_buffer"], stamp=False)
        write_json_atomic(SIGNAL_ZETA_REPORT_PATH, artifacts["signal_zeta"], stamp=False)
        write_json_atomic(FALSE_CONVICTION_REPORT_PATH, artifacts["false_conviction"], stamp=False)
        write_json_atomic(COLLAPSE_ANALYSIS_REPORT_PATH, artifacts["collapse_analysis"], stamp=False)
        write_json_atomic(MURCIELAGO_DURABILITY_REPORT_PATH, artifacts["murcielago_durability"], stamp=False)
        write_json_atomic(AVENTADOR_PROMOTION_REPORT_PATH, artifacts["aventador_promotion"], stamp=False)
        write_json_atomic(GALLARDO_EXECUTION_REPORT_PATH, artifacts["gallardo_execution"], stamp=False)
        write_json_atomic(BULL_STATE_REPORT_PATH, artifacts["bull_state"], stamp=False)
        write_json_atomic(BULL_TRANSITION_LOG_PATH, artifacts["bull_transition_log"], stamp=False)

    return {
        "system_name": payload.system_name,
        "state": layer.state,
        "release_pressure": layer.scores["release_pressure"],
        "release_ready": layer.scores["release_ready"],
        "trigger_strength": layer.scores["trigger_strength"],
        "system_mode": layer.scores["system_mode"],
        "signal_texture": layer.scores["signal_texture"],
        "opportunity_half_life": layer.scores["opportunity_half_life"],
        "validation_buffer": layer.scores["validation_buffer"],
        "separation_strength": layer.scores["separation_strength"],
        "signal_zeta": layer.scores["signal_zeta"],
        "aggregation_risk": layer.scores["aggregation_risk"],
        "false_conviction_risk": layer.scores["false_conviction_risk"],
        "collapse_mode_active": layer.state == BullSignalState.COLLAPSE_ANALYSIS.value,
        "collapse_cluster_count": artifacts["collapse_analysis"]["scores"]["collapse_cluster_count"],
        "durability_score": layer.scores["durability_score"],
        "promotion_ready": layer.scores["promotion_ready"],
        "execution_ready": layer.scores["execution_ready"],
        "active_vetoes": layer.vetoes,
        "recommended_next_action": layer.recommendation,
        "investable_signal": layer.scores["investable_signal"],
        "execution_quality": layer.scores["execution_quality"],
        "shock_score": layer.scores["shock_score"],
        "artifacts": {
            "latent_signal_release_report_path": repo_relative(LATENT_SIGNAL_RELEASE_REPORT_PATH),
            "signal_texture_report_path": repo_relative(SIGNAL_TEXTURE_REPORT_PATH),
            "opportunity_half_life_report_path": repo_relative(OPPORTUNITY_HALF_LIFE_REPORT_PATH),
            "validation_buffer_report_path": repo_relative(VALIDATION_BUFFER_REPORT_PATH),
            "signal_zeta_report_path": repo_relative(SIGNAL_ZETA_REPORT_PATH),
            "false_conviction_report_path": repo_relative(FALSE_CONVICTION_REPORT_PATH),
            "collapse_analysis_report_path": repo_relative(COLLAPSE_ANALYSIS_REPORT_PATH),
            "murcielago_durability_report_path": repo_relative(MURCIELAGO_DURABILITY_REPORT_PATH),
            "aventador_promotion_report_path": repo_relative(AVENTADOR_PROMOTION_REPORT_PATH),
            "gallardo_execution_report_path": repo_relative(GALLARDO_EXECUTION_REPORT_PATH),
            "bull_state_report_path": repo_relative(BULL_STATE_REPORT_PATH),
            "bull_transition_log_path": repo_relative(BULL_TRANSITION_LOG_PATH),
        },
        "subreports": artifacts,
        "rationale": layer.rationale,
        "data_quality": "synthetic_or_runtime_fallback",
        "live_ready": False,
    }


def format_latent_signal_release_bull_summary(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Latent Signal Release Bull Layer",
            f"state={report.get('state', BullSignalState.MIURA.value)}",
            f"release_pressure={report.get('release_pressure', 0.0)}",
            f"trigger_strength={report.get('trigger_strength', 0.0)}",
            f"signal_zeta={report.get('signal_zeta', 0.0)}",
            f"recommended_next_action={report.get('recommended_next_action', 'HOLD_MIURA_RAW')}",
        ]
    )


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate the latent signal release bull layer.")
    parser.add_argument("--summary", action="store_true", help="Emit a compact summary.")
    parser.add_argument("--write-runtime", action="store_true", help="Persist runtime artifacts.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    runtime_state = build_runtime_state_from_scm_report_payload(build_signal_conversion_report())
    report = build_latent_signal_release_bull_report(
        runtime_state=runtime_state,
        signal_refinery_report={},
        attention_proxy_report={},
        perception_control_report={},
        structural_admission_report={},
        write_runtime=args.write_runtime,
    )
    if args.summary:
        print(format_latent_signal_release_bull_summary(report))
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
