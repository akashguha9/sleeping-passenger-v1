"""Per-model reliability ledger + confidence calibration (AI Integration — Task 6).

The normalizer (:mod:`scripts.model_signal_normalizer`) collapses raw multi-model
reports into canonical advisory rows.  This module answers the *next* question:
**how much should we trust a given model's stated confidence?**  It scores each
model from its own outcome history and recalibrates a claimed confidence down by
that reliability and the cross-model source-independence — so an overconfident
model whose calls don't pan out cannot inflate the advisory picture.

Reliability formula (per model m)::

    ModelReliability_m =
        0.35 * DirectionalHitRate_m
      + 0.25 * InvalidationQuality_m
      + 0.20 * SourceDiversity_m
      + 0.10 * CalibrationQuality_m
      + 0.10 * MoltbookLessonConversion_m

    CalibrationError       = abs(ClaimedConfidence - RealizedOutcomeScore)
    CalibrationQuality_m   = 1 - mean(CalibrationError)
    ConfidenceCalibrated   = ClaimedConfidence * ModelReliability_m * SourceIndependenceScore

No-history is handled with a neutral prior of 0.5 per component (a model we have
never observed is neither trusted nor distrusted) and ``sample_size = 0`` so the
caller can see the score is a prior, not earned.

Pure module: no DB, no network, no broker calls, no execution, no AI execution.
Reliability is advisory-only and never authorises an action.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

try:
    from scripts.ai_output_schema import normalize_confidence_score
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from ai_output_schema import normalize_confidence_score  # type: ignore[no-redef]

# Reliability component weights (sum to 1.0).
W_DIRECTIONAL = 0.35
W_INVALIDATION = 0.25
W_SOURCE_DIVERSITY = 0.20
W_CALIBRATION = 0.10
W_MOLTBOOK = 0.10

NEUTRAL_PRIOR = 0.5
# A report citing this many distinct sources counts as fully diverse.
SOURCE_DIVERSITY_TARGET = 2


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _as_float(value: Any, default: float | None = None) -> float | None:
    conf, _warn = normalize_confidence_score(value)
    if conf is not None:
        return conf
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _distinct_source_count(record: dict[str, Any]) -> int:
    refs = record.get("source_refs") or record.get("sources") or []
    if isinstance(refs, str):
        refs = [refs]
    return len({str(r).strip().lower() for r in refs if str(r).strip()})


def calibration_error(claimed: float | None, realized: float | None) -> float | None:
    """abs(claimed - realized); ``None`` if either is missing."""
    if claimed is None or realized is None:
        return None
    return abs(_clamp01(float(claimed)) - _clamp01(float(realized)))


def calibrate_confidence(
    claimed: float | None,
    reliability: float,
    source_independence: float = 1.0,
) -> float:
    """ConfidenceCalibrated = claimed * reliability * source_independence.

    Penalises overconfidence: a high claimed confidence from a low-reliability
    model (or one resting on echoed sources) is scaled sharply down.  Missing
    claimed confidence calibrates to 0.0 (no earned confidence).
    """
    if claimed is None:
        return 0.0
    return round(
        _clamp01(float(claimed)) * _clamp01(reliability) * _clamp01(source_independence),
        4,
    )


def _score_model(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Score one model from its outcome records (neutral prior if empty)."""
    n = len(records)
    if n == 0:
        reliability = (
            W_DIRECTIONAL + W_INVALIDATION + W_SOURCE_DIVERSITY
            + W_CALIBRATION + W_MOLTBOOK
        ) * NEUTRAL_PRIOR
        return {
            "sample_size": 0,
            "is_prior": True,
            "directional_hit_rate": NEUTRAL_PRIOR,
            "invalidation_quality": NEUTRAL_PRIOR,
            "source_diversity": NEUTRAL_PRIOR,
            "calibration_quality": NEUTRAL_PRIOR,
            "moltbook_lesson_conversion": NEUTRAL_PRIOR,
            "reliability": round(reliability, 4),
        }

    directional = sum(1 for r in records if r.get("directional_correct")) / n
    invalidation = sum(1 for r in records if r.get("had_invalidation")) / n
    diversity = sum(
        min(1.0, _distinct_source_count(r) / SOURCE_DIVERSITY_TARGET) for r in records
    ) / n
    moltbook = sum(1 for r in records if r.get("converted_to_moltbook_lesson")) / n

    # Calibration quality from records that carry both claimed + realized.
    errors = [
        e for e in (
            calibration_error(_as_float(r.get("claimed_confidence")),
                              _as_float(r.get("realized_outcome_score")))
            for r in records
        ) if e is not None
    ]
    calibration_quality = (1.0 - (sum(errors) / len(errors))) if errors else NEUTRAL_PRIOR

    reliability = (
        W_DIRECTIONAL * directional
        + W_INVALIDATION * invalidation
        + W_SOURCE_DIVERSITY * diversity
        + W_CALIBRATION * _clamp01(calibration_quality)
        + W_MOLTBOOK * moltbook
    )
    return {
        "sample_size": n,
        "is_prior": False,
        "directional_hit_rate": round(directional, 4),
        "invalidation_quality": round(invalidation, 4),
        "source_diversity": round(diversity, 4),
        "calibration_quality": round(_clamp01(calibration_quality), 4),
        "moltbook_lesson_conversion": round(moltbook, 4),
        "reliability": round(_clamp01(reliability), 4),
    }


