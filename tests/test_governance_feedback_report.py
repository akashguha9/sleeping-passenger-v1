import json
from pathlib import Path

import scripts.governance_feedback_report as governance_feedback_report
from scripts.action_engine import build_action_report
from scripts.runtime_common import build_runtime_state_from_scm_report_payload
from scripts.signal_conversion_monitor import build_signal_conversion_report


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    body = "\n".join(json.dumps(row, separators=(",", ":")) for row in rows)
    if body:
        body += "\n"
    path.write_text(body, encoding="utf-8")


def test_governance_feedback_report_summarizes_gates_and_overrides(
    scratch_path: Path,
    monkeypatch,
) -> None:
    runtime_state = build_runtime_state_from_scm_report_payload(
        build_signal_conversion_report(simulate_all_clear=True)
    )
    action_report = build_action_report(runtime_state=runtime_state, write_runtime=False)

    override_path = scratch_path / "operator_overrides.jsonl"
    operator_path = scratch_path / "operator_quality_feedback.jsonl"
    model_path = scratch_path / "model_quality_feedback.jsonl"
    interaction_path = scratch_path / "interaction_quality_feedback.jsonl"
    reconciliation_summary_path = scratch_path / "paper_reconciliation_summary.json"
    output_path = scratch_path / "governance_feedback_report.json"

    _write_jsonl(
        override_path,
        [
            {
                "override_id": "override_1",
                "override_classification": "defer_execution",
                "manual_fpeg_state": "pass",
                "manual_fpeg_score": 1.0,
            }
        ],
    )
    _write_jsonl(
        operator_path,
        [{"override_id": "override_1", "operator_quality_score": 0.92, "operator_quality_state": "disciplined"}],
    )
    _write_jsonl(
        model_path,
        [{"override_id": "override_1", "model_quality_score": 0.81, "model_quality_state": "clear"}],
    )
    _write_jsonl(
        interaction_path,
        [{"override_id": "override_1", "interaction_quality_score": 0.88, "interaction_quality_state": "good"}],
    )
    reconciliation_summary_path.write_text(
        json.dumps(
            {
                "total_closed_paper_trades": 2,
                "evidence_strength": "insufficient_evidence",
                "parameter_change_note": "insufficient_evidence_for_parameter_change",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(governance_feedback_report, "OPERATOR_OVERRIDE_LEDGER_PATH", override_path)
    monkeypatch.setattr(governance_feedback_report, "OPERATOR_FEEDBACK_LEDGER_PATH", operator_path)
    monkeypatch.setattr(governance_feedback_report, "MODEL_FEEDBACK_LEDGER_PATH", model_path)
    monkeypatch.setattr(governance_feedback_report, "INTERACTION_FEEDBACK_LEDGER_PATH", interaction_path)

    report = governance_feedback_report.build_governance_feedback_report(
        runtime_state=runtime_state,
        action_report=action_report,
        reconciliation_summary_path=reconciliation_summary_path,
        output_path=output_path,
        write_runtime=True,
    )

    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["gate_usage"]["total_action_count"] == len(action_report["actions"])
    assert report["override_summary"]["total_override_count"] == 1
    assert report["interaction_quality_summary"]["average_score"] == 0.88
    assert report["automation_readiness"]["current_stage"] == "suggestion_only"
    assert report["automation_readiness"]["eligible_for_limited_delegation"] is False
    assert "manual_approval_required_by_design" in report["automation_readiness"]["blocking_reasons"]
    assert written["artifact_kind"] == "governance_feedback_report"
