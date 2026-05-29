"""Paper-only calibrated-weight readback for advisory external evidence.

EXTERNAL_EVIDENCE_WEIGHT_READBACK
=================================

The Moltbook calibration loop
(:mod:`scripts.external_evidence_moltbook_calibration`) learns a conservative
per-bucket advisory weight ``w_b`` after each *closed* outcome and stores it in
``external_evidence_calibration_buckets``.  Until this module, ``w_b`` was
**record-only**: it was computed and persisted but never read back into the
external-evidence score-delta.  Evidence history therefore could not influence
even the *paper / advisory* analysis.

This module is the read-side of that loop.  It looks up the bucket for an
evidence item, applies sample-size gating and harm-sensitive damping, and
returns an *effective paper-only weight* ``c_i_final`` that the advisory
scoring stage multiplies into the raw item contribution.

Hard safety contract
---------------------
``w_b`` is a **paper-only** prior.  Every return value carries
``real_money_weight_allowed = False`` and
``real_money_sizing_impact = "PROHIBITED"``.  Nothing here places a broker
order, generates a BUY/SELL/ENTER/EXIT, unlocks execution, or affects
real-money sizing.  Any DB read failure degrades to a conservative
error-safe default (``advisory_weight = 0.25``) rather than raising.

Mathematics (see docs/EXTERNAL_EVIDENCE_WEIGHT_READBACK.md)
----------------------------------------------------------
    confidence_band  : COLD (None) | LOW (<0.35) | MID (<0.65) | HIGH (>=0.65)
    bucket_id        : source_name | evidence_type | route_decision | band

    sample-size cap  : n<5 -> 0.25 (COLD_START)
                       5<=n<30 -> 0.50 (EARLY_SAMPLE)
                       30<=n<50 -> 0.75 (PROVISIONAL)
                       n>=50 -> 1.25 / no extra cap (MATURE_PAPER_ONLY)

    harm_damping     : null harm/false -> 1.00 (cold start)
                       else clip(1 - 0.75*X_b - 0.50*F_b, 0.25, 1.00)

    c_i_effective    = min(c_i, sample_cap)
    c_i_final        = clip(c_i_effective * harm_damping, 0.10, 1.25)

Real-money sizing remains PROHIBITED regardless of sample size.
"""
from __future__ import annotations

import sqlite3
from typing import Any

# ----------------------------------------------------------------- clamp range
WEIGHT_FLOOR = 0.10
WEIGHT_CEIL = 1.25

# Conservative cold-start default — no evidence history means no trust.
COLD_START_ADVISORY_WEIGHT = 0.25
COLD_START_RAW_RELIABILITY = 0.50
COLD_START_SAMPLE_MULTIPLIER = 0.50
ERROR_SAFE_ADVISORY_WEIGHT = 0.25

# Real-money influence is structurally off in this sprint regardless of sample
# size — the operator must explicitly approve later.
REAL_MONEY_WEIGHT_ALLOWED = False
REAL_MONEY_SIZING_IMPACT = "PROHIBITED"

# Weight-source vocabulary.
WEIGHT_SOURCE_BUCKET = "BUCKET"
WEIGHT_SOURCE_COLD_START = "COLD_START_DEFAULT"
WEIGHT_SOURCE_ERROR_SAFE = "ERROR_SAFE_DEFAULT"

# Proof-status vocabulary.
PROOF_BUCKET = "CALIBRATION_BUCKET_PAPER_ONLY"
PROOF_COLD_START = "COLD_START_NO_BUCKET_PAPER_ONLY"
PROOF_ERROR_SAFE = "CALIBRATION_READBACK_FAILED_SAFE_DEFAULT"

# Reliability labels (Section 5).
LABEL_COLD_START = "COLD_START"
LABEL_EARLY_SAMPLE = "EARLY_SAMPLE"
LABEL_PROVISIONAL = "PROVISIONAL"
LABEL_MATURE = "MATURE_PAPER_ONLY"

