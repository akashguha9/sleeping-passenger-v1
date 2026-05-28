"""
End-to-end integration test for the reconcile_trade → Moltbook bridge.

Walks the same path the Reconciliation UI takes: log a manual trade, then
call ``reconcile_trade`` with a STOP_HIT / PARTIAL_TP_HIT / CLOSED
outcome.  Asserts that the response carries the Moltbook learning
status and that SQLite has the corresponding row — without ever calling
a broker or touching execution state.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.signal_inbox_api as api
import scripts.moltbook_learning_bridge as bridge
import scripts.persistence as persistence


def _write_holdings(path: Path, normalized_tickers: tuple[str, ...]) -> Path:
    """Write a fixture verified-holdings file with the given OPEN tickers."""
    path.write_text(
        json.dumps(
            {
                "operator_note": "test fixture — fixture-controlled holdings",
                "positions": [
                    {
                        "ticker": t,
                        "normalized_ticker": t,
                        "status": "OPEN",
                        "quantity": 1.0,
                        "entry_price": 100.0,
                    }
                    for t in normalized_tickers
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture(autouse=True)
def _isolate_logs(tmp_path, monkeypatch):
    """Isolate every runtime side-channel so a test never reads stale state.

    Beyond the JSONL audit paths, this pins:
      * ``persistence.DB_PATH`` to a fresh temp SQLite DB (so Moltbook
        reads/writes never touch ``runtime/mvp_local.db``), and
      * ``moltbook_learning_bridge._DEFAULT_VERIFIED_HOLDINGS_PATH`` to a
        fixture holdings file that *does* list the tested tickers as OPEN.

    The holdings file deliberately contains XOM / ANET / MSFT so the
    verified-holdings cross-check is genuinely ACTIVE — the integration
    tests below therefore prove the learning-worthiness gate, not an
    accidentally-empty holdings file.
    """
    monkeypatch.setattr(api, "MANUAL_TRADE_LOG", tmp_path / "manual_trades.jsonl")
    monkeypatch.setattr(api, "RECONCILIATIONS_LOG", tmp_path / "reconciliations.jsonl")
    try:
        import scripts.moltbook_api as mb_api
        monkeypatch.setattr(mb_api, "MOLTBOOK_LOG", tmp_path / "moltbook.jsonl")
    except ImportError:
        pass

    db = tmp_path / "reconcile_moltbook.db"
    persistence.init_schema(db)
    monkeypatch.setattr(persistence, "DB_PATH", db)

    holdings = _write_holdings(
        tmp_path / "verified_current_holdings.json", ("XOM", "ANET", "MSFT")
    )
    monkeypatch.setattr(bridge, "_DEFAULT_VERIFIED_HOLDINGS_PATH", holdings)
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
    # CLOSED + P>0 normalizes to CLOSED_WIN per the outcome-correctness contract.
    assert learning["event_type"] == "CLOSED_WIN"
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


# ---------------------------------------------------------------------------
# Verified-holdings learning-worthiness gate — regression tests.
#
# These call the bridge directly with a *fixture-controlled* holdings file
# that lists the ticker as OPEN, proving the gate distinguishes bare
# open-trade contamination (blocked) from explicit learning-worthy
# reconciliations (allowed) regardless of canonical holdings.
# ---------------------------------------------------------------------------


@pytest.fixture
def verified_open_file(tmp_path) -> Path:
    """Holdings file listing XOM/ANET/MSFT as OPEN for the gate tests."""
    return _write_holdings(
        tmp_path / "gate_holdings.json", ("XOM", "ANET", "MSFT")
    )


@pytest.fixture
def gate_db(tmp_path) -> Path:
    db = tmp_path / "gate.db"
    persistence.init_schema(db)
    return db


def _assert_safety(result: dict) -> None:
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["broker_api_called"] is False
    assert result["ai_execution_count"] == 0


def test_open_ticker_without_close_evidence_is_skipped(
    verified_open_file: Path, gate_db: Path, tmp_path
):
    """(a) A verified-open ticker whose only signal is a *claimed* terminal
    label — no stop_loss_hit, no completed reconciliation status, no partial
    TP, no terminal exit_reason — is open-trade contamination and is
    skipped."""
    out = bridge.record_reconciliation_learning(
        trade_id="MT_GATE_OPEN",
        event_id="EV_GATE_OPEN",
        ticker="XOM",
        explicit_event_type="CLOSED_WIN",
        reconciliation_status="",  # not a completed reconciliation
        post_trade_outcome="CLOSED_WIN",
        actual_exit_price=160.0,
        exit_quantity=0.2,
        entry_price=157.92,
        entry_quantity=0.2,
        realized_pl=0.4,
        cross_check_verified_holdings=True,
        verified_holdings_path=verified_open_file,
        db_path=gate_db,
        jsonl_path=tmp_path / "a.jsonl",
    )
    assert out["status"] == "skipped"
    assert out["reason"] == bridge.SKIP_TICKER_STILL_OPEN_IN_VERIFIED_HOLDINGS
    _assert_safety(out)
    assert persistence.get_moltbook_entries(ticker="XOM", db_path=gate_db) == []


def test_stopped_out_creates_entry_even_if_verified_open(
    verified_open_file: Path, gate_db: Path, tmp_path
):
    """(b) A STOPPED_OUT with stop_loss_hit evidence creates a Moltbook
    entry even though XOM is listed open in verified holdings."""
    out = bridge.record_reconciliation_learning(
        trade_id="MT_GATE_STOP",
        event_id="EV_GATE_STOP",
        ticker="XOM",
        post_trade_outcome="STOPPED_OUT",
        stop_loss_hit=True,
        stop_loss_price=98.5,
        exit_reason="Stop-loss breached on close.",
        actual_exit_price=98.5,
        exit_quantity=10.0,
        entry_price=105.0,
        entry_quantity=10.0,
        realized_pl=-65.0,
        cross_check_verified_holdings=True,
        verified_holdings_path=verified_open_file,
        db_path=gate_db,
        jsonl_path=tmp_path / "b.jsonl",
    )
    assert out["status"] == "created"
    assert out["event_type"] == "STOP_LOSS_HIT"
    assert out["learning_direction"] == "MISTAKE_OR_INVALIDATION"
    _assert_safety(out)


def test_partial_tp_creates_entry_even_if_runner_open(
    verified_open_file: Path, gate_db: Path, tmp_path
):
    """(c) A PARTIAL_TP with a booked partial fill creates a Moltbook entry
    even though the runner keeps ANET open in verified holdings."""
    out = bridge.record_reconciliation_learning(
        trade_id="MT_GATE_PTP",
        event_id="EV_GATE_PTP",
        ticker="ANET",
        post_trade_outcome="PARTIAL_TP",
        reconciliation_status="",  # prove the partial-TP evidence path itself
        partial_take_profit_price=420.0,
        partial_take_profit_quantity=7.0,
        runner_quantity=3.0,
        actual_exit_price=420.0,
        exit_quantity=7.0,
        entry_price=380.0,
        entry_quantity=10.0,
        cross_check_verified_holdings=True,
        verified_holdings_path=verified_open_file,
        db_path=gate_db,
        jsonl_path=tmp_path / "c.jsonl",
    )
    assert out["status"] == "created"
    assert out["event_type"] == "PARTIAL_TP_HIT"
    assert out["learning_direction"] == "SUCCESS_PATTERN"
    _assert_safety(out)


def test_closed_win_full_close_creates_entry_even_if_verified_open(
    verified_open_file: Path, gate_db: Path, tmp_path
):
    """(d) A CLOSED_WIN whose actual_quantity fully closes the original
    trade (completed reconciliation) creates a Moltbook entry even though
    MSFT still appears in verified holdings."""
    out = bridge.record_reconciliation_learning(
        trade_id="MT_GATE_CLOSE",
        event_id="EV_GATE_CLOSE",
        ticker="MSFT",
        post_trade_outcome="CLOSED_WIN",
        reconciliation_status="RECONCILED",  # completed reconciliation
        actual_exit_price=430.0,
        exit_quantity=2.0,
        entry_price=400.0,
        entry_quantity=2.0,
        realized_pl=60.0,
        cross_check_verified_holdings=True,
        verified_holdings_path=verified_open_file,
        db_path=gate_db,
        jsonl_path=tmp_path / "d.jsonl",
    )
    assert out["status"] == "created"
    assert out["event_type"] == "CLOSED_WIN"
    assert out["learning_direction"] == "SUCCESS_PATTERN"
    _assert_safety(out)
