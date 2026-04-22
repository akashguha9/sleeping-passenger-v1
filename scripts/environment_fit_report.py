from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from scripts.experience_mode_report import build_experience_mode_report
    from scripts.governance_status import build_governance_status_report
    from scripts.pipeline_health_report import build_pipeline_health_report
    from scripts.repo_operating_mode import build_operating_mode_report
    from scripts.runtime_common import (
        ENVIRONMENT_FIT_CONFIG_PATH,
        ENVIRONMENT_FIT_REPORT_PATH,
        EXPERIENCE_MODE_REPORT_PATH,
        load_current_pipeline_state,
        load_json_file,
        repo_relative,
        stamp_payload,
        write_json_atomic,
    )
except ModuleNotFoundError:
    from experience_mode_report import build_experience_mode_report
    from governance_status import build_governance_status_report
    from pipeline_health_report import build_pipeline_health_report
    from repo_operating_mode import build_operating_mode_report
    from runtime_common import (  # type: ignore
        ENVIRONMENT_FIT_CONFIG_PATH,
        ENVIRONMENT_FIT_REPORT_PATH,
        EXPERIENCE_MODE_REPORT_PATH,
        load_current_pipeline_state,
        load_json_file,
        repo_relative,
        stamp_payload,
        write_json_atomic,
    )