# Modes that allow a paper-only contribution (Section 4 p_i).
_PAPER_MODES = frozenset({"PAPER", "ADVISORY_CONTEXT_ONLY"})
# Evidence statuses that zero-out any contribution (Section 4 p_i).
_ZERO_IMPACT_STATUSES = frozenset(
    {
        "ERROR_SAFE",
        "DISABLED",
        "CONFIG_MISSING",
        "ROUTER_REJECTED",
        "NO_ENABLED_ADAPTERS",
    }
)

# All bucket columns returned by :func:`load_calibration_bucket`.
_BUCKET_FIELDS = (
    "bucket_id",
    "source_name",
    "evidence_type",
    "route_decision",
    "confidence_band",
    "sample_count",
    "help_count",
    "harm_count",
    "false_confidence_count",
    "help_rate",
    "harm_rate",
    "false_confidence_rate",
    "raw_reliability",
    "sample_multiplier",
    "advisory_weight",
    "real_money_weight_allowed",
    "real_money_sizing_impact",
    "proof_status",
)


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


def _s(value: Any) -> str:
    return "" if value is None else str(value).strip()


# --------------------------------------------------------------------- Section 3
def confidence_band(confidence_calibrated: float | None) -> str:
    """Map a calibrated confidence to a coarse band.

    COLD if None; LOW (<0.35); MID (0.35<=c<0.65); HIGH (>=0.65).  Matches
    :func:`scripts.external_evidence_moltbook_calibration.confidence_band` so a
    bucket written at outcome-time is looked up identically at read-time.
    """
    if confidence_calibrated is None:
        return "COLD"
    c = float(confidence_calibrated)
    if c < 0.35:
        return "LOW"
    if c < 0.65:
        return "MID"
    return "HIGH"


def make_calibration_bucket_id(
    source_name: str,
    evidence_type: str,
    route_decision: str,
    confidence_band: str,  # noqa: A002 - matches Section 3 signature name
) -> str:
    """Deterministic bucket id: ``source|type|route|band``."""
    return "|".join(
        [_s(source_name), _s(evidence_type), _s(route_decision), _s(confidence_band)]
    )


def default_cold_start_bucket(
    *,
    bucket_id: str = "",
    source_name: str = "",
    evidence_type: str = "",
    route_decision: str = "",
    confidence_band: str = "",  # noqa: A002
    proof_status: str = PROOF_COLD_START,
) -> dict[str, Any]:
    """A conservative default bucket used when no history exists.

    No evidence history means no trust: a low advisory weight and a half
    sample-multiplier reduce influence rather than inventing confidence.
    """
    return {
        "bucket_id": bucket_id,
        "source_name": source_name,
        "evidence_type": evidence_type,
        "route_decision": route_decision,
        "confidence_band": confidence_band,
        "sample_count": 0,
        "help_count": 0,
        "harm_count": 0,
        "false_confidence_count": 0,
        "help_rate": None,
        "harm_rate": None,
        "false_confidence_rate": None,
        "raw_reliability": COLD_START_RAW_RELIABILITY,
        "sample_multiplier": COLD_START_SAMPLE_MULTIPLIER,
        "advisory_weight": COLD_START_ADVISORY_WEIGHT,
        "real_money_weight_allowed": False,
        "real_money_sizing_impact": REAL_MONEY_SIZING_IMPACT,
        "proof_status": proof_status,
    }


def load_calibration_bucket(
    conn: sqlite3.Connection, bucket_id: str
) -> dict[str, Any] | None:
    """Read one calibration bucket (read-only).  Returns None if absent.

    ``real_money_weight_allowed`` is normalised to a bool and
    ``real_money_sizing_impact`` is forced to PROHIBITED on the way out, so a
    bucket can never carry real-money authority even if the row were tampered.
    """
    row = conn.execute(
        "SELECT bucket_id, source_name, evidence_type, route_decision,"
        " confidence_band, sample_count, help_count, harm_count,"
        " false_confidence_count, help_rate, harm_rate, false_confidence_rate,"
        " raw_reliability, sample_multiplier, advisory_weight,"
        " real_money_weight_allowed, real_money_sizing_impact, proof_status"
        " FROM external_evidence_calibration_buckets WHERE bucket_id=?",
        (_s(bucket_id),),
    ).fetchone()
    if row is None:
        return None
    out = {field: row[i] for i, field in enumerate(_BUCKET_FIELDS)}
    out["real_money_weight_allowed"] = False
    out["real_money_sizing_impact"] = REAL_MONEY_SIZING_IMPACT
    return out


