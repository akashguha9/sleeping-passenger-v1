import json
from pathlib import Path

from scripts.operator_control import (
    build_operator_control_report,
    build_signal_admission_report,
    build_work_block_summary,
    close_work_block,
    evaluate_closure_threshold,
    load_active_work_block,
    load_operator_state,
    record_operator_state,
    record_work_block_event,
    start_work_block,
)
from scripts.pipeline_health_report import build_pipeline_health_report
from scripts.runtime_common import build_runtime_state_from_scm_report_payload
from scripts.signal_conversion_monitor import build_signal_conversion_report


def _runtime_state() -> dict:
    return build_runtime_state_from_scm_report_payload(build_signal_conversion_report())


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]


def test_signal_admission_gate_is_explicit_and_rejects_non_actionable_rows() -> None:
    report = build_signal_admission_report(_runtime_state(), write_runtime=False)
    decisions = {row["ticker"]: row for row in report["signals"]}

    assert report["admitted_count"] == 4
    assert set(report["admitted_tickers"]) == {"RTX", "TIP", "TLT", "ZIM"}
    assert set(report["rejected_tickers"]) == {"FCG", "GLD", "UNG"}
    assert decisions["GLD"]["admit"] is False
    assert decisions["GLD"]["rejection_dimensions"] == ["actionability"]
    assert decisions["RTX"]["admit"] is True
    assert decisions["TIP"]["dimension_product"] == 1
    assert decisions["RTX"]["row_key"] == "signal_id:SIG_2026_04_06_006"


def test_signal_admission_gate_keeps_missing_relevance_missing() -> None:
    report = build_signal_admission_report(
        {
            "source": "unit_test",
            "per_signal_attribution": [
                {
                    "signal_id": "SIG_2026_04_10_010",
                    "ticker": "ABC",
                    "status": "WATCHLIST",
                    "watchlist_tier": "PROMOTABLE",
                    "pre_entry_state": "BLOCKED_PROMOTABLE_CLEAN_CANDIDATE",
                }
            ],
        },
        write_runtime=False,
    )

    decision = report["signals"][0]
    assert decision["ce_score"] is None
    assert decision["admit"] is False
    assert decision["dimension_states"]["relevance"]["reason"] == "ce_score_unavailable"
    assert report["missing_relevance_count"] == 1


def test_signal_admission_gate_filters_by_row_key_not_ticker_only() -> None:
    report = build_signal_admission_report(
        {
            "source": "unit_test",
            "per_signal_attribution": [
                {
                    "signal_id": "SIG_2026_04_10_101",
                    "ticker": "DUP",
                    "status": "EXECUTED_CLEAN",
                    "ce_score": 0.7,
                },
                {
                    "signal_id": "SIG_2026_04_10_102",
                    "ticker": "DUP",
                    "status": "EXECUTED_CHAOS",
                    "ce_score": 0.2,
                },
            ],
        },
        write_runtime=False,
    )

    admitted_rows = [row for row in report["signals"] if row["admit"]]
    rejected_rows = [row for row in report["signals"] if not row["admit"]]
    assert len(admitted_rows) == 1
    assert len(rejected_rows) == 1
    assert report["admitted_row_keys"] == [admitted_rows[0]["row_key"]]
    assert report["rejected_row_keys"] == [rejected_rows[0]["row_key"]]


def test_signal_admission_gate_writes_summary_and_deduped_kill_log(
    scratch_path: Path,
) -> None:
    output_path = scratch_path / "signal_gate_summary.json"
    kill_log_path = scratch_path / "signal_kill_log.jsonl"

    first = build_signal_admission_report(
        _runtime_state(),
        output_path=output_path,
        kill_log_path=kill_log_path,
        write_runtime=True,
    )
    second = build_signal_admission_report(
        _runtime_state(),
        output_path=output_path,
        kill_log_path=kill_log_path,
        write_runtime=True,
    )

    summary = json.loads(output_path.read_text(encoding="utf-8"))
    kill_rows = _load_jsonl(kill_log_path)

    assert first["rejected_count"] == 3
    assert second["kill_log"]["appended_count"] == 0
    assert summary["artifact_kind"] == "signal_admission_gate_summary"
    assert len(kill_rows) == 3
    assert {row["ticker"] for row in kill_rows} == {"FCG", "GLD", "UNG"}
    assert all("row_key" in row for row in kill_rows)
    assert all("rejection_reasons" in row for row in kill_rows)
    assert all("timestamp" in row for row in kill_rows)
    assert all("summary" in row for row in kill_rows)
    assert all("rejection_reason" in row for row in kill_rows)
    assert all("objective_context" in row for row in kill_rows)


