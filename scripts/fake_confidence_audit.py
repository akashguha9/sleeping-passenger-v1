"""Fake-confidence defensive layer for advisory external evidence.

KANTE_FAKE_CONFIDENCE_AUDIT
===========================

N'Golo Kanté does the invisible defensive work: he closes the space before the
danger becomes visible.  This module is that closing-down for *confidence*.  The
Moltbook calibration loop learns a per-bucket advisory weight ``w_b`` from closed
outcomes.  A bucket that *looks* confident — a high learned weight — but keeps
being wrong (high harm rate) or wrong-while-sure (high false-confidence rate) is
exactly the counter-attack we must kill before it starts.

This module computes a single ``overconfidence_score`` (OCR) per bucket / item,
labels the fake-confidence risk, and provides the **hard block**: a HIGH-risk
bucket can never *add* positive score delta.  It can only reduce risk or trigger
human review.

Mathematics (see docs/KANTE_SCORE_CEILING_AUDIT.md, WORKSTREAM D / Section 4)
-----------------------------------------------------------------------------
    false_confidence_rate = false_confidence_count / max(sample_count, 1)
    harm_rate             = harm_count             / max(sample_count, 1)
    realized_help_rate    = help_count             / max(sample_count, 1)
    confidence_gap        = advisory_weight - realized_help_rate

    overconfidence_score (OCR) = clip(
          0.50 * false_confidence_rate
        + 0.30 * harm_rate
        + 0.20 * max(confidence_gap, 0),
        0, 1)

    label:
        sample_count < 5   -> COLD_START_UNKNOWN
        OCR >= 0.70        -> HIGH_FAKE_CONFIDENCE_RISK
        OCR >= 0.40        -> MODERATE_FAKE_CONFIDENCE_RISK
        else               -> LOW_FAKE_CONFIDENCE_RISK

    hard block:
        if OCR >= 0.70 and delta_calibrated > 0:
            positive_delta_allowed = False
            delta_calibrated = min(delta_calibrated, 0)

Hard safety contract
--------------------
Pure module.  No DB, no filesystem, no network, no broker calls.  Every returned
dict carries ``real_money_sizing_impact = "PROHIBITED"`` and
``real_money_weight_allowed = False``.  Nothing here places an order, sizes real
money, or unlocks execution.  The block can only *remove* positive influence,
never add it — bad evidence loses faster than good evidence gains.
"""
from __future__ import annotations

from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

# ----------------------------------------------------------------- thresholds
HIGH_RISK_THRESHOLD = 0.70
MODERATE_RISK_THRESHOLD = 0.40
COLD_START_MIN_SAMPLES = 5

# OCR weighting (Section 4).
W_FALSE_CONFIDENCE = 0.50
W_HARM = 0.30
W_CONFIDENCE_GAP = 0.20

# Risk labels.
LABEL_COLD_START = "COLD_START_UNKNOWN"
LABEL_HIGH = "HIGH_FAKE_CONFIDENCE_RISK"
LABEL_MODERATE = "MODERATE_FAKE_CONFIDENCE_RISK"
LABEL_LOW = "LOW_FAKE_CONFIDENCE_RISK"

REAL_MONEY_SIZING_IMPACT = "PROHIBITED"

PROOF_AUDIT = "FAKE_CONFIDENCE_AUDIT_PAPER_ONLY"


def _clip(value: float, low: float, high: float) -> float:
    if value < low:
        return low
    if value > high:
        return high
    return value


