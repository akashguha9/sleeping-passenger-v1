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
    from scripts.action_engine import build_action_report
    from scripts.execution_governance import (
        evaluate_automation_readiness,
        summarize_action_governance,
    )
    from scripts.runtime_common import (
        GOVERNANCE_FEEDBACK_REPORT_PATH,
        INTERACTION_FEEDBACK_LEDGER_PATH,
        MODEL_FEEDBACK_LEDGER_PATH,
        OPERATOR_FEEDBACK_LEDGER_PATH,
        OPERATOR_OVERRIDE_LEDGER_PATH,
        PAPER_RECONCILIATION_SUMMARY_PATH,
        load_current_pipeline_state,
        load_json_file,
        repo_relative,
        stamp_payload,
        write_json_atomic,
    )
except ModuleNotFoundError:
    from action_engine import build_action_report
    from execution_governance import (
        evaluate_automation_readiness,
        summarize_action_governance,
    )
    from runtime_common import (
        GOVERNANCE_FEEDBACK_REPORT_PATH,
        INTERACTION_FEEDBACK_LEDGER_PATH,
        MODEL_FEEDBACK_LEDGER_PATH,
        OPERATOR_FEEDBACK_LEDGER_PATH,
        OPERATOR_OVERRIDE_LEDGER_PATH,
        PAPER_RECONCILIATION_SUMMARY_PATH,
        load_current_pipeline_state,
        load_json_file,
        repo_relative,
        stamp_payload,
        write_json_atomic,
    )


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


def _coerce_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _summarize_override_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    classification_counts: dict[str, int] = {}
    fpeg_counts: dict[str, int] = {}
    scores: list[float] = []
    for row in rows:
        classification = str(row.get("override_classification") or "unknown")
        classification_counts[classification] = classification_counts.get(classification, 0) + 1
        fpeg_state = str(row.get("manual_fpeg_state") or "unknown")
        fpeg_counts[fpeg_state] = fpeg_counts.get(fpeg_state, 0) + 1
        score = _coerce_float(row.get("manual_fpeg_score"))
        if score is not None:
            scores.append(score)
    return {
        "total_override_count": len(rows),
        "override_classification_counts": classification_counts,
        "override_fpeg_state_counts": fpeg_counts,
        "average_manual_fpeg_score": round(sum(scores) / len(scores), 4) if scores else None,
        "manual_approval_logged_count": len(rows),
    }


def _summarize_quality_rows(
    rows: list[dict[str, Any]],
    score_field: str,
    state_field: str,
) -> dict[str, Any]:
    state_counts: dict[str, int] = {}
    scores: list[float] = []
    for row in rows:
        state = str(row.get(state_field) or "unknown")
        state_counts[state] = state_counts.get(state, 0) + 1
        score = _coerce_float(row.get(score_field))
        if score is not None:
            scores.append(score)
    return {
        "count": len(rows),
        "average_score": round(sum(scores) / len(scores), 4) if scores else None,
        "state_counts": state_counts,
    }


def build_governance_feedback_report(
    runtime_state: dict[str, Any] | None = None,
    action_report: dict[str, Any] | None = None,
    reconciliation_summary_path: Path | None = None,
    output_path: Path | None = None,
    write_runtime: bool = True,
) -> dict[str, Any]:
    state = runtime_state or load_current_pipeline_state()
    report = action_report or build_action_report(runtime_state=state, write_runtime=False)
    gate_summary = summarize_action_governance(report.get("actions", []))

    override_rows = _load_jsonl_rows(OPERATOR_OVERRIDE_LEDGER_PATH)
    operator_quality_rows = _load_jsonl_rows(OPERATOR_FEEDBACK_LEDGER_PATH)
    model_quality_rows = _load_jsonl_rows(MODEL_FEEDBACK_LEDGER_PATH)
    interaction_quality_rows = _load_jsonl_rows(INTERACTION_FEEDBACK_LEDGER_PATH)
    reconciliation_summary = load_json_file(
        reconciliation_summary_path or PAPER_RECONCILIATION_SUMMARY_PATH,
        default={},
    )
    if not isinstance(reconciliation_summary, dict):
        reconciliation_summary = {}

    override_summary = _summarize_override_rows(override_rows)
    operator_summary = _summarize_quality_rows(
        operator_quality_rows,
        score_field="operator_quality_score",
        state_field="operator_quality_state",
    )
    model_summary = _summarize_quality_rows(
        model_quality_rows,
        score_field="model_quality_score",
        state_field="model_quality_state",
    )
    interaction_summary = _summarize_quality_rows(
        interaction_quality_rows,
        score_field="interaction_quality_score",
        state_field="interaction_quality_state",
    )

    override_summary["average_interaction_quality"] = interaction_summary["average_score"]
    automation_readiness = evaluate_automation_readiness(
        gate_summary=gate_summary,
        override_summary=override_summary,
        reconciliation_summary=reconciliation_summary,
    )

    payload = stamp_payload(
        {
            "artifact_kind": "governance_feedback_report",
            "gate_usage": gate_summary,
            "override_summary": override_summary,
            "operator_quality_summary": operator_summary,
            "model_quality_summary": model_summary,
            "interaction_quality_summary": interaction_summary,
            "automation_readiness": automation_readiness,
            "reconciliation_evidence": {
                "total_closed_paper_trades": reconciliation_summary.get("total_closed_paper_trades"),
                "evidence_strength": reconciliation_summary.get("evidence_strength"),
                "parameter_change_note": reconciliation_summary.get("parameter_change_note"),
            },
            "note": (
                "Governance feedback is advisory. The repo remains suggestion-only "
                "for execution and requires explicit human approval."
            ),
        },
        runtime_state=state,
    )
    if write_runtime:
        write_json_atomic(output_path or GOVERNANCE_FEEDBACK_REPORT_PATH, payload, stamp=False)
    return payload


def format_governance_feedback_summary(report: dict[str, Any]) -> str:
    gate_usage = report.get("gate_usage", {})
    override_summary = report.get("override_summary", {})
    interaction_summary = report.get("interaction_quality_summary", {})
    readiness = report.get("automation_readiness", {})
    return "\n".join(
        [
            "Governance Feedback",
            f"fpeg_pass_rate={gate_usage.get('fpeg_pass_rate', 0.0)}",
            f"average_fpeg_score={gate_usage.get('average_fpeg_score')}",
            f"total_override_count={override_summary.get('total_override_count', 0)}",
            f"average_interaction_quality={interaction_summary.get('average_score')}",
            f"current_stage={readiness.get('current_stage', 'unknown')}",
            f"eligible_for_limited_delegation={str(bool(readiness.get('eligible_for_limited_delegation', False))).lower()}",
        ]
    )


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Summarize governance gate usage, override quality, and automation-readiness blockers."
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--summary", action="store_true", help="Emit a compact human-readable summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    report = build_governance_feedback_report(write_runtime=True)
    if args.summary:
        print(format_governance_feedback_summary(report))
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
