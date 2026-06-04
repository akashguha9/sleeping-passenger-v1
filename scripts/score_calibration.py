"""Score calibration from reconciled outcomes (false-confidence repair).

The signal scores in this MVP are hand-tuned weights (config/thresholds.yaml).
They are NOT empirically calibrated until enough real reconciled outcomes
exist to say anything about them. This module computes an HONEST calibration
summary from the local reconciliation history and provides an *envelope* that
labels every score with its calibration status — so a precise-looking 0.91
can never be presented as if it were validated.

It deliberately does NOT change the scoring weights. Year-1 priority is
survival and feedback, not PnL maximisation; the right move is to label the
uncertainty, not to fabricate a calibration.

Calibration status ladder (by reconciled sample size):

    0                       -> UNCALIBRATED   (no outcome evidence at all)
    1 .. LOW_SAMPLE_MAX     -> LOW_SAMPLE     (too few to infer anything)
    .. CALIBRATING_MAX      -> CALIBRATING    (accumulating; not proof)
    >= CALIBRATED_MIN       -> CALIBRATED     (reviewable — still not alpha proof)

``score_should_drive_sizing`` is True ONLY when CALIBRATED. Below that the
operator is told, in words, not to size position from the score.

Safety
------
Read-only with respect to the DB. Pure compute on the rows it is handed.
Carries advisory invariant stamps. No broker calls, no execution, stdlib only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Status constants.
UNCALIBRATED = "UNCALIBRATED"
LOW_SAMPLE = "LOW_SAMPLE"
CALIBRATING = "CALIBRATING"
CALIBRATED = "CALIBRATED"
# Extended status vocabulary for the metrics layer (compute_calibration_metrics).
NO_DATA = "NO_DATA"
MIS_CALIBRATED = "MIS_CALIBRATED"
FIXTURE_ONLY = "FIXTURE_ONLY"

# Calibration-quality gates (metrics layer).
ECE_MAX = 0.10
BRIER_MAX = 0.25
# Default score buckets: [lower, upper). The last bucket is inclusive of 1.0.
DEFAULT_BUCKETS: tuple[tuple[float, float], ...] = (
    (0.00, 0.20),
    (0.20, 0.40),
    (0.40, 0.60),
    (0.60, 0.75),
    (0.75, 0.90),
    (0.90, 1.0001),  # inclusive of 1.0
)
_LOGLOSS_DELTA = 1e-6
_WILSON_Z = 1.96

# Sample-size thresholds. Aligned with the conservative spirit of
# scripts/calibration_gate.py (20 / 50) so the two layers agree.
LOW_SAMPLE_MAX = 19      # 1..19 inclusive -> LOW_SAMPLE
CALIBRATING_MAX = 49     # 20..49 inclusive -> CALIBRATING
CALIBRATED_MIN = 50      # >=50 -> CALIBRATED

# Outcome vocabulary already used by reconcile_trade.
_RESOLVED = {"WIN", "LOSS", "BREAKEVEN"}

_ADVISORY_STAMPS = {
    "advisory_only": True,
    "advisory_status": "ADVISORY_ONLY",
    "human_execution_required": True,
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "ai_execution_count": 0,
}

_STATUS_MESSAGE = {
    UNCALIBRATED: (
        "Score is advisory and NOT empirically calibrated — no reconciled "
        "outcomes exist yet. Do not size positions from this score."
    ),
    LOW_SAMPLE: (
        "Score is advisory and low-confidence — too few reconciled outcomes "
        "to validate it. Do not size positions from this score."
    ),
    CALIBRATING: (
        "Score calibration is in progress — outcomes are accumulating but "
        "this is not yet proof of edge. Do not size positions from this score."
    ),
    CALIBRATED: (
        "Score has a reviewable calibration sample. This is process evidence, "
        "not a profitability guarantee; size conservatively and keep reviewing."
    ),
}


def classify_calibration_status(sample_size: int) -> str:
    if sample_size <= 0:
        return UNCALIBRATED
    if sample_size <= LOW_SAMPLE_MAX:
        return LOW_SAMPLE
    if sample_size <= CALIBRATING_MAX:
        return CALIBRATING
    return CALIBRATED


def _confidence_bucket(status: str) -> str:
    return {
        UNCALIBRATED: "NONE",
        LOW_SAMPLE: "VERY_LOW",
        CALIBRATING: "LOW",
        CALIBRATED: "MODERATE",
    }[status]


def compute_score_calibration(
    reconciliations: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Compute an honest calibration summary from reconciliation rows.

    A "resolved" row is one whose outcome_status is WIN / LOSS / BREAKEVEN.
    ``win_rate`` and ``false_positive_rate`` are computed over resolved rows
    only (UNKNOWN rows are excluded so they cannot inflate confidence).
    ``false_positive_rate`` = fraction of acted-on signals that lost.
    """
    wins = losses = breakeven = 0
    pnl_total = 0.0
    pnl_count = 0
    for row in reconciliations:
        status = str(row.get("outcome_status", "") or "").strip().upper()
        if status == "WIN":
            wins += 1
        elif status == "LOSS":
            losses += 1
        elif status == "BREAKEVEN":
            breakeven += 1
        else:
            continue  # UNKNOWN / unresolved — excluded from rates
        try:
            pnl_total += float(row.get("pnl_estimate", 0.0) or 0.0)
            pnl_count += 1
        except (TypeError, ValueError):
            pass

    resolved = wins + losses + breakeven
    win_rate = (wins / resolved) if resolved else None
    false_positive_rate = (losses / resolved) if resolved else None
    avg_return = (pnl_total / pnl_count) if pnl_count else None

    status = classify_calibration_status(resolved)
    summary = {
        "total_reconciled": resolved,
        "wins": wins,
        "losses": losses,
        "breakeven": breakeven,
        "win_rate": win_rate,
        "false_positive_rate": false_positive_rate,
        "average_realized_return": avg_return,
        "sample_size": resolved,
        "confidence_bucket": _confidence_bucket(status),
        "calibration_status": status,
        "score_should_drive_sizing": status == CALIBRATED,
        "message": _STATUS_MESSAGE[status],
        "thresholds": {
            "low_sample_max": LOW_SAMPLE_MAX,
            "calibrating_max": CALIBRATING_MAX,
            "calibrated_min": CALIBRATED_MIN,
        },
    }
    summary.update(_ADVISORY_STAMPS)
    return summary