# --------------------------------------------------------------------- Section 5
def sample_size_cap(sample_count: int) -> tuple[float, str, str]:
    """Return ``(cap, reliability_label, operator_message)`` for ``n``.

    Tiny samples must not manufacture confidence, so the effective weight is
    capped progressively until a mature (n>=50) sample is reached.  Even a
    mature sample stays paper-only — real-money sizing remains prohibited.
    """
    n = int(sample_count or 0)
    if n < 5:
        return (
            0.25,
            LABEL_COLD_START,
            "Too few outcomes. Reliability heavily discounted.",
        )
    if n < 30:
        return 0.50, LABEL_EARLY_SAMPLE, "Early evidence only. Paper-only."
    if n < 50:
        return 0.75, LABEL_PROVISIONAL, "Provisional reliability. Paper-only."
    return (
        WEIGHT_CEIL,
        LABEL_MATURE,
        "Mature sample, still paper-only. Real-money sizing prohibited.",
    )


# --------------------------------------------------------------------- Section 6
def harm_damping(
    harm_rate: float | None, false_confidence_rate: float | None
) -> float:
    """Damp the weight when a bucket has high harm / false-confidence rates.

    Bad evidence should lose influence faster than good evidence gains it.
    Null rates (cold start) yield no damping (1.00); the cold-start cap still
    applies upstream.
    """
    x = _f(harm_rate)
    f = _f(false_confidence_rate)
    if x is None or f is None:
        return 1.00
    return _clip(1.0 - 0.75 * x - 0.50 * f, 0.25, 1.00)


# --------------------------------------------------------------------- Section 4
def paper_only_eligibility(mode: str, status: str) -> float:
    """Return ``p_i`` in {0.0, 1.0}.

    1.0 only for a paper / advisory mode on a non-zero-impact status; 0.0 for
    real-money mode or any error/disabled/rejected evidence status.
    """
    if _s(mode).upper() == "REAL_MONEY":
        return 0.0
    if _s(status).upper() in _ZERO_IMPACT_STATUSES:
        return 0.0
    if _s(mode).upper() in _PAPER_MODES:
        return 1.0
    # Unknown mode: default conservative-but-allowed (advisory context).
    return 1.0


def _confidence_from_item(evidence_item: dict[str, Any]) -> float | None:
    """Best-effort calibrated confidence for band selection."""
    direct = _f(evidence_item.get("confidence_calibrated"))
    if direct is not None:
        return direct
    summary = evidence_item.get("payload_summary")
    if isinstance(summary, dict):
        return _f(summary.get("KRONOS_CONFIDENCE_CALIBRATED"))
    return None


