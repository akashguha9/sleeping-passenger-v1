"""
End-to-end integration test for the reconcile_trade → Moltbook bridge.

Walks the same path the Reconciliation UI takes: log a manual trade, then
call ``reconcile_trade`` with a STOP_HIT / PARTIAL_TP_HIT / CLOSED
outcome.  Asserts that the response carries the Moltbook learning
status and that SQLite has the corresponding row — without ever calling
a broker or touching execution state.
"""
from __future__ import annotations

import pytest

import scripts.signal_inbox_api as api
import scripts.persistence as persistence


@pytest.fixture(autouse=True)
def _isolate_logs(tmp_path, monkeypatch):
    """Redirect JSONL audit paths so the operator's real logs stay clean."""
    monkeypatch.setattr(api, "MANUAL_TRADE_LOG", tmp_path / "manual_trades.jsonl")
    monkeypatch.setattr(api, "RECONCILIATIONS_LOG", tmp_path / "reconciliations.jsonl")
    try:
        import scripts.moltbook_api as mb_api
        monkeypatch.setattr(mb_api, "MOLTBOOK_LOG", tmp_path / "moltbook.jsonl")
    except ImportError:
        pass
    yield


def _log_trade(ticker: str, price: float, qty: float = 1.0) -> str:
    out = api.log_manual_trade(
        event_id=f"USER_{ticker}",
        ticker=ticker,
        side="BUY",
        quantity=qty,
        price=price,
        thesis=f"Operator long {ticker} for swing setup.",
    )
    assert out.get("broker_api_called") is False
    return out["trade_id"]


def test_stop_hit_reconcile_creates_moltbook_entry():
    trade_id = _log_trade("XOM", 105.0, qty=10.0)
    out = api.reconcile_trade(
        trade_id,
        actual_fill_price=98.5,
        actual_quantity=10.0,
        post_trade_outcome="STOPPED_OUT",
        stop_loss_hit=True,
        stop_loss_price=98.5,
        exit_reason="Stop-loss breached on close.",
    )
    assert out["status"] == "logged"
    assert out["broker_api_called"] is False
    assert out["ai_execution_count"] == 0
    assert out["moltbook_message"] == "Moltbook learning entry created"
    learning = out["moltbook_learning"]
    assert learning["event_type"] == "STOP_LOSS_HIT"
    assert learning["learning_direction"] == "MISTAKE_OR_INVALIDATION"
    rows = persistence.get_moltbook_entries(ticker="XOM", db_path=persistence.DB_PATH)
    assert len(rows) == 1
    assert rows[0]["event_type"] == "STOP_LOSS_HIT"
    assert rows[0]["trade_id"] == trade_id


def test_partial_tp_hit_reconcile_creates_success_entry():
    trade_id = _log_trade("ANET", 380.0, qty=10.0)
    out = api.reconcile_trade(
        trade_id,
        actual_fill_price=420.0,
        actual_quantity=7.0,
        post_trade_outcome="PARTIAL_TP",
        partial_take_profit_price=420.0,
        partial_take_profit_quantity=7.0,
        runner_quantity=3.0,
        take_profit_plan="70% TP / 30% runner",
    )
    assert out["moltbook_message"] == "Moltbook learning entry created"
    learning = out["moltbook_learning"]
    assert learning["event_type"] == "PARTIAL_TP_HIT"
    assert learning["learning_direction"] == "SUCCESS_PATTERN"


def test_closed_win_reconcile_creates_entry():
    trade_id = _log_trade("MSFT", 400.0, qty=2.0)
    out = api.reconcile_trade(
        trade_id,
        actual_fill_price=430.0,
        actual_quantity=2.0,
        post_trade_outcome="CLOSED_WIN",
    )
    assert out["moltbook_message"] == "Moltbook learning entry created"
    learning = out["moltbook_learning"]
    assert learning["event_type"] == "CLOSED"
    assert learning["learning_direction"] == "SUCCESS_PATTERN"


def test_double_save_does_not_duplicate():
    trade_id = _log_trade("DUP", 100.0, qty=2.0)
    args = dict(
        trade_id=trade_id,
        actual_fill_price=110.0,
        actual_quantity=2.0,
        post_trade_outcome="CLOSED_WIN",
    )
    first = api.reconcile_trade(**args)
    second = api.reconcile_trade(**args)
    assert first["moltbook_message"] == "Moltbook learning entry created"
    assert second["moltbook_message"] == "Moltbook learning entry already existed, updated safely"
    rows = persistence.get_moltbook_entries(ticker="DUP", db_path=persistence.DB_PATH)
    assert len(rows) == 1


def test_advisory_invariants_unchanged():
    trade_id = _log_trade("SAFE", 50.0)
    out = api.reconcile_trade(
        trade_id,
        actual_fill_price=55.0,
        actual_quantity=1.0,
        post_trade_outcome="CLOSED_WIN",
    )
    assert out["advisory_status"] == "ADVISORY_ONLY"
    assert out["execution_mode"] == "HUMAN_ONLY"
    assert out["execution_gate"] == "LOCKED"
    assert out["broker_api_called"] is False
    assert out["ai_execution_count"] == 0
    assert out["execution_permission"] is False
    learning = out["moltbook_learning"]
    assert learning["advisory_status"] == "ADVISORY_ONLY"
    assert learning["broker_api_called"] is False
