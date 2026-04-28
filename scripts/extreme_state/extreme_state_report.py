from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from scripts.runtime_common import (
        EXTREME_STATE_REPORT_PATH,
        build_truth_context,
        get_source_mode,
        repo_relative,
        stamp_payload,
        write_json_atomic,
    )
except ModuleNotFoundError:
    from runtime_common import (  # type: ignore[no-redef]
        EXTREME_STATE_REPORT_PATH,
        build_truth_context,
        get_source_mode,
        repo_relative,
        stamp_payload,
        write_json_atomic,
    )

from .extreme_state_classifier import (
    DO_NOT_DEPLOY,
    SILENT_CHAOS,
    TERMINATE_OR_RECLASSIFY,
    evaluate_extreme_state_signal,
    evaluation_to_dict,
    summarize_extreme_state_counts,
)


def _dominant_state(evaluations: list[dict[str, Any]]) -> str:
    if not evaluations:
        return "NORMAL"
    priority = [DO_NOT_DEPLOY, SILENT_CHAOS, TERMINATE_OR_RECLASSIFY]
    for state in priority:
        if any(row.get("extreme_state") == state for row in evaluations):
            return state
    counter = Counter(str(row.get("extreme_state") or "NORMAL") for row in evaluations)
    return max(counter.items(), key=lambda item: (item[1], item[0]))[0]


def build_extreme_state_report(
    signals: list[dict[str, Any]] | None,
    *,
    runtime_state: dict[str, Any] | None = None,
    output_path: Path | None = None,
    write_runtime: bool = True,
) -> dict[str, Any]:
    rows = signals if isinstance(signals, list) else []
    evaluations = [evaluation_to_dict(evaluate_extreme_state_signal(row)) for row in rows]
    counts = summarize_extreme_state_counts(
        [evaluate_extreme_state_signal(row) for row in rows]
    )
    truth_context = build_truth_context(runtime_state or {})
    dominant_state = _dominant_state(evaluations)
    can_execute = any(bool(row.get("flags", {}).get("can_execute")) for row in evaluations) and (
        truth_context["truth_origin"] != "seeded"
    )
    summary_scores = {
        key: round(
            sum(float(row.get("scores", {}).get(key, 0.0) or 0.0) for row in evaluations)
            / max(len(evaluations), 1),
            3,
        )
        for key in (
            "performance_ceiling",
            "execution_efficiency",
            "structural_advantage",
            "repeatability",
            "stress_adjusted_repeatability",
            "conversion_probability",
            "exit_clarity",
            "true_edge",
            "executable_edge",
            "symmetry_risk",
            "equilibrium_score",
            "silent_chaos_score",
            "loop_risk",
            "holding_cost",
            "progress_score",
        )
    }
    diagnostics: list[str] = []
    if counts["silent_chaos_count"] > 0:
        diagnostics.append("Persistence is not progress")
    if counts["valid_but_non_executable_count"] > 0:
        diagnostics.append("Signal is valid but non-executable")
    if summary_scores["exit_clarity"] < 0.65:
        diagnostics.append("No exit clarity detected")
    if truth_context["truth_origin"] == "seeded":
        diagnostics.append("Inputs remain seeded; external reality is not connected")
    recommendation = (
        "BLOCK"
        if dominant_state == DO_NOT_DEPLOY
        else "TERMINATE"
        if dominant_state in {SILENT_CHAOS, TERMINATE_OR_RECLASSIFY}
        else "DOWNGRADE"
        if counts["valid_but_non_executable_count"] or counts["non_converting_equilibrium_count"]
        else "PROMOTE"
        if counts["promoted_count"] > 0
        else "WAIT"
    )
    report = {
        "module": "extreme_state_logic",
        "schema_version": "1.0",
        "source_mode": get_source_mode(),
        "operating_mode": truth_context["operating_mode"],
        "truth_origin": truth_context["truth_origin"],
        "external_reality_connected": truth_context["truth_origin"] != "seeded",
        "policy_state": str((runtime_state or {}).get("execution_policy", {}).get("policy_state") or "UNKNOWN").upper(),
        "signals_evaluated": len(evaluations),
        "extreme_state": dominant_state,
        "can_execute": bool(can_execute),
        "termination_triggered": counts["termination_required_count"] > 0,
        "silent_chaos_detected": counts["silent_chaos_count"] > 0,
        "non_converting_equilibrium_detected": counts["non_converting_equilibrium_count"] > 0,
        "valid_but_non_executable": counts["valid_but_non_executable_count"] > 0,
        "scores": summary_scores,
        "diagnostics": diagnostics,
        "recommended_action": recommendation,
        "extreme_state_logic": counts,
        "signals": evaluations,
        "report_path": repo_relative(output_path or EXTREME_STATE_REPORT_PATH),
    }
    stamped = stamp_payload(report, runtime_state=runtime_state or report)
    if write_runtime:
        write_json_atomic(output_path or EXTREME_STATE_REPORT_PATH, stamped, stamp=False)
    return stamped


def format_extreme_state_summary(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Extreme State Report",
            f"extreme_state={report.get('extreme_state', 'NORMAL')}",
            f"signals_evaluated={report.get('signals_evaluated', 0)}",
            f"Executable Edge={report.get('scores', {}).get('executable_edge')}",
            f"Loop Risk={report.get('scores', {}).get('loop_risk')}",
            f"Recommended Action={report.get('recommended_action', 'WAIT')}",
            (
                "Reason: "
                + (
                    report.get("diagnostics", ["No extreme-state warnings detected"])[0]
                    if isinstance(report.get("diagnostics"), list)
                    and report.get("diagnostics")
                    else "No extreme-state warnings detected"
                )
            ),
        ]
    )


def to_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True)
