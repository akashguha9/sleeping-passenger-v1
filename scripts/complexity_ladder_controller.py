from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from scripts.runtime_common import (
        COMPLEXITY_LADDER_CONTROLLER_PATH,
        EXPERIENCE_MODE_REPORT_PATH,
        build_truth_context,
        load_current_pipeline_state,
        load_json_file,
        repo_relative,
        stamp_payload,
        write_json_atomic,
    )
except ModuleNotFoundError:
    from runtime_common import (  # type: ignore
        COMPLEXITY_LADDER_CONTROLLER_PATH,
        EXPERIENCE_MODE_REPORT_PATH,
        build_truth_context,
        load_current_pipeline_state,
        load_json_file,
        repo_relative,
        stamp_payload,
        write_json_atomic,
    )


DEFAULT_UTILITY_READY_MIN = 0.60
DEFAULT_JET_READY_MIN = 0.80
DEFAULT_PREMIUM_UNRESOLVED_GAP_MAX = 0.10


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dedupe_reasons(reasons: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for reason in reasons:
        text = str(reason or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _safe_default_payload(
    *,
    runtime_state: dict[str, Any],
    input_path: Path,
    reason: str,
) -> dict[str, Any]:
    return stamp_payload(
        {
            "artifact_kind": "complexity_ladder_controller",
            "schema_version": "COMPLEXITY_LADDER_CONTROLLER_V1",
            "advisory_only": True,
            "experience_mode_report_present": False,
            "source_artifact": repo_relative(input_path),
            "trainer_surface_allowed": True,
            "utility_surface_allowed": False,
            "premium_surface_allowed": False,
            "explanation_heavy_required": True,
            "degraded_mode_annotations_required": True,
            "drilldown_required": True,
            "operator_surface_recommendation": "trainer",
            "controller_reasoning": _dedupe_reasons(
                [
                    reason,
                    "safe_surface_default_applied",
                    "drilldown_required_by_design",
                ]
            ),
            "note": (
                "Advisory-only complexity ladder controller. Missing or invalid inputs "
                "default to the trainer-safe surface."
            ),
        },
        runtime_state=runtime_state,
    )


def build_complexity_ladder_controller(
    *,
    report_payload: dict[str, Any] | None = None,
    runtime_state: dict[str, Any] | None = None,
    input_path: Path | None = None,
    output_path: Path | None = None,
    write_runtime: bool = True,
) -> dict[str, Any]:
    state = runtime_state or load_current_pipeline_state()
    target_input = input_path or EXPERIENCE_MODE_REPORT_PATH
    target_output = output_path or COMPLEXITY_LADDER_CONTROLLER_PATH
    raw_report = report_payload if isinstance(report_payload, dict) else load_json_file(
        target_input,
        default=None,
    )

    if raw_report is None:
        controller = _safe_default_payload(
            runtime_state=state,
            input_path=target_input,
            reason="experience_mode_report_missing",
        )
        if write_runtime:
            write_json_atomic(target_output, controller, stamp=False)
        return controller

    if not isinstance(raw_report, dict):
        controller = _safe_default_payload(
            runtime_state=state,
            input_path=target_input,
            reason="experience_mode_report_invalid",
        )
        if write_runtime:
            write_json_atomic(target_output, controller, stamp=False)
        return controller

    trainer_metadata = raw_report.get("trainer_mode_metadata", {})
    readiness = raw_report.get("readiness_ladder", {})
    visibility = raw_report.get("visibility_legibility_layer", {})
    utility = raw_report.get("utility_resilience_layer", {})
    premium = raw_report.get("premium_compression_layer", {})

    truth_context = build_truth_context(state)
    operating_mode = str(truth_context.get("operating_mode") or "seeded").strip().lower()
    trainer_mode_active = bool(trainer_metadata.get("trainer_mode_active"))
    recommended_profile = str(
        trainer_metadata.get("recommended_surface_profile")
        or readiness.get("recommended_surface_profile")
        or "trainer"
    ).strip().lower() or "trainer"
    utility_readiness = _coerce_float(readiness.get("utility_readiness")) or 0.0
    jet_readiness = _coerce_float(readiness.get("jet_readiness")) or 0.0
    unresolved_gap_rate = _coerce_float(visibility.get("unresolved_data_gap_rate")) or 0.0
    degraded_mode_required = bool(utility.get("degraded_mode_required"))
    premium_surface_eligible = bool(premium.get("premium_surface_eligible"))

    trainer_surface_allowed = True
    utility_surface_allowed = False
    premium_surface_allowed = False
    operator_surface_recommendation = "trainer"
    controller_reasoning: list[str] = []

    seeded_safe_mode = operating_mode in {"seeded", "paper_prepared"}
    if seeded_safe_mode:
        controller_reasoning.append(f"{operating_mode}_mode_forces_trainer_surface")
    elif trainer_mode_active or recommended_profile == "trainer":
        controller_reasoning.append("trainer_mode_active")
    elif utility_readiness >= DEFAULT_UTILITY_READY_MIN:
        utility_surface_allowed = True
        operator_surface_recommendation = "utility"
        controller_reasoning.append("utility_readiness_allows_utility_surface")
    else:
        controller_reasoning.append("utility_readiness_below_threshold")

    if trainer_mode_active and not seeded_safe_mode:
        controller_reasoning.append("trainer_mode_active")

    if utility_readiness < DEFAULT_UTILITY_READY_MIN:
        controller_reasoning.append("utility_readiness_below_threshold")

    if jet_readiness < DEFAULT_JET_READY_MIN:
        controller_reasoning.append("jet_readiness_below_threshold")

    if unresolved_gap_rate > DEFAULT_PREMIUM_UNRESOLVED_GAP_MAX:
        controller_reasoning.append("unresolved_gap_breach_forces_no_premium")

    if not premium_surface_eligible:
        controller_reasoning.append("premium_surface_not_eligible")

    if (
        not seeded_safe_mode
        and recommended_profile == "jet"
        and utility_readiness >= DEFAULT_UTILITY_READY_MIN
    ):
        utility_surface_allowed = True

    if (
        not seeded_safe_mode
        and recommended_profile == "jet"
        and jet_readiness >= DEFAULT_JET_READY_MIN
        and premium_surface_eligible
        and unresolved_gap_rate <= DEFAULT_PREMIUM_UNRESOLVED_GAP_MAX
    ):
        premium_surface_allowed = True
        utility_surface_allowed = True
        operator_surface_recommendation = "jet"
        controller_reasoning.append("jet_readiness_allows_premium_surface")

    explanation_heavy_required = operator_surface_recommendation != "jet"
    degraded_mode_annotations_required = (
        operator_surface_recommendation != "jet"
        or degraded_mode_required
        or unresolved_gap_rate > 0.0
    )
    if degraded_mode_annotations_required:
        controller_reasoning.append("degraded_mode_annotations_required")

    controller_reasoning.append("drilldown_required_by_design")

    controller = stamp_payload(
        {
            "artifact_kind": "complexity_ladder_controller",
            "schema_version": "COMPLEXITY_LADDER_CONTROLLER_V1",
            "advisory_only": True,
            "experience_mode_report_present": True,
            "source_artifact": repo_relative(target_input),
            "input_operating_mode": operating_mode,
            "input_recommended_surface_profile": recommended_profile,
            "input_utility_readiness": round(utility_readiness, 4),
            "input_jet_readiness": round(jet_readiness, 4),
            "input_unresolved_data_gap_rate": round(unresolved_gap_rate, 4),
            "trainer_surface_allowed": trainer_surface_allowed,
            "utility_surface_allowed": utility_surface_allowed,
            "premium_surface_allowed": premium_surface_allowed,
            "explanation_heavy_required": explanation_heavy_required,
            "degraded_mode_annotations_required": degraded_mode_annotations_required,
            "drilldown_required": True,
            "operator_surface_recommendation": operator_surface_recommendation,
            "controller_reasoning": _dedupe_reasons(controller_reasoning),
            "note": (
                "Advisory-only surface controller derived from the current "
                "experience-mode report. It does not change execution behavior."
            ),
        },
        runtime_state=state,
    )

    if write_runtime:
        write_json_atomic(target_output, controller, stamp=False)
    return controller


def format_complexity_ladder_summary(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Complexity Ladder Controller",
            f"operator_surface_recommendation={report.get('operator_surface_recommendation')}",
            f"trainer_surface_allowed={str(bool(report.get('trainer_surface_allowed'))).lower()}",
            f"utility_surface_allowed={str(bool(report.get('utility_surface_allowed'))).lower()}",
            f"premium_surface_allowed={str(bool(report.get('premium_surface_allowed'))).lower()}",
            f"explanation_heavy_required={str(bool(report.get('explanation_heavy_required'))).lower()}",
            f"degraded_mode_annotations_required={str(bool(report.get('degraded_mode_annotations_required'))).lower()}",
            f"drilldown_required={str(bool(report.get('drilldown_required'))).lower()}",
        ]
    )


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Advisory-only complexity ladder controller for trainer, utility, and "
            "premium surface exposure."
        )
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--summary", action="store_true", help="Emit a compact human-readable summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    report = build_complexity_ladder_controller(write_runtime=True)
    if args.summary:
        print(format_complexity_ladder_summary(report))
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
