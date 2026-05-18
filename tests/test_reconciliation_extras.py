"""
Sprint H — Reconciliation tab productisation: regression tests for the
reconciliation extras helper and the extended reconcile_trade path.

Coverage:

  * 70 / 30 default split — verified for the three example fixtures
    BHARTIARTL.NS (2.5830), ICICIBANK.NS (3.8908), SAP.DE (4.2917).
  * Realized P/L (long) — formula matches (exit - entry) * qty without
    double-counting leverage.
  * Enum normalisers tolerate bad input.
  * build_outcome_payload routes statuses correctly:
        PARTIAL_TP   → PARTIAL_RECONCILED + RUNNER_OPEN
        CLOSED_WIN   → RECONCILED         + NO_RUNNER (when full close)
        STOPPED_OUT  → RECONCILED         + RUNNER_STOPPED (if runner left)
  * reconcile_trade integration:
        - PARTIAL_TP keeps the trade visible as PARTIAL_RECONCILED.
        - CLOSED_WIN sets RECONCILED + WIN legacy status + realized P/L.
        - STOPPED_OUT sets RECONCILED + LOSS legacy status.
        - cancel_manual_trade_log marks the row CANCELLED_DUPLICATE,
          excludes it from the live queue, and does NOT call a broker.
  * Safety stamps survive every path.

The tests run against an isolated tmp SQLite DB and never touch
runtime/mvp_local.db.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


# ---------------------------------------------------------------------------
# Pure helper tests (no DB required)
# ---------------------------------------------------------------------------


def test_split_quantity_70_30_bhartiartl():
    from scripts.reconciliation_extras import split_quantity_70_30
    out = split_quantity_70_30(2.5830)
    assert out["partial_take_profit_quantity"] == 1.8081
    assert out["runner_quantity"] == 0.7749


def test_split_quantity_70_30_icicibank():
    from scripts.reconciliation_extras import split_quantity_70_30
    out = split_quantity_70_30(3.8908)
    assert out["partial_take_profit_quantity"] == 2.7236
    assert out["runner_quantity"] == 1.1672


def test_split_quantity_70_30_sap_de():
    from scripts.reconciliation_extras import split_quantity_70_30
    out = split_quantity_70_30(4.2917)
    assert out["partial_take_profit_quantity"] == 3.0042
    assert out["runner_quantity"] == 1.2875


def test_split_quantity_no_drift():
    """tp + runner == total at the configured precision, for many qtys."""
    from scripts.reconciliation_extras import (
        QUANTITY_PRECISION, split_quantity_70_30,
    )
    for q in (1.0, 2.5830, 3.8908, 4.2917, 10.123, 99.9999, 0.0001):
        out = split_quantity_70_30(q)
        # Float arithmetic may introduce a tiny rounding tail; the contract
        # is that tp + runner equals total at the configured precision.
        recomposed = round(
            out["partial_take_profit_quantity"] + out["runner_quantity"],
            QUANTITY_PRECISION,
        )
        assert recomposed == out["total_quantity"], (
            f"split drifted for qty={q}: {out}"
        )


def test_compute_realized_pnl_long_no_double_leverage():
    from scripts.reconciliation_extras import compute_realized_pnl_long
    pnl = compute_realized_pnl_long(
        entry_price=100.0, exit_price=110.0, exit_quantity=10.0,
        leverage=5.0, apply_leverage_multiplier=False,
    )
    # Quantity already reflects leveraged exposure → do NOT multiply again.
    assert pnl == 100.0


def test_compute_realized_pnl_long_opt_in_leverage_multiplier():
    from scripts.reconciliation_extras import compute_realized_pnl_long
    pnl = compute_realized_pnl_long(
        entry_price=100.0, exit_price=110.0, exit_quantity=10.0,
        leverage=5.0, apply_leverage_multiplier=True,
    )
    assert pnl == 500.0


def test_normalize_post_trade_outcome_round_trips():
    from scripts.reconciliation_extras import normalize_post_trade_outcome
    assert normalize_post_trade_outcome("partial_tp") == "PARTIAL_TP"
    assert normalize_post_trade_outcome("CLOSED_WIN") == "CLOSED_WIN"
    assert normalize_post_trade_outcome("garbage") == "OPEN"
    assert normalize_post_trade_outcome(None) == "OPEN"


def test_build_outcome_payload_partial_tp_routes_runner_open():
    from scripts.reconciliation_extras import build_outcome_payload
    out = build_outcome_payload(
        trade_id="MT_test1",
        post_trade_outcome="PARTIAL_TP",
        actual_exit_price=42.0,
        exit_quantity=2.7236,
        entry_price=40.72,
        entry_quantity=3.8908,
    )
    assert out["post_trade_outcome"] == "PARTIAL_TP"
    assert out["reconciliation_status"] == "PARTIAL_RECONCILED"
    assert out["runner_status"] == "RUNNER_OPEN"
    # runner_quantity = entry_quantity - exit_quantity (default behaviour)
    assert out["runner_quantity"] == 1.1672
    # P/L on the partial: (42.00 - 40.72) * 2.7236
    assert out["realized_pnl"] == round((42.0 - 40.72) * 2.7236, 4)
    # Safety stamps survive.
    assert out["broker_api_called"] is False
    assert out["ai_execution_count"] == 0
    assert out["execution_gate"] == "LOCKED"
    assert out["advisory_status"] == "ADVISORY_ONLY"


def test_build_outcome_payload_closed_win_routes_reconciled():
    from scripts.reconciliation_extras import build_outcome_payload
    out = build_outcome_payload(
        trade_id="MT_test2",
        post_trade_outcome="CLOSED_WIN",
        actual_exit_price=44.0,
        exit_quantity=3.8908,
        entry_price=40.72,
        entry_quantity=3.8908,
    )
    assert out["reconciliation_status"] == "RECONCILED"
    assert out["runner_status"] == "NO_RUNNER"
    assert out["remaining_quantity"] == 0.0


def test_build_outcome_payload_stopped_out_with_runner_stopped():
    from scripts.reconciliation_extras import build_outcome_payload
    out = build_outcome_payload(
        trade_id="MT_test3",
        post_trade_outcome="STOPPED_OUT",
        actual_exit_price=38.0,
        exit_quantity=1.1672,
        entry_price=40.72,
        entry_quantity=3.8908,
        runner_quantity=1.1672,
        stop_loss_price=38.0,
        stop_loss_hit=True,
    )
    assert out["reconciliation_status"] == "RECONCILED"
    assert out["runner_status"] == "RUNNER_STOPPED"
    assert out["stop_loss_hit"] is True
    assert out["realized_pnl"] == round((38.0 - 40.72) * 1.1672, 4)


def test_serialize_and_parse_outcome_round_trips():
    from scripts.reconciliation_extras import (
        build_outcome_payload, parse_outcome_from_notes,
        serialize_outcome_for_notes,
    )
    out = build_outcome_payload(
        trade_id="MT_test4",
        post_trade_outcome="CLOSED_WIN",
        actual_exit_price=44.0,
        exit_quantity=3.8908,
        entry_price=40.72,
        entry_quantity=3.8908,
        notes="Hit target.",
    )
    notes_str = serialize_outcome_for_notes(out, "Hit target.")
    parsed = parse_outcome_from_notes(notes_str)
    assert parsed is not None
    assert parsed["post_trade_outcome"] == "CLOSED_WIN"
    assert parsed["realized_pnl"] == out["realized_pnl"]


# ---------------------------------------------------------------------------
# Integration tests against an isolated SQLite DB
# ---------------------------------------------------------------------------


def _rebind_defaults(fn, new_db: Path) -> None:
    if fn.__defaults__:
        fn.__defaults__ = tuple(
            new_db if isinstance(d, Path) else d for d in fn.__defaults__
        )
    if fn.__kwdefaults__:
        fn.__kwdefaults__ = {
            k: (new_db if isinstance(v, Path) else v)
            for k, v in fn.__kwdefaults__.items()
        }


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Point the persistence layer at a fresh tmp DB for the test.

    Default args bound at function-definition time still reference the
    original ``DB_PATH``; mirror the pattern used by
    test_manual_trade_cancel_log.py and rebind those defaults onto the
    fresh tmp DB so SQLite writes land in the right file.
    """
    from scripts import persistence as p
    from scripts import signal_inbox_api as inbox_api
    db = tmp_path / "recon_extras.db"
    p.init_schema(db)

    helper_names = [
        "init_schema", "_get_conn", "insert_manual_trade",
        "get_trades_for_event", "get_event_id_for_trade",
        "get_all_manual_trades", "get_manual_trade",
        "get_manual_trade_raw_broker_flag", "cancel_manual_trade",
        "insert_reconciliation", "get_reconciliations_for_trade",
        "get_all_reconciliations",
    ]
    originals: dict = {}
    for name in helper_names:
        fn = getattr(p, name, None)
        if fn is None:
            continue
        originals[name] = (fn.__defaults__, dict(fn.__kwdefaults__ or {}))
        _rebind_defaults(fn, db)
    monkeypatch.setattr(p, "DB_PATH", db, raising=True)

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr(inbox_api, "MANUAL_TRADE_LOG", log_dir / "mt.jsonl")
    monkeypatch.setattr(inbox_api, "RECONCILIATIONS_LOG", log_dir / "rec.jsonl")
    monkeypatch.setattr(inbox_api, "REFLECTIONS_LOG", log_dir / "ref.jsonl")
    monkeypatch.setattr(inbox_api, "AI_SUMMARIES_LOG", log_dir / "ai.jsonl")
    monkeypatch.setattr(inbox_api, "INBOX_STATES_LOG", log_dir / "inbox.jsonl")
    monkeypatch.setattr(
        inbox_api,
        "MANUAL_TRADE_CANCELLATIONS_LOG",
        log_dir / "mt_cancels.jsonl",
    )
    monkeypatch.setattr(inbox_api, "_DB_AVAILABLE", True, raising=False)
    monkeypatch.setattr(inbox_api, "_persistence", p, raising=False)
    try:
        yield db
    finally:
        for name, (defs, kwdefs) in originals.items():
            fn = getattr(p, name)
            fn.__defaults__ = defs
            fn.__kwdefaults__ = kwdefs or None


