#!/usr/bin/env python3
"""S4-E2: forward-evidence report with strict sample-size gates.

    python scripts/forward_evidence_report.py --db runtime/mvp_local.db \
        --out runtime/forward_evidence_report.json

Metrics (exact Decimal where money; population stats in float):
    WinRate, LossRate, mean win/loss, Expectancy after costs,
    normalized Expectancy_R, max drawdown over the realized equity
    curve, Brier score (when probabilities exist), 95% CI on per-trade
    returns, Sharpe (suppressed below n=30).

Mandatory honesty gates (verbatim contract):
    T < 30                       -> sample-size suppression message
    CI95 lower bound <= 0        -> "Edge not proven."
    T >= 30 and CI lower > 0     -> "directionally positive" — still not
                                    proven-for-size.

Edge does not move because this report exists.  It moves only when the
gates pass on REAL closed forward trades.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.forward_evidence_ledger import load_cohort  # noqa: E402
from scripts.money import money_to_str  # noqa: E402
from scripts.runtime_common import restrict_file_permissions  # noqa: E402

GATE_MIN_T = 30

MSG_SAMPLE = (
    "Sample size below 30. Real-money readiness remains capped. "
    "No edge claim permitted."
)
MSG_CI_ZERO = (
    "Confidence interval includes zero or negative expectancy. Edge not proven."
)
MSG_DIRECTIONAL = (
    "Forward evidence is directionally positive, but still requires "
    "continued paper-trade monitoring before size-up."
)
MSG_INSUFFICIENT = "Forward evidence is insufficient to claim positive edge."


def compute_report(cohort: dict[str, Any]) -> dict[str, Any]:
    signals = cohort["signals"]
    exits = cohort["exits"]

    n_signals = len(signals)
    by_status: dict[str, int] = {}
    for s in signals:
        by_status[s["status"]] = by_status.get(s["status"], 0) + 1

    closed = [s for s in signals
              if s["status"] in ("CLOSED_WIN", "CLOSED_LOSS", "CLOSED_FLAT")]
    T = len(closed)
    pnls: list[Decimal] = []
    caps: list[Decimal] = []
    costs: list[Decimal] = []
    probs: list[tuple[float, int]] = []
    for s in closed:
        e = exits.get(s["signal_id"])
        if e is None:
            continue
        pnl = Decimal(str(e["pnl_net"]))
        pnls.append(pnl)
        caps.append(Decimal(str(s["capital_at_risk"] or "0")))
        costs.append(
            Decimal(str(e["fees"])) + Decimal(str(e["fx_cost"]))
            + Decimal(str(e["slippage"]))
        )
        if s["probability"] is not None:
            probs.append((float(s["probability"]), 1 if pnl > 0 else 0))

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    win_rate = (len(wins) / T) if T else None
    loss_rate = (1 - win_rate) if win_rate is not None else None
    avg_win = (sum(wins, Decimal(0)) / len(wins)) if wins else Decimal(0)
    avg_loss = (
        sum((abs(p) for p in losses), Decimal(0)) / len(losses)
        if losses else Decimal(0)
    )
    avg_cost = (sum(costs, Decimal(0)) / T) if T else Decimal(0)
    # pnl_net already includes costs; the explicit decomposition is
    # reported for transparency.  Expectancy = mean net P/L per trade.
    expectancy = (sum(pnls, Decimal(0)) / T) if T else None
    avg_capital = (
        sum(caps, Decimal(0)) / len([c for c in caps if c > 0])
        if any(c > 0 for c in caps) else None
    )
    expectancy_r = (
        (expectancy / avg_capital)
        if (expectancy is not None and avg_capital and avg_capital > 0)
        else None
    )

    # Equity curve + max drawdown (Decimal arithmetic).
    equity = Decimal(0)
    peak = Decimal(0)
    mdd = Decimal(0)
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        if peak > 0:
            dd = (equity - peak) / peak
            mdd = min(mdd, dd)

    # CI95 on per-trade P/L (float stats over exact Decimal inputs).
    mu = s_dev = se = ci_lo = ci_hi = None
    if T >= 2:
        rs = [float(p) for p in pnls]
        mu = sum(rs) / T
        s_dev = math.sqrt(sum((r - mu) ** 2 for r in rs) / (T - 1))
        se = s_dev / math.sqrt(T)
        ci_lo, ci_hi = mu - 1.96 * se, mu + 1.96 * se

    brier = (
        sum((p - y) ** 2 for p, y in probs) / len(probs) if probs else None
    )
    sharpe = None
    sharpe_note = None
    if T >= GATE_MIN_T and s_dev:
        sharpe = mu / s_dev if s_dev else None
    else:
        sharpe_note = "Sharpe suppressed: sample size below 30."

    # Honesty gates.
    statements: list[str] = []
    edge_proven = False
    if T < GATE_MIN_T:
        statements.append(MSG_SAMPLE)
        statements.append(MSG_INSUFFICIENT)
    elif ci_lo is None or ci_lo <= 0 or (expectancy or Decimal(0)) <= 0:
        statements.append(MSG_CI_ZERO)
    else:
        statements.append(MSG_DIRECTIONAL)

    return {
        "statements": statements,
        "edge_proven": edge_proven,
        "registered_forward_signals": n_signals,
        "status_breakdown": by_status,
        "closed_forward_trades": T,
        "wins": len(wins),
        "losses": len(losses),
        "flats": T - len(wins) - len(losses),
        "invalid_or_data_invalid": by_status.get("INVALIDATED", 0)
        + by_status.get("DATA_INVALID", 0),
        "win_rate": win_rate,
        "loss_rate": loss_rate,
        "avg_win": money_to_str(avg_win),
        "avg_loss": money_to_str(avg_loss),
        "avg_cost": money_to_str(avg_cost),
        "expectancy": money_to_str(expectancy) if expectancy is not None else None,
        "expectancy_normalized": (
            money_to_str(expectancy_r) if expectancy_r is not None else None
        ),
        "max_drawdown": money_to_str(mdd),
        "ci95_mean": mu,
        "ci95_lower": ci_lo,
        "ci95_upper": ci_hi,
        "brier_score": brier,
        "sharpe": sharpe,
        "sharpe_note": sharpe_note,
        "min_forward_trade_gate": GATE_MIN_T,
        "advisory_status": "ADVISORY_ONLY",
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "ai_execution_count": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    report = compute_report(load_cohort(args.db))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, default=str))
    restrict_file_permissions(args.out)
    print(f"[forward_evidence_report] T={report['closed_forward_trades']} "
          f"of {report['registered_forward_signals']} registered")
    for line in report["statements"]:
        print(f"[forward_evidence_report] {line}")
    print(f"[forward_evidence_report] report: {args.out}")
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI entry point
    raise SystemExit(main())
