"""S4-E1: forward-only paper-trade evidence ledger.

THE distinction this module enforces: a signal counts as FORWARD evidence
only if it was registered BEFORE the outcome could be known.  Formally:

    t_signal < t_entry_eligible < t_exit

Registrations violating the ordering are rejected.  Entry/exit prices
must reference a PINNED snapshot (its sha256); a missing pinned price
marks the trade DATA_INVALID — counted in denominators, never silently
excluded.  Records are append-only: there is no delete operation, and
corrections write an audit row (F13 table) capturing the prior state.

P/L is exact Decimal end-to-end (F3 contract):
    pnl_net = direction * (exit - entry) * qty - fees - fx - slippage

This module builds the machinery that can EVENTUALLY move edge.  It does
not move edge by existing: only closed forward trades in sufficient
number (T >= 30 minimum gate) feed the evidence report's claims.

Advisory invariants: paper records only — no broker, no execution.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from decimal import Decimal
from pathlib import Path
from typing import Any

try:
    from scripts import persistence as _p
    from scripts.money import money_to_str, parse_money
    from scripts.runtime_common import utc_timestamp
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import persistence as _p  # type: ignore[no-redef]
    from money import money_to_str, parse_money  # type: ignore[no-redef]
    from runtime_common import utc_timestamp  # type: ignore[no-redef]

_logger = logging.getLogger("scripts.forward_evidence_ledger")

STATUSES = (
    "OPEN", "CLOSED_WIN", "CLOSED_LOSS", "CLOSED_FLAT", "INVALIDATED",
    "DATA_INVALID",
)
_EPSILON = Decimal("0.000001")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_signals (
    signal_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    registered_at TEXT NOT NULL,
    signal_at TEXT NOT NULL,
    entry_eligible_at TEXT NOT NULL,
    model_score REAL,
    probability REAL,
    planned_entry_rule TEXT NOT NULL DEFAULT '',
    planned_exit_rule TEXT NOT NULL DEFAULT '',
    planned_invalidation_rule TEXT NOT NULL DEFAULT '',
    capital_at_risk TEXT NOT NULL DEFAULT '0',
    status TEXT NOT NULL DEFAULT 'OPEN',
    status_reason TEXT NOT NULL DEFAULT '',
    advisory_status TEXT NOT NULL DEFAULT 'ADVISORY_ONLY',
    broker_api_called INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS paper_entries (
    signal_id TEXT PRIMARY KEY,
    entered_at TEXT NOT NULL,
    entry_price TEXT NOT NULL,
    entry_price_source TEXT NOT NULL,
    entry_snapshot_sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS paper_exits (
    signal_id TEXT PRIMARY KEY,
    exited_at TEXT NOT NULL,
    exit_price TEXT NOT NULL,
    exit_price_source TEXT NOT NULL,
    exit_snapshot_sha256 TEXT NOT NULL,
    fees TEXT NOT NULL DEFAULT '0',
    fx_cost TEXT NOT NULL DEFAULT '0',
    slippage TEXT NOT NULL DEFAULT '0',
    pnl_net TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS paper_reconciliations (
    signal_id TEXT PRIMARY KEY,
    reconciled_at TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS paper_evidence_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_at TEXT NOT NULL,
    closed_trades INTEGER NOT NULL,
    report_sha256 TEXT NOT NULL
);
"""


class ForwardLedgerError(ValueError):
    """Registration or transition violates the forward-only contract."""


