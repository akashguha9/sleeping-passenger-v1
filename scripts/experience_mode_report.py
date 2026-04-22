from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from scripts.governance_feedback_report import build_governance_feedback_report
    from scripts.governance_status import build_governance_status_report
    from scripts.pipeline_health_report import build_pipeline_health_report
    from scripts.repo_operating_mode import build_operating_mode_report
    from scripts.runtime_common import (
        EXPERIENCE_MODE_CONFIG_PATH,
        EXPERIENCE_MODE_REPORT_PATH,
        PAPER_RECONCILIATION_HISTORY_PATH,
        PAPER_RECONCILIATION_SUMMARY_PATH,
        load_current_pipeline_state,
        load_json_file,
        repo_relative,
        stamp_payload,
        write_json_atomic,
    )
except ModuleNotFoundError:
    from governance_feedback_report import build_governance_feedback_report
    from governance_status import build_governance_status_report
    from pipeline_health_report import build_pipeline_health_report
    from repo_operating_mode import build_operating_mode_report
    from runtime_common import (
        EXPERIENCE_MODE_CONFIG_PATH,
        EXPERIENCE_MODE_REPORT_PATH,
        PAPER_RECONCILIATION_HISTORY_PATH,
        PAPER_RECONCILIATION_SUMMARY_PATH,
        load_current_pipeline_state,
        load_json_file,
        repo_relative,
        stamp_payload,
        write_json_atomic,
    )


DEFAULT_CONFIG: dict[str, Any] = {
    "feature_flags": {
        "enable_trainer_mode_metadata": True,
        "enable_visibility_legibility_layer": True,
        "enable_readiness_scaffold": True,
        "enable_utility_resilience_flags": True,
        "enable_premium_compression_placeholders": True,
        "enable_design_dna_stub": True,
    },
    "trainer_mode": {
        "force_recommendation_for_seeded": True,
        "force_recommendation_for_paper_prepared": True,
    },
    "readiness": {
        "feedback_density_target": 20,
        "utility_unresolved_gap_max": 0.25,
        "jet_unresolved_gap_max": 0.10,
        "trainer_ready_min": 0.55,
        "utility_ready_min": 0.60,
        "jet_ready_min": 0.80,
    },
}

