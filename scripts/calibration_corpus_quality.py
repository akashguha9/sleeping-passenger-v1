"""Calibration corpus quality — make the outcome corpus auditable, not counted.

KANTE_CALIBRATION_CORPUS_QUALITY
================================

Kanté Ceiling Push II, Workstream B.  Counting closed outcomes is not enough:
an operator needs to know *how good* the corpus is — how many rows are valid,
how many are linked to an external-evidence snapshot, how many actually landed
in a calibration bucket, and how much review / rejection burden is hiding in
the pile.  This module turns the raw counts into a single auditable quality
score + an honest label + the single most useful next action.

Hard safety contract
--------------------
* :func:`build_corpus_quality` is pure — no I/O.
* ``real_money_sizing_impact`` is always ``PROHIBITED``.  Even a
  ``STRONG_PAPER_ONLY`` corpus does NOT enable real-money sizing — paper
  calibration quality is a *data* verdict, never a sizing verdict.
* No execution-instruction wording is ever emitted.

Maths (per the sprint spec)
---------------------------
    validity_rate        = N_valid    / max(N_closed, 1)
    linkage_rate         = N_linked   / max(N_closed, 1)
    bucket_coverage_rate = N_bucketed / max(N_linked, 1)
    review_burden_rate   = N_review   / max(N_closed, 1)
    rejection_rate       = N_rejected / max(N_closed, 1)

    corpus_quality_score =
      clip(
          0.30 * validity_rate
        + 0.25 * linkage_rate
        + 0.20 * bucket_coverage_rate
        + 0.15 * (1 - review_burden_rate)
        + 0.10 * (1 - rejection_rate),
        0, 1)

    EMPTY             if N_closed == 0
    WEAK              if score < 0.40
    DEVELOPING        if 0.40 <= score < 0.70
    USABLE_PAPER_ONLY if 0.70 <= score < 0.90
    STRONG_PAPER_ONLY if score >= 0.90 and N_closed >= 100
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

STRONG_MIN_CLOSED = 100

LABEL_EMPTY = "EMPTY"
LABEL_WEAK = "WEAK"
LABEL_DEVELOPING = "DEVELOPING"
LABEL_USABLE_PAPER_ONLY = "USABLE_PAPER_ONLY"
LABEL_STRONG_PAPER_ONLY = "STRONG_PAPER_ONLY"

REAL_MONEY_SIZING_IMPACT = "PROHIBITED"
_PROOF = "CALIBRATION_CORPUS_QUALITY_PAPER_ONLY"


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _int(value: Any, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _label(score: float, n_closed: int) -> str:
    if n_closed <= 0:
        return LABEL_EMPTY
    if score >= 0.90 and n_closed >= STRONG_MIN_CLOSED:
        return LABEL_STRONG_PAPER_ONLY
    if score >= 0.90:
        # high quality but not enough volume — honest USABLE, not STRONG.
        return LABEL_USABLE_PAPER_ONLY
    if score >= 0.70:
        return LABEL_USABLE_PAPER_ONLY
    if score >= 0.40:
        return LABEL_DEVELOPING
    return LABEL_WEAK


def _top_blocker(
    *,
    n_closed: int,
    validity_rate: float,
    linkage_rate: float,
    bucket_coverage_rate: float,
    review_burden_rate: float,
    rejection_rate: float,
) -> str:
    if n_closed <= 0:
        return "no_closed_paper_outcomes"
    if n_closed < STRONG_MIN_CLOSED:
        # volume is the structural ceiling until 100 outcomes exist.
        candidates = {
            "low_linkage_rate": 1.0 - linkage_rate,
            "low_bucket_coverage": 1.0 - bucket_coverage_rate,
            "high_review_burden": review_burden_rate,
            "high_rejection_rate": rejection_rate,
            "low_validity_rate": 1.0 - validity_rate,
        }
        worst = max(candidates.items(), key=lambda kv: kv[1])
        if worst[1] <= 0.0:
            return "insufficient_outcome_volume"
        return worst[0]
    candidates = {
        "low_validity_rate": 1.0 - validity_rate,
        "low_linkage_rate": 1.0 - linkage_rate,
        "low_bucket_coverage": 1.0 - bucket_coverage_rate,
        "high_review_burden": review_burden_rate,
        "high_rejection_rate": rejection_rate,
    }
    worst = max(candidates.items(), key=lambda kv: kv[1])
    return worst[0] if worst[1] > 0.0 else "corpus_balanced"


def _operator_next_action(label: str, n_closed: int, top_blocker: str) -> str:
    if label == LABEL_EMPTY:
        return (
            "Collect closed paper outcomes via scripts/paper_outcome_intake.py "
            "(0 so far; target 50-100)."
        )
    if n_closed < STRONG_MIN_CLOSED:
        return (
            f"Continue accumulating closed paper outcomes ({n_closed}/100). "
            f"Top blocker: {top_blocker}."
        )
    if top_blocker == "low_linkage_rate":
        return "Backfill external-evidence snapshot links for closed outcomes."
    if top_blocker == "low_bucket_coverage":
        return "Refresh calibration buckets so linked outcomes are bucketed."
    if top_blocker in ("high_review_burden", "low_validity_rate"):
        return "Clear the operator-review queue via paper_outcome_intake validation."
    if top_blocker == "high_rejection_rate":
        return "Investigate rejected rows; fix proof/price-math before re-intake."
    return "Maintain corpus quality; keep linking + bucketing new outcomes."


def build_corpus_quality(
    *,
    n_closed: int,
    n_valid: int = 0,
    n_review: int = 0,
    n_rejected: int = 0,
    n_linked: int = 0,
    n_bucketed: int = 0,
    missing_fields_summary: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Compute the corpus quality report (pure).  Never raises."""
    n_closed = _int(n_closed)
    n_valid = _int(n_valid)
    n_review = _int(n_review)
    n_rejected = _int(n_rejected)
    n_linked = _int(n_linked)
    n_bucketed = _int(n_bucketed)
    n_unlinked = max(0, n_closed - n_linked)

    validity_rate = n_valid / float(max(n_closed, 1))
    linkage_rate = n_linked / float(max(n_closed, 1))
    bucket_coverage_rate = n_bucketed / float(max(n_linked, 1))
    review_burden_rate = n_review / float(max(n_closed, 1))
    rejection_rate = n_rejected / float(max(n_closed, 1))

    corpus_quality_score = _clip(
        0.30 * validity_rate
        + 0.25 * linkage_rate
        + 0.20 * bucket_coverage_rate
        + 0.15 * (1.0 - review_burden_rate)
        + 0.10 * (1.0 - rejection_rate),
        0.0,
        1.0,
    )

    label = _label(corpus_quality_score, n_closed)
    top_blocker = _top_blocker(
        n_closed=n_closed,
        validity_rate=validity_rate,
        linkage_rate=linkage_rate,
        bucket_coverage_rate=bucket_coverage_rate,
        review_burden_rate=review_burden_rate,
        rejection_rate=rejection_rate,
    )
    next_action = _operator_next_action(label, n_closed, top_blocker)

    out: dict[str, Any] = {
        "report": "calibration_corpus_quality",
        "n_closed": n_closed,
        "n_valid": n_valid,
        "n_review": n_review,
        "n_rejected": n_rejected,
        "n_linked": n_linked,
        "n_unlinked": n_unlinked,
        "n_bucketed": n_bucketed,
        "validity_rate": round(validity_rate, 6),
        "linkage_rate": round(linkage_rate, 6),
        "bucket_coverage_rate": round(bucket_coverage_rate, 6),
        "review_burden_rate": round(review_burden_rate, 6),
        "rejection_rate": round(rejection_rate, 6),
        "corpus_quality_score": round(corpus_quality_score, 6),
        "corpus_label": label,
        "top_blocker": top_blocker,
        "operator_next_action": next_action,
        "missing_fields_summary": dict(missing_fields_summary or {}),
        "target_minimum": 50,
        "target_preferred": STRONG_MIN_CLOSED,
        "real_money_sizing_impact": REAL_MONEY_SIZING_IMPACT,
        "real_money_weight_allowed": False,
        "proof_status": _PROOF,
    }
    out.update(_contract.advisory_safety_stamps())
    out["advisory_only"] = True
    out["human_execution_required"] = True
    out["operator_execution_required"] = True
    out["real_money_sizing_impact"] = REAL_MONEY_SIZING_IMPACT
    out["real_money_weight_allowed"] = False
    out["proof_status"] = _PROOF
    return out