def _conn(db_path: Path | None) -> sqlite3.Connection:
    conn = _p._get_conn(db_path or _p.DB_PATH)
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def register_signal(
    *,
    signal_id: str,
    ticker: str,
    signal_at: str,
    entry_eligible_at: str,
    model_score: float | None = None,
    probability: float | None = None,
    planned_entry_rule: str = "",
    planned_exit_rule: str = "",
    planned_invalidation_rule: str = "",
    capital_at_risk: Any = "0",
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Register a FORWARD signal.  t_signal < t_entry_eligible enforced."""
    if not signal_id or not ticker:
        raise ForwardLedgerError("signal_id and ticker are required")
    if str(signal_at) >= str(entry_eligible_at):
        raise ForwardLedgerError(
            f"forward-only violation: signal_at ({signal_at}) must precede "
            f"entry_eligible_at ({entry_eligible_at}) — a signal recorded at "
            "or after eligibility cannot count as forward evidence"
        )
    registered_at = utc_timestamp()
    if str(signal_at) > registered_at:
        raise ForwardLedgerError(
            "signal_at is in the future relative to registration — refusing"
        )
    if probability is not None and not (0.0 <= float(probability) <= 1.0):
        raise ForwardLedgerError("probability must be in [0,1]")
    conn = _conn(db_path)
    try:
        conn.execute(
            "INSERT INTO paper_signals (signal_id, ticker, registered_at,"
            " signal_at, entry_eligible_at, model_score, probability,"
            " planned_entry_rule, planned_exit_rule, planned_invalidation_rule,"
            " capital_at_risk) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (signal_id, str(ticker).upper(), registered_at, str(signal_at),
             str(entry_eligible_at), model_score, probability,
             planned_entry_rule, planned_exit_rule, planned_invalidation_rule,
             money_to_str(parse_money(capital_at_risk))),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise ForwardLedgerError(f"signal_id already registered: {signal_id}") from exc
    finally:
        conn.close()
    return {"signal_id": signal_id, "registered_at": registered_at,
            "status": "OPEN", "execution_gate": "LOCKED",
            "broker_api_called": False}


def record_entry(
    *,
    signal_id: str,
    entered_at: str,
    entry_price: Any,
    entry_price_source: str,
    entry_snapshot_sha256: str,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Record the paper entry.  Pinned snapshot hash is MANDATORY."""
    conn = _conn(db_path)
    try:
        sig = conn.execute(
            "SELECT entry_eligible_at, status FROM paper_signals WHERE signal_id=?",
            (signal_id,),
        ).fetchone()
        if sig is None:
            raise ForwardLedgerError(f"unknown signal {signal_id}")
        if not entry_snapshot_sha256:
            conn.execute(
                "UPDATE paper_signals SET status='DATA_INVALID',"
                " status_reason='entry price not pinned to a snapshot'"
                " WHERE signal_id=?",
                (signal_id,),
            )
            conn.commit()
            return {"signal_id": signal_id, "status": "DATA_INVALID",
                    "execution_gate": "LOCKED", "broker_api_called": False}
        if str(entered_at) < str(sig["entry_eligible_at"]):
            raise ForwardLedgerError(
                f"entry at {entered_at} precedes eligibility "
                f"{sig['entry_eligible_at']} — forward-only violation"
            )
        conn.execute(
            "INSERT INTO paper_entries (signal_id, entered_at, entry_price,"
            " entry_price_source, entry_snapshot_sha256) VALUES (?,?,?,?,?)",
            (signal_id, str(entered_at), money_to_str(parse_money(entry_price)),
             entry_price_source, entry_snapshot_sha256),
        )
        conn.commit()
    finally:
        conn.close()
    return {"signal_id": signal_id, "status": "OPEN",
            "execution_gate": "LOCKED", "broker_api_called": False}


def record_exit(
    *,
    signal_id: str,
    exited_at: str,
    exit_price: Any,
    exit_price_source: str,
    exit_snapshot_sha256: str,
    direction: str = "LONG",
    quantity: Any = "1",
    fees: Any = "0",
    fx_cost: Any = "0",
    slippage: Any = "0",
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Close the paper trade with exact Decimal P/L after costs."""
    conn = _conn(db_path)
    try:
        entry = conn.execute(
            "SELECT entered_at, entry_price FROM paper_entries WHERE signal_id=?",
            (signal_id,),
        ).fetchone()
        if entry is None:
            raise ForwardLedgerError(f"no entry recorded for {signal_id}")
        if not exit_snapshot_sha256:
            conn.execute(
                "UPDATE paper_signals SET status='DATA_INVALID',"
                " status_reason='exit price not pinned to a snapshot'"
                " WHERE signal_id=?",
                (signal_id,),
            )
            conn.commit()
            return {"signal_id": signal_id, "status": "DATA_INVALID",
                    "execution_gate": "LOCKED", "broker_api_called": False}
        if str(exited_at) <= str(entry["entered_at"]):
            raise ForwardLedgerError("exit must follow entry — forward-only")
        d = Decimal(-1) if str(direction).upper() == "SHORT" else Decimal(1)
        pnl = (
            d * (parse_money(exit_price) - parse_money(entry["entry_price"]))
            * parse_money(quantity)
            - parse_money(fees) - parse_money(fx_cost) - parse_money(slippage)
        )
        if pnl > _EPSILON:
            status = "CLOSED_WIN"
        elif pnl < -_EPSILON:
            status = "CLOSED_LOSS"
        else:
            status = "CLOSED_FLAT"
        conn.execute(
            "INSERT INTO paper_exits (signal_id, exited_at, exit_price,"
            " exit_price_source, exit_snapshot_sha256, fees, fx_cost, slippage,"
            " pnl_net) VALUES (?,?,?,?,?,?,?,?,?)",
            (signal_id, str(exited_at), money_to_str(parse_money(exit_price)),
             exit_price_source, exit_snapshot_sha256,
             money_to_str(parse_money(fees)), money_to_str(parse_money(fx_cost)),
             money_to_str(parse_money(slippage)), money_to_str(pnl)),
        )
        conn.execute(
            "UPDATE paper_signals SET status=? WHERE signal_id=?",
            (status, signal_id),
        )
        conn.commit()
    finally:
        conn.close()
    return {"signal_id": signal_id, "status": status,
            "pnl_net": money_to_str(pnl),
            "execution_gate": "LOCKED", "broker_api_called": False}


def invalidate_signal(
    signal_id: str, reason: str, db_path: Path | None = None
) -> dict[str, Any]:
    conn = _conn(db_path)
    try:
        cur = conn.execute(
            "UPDATE paper_signals SET status='INVALIDATED', status_reason=?"
            " WHERE signal_id=? AND status='OPEN'",
            (reason, signal_id),
        )
        conn.commit()
        ok = cur.rowcount > 0
    finally:
        conn.close()
    return {"signal_id": signal_id, "invalidated": ok,
            "execution_gate": "LOCKED", "broker_api_called": False}


def correct_record(
    signal_id: str, field: str, new_value: str, reason: str,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """No deletes, ever — corrections overwrite ONE allowlisted field and
    write an F13 audit row capturing the prior state."""
    allowed = {"status_reason", "planned_exit_rule", "planned_invalidation_rule"}
    if field not in allowed:
        raise ForwardLedgerError(
            f"field {field!r} is not correctable (allowed: {sorted(allowed)})"
        )
    conn = _conn(db_path)
    try:
        before = conn.execute(
            "SELECT * FROM paper_signals WHERE signal_id=?", (signal_id,)
        ).fetchone()
        if before is None:
            raise ForwardLedgerError(f"unknown signal {signal_id}")
        _p._write_audit_row(
            conn, "paper_signals", signal_id, "CORRECTION",
            {"before": dict(before), "reason": reason},
        )
        conn.execute(
            f"UPDATE paper_signals SET {_p._safe_identifier(field)}=?"
            " WHERE signal_id=?",
            (new_value, signal_id),
        )
        conn.commit()
    finally:
        conn.close()
    return {"signal_id": signal_id, "corrected_field": field,
            "execution_gate": "LOCKED", "broker_api_called": False}


def load_cohort(db_path: Path | None = None) -> dict[str, Any]:
    """Everything the evidence report needs, statuses included in denominators."""
    conn = _conn(db_path)
    try:
        signals = [dict(r) for r in conn.execute(
            "SELECT * FROM paper_signals ORDER BY registered_at").fetchall()]
        exits = {r["signal_id"]: dict(r) for r in conn.execute(
            "SELECT * FROM paper_exits").fetchall()}
    finally:
        conn.close()
    return {"signals": signals, "exits": exits}
