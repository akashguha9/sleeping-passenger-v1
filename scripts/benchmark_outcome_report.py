"""Post-hoc benchmark comparison for matured real-forward outcomes.

Close-the-Loop sprint (2026-07-04), forensic-audit follow-up: the audit
required every realized-return claim to sit next to a same-period benchmark
(SP-050 "no market-index benchmark anywhere in the live outcome path").

This module is **analytics only**:

* It NEVER re-labels an outcome.  Outcome labels were resolved against the
  pre-registered, timestamp-locked target contract
  (``target_event_definition`` at snapshot time) and stay exactly as attached.
* It NEVER mutates ``decision_probability_snapshots`` — read-only queries.
* It NEVER unlocks a predictive claim: ``predictive_claim_allowed`` is
  hardcoded ``False`` here regardless of how flattering or unflattering the
  numbers are.

For each matured real-forward row ``i`` with entry price ``P_entry`` at
``t_entry`` and horizon close ``t_close``::

    realized_return_i  = P_exit / P_entry - 1
    benchmark_return_i = B_exit / B_entry - 1     (same timestamps, tolerance-matched)
    alpha_i            = realized_return_i - benchmark_return_i

Aggregate honesty metrics::

    base_rate        = mean(y_i)
    brier_model      = mean((p_i - y_i)^2)
    brier_coin       = mean((0.5 - y_i)^2)         (always-0.5 reference)
    brier_base_rate  = mean((base_rate - y_i)^2)   (constant base-rate reference)
    skill_vs_coin    = brier_coin - brier_model    (>0 means beats coin)
    skill_vs_base    = brier_base_rate - brier_model

A model that cannot beat ``brier_base_rate`` has no demonstrated edge — the
report says so in plain text instead of hiding it.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

try:  # package layout
    from scripts import persistence
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.real_price_outcome_evidence import (
        DEFAULT_MAX_GAP_DAYS,
        _parse_iso,
        load_price_series,
        normalize_symbol,
        price_point_on_or_before,
    )
    from scripts.runtime_common import write_json_atomic
except ModuleNotFoundError:  # pragma: no cover - flat-layout fallback
    import persistence  # type: ignore[no-redef]
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]
    from real_price_outcome_evidence import (  # type: ignore[no-redef]
        DEFAULT_MAX_GAP_DAYS,
        _parse_iso,
        load_price_series,
        normalize_symbol,
        price_point_on_or_before,
    )
    from runtime_common import write_json_atomic  # type: ignore[no-redef]

DEFAULT_BENCHMARK = "SPY"
REPORT_RELPATH = Path("runtime") / "release" / "benchmark_comparison.json"

_ANALYTICS_STAMP = {
    "report_kind": "POST_HOC_ANALYTICS",
    "post_hoc_target_note": (
        "Outcome labels were resolved against the pre-registered, "
        "timestamp-locked target contract and are NOT re-labeled here. "
        "Benchmark alpha is descriptive analytics computed after the fact."
    ),
    "predictive_claim_allowed": False,
}


def _matured_rows(db_path: Any) -> list[dict[str, Any]]:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT snapshot_id, ticker, model_probability, outcome_label,
                   entry_price, entry_price_timestamp_utc, horizon_close_utc
            FROM decision_probability_snapshots
            WHERE is_real_outcome = 1
              AND outcome_label IN (0, 1)
              AND outcome_kind = 'real_forward'
            ORDER BY snapshot_id
            """
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    return [dict(r) for r in rows]


