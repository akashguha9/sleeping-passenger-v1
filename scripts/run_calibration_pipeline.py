"""End-to-end calibration pipeline (operator/demo CLI).

Runs the full advisory calibration stack on either a backtest over historical
OHLCV (``--backtest``) or the live extracted outcomes (default):

  outcomes -> calibration metrics (ECE/Brier/Murphy/bootstrap)
           -> OOS-validated recalibration map (isotonic/Platt)
           -> signal quality + readiness mode

Read-only. No execution, no broker calls. Backtest evidence calibrates the
SCORES; it never lifts real-money readiness (which keys on real outcomes).

Usage:
    python scripts/run_calibration_pipeline.py
    python scripts/run_calibration_pipeline.py --backtest --json
    python scripts/run_calibration_pipeline.py --db-path runtime/mvp_local.db
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _backtest_outcomes(db_path: Path | None) -> list[Any]:
    """Backtest the seeded universe over real OHLCV from the DB (if present)."""
    from scripts import backtest_calibration as bt
    from scripts import securities_master_coverage as smc

    series: dict[str, list[dict[str, Any]]] = {}
    for entry in smc.load_seed_universe():
        bars = bt.load_ohlcv_from_db(entry["symbol"], db_path)
        if len(bars) >= 30:
            series[entry["symbol"]] = bars
    if not series:
        return []
    # Real OHLCV from the store -> IMPORTED provenance.
    return bt.run_backtest(series, price_provenance=bt.PROV_IMPORTED)["outcomes"]


def run_pipeline(db_path: Path | None = None, *, backtest: bool = False) -> dict[str, Any]:
    from scripts import outcome_evidence_extractor as ex
    from scripts import score_calibration as sc
    from scripts import calibration_map as cm
    from scripts import calibration_recommendations as cr
    from scripts import signal_quality_report as sqr

    outcomes = _backtest_outcomes(db_path) if backtest else ex.extract_from_db(db_path)
    metrics = sc.compute_calibration_metrics(outcomes)
    cmap = cm.fit_from_outcomes(outcomes).to_dict() if outcomes else None
    rec = cr.build_recommendation_from_metrics(metrics)
    sq = sqr.build_signal_quality_report(
        metrics,
        coverage_score=_coverage(db_path),
        recommendation=rec,
        calibration_map=cmap,
    )
    return {
        "report": "calibration_pipeline",
        "mode": "backtest" if backtest else "live_outcomes",
        "provenance": {
            "real_n": metrics.get("real_n", 0),
            "paper_n": metrics.get("paper_n", 0),
            "backtest_n": metrics.get("backtest_n", 0),
            "synthetic_n": metrics.get("synthetic_n", 0),
            "eligible_n": metrics.get("eligible_n", 0),
        },
        "calibration": {
            "status": metrics.get("calibration_status"),
            "ece": metrics.get("ece"),
            "ece_ci": [metrics.get("ece_ci_lower"), metrics.get("ece_ci_upper")],
            "brier": metrics.get("brier"),
            "reliability": metrics.get("reliability"),
            "resolution": metrics.get("resolution"),
            "should_drive_sizing": metrics.get("should_drive_sizing", False),
        },
        "recalibration": cmap,
        "recommendation": {
            "category": rec.get("recommendation"),
            "threshold_shift": rec.get("recommended_threshold_shift"),
            "applied": rec.get("applied", False),
        },
        "signal_quality_score": sq.get("signal_quality_score"),
        "advisory_status": "ADVISORY_ONLY",
        "human_execution_required": True,
        "broker_api_called": False,
    }


def _coverage(db_path: Path | None) -> float:
    try:
        from scripts.securities_master_coverage import build_coverage_report
        return float(build_coverage_report(db_path).get("score", 0.0))
    except Exception:
        return 0.0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="End-to-end advisory calibration pipeline.")
    p.add_argument("--db-path", type=Path, default=None)
    p.add_argument("--backtest", action="store_true",
                   help="Calibrate scores against a backtest over real OHLCV.")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    rep = run_pipeline(args.db_path, backtest=args.backtest)
    if args.json:
        print(json.dumps(rep, indent=2, default=str))
    else:
        prov = rep["provenance"]
        cal = rep["calibration"]
        print(f"mode               : {rep['mode']}")
        print(f"provenance         : real={prov['real_n']} paper={prov['paper_n']} "
              f"backtest={prov['backtest_n']} eligible={prov['eligible_n']}")
        print(f"calibration_status : {cal['status']}  ECE={cal['ece']}  Brier={cal['brier']}")
        rc = rep["recalibration"] or {}
        print(f"recalibration      : {rc.get('method', 'none')} "
              f"improved_oos={rc.get('improved_out_of_sample', False)}")
        print(f"recommendation     : {rep['recommendation']['category']} "
              f"(applied={rep['recommendation']['applied']})")
        print(f"signal_quality     : {rep['signal_quality_score']}")
        print(f"should_drive_sizing: {cal['should_drive_sizing']}  (real-money gate keys on real_n)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["run_pipeline"]
