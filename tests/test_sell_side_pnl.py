"""F4 regression: realized P/L must be side-aware.

Audit finding F4: ``compute_realized_pnl_long`` ignored the trade side,
so a profitable short (SELL @ 100, cover @ 90) recorded realized_pnl
−1000 instead of +1000 — sign-inverting every short trade and poisoning
win-rate / calibration aggregates.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scripts import persistence
from scripts.reconciliation_extras import (
    build_outcome_payload,
    compute_realized_pnl,
    compute_realized_pnl_long,
)


# ---------------------------------------------------------------------------
# Formula-level
# ---------------------------------------------------------------------------


def test_short_profit_is_positive():
    # The exact audit repro: short 100 sh @ 100, cover @ 90 → +1000.
    pnl = compute_realized_pnl(
        entry_price=100.0, exit_price=90.0, exit_quantity=100.0, side="SELL"
    )
    assert pnl == 1000.0


def test_short_loss_is_negative():
    pnl = compute_realized_pnl(
        entry_price=100.0, exit_price=110.0, exit_quantity=100.0, side="SELL"
    )
    assert pnl == -1000.0


def test_long_profit_unchanged():
    pnl = compute_realized_pnl(
        entry_price=100.0, exit_price=110.0, exit_quantity=100.0, side="BUY"
    )
    assert pnl == 1000.0


def test_unknown_side_defaults_to_long_semantics():
    for side in ("", None, "HOLD", "buy "):
        pnl = compute_realized_pnl(
            entry_price=10.0, exit_price=12.0, exit_quantity=1.0, side=side
        )
        assert pnl == 2.0


def test_legacy_wrapper_still_long_only():
    assert compute_realized_pnl_long(
        entry_price=100.0, exit_price=90.0, exit_quantity=100.0
    ) == -1000.0


# ---------------------------------------------------------------------------
# Payload-level
# ---------------------------------------------------------------------------


def test_build_outcome_payload_sell_side():
    p = build_outcome_payload(
        trade_id="T_SHORT",
        post_trade_outcome="CLOSED_WIN",
        actual_exit_price=90.0,
        exit_quantity=100.0,
        entry_price=100.0,
        entry_quantity=100.0,
        side="SELL",
        leverage=1.0,
    )
    assert p["realized_pnl"] == 1000.0
    assert p["side"] == "SELL"


def test_build_outcome_payload_defaults_to_buy():
    p = build_outcome_payload(
        trade_id="T_LONG",
        post_trade_outcome="CLOSED_WIN",
        actual_exit_price=110.0,
        exit_quantity=100.0,
        entry_price=100.0,
        entry_quantity=100.0,
    )
    assert p["realized_pnl"] == 1000.0
    assert p["side"] == "BUY"


# ---------------------------------------------------------------------------
# End-to-end: reconcile_trade picks the side up from the trade row
# ---------------------------------------------------------------------------


def _rebind_defaults(fn, new_db: Path):
    if fn.__defaults__:
        fn.__defaults__ = tuple(
            new_db if isinstance(d, Path) else d for d in fn.__defaults__
        )
    if fn.__kwdefaults__:
        fn.__kwdefaults__ = {
            k: (new_db if isinstance(v, Path) else v)
            for k, v in fn.__kwdefaults__.items()
        }


@pytest.fixture()
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import scripts.signal_inbox_api as api

    db = tmp_path / "sell_pnl.db"
    persistence.init_schema(db)
    helpers = [
        "init_schema",
        "_get_conn",
        "insert_manual_trade",
        "get_manual_trade",
        "get_event_id_for_trade",
        "insert_reconciliation",
        "get_reconciliations_for_trade",
    ]
    originals: dict = {}
    for name in helpers:
        fn = getattr(persistence, name, None)
        if fn is None:
            continue
        originals[name] = (fn.__defaults__, dict(fn.__kwdefaults__ or {}))
        _rebind_defaults(fn, db)
    monkeypatch.setattr(persistence, "DB_PATH", db, raising=True)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr(api, "MANUAL_TRADE_LOG", log_dir / "mt.jsonl")
    monkeypatch.setattr(api, "RECONCILIATIONS_LOG", log_dir / "rec.jsonl")
    try:
        yield db
    finally:
        for name, (defs, kwdefs) in originals.items():
            fn = getattr(persistence, name)
            fn.__defaults__ = defs
            fn.__kwdefaults__ = kwdefs or None


def test_reconcile_trade_uses_sell_side_from_trade_row(tmp_db):
    import scripts.signal_inbox_api as api

    logged = api.log_manual_trade(
        event_id="EVT_SHORT",
        ticker="TSLA",
        side="SELL",
        quantity=100.0,
        price=100.0,
        thesis="short into resistance",
    )
    assert logged["status"] == "logged"
    rec = api.reconcile_trade(
        logged["trade_id"],
        actual_fill_price=90.0,
        actual_quantity=100.0,
        pnl_estimate=0.0,
        post_trade_outcome="CLOSED_WIN",
    )
    assert rec["status"] == "logged"
    assert rec["realized_pnl"] == 1000.0
    assert rec["pnl_estimate"] == 1000.0


# ---------------------------------------------------------------------------
# One-off audit script flags historical inverted rows, dry-run by default
# ---------------------------------------------------------------------------


def test_audit_script_flags_inverted_rows_and_apply_fixes(tmp_path):
    from scripts.audit_sell_side_pnl import apply_corrections, collect_sell_side_rows

    db = tmp_path / "hist.db"
    persistence.init_schema(db)
    persistence.insert_manual_trade(
        "MT_SHORT1", "EVT1", "TSLA", "SELL", 100.0, 100.0,
        "2026-01-01T00:00:00Z", "short thesis", "", "human", db_path=db,
    )
    # Historical row persisted with the OLD long-only (inverted) P/L.
    persistence.insert_reconciliation(
        "REC_SHORT1", "MT_SHORT1", "EVT1", "2026-01-02T00:00:00Z",
        90.0, 100.0, "", -1000.0, "WIN", db_path=db,
    )

    findings = collect_sell_side_rows(db)
    assert len(findings) == 1
    f = findings[0]
    assert f["stored_pnl"] == -1000.0
    assert f["corrected_pnl"] == 1000.0
    assert f["consistent"] is False

    # --apply path: backup then rewrite.
    result = apply_corrections(db, [f])
    assert result["applied"] == 1
    assert result.get("backup_path")
    assert Path(result["backup_path"]).exists()
    conn = sqlite3.connect(str(db))
    try:
        val = conn.execute(
            "SELECT pnl_estimate FROM reconciliation_results"
            " WHERE reconciliation_id='REC_SHORT1'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert float(val) == 1000.0
