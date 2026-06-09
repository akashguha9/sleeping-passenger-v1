"""F3 regression: money is Decimal end-to-end with zero float bridges.

Audit finding F3: the API validated money as Decimal then converted back
to float (``money_to_legacy_float``) before persistence; SQLite stored
money in REAL columns; P/L was float arithmetic.  This suite re-executes
the audit's adversarial repros against the migrated pipeline:

  (a) 1,000 closes of (0.30 − 0.10) × 0.1 must sum to exactly 20
      (float accumulation drifted to 19.999999999999662);
  (b) negative P/L stays exact;
  (c) money round-trips through SQLite as the exact Decimal string
      (TEXT affinity), never as a REAL;
  (d) the one-shot migration rebuilds legacy REAL columns to TEXT,
      takes a backup first, and fails loud on error;
  (e) the float bridge is gone: ``money_to_legacy_float`` no longer
      exists anywhere in the codebase.
"""
from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from scripts import persistence
from scripts.money import MoneyError, money_to_str, parse_money
from scripts.reconciliation_extras import compute_realized_pnl

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# (a) fractional-cent accumulation
# ---------------------------------------------------------------------------


def test_thousand_close_accumulation_is_exact():
    total = Decimal("0")
    for _ in range(1000):
        total += compute_realized_pnl(
            entry_price="0.10", exit_price="0.30", exit_quantity="0.1"
        )
    assert total == Decimal("20")


def test_float_inputs_are_decimalised_via_shortest_repr():
    # Even when a legacy caller passes binary floats, parse_money uses
    # str(float) so the operator-visible decimal value is what's computed.
    total = Decimal("0")
    for _ in range(1000):
        total += compute_realized_pnl(
            entry_price=0.10, exit_price=0.30, exit_quantity=0.1
        )
    assert total == Decimal("20")


# ---------------------------------------------------------------------------
# (b) negative P/L rounding
# ---------------------------------------------------------------------------


def test_negative_pnl_exact():
    pnl = compute_realized_pnl(
        entry_price="2.675", exit_price="2.665", exit_quantity="100"
    )
    assert pnl == Decimal("-1")


def test_rounding_mode_is_half_even():
    # 0.0000000000005 quantised at 1e-12 rounds to even (0), not up.
    assert parse_money("0.0000000000005") == Decimal("0")
    assert parse_money("0.0000000000015") == Decimal("0.000000000002")


# ---------------------------------------------------------------------------
# (c) SQLite round-trip exactness
# ---------------------------------------------------------------------------


def test_sqlite_roundtrip_exact_decimal_string(tmp_path):
    db = tmp_path / "rt.db"
    persistence.init_schema(db)
    persistence.insert_manual_trade(
        "MT_RT", "EVT_RT", "INFY", "BUY",
        Decimal("10.123456789012"), Decimal("4111.11"),
        "2026-01-01T00:00:00Z", "roundtrip", "", "human",
        db_path=db, leverage=Decimal("2.5"),
    )
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        r = conn.execute(
            "SELECT quantity, price, leverage,"
            " typeof(quantity) tq, typeof(price) tp, typeof(leverage) tl"
            " FROM manual_trades WHERE trade_id='MT_RT'"
        ).fetchone()
    finally:
        conn.close()
    assert (r["tq"], r["tp"], r["tl"]) == ("text", "text", "text")
    assert Decimal(r["quantity"]) == Decimal("10.123456789012")
    assert Decimal(r["price"]) == Decimal("4111.11")
    assert Decimal(r["leverage"]) == Decimal("2.5")


def test_reconciliation_money_stored_as_text(tmp_path):
    db = tmp_path / "rt2.db"
    persistence.init_schema(db)
    persistence.insert_reconciliation(
        "REC_RT", "MT_RT", "EVT_RT", "2026-01-02T00:00:00Z",
        Decimal("101.33"), Decimal("3"), "", Decimal("-0.07"), "LOSS",
        db_path=db,
    )
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        r = conn.execute(
            "SELECT actual_fill_price, actual_quantity, pnl_estimate,"
            " typeof(pnl_estimate) tp FROM reconciliation_results"
            " WHERE reconciliation_id='REC_RT'"
        ).fetchone()
    finally:
        conn.close()
    assert r["tp"] == "text"
    assert Decimal(r["pnl_estimate"]) == Decimal("-0.07")
    assert Decimal(r["actual_fill_price"]) == Decimal("101.33")


def test_persistence_refuses_nan_money(tmp_path):
    db = tmp_path / "nan.db"
    persistence.init_schema(db)
    with pytest.raises(MoneyError):
        persistence.insert_manual_trade(
            "MT_NAN", "EVT", "X", "BUY", float("nan"), 1.0,
            "2026-01-01T00:00:00Z", "t", "", "human", db_path=db,
        )


# ---------------------------------------------------------------------------
# (d) legacy REAL → TEXT migration
# ---------------------------------------------------------------------------

_LEGACY_SCHEMA = """
CREATE TABLE manual_trades (
    trade_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    executed_at TEXT NOT NULL,
    thesis TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    logged_by TEXT NOT NULL DEFAULT 'human',
    leverage REAL NOT NULL DEFAULT 1.0
);
CREATE TABLE reconciliation_results (
    reconciliation_id TEXT PRIMARY KEY,
    trade_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    reconciled_at TEXT NOT NULL,
    actual_fill_price REAL NOT NULL,
    actual_quantity REAL NOT NULL,
    outcome_notes TEXT NOT NULL DEFAULT '',
    pnl_estimate REAL NOT NULL DEFAULT 0.0,
    outcome_status TEXT NOT NULL DEFAULT 'UNKNOWN'
);
"""


