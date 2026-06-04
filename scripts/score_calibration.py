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
