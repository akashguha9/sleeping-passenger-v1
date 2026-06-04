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


def run_pipeline(
    db_path: Path | None = None,
    *,
    backtest: bool = False,
    seed_securities: bool = False,
    import_ohlcv: Path | None = None,
    import_outcomes: Path | None = None,
    horizon_days: int = 20,
    write_evidence: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Full evidence pipeline. Steps run in order; writes respect --dry-run.

    Outcome set = DB-extracted (real manual + reconciliation) ∪ imported
    outcomes (paper/real/backtest CSV) ∪ optional universe backtest over
    imported OHLCV. Backtest/paper improve signal quality; real-money readiness
    keys on real_n only.
    """
    from scripts import outcome_evidence_extractor as ex
    from scripts import import_outcomes_csv as ioc
    from scripts import score_calibration as sc
    from scripts import calibration_map as cm
    from scripts import calibration_recommendations as cr
    from scripts import signal_quality_report as sqr
    from scripts import pre_real_money_preflight as prm

    steps: list[str] = []
    do_write = write_evidence and not dry_run

    # 1. seed securities
    if seed_securities:
        if do_write:
            from scripts import securities_master_coverage as smc
            try:
                from scripts import persistence
            except ModuleNotFoundError:  # pragma: no cover
                import persistence  # type: ignore[no-redef]
            n = smc.seed_universe(smc.load_seed_universe(),
                                  db_path if db_path is not None else persistence.DB_PATH)
            steps.append(f"seeded_securities={n}")
        else:
            steps.append("seed_securities=skipped(dry_run)")

    # 2. import OHLCV
    if import_ohlcv is not None:
        from scripts import import_ohlcv_csv as iohlcv
        r = iohlcv.import_ohlcv_file(Path(import_ohlcv), db_path=db_path, dry_run=not do_write)
        steps.append(f"ohlcv_import accepted={r['accepted_count']} written={r['rows_written']}")

    # 3. import outcomes
    if import_outcomes is not None:
        r = ioc.import_outcomes_file(Path(import_outcomes), db_path=db_path, dry_run=not do_write)
        steps.append(f"outcome_import accepted={r['accepted_count']} written={r['rows_written']}")

    # 4-5. assemble outcome evidence (extracted + imported + optional backtest)
    outcomes = list(ex.extract_from_db(db_path))
    outcomes += list(ioc.rebuild_imported_outcomes(db_path))
    if backtest:
        outcomes += list(_backtest_outcomes(db_path))

    # 6-9. metrics / recalibration / recommendation / signal quality
    metrics = sc.compute_calibration_metrics(outcomes)
    cmap = cm.fit_from_outcomes(outcomes).to_dict() if outcomes else None
    rec = cr.build_recommendation_from_metrics(metrics)
    sq = sqr.build_signal_quality_report(
        metrics, coverage_score=_coverage(db_path), recommendation=rec, calibration_map=cmap,
    )

    # 10. readiness gate (keys on real outcomes, never backtest)
    readiness = prm.assess_real_money_readiness(db_path)

    rc = cmap or {}
    return {
        "report": "calibration_pipeline",
        "mode": "backtest" if backtest else "live_outcomes",
        "steps": steps,
        "dry_run": dry_run,
        # provenance
        "real_n": metrics.get("real_n", 0),
        "paper_n": metrics.get("paper_n", 0),
        "backtest_n": metrics.get("backtest_n", 0),
        "synthetic_n": metrics.get("synthetic_n", 0),
        "eligible_n": metrics.get("eligible_n", 0),
        # calibration
        "calibration_status": metrics.get("calibration_status"),
        "ECE": metrics.get("ece"),
        "Brier": metrics.get("brier"),
        "MCE": metrics.get("mce"),
        "log_loss": metrics.get("log_loss"),
        "ECE_CI_95": [metrics.get("ece_ci_lower"), metrics.get("ece_ci_upper")],
        # recalibration
        "recalibration_method": rc.get("method"),
        "raw_brier": rc.get("raw_test_brier"),
        "recalibrated_brier": rc.get("cal_test_brier"),
        "oos_improved": rc.get("improved_out_of_sample", False),
        # quality + readiness
        "signal_quality_score": sq.get("signal_quality_score"),
        "readiness_score": readiness.get("readiness_score"),
        "allowed_mode": readiness.get("allowed_mode"),
        "can_drive_sizing": metrics.get("should_drive_sizing", False),
        # invariants
        "advisory_only": True,
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
    p.add_argument("--seed-securities", action="store_true")
    p.add_argument("--import-ohlcv", type=Path, default=None)
    p.add_argument("--import-outcomes", type=Path, default=None)
    p.add_argument("--backtest", action="store_true",
                   help="Calibrate scores against a universe backtest over imported OHLCV.")
    p.add_argument("--horizon-days", type=int, default=20)
    p.add_argument("--write-evidence", action="store_true", default=True)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    rep = run_pipeline(
        args.db_path, backtest=args.backtest, seed_securities=args.seed_securities,
        import_ohlcv=args.import_ohlcv, import_outcomes=args.import_outcomes,
        horizon_days=args.horizon_days, write_evidence=args.write_evidence,
        dry_run=args.dry_run,
    )
    if args.json:
        print(json.dumps(rep, indent=2, default=str))
    else:
        print(f"mode               : {rep['mode']}  dry_run={rep['dry_run']}")
        if rep["steps"]:
            for s in rep["steps"]:
                print(f"  step             : {s}")
        print(f"provenance         : real={rep['real_n']} paper={rep['paper_n']} "
              f"backtest={rep['backtest_n']} synthetic={rep['synthetic_n']} eligible={rep['eligible_n']}")
        print(f"calibration_status : {rep['calibration_status']}  ECE={rep['ECE']}  Brier={rep['Brier']}")
        print(f"recalibration      : {rep['recalibration_method']} oos_improved={rep['oos_improved']}")
        print(f"signal_quality     : {rep['signal_quality_score']}")
        print(f"readiness          : {rep['readiness_score']}  mode={rep['allowed_mode']}")
        print(f"can_drive_sizing   : {rep['can_drive_sizing']}  (real-money gate keys on real_n)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["run_pipeline"]
