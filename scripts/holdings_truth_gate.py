"""Canonical holdings truth gate for the risk engine.

Close-the-Loop sprint (2026-07-04).  Forensic-audit findings SP-001/005/009/
010/011/012: the only stop/TP monitoring in the system read the demoted
``moltbook/open_positions.json`` phantom ledger while the file the project
itself declares "the only canonical truth for OPEN positions"
(``data/daily_payload/verified_current_holdings.json``) was consumed by
nothing, carried no stop fields, and had no freshness gate.

This module is that gate.  It is the ONLY sanctioned way for risk/action
machinery to obtain active positions:

* **Freshness fail-closed** — ``run_date`` older than ``max_age_days``
  (default 3) yields ``HOLDINGS_TRUTH_STALE``; missing/invalid file yields
  ``HOLDINGS_TRUTH_MISSING`` / ``HOLDINGS_TRUTH_INVALID``.  A non-OK status
  returns ZERO monitorable positions — stale truth must never silently feed
  stop-breach math.
* **Stop discipline fail-closed** — a position without a numeric
  ``stop_loss`` is returned as ``BLOCKED_MISSING_STOP`` and excluded from
  monitorable positions.  No stop, no "healthy".
* **Leverage explicit** — ``leverage`` is surfaced on every row; a leveraged
  position missing its stop escalates to ``BLOCKED_MISSING_STOP_LEVERAGED``
  (severity CRITICAL).  4x INR names can never be treated as quiet 1x risk.
* **Price honesty** — ``current_price`` is attached only from ingested
  ``market_data`` bars with a ``price_as_of`` timestamp; a missing or stale
  bar (older than ``max_price_age_days``) blocks monitoring with
  ``BLOCKED_STALE_PRICE`` / ``BLOCKED_NO_PRICE`` instead of evaluating stops
  against fiction.

Advisory-only: this module reads files and the local DB.  It never places,
sizes, or executes anything.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

try:  # package layout
    from scripts import persistence
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.runtime_common import REPO_ROOT
except ModuleNotFoundError:  # pragma: no cover - flat-layout fallback
    import persistence  # type: ignore[no-redef]
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]
    from runtime_common import REPO_ROOT  # type: ignore[no-redef]

HOLDINGS_TRUTH_PATH = REPO_ROOT / "data" / "daily_payload" / "verified_current_holdings.json"
ENV_PATH_OVERRIDE = "HOLDINGS_TRUTH_PATH"

DEFAULT_MAX_AGE_DAYS = 3.0
DEFAULT_MAX_PRICE_AGE_DAYS = 3.0

STATUS_OK = "OK"
STATUS_STALE = "HOLDINGS_TRUTH_STALE"
STATUS_MISSING = "HOLDINGS_TRUTH_MISSING"
STATUS_INVALID = "HOLDINGS_TRUTH_INVALID"

MON_READY = "READY"
MON_MISSING_STOP = "BLOCKED_MISSING_STOP"
MON_MISSING_STOP_LEV = "BLOCKED_MISSING_STOP_LEVERAGED"
MON_NO_PRICE = "BLOCKED_NO_PRICE"
MON_STALE_PRICE = "BLOCKED_STALE_PRICE"

SOURCE_NAME = "verified_current_holdings"


def _parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text.replace("+00:00", "Z"), fmt)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    return None


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f


def _latest_prices(db_path: Any, symbols: set[str]) -> dict[str, tuple[str, float]]:
    """Latest real close per symbol from ingested market_data bars."""
    out: dict[str, tuple[str, float]] = {}
    if not symbols:
        return out
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return out
    try:
        rows = conn.execute(
            "SELECT raw_payload FROM signal_events WHERE source_name = 'market_data'"
        ).fetchall()
    except sqlite3.Error:
        return out
    finally:
        conn.close()
    for (raw,) in rows:
        try:
            p = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        sym = str(p.get("symbol") or "").upper()
        if sym not in symbols:
            continue
        ts = str(p.get("timestamp") or "")
        close = _num(p.get("close")) or _num(p.get("latest_price"))
        if not ts or close is None or close <= 0:
            continue
        prev = out.get(sym)
        if prev is None or ts > prev[0]:
            out[sym] = (ts, close)
    return out


def load_holdings_truth_gate(
    *,
    path: Any = None,
    db_path: Any = None,
    now_utc: datetime | None = None,
    max_age_days: float = DEFAULT_MAX_AGE_DAYS,
    max_price_age_days: float = DEFAULT_MAX_PRICE_AGE_DAYS,
    attach_prices: bool = True,
) -> dict[str, Any]:
    """Load, validate, and freshness-gate the canonical holdings truth."""
    now = now_utc or datetime.now(timezone.utc)
    target = Path(
        path
        if path is not None
        else os.environ.get(ENV_PATH_OVERRIDE) or HOLDINGS_TRUTH_PATH
    )
    db = db_path if db_path is not None else persistence.DB_PATH

    gate: dict[str, Any] = {
        "report": "holdings_truth_gate",
        "source": SOURCE_NAME,
        "path": str(target),
        "checked_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "max_age_days": max_age_days,
        "status": STATUS_OK,
        "run_date": None,
        "age_days": None,
        "canonical_holding_count": 0,
        "monitorable_position_count": 0,
        "missing_stop_count": 0,
        "leveraged_position_count": 0,
        "leveraged_without_stop_count": 0,
        "broker_confirmed_count": 0,
        "risk_engine_ready": False,
        "positions": [],
        "blocked_positions": [],
        "issues": [],
        **advisory_safety_stamps(),
    }

    if not target.exists():
        gate["status"] = STATUS_MISSING
        gate["issues"].append(f"holdings truth file missing: {target}")
        return gate
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        positions_raw = payload["positions"]
        assert isinstance(positions_raw, list)
    except Exception as exc:  # noqa: BLE001 - disclosed as INVALID
        gate["status"] = STATUS_INVALID
        gate["issues"].append(f"holdings truth unreadable: {type(exc).__name__}")
        return gate

    run_date = _parse_date(payload.get("run_date"))
    gate["run_date"] = payload.get("run_date")
    if run_date is None:
        gate["status"] = STATUS_INVALID
        gate["issues"].append("holdings truth has no parseable run_date")
        return gate
    age_days = (now - run_date).total_seconds() / 86400.0
    gate["age_days"] = round(age_days, 2)
    if age_days > max_age_days:
        gate["status"] = STATUS_STALE
        gate["issues"].append(
            f"HOLDINGS_TRUTH_STALE: run_date {payload.get('run_date')} is "
            f"{age_days:.1f} days old (max {max_age_days:g}); all position "
            "management is demoted to review-only until the operator "
            "re-verifies holdings"
        )

    open_rows = [
        r for r in positions_raw
        if isinstance(r, dict) and str(r.get("status", "OPEN")).upper() == "OPEN"
    ]
    gate["canonical_holding_count"] = len(open_rows)

    symbols = {
        str(r.get("normalized_ticker") or r.get("ticker") or "").upper()
        for r in open_rows
    }
    prices = _latest_prices(db, symbols) if attach_prices else {}

    for row in open_rows:
        display = str(row.get("ticker") or "").upper()
        symbol = str(row.get("normalized_ticker") or display).upper()
        leverage = _num(row.get("leverage")) or 1.0
        stop_loss = _num(row.get("stop_loss"))
        take_profit = _num(row.get("take_profit"))
        entry_price = _num(row.get("entry_price"))
        price = prices.get(symbol)
        price_as_of, current_price = (price if price else (None, None))
        price_age_days = None
        if price_as_of:
            price_dt = _parse_date(price_as_of)
            if price_dt is not None:
                price_age_days = (now - price_dt).total_seconds() / 86400.0

        blocks: list[str] = []
        if stop_loss is None:
            blocks.append(
                MON_MISSING_STOP_LEV if leverage > 1 else MON_MISSING_STOP
            )
        if current_price is None:
            blocks.append(MON_NO_PRICE)
        elif price_age_days is not None and price_age_days > max_price_age_days:
            blocks.append(MON_STALE_PRICE)

        norm = {
            "ticker": display,
            "symbol": symbol,
            "asset_name": row.get("asset_name"),
            "quantity": _num(row.get("quantity")),
            "entry_price": entry_price,
            "entry_timestamp": row.get("opened_at"),
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "invalidation_level": _num(row.get("invalidation_level")),
            "leverage": leverage,
            "currency": row.get("currency"),
            "current_price": current_price,
            "price_as_of": price_as_of,
            "price_age_days": (
                round(price_age_days, 2) if price_age_days is not None else None
            ),
            "broker_confirmed": bool(row.get("broker_confirmed", False)),
            "human_confirmed": bool(row.get("human_confirmed", False)),
            "source": SOURCE_NAME,
            "provenance": row.get("created_via"),
            "freshness_timestamp": payload.get("run_date"),
            "risk_monitoring": MON_READY if not blocks else blocks[0],
            "risk_monitoring_blocks": blocks,
        }
        if leverage > 1:
            gate["leveraged_position_count"] += 1
            if stop_loss is None:
                gate["leveraged_without_stop_count"] += 1
        if stop_loss is None:
            gate["missing_stop_count"] += 1
        if norm["broker_confirmed"]:
            gate["broker_confirmed_count"] += 1

        if blocks or gate["status"] != STATUS_OK:
            gate["blocked_positions"].append(norm)
        else:
            gate["positions"].append(norm)

    gate["monitorable_position_count"] = len(gate["positions"])
    gate["risk_engine_ready"] = (
        gate["status"] == STATUS_OK
        and gate["canonical_holding_count"] > 0
        and gate["missing_stop_count"] == 0
    )
    if gate["missing_stop_count"]:
        gate["issues"].append(
            f"{gate['missing_stop_count']}/{gate['canonical_holding_count']} "
            "open positions have no stop_loss recorded; they are BLOCKED from "
            "risk monitoring (no stop -> no healthy)"
        )
    if gate["leveraged_without_stop_count"]:
        gate["issues"].append(
            f"CRITICAL: {gate['leveraged_without_stop_count']} LEVERAGED "
            "position(s) carry no stop_loss — largest un-instrumented loss "
            "path in the book"
        )
    return gate


def canonical_open_position_count(**kwargs: Any) -> int:
    """Open-position count from canonical truth (for capacity gates)."""
    gate = load_holdings_truth_gate(attach_prices=False, **kwargs)
    return int(gate["canonical_holding_count"])


def to_action_engine_position(
    norm: dict[str, Any], *, now_utc: datetime | None = None
) -> dict[str, Any]:
    """Shape a READY canonical position for the action engine's schema.

    Only valid for rows whose ``risk_monitoring`` is READY (stop + fresh
    price present).  Blocked rows must never be adapted — they are surfaced
    as blocked, not monitored.
    """
    if norm.get("risk_monitoring") != MON_READY:
        raise ValueError(
            f"cannot adapt non-READY position {norm.get('ticker')}: "
            f"{norm.get('risk_monitoring')}"
        )
    now = now_utc or datetime.now(timezone.utc)
    entry = float(norm["entry_price"])
    current = float(norm["current_price"])
    opened = _parse_date(norm.get("entry_timestamp"))
    days_held = int((now - opened).days) if opened else 0
    return {
        "ticker": norm["ticker"],
        "entry_price": entry,
        "current_price": current,
        "pnl_pct": round((current / entry - 1.0) * 100.0, 4) if entry else 0.0,
        "stop_loss": float(norm["stop_loss"]),
        "take_profit": (
            float(norm["take_profit"]) if norm.get("take_profit") is not None
            else current * 10.0  # no TP recorded: unreachable sentinel, never triggers
        ),
        "state": "OPEN",
        "position_size": f"LEVERAGE_{norm['leverage']:g}X" if norm["leverage"] > 1 else "UNLEVERAGED",
        "chaos_flag": False,
        "entry_type": "CLEAN",
        "thesis_cluster": str(norm.get("currency") or "UNSPECIFIED"),
        "time_in_trade": f"{days_held}d",
        "priority_score": 0.0,
        "leverage": norm["leverage"],
        "source": SOURCE_NAME,
        "price_as_of": norm.get("price_as_of"),
    }


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--path")
    p.add_argument("--db")
    p.add_argument("--max-age-days", type=float, default=DEFAULT_MAX_AGE_DAYS)
    args = p.parse_args(argv)
    gate = load_holdings_truth_gate(
        path=args.path, db_path=args.db, max_age_days=args.max_age_days
    )
    print(json.dumps(gate, indent=2, default=str))
    return 0 if gate["status"] == STATUS_OK else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
