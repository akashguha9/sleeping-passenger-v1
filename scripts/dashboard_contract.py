"""Stable dashboard JSON contract (advisory-only).

A single, versioned shape that a frontend / API / Google-Sheet export can
consume without re-deriving anything.  It composes the trade-log metrics, the
outcome-maturity counts, the model-version cohorts and (optionally) the daily
discovery board into one document, and it LABELS the capital figures explicitly
so no consumer can confuse free cash with total equity.

Contract — pure module / advisory-only: no DB, no network, no broker calls, no
AI execution.  Output always carries the advisory-safety block with
``execution_gate=LOCKED`` and ``broker_api_called=False``.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts.google_sheet_schema import TradeLogRow, load_trade_log_csv
    from scripts.trade_log_metrics import _is_closed, _is_open_or_partial, build_report
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from google_sheet_schema import TradeLogRow, load_trade_log_csv  # type: ignore[no-redef]
    from trade_log_metrics import _is_closed, _is_open_or_partial, build_report  # type: ignore[no-redef]

CONTRACT_VERSION = "trade_log_discovery_dashboard/v1"

CLOSED_SAMPLE_MIN = 10


def _realised_unrealised(rows: Sequence[TradeLogRow]) -> tuple[float, float]:
    realised = sum(r.profit_loss for r in rows if _is_closed(r))
    unrealised = sum(r.profit_loss for r in rows if _is_open_or_partial(r))
    return round(realised, 4), round(unrealised, 4)


def build_dashboard(
    rows: Sequence[TradeLogRow],
    starting_capital: float,
    report_date: date,
    *,
    discovery_board: dict[str, Any] | None = None,
    parse_issues: Sequence[Any] = (),
) -> dict[str, Any]:
    report = build_report(rows, starting_capital, report_date, parse_issues=parse_issues)
    cap = report["capital"]
    wr = report["win_rate"]
    exp = report["expectancy"]
    conc = report["country_concentration"]
    realised, unrealised = _realised_unrealised(rows)
    closed_immature = wr["closed_rows"] < CLOSED_SAMPLE_MIN or wr["closed_win_rate"] is None

    contract: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "report_date": report["report_date"],
        "labels": {
            "marked_equity": "starting_capital + latest cumulative P/L",
            "free_cash": "CAPITAL AFTER ROW — free/unallocated cash, NOT total equity",
            "open_allocated_capital": "capital tied up in open/partial positions",
            "realised_pl": "P/L from closed rows",
            "unrealised_marked_pl": "marked P/L on open/partial rows",
            "closed_only_evidence_immature": (
                "closed-sample too small to be conclusive" if closed_immature else "ok"
            ),
        },
        "capital": {
            "starting_capital": cap["starting_capital"],
            "marked_equity": cap["marked_equity"],
            "free_cash": cap["free_cash"],
            "open_allocated_capital": cap["allocated_open_capital"],
            "total_pl": cap["total_pl"],
            "realised_pl": realised,
            "unrealised_marked_pl": unrealised,
            "return_pct": cap["return_pct"],
            "capital_after_row_is_total_equity": False,
            "reconstruction_discrepancy": cap["reconstruction_discrepancy"],
        },
        "win_rate": {
            "wins": wr["wins"],
            "losses": wr["losses"],
            "flats": wr["flats"],
            "marked_win_rate_ex_flat": wr["marked_win_rate_ex_flat"],
            "all_row_win_rate": wr["all_row_win_rate"],
            "closed_win_rate": wr["closed_win_rate"],
            "closed_only_evidence_immature": closed_immature,
        },
        "expectancy": {
            "average_win": exp["average_win"],
            "average_loss_abs": exp["average_loss_abs"],
            "profit_factor": exp["profit_factor"],
            "expectancy_per_trade": exp["expectancy_per_trade"],
        },
        "diversity": {
            "country_hhi": conc["hhi_count"],
            "country_entropy": conc["entropy_norm_count"],
            "country_diversity_score": conc["country_diversity_score"],
            "us_share": conc["us_share"],
            "warnings": [conc["country_warning"]] if conc["country_warning"] else [],
        },
        "outcome_maturity": report["outcome_maturity"],
        "model_versions": report["model_version_performance"],
        "advisory_safety": {
            "advisory_only": True,
            "human_execution_required": True,
            "broker_api_called": report["broker_api_called"],
            "ai_execution_count": report["ai_execution_count"],
            "execution_gate": report["execution_gate"],
            "real_money_sizing_impact": report["real_money_sizing_impact"],
        },
        "warnings": report["warnings"],
    }
    if discovery_board is not None:
        contract["discovery_board"] = discovery_board
    return contract


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI
    parser = argparse.ArgumentParser(description="Emit the unified dashboard JSON contract.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--starting-capital", type=float, required=True)
    parser.add_argument("--report-date", default=None)
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

    result = load_trade_log_csv(args.input)
    report_date = date.fromisoformat(args.report_date) if args.report_date else date.today()
    contract = build_dashboard(
        result.rows, args.starting_capital, report_date, parse_issues=result.issues
    )
    print(json.dumps(contract, indent=2, default=str))
    return 0


__all__ = ["CONTRACT_VERSION", "build_dashboard"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
