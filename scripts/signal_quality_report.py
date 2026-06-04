"""Outcome-backed signal quality report.

Combines calibration metrics, securities coverage, the feedback loop, and
behavioural-test coverage into a single honest signal-quality score, with hard
caps that prevent over-claiming on thin or fixture-only evidence.

SQ = 10·(0.25·C + 0.20·ECE_score + 0.15·Brier_score + 0.15·Coverage
        + 0.15·Feedback + 0.10·BehavioralTests)

Caps: no real/paper outcomes -> 7.0; NO_DATA -> 7.0; fixtures-only -> 7.0;
ECE>0.20 with n>=50 -> 6.5; no score contract -> 6.0.

Read-only / pure. No execution, no broker calls. Advisory stamps preserved.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_ADVISORY_STAMPS = {
    "advisory_status": "ADVISORY_ONLY", "advisory_only": True,
    "human_execution_required": True, "human_review_required": True,
    "execution_gate": "LOCKED", "broker_api_called": False, "ai_execution_count": 0,
}


def _calibration_component(status: str, real_n: int) -> float:
    if status == "CALIBRATED":
        return 0.8 if real_n >= 50 else 0.7  # real- vs paper-calibrated
    return {
        "NO_DATA": 0.0, "FIXTURE_ONLY": 0.0, "LOW_SAMPLE": 0.2,
        "CALIBRATING": 0.5, "MIS_CALIBRATED": 0.4,
    }.get(status, 0.0)


def _feedback_component(recommendation: dict[str, Any] | None, *, human_reviewed: bool) -> float:
    if not recommendation:
        return 0.0
    n = int(recommendation.get("sample_size", 0) or 0)
    if human_reviewed:
        return 0.9
    if n >= 20:
        return 0.7
    return 0.5


def _bucket_analysis(buckets: list[dict[str, Any]]) -> dict[str, Any]:
    active = [b for b in buckets if (b.get("n", 0) or 0) > 0 and b.get("accuracy") is not None]
    strongest = weakest = None
    over: list[str] = []
    under: list[str] = []
    if active:
        strongest = max(active, key=lambda b: b["accuracy"])
        weakest = min(active, key=lambda b: b["accuracy"])
        for b in active:
            gap = b["accuracy"] - b["confidence"]
            label = f"[{b['lower']:.2f},{b['upper']:.2f})"
            if gap < 0:
                over.append(label)
            elif gap > 0:
                under.append(label)

    def _lab(b):
        return None if b is None else f"[{b['lower']:.2f},{b['upper']:.2f})"

    return {
        "strongest_bucket": _lab(strongest),
        "weakest_bucket": _lab(weakest),
        "overconfident_buckets": over,
        "underconfident_buckets": under,
    }


def build_signal_quality_report(
    metrics: dict[str, Any],
    *,
    coverage_score: float = 0.0,
    recommendation: dict[str, Any] | None = None,
    behavioral_tests_passed: int = 1,
    behavioral_tests_expected: int = 1,
    score_contract_present: bool = True,
    feedback_human_reviewed: bool = False,
    calibration_map: dict[str, Any] | None = None,
) -> dict[str, Any]:
    status = str(metrics.get("calibration_status", "NO_DATA"))
    real_n = int(metrics.get("real_n", 0) or 0)
    paper_n = int(metrics.get("paper_n", 0) or 0)
    backtest_n = int(metrics.get("backtest_n", 0) or 0)
    eligible_n = int(metrics.get("eligible_n", 0) or 0)
    n = int(metrics.get("n", 0) or 0)
    ece = metrics.get("ece")
    brier = metrics.get("brier")

    C = _calibration_component(status, real_n)
    # If an OOS-validated recalibration exists, signal quality reflects the
    # IMPROVED (recalibrated) ECE — honest credit for actually fixing
    # calibration, not just measuring it.
    ece_used = ece
    recalibrated = False
    if calibration_map and calibration_map.get("improved_out_of_sample"):
        cal_ece = calibration_map.get("cal_test_ece")
        if cal_ece is not None and ece is not None and cal_ece < ece:
            ece_used = cal_ece
            recalibrated = True
    ece_score = max(0.0, 1.0 - (ece_used / 0.20)) if ece_used is not None else 0.0
    brier_score = max(0.0, 1.0 - (brier / 0.25)) if brier is not None else 0.0
    cov = max(0.0, min(1.0, float(coverage_score)))
    feedback = _feedback_component(recommendation, human_reviewed=feedback_human_reviewed)
    bt = min(1.0, behavioral_tests_passed / behavioral_tests_expected) if behavioral_tests_expected else 0.0

    sq_raw = 10.0 * (
        0.25 * C + 0.20 * ece_score + 0.15 * brier_score
        + 0.15 * cov + 0.15 * feedback + 0.10 * bt
    )

    caps: list[float] = []
    caps_applied: list[str] = []
    # Signal quality measures whether the SCORES are good. Real, paper, AND
    # backtest evidence all count here (backtest = real forward returns), but
    # NOT for real-money readiness (that keys on real_n alone). Fixtures and
    # no-data are still hard-capped.
    if eligible_n == 0:
        caps.append(7.0); caps_applied.append("no_eligible_outcomes")
    if status == "NO_DATA":
        caps.append(7.0); caps_applied.append("calibration_no_data")
    if status == "FIXTURE_ONLY":
        caps.append(7.0); caps_applied.append("fixtures_only")
    if ece is not None and ece > 0.20 and n >= 50:
        caps.append(6.5); caps_applied.append("high_ece_large_sample")
    if not score_contract_present:
        caps.append(6.0); caps_applied.append("no_score_contract")

    sq = round(min(sq_raw, *caps) if caps else sq_raw, 2)

    # What evidence would most move the needle next?
    if status in {"NO_DATA", "FIXTURE_ONLY"}:
        next_data = "Log and reconcile real/paper trades with score_at_entry to begin calibration."
    elif status in {"LOW_SAMPLE", "CALIBRATING"}:
        next_data = f"Collect more reconciled outcomes (have n={n}; need >=50 for CALIBRATED)."
    elif status == "MIS_CALIBRATED":
        next_data = "Review miscalibrated buckets; do not loosen thresholds."
    elif real_n < 50:
        next_data = f"Accumulate >=50 REAL outcomes (real_n={real_n}) for real-grade calibration."
    else:
        next_data = "Maintain reconciliation discipline; widen archetype coverage."

    analysis = _bucket_analysis(metrics.get("buckets", []) or [])
    payload = {
        "report": "signal_quality_report",
        "signal_quality_score": sq,
        "signal_quality_raw": round(sq_raw, 2),
        "caps_applied": caps_applied,
        "components": {
            "C_calibration": C, "ECE_score": round(ece_score, 4),
            "Brier_score": round(brier_score, 4), "Coverage_score": cov,
            "Feedback_score": feedback, "Behavioral_test_score": round(bt, 4),
        },
        "calibration_status": status, "real_n": real_n, "paper_n": paper_n,
        "backtest_n": backtest_n, "eligible_n": eligible_n, "n": n,
        "recalibration_applied": recalibrated,
        "recommended_next_data_needed": next_data,
        **analysis,
        **_ADVISORY_STAMPS,
    }
    return payload


def build_signal_quality_report_from_db(db_path: Path | None = None) -> dict[str, Any]:
    """Assemble the report from the live DB. Defensive."""
    try:
        try:
            from scripts.score_calibration import build_calibration_metrics_report
            from scripts.securities_master_coverage import build_coverage_report
            from scripts.calibration_recommendations import build_recommendation_from_metrics
            from scripts import core_module_boundary as cmb
        except ModuleNotFoundError:  # pragma: no cover - script-style fallback
            from score_calibration import build_calibration_metrics_report  # type: ignore[no-redef]
            from securities_master_coverage import build_coverage_report  # type: ignore[no-redef]
            from calibration_recommendations import build_recommendation_from_metrics  # type: ignore[no-redef]
            import core_module_boundary as cmb  # type: ignore[no-redef]
        metrics = build_calibration_metrics_report(db_path)
        coverage = build_coverage_report(db_path).get("score", 0.0)
        rec = build_recommendation_from_metrics(metrics)
        # behavioural tests proxy: import isolation holds -> treat as 1/1.
        bt_pass = 1 if cmb.core_import_violations() == [] else 0
        # Fit an OOS-validated recalibration map from the extracted outcomes.
        cmap = None
        try:
            from scripts.outcome_evidence_extractor import extract_from_db
            from scripts.calibration_map import fit_from_outcomes
        except ModuleNotFoundError:  # pragma: no cover - script-style fallback
            from outcome_evidence_extractor import extract_from_db  # type: ignore[no-redef]
            from calibration_map import fit_from_outcomes  # type: ignore[no-redef]
        outcomes = extract_from_db(db_path)
        cmap = fit_from_outcomes(outcomes).to_dict() if outcomes else None
    except Exception:  # pragma: no cover - defensive
        metrics, coverage, rec, bt_pass, cmap = {"calibration_status": "NO_DATA"}, 0.0, None, 0, None
    return build_signal_quality_report(
        metrics, coverage_score=coverage, recommendation=rec,
        behavioral_tests_passed=bt_pass, behavioral_tests_expected=1,
        calibration_map=cmap,
    )


__all__ = ["build_signal_quality_report", "build_signal_quality_report_from_db"]