def _log_trade(ticker: str, qty: float, price: float, leverage: float = 1.0):
    from scripts.signal_inbox_api import log_manual_trade
    return log_manual_trade(
        event_id=f"EV_{ticker}",
        ticker=ticker,
        side="BUY",
        quantity=qty,
        price=price,
        # Use a realistic thesis sentence that does NOT contain any
        # fake-marker substring (probe/test/seed/demo/fixture/smoke/
        # sample/mock/"no currency given").  See
        # scripts/manual_trade_origin.FAKE_THESIS_SUBSTRINGS.  Helper
        # rows must look like genuine user logs so they pass the
        # visibility filter at the reconciliation queue boundary.
        thesis=f"reconciliation extras coverage for {ticker}",
        leverage=leverage,
    )


def test_reconcile_partial_tp_persists_partial_reconciled(isolated_db):
    from scripts.signal_inbox_api import reconcile_trade
    logged = _log_trade("ICICIBANK.NS", 3.8908, 40.72)
    trade_id = logged["trade_id"]

    resp = reconcile_trade(
        trade_id,
        actual_fill_price=42.0,
        actual_quantity=2.7236,
        post_trade_outcome="PARTIAL_TP",
        partial_take_profit_price=42.0,
        partial_take_profit_quantity=2.7236,
        runner_quantity=1.1672,
        lesson_takeaway="trim 70%, let runner work to next pivot",
    )
    assert resp["reconciliation_status"] == "PARTIAL_RECONCILED"
    assert resp["post_trade_outcome"] == "PARTIAL_TP"
    assert resp["runner_status"] == "RUNNER_OPEN"
    assert resp["runner_quantity"] == 1.1672
    assert resp["realized_pnl"] == round((42.0 - 40.72) * 2.7236, 4)
    # Safety stamps survive.
    assert resp["broker_api_called"] is False
    assert resp["ai_execution_count"] == 0
    assert resp["execution_gate"] == "LOCKED"
    assert resp["advisory_status"] == "ADVISORY_ONLY"


