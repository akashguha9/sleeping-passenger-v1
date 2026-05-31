"""Increase Forward-Eligible Throughput Sprint — Phase 4: resolve
MISSING_PROBABILITY without ever faking it.

A forward-eligible snapshot needs a valid ``model_probability`` in ``[0, 1]``.
The honest rule, restated and enforced here:

* A **complete** six-axis score vector ALWAYS yields a probability via the
  documented advisory logistic link::

      raw = mean(EMS, EQS, DS, LS, EFS, APS)
      p   = sigmoid(beta0 + beta1 * raw)        # beta0=0, beta1=1 (defaults)

  (this is the same math as :mod:`scripts.probability_snapshot`; it is a
  data-quality score, never a claim of predictive edge).
* An **incomplete** vector (a missing or out-of-range axis) yields ``p = None``
  with reason ``SCORE_VECTOR_INCOMPLETE`` — never a fabricated value.
* A **missing** vector yields ``p = None`` with ``SCORE_VECTOR_MISSING``.

So MISSING_PROBABILITY is only ever caused by an incomplete/missing vector — it
is *not* a wiring bug for complete vectors.  :func:`audit_missing_probability`
proves this against the side table: it reports how many SCORED-but-incomplete or
unscored rows exist, and asserts that every complete vector is resolvable.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Mapping

try:  # package layout
    from scripts.probability_snapshot import compute_model_probability
    from scripts.score_real_signal_events import (
        SCORE_VECTOR_TABLE,
        complete_axes_from_row,
        ensure_score_vector_schema,
    )
    from scripts.real_signal_score_vector import SCORED
except ModuleNotFoundError:  # pragma: no cover - flat-layout fallback
    from probability_snapshot import compute_model_probability  # type: ignore[no-redef]
    from score_real_signal_events import (  # type: ignore[no-redef]
        SCORE_VECTOR_TABLE,
        complete_axes_from_row,
        ensure_score_vector_schema,
    )
    from real_signal_score_vector import SCORED  # type: ignore[no-redef]

_AXES = ("EMS", "EQS", "DS", "LS", "EFS", "APS")

REASON_OK = "OK"
SCORE_VECTOR_MISSING = "SCORE_VECTOR_MISSING"
SCORE_VECTOR_INCOMPLETE = "SCORE_VECTOR_INCOMPLETE"


def _complete_axes(vector: Mapping[str, Any] | None) -> dict[str, float] | None:
    """Return the six axes as floats iff every one is present and in [0, 1]."""
    if not vector:
        return None
    out: dict[str, float] = {}
    for axis in _AXES:
        v = vector.get(axis)
        if v is None:
            return None
        try:
            fv = float(v)
        except (TypeError, ValueError):
            return None
        if fv < 0.0 or fv > 1.0:
            return None
        out[axis] = fv
    return out


def resolve_probability(vector: Mapping[str, Any] | None) -> tuple[float | None, str]:
    """Resolve ``(probability, reason)`` for a score vector.

    Complete vector -> ``(p in [0,1], "OK")``.  Incomplete -> ``(None,
    SCORE_VECTOR_INCOMPLETE)``.  Missing -> ``(None, SCORE_VECTOR_MISSING)``.
    Never fabricates a probability.
    """
    if not vector:
        return None, SCORE_VECTOR_MISSING
    axes = _complete_axes(vector)
    if axes is None:
        return None, SCORE_VECTOR_INCOMPLETE
    raw = sum(axes.values()) / len(axes)
    p = compute_model_probability(raw)
    return p, REASON_OK


def audit_missing_probability(db_path: Any) -> dict[str, Any]:
    """Audit the side table: prove complete vectors always resolve a probability.

    Read-only.  Returns counts of complete/incomplete/missing vectors and the
    number of complete vectors that failed to resolve (must be 0 — a regression
    canary).  Never claims calibration.
    """
    ensure_score_vector_schema(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(
            f"SELECT * FROM {SCORE_VECTOR_TABLE}"
        ).fetchall()]
    finally:
        conn.close()

    complete = 0
    incomplete = 0
    missing = 0
    complete_resolved = 0
    complete_unresolved = 0
    for r in rows:
        is_complete = str(r.get("score_status")) == SCORED and complete_axes_from_row(r) is not None
        if is_complete:
            complete += 1
            p, reason = resolve_probability(r)
            if p is not None and 0.0 <= p <= 1.0 and reason == REASON_OK:
                complete_resolved += 1
            else:
                complete_unresolved += 1
        elif str(r.get("score_status")) == SCORED:
            incomplete += 1
        else:
            missing += 1

    return {
        "total_vectors": len(rows),
        "complete_vectors": complete,
        "incomplete_vectors": incomplete,
        "missing_or_unscored_vectors": missing,
        "complete_resolved_to_probability": complete_resolved,
        "complete_unresolved": complete_unresolved,  # MUST be 0
        "wiring_ok": complete_unresolved == 0,
        # No fabricated probability is ever produced for incomplete rows.
        "predictive_claim_allowed": False,
        "calibration_status": "INSUFFICIENT_EVIDENCE",
        "advisory_status": "ADVISORY_ONLY",
        "execution_gate": "LOCKED",
    }


__all__ = [
    "REASON_OK",
    "SCORE_VECTOR_MISSING",
    "SCORE_VECTOR_INCOMPLETE",
    "resolve_probability",
    "audit_missing_probability",
]