def test_manual_operator_state_stays_absent_without_manual_fields(
    scratch_path: Path,
) -> None:
    operator_state_path = scratch_path / "operator_state.json"

    state = record_operator_state(path=operator_state_path, write_runtime=True)

    assert state["configured"] is False
    assert operator_state_path.exists() is False
    assert load_operator_state(operator_state_path)["state_source"] == "manual_optional_absent"


def test_active_work_block_requires_real_fields_not_metadata_only(
    scratch_path: Path,
) -> None:
    active_block_path = scratch_path / "active_work_block.json"
    active_block_path.write_text(
        json.dumps({"artifact_kind": "active_work_block"}, indent=2),
        encoding="utf-8",
    )

    block = load_active_work_block(active_block_path)
    assert block["configured"] is False
    assert block["status"] == "inactive"


def test_closure_threshold_engine_is_transparent() -> None:
    coding_closed_with_output = evaluate_closure_threshold(
        block_type="coding",
        output_exists=True,
        validation_exists=False,
    )
    research_closed_with_report = evaluate_closure_threshold(
        block_type="research",
        report_exists=True,
    )

    assert coding_closed_with_output["closure_met"] is True
    assert coding_closed_with_output["minimum_evidence_count"] == 1
    assert coding_closed_with_output["evidence_found"] == ["output_exists"]
    assert research_closed_with_report["closure_met"] is True
    assert research_closed_with_report["evidence_found"] == ["report_exists"]
    assert research_closed_with_report["rule_source"] == "global_closure_threshold"


def test_work_block_events_produce_drift_and_closure_metrics(
    scratch_path: Path,
) -> None:
    active_block_path = scratch_path / "active_work_block.json"
    events_path = scratch_path / "operator_block_events.jsonl"

    start_work_block(
        objective="Implement operator control",
        success_metric="tests green",
        time_boundary="90m",
        non_goals=["rewrite trading flow"],
        active_task="wire gate",
        block_type="coding",
        path=active_block_path,
        events_path=events_path,
        write_runtime=True,
    )
    record_work_block_event(
        event_type="execution_started",
        path=active_block_path,
        events_path=events_path,
        write_runtime=True,
    )
    record_work_block_event(
        event_type="context_switch",
        reason="checked adjacent module",
        path=active_block_path,
        events_path=events_path,
        write_runtime=True,
    )
    record_work_block_event(
        event_type="decision_reopened",
        reason="changed insertion point after audit",
        path=active_block_path,
        events_path=events_path,
        write_runtime=True,
    )
    close_work_block(
        output_exists=True,
        validation_exists=True,
        path=active_block_path,
        events_path=events_path,
        write_runtime=True,
    )

    start_work_block(
        objective="Second block",
        success_metric="decide",
        time_boundary="30m",
        non_goals=[],
        active_task="probe alternative",
        block_type="research",
        block_id="block_manual_2",
        path=active_block_path,
        events_path=events_path,
        write_runtime=True,
    )
    record_work_block_event(
        event_type="execution_started",
        block_id="block_manual_2",
        path=active_block_path,
        events_path=events_path,
        write_runtime=True,
    )
    close_work_block(
        block_id="block_manual_2",
        abandoned=True,
        reason="stopped before closure",
        path=active_block_path,
        events_path=events_path,
        write_runtime=True,
    )

    summary = build_work_block_summary(
        events_path=events_path,
        active_block_path=active_block_path,
    )

    assert summary["selected_block_count"] == 2
    assert summary["total_execution_blocks"] == 2
    assert summary["closed_block_count"] == 1
    assert summary["abandoned_block_count"] == 1
    assert summary["mid_block_switches"] == 1
    assert summary["reopened_decisions"] == 1
    assert summary["drift_rate"] == 0.5
    assert summary["closure_ratio"] == 0.5


