from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from scripts.runtime_common import (
        EXTREME_STATE_EVENTS_PATH,
        EXTREME_STATE_REPORT_PATH,
        append_jsonl,
        build_truth_context,
        get_source_mode,
        repo_relative,
        stamp_payload,
        write_json_atomic,
    )
except ModuleNotFoundError:
    from runtime_common import (  # type: ignore[no-redef]
        EXTREME_STATE_EVENTS_PATH,
        EXTREME_STATE_REPORT_PATH,
        append_jsonl,
        build_truth_context,
        get_source_mode,
        repo_relative,
        stamp_payload,
        write_json_atomic,
    )

from .extreme_state_classifier import (
    DO_NOT_DEPLOY,
    INFINITE_LOOP_RISK,
    SILENT_CHAOS,
    TERMINATION_REQUIRED,
    evaluate_extreme_state_signal,
    evaluation_to_dict,
    summarize_extreme_state_counts,
)


def _dominant_state(evaluations: list[dict[str, Any]]) -> str:
    if not evaluations:
        return "NORMAL"
    priority = [DO_NOT_DEPLOY, TERMINATION_REQUIRED, INFINITE_LOOP_RISK, SILENT_CHAOS]
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
    events_path: Path | None = None,
    write_runtime: bool = True,
) -> dict[str, Any]:
    rows = signals if isinstance(signals, list) else []
    evaluations_obj = [evaluate_extreme_state_signal(row) for row in rows]
    evaluations = [evaluation_to_dict(item) for item in evaluations_obj]
    counts = summarize_extreme_state_counts(evaluations_obj)
    truth_context = build_truth_context(runtime_state or {})
    dominant_state = _dominant_state(evaluations)
    summary_scores = {
        key: round(
            sum(float(row.get("scores", {}).get(key, 0.0) or 0.0) for row in evaluations)
            / max(len(evaluations), 1),
            3,
        )
        for key in (
            "performance_ceiling_score",
            "execution_efficiency_score",
            "structural_advantage_score",
            "repeatability_score",
            "stress_adjusted_repeatability",
            "usable_edge_score",
            "conversion_probability_score",
            "executable_edge_score",
            "net_signal_score",
            "symmetry_score",
            "silent_chaos_score",
            "loop_risk_score",
            "holding_cost_score",
        )
    }
    diagnostics: list[str] = []
    if counts["silent_chaos_count"] > 0:
        diagnostics.append("Persistence is not progress.")
    if counts["valid_but_non_executable_count"] > 0:
        diagnostics.append("A valid signal is not automatically executable.")
    if counts["non_converting_equilibrium_count"] > 0:
        diagnostics.append("Symmetry canceled advantage before conversion.")
    if summary_scores["holding_cost_score"] >= 0.60:
        diagnostics.append("Holding cost is rising faster than transition quality.")
    if truth_context["truth_origin"] == "seeded":
        diagnostics.append("Inputs remain seeded; external reality is not connected.")

    recommendation = (
        "REJECT"
        if dominant_state == DO_NOT_DEPLOY
        else "TERMINATE"
        if dominant_state in {SILENT_CHAOS, TERMINATION_REQUIRED, INFINITE_LOOP_RISK}
        else "DOWNGRADE"
        if counts["valid_but_non_executable_count"] or counts["non_converting_equilibrium_count"] or counts["downgraded_count"]
        else "PROMOTE"
        if counts["promoted_count"] > 0
        else "HOLD"
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
        "can_execute": False,
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
        "events_path": repo_relative(events_path or EXTREME_STATE_EVENTS_PATH),
    }
    stamped = stamp_payload(report, runtime_state=runtime_state or report)
    if write_runtime:
        write_json_atomic(output_path or EXTREME_STATE_REPORT_PATH, stamped, stamp=False)
        for row in evaluations:
            append_jsonl(events_path or EXTREME_STATE_EVENTS_PATH, row, stamp=True)
    return stamped


def format_extreme_state_summary(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Extreme State Report",
            f"extreme_state={report.get('extreme_state', 'NORMAL')}",
            f"signals_evaluated={report.get('signals_evaluated', 0)}",
            f"termination_required_count={report.get('extreme_state_logic', {}).get('termination_required_count', 0)}",
            f"silent_chaos_count={report.get('extreme_state_logic', {}).get('silent_chaos_count', 0)}",
            f"recommended_action={report.get('recommended_action', 'HOLD')}",
        ]
    )


def to_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True)