def _f(value: Any) -> float | None:
    """Coerce to float or None (never raises)."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if out != out else out  # NaN guard


def _rate_from(rate: Any, count: Any, sample_count: int) -> float:
    """Prefer an explicit rate; else derive ``count / max(sample, 1)``."""
    r = _f(rate)
    if r is not None:
        return _clip(r, 0.0, 1.0)
    c = _f(count)
    if c is None:
        return 0.0
    return _clip(c / max(sample_count, 1), 0.0, 1.0)


def compute_overconfidence(
    *,
    sample_count: int = 0,
    advisory_weight: float | None = None,
    help_rate: float | None = None,
    harm_rate: float | None = None,
    false_confidence_rate: float | None = None,
    help_count: int | None = None,
    harm_count: int | None = None,
    false_confidence_count: int | None = None,
) -> dict[str, Any]:
    """Compute the overconfidence score (OCR) + fake-confidence label.

    Accepts either explicit rates or raw counts (rates win when both supplied).
    ``advisory_weight`` is the learned paper-only weight ``w_b`` (treated as
    ``c_i`` for the confidence-gap term); when absent the gap term is 0.  Never
    raises.
    """
    n = int(sample_count or 0)
    f_rate = _rate_from(false_confidence_rate, false_confidence_count, n)
    x_rate = _rate_from(harm_rate, harm_count, n)
    h_rate = _rate_from(help_rate, help_count, n)
    weight = _f(advisory_weight)
    confidence_gap = 0.0 if weight is None else (weight - h_rate)
    positive_gap = max(confidence_gap, 0.0)

    ocr = _clip(
        W_FALSE_CONFIDENCE * f_rate + W_HARM * x_rate + W_CONFIDENCE_GAP * positive_gap,
        0.0,
        1.0,
    )

    label = fake_confidence_label(ocr, n)
    return {
        "sample_count": n,
        "false_confidence_rate": round(f_rate, 6),
        "harm_rate": round(x_rate, 6),
        "realized_help_rate": round(h_rate, 6),
        "advisory_weight": None if weight is None else round(weight, 6),
        "confidence_gap": round(confidence_gap, 6),
        "overconfidence_score": round(ocr, 6),
        "fake_confidence_label": label,
        "positive_delta_allowed": label != LABEL_HIGH,
        "real_money_weight_allowed": False,
        "real_money_sizing_impact": REAL_MONEY_SIZING_IMPACT,
        "proof_status": PROOF_AUDIT,
    }


def fake_confidence_label(overconfidence_score: float, sample_count: int) -> str:
    """Map OCR + sample size to a fake-confidence risk label.

    Cold start (too few samples) is *unknown*, never "low" — absence of harm
    evidence is not evidence of safety.
    """
    if int(sample_count or 0) < COLD_START_MIN_SAMPLES:
        return LABEL_COLD_START
    ocr = float(overconfidence_score or 0.0)
    if ocr >= HIGH_RISK_THRESHOLD:
        return LABEL_HIGH
    if ocr >= MODERATE_RISK_THRESHOLD:
        return LABEL_MODERATE
    return LABEL_LOW


def apply_fake_confidence_block(
    delta_calibrated: float, overconfidence_score: float, sample_count: int
) -> dict[str, Any]:
    """Apply the hard fake-confidence block to a calibrated item delta.

    HIGH fake-confidence risk can never *add* positive score delta: a positive
    delta is forced to 0.  Negative deltas (risk reduction) pass through —
    fake-confident evidence is still allowed to *lower* a score.  Cold-start and
    moderate/low risk pass through unchanged.
    """
    delta = _f(delta_calibrated) or 0.0
    label = fake_confidence_label(overconfidence_score, sample_count)
    blocked = label == LABEL_HIGH and delta > 0
    out_delta = 0.0 if blocked else delta
    return {
        "delta_in": round(delta, 6),
        "delta_out": round(out_delta, 6),
        "positive_delta_blocked": blocked,
        "positive_delta_allowed": label != LABEL_HIGH,
        "fake_confidence_label": label,
        "overconfidence_score": round(float(overconfidence_score or 0.0), 6),
        "real_money_sizing_impact": REAL_MONEY_SIZING_IMPACT,
    }


def audit_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
    """Audit a single calibration-bucket-shaped dict for fake confidence.

    Reads the bucket fields produced by
    :mod:`scripts.external_evidence_moltbook_calibration` /
    :mod:`scripts.external_evidence_weight_readback` and returns the OCR audit
    plus the bucket id for grouping.
    """
    b = dict(bucket or {})
    audit = compute_overconfidence(
        sample_count=int(b.get("sample_count") or 0),
        advisory_weight=b.get("advisory_weight"),
        help_rate=b.get("help_rate"),
        harm_rate=b.get("harm_rate"),
        false_confidence_rate=b.get("false_confidence_rate"),
        help_count=b.get("help_count"),
        harm_count=b.get("harm_count"),
        false_confidence_count=b.get("false_confidence_count"),
    )
    audit["bucket_id"] = b.get("bucket_id") or ""
    audit["source_name"] = b.get("source_name") or ""
    audit["evidence_type"] = b.get("evidence_type") or ""
    return audit


def build_fake_confidence_summary(
    buckets: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Summarise fake-confidence risk across a set of calibration buckets.

    Honest when empty: with no buckets the summary reports
    ``COLD_START_UNKNOWN`` and ``data_available = False`` rather than inventing
    a "low risk" all-clear.  Identifies the best source bucket (largest mature,
    low-risk sample) and the worst (highest harm / false-confidence rate).
    """
    audits = [audit_bucket(b) for b in (buckets or [])]
    if not audits:
        out = {
            "data_available": False,
            "bucket_count": 0,
            "high_risk_count": 0,
            "moderate_risk_count": 0,
            "low_risk_count": 0,
            "cold_start_count": 0,
            "overall_fake_confidence_label": LABEL_COLD_START,
            "max_overconfidence_score": 0.0,
            "best_source_bucket": None,
            "worst_source_bucket": None,
            "operator_message": (
                "No closed-outcome buckets yet. Fake-confidence risk is "
                "UNKNOWN (cold start), not low. Paper outcomes needed."
            ),
        }
        out.update(_contract.advisory_safety_stamps())
        out["real_money_sizing_impact"] = REAL_MONEY_SIZING_IMPACT
        out["proof_status"] = PROOF_AUDIT
        return out

    high = [a for a in audits if a["fake_confidence_label"] == LABEL_HIGH]
    moderate = [a for a in audits if a["fake_confidence_label"] == LABEL_MODERATE]
    low = [a for a in audits if a["fake_confidence_label"] == LABEL_LOW]
    cold = [a for a in audits if a["fake_confidence_label"] == LABEL_COLD_START]

    if high:
        overall = LABEL_HIGH
    elif moderate:
        overall = LABEL_MODERATE
    elif low:
        overall = LABEL_LOW
    else:
        overall = LABEL_COLD_START

    # Best bucket: a mature, low-risk source with the largest sample.
    mature_low = [
        a for a in audits
        if a["fake_confidence_label"] == LABEL_LOW and a["sample_count"] >= 5
    ]
    best = max(mature_low, key=lambda a: a["sample_count"], default=None)
    # Worst bucket: highest overconfidence among non-cold-start buckets.
    rated = [a for a in audits if a["fake_confidence_label"] != LABEL_COLD_START]
    worst = max(rated, key=lambda a: a["overconfidence_score"], default=None)

    max_ocr = max((a["overconfidence_score"] for a in audits), default=0.0)

    out = {
        "data_available": True,
        "bucket_count": len(audits),
        "high_risk_count": len(high),
        "moderate_risk_count": len(moderate),
        "low_risk_count": len(low),
        "cold_start_count": len(cold),
        "overall_fake_confidence_label": overall,
        "max_overconfidence_score": round(max_ocr, 6),
        "best_source_bucket": best,
        "worst_source_bucket": worst,
        "operator_message": _summary_message(overall, len(high)),
    }
    out.update(_contract.advisory_safety_stamps())
    out["real_money_sizing_impact"] = REAL_MONEY_SIZING_IMPACT
    out["proof_status"] = PROOF_AUDIT
    return out


def _summary_message(overall_label: str, high_count: int) -> str:
    if overall_label == LABEL_HIGH:
        return (
            f"{high_count} bucket(s) at HIGH fake-confidence risk. Positive "
            "score delta is BLOCKED for those buckets; human review required."
        )
    if overall_label == LABEL_MODERATE:
        return "Moderate fake-confidence risk present. Weights damped; review."
    if overall_label == LABEL_LOW:
        return "Fake-confidence risk low across rated buckets. Still paper-only."
    return "Fake-confidence risk unknown (cold start). Paper outcomes needed."


__all__ = [
    "HIGH_RISK_THRESHOLD",
    "MODERATE_RISK_THRESHOLD",
    "COLD_START_MIN_SAMPLES",
    "LABEL_COLD_START",
    "LABEL_HIGH",
    "LABEL_MODERATE",
    "LABEL_LOW",
    "REAL_MONEY_SIZING_IMPACT",
    "compute_overconfidence",
    "fake_confidence_label",
    "apply_fake_confidence_block",
    "audit_bucket",
    "build_fake_confidence_summary",
]