def test_reconcile_close_trade_sets_reconciled_and_wins(isolated_db):
    from scripts.signal_inbox_api import reconcile_trade
    # NOTE: avoid the AAPL/$180/qty{5,10} fingerprint — that combo is a
    # fake-marker veto (see scripts/manual_trade_origin.FAKE_AAPL_*).
    logged = _log_trade("MSFT", 10.0, 180.0)
    trade_id = logged["trade_id"]

    resp = reconcile_trade(
        trade_id,
        actual_fill_price=190.0,
        actual_quantity=10.0,
        post_trade_outcome="CLOSED_WIN",
        outcome_quality="GOOD_PROCESS_WIN",
        lesson_takeaway="trend held; keep size",
    )
    assert resp["reconciliation_status"] == "RECONCILED"
    assert resp["outcome_status"] == "WIN"
    assert resp["realized_pnl"] == 100.0
    assert resp["remaining_quantity"] == 0.0
    assert resp["broker_api_called"] is False
    assert resp["ai_execution_count"] == 0


def test_reconcile_stop_hit_sets_reconciled_and_loss(isolated_db):
    from scripts.signal_inbox_api import reconcile_trade
    logged = _log_trade("SPY", 5.0, 520.0)
    trade_id = logged["trade_id"]

    resp = reconcile_trade(
        trade_id,
        actual_fill_price=510.0,
        actual_quantity=5.0,
        post_trade_outcome="STOPPED_OUT",
        stop_loss_price=510.0,
        stop_loss_hit=True,
        outcome_quality="GOOD_PROCESS_LOSS",
        lesson_takeaway="invalidation respected",
    )
    assert resp["reconciliation_status"] == "RECONCILED"
    assert resp["outcome_status"] == "LOSS"
    assert resp["stop_loss_hit"] is True
    assert resp["realized_pnl"] == -50.0
    assert resp["broker_api_called"] is False
    assert resp["ai_execution_count"] == 0


