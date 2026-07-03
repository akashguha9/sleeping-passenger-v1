"""NBI calibration report — Brier / log-loss / ECE over closed backtest cases.

Builds the calibration path WITHOUT fitting fake weights.  The report:

* runs with zero cases (status INSUFFICIENT_EVIDENCE_FOR_CALIBRATION);
* counts fixture cases but EXCLUDES them from every metric;
* computes Brier, log loss, and expected calibration error (ECE) on the
  core-branch probability recorded at rumor peak vs the resolved outcome;
* refuses to emit fitted weights below the case threshold — the current
  heuristic CLASS_LLR weights are echoed verbatim as ``heuristic_weights``
  so what the engine actually uses is always documented, never implied
  to be calibrated.

    Brier   = mean((p_i - y_i)^2)
    LogLoss = -mean(y ln(p+eps) + (1-y) ln(1-p+eps))
    ECE     = sum_m |B_m|/N * |acc(B_m) - conf(B_m)|     (M=5 fixed bins)

Outcome mapping (core branch): CORE_HELD_INTACT / CORE_HELD_SUB_BRANCH_
COLLAPSED / RUMOR_FALSE -> y=1;  CORE_DIED / RUMOR_TRUE -> y=0;
UNRESOLVED -> excluded (not a closed case).

Advisory-only.  Read-only over the store; no execution, no weight mutation.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from scripts.advisory_contract import advisory_safety_stamps
from scripts.narrative_branch_engine import CLASS_LLR
from scripts.nbi_store import (
    CASE_KIND_TEMPLATE,
    REAL_CASE_MIN_CALIBRATION,
    REAL_CASE_MIN_DESCRIPTIVE,
    load_nbi_backtest_cases,
)
from scripts.nbi_track_record_ledger import compute_case_quality

CALIBRATION_REPORT_VERSION = "nbi-calibration-v1.1"
STATUS_INSUFFICIENT = "INSUFFICIENT_EVIDENCE_FOR_CALIBRATION"
STATUS_ACCUMULATION = "CASE_ACCUMULATION"
STATUS_DESCRIPTIVE = "DESCRIPTIVE_ONLY"
STATUS_POSSIBLE = "CALIBRATION_POSSIBLE"

_EPS = 1e-9
_ECE_BINS = 5

_OUTCOME_TO_Y: dict[str, int] = {
    "CORE_HELD_INTACT": 1,
    "CORE_HELD_SUB_BRANCH_COLLAPSED": 1,
    "RUMOR_FALSE": 1,
    "CORE_DIED": 0,
    "RUMOR_TRUE": 0,
}


def _closed_pairs(cases: list[dict[str, Any]]) -> list[tuple[float, int, str]]:
    """(p_core_at_rumor_peak, y, case_id) for resolvable non-fixture cases."""
    pairs: list[tuple[float, int, str]] = []
    for case in cases:
        if case.get("is_fixture"):
            continue
        if not case.get("resolution_timestamp"):
            continue
        labels = case.get("resolution_labels") or {}
        outcome = str(labels.get("outcome_label") or case.get("outcome_label") or "")
        y = _OUTCOME_TO_Y.get(outcome)
        if y is None:
            continue
        probs = case.get("branch_probabilities") or {}
        p = probs.get("core_event")
        if p is None:
            continue
        pairs.append((max(0.0, min(1.0, float(p))), y, str(case.get("case_id"))))
    return pairs


def brier_score(pairs: list[tuple[float, int, str]]) -> float:
    return sum((p - y) ** 2 for p, y, _ in pairs) / len(pairs)


def log_loss(pairs: list[tuple[float, int, str]]) -> float:
    total = 0.0
    for p, y, _ in pairs:
        total += y * math.log(p + _EPS) + (1 - y) * math.log(1 - p + _EPS)
    return -total / len(pairs)


def expected_calibration_error(
    pairs: list[tuple[float, int, str]], bins: int = _ECE_BINS,
) -> float:
    n = len(pairs)
    ece = 0.0
    for m in range(bins):
        lo, hi = m / bins, (m + 1) / bins
        bucket = [
            (p, y) for p, y, _ in pairs
            if (lo <= p < hi) or (m == bins - 1 and p == hi)
        ]
        if not bucket:
            continue
        acc = sum(y for _, y in bucket) / len(bucket)
        conf = sum(p for p, _ in bucket) / len(bucket)
        ece += (len(bucket) / n) * abs(acc - conf)
    return ece


def build_nbi_calibration_report(
    cases: list[dict[str, Any]] | None = None,
    *,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """The calibration report.  Metrics only when honestly computable."""
    if cases is None:
        cases = load_nbi_backtest_cases(db_path, include_fixtures=True)
    fixtures = [c for c in cases if c.get("is_fixture")]
    templates = [c for c in cases if c.get("case_kind") == CASE_KIND_TEMPLATE]
    quality = [
        (c, compute_case_quality(c)) for c in cases
        if not c.get("is_fixture")
    ]
    eligible = [c for c, q in quality if q["calibration_eligible"]]
    avg_eqs = (
        round(sum(q["EQS10"] for _, q in quality) / len(quality), 4)
        if quality else None
    )
    pairs = _closed_pairs(cases)
    n = len(pairs)

    if n >= REAL_CASE_MIN_CALIBRATION:
        status = STATUS_POSSIBLE
    elif n >= REAL_CASE_MIN_DESCRIPTIVE:
        status = STATUS_DESCRIPTIVE
    elif n >= 1:
        # v1.4 band: cases are accumulating but metrics stay withheld —
        # single-digit corpora produce noise, not calibration.
        status = STATUS_ACCUMULATION
    else:
        status = STATUS_INSUFFICIENT

    metrics: dict[str, Any] = {"brier": None, "log_loss": None, "ece": None}
    baseline_brier = None
    if n > 0 and status not in (STATUS_INSUFFICIENT, STATUS_ACCUMULATION):
        metrics = {
            "brier": round(brier_score(pairs), 6),
            "log_loss": round(log_loss(pairs), 6),
            "ece": round(expected_calibration_error(pairs), 6),
        }
        # Baseline: climatology — always predicting the outcome base rate.
        base_rate = sum(y for _, y, _ in pairs) / n
        baseline_brier = round(
            sum((base_rate - y) ** 2 for _, y, _ in pairs) / n, 6
        )

    next_actions: list[str] = []
    if n < REAL_CASE_MIN_CALIBRATION:
        next_actions.append(
            f"close {REAL_CASE_MIN_CALIBRATION - n} more REAL events with "
            "outcome labels"
        )
    if templates:
        next_actions.append(
            f"{len(templates)} template case(s) await real outcome + price "
            "evidence before they can count"
        )
    if quality and eligible != [c for c, _ in quality]:
        next_actions.append(
            "raise evidence quality (EQS10 >= 7 needed: citations, price "
            "outcomes, branch labels, operator decisions)"
        )

    return {
        "report": "nbi_calibration_report",
        "version": CALIBRATION_REPORT_VERSION,
        "status": status,
        "n_closed_real_cases": n,
        "n_fixture_cases_excluded": len(fixtures),
        "n_template_cases_excluded": len(templates),
        "n_calibration_eligible": len(eligible),
        "avg_evidence_quality_eqs10": avg_eqs,
        "baseline_brier": baseline_brier,
        "next_required_actions": next_actions,
        "thresholds": {
            "descriptive_min": REAL_CASE_MIN_DESCRIPTIVE,
            "calibration_min": REAL_CASE_MIN_CALIBRATION,
        },
        "metrics": metrics,
        # What the engine ACTUALLY runs on today — documented, not implied
        # calibrated.  fitted_weights stays None until the threshold is met
        # AND a human review signs off; this module never mutates weights.
        "heuristic_weights_in_use": dict(CLASS_LLR),
        "fitted_weights": None,
        "fitted_weights_blocked_reason": (
            None if status == STATUS_POSSIBLE
            else f"{status}: n_closed_real_cases={n}"
        ),
        "case_ids_used": [cid for _, _, cid in pairs],
        "safety": advisory_safety_stamps(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="NBI calibration report (Brier/logloss/ECE; honest gating)."
    )
    parser.add_argument("--db", default=None, help="DB path (default canonical)")
    args = parser.parse_args(argv)
    print(json.dumps(build_nbi_calibration_report(db_path=args.db), indent=2))
    return 0


__all__ = [
    "CALIBRATION_REPORT_VERSION",
    "STATUS_INSUFFICIENT", "STATUS_ACCUMULATION", "STATUS_DESCRIPTIVE",
    "STATUS_POSSIBLE",
    "brier_score", "log_loss", "expected_calibration_error",
    "build_nbi_calibration_report", "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
