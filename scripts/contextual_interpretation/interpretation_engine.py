from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    from scripts.contextual_interpretation.context_profile import ContextProfile, build_context_profile
    from scripts.contextual_interpretation_engine import build_contextual_interpretation_report
    from scripts.contextual_interpretation.interpretation_drift import (
        InterpretationDriftReport,
        compute_interpretation_drift,
    )
    from scripts.contextual_interpretation.interpretation_failure_classifier import (
        classify_interpretation_failure,
    )
    from scripts.contextual_interpretation.operator_lens import (
        OperatorLens,
        default_operator_lenses,
    )
    from scripts.contextual_interpretation.reality_renderer import render_reality_packet
    from scripts.runtime_common import (
        CONTEXT_PROFILE_REPORT_PATH,
        CONTEXTUAL_INTERPRETATION_REPORT_PATH,
        CONTEXTUAL_INTERPRETATION_SUMMARY_PATH,
        INTERPRETATION_DRIFT_REPORT_PATH,
        INTERPRETATION_FAILURE_LOG_PATH,
        INTERPRETATION_PACKET_REPORT_PATH,
        REALITY_RENDERING_REPORT_PATH,
        append_jsonl,
        build_truth_context,
        classify_operating_mode,
        get_run_id,
        repo_relative,
        utc_timestamp,
        write_json_atomic,
    )
except ModuleNotFoundError:
    from contextual_interpretation.context_profile import ContextProfile, build_context_profile  # type: ignore[no-redef]
    from contextual_interpretation_engine import (  # type: ignore[no-redef]
        build_contextual_interpretation_report,
    )
    from contextual_interpretation.interpretation_drift import (  # type: ignore[no-redef]
        InterpretationDriftReport,
        compute_interpretation_drift,
    )
    from contextual_interpretation.interpretation_failure_classifier import (  # type: ignore[no-redef]
        classify_interpretation_failure,
    )
    from contextual_interpretation.operator_lens import (  # type: ignore[no-redef]
        OperatorLens,
        default_operator_lenses,
    )
    from contextual_interpretation.reality_renderer import render_reality_packet  # type: ignore[no-redef]
    from runtime_common import (  # type: ignore[no-redef]
        CONTEXT_PROFILE_REPORT_PATH,
        CONTEXTUAL_INTERPRETATION_REPORT_PATH,
        CONTEXTUAL_INTERPRETATION_SUMMARY_PATH,
        INTERPRETATION_DRIFT_REPORT_PATH,
        INTERPRETATION_FAILURE_LOG_PATH,
        INTERPRETATION_PACKET_REPORT_PATH,
        REALITY_RENDERING_REPORT_PATH,
        append_jsonl,
        build_truth_context,
        classify_operating_mode,
        get_run_id,
        repo_relative,
        utc_timestamp,
        write_json_atomic,
    )


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


@dataclass(frozen=True)
class LensInterpretation:
    lens_name: str
    meaning_label: str
    meaning_score: float
    confidence: float
    risk_notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InterpretationPacket:
    signal_id: str
    raw_signal: dict[str, Any]
    context_profile: ContextProfile
    lens_interpretations: list[LensInterpretation]
    selected_interpretation: str
    interpretation_confidence: float
    interpretation_drift: float
    chaos_veto: bool
    recommended_action: str
    reason_codes: list[str]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["context_profile"] = self.context_profile.to_dict()
        payload["lens_interpretations"] = [row.to_dict() for row in self.lens_interpretations]
        return payload


