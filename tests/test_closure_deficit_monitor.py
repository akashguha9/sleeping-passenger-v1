import json
from pathlib import Path

from scripts.action_engine import build_action_report
from scripts.closure_deficit_monitor import build_closure_deficit_report
from scripts.runtime_common import build_runtime_state_from_scm_report_payload
from scripts.signal_conversion_monitor import build_signal_conversion_report
from scripts.signal_refinery import build_signal_refinery_report
from scripts.trend_engine import build_trend_report


REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_SNAPSHOT_LOG = REPO_ROOT / "tests" / "fixtures" / "system_snapshots_seed.jsonl"


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    body = "\n".join(json.dumps(row, separators=(",", ":")) for row in rows)
    if body:
        body += "\n"
    path.write_text(body, encoding="utf-8")


def test_closure_deficit_monitor_stays_sparse_when_ledgers_are_absent(
    scratch_path: Path,
) -> None:
    runtime_state = build_runtime_state_from_scm_report_payload(build_signal_conversion_report())
    trend_report = build_trend_report(log_path=SEED_SNAPSHOT_LOG, write_runtime=False)
    signal_refinery_report = build_signal_refinery_report(
        runtime_state=runtime_state,
        trend_report=trend_report,
        write_runtime=False,
    )
    action_report = build_action_report(
        runtime_state=runtime_state,
        signal_refinery_report=signal_refinery_report,
        write_runtime=False,
    )

    report = build_closure_deficit_report(
        runtime_state=runtime_state,
        action_report=action_report,
        signal_refinery_report=signal_refinery_report,
        decision_ledger_path=scratch_path / "missing_decisions.jsonl",
        close_ledger_path=scratch_path / "missing_closes.jsonl",
        paper_positions_path=scratch_path / "missing_positions.json",
        reconciliation_history_path=scratch_path / "missing_history.jsonl",
        reconciliation_summary_path=scratch_path / "missing_summary.json",
        write_runtime=False,
    )

    assert report["closure_deficit_state"] == "SPARSE"
    assert report["closure_deficit_score"] is None
    assert report["counts"]["actions_approved"] == 0
    assert report["counts"]["actions_closed"] == 0
    assert report["counts"]["actions_reconciled_with_sufficient_evidence"] == 0
    assert report["governance_boundary"]["suggestion_only"] is True
    assert report["governance_boundary"]["human_execution_required"] is True


def test_closure_deficit_monitor_counts_approvals_closes_and_reconciliation(
    scratch_path: Path,
) -> None:
    runtime_state = build_runtime_state_from_scm_report_payload(
        build_signal_conversion_report(simulate_all_clear=True)
    )
    trend_report = build_trend_report(log_path=SEED_SNAPSHOT_LOG, write_runtime=False)
    signal_refinery_report = build_signal_refinery_report(
        runtime_state=runtime_state,
        trend_report=trend_report,
        write_runtime=False,
    )
    action_report = build_action_report(
        runtime_state=runtime_state,
        signal_refinery_report=signal_refinery_report,
        write_runtime=False,
    )

    decision_rows = []
    for index, row in enumerate(action_report["actions"], start=1):
        decision_rows.append(
            {
                "decision_id": f"decision_{index}",
                "ticker": row["ticker"],
                "signal_id": row["signal_id"],
                "action_type": row["action"],
                "approval_state": (
                    "APPROVED_BY_HUMAN_FOR_PAPER"
                    if row["action"] == "REVIEW_FOR_ENTRY"
                    else "PENDING_HUMAN_APPROVAL"
                ),
            }
        )

    _write_jsonl(scratch_path / "paper_decisions.jsonl", decision_rows)
    _write_jsonl(
        scratch_path / "paper_closes.jsonl",
        [
            {"close_id": "close_rtx", "ticker": "RTX"},
            {"close_id": "close_zim", "ticker": "ZIM"},
        ],
    )
    _write_json(
        scratch_path / "paper_positions.json",
        {
            "artifact_kind": "paper_positions_ledger",
            "positions": [],
            "open_position_count": 0,
        },
    )
    _write_jsonl(
        scratch_path / "paper_reconciliation_history.jsonl",
        [
            {"close_id": "close_rtx", "reconciliation_status": "fully_reconciled"},
            {"close_id": "close_zim", "reconciliation_status": "fully_reconciled"},
        ],
    )
    _write_json(
        scratch_path / "paper_reconciliation_summary.json",
        {
            "evidence_strength": "early_pattern",
        },
    )

    report = build_closure_deficit_report(
        runtime_state=runtime_state,
        action_report=action_report,
        signal_refinery_report=signal_refinery_report,
        packet_summary={
            "entry_review_candidate_names": ["RTX", "ZIM"],
            "transition_review_candidate_names": [],
        },
        decision_ledger_path=scratch_path / "paper_decisions.jsonl",
        close_ledger_path=scratch_path / "paper_closes.jsonl",
        paper_positions_path=scratch_path / "paper_positions.json",
        reconciliation_history_path=scratch_path / "paper_reconciliation_history.jsonl",
        reconciliation_summary_path=scratch_path / "paper_reconciliation_summary.json",
        write_runtime=False,
    )

    assert report["closure_deficit_state"] == "LOW_DEFICIT"
    assert report["closure_deficit_score"] is not None
    assert report["counts"]["insights_produced"] >= 2
    assert report["counts"]["actions_suggested"] == len(action_report["actions"])
    assert report["counts"]["actions_approved"] == 2
    assert report["counts"]["actions_closed"] == 2
    assert report["counts"]["actions_reconciled_with_sufficient_evidence"] == 2
    assert report["ratios"]["decision_capture_ratio"] == 1.0
    assert report["ratios"]["entry_approval_ratio"] == 1.0
    assert report["ratios"]["reconciliation_completion_ratio"] == 1.0
    assert report["ratios"]["evidence_sufficiency_ratio"] == 1.0