def test_legacy_reconcile_path_still_works(isolated_db):
    """Pre-Sprint-H clients that only send the four core fields should keep
    working: outcome_status WIN, no extra structured fields, no broker call."""
    from scripts.signal_inbox_api import reconcile_trade
    logged = _log_trade("TLT", 4.0, 90.0)
    trade_id = logged["trade_id"]

    resp = reconcile_trade(
        trade_id,
        actual_fill_price=92.0,
        actual_quantity=4.0,
        outcome_status="WIN",
        pnl_estimate=8.0,
    )
    assert resp["outcome_status"] == "WIN"
    assert resp["broker_api_called"] is False
    assert resp["ai_execution_count"] == 0
    # No structured-outcome surface fields when the caller did not opt in.
    assert "post_trade_outcome" not in resp


def test_cancel_log_excludes_from_queue(isolated_db):
    from scripts.signal_inbox_api import cancel_manual_trade_log
    from scripts.reconciliation_queue import build_queue
    logged = _log_trade("BHARTIARTL.NS", 2.5830, 1700.0)
    trade_id = logged["trade_id"]

    # Sanity: trade appears in the queue before cancel.
    pre = build_queue(isolated_db)
    pre_ids = {it["trade_id"] for it in pre["items"]}
    assert trade_id in pre_ids

    cancel_resp = cancel_manual_trade_log(trade_id)
    assert cancel_resp["status"] == "cancelled"
    assert cancel_resp["broker_api_called"] is False
    assert cancel_resp["ai_execution_count"] == 0
    assert cancel_resp["reconciliation_status"] == "CANCELLED_DUPLICATE"

    post = build_queue(isolated_db)
    post_ids = {it["trade_id"] for it in post["items"]}
    assert trade_id not in post_ids, (
        "cancelled log must not appear in the awaiting-reconciliation queue"
    )