def _label_for_lens(
    raw_signal: dict[str, Any],
    context_profile: ContextProfile,
    lens: OperatorLens,
) -> LensInterpretation:
    price_spike = clamp01(float(raw_signal.get("price_move_intensity", raw_signal.get("initial_shock", 0.0)) or 0.0))
    narrative = clamp01(float(raw_signal.get("narrative_acceleration", raw_signal.get("novelty_score", 0.0)) or 0.0))
    validation = clamp01(float(raw_signal.get("minimum_validation", raw_signal.get("validation_score", 0.0)) or 0.0))
    liquidity_fragility = clamp01(float(raw_signal.get("liquidity_fragility", 1.0 if context_profile.liquidity == "THIN" else 0.2) or 0.0))
    momentum = clamp01(float(raw_signal.get("momentum", raw_signal.get("detection_score", 0.0)) or 0.0))
    exhaustion = clamp01(float(raw_signal.get("sentiment_divergence", raw_signal.get("crowd_saturation", 0.0)) or 0.0))

    if lens.lens_name == "Retail":
        label = "BREAKOUT" if price_spike >= 0.55 and narrative >= 0.45 else "WAIT"
        score = clamp01((price_spike + narrative + momentum) / 3.0)
        confidence = clamp01((score + validation) / 2.0)
        notes = ["Retail lens is sensitive to narrative heat."]
    elif lens.lens_name == "Institution":
        label = "LIQUIDITY_GRAB" if price_spike >= 0.55 and liquidity_fragility >= 0.45 else "ACCUMULATION"
        score = clamp01((price_spike + liquidity_fragility + validation) / 3.0)
        confidence = clamp01((score + (1.0 - narrative * 0.3)) / 1.3)
        notes = ["Institution lens discounts raw excitement without structure."]
    elif lens.lens_name == "Momentum":
        label = "CONTINUATION" if momentum >= 0.55 and validation >= 0.45 else "MOMENTUM_FADE"
        score = clamp01((momentum + price_spike + validation) / 3.0)
        confidence = clamp01((score + narrative) / 2.0)
        notes = ["Momentum lens requires follow-through."]
    elif lens.lens_name == "MarketMaker":
        label = "STOP_RUN" if price_spike >= 0.55 and context_profile.spread in {"NORMAL", "WIDE"} else "INVENTORY_REBALANCE"
        score = clamp01((price_spike + liquidity_fragility + exhaustion) / 3.0)
        confidence = clamp01((score + 0.55) / 1.55)
        notes = ["Market-maker lens reads spread and inventory stress first."]
    elif lens.lens_name == "Contrarian":
        label = "EXHAUSTION" if exhaustion >= 0.5 or narrative >= 0.65 else "VALUE_RESET"
        score = clamp01((exhaustion + (1.0 - validation * 0.4) + narrative) / 3.0)
        confidence = clamp01((score + 0.45) / 1.45)
        notes = ["Contrarian lens elevates crowding and reversal risk."]
    else:
        label = "STEALTH_ACCUMULATION" if validation >= 0.55 and liquidity_fragility <= 0.45 else "FLOW_PROBE"
        score = clamp01((validation + momentum + (1.0 - liquidity_fragility)) / 3.0)
        confidence = clamp01((score + 0.5) / 1.5)
        notes = ["Whale lens emphasizes hidden flow quality."]
    if context_profile.regime == "CHAOS":
        notes.append("CHAOS regime lowers interpretive trust.")
    return LensInterpretation(
        lens_name=lens.lens_name,
        meaning_label=label,
        meaning_score=score,
        confidence=confidence,
        risk_notes=notes,
    )


