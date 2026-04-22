import json
from pathlib import Path

import pytest

from scripts.paper_reconciliation import (
    assign_reconciliation_status,
    build_reconciliation_row,
    classify_evidence_strength,
    lineage_completeness_score,
    run_paper_reconciliation,
)
from scripts.runtime_common import build_runtime_state_from_scm_report_payload
from scripts.signal_conversion_monitor import build_signal_conversion_report


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    body = "\n".join(json.dumps(row, separators=(",", ":")) for row in rows)
    if body:
        body += "\n"
    path.write_text(body, encoding="utf-8")


def _runtime_state() -> dict:
    return build_runtime_state_from_scm_report_payload(build_signal_conversion_report())


def _marks_payload() -> dict:
    return {
        "artifact_kind": "external_market_marks",
        "source_name": "yahoo_finance",
        "fetched_at": "2026-04-22T12:00:00+00:00",
        "success_count": 2,
        "failure_count": 0,
        "marks": [
            {
                "mark_id": "mark_rtx",
                "ticker": "RTX",
                "ok": True,
                "source_name": "yahoo_finance",
                "fetched_at": "2026-04-22T12:00:00+00:00",
                "staleness_classification": "fresh",
                "last_price": 104.0,
            },
            {
                "mark_id": "mark_zim",
                "ticker": "ZIM",
                "ok": True,
                "source_name": "yahoo_finance",
                "fetched_at": "2026-04-22T12:00:00+00:00",
                "staleness_classification": "fresh",
                "last_price": 47.0,
            },
        ],
    }


def test_lineage_completeness_score_fraction() -> None:
    row = {
        "signal_id": "SIG_1",
        "decision_id": "DEC_1",
        "paper_order_id": "ORD_1",
        "paper_fill_id": "FIL_1",
        "position_id": "POS_1",
        "close_id": "CLOSE_1",
        "mark_id": "",
    }

    assert lineage_completeness_score(row) == 0.857


def test_assign_reconciliation_status_variants() -> None:
    close_row = {
        "opening_decision_id": "DEC_1",
        "opening_paper_order_id": "ORD_1",
        "opening_paper_fill_id": "FIL_1",
    }
    assert (
        assign_reconciliation_status(["missing_mark"], [], close_row) == "missing_mark"
    )
    assert (
        assign_reconciliation_status(["missing_open_fill"], [], close_row) == "missing_fill"
    )
    assert (
        assign_reconciliation_status([], ["close_reason"], close_row)
        == "missing_close_context"
    )
    assert (
        assign_reconciliation_status(["mark_error"], [], close_row)
        == "data_gap_unresolved"
    )
    assert (
        assign_reconciliation_status([], [], {"opening_decision_id": "", "opening_paper_order_id": "", "opening_paper_fill_id": ""})
        == "legacy_incomplete"
    )


def test_build_reconciliation_row_with_missing_mark_and_gap_flags() -> None:
    runtime_state = _runtime_state()
    close_row = {
        "close_id": "close_1",
        "position_id": "pos_1",
        "ticker": "RTX",
        "signal_id": "SIG_RTX",
        "opening_decision_id": "open_decision_1",
        "opening_paper_order_id": "open_order_1",
        "opening_paper_fill_id": "open_fill_1",
        "paper_fill_id": "close_fill_1",
        "paper_order_id": "close_order_1",
        "decision_id": "close_decision_1",
        "exit_price": 104.0,
        "closed_at": "2026-04-22T12:00:00+00:00",
        "close_reason": "target_hit",
        "realized_pnl": 4.0,
        "run_id": "run_close_1",
        "truth_origin": "external",
        "operating_mode": "hybrid",
    }
    decisions = {
        "open_decision_1": {
            "decision_id": "open_decision_1",
            "entry_light_score": 0.54,
            "entry_shadow_score": 0.46,
            "entry_moon_phase": "quarter",
            "entry_temporal_position": 0.42,
            "entry_crowding_score": 0.31,
            "entry_light_velocity": 0.04,
            "entry_shadow_velocity": -0.04,
        }
    }
    orders = {"open_order_1": {"paper_order_id": "open_order_1", "side": "BUY", "requested_qty": 1.0}}
    fills = {"open_fill_1": {"paper_fill_id": "open_fill_1", "fill_price": 100.0, "fill_qty": 1.0, "filled_at": "2026-04-20T12:00:00+00:00"}}

    row = build_reconciliation_row(
        close_row=close_row,
        decisions_by_id=decisions,
        orders_by_id=orders,
        fills_by_id=fills,
        feedback_by_close_id={},
        marks_by_id={},
        marks_by_ticker={},
        runtime_state=runtime_state,
    )

    assert row["reconciliation_status"] == "missing_mark"
    assert "missing_mark" in row["data_gap_flags"]
    assert "missing_feedback" in row["data_gap_flags"]
    assert row["lineage_completeness_score"] < 1.0
    assert row["execution_context"] == "paper_simulated"
    assert row["entry_light_score"] == 0.54
    assert row["entry_moon_phase"] == "quarter"