# ---------------------------------------------------------------------------
# Read-only loader — reuses the existing paper-outcome readiness loader so the
# two reports agree on the closed/linked/bucket counts.  Never mutates.
# ---------------------------------------------------------------------------


def build_from_db(db_path: Path | None = None) -> dict[str, Any]:
    """Load read-only counts and build the corpus quality report.

    Without an outcome corpus this honestly reports the EMPTY label — it never
    invents validity / linkage to look better than the data supports.
    """
    try:
        try:
            from scripts.paper_outcome_collection_readiness import (
                load_paper_outcome_inputs,
            )
        except ModuleNotFoundError:  # pragma: no cover
            from paper_outcome_collection_readiness import (  # type: ignore
                load_paper_outcome_inputs,
            )
        inputs = load_paper_outcome_inputs(db_path)
        n_closed = _int(inputs.get("closed_paper_outcomes_count"))
        n_linked = _int(inputs.get("linked_external_evidence_outcomes_count"))
        buckets = inputs.get("buckets") or []
        n_bucketed = sum(_int(b.get("sample_count")) for b in buckets)
    except Exception:  # noqa: BLE001 - missing DB degrades to EMPTY, honestly
        n_closed = n_linked = n_bucketed = 0
    # Without an intake validation pass over the canonical store we conserve:
    # treat every closed outcome as not-yet-validated (n_valid unknown -> 0).
    return build_corpus_quality(
        n_closed=n_closed,
        n_linked=min(n_linked, n_closed),
        n_bucketed=min(n_bucketed, n_linked),
    )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="calibration_corpus_quality.py",
        description=(
            "Report calibration-corpus quality (validity / linkage / bucket "
            "coverage / review + rejection burden). Read-only; advisory-only; "
            "real-money sizing PROHIBITED."
        ),
    )
    p.add_argument("--json", action="store_true", help="print the JSON report")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = build_from_db()
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("calibration_corpus_quality")
        print(f"  corpus_label    : {report['corpus_label']}")
        print(f"  n_closed        : {report['n_closed']}")
        print(f"  quality score   : {report['corpus_quality_score']}")
        print(f"  top blocker     : {report['top_blocker']}")
        print(f"  real-money      : {report['real_money_sizing_impact']}")
        print(f"  next action     : {report['operator_next_action']}")
    return 0


__all__ = [
    "STRONG_MIN_CLOSED",
    "LABEL_EMPTY",
    "LABEL_WEAK",
    "LABEL_DEVELOPING",
    "LABEL_USABLE_PAPER_ONLY",
    "LABEL_STRONG_PAPER_ONLY",
    "build_corpus_quality",
    "build_from_db",
    "main",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
