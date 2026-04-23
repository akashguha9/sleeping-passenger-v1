from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any

try:
    from scripts.runtime_common import (
        PERCEPTION_CONTROL_CONFIG_PATH,
        PERCEPTION_CONTROL_REPORT_PATH,
        build_runtime_state_from_scm_report_payload,
        get_source_mode,
        load_json_file,
        repo_relative,
        write_json_atomic,
    )
except ModuleNotFoundError:
    from runtime_common import (
        PERCEPTION_CONTROL_CONFIG_PATH,
        PERCEPTION_CONTROL_REPORT_PATH,
        build_runtime_state_from_scm_report_payload,
        get_source_mode,
        load_json_file,
        repo_relative,
        write_json_atomic,
    )


DEFAULT_CONFIG: dict[str, Any] = {
    "deprivation": {
        "pass_threshold": 0.57,
        "persistence_cap": 4,
        "weights": {
            "confidence": 0.24,
            "persistence": 0.08,
            "structural_relevance": 0.18,
            "asset_attachment": 0.10,
            "timing_usefulness": 0.14,
            "readiness_compatibility": 0.14,
            "source_quality": 0.06,
            "blocker_interaction": 0.06,
        },
    },
    "injection": {
        "resurfacing_threshold": 0.58,
        "weights": {
            "intensity": 0.22,
            "validation": 0.18,
            "visibility": 0.16,
            "timing": 0.16,
            "persistence": 0.08,
            "source_quality": 0.08,
            "phase_relevance": 0.12,
        },
    },
    "gravity": {
        "survival_threshold": 0.64,
        "timing_alignment_floor": 0.42,
        "explainability_floor": 0.55,
        "weights": {
            "signal_lux": 0.32,
            "explainability": 0.22,
            "timing_alignment": 0.16,
            "blocker_clearance": 0.14,
            "structural_coherence": 0.16,
        },
    },
    "bias_proxy": {
        "prior_dominance_gap_threshold": 0.08,
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_perception_control_config(path: Path | None = None) -> dict[str, Any]:
    target = path or PERCEPTION_CONTROL_CONFIG_PATH
    payload = load_json_file(target, default={})
    if not isinstance(payload, dict):
        payload = {}
    return _deep_merge(DEFAULT_CONFIG, payload)


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip() or default


def _coerce_float(value: Any, default: float | None = None) -> float | None:
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: Any, default: int = 0) -> int:
    if value is None or isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _safe_round(value: float | None, digits: int = 3) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _mean(values: list[float]) -> float | None:
    return float(mean(values)) if values else None


def _median(values: list[float]) -> float | None:
    return float(median(values)) if values else None


def _validation_rows_by_ticker(signal_refinery_report: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    report = signal_refinery_report if isinstance(signal_refinery_report, dict) else {}
    validation_engine = report.get("validation_engine", {})
    rows = validation_engine.get("signals", []) if isinstance(validation_engine, dict) else []
    mapping: dict[str, dict[str, Any]] = {}
    if not isinstance(rows, list):
        return mapping
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = _text(row.get("ticker")).upper()
        signal_id = _text(row.get("signal_id"))
        if ticker:
            mapping[ticker] = row
        if signal_id and signal_id not in mapping:
            mapping[signal_id] = row
    return mapping


def _launch_rows_by_ticker(signal_refinery_report: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    report = signal_refinery_report if isinstance(signal_refinery_report, dict) else {}
    launch_control = report.get("launch_control", {})
    rows = launch_control.get("launch_rows", []) if isinstance(launch_control, dict) else []
    mapping: dict[str, dict[str, Any]] = {}
    if not isinstance(rows, list):
        return mapping
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = _text(row.get("ticker")).upper()
        if ticker:
            mapping[ticker] = row
    return mapping


def _persistence_by_ticker(trend_report: dict[str, Any] | None) -> dict[str, int]:
    report = trend_report if isinstance(trend_report, dict) else {}
    keys = (
        "blocked_promotable_transition_streak",
        "clean_ready_pending_transition_streak",
        "clean_entry_eligible_transition_streak",
        "entry_review_candidate_streak",
        "transition_review_candidate_streak",
    )
    mapping: dict[str, int] = {}
    for key in keys:
        block = report.get(key, {})
        if not isinstance(block, dict):
            continue
        rows = block.get("persistent_names", [])
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                ticker = _text(row.get("ticker")).upper()
                if not ticker:
                    continue
                mapping[ticker] = max(
                    mapping.get(ticker, 0),
                    _coerce_int(row.get("consecutive_snapshots"), 0),
                )
        current_names = block.get("current_names", [])
        if isinstance(current_names, list):
            count = _coerce_int(block.get("consecutive_snapshots"), 0)
            for item in current_names:
                ticker = _text(item).upper()
                if ticker:
                    mapping[ticker] = max(mapping.get(ticker, 0), count)
    return mapping


def _readiness_compatibility(signal_row: dict[str, Any]) -> float:
    status = _text(signal_row.get("status")).upper()
    pre_entry_state = _text(signal_row.get("pre_entry_state"), "NONE").upper()
    watchlist_tier = _text(signal_row.get("watchlist_tier"), "NONE").upper()
    if status == "EXECUTED_CLEAN":
        return 0.9
    if pre_entry_state == "CLEAN_ENTRY_ELIGIBLE":
        return 0.95
    if pre_entry_state == "CLEAN_READY_PENDING_TRIGGER":
        return 0.8
    if pre_entry_state == "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE":
        return 0.68
    if watchlist_tier == "PROMOTABLE":
        return 0.58
    if status == "EXECUTED_CHAOS":
        return 0.1
    return 0.28


def _structural_relevance(signal_row: dict[str, Any], validation_row: dict[str, Any] | None) -> float:
    validation_score = _coerce_float((validation_row or {}).get("validation_score"))
    ce_score = _coerce_float(signal_row.get("ce_score"), 0.0) or 0.0
    readiness = _readiness_compatibility(signal_row)
    if validation_score is None:
        return _clamp((0.55 * readiness) + (0.45 * ce_score))
    return _clamp((0.5 * readiness) + (0.5 * validation_score))


def _confidence_input(signal_row: dict[str, Any], validation_row: dict[str, Any] | None) -> float:
    values = [
        value
        for value in (
            _coerce_float(signal_row.get("ce_score")),
            _coerce_float(signal_row.get("priority_score")),
            _coerce_float((validation_row or {}).get("validation_score")),
        )
        if value is not None
    ]
    return _clamp(max(values) if values else 0.0)


def _blocker_interaction(signal_row: dict[str, Any], validation_row: dict[str, Any] | None) -> float:
    blocker_clearance = _coerce_float((validation_row or {}).get("blocker_clearance_score"))
    if blocker_clearance is not None:
        return _clamp(blocker_clearance)
    blocker = _text(signal_row.get("blocker_attribution"), "NONE").upper()
    if blocker == "NONE":
        return 1.0
    if blocker == "GSCE_PHASE_LOCK":
        return 0.35
    if blocker == "REALM_BIS":
        return 0.05
    return 0.2


def _timing_alignment_score(
    signal_row: dict[str, Any],
    validation_row: dict[str, Any] | None,
) -> float:
    temporal_position = _coerce_float((validation_row or {}).get("temporal_position"))
    if temporal_position is None:
        status = _text(signal_row.get("status")).upper()
        if status == "EXECUTED_CLEAN":
            return 0.62
        if _text(signal_row.get("watchlist_tier")).upper() == "PROMOTABLE":
            return 0.58
        return 0.38

    pre_entry_state = _text(signal_row.get("pre_entry_state"), "NONE").upper()
    status = _text(signal_row.get("status")).upper()
    target = 0.4
    if pre_entry_state == "CLEAN_ENTRY_ELIGIBLE":
        target = 0.48
    elif pre_entry_state == "CLEAN_READY_PENDING_TRIGGER":
        target = 0.42
    elif pre_entry_state == "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE":
        target = 0.36
    elif status == "EXECUTED_CLEAN":
        target = 0.55
    score = max(0.0, 1.0 - (abs(temporal_position - target) / 0.7))
    if bool((validation_row or {}).get("asymmetry_window_flag")):
        score += 0.08
    if bool((validation_row or {}).get("late_obviousness_flag")) or bool(
        (validation_row or {}).get("full_moon_trap_flag")
    ):
        score -= 0.12
    return _clamp(score)


def _asset_attachment(signal_row: dict[str, Any]) -> float:
    signal_id = _text(signal_row.get("signal_id"))
    ticker = _text(signal_row.get("ticker")).upper()
    if signal_id and ticker:
        return 1.0
    if ticker:
        return 0.72
    return 0.0


def _source_quality(signal_row: dict[str, Any], validation_row: dict[str, Any] | None) -> float:
    source_quality = _coerce_float((validation_row or {}).get("source_quality_score"))
    if source_quality is not None:
        return _clamp(source_quality)
    source_name = _text(signal_row.get("source_name")).lower()
    signal_origin = _text(signal_row.get("signal_origin")).lower()
    if source_name.startswith("polymarket") or signal_origin == "external":
        return 0.62
    return 0.55


def _phase_relevance(signal_row: dict[str, Any], launch_row: dict[str, Any] | None) -> float:
    launch_state = _text((launch_row or {}).get("launch_state")).upper()
    if launch_state == "REVIEW_READY":
        return 1.0
    if launch_state == "ACTIVE_VALIDATED_POSITION":
        return 0.9
    if launch_state.startswith("BLOCKED_"):
        return 0.52
    pre_entry_state = _text(signal_row.get("pre_entry_state"), "NONE").upper()
    status = _text(signal_row.get("status")).upper()
    if pre_entry_state == "CLEAN_ENTRY_ELIGIBLE":
        return 0.92
    if pre_entry_state == "CLEAN_READY_PENDING_TRIGGER":
        return 0.78
    if pre_entry_state == "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE":
        return 0.65
    if status == "EXECUTED_CLEAN":
        return 0.74
    if status == "EXECUTED_CHAOS":
        return 0.12
    return 0.35


def _spectrum_class(
    signal_row: dict[str, Any],
    validation_row: dict[str, Any] | None,
) -> str:
    status = _text(signal_row.get("status")).upper()
    pre_entry_state = _text(signal_row.get("pre_entry_state"), "NONE").upper()
    watchlist_tier = _text(signal_row.get("watchlist_tier"), "NONE").upper()
    if status == "EXECUTED_CHAOS" or _text(signal_row.get("blocker_attribution")).upper() == "REALM_BIS":
        return "anomaly"
    if status == "EXECUTED_CLEAN":
        return "flow"
    if pre_entry_state in {
        "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE",
        "CLEAN_READY_PENDING_TRIGGER",
        "CLEAN_ENTRY_ELIGIBLE",
    } or watchlist_tier == "PROMOTABLE":
        return "structural"
    temporal_position = _coerce_float((validation_row or {}).get("temporal_position"))
    if temporal_position is not None and temporal_position <= 0.28:
        return "event"
    return "narrative"


def _noise_classification(
    signal_row: dict[str, Any],
    deprivation_pass: bool,
    timing_alignment_score: float,
    readiness_compatibility: float,
    asset_attachment: float,
) -> str:
    if deprivation_pass:
        return "retained_signal"
    status = _text(signal_row.get("status")).upper()
    blocker = _text(signal_row.get("blocker_attribution")).upper()
    watchlist_tier = _text(signal_row.get("watchlist_tier")).upper()
    if status == "EXECUTED_CHAOS" or blocker == "REALM_BIS":
        return "chaos_contamination"
    if asset_attachment < 0.8:
        return "weak_attachment"
    if timing_alignment_score < 0.42:
        return "timing_drift"
    if readiness_compatibility < 0.45 and watchlist_tier != "PROMOTABLE":
        return "premature_exposure"
    return "low_structural_signal"


def _perception_row(
    signal_row: dict[str, Any],
    validation_row: dict[str, Any] | None,
    launch_row: dict[str, Any] | None,
    persistence_count: int,
    config: dict[str, Any],
) -> dict[str, Any]:
    deprivation_config = config["deprivation"]
    injection_config = config["injection"]
    gravity_config = config["gravity"]

    confidence = _confidence_input(signal_row, validation_row)
    readiness = _readiness_compatibility(signal_row)
    structural_relevance = _structural_relevance(signal_row, validation_row)
    timing_alignment_score = _timing_alignment_score(signal_row, validation_row)
    asset_attachment = _asset_attachment(signal_row)
    source_quality = _source_quality(signal_row, validation_row)
    blocker_interaction = _blocker_interaction(signal_row, validation_row)
    persistence_cap = max(1, _coerce_int(deprivation_config.get("persistence_cap"), 4))
    persistence_score = _clamp(max(0.25, persistence_count / persistence_cap))
    deprivation_weights = deprivation_config["weights"]
    deprivation_score = _clamp(
        (confidence * float(deprivation_weights["confidence"]))
        + (persistence_score * float(deprivation_weights["persistence"]))
        + (structural_relevance * float(deprivation_weights["structural_relevance"]))
        + (asset_attachment * float(deprivation_weights["asset_attachment"]))
        + (timing_alignment_score * float(deprivation_weights["timing_usefulness"]))
        + (readiness * float(deprivation_weights["readiness_compatibility"]))
        + (source_quality * float(deprivation_weights["source_quality"]))
        + (blocker_interaction * float(deprivation_weights["blocker_interaction"]))
    )
    deprivation_pass = deprivation_score >= float(deprivation_config.get("pass_threshold", 0.57))
    deprivation_reason_codes: list[str] = []
    if confidence < 0.5:
        deprivation_reason_codes.append("low_confidence")
    if structural_relevance < 0.5:
        deprivation_reason_codes.append("low_structural_relevance")
    if asset_attachment < 0.8:
        deprivation_reason_codes.append("weak_asset_attachment")
    if timing_alignment_score < 0.42:
        deprivation_reason_codes.append("weak_timing_utility")
    if readiness < 0.45:
        deprivation_reason_codes.append("readiness_mismatch")
    if blocker_interaction < 0.2:
        deprivation_reason_codes.append("blocker_conflict")
    if deprivation_pass:
        deprivation_reason_codes.append("survives_deprivation")

    light_score = _coerce_float((validation_row or {}).get("light_score"), confidence) or confidence
    validation_score = _coerce_float((validation_row or {}).get("validation_score"), confidence) or confidence
    phase_relevance = _phase_relevance(signal_row, launch_row)
    injection_weights = injection_config["weights"]
    signal_lux = _clamp(
        (confidence * float(injection_weights["intensity"]))
        + (validation_score * float(injection_weights["validation"]))
        + (light_score * float(injection_weights["visibility"]))
        + (timing_alignment_score * float(injection_weights["timing"]))
        + (persistence_score * float(injection_weights["persistence"]))
        + (source_quality * float(injection_weights["source_quality"]))
        + (phase_relevance * float(injection_weights["phase_relevance"]))
    )
    resurfacing_priority = _clamp(
        (0.55 * signal_lux)
        + (0.25 * phase_relevance)
        + (0.20 * timing_alignment_score)
        + (0.04 if bool((validation_row or {}).get("asymmetry_window_flag")) else 0.0)
        - (0.06 if bool((validation_row or {}).get("late_obviousness_flag")) else 0.0)
    )
    resurfacing_candidate = deprivation_pass and (
        resurfacing_priority >= float(injection_config.get("resurfacing_threshold", 0.58))
        or phase_relevance >= 0.85
    )
    injection_reason_codes: list[str] = []
    if signal_lux >= 0.65:
        injection_reason_codes.append("high_signal_lux")
    if timing_alignment_score >= 0.6:
        injection_reason_codes.append("timing_aligned")
    if phase_relevance >= 0.8:
        injection_reason_codes.append("phase_relevant")
    if bool((validation_row or {}).get("asymmetry_window_flag")):
        injection_reason_codes.append("asymmetry_window")
    if resurfacing_candidate:
        injection_reason_codes.append("resurface_candidate")

    exposure_timing_state = "DEFER"
    if timing_alignment_score >= 0.72 and phase_relevance >= 0.75:
        exposure_timing_state = "IMMEDIATE"
    elif timing_alignment_score >= 0.55:
        exposure_timing_state = "NEAR_TERM"
    elif bool((validation_row or {}).get("late_obviousness_flag")):
        exposure_timing_state = "LATE"

    spectrum_class = _spectrum_class(signal_row, validation_row)
    validation_state = _text((validation_row or {}).get("validation_state"), "UNSCORED").upper()
    launch_state = _text((launch_row or {}).get("launch_state"), "OBSERVE").upper()
    hidden_risk_flag = bool((validation_row or {}).get("hidden_risk_flag"))
    explainability_score = 0.25
    if validation_state == "VALIDATED":
        explainability_score = 1.0
    elif validation_state == "NEEDS_CONFIRMATION":
        explainability_score = 0.72
    elif validation_state == "INVALIDATED":
        explainability_score = 0.18
    invalidation_clarity_score = 0.4
    if _text(signal_row.get("signal_id")) and _text(signal_row.get("blocker_attribution")) and _text(
        signal_row.get("pre_entry_state"),
        "NONE",
    ):
        invalidation_clarity_score = 1.0
    structural_coherence = {
        "structural": 0.9,
        "flow": 0.82,
        "event": 0.68,
        "narrative": 0.45,
        "anomaly": 0.15,
    }[spectrum_class]
    if hidden_risk_flag:
        structural_coherence = max(0.0, structural_coherence - 0.25)
    gravity_weights = gravity_config["weights"]
    survival_score = _clamp(
        (signal_lux * float(gravity_weights["signal_lux"]))
        + (explainability_score * float(gravity_weights["explainability"]))
        + (timing_alignment_score * float(gravity_weights["timing_alignment"]))
        + (blocker_interaction * float(gravity_weights["blocker_clearance"]))
        + (structural_coherence * float(gravity_weights["structural_coherence"]))
        + (0.05 * invalidation_clarity_score)
        + (
            0.06
            if launch_state in {"REVIEW_READY", "ACTIVE_VALIDATED_POSITION"}
            else 0.0
        )
        - (0.1 if launch_state.startswith("BLOCKED_") else 0.0)
    )
    gravity_failure_reasons: list[str] = []
    if not deprivation_pass:
        gravity_failure_reasons.append("suppressed_before_constraint")
    if not resurfacing_candidate:
        gravity_failure_reasons.append("not_selected_for_resurfacing")
    if explainability_score < float(gravity_config.get("explainability_floor", 0.55)):
        gravity_failure_reasons.append("weak_explainability")
    if timing_alignment_score < float(gravity_config.get("timing_alignment_floor", 0.42)):
        gravity_failure_reasons.append("weak_timing_alignment")
    if blocker_interaction < 0.5 and launch_state not in {
        "REVIEW_READY",
        "ACTIVE_VALIDATED_POSITION",
    }:
        gravity_failure_reasons.append("blocker_not_cleared")
    if hidden_risk_flag:
        gravity_failure_reasons.append("hidden_risk_flag")
    if launch_state.startswith("BLOCKED_"):
        gravity_failure_reasons.append(f"launch_control_{launch_state.lower()}")
    if spectrum_class in {"narrative", "anomaly"}:
        gravity_failure_reasons.append(f"weak_spectrum_{spectrum_class}")

    gravity_pass = (
        deprivation_pass
        and resurfacing_candidate
        and survival_score >= float(gravity_config.get("survival_threshold", 0.64))
        and explainability_score >= float(gravity_config.get("explainability_floor", 0.55))
        and timing_alignment_score >= float(gravity_config.get("timing_alignment_floor", 0.42))
        and not hidden_risk_flag
        and not launch_state.startswith("BLOCKED_")
        and (
            blocker_interaction >= 0.5
            or launch_state in {"REVIEW_READY", "ACTIVE_VALIDATED_POSITION"}
        )
        and spectrum_class not in {"narrative", "anomaly"}
    )
    if gravity_pass:
        gravity_failure_reasons = []
        gravity_mode_state = "SURVIVED"
    elif not deprivation_pass:
        gravity_mode_state = "SUPPRESSED"
    elif launch_state.startswith("BLOCKED_"):
        gravity_mode_state = "FAILED_BLOCKED"
    elif hidden_risk_flag:
        gravity_mode_state = "FAILED_HIDDEN_RISK"
    elif spectrum_class in {"narrative", "anomaly"}:
        gravity_mode_state = "FAILED_STRUCTURAL"
    else:
        gravity_mode_state = "FAILED_CONSTRAINT"

    if not deprivation_pass:
        perception_control_state = "SUPPRESSED"
    elif gravity_pass:
        perception_control_state = "SURVIVED_CONSTRAINT"
    elif resurfacing_candidate:
        perception_control_state = "AMPLIFIED_UNDER_CONSTRAINT"
    else:
        perception_control_state = "FILTERED_VISIBLE"

    visibility_state = "SUPPRESSED"
    if deprivation_pass and not resurfacing_candidate:
        visibility_state = "VISIBLE"
    if resurfacing_candidate:
        visibility_state = "RESURFACED"
    if gravity_pass:
        visibility_state = "PRIORITY_VISIBLE"

    noise_classification = _noise_classification(
        signal_row,
        deprivation_pass=deprivation_pass,
        timing_alignment_score=timing_alignment_score,
        readiness_compatibility=readiness,
        asset_attachment=asset_attachment,
    )
    action_visibility_priority = _clamp(
        (0.58 * survival_score)
        + (0.42 * resurfacing_priority)
        + (0.05 if gravity_pass else -0.05)
    )
    suppression_weight = _clamp(
        1.0 - deprivation_score + (0.12 if not deprivation_pass else 0.0)
    )
    prior_state_bias = _clamp((0.65 * readiness) + (0.35 * persistence_score))
    evidence_strength = _clamp(
        (0.45 * confidence)
        + (0.35 * timing_alignment_score)
        + (0.20 * source_quality)
    )
    prior_bias_gap = prior_state_bias - evidence_strength

    return {
        "signal_id": _text(signal_row.get("signal_id")),
        "ticker": _text(signal_row.get("ticker")).upper(),
        "status": _text(signal_row.get("status")).upper(),
        "blocker_attribution": _text(signal_row.get("blocker_attribution"), "NONE").upper(),
        "watchlist_tier": _text(signal_row.get("watchlist_tier"), "NONE").upper(),
        "pre_entry_state": _text(signal_row.get("pre_entry_state"), "NONE").upper(),
        "launch_state": launch_state,
        "validation_state": validation_state,
        "ce_score": _safe_round(_coerce_float(signal_row.get("ce_score")), 3),
        "priority_score": _safe_round(_coerce_float(signal_row.get("priority_score")), 3),
        "deprivation_pass": deprivation_pass,
        "deprivation_reason_codes": deprivation_reason_codes,
        "suppression_weight": round(suppression_weight, 3),
        "visibility_state": visibility_state,
        "noise_classification": noise_classification,
        "signal_lux": round(signal_lux, 3),
        "spectrum_class": spectrum_class,
        "resurfacing_priority": round(resurfacing_priority, 3),
        "timing_alignment_score": round(timing_alignment_score, 3),
        "injection_reason_codes": injection_reason_codes,
        "gravity_pass": gravity_pass,
        "gravity_failure_reasons": gravity_failure_reasons,
        "survival_score": round(survival_score, 3),
        "gravity_mode_state": gravity_mode_state,
        "perception_control_state": perception_control_state,
        "action_visibility_priority": round(action_visibility_priority, 3),
        "exposure_timing_state": exposure_timing_state,
        "resurfacing_candidate": resurfacing_candidate,
        "persistence_count": persistence_count,
        "confidence_input": round(confidence, 3),
        "readiness_compatibility": round(readiness, 3),
        "structural_relevance": round(structural_relevance, 3),
        "asset_attachment": round(asset_attachment, 3),
        "source_quality": round(source_quality, 3),
        "blocker_interaction": round(blocker_interaction, 3),
        "prior_state_bias": round(prior_state_bias, 3),
        "evidence_strength": round(evidence_strength, 3),
        "prior_bias_gap": round(prior_bias_gap, 3),
    }


def _gravity_pressure_state(signal_survival_rate: float | None) -> str:
    if signal_survival_rate is None:
        return "UNKNOWN"
    if signal_survival_rate < 0.4:
        return "HIGH"
    if signal_survival_rate < 0.7:
        return "MODERATE"
    return "STABLE"


def _resurfacing_load_state(resurfacing_candidate_count: int, total_signal_count: int) -> str:
    if total_signal_count <= 0:
        return "NONE"
    ratio = resurfacing_candidate_count / total_signal_count
    if ratio > 0.6:
        return "HEAVY"
    if ratio > 0.3:
        return "MODERATE"
    return "LIGHT"


def _perception_control_state(
    *,
    total_signal_count: int,
    noise_suppression_ratio: float | None,
    signal_survival_rate: float | None,
    average_signal_lux: float | None,
    resurfacing_candidate_count: int,
    gravity_rejection_count: int,
    final_candidate_count: int,
) -> str:
    if total_signal_count <= 0:
        return "FILTERED"
    if noise_suppression_ratio is not None and noise_suppression_ratio < 0.25:
        return "NOISY"
    if gravity_rejection_count >= max(2, resurfacing_candidate_count - final_candidate_count) and final_candidate_count < resurfacing_candidate_count:
        return "CONSTRAINED"
    if (
        noise_suppression_ratio is not None
        and noise_suppression_ratio >= 0.65
        and final_candidate_count <= 1
    ):
        return "FILTERED"
    if (
        signal_survival_rate is not None
        and signal_survival_rate >= 0.75
        and average_signal_lux is not None
        and average_signal_lux >= 0.62
        and 0.3 <= (noise_suppression_ratio or 0.0) <= 0.7
    ):
        return "BALANCED"
    if average_signal_lux is not None and average_signal_lux >= 0.68:
        return "AMPLIFIED"
    return "BALANCED"


def _bias_monitor(
    rows: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    if not rows:
        return {
            "proxy_name": "state_bias_over_evidence_gap",
            "average_bias_gap": None,
            "prior_dominant_signal_count": 0,
            "prior_dominant_ratio": None,
            "bias_state": "UNKNOWN",
            "note": (
                "Proxy compares internal state/persistence bias to current evidence strength. "
                "It is not a direct measure of model priors."
            ),
        }
    threshold = float(config["bias_proxy"].get("prior_dominance_gap_threshold", 0.08))
    gaps = [float(row.get("prior_bias_gap", 0.0)) for row in rows]
    prior_dominant_count = sum(1 for gap in gaps if gap > threshold)
    ratio = prior_dominant_count / len(rows)
    if ratio >= 0.5:
        bias_state = "PRIOR_HEAVY"
    elif ratio >= 0.25:
        bias_state = "MIXED"
    else:
        bias_state = "EVIDENCE_LED"
    return {
        "proxy_name": "state_bias_over_evidence_gap",
        "average_bias_gap": _safe_round(_mean(gaps), 3),
        "prior_dominant_signal_count": prior_dominant_count,
        "prior_dominant_ratio": _safe_round(ratio, 3),
        "bias_state": bias_state,
        "note": (
            "Proxy compares internal state/persistence bias to current evidence strength. "
            "It is not a direct measure of model priors."
        ),
    }


def _advisories(
    *,
    noise_suppression_ratio: float | None,
    signal_survival_rate: float | None,
    resurfacing_candidate_count: int,
    gravity_rejection_count: int,
    final_candidate_count: int,
    bias_state: str,
) -> list[str]:
    advisories: list[str] = []
    if noise_suppression_ratio is not None and noise_suppression_ratio < 0.25:
        advisories.append(
            "INPUT OVEREXPOSURE - deprivation filter suppressing insufficiently"
        )
    if (
        resurfacing_candidate_count > 0
        and gravity_rejection_count > 0
        and signal_survival_rate is not None
        and signal_survival_rate < 0.55
    ):
        advisories.append(
            "AMPLIFICATION WITHOUT SURVIVAL - injected signals failing gravity"
        )
    if (
        noise_suppression_ratio is not None
        and noise_suppression_ratio >= 0.65
        and final_candidate_count <= 1
    ):
        advisories.append(
            "HIGH SUPPRESSION / LOW ACTIONABILITY - possible over-filtering"
        )
    if bias_state == "PRIOR_HEAVY":
        advisories.append(
            "RESIDUAL BIAS PRESSURE - state priors outweighing current evidence proxy"
        )
    if not advisories and final_candidate_count > 0:
        advisories.append(
            "BALANCED PERCEPTION CONTROL - strong survivors feeding action engine"
        )
    return advisories


def build_perception_control_report(
    runtime_state: dict[str, Any],
    signal_refinery_report: dict[str, Any] | None = None,
    trend_report: dict[str, Any] | None = None,
    config_path: Path | None = None,
    output_path: Path | None = None,
    write_runtime: bool = False,
) -> dict[str, Any]:
    config = load_perception_control_config(config_path)
    state = runtime_state if isinstance(runtime_state, dict) else {}
    rows = state.get("per_signal_attribution", [])
    if not isinstance(rows, list):
        rows = []
    validation_by_key = _validation_rows_by_ticker(signal_refinery_report)
    launch_by_ticker = _launch_rows_by_ticker(signal_refinery_report)
    persistence_map = _persistence_by_ticker(trend_report)
    generated_at = datetime.now(timezone.utc)

    perception_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = _text(row.get("ticker")).upper()
        signal_id = _text(row.get("signal_id"))
        validation_row = validation_by_key.get(signal_id) or validation_by_key.get(ticker)
        launch_row = launch_by_ticker.get(ticker)
        persistence_count = max(
            persistence_map.get(ticker, 0),
            _coerce_int((validation_row or {}).get("persistence_count"), 0),
        )
        perception_rows.append(
            _perception_row(
                row,
                validation_row=validation_row,
                launch_row=launch_row,
                persistence_count=persistence_count,
                config=config,
            )
        )

    perception_rows.sort(
        key=lambda item: (-float(item.get("action_visibility_priority", 0.0)), item["ticker"])
    )
    total_signal_count = len(perception_rows)
    deprivation_survivors = [row for row in perception_rows if row["deprivation_pass"]]
    injected_rows = [row for row in deprivation_survivors if row["resurfacing_candidate"]]
    gravity_survivors = [row for row in perception_rows if row["gravity_pass"]]
    noise_suppression_ratio = (
        (total_signal_count - len(deprivation_survivors)) / total_signal_count
        if total_signal_count
        else None
    )
    signal_survival_rate = (
        len(gravity_survivors) / len(deprivation_survivors)
        if deprivation_survivors
        else None
    )
    signal_lux_values = [float(row["signal_lux"]) for row in deprivation_survivors]
    average_signal_lux = _mean(signal_lux_values)
    median_signal_lux = _median(signal_lux_values)
    gravity_rejection_count = max(0, len(deprivation_survivors) - len(gravity_survivors))
    spectrum_counter = Counter(row["spectrum_class"] for row in perception_rows if row.get("spectrum_class"))
    dominant_spectrum_class = (
        max(spectrum_counter.items(), key=lambda item: (item[1], item[0]))[0]
        if spectrum_counter
        else "unknown"
    )
    final_candidates = [
        {
            "signal_id": row["signal_id"],
            "ticker": row["ticker"],
            "status": row["status"],
            "pre_entry_state": row["pre_entry_state"],
            "launch_state": row["launch_state"],
            "perception_control_state": row["perception_control_state"],
            "signal_lux": row["signal_lux"],
            "survival_score": row["survival_score"],
            "gravity_pass": row["gravity_pass"],
            "action_visibility_priority": row["action_visibility_priority"],
            "spectrum_class": row["spectrum_class"],
            "exposure_timing_state": row["exposure_timing_state"],
        }
        for row in gravity_survivors
    ]
    bias_monitor = _bias_monitor(gravity_survivors or deprivation_survivors, config)
    advisories = _advisories(
        noise_suppression_ratio=noise_suppression_ratio,
        signal_survival_rate=signal_survival_rate,
        resurfacing_candidate_count=len(injected_rows),
        gravity_rejection_count=gravity_rejection_count,
        final_candidate_count=len(final_candidates),
        bias_state=_text(bias_monitor.get("bias_state"), "UNKNOWN"),
    )
    perception_control_state = _perception_control_state(
        total_signal_count=total_signal_count,
        noise_suppression_ratio=noise_suppression_ratio,
        signal_survival_rate=signal_survival_rate,
        average_signal_lux=average_signal_lux,
        resurfacing_candidate_count=len(injected_rows),
        gravity_rejection_count=gravity_rejection_count,
        final_candidate_count=len(final_candidates),
    )

    report = {
        "artifact_kind": "perception_control_report",
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "source_mode": get_source_mode(),
        "config_path": repo_relative(config_path or PERCEPTION_CONTROL_CONFIG_PATH),
        "perception_control_state": perception_control_state,
        "noise_suppression_ratio": _safe_round(noise_suppression_ratio, 3),
        "signal_survival_rate": _safe_round(signal_survival_rate, 3),
        "average_signal_lux": _safe_round(average_signal_lux, 3),
        "median_signal_lux": _safe_round(median_signal_lux, 3),
        "gravity_rejection_count": gravity_rejection_count,
        "resurfacing_candidate_count": len(injected_rows),
        "deprivation_pass_count": len(deprivation_survivors),
        "gravity_pass_count": len(gravity_survivors),
        "final_candidate_count": len(final_candidates),
        "dominant_spectrum_class": dominant_spectrum_class,
        "spectrum_distribution": dict(sorted(spectrum_counter.items())),
        "gravity_pressure_state": _gravity_pressure_state(signal_survival_rate),
        "resurfacing_load_state": _resurfacing_load_state(len(injected_rows), total_signal_count),
        "residual_bias_monitor": bias_monitor,
        "advisories": advisories,
        "signals": perception_rows,
        "final_candidates": final_candidates,
        "note": (
            "Perception control suppresses low-value exposure before downstream action ranking, "
            "re-surfaces stronger signals with timing-aware lux scoring, and applies structured "
            "high-constraint evaluation before candidate promotion."
        ),
    }

    if write_runtime:
        write_json_atomic(output_path or PERCEPTION_CONTROL_REPORT_PATH, report)
    return report


def format_perception_control_summary(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Perception Control",
            f"perception_control_state={report.get('perception_control_state', 'UNKNOWN')}",
            f"noise_suppression_ratio={report.get('noise_suppression_ratio')}",
            f"signal_survival_rate={report.get('signal_survival_rate')}",
            f"average_signal_lux={report.get('average_signal_lux')}",
            f"resurfacing_candidate_count={report.get('resurfacing_candidate_count', 0)}",
            f"gravity_rejection_count={report.get('gravity_rejection_count', 0)}",
            f"dominant_spectrum_class={report.get('dominant_spectrum_class', 'unknown')}",
        ]
    )


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the perception-control layer over the current runtime state."
    )
    parser.add_argument(
        "--write-runtime",
        action="store_true",
        help="Persist runtime/perception_control_report.json.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    mode.add_argument("--summary", action="store_true", help="Emit compact human-readable summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)

    try:
        from scripts.signal_conversion_monitor import build_signal_conversion_report
        from scripts.signal_refinery import build_signal_refinery_report
    except ModuleNotFoundError:
        from signal_conversion_monitor import build_signal_conversion_report
        from signal_refinery import build_signal_refinery_report

    runtime_state = build_runtime_state_from_scm_report_payload(build_signal_conversion_report())
    signal_refinery_report = build_signal_refinery_report(
        runtime_state=runtime_state,
        write_runtime=False,
    )
    payload = build_perception_control_report(
        runtime_state=runtime_state,
        signal_refinery_report=signal_refinery_report,
        write_runtime=args.write_runtime,
    )
    if args.summary:
        print(format_perception_control_summary(payload))
    else:
        print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