def score_calibration_envelope(
    score: Any,
    summary: dict[str, Any] | None = None,
    *,
    label: str = "priority_score",
) -> dict[str, Any]:
    """Wrap a single score with its calibration metadata.

    The point of the envelope is that a raw number can never travel without
    its calibration status attached, so no surface can render a precise score
    as if it were validated.
    """
    status = str((summary or {}).get("calibration_status", UNCALIBRATED))
    sample = int((summary or {}).get("sample_size", 0) or 0)
    drive = bool((summary or {}).get("score_should_drive_sizing", False))
    return {
        "label": label,
        "score": score,
        "score_calibration_status": status,
        "score_sample_size": sample,
        "score_should_drive_sizing": drive,
        "warning": _STATUS_MESSAGE.get(status, _STATUS_MESSAGE[UNCALIBRATED]),
        **_ADVISORY_STAMPS,
    }


def build_score_calibration_report(db_path: Path | None = None) -> dict[str, Any]:
    """Read reconciliations from the local DB and compute the summary.

    Read-only and defensive: any DB problem degrades to an UNCALIBRATED
    summary (the safe, no-false-confidence default) rather than raising.
    """
    try:
        try:
            from scripts import persistence
        except ModuleNotFoundError:  # pragma: no cover - script-style fallback
            import persistence  # type: ignore[no-redef]
        rows = persistence.get_all_reconciliations(
            db_path if db_path is not None else persistence.DB_PATH
        )
    except Exception:  # pragma: no cover - defensive
        rows = []
    return compute_score_calibration(rows)


# ---------------------------------------------------------------------------
# Mathematical calibration metrics (ECE/MCE/Brier/LogLoss/Wilson/Bayesian)
# ---------------------------------------------------------------------------

import math as _math


def _normalize_score(value: Any) -> float | None:
    try:
        s = float(value)
    except (TypeError, ValueError):
        return None
    if s > 1.0:  # treat as a 0..100 score
        s = s / 100.0
    return min(1.0, max(0.0, s))