def test_operator_control_report_surfaces_manual_state_and_phase_scores(
    scratch_path: Path,
) -> None:
    operator_state_path = scratch_path / "operator_state.json"
    active_block_path = scratch_path / "active_work_block.json"
    events_path = scratch_path / "operator_block_events.jsonl"

    record_operator_state(
        active_objective="Ship operator control MVP",
        active_task="document behavior",
        operator_mode="focused",
        baseline_score=0.42,
        current_score=0.58,
        peak_score=0.73,
        recent_scores=[0.42, 0.58, 0.73],
        instability_reasons=["manual audit pending"],
        notes=["manual-only state"],
        path=operator_state_path,
        write_runtime=True,
    )
    start_work_block(
        objective="Ship operator control MVP",
        success_metric="phase report exists",
        time_boundary="60m",
        non_goals=["add live inference"],
        active_task="phase balance",
        block_type="feature",
        path=active_block_path,
        events_path=events_path,
        write_runtime=True,
    )
    record_work_block_event(
        event_type="execution_started",
        path=active_block_path,
        events_path=events_path,
        write_runtime=True,
    )
    close_work_block(
        output_exists=True,
        validation_exists=True,
        path=active_block_path,
        events_path=events_path,
        write_runtime=True,
    )

    report = build_operator_control_report(
        operator_state_path=operator_state_path,
        gate_summary=build_signal_admission_report(_runtime_state(), write_runtime=False),
        block_summary=build_work_block_summary(
            events_path=events_path,
            active_block_path=active_block_path,
        ),
        active_block_path=active_block_path,
        test_status={"passed": True},
        write_runtime=False,
    )

    assert report["manual_operator_state"]["operator_mode"] == "focused"
    assert report["top_down_constraint_header"]["objective"] == "Ship operator control MVP"
    assert report["baseline_vs_peak"]["state"] == "between_baseline_and_peak"
    assert report["phase_balance"]["phase_1_self_alignment"]["score"] is not None
    assert report["phase_balance"]["phase_2_selective_expansion"]["score"] is not None
    assert report["phase_balance"]["phase_3_system_building"]["score"] is not None
    assert report["phase_balance"]["phase_1_self_alignment"]["score_state"] == "observed_proxy_blend"


def test_operator_control_report_keeps_sparse_phase_scores_null() -> None:
    report = build_operator_control_report(
        gate_summary={},
        block_summary={},
        test_status={},
        write_runtime=False,
    )

    assert report["phase_balance"]["phase_1_self_alignment"]["score"] is None
    assert report["phase_balance"]["phase_2_selective_expansion"]["score"] is None
    assert report["phase_balance"]["phase_3_system_building"]["score"] is None
    assert report["phase_balance"]["phase_1_self_alignment"]["score_state"] == "insufficient_evidence"


def test_operator_control_report_writes_phase_balance_artifacts(
    scratch_path: Path,
) -> None:
    balance_path = scratch_path / "operator_phase_balance.json"
    report_path = scratch_path / "operator_phase_report.json"

    report = build_operator_control_report(
        gate_summary=build_signal_admission_report(_runtime_state(), write_runtime=False),
        block_summary={},
        test_status={"passed": True},
        output_balance_path=balance_path,
        output_report_path=report_path,
        write_runtime=True,
    )

    balance_payload = json.loads(balance_path.read_text(encoding="utf-8"))
    report_payload = json.loads(report_path.read_text(encoding="utf-8"))

    assert report["artifact_kind"] == "operator_control_report"
    assert balance_payload["artifact_kind"] == "operator_phase_balance"
    assert "phase_balance" in balance_payload
    assert report_payload["artifact_kind"] == "operator_control_report"


def test_pipeline_health_report_includes_operator_control() -> None:
    payload = build_pipeline_health_report(
        include_tests=False,
        write_runtime=False,
        runtime_state=_runtime_state(),
    )

    assert payload["operator_control"]["signal_admission_gate"]["rejected_count"] == 3
    assert "phase_balance" in payload["operator_control"]
    assert "operator_pressure_state" in payload
    assert "operator_state" not in payload