def test_classify_evidence_strength_thresholds() -> None:
    assert classify_evidence_strength(0) == "insufficient_evidence"
    assert classify_evidence_strength(6) == "weak_signal"
    assert classify_evidence_strength(12) == "early_pattern"
    assert classify_evidence_strength(25) == "moderate_pattern"


def test_run_paper_reconciliation_creates_history_and_summary_without_duplicates(
    scratch_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIPELINE_ENABLE_LIVE_EXECUTION", "false")

    runtime_state = _runtime_state()
    closes_path = scratch_path / "paper_closes.jsonl"
    decisions_path = scratch_path / "paper_decisions.jsonl"
    orders_path = scratch_path / "paper_orders.jsonl"
    fills_path = scratch_path / "paper_fills.jsonl"
    feedback_path = scratch_path / "post_trade_feedback.jsonl"
    marks_path = scratch_path / "external_market_marks.json"
    history_path = scratch_path / "paper_reconciliation_history.jsonl"
    summary_path = scratch_path / "paper_reconciliation_summary.json"
    report_path = scratch_path / "paper_reconciliation_report.json"

    _write_jsonl(
        decisions_path,
        [
            {
                "decision_id": "open_decision_rtx",
                "conviction_score": 0.8,
                "entry_light_score": 0.63,
                "entry_shadow_score": 0.37,
                "entry_moon_phase": "gibbous",
                "entry_temporal_position": 0.58,
                "entry_crowding_score": 0.41,
                "entry_light_velocity": 0.05,
                "entry_shadow_velocity": -0.05,
            },
            {
                "decision_id": "open_decision_zim",
                "conviction_score": 0.7,
                "entry_light_score": 0.82,
                "entry_shadow_score": 0.18,
                "entry_moon_phase": "full_moon",
                "entry_temporal_position": 0.79,
                "entry_crowding_score": 0.84,
                "entry_light_velocity": 0.02,
                "entry_shadow_velocity": -0.02,
            },
        ],
    )
    _write_jsonl(
        orders_path,
        [
            {"paper_order_id": "open_order_rtx", "side": "BUY", "requested_qty": 1.0},
            {"paper_order_id": "open_order_zim", "side": "BUY", "requested_qty": 1.0},
        ],
    )
    _write_jsonl(
        fills_path,
        [
            {"paper_fill_id": "open_fill_rtx", "fill_price": 100.0, "fill_qty": 1.0, "filled_at": "2026-04-20T12:00:00+00:00"},
            {"paper_fill_id": "open_fill_zim", "fill_price": 50.0, "fill_qty": 1.0, "filled_at": "2026-04-18T12:00:00+00:00"},
        ],
    )
    _write_jsonl(
        closes_path,
        [
            {
                "close_id": "close_rtx",
                "position_id": "pos_rtx",
                "ticker": "RTX",
                "signal_id": "SIG_RTX",
                "opening_decision_id": "open_decision_rtx",
                "opening_paper_order_id": "open_order_rtx",
                "opening_paper_fill_id": "open_fill_rtx",
                "decision_id": "close_decision_rtx",
                "paper_order_id": "close_order_rtx",
                "paper_fill_id": "close_fill_rtx",
                "mark_id": "mark_rtx",
                "mark_source_name": "yahoo_finance",
                "mark_fetched_at": "2026-04-22T12:00:00+00:00",
                "mark_staleness_classification": "fresh",
                "exit_price": 104.0,
                "closed_at": "2026-04-22T12:00:00+00:00",
                "close_reason": "target_hit",
                "realized_pnl": 4.0,
                "run_id": "run_close_rtx",
                "truth_origin": "external",
                "operating_mode": "hybrid",
            },
            {
                "close_id": "close_zim",
                "position_id": "pos_zim",
                "ticker": "ZIM",
                "signal_id": "SIG_ZIM",
                "opening_decision_id": "open_decision_zim",
                "opening_paper_order_id": "open_order_zim",
                "opening_paper_fill_id": "open_fill_zim",
                "decision_id": "close_decision_zim",
                "paper_order_id": "close_order_zim",
                "paper_fill_id": "close_fill_zim",
                "mark_id": "mark_zim",
                "mark_source_name": "yahoo_finance",
                "mark_fetched_at": "2026-04-22T12:00:00+00:00",
                "mark_staleness_classification": "fresh",
                "exit_price": 47.0,
                "closed_at": "2026-04-22T12:00:00+00:00",
                "close_reason": "stop_hit",
                "realized_pnl": -3.0,
                "run_id": "run_close_zim",
                "truth_origin": "external",
                "operating_mode": "hybrid",
            },
        ],
    )
    _write_jsonl(
        feedback_path,
        [
            {
                "close_id": "close_rtx",
                "mark_id": "mark_rtx",
                "thesis_state": "confirmed",
                "confidence_calibration_note": "aligned",
                "source_quality_notes": "Yahoo note",
                "realized_return_pct": 4.0,
                "holding_period_days": 2.0,
                "entry_light_score": 0.63,
                "entry_shadow_score": 0.37,
                "entry_moon_phase": "gibbous",
                "entry_temporal_position": 0.58,
                "entry_crowding_score": 0.41,
                "entry_light_velocity": 0.05,
                "entry_shadow_velocity": -0.05,
                "truth_origin": "external",
                "operating_mode": "hybrid",
            },
            {
                "close_id": "close_zim",
                "mark_id": "mark_zim",
                "thesis_state": "invalidated",
                "confidence_calibration_note": "missed",
                "source_quality_notes": "Yahoo note",
                "realized_return_pct": -6.0,
                "holding_period_days": 4.0,
                "entry_light_score": 0.82,
                "entry_shadow_score": 0.18,
                "entry_moon_phase": "full_moon",
                "entry_temporal_position": 0.79,
                "entry_crowding_score": 0.84,
                "entry_light_velocity": 0.02,
                "entry_shadow_velocity": -0.02,
                "truth_origin": "external",
                "operating_mode": "hybrid",
            },
        ],
    )
    marks_path.write_text(json.dumps(_marks_payload()), encoding="utf-8")

    first = run_paper_reconciliation(
        runtime_state=runtime_state,
        close_ledger_path=closes_path,
        decision_ledger_path=decisions_path,
        order_ledger_path=orders_path,
        fill_ledger_path=fills_path,
        feedback_ledger_path=feedback_path,
        external_marks_path=marks_path,
        history_path=history_path,
        summary_path=summary_path,
        report_path=report_path,
    )
    second = run_paper_reconciliation(
        runtime_state=runtime_state,
        close_ledger_path=closes_path,
        decision_ledger_path=decisions_path,
        order_ledger_path=orders_path,
        fill_ledger_path=fills_path,
        feedback_ledger_path=feedback_path,
        external_marks_path=marks_path,
        history_path=history_path,
        summary_path=summary_path,
        report_path=report_path,
    )

    history_rows = [
        json.loads(line)
        for line in history_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert first["history_row_count"] == 2
    assert first["new_history_rows"] == 2
    assert second["history_row_count"] == 2
    assert second["new_history_rows"] == 0
    assert len(history_rows) == 2
    assert {row["close_id"] for row in history_rows} == {"close_rtx", "close_zim"}
    assert all(row["reconciliation_status"] == "fully_reconciled" for row in history_rows)
    assert all(row["parameter_change_note"] == "insufficient_evidence_for_parameter_change" for row in history_rows)
    rtx_row = next(row for row in history_rows if row["close_id"] == "close_rtx")
    assert rtx_row["entry_light_score"] == 0.63
    assert rtx_row["entry_moon_phase"] == "gibbous"
    assert rtx_row["entry_temporal_position"] == 0.58
    assert rtx_row["entry_crowding_score"] == 0.41

    assert summary["total_closed_paper_trades"] == 2
    assert summary["win_rate"] == 0.5
    assert summary["loser_rate"] == 0.5
    assert summary["average_realized_return_pct"] == -1.0
    assert summary["median_realized_return_pct"] == -1.0
    assert summary["average_winner_return_pct"] == 4.0
    assert summary["average_loser_return_pct"] == -6.0
    assert summary["expectancy_return_pct"] == -1.0
    assert summary["average_holding_period_days"] == 3.0
    assert summary["close_reason_distribution"] == {"target_hit": 1, "stop_hit": 1}
    assert summary["stale_signal_rate"] == 0.0
    assert summary["invalidation_rate"] == 0.5
    assert summary["unresolved_data_gap_rate"] == 0.0
    assert summary["sample_size_for_learning"] == 2
    assert summary["evidence_strength"] == "insufficient_evidence"
    assert summary["parameter_change_eligible"] is False
    assert summary["parameter_change_note"] == "insufficient_evidence_for_parameter_change"
    assert summary["leakage_diagnostics"]["signal_to_fill_drift_avg_bps"] is None
    assert report["history_row_count"] == 2
    assert report["operating_mode"] == "hybrid"
    assert report["truth_origin"] == "external"


def test_run_paper_reconciliation_handles_unresolved_gap_rows(
    scratch_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIPELINE_ENABLE_LIVE_EXECUTION", "false")
    runtime_state = _runtime_state()

    closes_path = scratch_path / "paper_closes.jsonl"
    decisions_path = scratch_path / "paper_decisions.jsonl"
    orders_path = scratch_path / "paper_orders.jsonl"
    fills_path = scratch_path / "paper_fills.jsonl"
    feedback_path = scratch_path / "post_trade_feedback.jsonl"
    marks_path = scratch_path / "external_market_marks.json"
    history_path = scratch_path / "paper_reconciliation_history.jsonl"
    summary_path = scratch_path / "paper_reconciliation_summary.json"
    report_path = scratch_path / "paper_reconciliation_report.json"

    _write_jsonl(decisions_path, [{"decision_id": "open_decision_gap"}])
    _write_jsonl(orders_path, [{"paper_order_id": "open_order_gap", "side": "BUY", "requested_qty": 1.0}])
    _write_jsonl(fills_path, [])
    _write_jsonl(
        closes_path,
        [
            {
                "close_id": "close_gap",
                "position_id": "pos_gap",
                "ticker": "RTX",
                "signal_id": "SIG_GAP",
                "opening_decision_id": "open_decision_gap",
                "opening_paper_order_id": "open_order_gap",
                "opening_paper_fill_id": "open_fill_gap",
                "decision_id": "close_decision_gap",
                "paper_order_id": "close_order_gap",
                "paper_fill_id": "close_fill_gap",
                "exit_price": 101.0,
                "closed_at": "2026-04-22T12:00:00+00:00",
                "close_reason": "target_hit",
                "realized_pnl": 1.0,
                "run_id": "run_gap",
                "truth_origin": "seeded",
                "operating_mode": "seeded",
            }
        ],
    )
    _write_jsonl(feedback_path, [])
    marks_path.write_text(json.dumps({"success_count": 0, "marks": []}), encoding="utf-8")

    run_paper_reconciliation(
        runtime_state=runtime_state,
        close_ledger_path=closes_path,
        decision_ledger_path=decisions_path,
        order_ledger_path=orders_path,
        fill_ledger_path=fills_path,
        feedback_ledger_path=feedback_path,
        external_marks_path=marks_path,
        history_path=history_path,
        summary_path=summary_path,
        report_path=report_path,
    )

    history_rows = [
        json.loads(line)
        for line in history_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    assert len(history_rows) == 1
    assert history_rows[0]["reconciliation_status"] == "missing_mark"
    assert "missing_mark" in history_rows[0]["data_gap_flags"]
    assert "missing_open_fill" in history_rows[0]["data_gap_flags"]
    assert summary["unresolved_data_gap_rate"] == 1.0


def test_reconciliation_refuses_when_live_execution_enabled(
    scratch_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIPELINE_ENABLE_LIVE_EXECUTION", "true")

    with pytest.raises(ValueError, match="live execution is enabled"):
        run_paper_reconciliation(
            runtime_state=_runtime_state(),
            close_ledger_path=scratch_path / "paper_closes.jsonl",
            decision_ledger_path=scratch_path / "paper_decisions.jsonl",
            order_ledger_path=scratch_path / "paper_orders.jsonl",
            fill_ledger_path=scratch_path / "paper_fills.jsonl",
            feedback_ledger_path=scratch_path / "post_trade_feedback.jsonl",
            external_marks_path=scratch_path / "external_market_marks.json",
            history_path=scratch_path / "paper_reconciliation_history.jsonl",
            summary_path=scratch_path / "paper_reconciliation_summary.json",
            report_path=scratch_path / "paper_reconciliation_report.json",
        )