def _y_of(label: str) -> float | None:
    if label == "WIN":
        return 1.0
    if label == "LOSS":
        return 0.0
    if label == "BREAKEVEN":
        return 0.5
    return None


def _wilson_interval(wins: float, n: int, z: float = _WILSON_Z) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 0.0)
    p = wins / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * _math.sqrt((p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def compute_calibration_metrics(
    outcomes: list[Any],
    *,
    buckets: tuple[tuple[float, float], ...] = DEFAULT_BUCKETS,
    human_approved: bool = False,
) -> dict[str, Any]:
    """Full calibration diagnostics over OutcomeEvidence records.

    Only calibration-eligible outcomes are used. BREAKEVEN is modelled as
    y_i = 0.5. Synthetic-only evidence yields FIXTURE_ONLY and can never be
    sizing-grade. Pure compute; never fabricates outcomes.
    """
    try:
        from scripts import outcome_evidence as oe
    except ModuleNotFoundError:  # pragma: no cover - script-style fallback
        import outcome_evidence as oe  # type: ignore[no-redef]

    prov = oe.provenance_counts(list(outcomes))
    eligible = oe.eligible_outcomes(list(outcomes))
    n = len(eligible)

    base = {
        **prov,
        "n": n,
        "buckets": [],
        "ece": None, "mce": None, "brier": None, "log_loss": None,
        "win_rate": None, "loss_rate": None, "breakeven_rate": None,
        "avg_return": None, "avg_levered_return": None,
        "wilson_lower": None, "wilson_upper": None,
        "posterior_mean": None, "posterior_var": None,
        "should_drive_sizing": False,
        "human_approved": bool(human_approved),
    }

    if n == 0:
        status = FIXTURE_ONLY if prov.get("synthetic_n", 0) > 0 else NO_DATA
        base["calibration_status"] = status
        base["message"] = (
            "Only synthetic fixture outcomes exist — never sizing-grade."
            if status == FIXTURE_ONLY
            else "No eligible outcomes — uncalibrated."
        )
        base.update(_ADVISORY_STAMPS)
        base["human_review_required"] = True
        return base

    # Aligned points: (y, s, realized_return, realized_levered_return).
    pts: list[tuple[float, float, float | None, float | None]] = []
    wins = losses = breakevens = 0
    for o in eligible:
        y = _y_of(o.outcome_label)
        s = _normalize_score(o.score_at_entry)
        if y is None or s is None:
            continue
        pts.append((y, s, o.realized_return, o.realized_levered_return))
        if y == 1.0:
            wins += 1
        elif y == 0.0:
            losses += 1
        else:
            breakevens += 1

    m = len(pts)  # outcomes with both a label and a score
    rs = [p[2] for p in pts if p[2] is not None]
    rls = [p[3] for p in pts if p[3] is not None]

    # Buckets.
    bucket_rows: list[dict[str, Any]] = []
    ece = 0.0
    mce = 0.0
    for lo, hi in buckets:
        members = [p for p in pts if lo <= p[1] < hi]
        nk = len(members)
        if nk == 0:
            bucket_rows.append({
                "lower": lo, "upper": min(hi, 1.0), "n": 0,
                "confidence": None, "accuracy": None,
                "avg_return": None, "avg_levered_return": None,
                "wins": 0, "losses": 0,
            })
            continue
        conf_k = sum(p[1] for p in members) / nk
        acc_k = sum(p[0] for p in members) / nk
        bucket_returns = [p[2] for p in members if p[2] is not None]
        bucket_lret = [p[3] for p in members if p[3] is not None]
        avg_ret_k = sum(bucket_returns) / len(bucket_returns) if bucket_returns else None
        avg_lret_k = sum(bucket_lret) / len(bucket_lret) if bucket_lret else None
        w_k = sum(1 for p in members if p[0] == 1.0)
        l_k = sum(1 for p in members if p[0] == 0.0)
        gap = abs(acc_k - conf_k)
        ece += (nk / m) * gap
        mce = max(mce, gap)
        bucket_rows.append({
            "lower": lo, "upper": min(hi, 1.0), "n": nk,
            "confidence": conf_k, "accuracy": acc_k,
            "avg_return": avg_ret_k, "avg_levered_return": avg_lret_k,
            "wins": w_k, "losses": l_k,
        })

    brier = sum((p[1] - p[0]) ** 2 for p in pts) / m
    log_loss = 0.0
    for y, s, _r, _rl in pts:
        s_c = min(1 - _LOGLOSS_DELTA, max(_LOGLOSS_DELTA, s))
        log_loss += -(y * _math.log(s_c) + (1 - y) * _math.log(1 - s_c))
    log_loss /= m

    wr = wins / m
    lr = losses / m
    br = breakevens / m
    avg_return = (sum(rs) / len(rs)) if rs else None
    avg_lret = (sum(rls) / len(rls)) if rls else None
    wl, wu = _wilson_interval(wins, m)

    alpha = 1.0 + wins + 0.5 * breakevens
    beta = 1.0 + losses + 0.5 * breakevens
    post_mean = alpha / (alpha + beta)
    post_var = (alpha * beta) / ((alpha + beta) ** 2 * (alpha + beta + 1))

    # Status ladder.
    if m < LOW_SAMPLE_MAX + 1:
        status = LOW_SAMPLE
    elif m < CALIBRATED_MIN:
        status = CALIBRATING
    elif ece <= ECE_MAX and brier <= BRIER_MAX:
        status = CALIBRATED
    else:
        status = MIS_CALIBRATED

    should_drive = (
        status == CALIBRATED
        and prov.get("real_n", 0) >= CALIBRATED_MIN
        and bool(human_approved)
    )

    base.update({
        "n": m,
        "calibration_status": status,
        "buckets": bucket_rows,
        "ece": ece, "mce": mce, "brier": brier, "log_loss": log_loss,
        "win_rate": wr, "loss_rate": lr, "breakeven_rate": br,
        "wins": wins, "losses": losses, "breakevens": breakevens,
        "avg_return": avg_return, "avg_levered_return": avg_lret,
        "wilson_lower": wl, "wilson_upper": wu,
        "posterior_mean": post_mean, "posterior_var": post_var,
        "should_drive_sizing": should_drive,
        "message": _metrics_message(status, prov),
    })
    base.update(_ADVISORY_STAMPS)
    base["human_review_required"] = True
    return base


def _metrics_message(status: str, prov: dict[str, int]) -> str:
    real = prov.get("real_n", 0)
    if status == CALIBRATED and real >= CALIBRATED_MIN:
        return "Real-calibrated on >=50 real outcomes; still not a profit guarantee."
    if status == CALIBRATED:
        return "Calibrated on outcomes, but not on >=50 REAL trades — treat as paper-calibrated."
    if status == MIS_CALIBRATED:
        return "Miscalibrated (ECE/Brier above threshold) — human review required."
    return "Insufficient eligible outcomes to calibrate; do not size from scores."


def build_calibration_metrics_report(
    db_path: Path | None = None,
    *,
    source_type: str | None = None,
) -> dict[str, Any]:
    """Extract outcomes from the DB and compute full metrics. Defensive."""
    try:
        try:
            from scripts import outcome_evidence_extractor as ex
            from scripts import outcome_evidence as oe
        except ModuleNotFoundError:  # pragma: no cover - script-style fallback
            import outcome_evidence_extractor as ex  # type: ignore[no-redef]
            import outcome_evidence as oe  # type: ignore[no-redef]
        st = source_type or oe.REAL_MANUAL_TRADE
        outcomes = ex.extract_from_db(db_path, source_type=st)
    except Exception:  # pragma: no cover - defensive
        outcomes = []
    return compute_calibration_metrics(outcomes)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Honest score-calibration summary.")
    p.add_argument("--db-path", type=Path, default=None)
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = build_score_calibration_report(args.db_path)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"calibration_status : {report['calibration_status']}")
        print(f"sample_size        : {report['sample_size']}")
        print(f"win_rate           : {report['win_rate']}")
        print(f"should_drive_sizing: {report['score_should_drive_sizing']}")
        print(report["message"])
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "UNCALIBRATED",
    "LOW_SAMPLE",
    "CALIBRATING",
    "CALIBRATED",
    "classify_calibration_status",
    "compute_score_calibration",
    "score_calibration_envelope",
    "build_score_calibration_report",
]
