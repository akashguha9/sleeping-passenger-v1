import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.action_engine import build_action_report
from scripts.paper_execution import close_paper_position, sync_paper_execution
from scripts.runtime_common import build_runtime_state_from_scm_report_payload
from scripts.signal_conversion_monitor import build_signal_conversion_report


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def test_sync_records_decisions_even_when_paper_execution_disabled(
    scratch_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIPELINE_ENABLE_PAPER_EXECUTION", "false")
    monkeypatch.setenv("PIPELINE_ENABLE_LIVE_EXECUTION", "false")

    decisions_path = scratch_path / "paper_decisions.jsonl"
    orders_path = scratch_path / "paper_orders.jsonl"
    fills_path = scratch_path / "paper_fills.jsonl"
    positions_path = scratch_path / "paper_positions.json"

    report = sync_paper_execution(
        decision_ledger_path=decisions_path,
        order_ledger_path=orders_path,
        fill_ledger_path=fills_path,
        paper_positions_path=positions_path,
    )

    assert report["paper_execution_enabled"] is False
    assert report["decisions_recorded"] == 7
    assert report["orders_created"] == 0
    assert report["fills_recorded"] == 0
    assert report["positions_opened"] == 0

    decisions = _load_jsonl(decisions_path)
    assert len(decisions) == 7
    assert decisions[0]["artifact_kind"] == "paper_decision"
    assert decisions[0]["run_id"]
    assert decisions[0]["operating_mode"] == "seeded"
    assert decisions[0]["truth_origin"] == "seeded"
    assert decisions[0]["commit_hash"]
    assert decisions[0]["config_fingerprint"]


def test_sync_with_paper_enabled_creates_orders_fills_and_positions(
    scratch_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIPELINE_ENABLE_PAPER_EXECUTION", "true")
    monkeypatch.setenv("PIPELINE_ENABLE_LIVE_EXECUTION", "false")

    decisions_path = scratch_path / "paper_decisions.jsonl"
    orders_path = scratch_path / "paper_orders.jsonl"
    fills_path = scratch_path / "paper_fills.jsonl"
    positions_path = scratch_path / "paper_positions.json"

    runtime_state = build_runtime_state_from_scm_report_payload(
        build_signal_conversion_report(simulate_all_clear=True)
    )
    action_report = build_action_report(runtime_state=runtime_state, write_runtime=False)

    report = sync_paper_execution(
        runtime_state=runtime_state,
        action_report=action_report,
        decision_ledger_path=decisions_path,
        order_ledger_path=orders_path,
        fill_ledger_path=fills_path,
        paper_positions_path=positions_path,
        fill_price_overrides={"RTX": 101.5, "ZIM": 44.25},
    )

    assert report["paper_execution_enabled"] is True
    assert report["orders_created"] == 2
    assert report["fills_recorded"] == 2
    assert report["positions_opened"] == 2
    assert report["open_position_count"] == 2

    decisions = _load_jsonl(decisions_path)
    orders = _load_jsonl(orders_path)
    fills = _load_jsonl(fills_path)
    positions_payload = json.loads(positions_path.read_text(encoding="utf-8"))
    positions = positions_payload["positions"]

    assert len(decisions) == 7
    assert len(orders) == 2
    assert len(fills) == 2
    assert {row["ticker"] for row in orders} == {"RTX", "ZIM"}
    assert {row["ticker"] for row in fills} == {"RTX", "ZIM"}
    assert {row["ticker"] for row in positions} == {"RTX", "ZIM"}
    assert all(row["side"] == "BUY" for row in orders)
    assert all(row["position_id"] for row in positions)
    assert all(row["run_id"] for row in orders)
    assert all(row["run_id"] for row in fills)
    assert all(row["operating_mode"] == "paper_prepared" for row in orders)
    assert all(row["operating_mode"] == "paper_prepared" for row in fills)
    assert all(row["truth_origin"] == "synthetic" for row in orders)
    assert all(row["truth_origin"] == "synthetic" for row in fills)
    assert all(row["config_fingerprint"] for row in orders)
    assert all(row["config_fingerprint"] for row in fills)
    assert positions_payload["operating_mode"] == "paper_prepared"
    assert positions_payload["truth_origin"] == "synthetic"

    decision_by_id = {row["decision_id"]: row for row in decisions}
    order_by_id = {row["paper_order_id"]: row for row in orders}
    for fill in fills:
        order = order_by_id[fill["paper_order_id"]]
        assert fill["decision_id"] == order["decision_id"]
        assert order["decision_id"] in decision_by_id


def test_close_position_records_lineage_and_removes_open_position(
    scratch_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIPELINE_ENABLE_PAPER_EXECUTION", "true")
    monkeypatch.setenv("PIPELINE_ENABLE_LIVE_EXECUTION", "false")

    decisions_path = scratch_path / "paper_decisions.jsonl"
    orders_path = scratch_path / "paper_orders.jsonl"
    fills_path = scratch_path / "paper_fills.jsonl"
    closes_path = scratch_path / "paper_closes.jsonl"
    positions_path = scratch_path / "paper_positions.json"

    runtime_state = build_runtime_state_from_scm_report_payload(
        build_signal_conversion_report(simulate_all_clear=True)
    )
    action_report = build_action_report(runtime_state=runtime_state, write_runtime=False)
    sync_paper_execution(
        runtime_state=runtime_state,
        action_report=action_report,
        decision_ledger_path=decisions_path,
        order_ledger_path=orders_path,
        fill_ledger_path=fills_path,
        paper_positions_path=positions_path,
        fill_price_overrides={"RTX": 100.0, "ZIM": 40.0},
    )

    positions_payload = json.loads(positions_path.read_text(encoding="utf-8"))
    target = next(row for row in positions_payload["positions"] if row["ticker"] == "RTX")

    report = close_paper_position(
        position_id=target["position_id"],
        exit_price=104.0,
        close_reason="TARGET_REACHED",
        runtime_state=runtime_state,
        decision_ledger_path=decisions_path,
        order_ledger_path=orders_path,
        fill_ledger_path=fills_path,
        close_ledger_path=closes_path,
        paper_positions_path=positions_path,
    )

    closes = _load_jsonl(closes_path)
    updated_positions = json.loads(positions_path.read_text(encoding="utf-8"))["positions"]

    assert report["position_closed"] is True
    assert report["ticker"] == "RTX"
    assert report["realized_pnl"] == 4.0
    assert len(closes) == 1
    assert closes[0]["position_id"] == target["position_id"]
    assert closes[0]["decision_id"] == report["decision_id"]
    assert closes[0]["paper_order_id"] == report["paper_order_id"]
    assert closes[0]["paper_fill_id"] == report["paper_fill_id"]
    assert closes[0]["opening_decision_id"] == target["decision_id"]
    assert closes[0]["run_id"]
    assert closes[0]["operating_mode"] == "paper_prepared"
    assert closes[0]["truth_origin"] == "synthetic"
    assert closes[0]["config_fingerprint"]
    assert all(row["ticker"] != "RTX" for row in updated_positions)


def test_paper_execution_refuses_when_live_execution_enabled(
    scratch_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIPELINE_ENABLE_PAPER_EXECUTION", "true")
    monkeypatch.setenv("PIPELINE_ENABLE_LIVE_EXECUTION", "true")

    with pytest.raises(ValueError, match="live execution is enabled"):
        sync_paper_execution(
            decision_ledger_path=scratch_path / "paper_decisions.jsonl",
            order_ledger_path=scratch_path / "paper_orders.jsonl",
            fill_ledger_path=scratch_path / "paper_fills.jsonl",
            paper_positions_path=scratch_path / "paper_positions.json",
        )


def test_close_refuses_when_paper_execution_disabled(
    scratch_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIPELINE_ENABLE_PAPER_EXECUTION", "false")
    monkeypatch.setenv("PIPELINE_ENABLE_LIVE_EXECUTION", "false")

    positions_path = scratch_path / "paper_positions.json"
    positions_path.write_text(
        json.dumps(
            {
                "artifact_kind": "paper_positions_ledger",
                "positions": [
                    {
                        "position_id": "paper_position_test",
                        "decision_id": "paper_decision_test",
                        "paper_order_id": "paper_order_test",
                        "paper_fill_id": "paper_fill_test",
                        "signal_id": "SIG_TEST",
                        "ticker": "RTX",
                        "side": "BUY",
                        "avg_entry_price": 100.0,
                        "qty": 1.0,
                        "opened_at": "2026-04-22T00:00:00+00:00",
                        "latest_mark": 100.0,
                        "unrealized_pnl": 0.0,
                        "status": "OPEN",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="paper execution is disabled"):
        close_paper_position(
            position_id="paper_position_test",
            exit_price=101.0,
            close_reason="MANUAL_TEST",
            paper_positions_path=positions_path,
            decision_ledger_path=scratch_path / "paper_decisions.jsonl",
            order_ledger_path=scratch_path / "paper_orders.jsonl",
            fill_ledger_path=scratch_path / "paper_fills.jsonl",
            close_ledger_path=scratch_path / "paper_closes.jsonl",
        )


def test_paper_execution_cli_summary_smoke(
    scratch_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIPELINE_ENABLE_PAPER_EXECUTION", "false")
    monkeypatch.setenv("PIPELINE_ENABLE_LIVE_EXECUTION", "false")

    env = dict(os.environ)
    env["PIPELINE_ENABLE_PAPER_EXECUTION"] = "false"
    env["PIPELINE_ENABLE_LIVE_EXECUTION"] = "false"

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "paper_execution.py"), "sync", "--summary"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )

    lines = result.stdout.strip().splitlines()
    assert lines[0] == "Paper Execution Sync"
    assert "paper_execution_enabled=false" in lines
