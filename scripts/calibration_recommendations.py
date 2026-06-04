"""Guarded calibration recommendations from reconciled outcomes + Moltbook.

This is the *feedback loop*, made safe. It reads historical reconciliation
outcomes (and optional Moltbook feedback cases), buckets them, computes honest
rates, and produces a **recommendation** about whether a score threshold
should move. It NEVER auto-applies anything: ``applied`` is always False and
``human_review_required`` is always True. Applying a recommendation is a
separate, deliberate human action that lives outside this module.

Recommendation ladder:

    no resolved outcomes        -> OBSERVE_MORE_DATA           (shift 0.0)
    1 .. MIN_SAMPLE-1 outcomes  -> LOW_SAMPLE_DO_NOT_ADJUST    (shift 0.0)
    >= MIN_SAMPLE:
        false_positive_rate high -> RECOMMEND_TIGHTEN          (shift +)
        win_rate high            -> RECOMMEND_LOOSEN_SLIGHTLY   (shift -, tiny)
        otherwise                -> RECOMMEND_MAINTAIN          (shift 0.0)

Safety
------
Read-only on inputs; pure compute. No DB writes, no threshold writes, no
broker calls, no AI execution. Advisory invariant stamps on every payload.
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

try:
    from scripts.score_calibration import (
        CALIBRATED,
        CALIBRATING,
        LOW_SAMPLE,
        UNCALIBRATED,
        compute_score_calibration,
    )
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from score_calibration import (  # type: ignore[no-redef]
        CALIBRATED,
        CALIBRATING,
        LOW_SAMPLE,
        UNCALIBRATED,
        compute_score_calibration,
    )

# Recommendation verbs.
OBSERVE_MORE_DATA = "OBSERVE_MORE_DATA"
LOW_SAMPLE_DO_NOT_ADJUST = "LOW_SAMPLE_DO_NOT_ADJUST"
RECOMMEND_TIGHTEN = "RECOMMEND_TIGHTEN"
RECOMMEND_MAINTAIN = "RECOMMEND_MAINTAIN"
RECOMMEND_LOOSEN_SLIGHTLY = "RECOMMEND_LOOSEN_SLIGHTLY"

# Minimum resolved outcomes before we will recommend any threshold move.
MIN_SAMPLE_TO_RECOMMEND = 20
# Outcome-rate triggers.
HIGH_FALSE_POSITIVE_RATE = 0.60   # >= this -> tighten
HIGH_WIN_RATE = 0.70              # >= this -> consider a tiny loosen
# Conservative shift magnitudes (in score-threshold units, 0..1 scale).
TIGHTEN_SHIFT = 0.05
LOOSEN_SHIFT = -0.02

_ADVISORY_STAMPS = {
    "advisory_only": True,
    "advisory_status": "ADVISORY_ONLY",
    "human_execution_required": True,
    "human_review_required": True,
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "ai_execution_count": 0,
}


def _confidence_for(sample_size: int, status: str) -> float:
    """Confidence in the recommendation, 0..1. Grows with sample, capped."""
    if sample_size < MIN_SAMPLE_TO_RECOMMEND:
        return 0.0
    # Linear ramp from MIN_SAMPLE..(MIN_SAMPLE*5), capped at 0.8 — we never
    # claim high confidence from a local single-operator journal.
    span = MIN_SAMPLE_TO_RECOMMEND * 5
    frac = min(1.0, sample_size / span)
    base = 0.3 + 0.5 * frac
    return round(min(0.8, base), 3)


def _recommend(summary: dict[str, Any]) -> dict[str, Any]:
    """Turn a calibration summary into a guarded recommendation."""
    sample = int(summary.get("sample_size", 0) or 0)
    fpr = summary.get("false_positive_rate")
    win = summary.get("win_rate")
    status = str(summary.get("calibration_status", UNCALIBRATED))

    if sample <= 0:
        rec, shift, reason = (
            OBSERVE_MORE_DATA, 0.0,
            "No resolved outcomes yet — collect reconciled trades before adjusting anything.",
        )
    elif sample < MIN_SAMPLE_TO_RECOMMEND:
        rec, shift, reason = (
            LOW_SAMPLE_DO_NOT_ADJUST, 0.0,
            f"Only {sample} resolved outcome(s) (< {MIN_SAMPLE_TO_RECOMMEND}); "
            "too few to justify any threshold change.",
        )
    elif fpr is not None and fpr >= HIGH_FALSE_POSITIVE_RATE:
        rec, shift, reason = (
            RECOMMEND_TIGHTEN, TIGHTEN_SHIFT,
            f"False-positive rate {fpr:.0%} over {sample} outcomes is high; "
            f"recommend RAISING the score threshold by {TIGHTEN_SHIFT:+.2f} "
            "(advisory; not applied).",
        )
    elif win is not None and win >= HIGH_WIN_RATE:
        rec, shift, reason = (
            RECOMMEND_LOOSEN_SLIGHTLY, LOOSEN_SHIFT,
            f"Win rate {win:.0%} over {sample} outcomes is strong; a small "
            f"loosen of {LOOSEN_SHIFT:+.2f} could be considered (advisory; "
            "not applied). Prefer maintaining if unsure.",
        )
    else:
        rec, shift, reason = (
            RECOMMEND_MAINTAIN, 0.0,
            f"Mixed outcomes over {sample} samples; maintain the current "
            "threshold and keep collecting evidence.",
        )

    return {
        "recommendation": rec,
        "recommended_threshold_shift": shift,
        "confidence": _confidence_for(sample, status),
        "sample_size": sample,
        "win_rate": win,
        "loss_rate": fpr,  # loss fraction == false-positive fraction here
        "false_positive_rate": fpr,
        "avg_pnl": summary.get("average_realized_return"),
        "calibration_status": status,
        "reason": reason,
        # Hard safety: this module recommends only. It never writes thresholds.
        "applied": False,
    }


def build_recommendation(
    reconciliations: Iterable[dict[str, Any]],
    *,
    bucket_key: str | None = None,
) -> dict[str, Any]:
    """Build an overall recommendation, plus per-bucket ones if ``bucket_key``
    is given and present on the rows (e.g. "signal_state" / "archetype").
    """
    rows = list(reconciliations)
    overall = _recommend(compute_score_calibration(rows))

    buckets: dict[str, Any] = {}
    if bucket_key:
        groups: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            key = str(r.get(bucket_key, "") or "UNLABELLED")
            groups.setdefault(key, []).append(r)
        for key, group_rows in sorted(groups.items()):
            buckets[key] = _recommend(compute_score_calibration(group_rows))

    payload = {
        "report": "calibration_recommendations",
        "overall": overall,
        "buckets": buckets,
        "bucket_key": bucket_key,
        "auto_apply": False,  # this module NEVER auto-applies
        "note": (
            "Advisory feedback loop. Recommendations are never auto-applied; "
            "a human must review and act. No execution or sizing command is "
            "produced here."
        ),
    }
    payload.update(_ADVISORY_STAMPS)
    return payload


def build_recommendation_report(db_path: Path | None = None) -> dict[str, Any]:
    """Read reconciliations from the local DB and build the report.

    Read-only and defensive: any DB problem degrades to OBSERVE_MORE_DATA.
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
    return build_recommendation(rows)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Guarded calibration recommendations.")
    p.add_argument("--db-path", type=Path, default=None)
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = build_recommendation_report(args.db_path)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        o = report["overall"]
        print(f"recommendation : {o['recommendation']}")
        print(f"threshold_shift: {o['recommended_threshold_shift']:+.2f}")
        print(f"sample_size    : {o['sample_size']}")
        print(f"applied        : {o['applied']}")
        print(o["reason"])
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "OBSERVE_MORE_DATA",
    "LOW_SAMPLE_DO_NOT_ADJUST",
    "RECOMMEND_TIGHTEN",
    "RECOMMEND_MAINTAIN",
    "RECOMMEND_LOOSEN_SLIGHTLY",
    "MIN_SAMPLE_TO_RECOMMEND",
    "build_recommendation",
    "build_recommendation_report",
]
