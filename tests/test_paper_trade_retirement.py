import json
from pathlib import Path

import pytest

from scripts.paper_trade_retirement import evaluate_close_rule, retire_paper_trades
from scripts.runtime_common import build_runtime_state_from_scm_report_payload
from scripts.signal_conversion_monitor import build_signal_conversion_report


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, separators=(",", ":")) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_evaluate_close_rule_supports_bounded_reasons() -> None:
    position_row = {
        "position_id": "paper_position_rtx",
        "ticker": "RTX",
        "side": "BUY",
        "avg_entry_price": 100.0,
        "qty": 1.0,
        "opened_at": "2026-04-10T00:00:00+00:00",
    }

    target_eval = evaluate_close_rule(
        position_row=position_row,
        mark_row={
            "ok": True,
            "last_price": 104.0,
            "observed_at": "2026-04-22T00:00:00+00:00",
            "context_5d_change_pct": 2.0,
        },
    )
    assert target_eval["close_reason"] == "target_hit"

    stop_eval = evaluate_close_rule(
        position_row=position_row,
        mark_row={
            "ok": True,
            "last_price": 96.0,
            "observed_at": "2026-04-22T00:00:00+00:00",
            "context_5d_change_pct": -6.0,
        },
    )
    assert stop_eval["close_reason"] == "stop_hit"

    stale_eval = evaluate_close_rule(
        position_row=position_row,
        mark_row={
            "ok": True,
            "last_price": 100.4,
            "observed_at": "2026-04-22T00:00:00+00:00",
            "context_5d_change_pct": 0.1,
        },
    )
    assert stale_eval["close_reason"] == "stale_signal_timeout"

    no_data_eval = evaluate_close_rule(
        position_row=position_row,
        mark_row={"ok": False, "retrieval_error": "no_data"},
    )
    assert no_data_eval["close_reason"] == "no_data_unresolved"
    assert no_data_eval["eligible"] is False


