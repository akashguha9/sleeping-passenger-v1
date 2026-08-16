"""Regime-transition sprint — Contract Equivalence Score (CES).

Answers ONE question (reflection §23 / component 5):

    Are two prediction-market contracts genuinely resolving the same
    proposition, and how much should a divergence comparison be trusted?

This module wraps the existing semantic-pairing classifier
(``scripts/prediction_market_semantic_pairing.py``) — it does NOT
re-implement event matching.  It adds the numeric CES ∈ [0, 100] and the
comparison gate the disagreement scanner previously lacked.

Design rules (anti-overfitting contract):
- Missing metadata NEVER silently scores 0.  Each missing dimension moves
  its weight into ``unknown_weight``; CES is computed over known weight
  only and ``metadata_coverage`` is reported.  Low coverage fails closed
  (BLOCKED_INSUFFICIENT_METADATA) rather than producing a fake number.
- Gate thresholds (>=90 direct, 75–89 penalized, <75 blocked) come from
  the reflection and are UNCALIBRATED defaults — stamped as such.
- Advisory-only.  No broker, no execution, no order placement.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from scripts.prediction_market_semantic_pairing import (
    AMBIGUOUS_MATCH,
    FALSE_MATCH,
    SAME_EVENT_DIFFERENT_THRESHOLD,
    SAME_EVENT_SAME_RESOLUTION,
    SAME_THEME_DIFFERENT_EVENT,
)

ADVISORY_STATUS = "ADVISORY_ONLY"
REAL_MONEY = "PROHIBITED"
CALIBRATION_STATUS = "UNCALIBRATED_DEFAULTS"

# Comparison gates (reflection §23; uncalibrated).
GATE_DIRECT = "DIRECT_COMPARISON"
GATE_PENALIZED = "PENALIZED_COMPARISON"
GATE_BLOCKED = "BLOCKED_NOT_EQUIVALENT"
GATE_INSUFFICIENT = "BLOCKED_INSUFFICIENT_METADATA"

DIRECT_FLOOR = 90.0
PENALIZED_FLOOR = 75.0
MIN_METADATA_COVERAGE = 0.60

# Dimension weights (sum 100).  Documented, not tuned on any outcome data.
_WEIGHTS: dict[str, float] = {
    "event": 40.0,        # same underlying proposition (semantic pairing class)
    "deadline": 20.0,     # same resolution date/window
    "threshold": 20.0,    # same numeric threshold / condition
    "resolution_source": 10.0,
    "jurisdiction": 10.0,
}

# Semantic-pairing class -> event-dimension credit in [0, 1].
_EVENT_CREDIT: dict[str, float] = {
    SAME_EVENT_SAME_RESOLUTION: 1.0,
    SAME_EVENT_DIFFERENT_THRESHOLD: 0.75,
    AMBIGUOUS_MATCH: 0.40,
    SAME_THEME_DIFFERENT_EVENT: 0.10,
    FALSE_MATCH: 0.0,
}

_DEADLINE_TOLERANCE_DAYS = 3  # settlement-timing slack before credit decays


@dataclass
class ContractSpec:
    """Normalized metadata for one venue's contract.  ``None`` == unknown."""

    venue: str
    title: str
    deadline: str | None = None            # ISO date
    threshold_value: float | None = None
    threshold_unit: str | None = None
    resolution_source: str | None = None
    jurisdiction: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _deadline_credit(a: str | None, b: str | None) -> float | None:
    if a is None or b is None:
        return None
    try:
        da, db = date.fromisoformat(a), date.fromisoformat(b)
    except ValueError:
        return None
    gap = abs((da - db).days)
    if gap == 0:
        return 1.0
    if gap <= _DEADLINE_TOLERANCE_DAYS:
        return 0.5
    return 0.0


def _threshold_credit(a: ContractSpec, b: ContractSpec) -> float | None:
    if a.threshold_value is None or b.threshold_value is None:
        return None
    unit_a = (a.threshold_unit or "").strip().lower()
    unit_b = (b.threshold_unit or "").strip().lower()
    if unit_a and unit_b and unit_a != unit_b:
        return 0.0
    if a.threshold_value == b.threshold_value:
        return 1.0
    hi = max(abs(a.threshold_value), abs(b.threshold_value))
    if hi > 0 and abs(a.threshold_value - b.threshold_value) / hi <= 0.01:
        return 0.9
    return 0.0


def _text_credit(a: str | None, b: str | None) -> float | None:
    if not a or not b:
        return None
    return 1.0 if a.strip().lower() == b.strip().lower() else 0.0


def score_contract_equivalence(
    spec_a: ContractSpec,
    spec_b: ContractSpec,
    *,
    pairing_classification: str | None,
) -> dict[str, Any]:
    """Return the CES verdict for one contract pair.

    ``pairing_classification`` is the label from
    ``prediction_market_semantic_pairing.classify_pair_resolution`` (or None
    when no semantic pass ran — the event dimension is then UNKNOWN).
    """
    credits: dict[str, float | None] = {
        "event": _EVENT_CREDIT.get(pairing_classification)
        if pairing_classification is not None else None,
        "deadline": _deadline_credit(spec_a.deadline, spec_b.deadline),
        "threshold": _threshold_credit(spec_a, spec_b),
        "resolution_source": _text_credit(
            spec_a.resolution_source, spec_b.resolution_source),
        "jurisdiction": _text_credit(spec_a.jurisdiction, spec_b.jurisdiction),
    }
    known_weight = sum(_WEIGHTS[k] for k, v in credits.items() if v is not None)
    unknown_weight = sum(_WEIGHTS[k] for k, v in credits.items() if v is None)
    coverage = known_weight / (known_weight + unknown_weight)

    if coverage < MIN_METADATA_COVERAGE:
        ces: float | None = None
        gate = GATE_INSUFFICIENT
        penalty = 0.0
    else:
        raw = sum(_WEIGHTS[k] * float(v) for k, v in credits.items()
                  if v is not None)
        ces = round(100.0 * raw / known_weight, 2)
        if ces >= DIRECT_FLOOR:
            gate, penalty = GATE_DIRECT, 1.0
        elif ces >= PENALIZED_FLOOR:
            # Linear penalty in the penalized band (documented heuristic).
            gate = GATE_PENALIZED
            penalty = round(
                (ces - PENALIZED_FLOOR) / (DIRECT_FLOOR - PENALIZED_FLOOR), 4)
        else:
            gate, penalty = GATE_BLOCKED, 0.0

    return {
        "ces": ces,
        "gate": gate,
        "divergence_weight_multiplier": penalty,
        "metadata_coverage": round(coverage, 4),
        "dimension_credits": {
            k: (None if v is None else round(v, 4)) for k, v in credits.items()
        },
        "unknown_dimensions": sorted(k for k, v in credits.items() if v is None),
        "pairing_classification": pairing_classification,
        "calibration_status": CALIBRATION_STATUS,
        "safety": {"advisory_status": ADVISORY_STATUS, "real_money": REAL_MONEY},
    }


def divergence_comparison_allowed(verdict: dict[str, Any]) -> bool:
    """True only when a cross-venue divergence signal may be emitted at all."""
    return verdict.get("gate") in (GATE_DIRECT, GATE_PENALIZED)
