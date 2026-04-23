from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from scripts.action_engine import build_action_report
    from scripts.operator_control import build_operator_control_report
    from scripts.runtime_common import (
        CLOSURE_DEFICIT_REPORT_PATH,
        PAPER_CLOSE_LEDGER_PATH,
        PAPER_DECISION_LEDGER_PATH,
        PAPER_POSITIONS_PATH,
        PAPER_RECONCILIATION_HISTORY_PATH,
        PAPER_RECONCILIATION_SUMMARY_PATH,
        build_deployment_permissions,
        load_current_pipeline_state,
        load_json_file,
        repo_relative,
        stamp_payload,
        write_json_atomic,
    )
    from scripts.signal_refinery import build_signal_refinery_report
    from scripts.trend_engine import build_trend_report
except ModuleNotFoundError:
    from action_engine import build_action_report
    from operator_control import build_operator_control_report
    from runtime_common import (
        CLOSURE_DEFICIT_REPORT_PATH,
        PAPER_CLOSE_LEDGER_PATH,
        PAPER_DECISION_LEDGER_PATH,
        PAPER_POSITIONS_PATH,
        PAPER_RECONCILIATION_HISTORY_PATH,
        PAPER_RECONCILIATION_SUMMARY_PATH,
        build_deployment_permissions,
        load_current_pipeline_state,
        load_json_file,
        repo_relative,
        stamp_payload,
        write_json_atomic,
    )
    from signal_refinery import build_signal_refinery_report
    from trend_engine import build_trend_report


SUFFICIENT_EVIDENCE_STATES = {"early_pattern", "moderate_pattern"}
LINEAGE_COMPLETE_STATUSES = {"fully_reconciled", "partially_reconciled"}
DECISIVE_ACTIONS = {"REVIEW_FOR_ENTRY", "EXIT_NOW", "REDUCE", "BLOCK_ENTRY"}


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


def _open_paper_position_count(path: Path) -> int:
    payload = load_json_file(path, default={}) or {}
    if not isinstance(payload, dict):
        return 0
    rows = payload.get("positions", [])
    if not isinstance(rows, list):
        return 0
    return sum(1 for row in rows if str((row or {}).get("status") or "").upper() == "OPEN")


def _non_close_decision_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for row in rows:
        action_type = str(row.get("action_type") or "").upper()
        if action_type == "CLOSE_POSITION":
            continue
        filtered.append(row)
    return filtered


def _approved_entry_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    approved: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("approval_state") or "").upper() != "APPROVED_BY_HUMAN_FOR_PAPER":
            continue
        if str(row.get("action_type") or "").upper() != "REVIEW_FOR_ENTRY":
            continue
        approved.append(row)
    return approved


def _insight_ticker_count(
    signal_refinery_report: dict[str, Any],
    packet_summary: dict[str, Any] | None = None,
) -> int:
    tickers: set[str] = set()
    validation_rows = signal_refinery_report.get("validation_engine", {}).get("signals", [])
    if isinstance(validation_rows, list):
        for row in validation_rows:
            if not isinstance(row, dict):
                continue
            validation_state = str(row.get("validation_state") or "").upper()
            if validation_state not in {"VALIDATED", "NEEDS_CONFIRMATION"}:
                continue
            ticker = str(row.get("ticker") or "").upper()
            if ticker:
                tickers.add(ticker)
    packets = packet_summary if isinstance(packet_summary, dict) else {}
    for key in ("entry_review_candidate_names", "transition_review_candidate_names"):
        value = packets.get(key, [])
        if not isinstance(value, list):
            continue
        for ticker in value:
            text = str(ticker or "").upper().strip()
            if text:
                tickers.add(text)
    return len(tickers)


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(min(numerator / denominator, 1.0), 4)