def test_retire_paper_trades_closes_two_eligible_positions_and_writes_feedback(
    scratch_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIPELINE_ENABLE_PAPER_EXECUTION", "true")
    monkeypatch.setenv("PIPELINE_ENABLE_LIVE_EXECUTION", "false")

    runtime_state = build_runtime_state_from_scm_report_payload(
        build_signal_conversion_report()
    )

    positions_path = scratch_path / "paper_positions.json"
    decisions_path = scratch_path / "paper_decisions.jsonl"
    orders_path = scratch_path / "paper_orders.jsonl"
    fills_path = scratch_path / "paper_fills.jsonl"
    closes_path = scratch_path / "paper_closes.jsonl"
    marks_path = scratch_path / "external_market_marks.json"
    retirement_path = scratch_path / "paper_retirement_report.json"
    model_path = scratch_path / "model_upgrade_report.json"
    feedback_path = scratch_path / "post_trade_feedback.jsonl"

    positions_path.write_text(
        json.dumps(
            {
                "artifact_kind": "paper_positions_ledger",
                "positions": [
                    {
                        "position_id": "paper_position_rtx",
                        "decision_id": "paper_decision_rtx",
                        "paper_order_id": "paper_order_rtx",
                        "paper_fill_id": "paper_fill_rtx",
                        "signal_id": "SIG_RTX",
                        "ticker": "RTX",
                        "side": "BUY",
                        "avg_entry_price": 100.0,
                        "qty": 1.0,
                        "opened_at": "2026-04-10T00:00:00+00:00",
                        "latest_mark": 100.0,
                        "unrealized_pnl": 0.0,
                        "status": "OPEN",
                    },
                    {
                        "position_id": "paper_position_zim",
                        "decision_id": "paper_decision_zim",
                        "paper_order_id": "paper_order_zim",
                        "paper_fill_id": "paper_fill_zim",
                        "signal_id": "SIG_ZIM",
                        "ticker": "ZIM",
                        "side": "BUY",
                        "avg_entry_price": 50.0,
                        "qty": 1.0,
                        "opened_at": "2026-04-18T00:00:00+00:00",
                        "latest_mark": 50.0,
                        "unrealized_pnl": 0.0,
                        "status": "OPEN",
                    },
                    {
                        "position_id": "paper_position_tlt",
                        "decision_id": "paper_decision_tlt",
                        "paper_order_id": "paper_order_tlt",
                        "paper_fill_id": "paper_fill_tlt",
                        "signal_id": "SIG_TLT",
                        "ticker": "TLT",
                        "side": "BUY",
                        "avg_entry_price": 100.0,
                        "qty": 1.0,
                        "opened_at": "2026-04-10T00:00:00+00:00",
                        "latest_mark": 100.0,
                        "unrealized_pnl": 0.0,
                        "status": "OPEN",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    _write_jsonl(
        decisions_path,
        [
            {"decision_id": "paper_decision_rtx", "conviction_score": 0.8},
            {"decision_id": "paper_decision_zim", "conviction_score": 0.75},
            {"decision_id": "paper_decision_tlt", "conviction_score": 0.55},
        ],
    )
    _write_jsonl(orders_path, [])
    _write_jsonl(fills_path, [])
    _write_jsonl(closes_path, [])

    mark_map = {
        "RTX": {
            "last_price": 104.0,
            "currency": "USD",
            "previous_close": 103.0,
            "open": 103.5,
            "day_high": 105.0,
            "day_low": 102.5,
            "volume": 1000,
            "regular_market_time": "2026-04-22T12:00:00+00:00",
            "raw_history": [
                {"close": 99.0},
                {"close": 100.0},
                {"close": 101.0},
                {"close": 102.0},
                {"close": 103.0},
                {"close": 104.0},
            ],
        },
        "ZIM": {
            "last_price": 47.0,
            "currency": "USD",
            "previous_close": 48.0,
            "open": 48.0,
            "day_high": 48.5,
            "day_low": 46.5,
            "volume": 1200,
            "regular_market_time": "2026-04-22T12:00:00+00:00",
            "raw_history": [
                {"close": 53.0},
                {"close": 52.0},
                {"close": 51.0},
                {"close": 50.0},
                {"close": 49.0},
                {"close": 47.0},
            ],
        },
        "TLT": {
            "last_price": 100.2,
            "currency": "USD",
            "previous_close": 100.1,
            "open": 100.1,
            "day_high": 100.4,
            "day_low": 99.8,
            "volume": 900,
            "regular_market_time": "2026-04-22T12:00:00+00:00",
            "raw_history": [
                {"close": 100.0},
                {"close": 100.1},
                {"close": 100.0},
                {"close": 100.2},
                {"close": 100.1},
                {"close": 100.2},
            ],
        },
    }

    def fake_fetcher(ticker: str) -> dict:
        symbol = str(ticker).upper()
        return mark_map.get(
            symbol,
            {
                "last_price": 100.0,
                "currency": "USD",
                "previous_close": 100.0,
                "open": 100.0,
                "day_high": 100.0,
                "day_low": 100.0,
                "volume": 1,
                "regular_market_time": "2026-04-22T12:00:00+00:00",
                "raw_history": [{"close": 100.0}, {"close": 100.0}],
            },
        )

    summary = retire_paper_trades(
        runtime_state=runtime_state,
        fetcher=fake_fetcher,
        max_retirements=2,
        paper_positions_path=positions_path,
        external_marks_path=marks_path,
        retirement_report_path=retirement_path,
        model_upgrade_report_path=model_path,
        feedback_ledger_path=feedback_path,
        decision_ledger_path=decisions_path,
        order_ledger_path=orders_path,
        fill_ledger_path=fills_path,
        close_ledger_path=closes_path,
    )

    retirement_report = json.loads(retirement_path.read_text(encoding="utf-8"))
    model_report = json.loads(model_path.read_text(encoding="utf-8"))
    marks_report = json.loads(marks_path.read_text(encoding="utf-8"))
    closes = [
        json.loads(line)
        for line in closes_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    feedback_rows = [
        json.loads(line)
        for line in feedback_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    updated_positions = json.loads(positions_path.read_text(encoding="utf-8"))["positions"]

    assert summary["retired_trade_count"] == 2
    assert summary["operating_mode"] == "hybrid"
    assert summary["truth_origin"] == "external"

    assert marks_report["operating_mode"] == "hybrid"
    assert marks_report["truth_origin"] == "external"
    assert marks_report["success_count"] >= 3

    assert retirement_report["retired_trade_count"] == 2
    assert retirement_report["close_reason_counts"] == {
        "stop_hit": 1,
        "target_hit": 1,
    }

    assert len(closes) == 2
    assert len(feedback_rows) == 2
    assert {row["ticker"] for row in feedback_rows} == {"RTX", "ZIM"}
    assert all(row["mark_id"] for row in feedback_rows)
    assert all(row["close_id"] for row in feedback_rows)
    assert all(row["truth_origin"] == "external" for row in feedback_rows)

    assert any(row["ticker"] == "RTX" and row["realized_pnl"] == 4.0 for row in closes)
    assert any(row["ticker"] == "ZIM" and row["realized_pnl"] == -3.0 for row in closes)
    assert all(row.get("mark_id") for row in closes)

    assert len(updated_positions) == 1
    assert updated_positions[0]["ticker"] == "TLT"
    assert updated_positions[0]["latest_mark"] == 100.2
    assert updated_positions[0]["unrealized_pnl"] == 0.2

    assert model_report["retired_paper_trades"] == 2
    assert model_report["winners"] == 1
    assert model_report["losers"] == 1
    assert model_report["parameter_change_note"] == "insufficient_evidence_for_parameter_change"


def test_retirement_refuses_when_live_execution_enabled(
    scratch_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIPELINE_ENABLE_PAPER_EXECUTION", "true")
    monkeypatch.setenv("PIPELINE_ENABLE_LIVE_EXECUTION", "true")

    runtime_state = build_runtime_state_from_scm_report_payload(
        build_signal_conversion_report()
    )

    with pytest.raises(ValueError, match="live execution is enabled"):
        retire_paper_trades(
            runtime_state=runtime_state,
            paper_positions_path=scratch_path / "paper_positions.json",
            external_marks_path=scratch_path / "external_market_marks.json",
            retirement_report_path=scratch_path / "paper_retirement_report.json",
            model_upgrade_report_path=scratch_path / "model_upgrade_report.json",
            feedback_ledger_path=scratch_path / "post_trade_feedback.jsonl",
            decision_ledger_path=scratch_path / "paper_decisions.jsonl",
            order_ledger_path=scratch_path / "paper_orders.jsonl",
            fill_ledger_path=scratch_path / "paper_fills.jsonl",
            close_ledger_path=scratch_path / "paper_closes.jsonl",
        )