def build_ledger(records: Any) -> dict[str, Any]:
    """Build the per-model reliability ledger from a flat list of outcome records.

    Each record is a dict keyed by ``model_name`` plus any of: ``directional_correct``
    (bool), ``had_invalidation`` (bool), ``source_refs`` (list), ``claimed_confidence``,
    ``realized_outcome_score`` (0..1), ``converted_to_moltbook_lesson`` (bool).
    Never raises; unusable records are skipped.
    """
    by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    skipped = 0
    rows = records if isinstance(records, list) else [records]
    for rec in rows:
        if not isinstance(rec, dict):
            skipped += 1
            continue
        model = str(rec.get("model_name") or rec.get("model") or "").strip()
        if not model:
            skipped += 1
            continue
        by_model[model].append(rec)

    models = {name: _score_model(recs) for name, recs in sorted(by_model.items())}
    return {
        "report": "model_reliability_ledger",
        "model_count": len(models),
        "total_records": sum(len(v) for v in by_model.values()),
        "skipped_records": skipped,
        "models": models,
        "advisory_status": _contract.ADVISORY_STATUS,
        "human_review_required": True,
        # Reliability is advisory weighting only — never an execution authority.
        **_contract.execution_lock_stamp(),
    }


def reliability_for(ledger: dict[str, Any], model_name: str) -> float:
    """Look up a model's reliability, falling back to the neutral prior."""
    model = (ledger.get("models") or {}).get(str(model_name).strip())
    if not model:
        return round((W_DIRECTIONAL + W_INVALIDATION + W_SOURCE_DIVERSITY
                      + W_CALIBRATION + W_MOLTBOOK) * NEUTRAL_PRIOR, 4)
    return float(model.get("reliability", NEUTRAL_PRIOR))


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="model_reliability_ledger.py",
        description=(
            "Score per-model reliability from outcome history and recalibrate "
            "claimed confidence. Advisory-only; never an order. Reads a JSON "
            "list of outcome records from a file."
        ),
    )
    p.add_argument("--input", type=str, default=None,
                   help="JSON file with a list of outcome records.")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    import pathlib

    args = _build_parser().parse_args(argv)
    records: Any = []
    if args.input:
        records = json.loads(pathlib.Path(args.input).read_text(encoding="utf-8-sig"))
    ledger = build_ledger(records)
    if args.json or not args.input:
        print(json.dumps(ledger, indent=2, default=str))
    else:
        print("Model Reliability Ledger (advisory-only)")
        print("========================================")
        for name, m in ledger["models"].items():
            tag = "prior" if m["is_prior"] else f"n={m['sample_size']}"
            print(f"  {name:<14} reliability={m['reliability']:<6} ({tag})")
    return 0


__all__ = [
    "W_DIRECTIONAL", "W_INVALIDATION", "W_SOURCE_DIVERSITY",
    "W_CALIBRATION", "W_MOLTBOOK", "NEUTRAL_PRIOR",
    "calibration_error", "calibrate_confidence",
    "build_ledger", "reliability_for",
]


if __name__ == "__main__":
    raise SystemExit(main())