# --------------------------------------------------------------------- Section 3
def calibrated_weight_for_item(
    conn: sqlite3.Connection | None, evidence_item: dict[str, Any]
) -> dict[str, Any]:
    """Resolve the paper-only effective weight for one evidence item.

    Looks up the bucket (cold-start default when absent, error-safe default on
    any DB failure), applies the sample-size cap and harm-sensitive damping,
    and returns the full calibration read.  Never raises.

    The returned ``advisory_weight`` is the bucket's stored ``w_b``;
    ``effective_weight`` (``c_i_final``) is the value the scoring stage must
    actually multiply into the raw contribution.
    """
    item = dict(evidence_item or {})
    source_name = _s(item.get("source_name")) or "unknown"
    evidence_type = _s(item.get("evidence_type")) or "UNKNOWN"
    route_decision = _s(item.get("route_decision")).upper() or "REJECT"
    conf = _confidence_from_item(item)
    band = confidence_band(conf)
    bucket_id = make_calibration_bucket_id(
        source_name, evidence_type, route_decision, band
    )

    weight_source = WEIGHT_SOURCE_BUCKET
    bucket: dict[str, Any] | None = None
    try:
        if conn is None:
            raise RuntimeError("no calibration connection")
        bucket = load_calibration_bucket(conn, bucket_id)
    except Exception:  # noqa: BLE001 - DB failure degrades to error-safe default
        bucket = default_cold_start_bucket(
            bucket_id=bucket_id,
            source_name=source_name,
            evidence_type=evidence_type,
            route_decision=route_decision,
            confidence_band=band,
            proof_status=PROOF_ERROR_SAFE,
        )
        bucket["advisory_weight"] = ERROR_SAFE_ADVISORY_WEIGHT
        weight_source = WEIGHT_SOURCE_ERROR_SAFE

    if bucket is None:
        bucket = default_cold_start_bucket(
            bucket_id=bucket_id,
            source_name=source_name,
            evidence_type=evidence_type,
            route_decision=route_decision,
            confidence_band=band,
        )
        weight_source = WEIGHT_SOURCE_COLD_START

    sample_count = int(bucket.get("sample_count") or 0)
    advisory_weight = _f(bucket.get("advisory_weight"))
    if advisory_weight is None:
        advisory_weight = COLD_START_ADVISORY_WEIGHT
    harm_rate = _f(bucket.get("harm_rate"))
    false_rate = _f(bucket.get("false_confidence_rate"))

    cap, reliability_label, operator_message = sample_size_cap(sample_count)
    c_i_effective = min(advisory_weight, cap)
    damping = harm_damping(harm_rate, false_rate)
    c_i_final = _clip(c_i_effective * damping, WEIGHT_FLOOR, WEIGHT_CEIL)

    proof_status = bucket.get("proof_status") or (
        PROOF_BUCKET if weight_source == WEIGHT_SOURCE_BUCKET else PROOF_COLD_START
    )
    if weight_source == WEIGHT_SOURCE_ERROR_SAFE:
        proof_status = PROOF_ERROR_SAFE
    elif weight_source == WEIGHT_SOURCE_COLD_START:
        proof_status = PROOF_COLD_START

    return {
        "bucket_id": bucket_id,
        "confidence_band": band,
        "sample_count": sample_count,
        "help_rate": _f(bucket.get("help_rate")),
        "harm_rate": harm_rate,
        "false_confidence_rate": false_rate,
        "raw_reliability": _f(bucket.get("raw_reliability")),
        "sample_multiplier": _f(bucket.get("sample_multiplier")),
        "advisory_weight": round(advisory_weight, 6),
        "effective_weight": round(c_i_final, 6),
        "harm_damping": round(damping, 6),
        "weight_source": weight_source,
        "reliability_label": reliability_label,
        "operator_message": operator_message,
        # Hard, unconditional safety stamps.
        "real_money_weight_allowed": False,
        "real_money_sizing_impact": REAL_MONEY_SIZING_IMPACT,
        "proof_status": proof_status,
    }


__all__ = [
    "WEIGHT_FLOOR",
    "WEIGHT_CEIL",
    "COLD_START_ADVISORY_WEIGHT",
    "ERROR_SAFE_ADVISORY_WEIGHT",
    "REAL_MONEY_WEIGHT_ALLOWED",
    "REAL_MONEY_SIZING_IMPACT",
    "WEIGHT_SOURCE_BUCKET",
    "WEIGHT_SOURCE_COLD_START",
    "WEIGHT_SOURCE_ERROR_SAFE",
    "LABEL_COLD_START",
    "LABEL_EARLY_SAMPLE",
    "LABEL_PROVISIONAL",
    "LABEL_MATURE",
    "confidence_band",
    "make_calibration_bucket_id",
    "default_cold_start_bucket",
    "load_calibration_bucket",
    "sample_size_cap",
    "harm_damping",
    "paper_only_eligibility",
    "calibrated_weight_for_item",
]
