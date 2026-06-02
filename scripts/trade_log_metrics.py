"""Deterministic trade-log analytics from a Google-Sheet CSV export.

Ingests one normalized trade-log export (via
:mod:`scripts.google_sheet_schema`) and computes capital, P/L, the win-rate
triad (marked / all-row / closed-only), profit factor, expectancy, R metrics,
TP/runner rates, country concentration, model-version cohorts, and outcome
maturity counts (via :mod:`scripts.outcome_maturity`).

Hard truth invariants encoded here
----------------------------------
* ``CAPITAL AFTER ROW`` is **free / unallocated cash**, never total equity.
* Marked equity = ``starting_capital + latest cumulative P/L``.
* Open allocated capital is approximated from per-row remaining fraction and is
  reported separately; any reconstruction gap is surfaced, not hidden.

Contract — pure module / advisory-only
--------------------------------------
No DB, no network, no broker calls, no AI execution.  Output carries the
canonical advisory-only safety stamps.  It produces *no* trade instruction.

CLI::

    python scripts/trade_log_metrics.py --input exports/trade_log.csv \
        --starting-capital 4000
    python scripts/trade_log_metrics.py --input exports/trade_log.csv \
        --starting-capital 4000 --format json --report-date 2026-06-02
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.google_sheet_schema import TradeLogRow, load_trade_log_csv
    from scripts.outcome_maturity import (
        MATURITY_PENDING,
        classify_maturity,
        summarize_maturity,
    )
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]
    from google_sheet_schema import TradeLogRow, load_trade_log_csv  # type: ignore[no-redef]
    from outcome_maturity import (  # type: ignore[no-redef]
        MATURITY_PENDING,
        classify_maturity,
        summarize_maturity,
    )

LOW_SAMPLE_THRESHOLD = 10
MEDIUM_SAMPLE_THRESHOLD = 30
US_HEAVY_SHARE = 0.50
US_OVERCONCENTRATED_SHARE = 0.65

_US_NAMES = {"UNITED STATES", "US", "USA", "U.S.", "U.S.A.", "AMERICA"}


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _norm(value: Any) -> str:
    return re.sub(r"\s+", "_", str(value or "").strip().upper())


def _is_closed(row: TradeLogRow) -> bool:
    ts, es = _norm(row.trade_state), _norm(row.exit_stage_v2)
    return ts in {"CLOSED", "STOP_CLOSED", "CLOSE_TRADE_SYNCED"} or "CLOSED" in es


def _is_open_or_partial(row: TradeLogRow) -> bool:
    if _is_closed(row):
        return False
    ts = _norm(row.trade_state)
    return ts.startswith("OPEN") or ts == "PARTIAL_TP_LOGGED" or ts == "NEW"


def _round(value: float | None, ndigits: int = 6) -> float | None:
    if value is None:
        return None
    return round(value, ndigits)


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


# --------------------------------------------------------------------------- #
# Capital
# --------------------------------------------------------------------------- #
def compute_capital(rows: Sequence[TradeLogRow], starting_capital: float) -> dict[str, Any]:
    pls = [r.profit_loss for r in rows]
    sum_pl = sum(pls)
    cum_last = next(
        (r.cumulative_pl for r in reversed(rows) if r.cumulative_pl is not None), None
    )
    total_pl = cum_last if cum_last is not None else sum_pl
    marked_equity = starting_capital + total_pl

    free_cash = next(
        (r.capital_after_row for r in reversed(rows) if r.capital_after_row is not None),
        None,
    )

    allocated_open = 0.0
    for r in rows:
        if _is_open_or_partial(r):
            remaining = r.remaining_pct if r.remaining_pct is not None else 1.0
            allocated_open += r.money_allocated * remaining

    # Honest reconstruction check (FX/leverage simplifications mean this may not
    # close exactly — we report the gap rather than hide it).
    reconstructed = (free_cash or 0.0) + allocated_open
    discrepancy = marked_equity - reconstructed

    return {
        "starting_capital": _round(starting_capital, 4),
        "marked_equity": _round(marked_equity, 4),
        "total_pl": _round(total_pl, 4),
        "sum_of_row_pl": _round(sum_pl, 4),
        "cumulative_pl_last_row": _round(cum_last, 4),
        "return_pct": _round(total_pl / starting_capital, 6) if starting_capital else None,
        "free_cash": _round(free_cash, 6),
        "allocated_open_capital": _round(allocated_open, 4),
        "capital_after_row_is_total_equity": False,
        "reconstruction_discrepancy": _round(discrepancy, 4),
    }


# --------------------------------------------------------------------------- #
# Win rates / expectancy
# --------------------------------------------------------------------------- #
def _win_loss_flat(pls: Iterable[float]) -> tuple[int, int, int]:
    wins = sum(1 for p in pls if p > 0)
    losses = sum(1 for p in pls if p < 0)
    flats = sum(1 for p in pls if p == 0)
    return wins, losses, flats


def compute_win_rates(rows: Sequence[TradeLogRow]) -> dict[str, Any]:
    pls = [r.profit_loss for r in rows]
    n = len(rows)
    wins, losses, flats = _win_loss_flat(pls)
    nonflat = wins + losses

    closed = [r for r in rows if _is_closed(r)]
    c_wins, c_losses, _ = _win_loss_flat([r.profit_loss for r in closed])
    c_nonflat = c_wins + c_losses

    return {
        "wins": wins,
        "losses": losses,
        "flats": flats,
        "n_rows": n,
        "marked_win_rate_ex_flat": _round(wins / nonflat, 4) if nonflat else None,
        "all_row_win_rate": _round(wins / n, 4) if n else None,
        "closed_win_rate": _round(c_wins / c_nonflat, 4) if c_nonflat else None,
        "closed_rows": len(closed),
        "closed_wins": c_wins,
        "closed_losses": c_losses,
    }


def compute_expectancy(rows: Sequence[TradeLogRow]) -> dict[str, Any]:
    pls = [r.profit_loss for r in rows]
    wins_pl = [p for p in pls if p > 0]
    losses_pl = [p for p in pls if p < 0]
    wins, losses, _ = _win_loss_flat(pls)
    nonflat = wins + losses

    avg_win = _mean(wins_pl)
    avg_loss_abs = abs(_mean(losses_pl)) if losses_pl else None
    gross_profit = sum(wins_pl)
    gross_loss = abs(sum(losses_pl))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None

    p_win = (wins / nonflat) if nonflat else None
    if p_win is not None and avg_win is not None:
        loss_term = (1 - p_win) * (avg_loss_abs or 0.0)
        expectancy = p_win * avg_win - loss_term
    else:
        expectancy = None

    nonflat_pl = [p for p in pls if p != 0]
    expectancy_nonflat = (sum(nonflat_pl) / len(nonflat_pl)) if nonflat_pl else None

    return {
        "average_win": _round(avg_win, 4),
        "average_loss_abs": _round(avg_loss_abs, 4),
        "gross_profit": _round(gross_profit, 4),
        "gross_loss": _round(gross_loss, 4),
        "profit_factor": _round(profit_factor, 4),
        "expectancy_per_trade": _round(expectancy, 4),
        "expectancy_nonflat": _round(expectancy_nonflat, 4),
    }


def compute_r_metrics(rows: Sequence[TradeLogRow]) -> dict[str, Any]:
    r_values = [r.r_multiple for r in rows if r.r_multiple is not None]
    r_wins = sum(1 for r in r_values if r > 0)
    r_losses = sum(1 for r in r_values if r < 0)
    return {
        "r_count": len(r_values),
        "r_expectancy": _round(_mean(r_values), 4),
        "r_wins": r_wins,
        "r_losses": r_losses,
        "r_win_rate": _round(r_wins / (r_wins + r_losses), 4) if (r_wins + r_losses) else None,
    }


# --------------------------------------------------------------------------- #
# TP / runner rates
# --------------------------------------------------------------------------- #
def compute_tp_runner_rates(
    rows: Sequence[TradeLogRow], report_date: date
) -> dict[str, Any]:
    eligible = [
        r
        for r in rows
        if classify_maturity(r, report_date)["maturity"] != MATURITY_PENDING
    ]
    n_elig = len(eligible)

    tp1_hits = 0
    tp2_hits = 0
    for r in eligible:
        es, ts = _norm(r.exit_stage_v2), _norm(r.trade_state)
        note = _norm(r.action_required_v2)
        if "TP1" in es or "PARTIAL_TP" in ts or "PARTIAL_TP" in es:
            tp1_hits += 1
        if "TP2" in es or "TP2" in note or r.booked_pct >= 0.8:
            tp2_hits += 1

    open_partial = [r for r in rows if _is_open_or_partial(r)]
    runner_protected = sum(
        1
        for r in open_partial
        if "RUNNER" in _norm(r.exit_stage_v2)
        or "PROTECTED" in _norm(r.exit_stage_v2)
        or "PROTECTED_STOP" in _norm(r.action_required_v2)
    )

    return {
        "tp1_eligible": n_elig,
        "tp1_hits": tp1_hits,
        "tp1_hit_rate": _round(tp1_hits / n_elig, 4) if n_elig else None,
        "tp2_hits": tp2_hits,
        "tp2_hit_rate": _round(tp2_hits / n_elig, 4) if n_elig else None,
        "open_or_partial_rows": len(open_partial),
        "runner_protected": runner_protected,
        "runner_protection_rate": (
            _round(runner_protected / len(open_partial), 4) if open_partial else None
        ),
    }


# --------------------------------------------------------------------------- #
# Country concentration
# --------------------------------------------------------------------------- #
def compute_country_concentration(rows: Sequence[TradeLogRow]) -> dict[str, Any]:
    n = len(rows)
    counts: dict[str, int] = {}
    alloc: dict[str, float] = {}
    for r in rows:
        c = r.country.strip() or "UNKNOWN"
        counts[c] = counts.get(c, 0) + 1
        alloc[c] = alloc.get(c, 0.0) + r.money_allocated
    total_alloc = sum(alloc.values())
    k = len(counts)

    hhi_count = sum((cnt / n) ** 2 for cnt in counts.values()) if n else 0.0
    hhi_alloc = (
        sum((a / total_alloc) ** 2 for a in alloc.values()) if total_alloc > 0 else 0.0
    )

    if k > 1 and n:
        h = -sum(
            (cnt / n) * math.log(cnt / n) for cnt in counts.values() if cnt > 0
        )
        entropy_norm = h / math.log(k)
    else:
        entropy_norm = 0.0

    diversity_score = max(0.0, min(100.0, 100.0 * entropy_norm * (1 - hhi_count)))

    n_us = sum(cnt for name, cnt in counts.items() if name.upper() in _US_NAMES)
    us_share = n_us / n if n else 0.0
    country_warning = None
    if us_share > US_OVERCONCENTRATED_SHARE:
        country_warning = "US_OVERCONCENTRATED"
    elif us_share > US_HEAVY_SHARE:
        country_warning = "US_HEAVY"

    return {
        "country_count": k,
        "counts": dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "hhi_count": _round(hhi_count, 4),
        "hhi_alloc": _round(hhi_alloc, 4),
        "entropy_norm_count": _round(entropy_norm, 4),
        "country_diversity_score": _round(diversity_score, 2),
        "us_share": _round(us_share, 4),
        "country_warning": country_warning,
    }


# --------------------------------------------------------------------------- #
# Model-version cohorts
# --------------------------------------------------------------------------- #
def model_cohort(row: TradeLogRow) -> str:
    if row.model_version:
        return row.model_version
    d = row.date
    if d is None:
        return "unknown"
    if date(2026, 5, 14) <= d <= date(2026, 5, 20):
        return "v2026_05_early"
    if date(2026, 5, 21) <= d <= date(2026, 5, 24):
        return "v2026_05_override"
    if date(2026, 5, 25) <= d <= date(2026, 5, 31):
        return "v2026_05_recalibration"
    if d >= date(2026, 6, 1):
        return "v2026_06_global_watchlist"
    return "v_pre_2026_05_14"


def _cohort_stats(rows: Sequence[TradeLogRow]) -> dict[str, Any]:
    n = len(rows)
    wr = compute_win_rates(rows)
    exp = compute_expectancy(rows)
    cap_pl = sum(r.profit_loss for r in rows)
    closed = sum(1 for r in rows if _is_closed(r))
    conc = compute_country_concentration(rows)
    if n < LOW_SAMPLE_THRESHOLD:
        confidence, sample_warning = "LOW", "LOW_SAMPLE_SIZE"
    elif n < MEDIUM_SAMPLE_THRESHOLD:
        confidence, sample_warning = "MEDIUM", None
    else:
        confidence, sample_warning = "HIGH", None
    return {
        "n": n,
        "total_pl": _round(cap_pl, 4),
        "win_rate": wr["marked_win_rate_ex_flat"],
        "wins": wr["wins"],
        "losses": wr["losses"],
        "flats": wr["flats"],
        "average_win": exp["average_win"],
        "average_loss_abs": exp["average_loss_abs"],
        "profit_factor": exp["profit_factor"],
        "expectancy": exp["expectancy_per_trade"],
        "closed_evidence_ratio": _round(closed / n, 4) if n else None,
        "country_entropy": conc["entropy_norm_count"],
        "confidence": confidence,
        "sample_warning": sample_warning,
        "maturity_note": "promising but immature" if n < MEDIUM_SAMPLE_THRESHOLD else "sample sufficient",
    }


def compute_model_versions(rows: Sequence[TradeLogRow]) -> dict[str, Any]:
    cohorts: dict[str, list[TradeLogRow]] = {}
    for r in rows:
        cohorts.setdefault(model_cohort(r), []).append(r)
    return {name: _cohort_stats(rs) for name, rs in sorted(cohorts.items())}


# --------------------------------------------------------------------------- #
# Top-level report
# --------------------------------------------------------------------------- #
def build_report(
    rows: Sequence[TradeLogRow],
    starting_capital: float,
    report_date: date,
    *,
    parse_issues: Sequence[Any] = (),
) -> dict[str, Any]:
    capital = compute_capital(rows, starting_capital)
    win_rate = compute_win_rates(rows)
    expectancy = compute_expectancy(rows)
    r_metrics = compute_r_metrics(rows)
    tp_runner = compute_tp_runner_rates(rows, report_date)
    concentration = compute_country_concentration(rows)
    model_versions = compute_model_versions(rows)
    maturity = summarize_maturity(rows, report_date)

    warnings: list[str] = []
    if concentration["country_warning"]:
        warnings.append(concentration["country_warning"])
    if expectancy["profit_factor"] is None:
        warnings.append("PROFIT_FACTOR_UNDEFINED_NO_LOSSES")
    if win_rate["closed_win_rate"] is None or win_rate["closed_rows"] < LOW_SAMPLE_THRESHOLD:
        warnings.append("CLOSED_ONLY_EVIDENCE_IMMATURE")
    if abs(capital["reconstruction_discrepancy"] or 0.0) > 1.0:
        warnings.append("CAPITAL_RECONSTRUCTION_DISCREPANCY")

    report: dict[str, Any] = {
        "report_date": report_date.isoformat(),
        "row_count": len(rows),
        "parse_error_count": sum(1 for i in parse_issues if getattr(i, "severity", "") == "ERROR"),
        "capital": capital,
        "win_rate": win_rate,
        "expectancy": expectancy,
        "r_metrics": r_metrics,
        "tp_runner": tp_runner,
        "country_concentration": concentration,
        "model_version_performance": model_versions,
        "outcome_maturity_counts": maturity["maturity_counts"],
        "outcome_maturity": {
            "pending_horizon": maturity["pending_horizon"],
            "score_eligible": maturity["score_eligible"],
            "closed": maturity["closed"],
            "horizon_bucket_counts": maturity["horizon_bucket_counts"],
        },
        "warnings": warnings,
    }
    report.update(advisory_safety_stamps())
    report["human_execution_required"] = True
    report["real_money_sizing_impact"] = "PROHIBITED"
    return report


# --------------------------------------------------------------------------- #
# Rendering / CLI
# --------------------------------------------------------------------------- #
def render_text(report: dict[str, Any]) -> str:
    cap = report["capital"]
    wr = report["win_rate"]
    exp = report["expectancy"]
    conc = report["country_concentration"]
    lines = [
        "TRADE LOG METRICS (advisory-only; human execution required)",
        f"report_date: {report['report_date']}  rows: {report['row_count']}",
        "",
        "CAPITAL",
        f"  starting_capital     : {cap['starting_capital']}",
        f"  marked_equity        : {cap['marked_equity']}  (= start + cumulative P/L)",
        f"  total_pl             : {cap['total_pl']}   return_pct: {cap['return_pct']}",
        f"  free_cash            : {cap['free_cash']}  (CAPITAL AFTER ROW = free cash, NOT equity)",
        f"  allocated_open       : {cap['allocated_open_capital']}",
        f"  reconstruction_gap   : {cap['reconstruction_discrepancy']}",
        "",
        "WIN RATE",
        f"  wins/losses/flats    : {wr['wins']}/{wr['losses']}/{wr['flats']}",
        f"  marked_ex_flat       : {wr['marked_win_rate_ex_flat']}",
        f"  all_row              : {wr['all_row_win_rate']}",
        f"  closed_only          : {wr['closed_win_rate']}  (rows: {wr['closed_rows']})",
        "",
        "EXPECTANCY",
        f"  average_win          : {exp['average_win']}",
        f"  average_loss_abs     : {exp['average_loss_abs']}",
        f"  profit_factor        : {exp['profit_factor']}",
        f"  expectancy_per_trade : {exp['expectancy_per_trade']}",
        "",
        "DIVERSITY",
        f"  country_diversity    : {conc['country_diversity_score']}  HHI(count): {conc['hhi_count']}",
        f"  us_share             : {conc['us_share']}  warning: {conc['country_warning']}",
        "",
        f"WARNINGS: {', '.join(report['warnings']) or '(none)'}",
        f"execution_gate={report['execution_gate']}  broker_api_called={report['broker_api_called']}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI
    parser = argparse.ArgumentParser(
        description="Compute advisory-only trade-log metrics from a CSV export."
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--starting-capital", type=float, required=True)
    parser.add_argument("--report-date", default=None)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

    result = load_trade_log_csv(args.input)
    report_date = (
        date.fromisoformat(args.report_date) if args.report_date else date.today()
    )
    report = build_report(
        result.rows, args.starting_capital, report_date, parse_issues=result.issues
    )
    if args.format == "json":
        print(json.dumps(report, indent=2, default=str))
    else:
        print(render_text(report))
    return 0


__all__ = [
    "compute_capital",
    "compute_win_rates",
    "compute_expectancy",
    "compute_r_metrics",
    "compute_tp_runner_rates",
    "compute_country_concentration",
    "compute_model_versions",
    "model_cohort",
    "build_report",
    "render_text",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