def _mean(xs: Sequence[float]) -> float | None:
    vals = [float(x) for x in xs if x is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def build_benchmark_comparison(
    *,
    db_path: Any = None,
    benchmark_symbol: str = DEFAULT_BENCHMARK,
    max_gap_days: float = DEFAULT_MAX_GAP_DAYS,
    now_utc: str | None = None,
) -> dict[str, Any]:
    """Read-only benchmark comparison over the matured real-forward corpus."""
    db = db_path if db_path is not None else persistence.DB_PATH
    rows = _matured_rows(db)
    generated_at = now_utc or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    report: dict[str, Any] = {
        "report": "benchmark_outcome_comparison",
        "generated_at_utc": generated_at,
        "benchmark_symbol": benchmark_symbol,
        "n_matured_real_forward": len(rows),
        **_ANALYTICS_STAMP,
        **advisory_safety_stamps(),
    }

    if not rows:
        report["status"] = "NO_MATURED_OUTCOMES"
        report["detail"] = (
            "No matured real-forward outcomes exist; run "
            "scripts/run_daily_outcome_maturation.py --write first."
        )
        return report

    bench_sym = normalize_symbol(benchmark_symbol)
    symbols = {bench_sym} if bench_sym else set()
    for r in rows:
        sym = normalize_symbol(r.get("ticker"))
        if sym:
            symbols.add(sym)
    series = load_price_series(db, symbols=symbols)
    bench_bars = series.get(bench_sym or "", [])

    per_row: list[dict[str, Any]] = []
    n_bench_matched = 0
    for r in rows:
        sym = normalize_symbol(r.get("ticker"))
        entry_ts = _parse_iso(r.get("entry_price_timestamp_utc"))
        close_ts = _parse_iso(r.get("horizon_close_utc"))
        entry_price = r.get("entry_price")
        item: dict[str, Any] = {
            "snapshot_id": r["snapshot_id"],
            "ticker": r.get("ticker"),
            "model_probability": r.get("model_probability"),
            "outcome_label": r.get("outcome_label"),
            "realized_return": None,
            "benchmark_return": None,
            "alpha": None,
            "benchmark_status": "BENCHMARK_UNAVAILABLE",
        }
        bars = series.get(sym or "", [])
        if entry_ts and close_ts and entry_price and float(entry_price) > 0 and bars:
            exit_pt = price_point_on_or_before(bars, close_ts, max_gap_days=max_gap_days)
            if exit_pt is not None:
                item["realized_return"] = exit_pt[1] / float(entry_price) - 1.0
        if entry_ts and close_ts and bench_bars:
            b_entry = price_point_on_or_before(bench_bars, entry_ts, max_gap_days=max_gap_days)
            b_exit = price_point_on_or_before(bench_bars, close_ts, max_gap_days=max_gap_days)
            if b_entry is not None and b_exit is not None and b_entry[1] > 0:
                item["benchmark_return"] = b_exit[1] / b_entry[1] - 1.0
                item["benchmark_status"] = "OK"
                n_bench_matched += 1
        if item["realized_return"] is not None and item["benchmark_return"] is not None:
            item["alpha"] = item["realized_return"] - item["benchmark_return"]
        per_row.append(item)

    labels = [float(r["outcome_label"]) for r in rows]
    probs = [float(r["model_probability"]) for r in rows]
    base_rate = sum(labels) / len(labels)
    brier_model = _mean([(p - y) ** 2 for p, y in zip(probs, labels)])
    brier_coin = _mean([(0.5 - y) ** 2 for y in labels])
    brier_base = _mean([(base_rate - y) ** 2 for y in labels])

    beats_coin = brier_model is not None and brier_coin is not None and brier_model < brier_coin
    beats_base = brier_model is not None and brier_base is not None and brier_model < brier_base

    report.update(
        {
            "status": "OK" if n_bench_matched else "BENCHMARK_UNAVAILABLE",
            "n_benchmark_matched": n_bench_matched,
            "base_rate": base_rate,
            "hit_rate": base_rate,
            "mean_model_probability": _mean(probs),
            "mean_realized_return": _mean([i["realized_return"] for i in per_row]),
            "mean_benchmark_return": _mean([i["benchmark_return"] for i in per_row]),
            "mean_alpha": _mean([i["alpha"] for i in per_row]),
            "brier_model": brier_model,
            "brier_always_half": brier_coin,
            "brier_base_rate": brier_base,
            "skill_vs_coin": (brier_coin - brier_model) if beats_coin or brier_model is not None else None,
            "skill_vs_base_rate": (brier_base - brier_model) if brier_model is not None else None,
            "beats_coin_baseline": bool(beats_coin),
            "beats_base_rate_baseline": bool(beats_base),
            "honest_verdict": (
                "Model Brier beats both reference predictors."
                if beats_coin and beats_base
                else "NO DEMONSTRATED EDGE: model Brier does not beat the "
                "constant base-rate reference predictor on this corpus."
                if not beats_base
                else "Model beats the coin baseline but not the base-rate baseline."
            ),
            "per_row": per_row,
        }
    )
    return report


def write_report(report: dict[str, Any], path: Any = None) -> Path:
    target = Path(path) if path is not None else (persistence.DB_PATH.parent.parent / REPORT_RELPATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(target, report)
    return target


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--benchmark-symbol", default=DEFAULT_BENCHMARK)
    p.add_argument("--write", action="store_true", help="persist the JSON report")
    p.add_argument("--db")
    args = p.parse_args(argv)
    report = build_benchmark_comparison(
        db_path=args.db, benchmark_symbol=args.benchmark_symbol
    )
    if args.write:
        path = write_report(report)
        report["report_path"] = str(path)
    print(json.dumps({k: v for k, v in report.items() if k != "per_row"}, indent=2, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
