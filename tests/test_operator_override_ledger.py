import json
from pathlib import Path

from scripts.action_engine import build_action_report
from scripts.operator_override_ledger import record_operator_override
from scripts.runtime_common import build_runtime_state_from_scm_report_payload
from scripts.signal_conversion_monitor import build_signal_conversion_report


def _load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]


def test_record_operator_override_writes_all_feedback_ledgers(
    scratch_path: Path,
) -> None:
    runtime_state = build_runtime_state_from_scm_report_payload(
        build_signal_conversion_report(simulate_all_clear=True)
    )
    action_report = build_action_report(runtime_state=runtime_state, write_runtime=False)

    override_path = scratch_path / "operator_overrides.jsonl"
    operator_path = scratch_path / "operator_quality_feedback.jsonl"
    model_path = scratch_path / "model_quality_feedback.jsonl"
    interaction_path = scratch_path / "interaction_quality_feedback.jsonl"

    report = record_operator_override(
        ticker="RTX",
        override_action="MONITOR",
        why_this_move="Preserve discretion while waiting for manual entry review.",
        trigger="Review-ready candidate should still pass manual checklist.",
        invalidation="Cancel the idea if validation weakens or price structure fails.",
        regime="review_ready",
        why_now="GSCE and REALM_BIS both cleared in the simulated state.",
        operator_id="operator_alpha",
        confidence_source="internal_evidence",
        runtime_state=runtime_state,
        action_report=action_report,
        override_ledger_path=override_path,
        operator_feedback_path=operator_path,
        model_feedback_path=model_path,
        interaction_feedback_path=interaction_path,
    )

    override_rows = _load_jsonl(override_path)
    operator_rows = _load_jsonl(operator_path)
    model_rows = _load_jsonl(model_path)
    interaction_rows = _load_jsonl(interaction_path)

    assert report["override_classification"] == "defer_execution"
    assert report["manual_fpeg_state"] == "pass"
    assert len(override_rows) == 1
    assert len(operator_rows) == 1
    assert len(model_rows) == 1
    assert len(interaction_rows) == 1
    assert override_rows[0]["override_id"] == operator_rows[0]["override_id"]
    assert override_rows[0]["override_id"] == model_rows[0]["override_id"]
    assert override_rows[0]["override_id"] == interaction_rows[0]["override_id"]
    assert override_rows[0]["approval_state"] == "MANUAL_OVERRIDE_LOGGED"
    assert override_rows[0]["human_execution_required"] is True
    assert interaction_rows[0]["interaction_quality_state"] in {"good", "watch", "poor"}
