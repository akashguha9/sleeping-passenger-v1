"""Drawdown and stop-breach monitor over canonical holdings.

Open-the-Gate sprint (2026-07-04).  The last missing risk-engine organ
(forensic audit SP-044: "no live portfolio drawdown monitor"): once stops
are operator-confirmed, something must WATCH them.

Math (long-only book today; short formulas ready per spec)::

    Unrealized_Return_h            = (P_h - Entry_h) / Entry_h
    Leveraged_Unrealized_Return_h  = Unrealized_Return_h × Leverage_h
    Distance_To_Stop_h (long)      = (P_h - Stop_h) / P_h
    Stop_Breached_h    (long)      = P_h <= Stop_h
    Portfolio_Unrealized_PnL       = Σ (P_h - Entry_h) × Qty_h × Lev_h
    Portfolio_Drawdown_Fraction    = min(0, PnL / Portfolio_Equity_Basis)

Alert policy::

    breach                         -> CRITICAL
    distance <= 1%                 -> CRITICAL
    distance <= 3%                 -> WARNING
    drawdown <= -5%                -> WARNING
    drawdown <= -10%               -> CRITICAL

Honesty rules:

* positions without a USABLE (operator-confirmed) stop are reported as
  UNMONITORABLE — never silently skipped, never guessed;
* stale/missing prices block that position's evaluation (the gate already
  enforces this; the monitor surfaces it);
* the monitor NEVER executes anything — it emits advisory alerts through
  the operator alert bridge and writes append-only artifacts
  (``runtime/drawdown_monitor.jsonl`` + a latest snapshot).

Advisory-only, read-only over holdings and prices.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

try:  # package layout
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.holdings_truth_gate import load_holdings_truth_gate
    from scripts.operator_alert_bridge import (
        SEV_CRITICAL,
        SEV_WARNING,
        _alert,
        dispatch_alerts,
    )
    from scripts.runtime_common import REPO_ROOT, write_json_atomic
except ModuleNotFoundError:  # pragma: no cover - flat-layout fallback
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]
    from holdings_truth_gate import load_holdings_truth_gate  # type: ignore[no-redef]
    from operator_alert_bridge import (  # type: ignore[no-redef]
        SEV_CRITICAL,
        SEV_WARNING,
        _alert,
        dispatch_alerts,
    )
    from runtime_common import REPO_ROOT, write_json_atomic  # type: ignore[no-redef]

HISTORY_PATH = REPO_ROOT / "runtime" / "drawdown_monitor.jsonl"
LATEST_PATH = REPO_ROOT / "runtime" / "drawdown_monitor_latest.json"

NEAR_STOP_CRITICAL = 0.01
NEAR_STOP_WARNING = 0.03
DRAWDOWN_WARNING = -0.05
DRAWDOWN_CRITICAL = -0.10


def _resolved(default: Path) -> Path:
    """Honor NBI_ARTIFACT_DIR (test isolation, repo convention)."""
    import os as _os

    override = _os.environ.get("NBI_ARTIFACT_DIR")
    if not override:
        return default
    d = Path(override)
    d.mkdir(parents=True, exist_ok=True)
    return d / default.name


def run_drawdown_monitor(
    *,
    holdings_path: Any = None,
    db_path: Any = None,
    now_utc: datetime | None = None,
    write: bool = False,
    dispatch: bool = False,
) -> dict[str, Any]:
    """One monitor pass.  Never executes; only measures and alerts."""
    now = now_utc or datetime.now(timezone.utc)
    gate = load_holdings_truth_gate(
        path=holdings_path, db_path=db_path, now_utc=now
    )
    rows: list[dict[str, Any]] = []
    alerts: list[dict[str, Any]] = []
    pnl_total = 0.0
    breach_count = 0
    near_stop_count = 0

    def alert(severity: str, category: str, title: str, message: str) -> None:
        alerts.append(_alert(
            now=now, severity=severity, category=category, title=title,
            message=message, source="drawdown_stop_monitor",
            requires_operator_action=True, run_id=None,
        ))

    for pos in gate["positions"]:  # READY only: confirmed stop + fresh price
        entry = float(pos["entry_price"])
        price = float(pos["current_price"])
        qty = float(pos["quantity"] or 0.0)
        lev = float(pos["leverage"] or 1.0)
        stop = float(pos["stop_loss"])
        unreal = (price - entry) / entry if entry else 0.0
        dist = (price - stop) / price if price else 0.0
        breached = price <= stop
        pnl = (price - entry) * qty * lev
        pnl_total += pnl
        row = {
            "ticker": pos["ticker"],
            "state": "MONITORED",
            "entry_price": entry,
            "current_price": price,
            "price_as_of": pos.get("price_as_of"),
            "stop_loss": stop,
            "quantity": qty,
            "leverage": lev,
            "unrealized_return": round(unreal, 6),
            "leveraged_unrealized_return": round(unreal * lev, 6),
            "distance_to_stop": round(dist, 6),
            "stop_breached": bool(breached),
            "unrealized_pnl": round(pnl, 4),
        }
        rows.append(row)
        if breached:
            breach_count += 1
            alert(
                SEV_CRITICAL, "stop_breach",
                f"STOP BREACHED: {pos['ticker']}",
                f"price {price} <= confirmed stop {stop} "
                f"(leverage {lev:g}x). ADVISORY: review exit immediately — "
                "a human must decide; nothing is executed.",
            )
        elif dist <= NEAR_STOP_CRITICAL:
            near_stop_count += 1
            alert(
                SEV_CRITICAL, "near_stop",
                f"WITHIN 1% OF STOP: {pos['ticker']}",
                f"distance_to_stop {dist:.2%} (price {price}, stop {stop})",
            )
        elif dist <= NEAR_STOP_WARNING:
            near_stop_count += 1
            alert(
                SEV_WARNING, "near_stop",
                f"Within 3% of stop: {pos['ticker']}",
                f"distance_to_stop {dist:.2%} (price {price}, stop {stop})",
            )

    for pos in gate["blocked_positions"]:
        rows.append({
            "ticker": pos["ticker"],
            "state": "UNMONITORABLE",
            "reason": pos["risk_monitoring"],
            "leverage": pos["leverage"],
        })

    equity = gate.get("portfolio_equity_basis")
    drawdown_fraction = None
    if equity:
        drawdown_fraction = round(min(0.0, pnl_total / equity), 6)
        if drawdown_fraction <= DRAWDOWN_CRITICAL:
            alert(
                SEV_CRITICAL, "portfolio_drawdown",
                "Portfolio drawdown beyond -10%",
                f"drawdown fraction {drawdown_fraction:.2%} on cost-basis "
                "equity — ADVISORY: de-risk review required",
            )
        elif drawdown_fraction <= DRAWDOWN_WARNING:
            alert(
                SEV_WARNING, "portfolio_drawdown",
                "Portfolio drawdown beyond -5%",
                f"drawdown fraction {drawdown_fraction:.2%} on cost-basis equity",
            )

    monitorable = [r for r in rows if r["state"] == "MONITORED"]
    status = (
        "NO_MONITORABLE_POSITIONS" if not monitorable
        else "BREACH" if breach_count
        else "NEAR_STOP" if near_stop_count
        else "OK"
    )
    report = {
        "report": "drawdown_stop_monitor",
        "generated_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": status,
        "gate_operational_state": gate["operational_state"],
        "monitored_count": len(monitorable),
        "unmonitorable_count": len(rows) - len(monitorable),
        "stop_breach_count": breach_count,
        "near_stop_count": near_stop_count,
        "portfolio_unrealized_pnl": round(pnl_total, 4),
        "portfolio_equity_basis": equity,
        "portfolio_drawdown_fraction": drawdown_fraction,
        "positions": rows,
        "alerts_generated": len(alerts),
        "next_operator_action": (
            "Confirm stops (--write-template -> confirm -> --apply-confirmed)"
            if not monitorable and gate["missing_stop_count"]
            + gate["unconfirmed_stop_count"] > 0
            else "Review breached/near-stop positions — human decision required"
            if breach_count or near_stop_count
            else "None — monitoring"
        ),
        **advisory_safety_stamps(),
    }
    if write:
        hist = _resolved(HISTORY_PATH)
        hist.parent.mkdir(parents=True, exist_ok=True)
        with open(hist, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(report, ensure_ascii=False,
                                default=str) + "\n")
        write_json_atomic(_resolved(LATEST_PATH), report)
    if dispatch and alerts:
        dispatch_alerts(alerts, write=write, now_utc=now, echo=True)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--write", action="store_true",
                   help="append to the monitor history + snapshot")
    p.add_argument("--dispatch", action="store_true",
                   help="dispatch generated alerts to the operator queue")
    p.add_argument("--db")
    args = p.parse_args(argv)
    report = run_drawdown_monitor(
        db_path=args.db, write=args.write, dispatch=args.dispatch
    )
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["status"] in ("OK", "NO_MONITORABLE_POSITIONS") else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
