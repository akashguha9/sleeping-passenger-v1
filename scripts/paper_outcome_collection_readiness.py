"""Paper-outcome collection readiness — how close calibration is to usable.

KANTE_PAPER_OUTCOME_COLLECTION_READINESS
========================================

Calibration buckets stay cold-start until there are enough *closed paper
outcomes* behind them.  This module is the operator-facing "how far are we
from a statistically usable calibration?" report — the Kanté tracking-back
work that turns invisible accumulation into a visible target.

It does NOT invent outcomes.  It counts what genuinely exists (closed manual /
paper trades with entry+exit, linked external-evidence outcome rows, and the
calibration buckets) and reports an honest readiness label + score.

Hard safety contract
--------------------
* Pure maths in :func:`build_paper_outcome_collection_readiness` — no I/O.
* The loader is strictly read-only (SELECT / count only).
* ``real_money_sizing_impact`` is always ``PROHIBITED``.  Paper-calibration
  readiness is NOT real-money readiness — the two are deliberately distinct.
* No execution-instruction wording is ever emitted.
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

TARGET_MINIMUM = 50
TARGET_PREFERRED = 100

LABEL_COLD_START = "COLD_START"
LABEL_EARLY_SAMPLE = "EARLY_SAMPLE"
LABEL_PROVISIONAL = "PROVISIONAL"
LABEL_PAPER_CALIBRATED = "PAPER_CALIBRATED"

REAL_MONEY_SIZING_IMPACT = "PROHIBITED"
_PROOF = "PAPER_OUTCOME_COLLECTION_READINESS_PAPER_ONLY"

# Bucket maturity bands (by sample_count).
_MATURE_MIN = 50
_PROVISIONAL_MIN = 30
_EARLY_MIN = 5


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _sample_count(bucket: dict[str, Any]) -> int:
    return _int(bucket.get("sample_count"))


def _readiness_label(closed: int) -> str:
    if closed < 30:
        return LABEL_COLD_START
    if closed < TARGET_MINIMUM:
        return LABEL_EARLY_SAMPLE
    if closed < TARGET_PREFERRED:
        return LABEL_PROVISIONAL
    return LABEL_PAPER_CALIBRATED


def _next_required_action(label: str, closed: int, linked: int, mature: int) -> str:
    if label == LABEL_COLD_START:
        return (
            f"Log closed paper outcomes: {closed}/30 to leave cold-start "
            f"(target {TARGET_MINIMUM}-{TARGET_PREFERRED})."
        )
    if linked < closed:
        return (
            "Backfill external-evidence outcome links for closed trades "
            f"({linked}/{closed} linked) so buckets can mature."
        )
    if label == LABEL_EARLY_SAMPLE:
        return f"Continue toward the {TARGET_MINIMUM}-outcome minimum (now {closed})."
    if label == LABEL_PROVISIONAL:
        return (
            f"Continue toward {TARGET_PREFERRED} closed paper outcomes for "
            f"paper-calibration (now {closed})."
        )
    if mature == 0:
        return "Refresh calibration buckets so sample_count>=50 buckets appear."
    return "Maintain sample; refresh calibration buckets from new closed outcomes."


def build_paper_outcome_collection_readiness(
    *,
    closed_paper_outcomes_count: int,
    linked_external_evidence_outcomes_count: int = 0,
    buckets: list[dict[str, Any]] | None = None,
    valid_proof_rows: int | None = None,
) -> dict[str, Any]:
    """Compute the paper-outcome collection readiness report (pure).

    ``buckets`` is a list of calibration-bucket dicts each carrying a
    ``sample_count``.  ``valid_proof_rows`` defaults to
    ``closed_paper_outcomes_count`` (assume each closed outcome has a valid
    proof unless told otherwise).  Never raises.
    """
    closed = max(0, _int(closed_paper_outcomes_count))
    linked = max(0, _int(linked_external_evidence_outcomes_count))
    buckets = list(buckets or [])
    bucket_count = len(buckets)

    cold = sum(1 for b in buckets if _sample_count(b) < _EARLY_MIN)
    early = sum(1 for b in buckets if _EARLY_MIN <= _sample_count(b) < _PROVISIONAL_MIN)
    provisional = sum(
        1 for b in buckets if _PROVISIONAL_MIN <= _sample_count(b) < _MATURE_MIN
    )
    mature = sum(1 for b in buckets if _sample_count(b) >= _MATURE_MIN)

    valid_proof = closed if valid_proof_rows is None else max(0, _int(valid_proof_rows))

    paper_outcome_progress = closed / float(TARGET_PREFERRED)
    linked_evidence_progress = linked / float(max(closed, 1))
    mature_bucket_ratio = mature / float(max(bucket_count, 1))
    proof_quality_score = valid_proof / float(max(closed, 1))

    calibration_readiness_score = _clip(
        0.40 * min(paper_outcome_progress, 1.0)
        + 0.30 * min(linked_evidence_progress, 1.0)
        + 0.20 * mature_bucket_ratio
        + 0.10 * proof_quality_score,
        0.0,
        1.0,
    )

    label = _readiness_label(closed)

    out: dict[str, Any] = {
        "report": "paper_outcome_collection_readiness",
        "closed_paper_outcomes_count": closed,
        "target_minimum": TARGET_MINIMUM,
        "target_preferred": TARGET_PREFERRED,
        "linked_external_evidence_outcomes_count": linked,
        "bucket_count": bucket_count,
        "cold_bucket_count": cold,
        "early_bucket_count": early,
        "provisional_bucket_count": provisional,
        "mature_bucket_count": mature,
        "paper_outcome_progress": round(paper_outcome_progress, 6),
        "linked_evidence_progress": round(linked_evidence_progress, 6),
        "mature_bucket_ratio": round(mature_bucket_ratio, 6),
        "proof_quality_score": round(proof_quality_score, 6),
        "calibration_readiness_score": round(calibration_readiness_score, 6),
        "readiness_label": label,
        "real_money_sizing_impact": REAL_MONEY_SIZING_IMPACT,
        "next_required_action": _next_required_action(label, closed, linked, mature),
    }
    out.update(_contract.advisory_safety_stamps())
    out["advisory_only"] = True
    out["human_execution_required"] = True
    out["real_money_sizing_impact"] = REAL_MONEY_SIZING_IMPACT
    out["real_money_weight_allowed"] = False
    out["proof_status"] = _PROOF
    return out


# ---------------------------------------------------------------------------
# Read-only loader — counts what genuinely exists.  Never mutates trade or
# execution state (the calibration tables are advisory-only).
# ---------------------------------------------------------------------------


def load_paper_outcome_inputs(db_path: Path | None = None) -> dict[str, Any]:
    """Read closed-outcome / linked-evidence / bucket counts (read-only)."""
    closed = 0
    linked = 0
    buckets: list[dict[str, Any]] = []
    try:
        try:
            from scripts import external_evidence_calibration_backfill as _backfill
        except ModuleNotFoundError:  # pragma: no cover
            import external_evidence_calibration_backfill as _backfill  # type: ignore
        closed = len(_backfill._build_closed_trade_outcomes(db_path))
    except Exception:  # noqa: BLE001 - missing DB degrades to zero, honestly
        closed = 0
    try:
        try:
            from scripts import external_evidence_persistence as _eep
        except ModuleNotFoundError:  # pragma: no cover
            import external_evidence_persistence as _eep  # type: ignore
        conn = _eep._open(db_path)
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM external_evidence_outcomes"
            ).fetchone()
            linked = _int(row[0] if row else 0)
            cur = conn.execute(
                "SELECT sample_count FROM external_evidence_calibration_buckets"
            )
            buckets = [{"sample_count": _int(r[0])} for r in cur.fetchall()]
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        linked, buckets = 0, []
    return {
        "closed_paper_outcomes_count": closed,
        "linked_external_evidence_outcomes_count": linked,
        "buckets": buckets,
    }


def build_from_db(db_path: Path | None = None) -> dict[str, Any]:
    """Convenience: load read-only inputs then build the readiness report."""
    inputs = load_paper_outcome_inputs(db_path)
    return build_paper_outcome_collection_readiness(
        closed_paper_outcomes_count=inputs["closed_paper_outcomes_count"],
        linked_external_evidence_outcomes_count=inputs[
            "linked_external_evidence_outcomes_count"
        ],
        buckets=inputs["buckets"],
    )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="paper_outcome_collection_readiness.py",
        description=(
            "Report how close paper-outcome collection is to a usable "
            "calibration. Read-only; advisory-only; real-money sizing PROHIBITED."
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
        print("paper_outcome_collection_readiness")
        print(f"  readiness_label : {report['readiness_label']}")
        print(
            f"  closed outcomes : {report['closed_paper_outcomes_count']} "
            f"(min {report['target_minimum']} / pref {report['target_preferred']})"
        )
        print(f"  linked evidence : {report['linked_external_evidence_outcomes_count']}")
        print(
            f"  buckets         : {report['bucket_count']} "
            f"(cold={report['cold_bucket_count']} early={report['early_bucket_count']} "
            f"prov={report['provisional_bucket_count']} mature={report['mature_bucket_count']})"
        )
        print(f"  readiness score : {report['calibration_readiness_score']}")
        print(f"  real-money      : {report['real_money_sizing_impact']}")
        print(f"  next action     : {report['next_required_action']}")
    return 0


__all__ = [
    "TARGET_MINIMUM",
    "TARGET_PREFERRED",
    "LABEL_COLD_START",
    "LABEL_EARLY_SAMPLE",
    "LABEL_PROVISIONAL",
    "LABEL_PAPER_CALIBRATED",
    "build_paper_outcome_collection_readiness",
    "load_paper_outcome_inputs",
    "build_from_db",
    "main",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