def interpret_signal(
    raw_signal: dict[str, Any],
    *,
    context_profile: ContextProfile,
    operator_lenses: list[OperatorLens] | None = None,
    drift_threshold: float = 0.35,
    runtime_state: dict[str, Any] | None = None,
) -> InterpretationPacket:
    lenses = operator_lenses or default_operator_lenses()
    lens_interpretations = [_label_for_lens(raw_signal, context_profile, lens) for lens in lenses]
    drift_report: InterpretationDriftReport = compute_interpretation_drift(
        str(raw_signal.get("signal_id") or raw_signal.get("ticker") or "UNKNOWN"),
        [row.to_dict() for row in lens_interpretations],
        drift_threshold,
    )
    composites = [
        (
            row.meaning_label,
            clamp01(row.meaning_score * 0.6 + row.confidence * 0.4),
        )
        for row in lens_interpretations
    ]
    selected_interpretation, selected_score = max(composites, key=lambda item: item[1], default=("UNKNOWN", 0.0))
    interpretation_confidence = clamp01(selected_score * (1.0 - min(0.8, drift_report.drift_score * 0.5)))

    reason_codes = ["RAW_SIGNAL_INTERPRETED"]
    policy_allowed = bool((runtime_state or {}).get("execution_policy", {}).get("allow_new_risk", False))
    if not policy_allowed:
        reason_codes.append("POLICY_RESTRICTED")
    if drift_report.drift_score > drift_threshold:
        reason_codes.append("HIGH_INTERPRETATION_DRIFT")
    elif drift_report.drift_score > drift_threshold * 0.8:
        reason_codes.append("MODERATE_INTERPRETATION_DRIFT")
    if interpretation_confidence < 0.5:
        reason_codes.append("LOW_INTERPRETATION_CONFIDENCE")
    if context_profile.regime == "CHAOS":
        reason_codes.append("REGIME_CHAOS")
    if raw_signal.get("shock_override") or raw_signal.get("pattern_shock"):
        reason_codes.append("SHOCK_RECLASSIFICATION")

    chaos_veto = bool(drift_report.chaos_veto)
    if not policy_allowed:
        recommended_action = "BLOCK"
    elif chaos_veto:
        recommended_action = "BLOCK"
    elif drift_report.drift_score > drift_threshold * 0.8:
        recommended_action = "REDUCE_SIZE"
    else:
        recommended_action = "ALLOW"

    return InterpretationPacket(
        signal_id=str(raw_signal.get("signal_id") or raw_signal.get("ticker") or "UNKNOWN"),
        raw_signal=dict(raw_signal),
        context_profile=context_profile,
        lens_interpretations=lens_interpretations,
        selected_interpretation=selected_interpretation,
        interpretation_confidence=interpretation_confidence,
        interpretation_drift=drift_report.drift_score,
        chaos_veto=chaos_veto,
        recommended_action=recommended_action,
        reason_codes=reason_codes,
        created_at=utc_timestamp(),
    )


def _merge_interpreted_signal(raw_signal: dict[str, Any], packet: InterpretationPacket) -> dict[str, Any]:
    merged = dict(raw_signal)
    merged["interpretation_packet"] = packet.to_dict()
    merged["context_profile"] = packet.context_profile.to_dict()
    merged["selected_interpretation"] = packet.selected_interpretation
    merged["interpretation_confidence"] = packet.interpretation_confidence
    merged["interpretation_drift"] = packet.interpretation_drift
    merged["chaos_veto"] = bool(merged.get("chaos_veto", False) or packet.chaos_veto)
    merged["validation_input_mode"] = "INTERPRETED_PAYLOAD"
    return merged