def _make_legacy_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(_LEGACY_SCHEMA)
        conn.execute(
            "INSERT INTO manual_trades (trade_id, event_id, ticker, side,"
            " quantity, price, executed_at) VALUES"
            " ('MT_L1','E1','AAPL','BUY', 0.1, 0.30000000000000004,"
            "  '2026-01-01T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO reconciliation_results (reconciliation_id, trade_id,"
            " event_id, reconciled_at, actual_fill_price, actual_quantity,"
            " pnl_estimate) VALUES"
            " ('R_L1','MT_L1','E1','2026-01-02T00:00:00Z', 4111.11, 1, -1.0)"
        )
        conn.commit()
    finally:
        conn.close()


def test_migration_rebuilds_legacy_real_columns(tmp_path):
    db = tmp_path / "legacy.db"
    _make_legacy_db(db)
    persistence.init_schema(db)

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        info = {r[1]: str(r[2]).upper() for r in conn.execute(
            "PRAGMA table_info(manual_trades)")}
        assert info["quantity"] == "TEXT"
        assert info["price"] == "TEXT"
        assert info["leverage"] == "TEXT"
        row = conn.execute(
            "SELECT quantity, price FROM manual_trades WHERE trade_id='MT_L1'"
        ).fetchone()
        # Exact decimal of the float's shortest repr; noise quantised at 12dp.
        assert Decimal(row["quantity"]) == Decimal("0.1")
        assert Decimal(row["price"]) == Decimal("0.3")
        rinfo = {r[1]: str(r[2]).upper() for r in conn.execute(
            "PRAGMA table_info(reconciliation_results)")}
        assert rinfo["pnl_estimate"] == "TEXT"
        rrow = conn.execute(
            "SELECT actual_fill_price, pnl_estimate FROM"
            " reconciliation_results WHERE reconciliation_id='R_L1'"
        ).fetchone()
        assert Decimal(rrow["actual_fill_price"]) == Decimal("4111.11")
        assert Decimal(rrow["pnl_estimate"]) == Decimal("-1")
    finally:
        conn.close()

    # Backup was taken BEFORE the rebuild and a report was written.
    backups = list((tmp_path / "backups").glob("*.pre-f3-money.*.db"))
    assert backups, "migration must back the DB up before rebuilding"
    reports = list((tmp_path / "backups").glob("f3_money_migration_report_*.json"))
    assert reports, "migration must write a conversion report"
    report = json.loads(reports[0].read_text())
    assert report["rows_converted"] >= 2
    # 0.30000000000000004 carries float noise beyond 8 dp → flagged.
    assert any(
        a["raw_repr"] == "0.30000000000000004"
        for a in report["ambiguous_float_values"]
    )


def test_migration_is_idempotent(tmp_path):
    db = tmp_path / "idem.db"
    _make_legacy_db(db)
    persistence.init_schema(db)
    persistence.init_schema(db)  # second run must be a no-op
    backups = list((tmp_path / "backups").glob("*.pre-f3-money.*.db"))
    assert len(backups) == 1


# ---------------------------------------------------------------------------
# (e) the float bridge is dead
# ---------------------------------------------------------------------------


def test_money_to_legacy_float_is_deleted():
    import scripts.money as money

    assert not hasattr(money, "money_to_legacy_float")


def test_no_float_bridge_references_in_codebase():
    hits = []
    for py in (REPO_ROOT / "scripts").rglob("*.py"):
        text = py.read_text(encoding="utf-8", errors="ignore")
        if "money_to_legacy_float" in text or "_money_to_float" in text:
            hits.append(str(py))
    assert hits == [], f"float bridge references survive in: {hits}"


# ---------------------------------------------------------------------------
# HTTP wire → persistence: the operator's exact string survives
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


def test_wire_to_disk_decimal_fidelity(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import scripts.api_server as srv
    import scripts.signal_inbox_api as api

    db = tmp_path / "wire.db"
    persistence.init_schema(db)
    originals: dict = {}
    for name in ("init_schema", "_get_conn", "insert_manual_trade",
                 "get_manual_trade", "get_event_id_for_trade",
                 "insert_reconciliation", "get_reconciliations_for_trade"):
        fn = getattr(persistence, name)
        originals[name] = (fn.__defaults__, dict(fn.__kwdefaults__ or {}))
        _rebind_defaults(fn, db)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr(api, "MANUAL_TRADE_LOG", log_dir / "mt.jsonl")
    monkeypatch.setattr(api, "RECONCILIATIONS_LOG", log_dir / "rec.jsonl")
    try:
        client = TestClient(srv.app, raise_server_exceptions=False)
        r = client.post(
            "/manual-trades",
            json={
                "event_id": "EVT_WIRE",
                "ticker": "BTC",
                "side": "BUY",
                # adversarial: a value floats cannot represent
                "quantity": "0.1",
                "price": "4111.11",
                "thesis": "decimal fidelity",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert Decimal(body["quantity"]) == Decimal("0.1")
        assert Decimal(body["price"]) == Decimal("4111.11")
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT quantity, price, typeof(price) tp FROM manual_trades"
                " WHERE trade_id=?",
                (body["trade_id"],),
            ).fetchone()
        finally:
            conn.close()
        assert row["tp"] == "text"
        assert row["quantity"] == "0.1"
        assert row["price"] == "4111.11"
    finally:
        for name, (defs, kwdefs) in originals.items():
            fn = getattr(persistence, name)
            fn.__defaults__ = defs
            fn.__kwdefaults__ = kwdefs or None