def build_closure_deficit_report(
    runtime_state: dict[str, Any] | None = None,
    action_report: dict[str, Any] | None = None,
    signal_refinery_report: dict[str, Any] | None = None,
    packet_summary: dict[str, Any] | None = None,
    operator_control_report: dict[str, Any] | None = None,
    decision_ledger_path: Path | None = None,
    close_ledger_path: Path | None = None,
    paper_positions_path: Path | None = None,
    reconciliation_history_path: Path | None = None,
    reconciliation_summary_path: Path | None = None,
    output_path: Path | None = None,
    write_runtime: bool = True,
) -> dict[str, Any]:
    state = runtime_state or load_current_pipeline_state()
    report = action_report or build_action_report(runtime_state=state, write_runtime=False)
    refinery = signal_refinery_report or build_signal_refinery_report(
        runtime_state=state,
        trend_report=build_trend_report(write_runtime=False),
        write_runtime=False,
    )
    operator_report = operator_control_report or build_operator_control_report(write_runtime=False)

    decisions_path = decision_ledger_path or PAPER_DECISION_LEDGER_PATH
    closes_path = close_ledger_path or PAPER_CLOSE_LEDGER_PATH
    positions_path = paper_positions_path or PAPER_POSITIONS_PATH
    history_path = reconciliation_history_path or PAPER_RECONCILIATION_HISTORY_PATH
    summary_path = reconciliation_summary_path or PAPER_RECONCILIATION_SUMMARY_PATH

    decision_rows = _non_close_decision_rows(_load_jsonl_rows(decisions_path))
    close_rows = _load_jsonl_rows(closes_path)
    history_rows = _load_jsonl_rows(history_path)
    summary_payload = load_json_file(summary_path, default={}) or {}
    if not isinstance(summary_payload, dict):
        summary_payload = {}

    insights_produced_count = _insight_ticker_count(refinery, packet_summary=packet_summary)
    actions_suggested_count = len(report.get("actions", []))
    decisive_action_count = sum(
        1
        for row in report.get("actions", [])
        if str((row or {}).get("action") or "").upper() in DECISIVE_ACTIONS
    )
    review_for_entry_suggestion_count = sum(
        1
        for row in report.get("actions", [])
        if str((row or {}).get("action") or "").upper() == "REVIEW_FOR_ENTRY"
    )
    decision_recorded_count = len(decision_rows)
    actions_approved_count = len(_approved_entry_rows(decision_rows))
    actions_closed_count = len(close_rows)
    open_paper_position_count = _open_paper_position_count(positions_path)

    reconciled_lineage_count = sum(
        1
        for row in history_rows
        if str(row.get("reconciliation_status") or "").lower() in LINEAGE_COMPLETE_STATUSES
    )
    evidence_strength = str(summary_payload.get("evidence_strength") or "insufficient_evidence")
    actions_reconciled_with_sufficient_evidence = (
        reconciled_lineage_count if evidence_strength in SUFFICIENT_EVIDENCE_STATES else 0
    )

    drift_monitor = operator_report.get("drift_monitor", {}) if isinstance(operator_report, dict) else {}
    total_execution_blocks = int(drift_monitor.get("total_execution_blocks") or 0)
    unfinished_closure_count = int(drift_monitor.get("unfinished_closure_count") or 0)

    decision_capture_ratio = _ratio(decision_recorded_count, actions_suggested_count)
    entry_approval_ratio = _ratio(actions_approved_count, review_for_entry_suggestion_count)
    total_positions_observed = open_paper_position_count + actions_closed_count
    open_closure_backlog_ratio = _ratio(open_paper_position_count, total_positions_observed)
    reconciliation_completion_ratio = _ratio(reconciled_lineage_count, actions_closed_count)
    evidence_sufficiency_ratio = _ratio(
        actions_reconciled_with_sufficient_evidence,
        actions_closed_count,
    )
    operator_unfinished_ratio = _ratio(unfinished_closure_count, total_execution_blocks)

    gap_components: list[dict[str, Any]] = []
    for name, ratio, gap_mode in (
        ("decision_capture_gap", decision_capture_ratio, "inverse"),
        ("entry_approval_gap", entry_approval_ratio, "inverse"),
        ("open_closure_backlog_gap", open_closure_backlog_ratio, "direct"),
        ("reconciliation_completion_gap", reconciliation_completion_ratio, "inverse"),
        ("evidence_sufficiency_gap", evidence_sufficiency_ratio, "inverse"),
        ("operator_unfinished_gap", operator_unfinished_ratio, "direct"),
    ):
        if ratio is None:
            continue
        gap_value = ratio if gap_mode == "direct" else round(1.0 - ratio, 4)
        gap_components.append(
            {
                "name": name,
                "observed_ratio": ratio,
                "gap_value": round(gap_value, 4),
            }
        )

    closure_deficit_score = None
    closure_deficit_state = "SPARSE"
    if len(gap_components) >= 2:
        closure_deficit_score = round(
            sum(float(item["gap_value"]) for item in gap_components) / len(gap_components),
            4,
        )
        if closure_deficit_score >= 0.65:
            closure_deficit_state = "HIGH_DEFICIT"
        elif closure_deficit_score >= 0.4:
            closure_deficit_state = "MEDIUM_DEFICIT"
        else:
            closure_deficit_state = "LOW_DEFICIT"

    deployment = build_deployment_permissions(state)
    payload = stamp_payload(
        {
            "artifact_kind": "closure_deficit_report",
            "counts": {
                "insights_produced": insights_produced_count,
                "actions_suggested": actions_suggested_count,
                "decisive_actions_suggested": decisive_action_count,
                "actions_approved": actions_approved_count,
                "actions_closed": actions_closed_count,
                "actions_reconciled_with_sufficient_evidence": actions_reconciled_with_sufficient_evidence,
                "actions_reconciled_with_complete_lineage": reconciled_lineage_count,
                "open_paper_positions": open_paper_position_count,
            },
            "ratios": {
                "decision_capture_ratio": decision_capture_ratio,
                "entry_approval_ratio": entry_approval_ratio,
                "open_closure_backlog_ratio": open_closure_backlog_ratio,
                "reconciliation_completion_ratio": reconciliation_completion_ratio,
                "evidence_sufficiency_ratio": evidence_sufficiency_ratio,
                "operator_unfinished_ratio": operator_unfinished_ratio,
            },
            "gap_components": gap_components,
            "closure_deficit_score": closure_deficit_score,
            "closure_deficit_state": closure_deficit_state,
            "measurement_coverage": {
                "observed_component_count": len(gap_components),
                "decision_ledger_present": decisions_path.exists(),
                "close_ledger_present": closes_path.exists(),
                "reconciliation_history_present": history_path.exists(),
                "reconciliation_summary_present": summary_path.exists(),
            },
            "operator_closure_context": {
                "total_execution_blocks": total_execution_blocks,
                "unfinished_closure_count": unfinished_closure_count,
            },
            "count_scope_notes": {
                "insights_produced": "Unique validated or review-surface tickers visible in the current refinery/report state.",
                "actions_suggested": "Current action report rows.",
                "actions_approved": "Human-approved paper entry decisions only. Exit approvals are not separately logged today.",
                "actions_closed": "Paper close ledger rows.",
                "actions_reconciled_with_sufficient_evidence": "Reconciled closes only after lineage is complete and the cumulative evidence state is at least early_pattern.",
            },
            "governance_boundary": {
                "suggestion_only": True,
                "human_execution_required": True,
                "paper_execution_enabled": bool(deployment.get("paper_execution_enabled", False)),
                "live_execution_enabled": bool(deployment.get("live_execution_enabled", False)),
            },
            "source_paths": {
                "decision_ledger_path": repo_relative(decisions_path),
                "close_ledger_path": repo_relative(closes_path),
                "paper_positions_path": repo_relative(positions_path),
                "reconciliation_history_path": repo_relative(history_path),
                "reconciliation_summary_path": repo_relative(summary_path),
            },
            "note": (
                "Closure deficit is measured from repo-visible paper and operator artifacts only. "
                "Missing approval latency, live fills, or broker reconciliation are reported as absent rather than inferred."
            ),
        },
        runtime_state=state,
    )
    if write_runtime:
        write_json_atomic(output_path or CLOSURE_DEFICIT_REPORT_PATH, payload, stamp=False)
    return payload


def format_closure_deficit_summary(report: dict[str, Any]) -> str:
    counts = report.get("counts", {})
    return "\n".join(
        [
            "Closure Deficit",
            f"closure_deficit_state={report.get('closure_deficit_state')}",
            f"closure_deficit_score={report.get('closure_deficit_score')}",
            f"insights_produced={counts.get('insights_produced', 0)}",
            f"actions_suggested={counts.get('actions_suggested', 0)}",
            f"actions_approved={counts.get('actions_approved', 0)}",
            f"actions_closed={counts.get('actions_closed', 0)}",
            "actions_reconciled_with_sufficient_evidence="
            f"{counts.get('actions_reconciled_with_sufficient_evidence', 0)}",
        ]
    )


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure the closure gap between current suggestions, paper approvals, closes, and reconciled evidence."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    mode.add_argument("--summary", action="store_true", help="Emit a compact human-readable summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    report = build_closure_deficit_report(write_runtime=True)
    if args.summary:
        print(format_closure_deficit_summary(report))
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