def build_contextual_interpretation_summary(
    signals: list[dict[str, Any]],
    *,
    runtime_state: dict[str, Any] | None = None,
    drift_threshold: float = 0.35,
    render_operator_mode: str = "validate",
    write_runtime: bool = True,
    artifact_paths: dict[str, Path] | None = None,
) -> dict[str, Any]:
    state = runtime_state if isinstance(runtime_state, dict) else {}
    truths = build_truth_context(state)
    path_map = {
        "context_profile": CONTEXT_PROFILE_REPORT_PATH,
        "meaning_report": CONTEXTUAL_INTERPRETATION_REPORT_PATH,
        "interpretation_packet": INTERPRETATION_PACKET_REPORT_PATH,
        "interpretation_drift": INTERPRETATION_DRIFT_REPORT_PATH,
        "reality_rendering": REALITY_RENDERING_REPORT_PATH,
        "failure_log": INTERPRETATION_FAILURE_LOG_PATH,
        "summary": CONTEXTUAL_INTERPRETATION_SUMMARY_PATH,
    }
    if artifact_paths:
        path_map.update(artifact_paths)

    profiles = [build_context_profile(signal, state) for signal in signals]
    packets = [
        interpret_signal(
            signal,
            context_profile=profile,
            drift_threshold=drift_threshold,
            runtime_state=state,
        )
        for signal, profile in zip(signals, profiles)
    ]
    failures = [classify_interpretation_failure(packet.to_dict()).to_dict() for packet in packets]
    render_rows = [
        render_reality_packet(packet.to_dict(), mode=render_operator_mode, failure_record=failure).to_dict()
        for packet, failure in zip(packets, failures)
    ]
    interpreted_signals = [_merge_interpreted_signal(signal, packet) for signal, packet in zip(signals, packets)]
    meaning_report = build_contextual_interpretation_report(
        signals,
        runtime_state=state,
        write_runtime=False,
        artifact_path=path_map["meaning_report"],
    )

    action_counts = Counter(packet.recommended_action for packet in packets)
    reason_counts = Counter(reason for packet in packets for reason in packet.reason_codes)
    avg_drift = sum(packet.interpretation_drift for packet in packets) / max(1, len(packets))
    avg_confidence = sum(packet.interpretation_confidence for packet in packets) / max(1, len(packets))

    summary = {
        "run_id": get_run_id(),
        "generated_at": utc_timestamp(),
        "module": "contextual_interpretation",
        "schema_version": "1.0",
        "enabled": True,
        "drift_threshold": drift_threshold,
        "render_operator_mode": render_operator_mode,
        "total_signals": len(signals),
        "context_profiles": [profile.to_dict() for profile in profiles],
        "interpretation_packets": [packet.to_dict() for packet in packets],
        "interpreted_signals": interpreted_signals,
        "rendered_reality_packets": render_rows,
        "validation_input_mode": "INTERPRETED_PAYLOAD",
        "selected_interpretation_distribution": dict(
            Counter(packet.selected_interpretation for packet in packets)
        ),
        "recommended_action_counts": dict(action_counts),
        "reason_code_counts": dict(reason_counts),
        "chaos_veto_count": sum(1 for packet in packets if packet.chaos_veto),
        "block_count": action_counts.get("BLOCK", 0),
        "reduce_size_count": action_counts.get("REDUCE_SIZE", 0),
        "allow_count": action_counts.get("ALLOW", 0),
        "average_interpretation_drift": avg_drift,
        "average_interpretation_confidence": avg_confidence,
        "contextual_meaning_type": meaning_report.get("contextual_meaning_type", "UNKNOWN"),
        "contextual_meaning_confidence": meaning_report.get("contextual_meaning_confidence", 0.0),
        "contextual_latent_capability_state": meaning_report.get(
            "contextual_latent_capability_state",
            "UNOBSERVED",
        ),
        "contextual_recommended_action": meaning_report.get(
            "contextual_recommended_action",
            "HOLD_FOR_REPEATABILITY",
        ),
        "contextual_bull_state": meaning_report.get("contextual_bull_state", "MIURA"),
        "contextual_main_guardrail": meaning_report.get("contextual_main_guardrail", "no_signals"),
        "contextual_meaning_report": meaning_report,
        "example_interpretation_packet": packets[0].to_dict() if packets else None,
        "operating_mode": classify_operating_mode(state),
        "truth_origin": truths["truth_origin"],
        "data_quality": "synthetic_or_runtime_fallback",
        "live_ready": False,
        "report_paths": {
            "context_profile": repo_relative(path_map["context_profile"]),
            "interpretation_packet": repo_relative(path_map["interpretation_packet"]),
            "interpretation_drift": repo_relative(path_map["interpretation_drift"]),
            "reality_rendering": repo_relative(path_map["reality_rendering"]),
            "meaning_report": repo_relative(path_map["meaning_report"]),
            "failure_log": repo_relative(path_map["failure_log"]),
            "summary": repo_relative(path_map["summary"]),
        },
    }

    if write_runtime:
        context_payload = {
            "run_id": summary["run_id"],
            "generated_at": summary["generated_at"],
            "module": "context_profile",
            "schema_version": "1.0",
            "inputs": {"signal_count": len(signals)},
            "scores": {"profile_count": len(profiles)},
            "state": "CONTEXT_PROFILE_READY",
            "vetoes": [],
            "recommendation": "INTERPRET_SIGNALS",
            "rationale": ["ContextProfile = local regime, liquidity, volatility, spread, and truth origin."],
            "profiles": [profile.to_dict() for profile in profiles],
            "data_quality": summary["data_quality"],
            "live_ready": False,
        }
        packet_payload = {
            "run_id": summary["run_id"],
            "generated_at": summary["generated_at"],
            "module": "interpretation_packet",
            "schema_version": "1.0",
            "inputs": {"signal_count": len(signals)},
            "scores": {"average_confidence": avg_confidence},
            "state": "INTERPRETATION_READY",
            "vetoes": ["HIGH_INTERPRETATION_DRIFT"] if summary["chaos_veto_count"] else [],
            "recommendation": "VALIDATE_INTERPRETED_SIGNALS",
            "rationale": ["Validation must operate on interpreted signals, not raw signals."],
            "packets": [packet.to_dict() for packet in packets],
            "data_quality": summary["data_quality"],
            "live_ready": False,
        }
        drift_payload = {
            "run_id": summary["run_id"],
            "generated_at": summary["generated_at"],
            "module": "interpretation_drift",
            "schema_version": "1.0",
            "inputs": {"threshold": drift_threshold},
            "scores": {"average_interpretation_drift": avg_drift},
            "state": "DIABLO_VETO" if summary["chaos_veto_count"] else "DRIFT_CONTROLLED",
            "vetoes": ["DIABLO_CHAOS_VETO"] if summary["chaos_veto_count"] else [],
            "recommendation": "BLOCK" if summary["chaos_veto_count"] else "ALLOW_OR_REDUCE_SIZE",
            "rationale": ["ChaosRisk is proportional to InterpretationDrift."],
            "drift_reports": [
                compute_interpretation_drift(packet.signal_id, [row.to_dict() for row in packet.lens_interpretations], drift_threshold).to_dict()
                for packet in packets
            ],
            "data_quality": summary["data_quality"],
            "live_ready": False,
        }
        rendering_payload = {
            "run_id": summary["run_id"],
            "generated_at": summary["generated_at"],
            "module": "reality_renderer",
            "schema_version": "1.0",
            "inputs": {"mode": render_operator_mode},
            "scores": {"average_interpretation_confidence": avg_confidence},
            "state": "RENDERED",
            "vetoes": [],
            "recommendation": "MODE_SPECIFIC_VIEW",
            "rationale": ["Same backend state should render differently by operator mode."],
            "rendered_packets": render_rows,
            "data_quality": summary["data_quality"],
            "live_ready": False,
        }
        meaning_payload = {
            "run_id": summary["run_id"],
            "generated_at": summary["generated_at"],
            "module": "contextual_interpretation_report",
            "schema_version": "1.0",
            "inputs": {"signal_count": len(signals)},
            "scores": {
                "contextual_meaning_confidence": summary["contextual_meaning_confidence"],
                "average_interpretation_confidence": avg_confidence,
            },
            "state": summary["contextual_recommended_action"],
            "vetoes": ["CHAOS_HOLD"] if summary["contextual_recommended_action"] == "CHAOS_HOLD" else [],
            "recommendation": summary["contextual_recommended_action"],
            "rationale": [
                "Raw Signal does not equal Meaning.",
                "Holding for repeatability is a healthy result, not failure.",
            ],
            "report": meaning_report,
            "data_quality": summary["data_quality"],
            "live_ready": False,
        }
        summary_payload = {
            "run_id": summary["run_id"],
            "generated_at": summary["generated_at"],
            "module": "contextual_interpretation_summary",
            "schema_version": "1.0",
            "inputs": {"signal_count": len(signals), "render_operator_mode": render_operator_mode},
            "scores": {
                "average_interpretation_drift": avg_drift,
                "average_interpretation_confidence": avg_confidence,
            },
            "state": "BLOCK" if summary["block_count"] else "ALLOW_WITH_GUARDS",
            "vetoes": ["POLICY_RESTRICTED"] if not state.get("execution_policy", {}).get("allow_new_risk", False) else [],
            "recommendation": "VALIDATE_INTERPRETED_SIGNALS",
            "rationale": ["RawSignal does not equal InterpretedSignal."],
            "summary": summary,
            "data_quality": summary["data_quality"],
            "live_ready": False,
        }
        write_json_atomic(path_map["context_profile"], context_payload, stamp=False)
        write_json_atomic(path_map["meaning_report"], meaning_payload, stamp=False)
        write_json_atomic(path_map["interpretation_packet"], packet_payload, stamp=False)
        write_json_atomic(path_map["interpretation_drift"], drift_payload, stamp=False)
        write_json_atomic(path_map["reality_rendering"], rendering_payload, stamp=False)
        write_json_atomic(path_map["summary"], summary_payload, stamp=False)
        for row in failures:
            append_jsonl(path_map["failure_log"], row, stamp=True)

    return summary