EVIDENCE_STRENGTH_SCORES = {
    "insufficient_evidence": 0.2,
    "weak_signal": 0.4,
    "early_pattern": 0.6,
    "moderate_pattern": 0.8,
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_experience_mode_config(path: Path | None = None) -> dict[str, Any]:
    payload = load_json_file(path or EXPERIENCE_MODE_CONFIG_PATH, default={})
    if not isinstance(payload, dict):
        payload = {}
    return _deep_merge(DEFAULT_CONFIG, payload)


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def _coerce_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _truth_context_score(governance_status_report: dict[str, Any]) -> float:
    controls = governance_status_report.get("controls", {})
    coherence_state = str(
        controls.get("artifact_coherence", {}).get("state") or "incoherent"
    ).lower()
    provenance_state = str(controls.get("provenance", {}).get("state") or "partial").lower()
    score = 0.0
    if coherence_state == "coherent":
        score += 1.0
    elif coherence_state == "legacy_polluted":
        score += 0.5
    if provenance_state == "basic":
        score += 1.0
    elif provenance_state == "partial":
        score += 0.5
    return round(_clamp(score / 2.0), 4)


def build_visibility_legibility_layer(
    health_report: dict[str, Any],
    governance_status_report: dict[str, Any],
    reconciliation_summary: dict[str, Any],
    reconciliation_history_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    visibility = health_report.get("visibility_timing_context", {})
    avg_lineage = None
    lineage_values = [
        float(row["lineage_completeness_score"])
        for row in reconciliation_history_rows
        if _coerce_float(row.get("lineage_completeness_score")) is not None
    ]
    if lineage_values:
        avg_lineage = round(sum(lineage_values) / len(lineage_values), 4)
    unresolved_gap_rate = _coerce_float(reconciliation_summary.get("unresolved_data_gap_rate"))
    missing_mark_frequency = _coerce_float(
        reconciliation_summary.get("leakage_diagnostics", {}).get("missing_mark_frequency")
    )
    truth_context_score = _truth_context_score(governance_status_report)
    full_context_coverage = _coerce_float(visibility.get("full_context_coverage_ratio"))
    visibility_legibility_score = round(
        _clamp(
            (
                (0.30 * (full_context_coverage or 0.0))
                + (0.30 * truth_context_score)
                + (0.20 * (avg_lineage or 0.0))
                + (0.20 * (1.0 - (unresolved_gap_rate or 1.0)))
            )
        ),
        4,
    )
    return {
        "average_light_score": visibility.get("average_light_score"),
        "average_shadow_score": visibility.get("average_shadow_score"),
        "average_temporal_position": visibility.get("average_temporal_position"),
        "phase_distribution": visibility.get("phase_distribution", {}),
        "full_context_coverage_ratio": full_context_coverage,
        "context_scored_count": visibility.get("context_scored_count"),
        "trap_flag_rate": visibility.get("trap_flag_rate"),
        "average_lineage_completeness_score": avg_lineage,
        "unresolved_data_gap_rate": unresolved_gap_rate,
        "missing_mark_frequency": missing_mark_frequency,
        "artifact_coherence_state": governance_status_report.get("controls", {})
        .get("artifact_coherence", {})
        .get("state"),
        "provenance_state": governance_status_report.get("controls", {})
        .get("provenance", {})
        .get("state"),
        "visibility_legibility_score": visibility_legibility_score,
    }


def build_readiness_ladder(
    operating_mode_report: dict[str, Any],
    governance_feedback_report: dict[str, Any],
    visibility_legibility_layer: dict[str, Any],
    reconciliation_summary: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    readiness = config["readiness"]
    lineage_completeness = _coerce_float(
        visibility_legibility_layer.get("average_lineage_completeness_score")
    ) or 0.0
    evidence_strength = EVIDENCE_STRENGTH_SCORES.get(
        str(reconciliation_summary.get("evidence_strength") or "insufficient_evidence"),
        0.2,
    )
    reconciliation_stability = 1.0 - (
        _coerce_float(reconciliation_summary.get("unresolved_data_gap_rate")) or 1.0
    )
    feedback_density = _clamp(
        (float(reconciliation_summary.get("sample_size_for_learning") or 0.0))
        / float(readiness["feedback_density_target"])
    )
    degraded_mode_survival = round(
        _clamp(
            0.5 * reconciliation_stability
            + 0.5
            * (
                1.0
                - (
                    _coerce_float(
                        reconciliation_summary.get("leakage_diagnostics", {}).get(
                            "missing_mark_frequency"
                        )
                    )
                    or 0.0
                )
            )
        ),
        4,
    )
    execution_discipline = _coerce_float(
        governance_feedback_report.get("gate_usage", {}).get("average_fpeg_score")
    ) or 0.0
    operator_usage_maturity = round(
        _clamp(
            0.5
            * (
                _coerce_float(
                    governance_feedback_report.get("interaction_quality_summary", {}).get(
                        "average_score"
                    )
                )
                or 0.0
            )
            + 0.5 * feedback_density
        ),
        4,
    )
    visibility_legibility = _coerce_float(
        visibility_legibility_layer.get("visibility_legibility_score")
    ) or 0.0
    truthfulness_guardrails = 1.0 if operating_mode_report.get("live_execution_enabled") is False else 0.0

    trainer_readiness = round(
        _clamp(
            (0.30 * visibility_legibility)
            + (0.25 * execution_discipline)
            + (0.20 * truthfulness_guardrails)
            + (0.15 * degraded_mode_survival)
            + (0.10 * feedback_density)
        ),
        4,
    )
    utility_readiness = round(
        _clamp(
            (0.25 * lineage_completeness)
            + (0.20 * degraded_mode_survival)
            + (0.20 * reconciliation_stability)
            + (0.15 * evidence_strength)
            + (0.10 * execution_discipline)
            + (0.10 * feedback_density)
        ),
        4,
    )
    jet_readiness = round(
        _clamp(
            (0.25 * evidence_strength)
            + (0.20 * reconciliation_stability)
            + (0.15 * lineage_completeness)
            + (0.15 * execution_discipline)
            + (0.15 * operator_usage_maturity)
            + (0.10 * feedback_density)
        ),
        4,
    )

    operating_mode = str(operating_mode_report.get("operating_mode") or "")
    if (
        readiness.get("trainer_ready_min") is not None
        and config["trainer_mode"].get("force_recommendation_for_seeded")
        and operating_mode == "seeded"
    ):
        recommended_surface_profile = "trainer"
    elif (
        config["trainer_mode"].get("force_recommendation_for_paper_prepared")
        and operating_mode == "paper_prepared"
    ):
        recommended_surface_profile = "trainer"
    elif jet_readiness >= float(readiness["jet_ready_min"]):
        recommended_surface_profile = "jet"
    elif utility_readiness >= float(readiness["utility_ready_min"]):
        recommended_surface_profile = "utility"
    else:
        recommended_surface_profile = "trainer"

    return {
        "dimensions": {
            "lineage_completeness": round(lineage_completeness, 4),
            "evidence_strength": round(evidence_strength, 4),
            "reconciliation_stability": round(reconciliation_stability, 4),
            "feedback_density": round(feedback_density, 4),
            "degraded_mode_survival": degraded_mode_survival,
            "execution_discipline": round(execution_discipline, 4),
            "operator_usage_maturity": operator_usage_maturity,
            "visibility_legibility": round(visibility_legibility, 4),
        },
        "trainer_readiness": trainer_readiness,
        "utility_readiness": utility_readiness,
        "jet_readiness": jet_readiness,
        "provisional_thresholds": readiness,
        "recommended_surface_profile": recommended_surface_profile,
        "unknowns": [
            "No dedicated operator-maturity profile exists yet.",
            "Jet readiness is provisional until reconciliation sample size and lineage quality improve.",
        ],
    }


def build_trainer_mode_metadata(
    operating_mode_report: dict[str, Any],
    readiness_ladder: dict[str, Any],
) -> dict[str, Any]:
    recommended_surface_profile = str(
        readiness_ladder.get("recommended_surface_profile") or "trainer"
    )
    trainer_mode_active = recommended_surface_profile == "trainer"
    return {
        "trainer_mode_active": trainer_mode_active,
        "recommended_surface_profile": recommended_surface_profile,
        "paper_only_bias": True,
        "explanation_heavy_surface": True,
        "uncertainty_explicit": True,
        "slow_cadence_recommended": trainer_mode_active,
        "human_review_required": True,
        "mode_reason": (
            "Early-stage or seeded operation should stay trainer-simple and explanation-first."
            if trainer_mode_active
            else "Trainer mode can be relaxed only when readiness and lineage improve."
        ),
        "operating_mode": operating_mode_report.get("operating_mode"),
    }


def build_utility_resilience_layer(
    visibility_legibility_layer: dict[str, Any],
    reconciliation_summary: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    unresolved_gap_rate = _coerce_float(
        visibility_legibility_layer.get("unresolved_data_gap_rate")
    ) or 1.0
    missing_mark_frequency = _coerce_float(
        visibility_legibility_layer.get("missing_mark_frequency")
    ) or 0.0
    degraded_mode_required = unresolved_gap_rate > 0 or missing_mark_frequency > 0
    readiness = config["readiness"]
    return {
        "degraded_mode_required": degraded_mode_required,
        "partial_evidence_active": degraded_mode_required,
        "fallback_reporting_available": True,
        "confidence_downgrade_required": degraded_mode_required,
        "reconciliation_evidence_strength": reconciliation_summary.get("evidence_strength"),
        "utility_ready_by_gap_policy": unresolved_gap_rate <= float(
            readiness["utility_unresolved_gap_max"]
        ),
    }


def build_premium_compression_layer(
    readiness_ladder: dict[str, Any],
    visibility_legibility_layer: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    jet_ready = float(readiness_ladder.get("jet_readiness") or 0.0) >= float(
        config["readiness"]["jet_ready_min"]
    )
    low_gap = (_coerce_float(visibility_legibility_layer.get("unresolved_data_gap_rate")) or 1.0) <= float(
        config["readiness"]["jet_unresolved_gap_max"]
    )
    premium_surface_eligible = jet_ready and low_gap
    return {
        "premium_surface_eligible": premium_surface_eligible,
        "compression_allowed": premium_surface_eligible,
        "drilldown_required": True,
        "surface_state": "placeholder_only",
        "note": (
            "The mature MVP may feel calm and compressed on the surface, "
            "but premium compression is not eligible until lineage and reconciliation stabilize."
        ),
    }


def build_design_dna_stub() -> dict[str, Any]:
    return {
        "schema_version": "DESIGN_DNA_RUBRIC_V0",
        "dimensions": [
            "mission_fit",
            "truthfulness",
            "visibility_contribution",
            "resilience_contribution",
            "cognitive_load_impact",
            "maturity_stage_fit",
            "reversibility_auditability",
            "decorative_complexity_penalty",
        ],
        "state": "stub_only",
        "note": "First slice defines the rubric surface but does not yet score modules automatically.",
    }


def build_experience_mode_report(
    runtime_state: dict[str, Any] | None = None,
    health_report: dict[str, Any] | None = None,
    governance_status_report: dict[str, Any] | None = None,
    governance_feedback_report: dict[str, Any] | None = None,
    operating_mode_report: dict[str, Any] | None = None,
    reconciliation_summary: dict[str, Any] | None = None,
    reconciliation_history_rows: list[dict[str, Any]] | None = None,
    config: dict[str, Any] | None = None,
    output_path: Path | None = None,
    write_runtime: bool = True,
) -> dict[str, Any]:
    state = runtime_state or load_current_pipeline_state()
    active_config = config or load_experience_mode_config()
    operating = operating_mode_report or build_operating_mode_report(runtime_state=state)
    health = health_report or build_pipeline_health_report(
        include_tests=False,
        write_runtime=False,
        runtime_state=state,
    )
    governance = governance_status_report or build_governance_status_report()
    governance_feedback = governance_feedback_report or build_governance_feedback_report(
        runtime_state=state,
        write_runtime=False,
    )
    reconciliation = reconciliation_summary if isinstance(reconciliation_summary, dict) else (
        load_json_file(PAPER_RECONCILIATION_SUMMARY_PATH, default={}) or {}
    )
    if not isinstance(reconciliation, dict):
        reconciliation = {}
    history_rows = (
        reconciliation_history_rows
        if isinstance(reconciliation_history_rows, list)
        else _load_jsonl_rows(PAPER_RECONCILIATION_HISTORY_PATH)
    )

    visibility_legibility_layer = build_visibility_legibility_layer(
        health_report=health,
        governance_status_report=governance,
        reconciliation_summary=reconciliation,
        reconciliation_history_rows=history_rows,
    )
    readiness_ladder = build_readiness_ladder(
        operating_mode_report=operating,
        governance_feedback_report=governance_feedback,
        visibility_legibility_layer=visibility_legibility_layer,
        reconciliation_summary=reconciliation,
        config=active_config,
    )
    trainer_mode_metadata = build_trainer_mode_metadata(
        operating_mode_report=operating,
        readiness_ladder=readiness_ladder,
    )
    utility_resilience_layer = build_utility_resilience_layer(
        visibility_legibility_layer=visibility_legibility_layer,
        reconciliation_summary=reconciliation,
        config=active_config,
    )
    premium_compression_layer = build_premium_compression_layer(
        readiness_ladder=readiness_ladder,
        visibility_legibility_layer=visibility_legibility_layer,
        config=active_config,
    )

    report = stamp_payload(
        {
            "artifact_kind": "experience_mode_report",
            "feature_flags": active_config.get("feature_flags", {}),
            "trainer_mode_metadata": trainer_mode_metadata,
            "visibility_legibility_layer": visibility_legibility_layer,
            "readiness_ladder": readiness_ladder,
            "utility_resilience_layer": utility_resilience_layer,
            "premium_compression_layer": premium_compression_layer,
            "design_dna_stub": build_design_dna_stub(),
            "source_artifacts": {
                "health_report": repo_relative(Path("runtime") / "pipeline_health_report.json"),
                "governance_feedback_report": repo_relative(Path("runtime") / "governance_feedback_report.json"),
                "reconciliation_summary": repo_relative(PAPER_RECONCILIATION_SUMMARY_PATH),
                "reconciliation_history": repo_relative(PAPER_RECONCILIATION_HISTORY_PATH),
            },
            "note": (
                "This report is an additive experience/readiness layer. It does not "
                "change execution behavior or enable live automation."
            ),
        },
        runtime_state=state,
    )
    if write_runtime:
        write_json_atomic(output_path or EXPERIENCE_MODE_REPORT_PATH, report, stamp=False)
    return report


def format_experience_mode_summary(report: dict[str, Any]) -> str:
    trainer = report.get("trainer_mode_metadata", {})
    readiness = report.get("readiness_ladder", {})
    visibility = report.get("visibility_legibility_layer", {})
    utility = report.get("utility_resilience_layer", {})
    premium = report.get("premium_compression_layer", {})
    return "\n".join(
        [
            "Experience Mode Report",
            f"recommended_surface_profile={trainer.get('recommended_surface_profile')}",
            f"trainer_mode_active={str(bool(trainer.get('trainer_mode_active'))).lower()}",
            f"trainer_readiness={readiness.get('trainer_readiness')}",
            f"utility_readiness={readiness.get('utility_readiness')}",
            f"jet_readiness={readiness.get('jet_readiness')}",
            f"visibility_legibility_score={visibility.get('visibility_legibility_score')}",
            f"degraded_mode_required={str(bool(utility.get('degraded_mode_required'))).lower()}",
            f"premium_surface_eligible={str(bool(premium.get('premium_surface_eligible'))).lower()}",
        ]
    )


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Summarize the MVP experience ladder: trainer-mode metadata, "
            "visibility/lineage legibility, readiness scaffolding, and premium-surface eligibility."
        )
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--summary", action="store_true", help="Emit a compact human-readable summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    report = build_experience_mode_report(write_runtime=True)
    if args.summary:
        print(format_experience_mode_summary(report))
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