DEFAULT_CONFIG = {
    "schema_version": "ENVIRONMENT_FIT_CONFIG_V1",
    "feature_flags": {
        "enable_environment_fit_scorer": True,
        "enable_robustness_precision_classifier": True,
        "enable_local_signal_priority_engine": True,
        "enable_dependency_fragility_detector": True,
        "enable_over_customization_guardrail": True,
        "enable_constraint_feature_mapper": True,
        "enable_strategy_family_selector_stub": True,
        "enable_identity_utility_stub": True,
    },
    "weights": {
        "mode_truth_alignment": 0.30,
        "visibility_legibility": 0.20,
        "dependency_simplicity": 0.20,
        "resilience_honesty": 0.20,
        "local_proximity": 0.10,
    },
    "thresholds": {
        "high_fit_min": 0.75,
        "medium_fit_min": 0.55,
        "precision_ready_jet_min": 0.80,
        "premium_gap_max": 0.10,
        "fragility_elevated_min": 0.60,
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


def load_environment_fit_config(path: Path | None = None) -> dict[str, Any]:
    payload = load_json_file(path or ENVIRONMENT_FIT_CONFIG_PATH, default={})
    if not isinstance(payload, dict):
        payload = {}
    return _deep_merge(DEFAULT_CONFIG, payload)


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_float_default(value: Any, default: float) -> float:
    coerced = _coerce_float(value)
    return default if coerced is None else coerced


def _artifact_or_built(
    artifact_path: Path,
    builder,
    **builder_kwargs: Any,
) -> dict[str, Any]:
    payload = load_json_file(artifact_path, default={}) or {}
    if isinstance(payload, dict) and payload:
        return payload
    built = builder(**builder_kwargs)
    return built if isinstance(built, dict) else {}


def build_environment_fit_scorer(
    operating_mode_report: dict[str, Any],
    governance_status_report: dict[str, Any],
    experience_mode_report: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    weights = config["weights"]
    thresholds = config["thresholds"]
    trainer_metadata = experience_mode_report.get("trainer_mode_metadata", {})
    readiness = experience_mode_report.get("readiness_ladder", {})
    visibility = experience_mode_report.get("visibility_legibility_layer", {})
    utility = experience_mode_report.get("utility_resilience_layer", {})
    premium = experience_mode_report.get("premium_compression_layer", {})
    coherence_state = governance_status_report.get("controls", {}).get(
        "artifact_coherence",
        {},
    ).get("state")

    operating_mode = str(operating_mode_report.get("operating_mode") or "seeded").lower()
    truth_origin = str(operating_mode_report.get("truth_origin") or "seeded").lower()
    recommended_surface = str(
        trainer_metadata.get("recommended_surface_profile")
        or readiness.get("recommended_surface_profile")
        or "trainer"
    ).lower()
    visibility_legibility = _coerce_float_default(
        visibility.get("visibility_legibility_score"),
        0.0,
    )
    unresolved_gap_rate = _coerce_float_default(
        visibility.get("unresolved_data_gap_rate"),
        1.0,
    )
    degraded_mode_required = bool(utility.get("degraded_mode_required"))

    if operating_mode in {"seeded", "paper_prepared"} and recommended_surface == "trainer":
        mode_truth_alignment = 1.0
    elif operating_mode == "hybrid" and recommended_surface in {"trainer", "utility"}:
        mode_truth_alignment = 0.85
    else:
        mode_truth_alignment = 0.40

    if operating_mode in {"seeded", "paper_prepared"} and truth_origin == "seeded":
        dependency_simplicity = 1.0
        local_proximity = 1.0
    elif operating_mode == "hybrid":
        dependency_simplicity = 0.70
        local_proximity = 0.60
    else:
        dependency_simplicity = 0.40
        local_proximity = 0.30

    if unresolved_gap_rate > 0.0 and degraded_mode_required:
        resilience_honesty = 1.0
    elif unresolved_gap_rate <= 0.0:
        resilience_honesty = 0.80
    else:
        resilience_honesty = 0.45

    score = _clamp(
        (weights["mode_truth_alignment"] * mode_truth_alignment)
        + (weights["visibility_legibility"] * visibility_legibility)
        + (weights["dependency_simplicity"] * dependency_simplicity)
        + (weights["resilience_honesty"] * resilience_honesty)
        + (weights["local_proximity"] * local_proximity)
        - (0.05 if coherence_state == "legacy_polluted" else 0.0)
    )

    if score >= float(thresholds["high_fit_min"]):
        fit_state = "aligned"
    elif score >= float(thresholds["medium_fit_min"]):
        fit_state = "conditional"
    else:
        fit_state = "misaligned"

    reasons: list[str] = []
    if operating_mode in {"seeded", "paper_prepared"}:
        reasons.append("local_decision_shell_matches_local_first_environment")
    if recommended_surface == "trainer":
        reasons.append("respect_where_you_are_requires_trainer_surface")
    if degraded_mode_required:
        reasons.append("partial_evidence_is_explicitly_downgraded")
    if bool(premium.get("premium_surface_eligible")) is False:
        reasons.append("premium_compression_not_yet_earned")
    if coherence_state == "legacy_polluted":
        reasons.append("legacy_artifact_pollution_reduces_fit_confidence")

    return {
        "environment_fit_score": round(score, 4),
        "fit_state": fit_state,
        "respect_where_you_are_flag": recommended_surface == "trainer",
        "component_scores": {
            "mode_truth_alignment": round(mode_truth_alignment, 4),
            "visibility_legibility": round(visibility_legibility, 4),
            "dependency_simplicity": round(dependency_simplicity, 4),
            "resilience_honesty": round(resilience_honesty, 4),
            "local_proximity": round(local_proximity, 4),
        },
        "reasons": reasons,
    }


def build_robustness_precision_classifier(
    operating_mode_report: dict[str, Any],
    experience_mode_report: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    thresholds = config["thresholds"]
    readiness = experience_mode_report.get("readiness_ladder", {})
    visibility = experience_mode_report.get("visibility_legibility_layer", {})
    utility = experience_mode_report.get("utility_resilience_layer", {})
    premium = experience_mode_report.get("premium_compression_layer", {})

    operating_mode = str(operating_mode_report.get("operating_mode") or "seeded").lower()
    jet_readiness = _coerce_float_default(readiness.get("jet_readiness"), 0.0)
    unresolved_gap_rate = _coerce_float_default(
        visibility.get("unresolved_data_gap_rate"),
        1.0,
    )
    degraded_mode_required = bool(utility.get("degraded_mode_required"))
    precision_ready = (
        jet_readiness >= float(thresholds["precision_ready_jet_min"])
        and bool(premium.get("premium_surface_eligible"))
        and unresolved_gap_rate <= float(thresholds["premium_gap_max"])
        and operating_mode in {"hybrid", "live_prepared"}
    )

    if degraded_mode_required or unresolved_gap_rate > float(thresholds["premium_gap_max"]):
        classification = "robustness_first"
    elif precision_ready:
        classification = "precision_suitable"
    else:
        classification = "balanced_transition"

    reasons = []
    if classification == "robustness_first":
        reasons.append("current_environment_has_partial_evidence_or_gap_pressure")
    if classification == "precision_suitable":
        reasons.append("precision_surface_supported_by_low_gap_and_high_readiness")
    if classification == "balanced_transition":
        reasons.append("neither_full_precision_nor_heavy_degradation_dominates")

    return {
        "classification": classification,
        "precision_ready": precision_ready,
        "degraded_mode_required": degraded_mode_required,
        "reasons": reasons,
    }


def build_local_signal_priority_engine(
    operating_mode_report: dict[str, Any],
) -> dict[str, Any]:
    operating_mode = str(operating_mode_report.get("operating_mode") or "seeded").lower()
    truth_origin = str(operating_mode_report.get("truth_origin") or "seeded").lower()

    if operating_mode in {"seeded", "paper_prepared"} and truth_origin == "seeded":
        state = "local_primary"
        score = 1.0
        reasons = [
            "local_file_driven_pipeline_has_short_information_chain",
            "local_runtime_truth_is_primary",
        ]
    elif operating_mode == "hybrid":
        state = "local_with_external_overlay"
        score = 0.65
        reasons = [
            "external_observation_exists_but_local_shell_still_shapes_decisions",
        ]
    else:
        state = "mixed"
        score = 0.35
        reasons = ["local_priority_is_no_longer_dominant"]

    return {
        "local_signal_priority_state": state,
        "local_signal_priority_score": round(score, 4),
        "reasons": reasons,
    }


def build_dependency_fragility_detector(
    operating_mode_report: dict[str, Any],
    governance_status_report: dict[str, Any],
    experience_mode_report: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    thresholds = config["thresholds"]
    visibility = experience_mode_report.get("visibility_legibility_layer", {})
    coherence_state = governance_status_report.get("controls", {}).get(
        "artifact_coherence",
        {},
    ).get("state")
    operating_mode = str(operating_mode_report.get("operating_mode") or "seeded").lower()

    unresolved_gap_rate = _coerce_float_default(
        visibility.get("unresolved_data_gap_rate"),
        1.0,
    )
    missing_mark_frequency = _coerce_float_default(
        visibility.get("missing_mark_frequency"),
        0.0,
    )
    legacy_penalty = 1.0 if coherence_state == "legacy_polluted" else 0.0

    if operating_mode in {"seeded", "paper_prepared"}:
        short_chain_advantage_score = 1.0
    elif operating_mode == "hybrid":
        short_chain_advantage_score = 0.65
    else:
        short_chain_advantage_score = 0.40

    dependency_fragility_score = _clamp(
        (0.45 * unresolved_gap_rate)
        + (0.30 * missing_mark_frequency)
        + (0.25 * legacy_penalty)
    )
    if dependency_fragility_score >= float(thresholds["fragility_elevated_min"]):
        fragility_state = "elevated"
    elif dependency_fragility_score >= 0.30:
        fragility_state = "watch"
    else:
        fragility_state = "contained"

    reasons = []
    if short_chain_advantage_score >= 1.0:
        reasons.append("short_local_chain_reduces_operational_dependency_load")
    if unresolved_gap_rate > 0.0:
        reasons.append("unresolved_reconciliation_gaps_raise_fragility")
    if coherence_state == "legacy_polluted":
        reasons.append("legacy_artifact_pollution_adds_structural_fragility")

    return {
        "short_chain_advantage_score": round(short_chain_advantage_score, 4),
        "dependency_fragility_score": round(dependency_fragility_score, 4),
        "dependency_fragility_state": fragility_state,
        "reasons": reasons,
    }


def build_over_customization_guardrail(
    operating_mode_report: dict[str, Any],
    experience_mode_report: dict[str, Any],
) -> dict[str, Any]:
    operating_mode = str(operating_mode_report.get("operating_mode") or "seeded").lower()
    readiness = experience_mode_report.get("readiness_ladder", {})
    trainer_metadata = experience_mode_report.get("trainer_mode_metadata", {})
    recommended_surface = str(
        trainer_metadata.get("recommended_surface_profile")
        or readiness.get("recommended_surface_profile")
        or "trainer"
    ).lower()
    jet_readiness = _coerce_float_default(readiness.get("jet_readiness"), 0.0)

    if operating_mode in {"seeded", "paper_prepared"} and recommended_surface != "trainer":
        state = "elevated"
        reasons = ["surface_complexity_is_outpacing_environment_truth"]
    elif recommended_surface == "jet" and jet_readiness < 0.80:
        state = "elevated"
        reasons = ["premium_surface_requested_without_earned_readiness"]
    else:
        state = "low"
        reasons = ["active_runtime_spine_should_receive_additive_not_casual_refactors"]

    return {
        "casual_modification_risk_state": state,
        "recommended_change_style": "additive_extensions_only",
        "reasons": reasons,
    }


def build_constraint_to_feature_mapper(
    operating_mode_report: dict[str, Any],
    experience_mode_report: dict[str, Any],
) -> dict[str, Any]:
    utility = experience_mode_report.get("utility_resilience_layer", {})
    mappings = [
        {
            "constraint": "seeded_local_runtime",
            "feature": "deterministic_lineage_and_mode_honesty",
            "state": operating_mode_report.get("operating_mode"),
        },
        {
            "constraint": "paper_only_execution",
            "feature": "human_review_and_reconciliation_discipline",
            "state": "active",
        },
    ]
    if bool(utility.get("degraded_mode_required")):
        mappings.append(
            {
                "constraint": "partial_evidence",
                "feature": "explicit_confidence_downgrade_and_fallback_reporting",
                "state": "active",
            }
        )
    return {
        "state": "advisory_mapping",
        "mappings": mappings,
    }


def build_strategy_family_selector(
    experience_mode_report: dict[str, Any],
) -> dict[str, Any]:
    readiness = experience_mode_report.get("readiness_ladder", {})
    selected = str(readiness.get("recommended_surface_profile") or "trainer").lower()
    return {
        "state": "advisory_selector",
        "available_families": ["trainer", "utility", "jet"],
        "selected_family": selected,
        "selection_basis": {
            "trainer_readiness": readiness.get("trainer_readiness"),
            "utility_readiness": readiness.get("utility_readiness"),
            "jet_readiness": readiness.get("jet_readiness"),
        },
    }


def build_identity_utility_stub() -> dict[str, Any]:
    return {
        "state": "concept_only",
        "performance_utility_state": "measurable_via_existing_reconciliation_and_governance",
        "identity_utility_state": "unmeasured",
        "note": (
            "The repo does not yet capture operator preference or identity telemetry. "
            "Identity utility remains conceptual until human-review data is recorded."
        ),
    }


def build_environment_fit_report(
    runtime_state: dict[str, Any] | None = None,
    operating_mode_report: dict[str, Any] | None = None,
    governance_status_report: dict[str, Any] | None = None,
    health_report: dict[str, Any] | None = None,
    experience_mode_report: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
    output_path: Path | None = None,
    write_runtime: bool = True,
) -> dict[str, Any]:
    state = runtime_state or load_current_pipeline_state()
    active_config = config or load_environment_fit_config()
    operating = operating_mode_report or build_operating_mode_report(runtime_state=state)
    governance = governance_status_report or build_governance_status_report()
    health = health_report or build_pipeline_health_report(
        include_tests=False,
        write_runtime=False,
        runtime_state=state,
    )
    experience = experience_mode_report or _artifact_or_built(
        EXPERIENCE_MODE_REPORT_PATH,
        build_experience_mode_report,
        runtime_state=state,
        health_report=health,
        governance_status_report=governance,
        write_runtime=False,
    )

    report = stamp_payload(
        {
            "artifact_kind": "environment_fit_report",
            "feature_flags": active_config.get("feature_flags", {}),
            "environment_fit_scorer": build_environment_fit_scorer(
                operating_mode_report=operating,
                governance_status_report=governance,
                experience_mode_report=experience,
                config=active_config,
            ),
            "robustness_precision_classifier": build_robustness_precision_classifier(
                operating_mode_report=operating,
                experience_mode_report=experience,
                config=active_config,
            ),
            "local_signal_priority_engine": build_local_signal_priority_engine(
                operating_mode_report=operating,
            ),
            "dependency_fragility_detector": build_dependency_fragility_detector(
                operating_mode_report=operating,
                governance_status_report=governance,
                experience_mode_report=experience,
                config=active_config,
            ),
            "over_customization_guardrail": build_over_customization_guardrail(
                operating_mode_report=operating,
                experience_mode_report=experience,
            ),
            "constraint_to_feature_mapper": build_constraint_to_feature_mapper(
                operating_mode_report=operating,
                experience_mode_report=experience,
            ),
            "strategy_family_selector": build_strategy_family_selector(experience),
            "identity_utility_layer": build_identity_utility_stub(),
            "source_artifacts": {
                "operating_mode_report": "runtime-derived",
                "governance_status_report": "runtime/governance_status.py",
                "pipeline_health_report": repo_relative(Path("runtime") / "pipeline_health_report.json"),
                "experience_mode_report": repo_relative(EXPERIENCE_MODE_REPORT_PATH),
            },
            "note": (
                "This report is advisory-only. It maps environment fit, robustness-vs-precision, "
                "locality, dependency fragility, and anti-overcustomization guardrails onto the "
                "current MVP without changing trading behavior."
            ),
        },
        runtime_state=state,
    )
    if write_runtime:
        write_json_atomic(output_path or ENVIRONMENT_FIT_REPORT_PATH, report, stamp=False)
    return report


def format_environment_fit_summary(report: dict[str, Any]) -> str:
    fit = report.get("environment_fit_scorer", {})
    robustness = report.get("robustness_precision_classifier", {})
    locality = report.get("local_signal_priority_engine", {})
    fragility = report.get("dependency_fragility_detector", {})
    guardrail = report.get("over_customization_guardrail", {})
    return "\n".join(
        [
            "Environment Fit Report",
            f"environment_fit_score={fit.get('environment_fit_score')}",
            f"fit_state={fit.get('fit_state')}",
            f"robustness_precision_classification={robustness.get('classification')}",
            f"local_signal_priority_state={locality.get('local_signal_priority_state')}",
            f"dependency_fragility_state={fragility.get('dependency_fragility_state')}",
            f"modification_guardrail_state={guardrail.get('casual_modification_risk_state')}",
        ]
    )


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Summarize environment fit, robustness-vs-precision posture, locality, and "
            "anti-overcustomization guardrails for the current MVP runtime."
        )
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--summary", action="store_true", help="Emit a compact human-readable summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    report = build_environment_fit_report(write_runtime=True)
    if args.summary:
        print(format_environment_fit_summary(report))
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
