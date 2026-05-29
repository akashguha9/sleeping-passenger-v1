"""Moltbook calibration for advisory external evidence — learn after the close.

EXTERNAL_EVIDENCE_MOLTBOOK_CALIBRATION
======================================

This module closes the learning loop for the advisory external-evidence
framework.  Snapshots are persisted at *signal time* by
:mod:`scripts.external_evidence_persistence` as immutable evidence-at-time-t.
This module is the *outcome-time* half: when a paper / manual trade closes, it
loads the original snapshot(s), compares the forecast / context against the
realized outcome, writes one advisory learning record per snapshot, and updates
a conservative per-source calibration weight ``w_b`` for FUTURE advisory
analysis only.

Why learn only after the close
------------------------------
External evidence must be judged only once the outcome is known.  There is no
pre-outcome self-confirmation: a snapshot cannot mark *itself* helpful.  Open
trades never learn (``OUTCOME_NOT_FINAL``); trades with missing entry/exit
prices never learn (``INSUFFICIENT_OUTCOME_DATA``).

Hard safety contract
--------------------
Nothing here affects real-money sizing.  ``real_money_sizing_impact`` is
``PROHIBITED`` on every row and every return value, ``real_money_weight_allowed``
is always 0, the advisory weights only ever feed *paper* analysis, and the
module never places a broker order, never generates BUY/SELL/ENTER/EXIT, and
never unlocks execution.  Any failure degrades to ``ERROR_SAFE`` with zero
decision impact rather than raising.

Mathematics (see docs/EXTERNAL_EVIDENCE_MOLTBOOK_CALIBRATION.md)
---------------------------------------------------------------
    R_actual            = (P_exit - P_entry) / P_entry
    realized_return_pct = 100 * R_actual
    actual_direction    = +1 if rr > +THETA_ACTUAL, -1 if rr < -THETA_ACTUAL, else 0
    forecast_direction  = from KRONOS_FORECAST_RETURN_PCT (THETA_FORECAST),
                          else alignment_score (THETA_ALIGNMENT), else 0
    direction_correct   = 1 iff both nonzero and equal
    forecast_error_pct  = |forecast_return_pct - realized_return_pct|

    H_b = h_b/max(n_b,1)   X_b = x_b/max(n_b,1)   F_b = f_b/max(n_b,1)
    Rel_b = clip(0.50 + 0.75*(H_b-0.50) - 1.00*X_b - 0.75*F_b, 0.10, 1.25)
    sample_multiplier_b = 0.50 (n<30) | 0.75 (30<=n<50) | 1.00 (n>=50)
    w_b = clip(Rel_b * sample_multiplier_b, 0.10, 1.25)
"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any

try:
    import scripts.external_evidence_persistence as eep
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import external_evidence_persistence as eep  # type: ignore[no-redef]

try:
    from scripts.runtime_common import utc_timestamp
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from runtime_common import utc_timestamp  # type: ignore[no-redef]


# ------------------------------------------------------------------- thresholds
THETA_ACTUAL = 0.25      # % move that counts as a real realized direction
THETA_FORECAST = 0.50    # % forecast return that counts as a directional call
THETA_ALIGNMENT = 0.10   # alignment score magnitude that counts as directional
MISSED_OPPORTUNITY_THRESHOLD = 2.0  # % up that a negative-evidence miss "harmed"
FALSE_CONFIDENCE_MIN = 0.50         # calibrated-confidence floor for false confidence
REAL_MONEY_MIN_SAMPLES = 50         # n_b below which real-money is structurally off

# Weight clamp + reliability constants (Section 8).
WEIGHT_FLOOR = 0.10
WEIGHT_CEIL = 1.25
REL_BASE = 0.50
REL_HELP_COEF = 0.75
REL_HARM_COEF = 1.00
REL_FALSE_COEF = 0.75

REAL_MONEY_SIZING_IMPACT = "PROHIBITED"
EXECUTION_GATE_LOCKED = "LOCKED"

# Result statuses.
STATUS_RECORDED = "RECORDED"
STATUS_NO_MATCH = "NO_MATCHING_EVIDENCE"
STATUS_NOT_FINAL = "OUTCOME_NOT_FINAL"
STATUS_INSUFFICIENT = "INSUFFICIENT_OUTCOME_DATA"
STATUS_ERROR_SAFE = "ERROR_SAFE"

_PROOF = {
    STATUS_RECORDED: "OUTCOME_RECORDED_ADVISORY_ONLY",
    STATUS_NO_MATCH: "NO_MATCHING_EVIDENCE_NO_DECISION_IMPACT",
    STATUS_NOT_FINAL: "OUTCOME_NOT_FINAL_NO_LEARNING",
    STATUS_INSUFFICIENT: "INSUFFICIENT_OUTCOME_DATA_NO_LEARNING",
    STATUS_ERROR_SAFE: "OUTCOME_LEARNING_FAILED_SAFE_NO_DECISION_IMPACT",
}

# Trade states that mean "final / closed" → eligible to learn.
_CLOSED_STATES = frozenset(
    {
        "CLOSED", "CLOSED_LOSS", "CLOSED_WIN", "TP_HIT", "TAKE_PROFIT",
        "STOP_LOSS", "STOP_LOSS_HIT", "STOP_LOSS_BREACH", "MANUAL_EXIT",
        "EXITED", "EXIT", "FULLY_RECONCILED", "RECONCILED", "WIN", "LOSS",
        "PROFIT", "GAIN", "LOSING", "BREAKEVEN", "SCRATCH", "FLAT",
    }
)
# Trade states that explicitly mean "still open" → never learn.
_OPEN_STATES = frozenset(
    {"OPEN", "ACTIVE", "PARTIAL", "EXIT_PENDING", "REDUCED", "UNRECONCILED"}
)


def _f(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:
        return None
    return f


def _s(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _clip(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


def _dir_to_text(direction: int) -> str:
    return "UP" if direction > 0 else "DOWN" if direction < 0 else "FLAT"


# --------------------------------------------------------------------- math API
def confidence_band(confidence_calibrated: float | None) -> str:
    """Map a calibrated confidence to a coarse band (Section 7)."""
    if confidence_calibrated is None:
        return "COLD"
    c = float(confidence_calibrated)
    if c < 0.35:
        return "LOW"
    if c < 0.65:
        return "MID"
    return "HIGH"


def actual_direction(realized_return_pct: float) -> int:
    if realized_return_pct > THETA_ACTUAL:
        return 1
    if realized_return_pct < -THETA_ACTUAL:
        return -1
    return 0


def forecast_direction(
    forecast_return_pct: float | None,
    alignment_score: float | None,
) -> int:
    if forecast_return_pct is not None:
        if forecast_return_pct > THETA_FORECAST:
            return 1
        if forecast_return_pct < -THETA_FORECAST:
            return -1
        return 0
    if alignment_score is not None:
        if alignment_score > THETA_ALIGNMENT:
            return 1
        if alignment_score < -THETA_ALIGNMENT:
            return -1
        return 0
    return 0


def make_learning_id(
    *,
    snapshot_id: str,
    trade_id: str,
    exit_timestamp_utc: str,
    outcome_event_type: str,
) -> str:
    """Deterministic learning id (Section 6 idempotency)."""
    raw = "|".join(
        [
            _s(snapshot_id),
            _s(trade_id),
            _s(exit_timestamp_utc),
            _s(outcome_event_type),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _forecast_return_from_snapshot(snapshot: dict[str, Any]) -> float | None:
    """Pull KRONOS_FORECAST_RETURN_PCT from a snapshot's payload_json."""
    import json

    raw = snapshot.get("payload_json")
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    return _f(payload.get("KRONOS_FORECAST_RETURN_PCT"))


def compute_outcome_metrics(
    snapshot: dict[str, Any],
    trade_outcome: dict[str, Any],
) -> dict[str, Any]:
    """Compute all Section 6/7 learning fields for one snapshot + closed trade.

    Caller must have already validated entry/exit prices are present and
    ``entry_price != 0``.
    """
    entry_price = _f(trade_outcome.get("entry_price"))
    exit_price = _f(trade_outcome.get("exit_price"))
    assert entry_price not in (None, 0.0) and exit_price is not None

    r_actual = (exit_price - entry_price) / entry_price
    realized_return_pct = 100.0 * r_actual

    score_delta = _f(snapshot.get("score_delta")) or 0.0
    alignment = _f(snapshot.get("alignment_score"))
    conf_cal = _f(snapshot.get("confidence_calibrated"))
    downside = _f(snapshot.get("downside_risk"))
    route_decision = _s(snapshot.get("route_decision")).upper()

    fcast_return = _forecast_return_from_snapshot(snapshot)
    a_dir = actual_direction(realized_return_pct)
    f_dir = forecast_direction(fcast_return, alignment)
    direction_correct = 1 if (f_dir != 0 and a_dir != 0 and f_dir == a_dir) else 0

    forecast_error_pct = (
        abs(fcast_return - realized_return_pct) if fcast_return is not None else None
    )

    helped = _evidence_helped(
        route_decision=route_decision,
        score_delta=score_delta,
        direction_correct=direction_correct,
        realized_return_pct=realized_return_pct,
    )
    harmed = _evidence_harmed(
        score_delta=score_delta, realized_return_pct=realized_return_pct
    )
    false_conf = _false_confidence(
        score_delta=score_delta,
        confidence_calibrated=conf_cal,
        realized_return_pct=realized_return_pct,
    )
    risk_reducer = 1 if (score_delta < 0 and realized_return_pct < 0) else 0

    bucket_id = _bucket_id(
        source_name=_s(snapshot.get("source_name")),
        evidence_type=_s(snapshot.get("evidence_type")),
        route_decision=route_decision,
        band=confidence_band(conf_cal),
    )

    return {
        "realized_return_pct": round(realized_return_pct, 6),
        "realized_r_multiple": _f(trade_outcome.get("realized_r_multiple")),
        "outcome_y_0_or_1": 1 if realized_return_pct > 0 else 0,
        "outcome_direction": _dir_to_text(a_dir),
        "evidence_score_delta": score_delta,
        "evidence_alignment_score": alignment,
        "evidence_confidence_calibrated": conf_cal,
        "evidence_downside_risk": downside,
        "evidence_route_decision": route_decision,
        "forecast_direction": _dir_to_text(f_dir),
        "actual_direction": _dir_to_text(a_dir),
        "direction_correct": direction_correct,
        "forecast_error_pct": (
            round(forecast_error_pct, 6) if forecast_error_pct is not None else None
        ),
        "evidence_helped": helped,
        "evidence_harmed": harmed,
        "false_confidence": false_conf,
        "risk_reducer_helped": risk_reducer,
        "calibration_bucket": bucket_id,
    }


def _evidence_helped(
    *,
    route_decision: str,
    score_delta: float,
    direction_correct: int,
    realized_return_pct: float,
) -> int:
    # A. supportive / positive evidence that called the direction on a winner
    if (
        route_decision in {"WATCH", "ACCEPTED", "ADVISORY_CONTEXT_ONLY"}
        and score_delta > 0
        and direction_correct == 1
        and realized_return_pct > 0
    ):
        return 1
    # B. risk reducer: negative evidence ahead of a loss
    if score_delta < 0 and realized_return_pct < 0:
        return 1
    # C. veto support: router rejected evidence and the trade lost / was avoided
    if route_decision == "REJECT" and realized_return_pct < 0:
        return 1
    return 0


def _evidence_harmed(*, score_delta: float, realized_return_pct: float) -> int:
    # A. positive evidence but a losing outcome
    if score_delta > 0 and realized_return_pct < 0:
        return 1
    # B. negative evidence that talked us out of a clear winner
    if score_delta < 0 and realized_return_pct > MISSED_OPPORTUNITY_THRESHOLD:
        return 1
    return 0


def _false_confidence(
    *,
    score_delta: float,
    confidence_calibrated: float | None,
    realized_return_pct: float,
) -> int:
    if (
        score_delta > 0
        and confidence_calibrated is not None
        and confidence_calibrated >= FALSE_CONFIDENCE_MIN
        and realized_return_pct < 0
    ):
        return 1
    return 0


def _bucket_id(
    *, source_name: str, evidence_type: str, route_decision: str, band: str
) -> str:
    return "|".join([source_name, evidence_type, route_decision, band])


def compute_bucket_weights(
    n: int, h: int, x: int, f: int
) -> dict[str, Any]:
    """Pure Section 8 weight math for a bucket with counts (n, h, x, f)."""
    denom = max(n, 1)
    help_rate = h / denom
    harm_rate = x / denom
    false_rate = f / denom
    raw_reliability = _clip(
        REL_BASE
        + REL_HELP_COEF * (help_rate - 0.50)
        - REL_HARM_COEF * harm_rate
        - REL_FALSE_COEF * false_rate,
        WEIGHT_FLOOR,
        WEIGHT_CEIL,
    )
    if n < 30:
        sample_multiplier = 0.50
    elif n < 50:
        sample_multiplier = 0.75
    else:
        sample_multiplier = 1.00
    advisory_weight = _clip(
        raw_reliability * sample_multiplier, WEIGHT_FLOOR, WEIGHT_CEIL
    )
    return {
        "help_rate": round(help_rate, 6),
        "harm_rate": round(harm_rate, 6),
        "false_confidence_rate": round(false_rate, 6),
        "raw_reliability": round(raw_reliability, 6),
        "sample_multiplier": sample_multiplier,
        "advisory_weight": round(advisory_weight, 6),
        # Real-money influence is structurally off in this sprint regardless
        # of sample size — the operator must explicitly approve later.
        "real_money_weight_allowed": 0,
        "real_money_sizing_impact": REAL_MONEY_SIZING_IMPACT,
    }


def _read_bucket(conn: sqlite3.Connection, bucket_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM external_evidence_calibration_buckets WHERE bucket_id=?",
        (bucket_id,),
    ).fetchone()
    return dict(row) if row else None


def update_calibration_bucket(
    conn: sqlite3.Connection,
    *,
    bucket_id: str,
    source_name: str,
    evidence_type: str,
    route_decision: str,
    confidence_band: str,
    helped: int,
    harmed: int,
    false_confidence: int,
) -> dict[str, Any]:
    """Increment a bucket's counts by one outcome and recompute its weight.

    Returns ``{pre_update_weight, post_update_weight, sample_count_before,
    sample_count_after}``.  ``real_money_weight_allowed`` stays 0 and
    ``real_money_sizing_impact`` stays PROHIBITED unconditionally.
    """
    existing = _read_bucket(conn, bucket_id)
    n0 = int((existing or {}).get("sample_count") or 0)
    h0 = int((existing or {}).get("help_count") or 0)
    x0 = int((existing or {}).get("harm_count") or 0)
    f0 = int((existing or {}).get("false_confidence_count") or 0)
    pre_weight = _f((existing or {}).get("advisory_weight"))
    if pre_weight is None:
        pre_weight = compute_bucket_weights(n0, h0, x0, f0)["advisory_weight"]

    n1 = n0 + 1
    h1 = h0 + (1 if helped else 0)
    x1 = x0 + (1 if harmed else 0)
    f1 = f0 + (1 if false_confidence else 0)
    weights = compute_bucket_weights(n1, h1, x1, f1)

    conn.execute(
        "INSERT INTO external_evidence_calibration_buckets"
        " (bucket_id, source_name, evidence_type, route_decision, confidence_band,"
        "  sample_count, help_count, harm_count, false_confidence_count,"
        "  help_rate, harm_rate, false_confidence_rate, raw_reliability,"
        "  sample_multiplier, advisory_weight, real_money_weight_allowed,"
        "  real_money_sizing_impact, last_updated_utc, proof_status)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(bucket_id) DO UPDATE SET"
        "  sample_count=excluded.sample_count,"
        "  help_count=excluded.help_count,"
        "  harm_count=excluded.harm_count,"
        "  false_confidence_count=excluded.false_confidence_count,"
        "  help_rate=excluded.help_rate,"
        "  harm_rate=excluded.harm_rate,"
        "  false_confidence_rate=excluded.false_confidence_rate,"
        "  raw_reliability=excluded.raw_reliability,"
        "  sample_multiplier=excluded.sample_multiplier,"
        "  advisory_weight=excluded.advisory_weight,"
        "  real_money_weight_allowed=excluded.real_money_weight_allowed,"
        "  real_money_sizing_impact=excluded.real_money_sizing_impact,"
        "  last_updated_utc=excluded.last_updated_utc,"
        "  proof_status=excluded.proof_status",
        (
            bucket_id, source_name, evidence_type, route_decision, confidence_band,
            n1, h1, x1, f1,
            weights["help_rate"], weights["harm_rate"],
            weights["false_confidence_rate"], weights["raw_reliability"],
            weights["sample_multiplier"], weights["advisory_weight"],
            0, REAL_MONEY_SIZING_IMPACT, utc_timestamp(),
            "ADVISORY_WEIGHT_PAPER_ONLY_NO_REAL_MONEY",
        ),
    )
    return {
        "pre_update_weight": pre_weight,
        "post_update_weight": weights["advisory_weight"],
        "sample_count_before": n0,
        "sample_count_after": n1,
    }


# ------------------------------------------------------------- outcome recording
def _is_closed(trade_outcome: dict[str, Any]) -> bool:
    if isinstance(trade_outcome.get("closed"), bool):
        return bool(trade_outcome["closed"])
    for key in ("status", "outcome_status", "outcome_event_type", "trade_state"):
        val = _s(trade_outcome.get(key)).upper()
        if val in _CLOSED_STATES:
            return True
        if val in _OPEN_STATES:
            return False
    return False


_OUTCOME_COLUMNS = (
    "learning_id", "snapshot_id", "signal_id", "trade_id", "ticker",
    "source_name", "evidence_type", "entry_timestamp_utc", "exit_timestamp_utc",
    "holding_days", "entry_price", "exit_price", "realized_return_pct",
    "realized_r_multiple", "outcome_y_0_or_1", "outcome_direction",
    "evidence_score_delta", "evidence_alignment_score",
    "evidence_confidence_calibrated", "evidence_downside_risk",
    "evidence_route_decision", "forecast_direction", "actual_direction",
    "direction_correct", "forecast_error_pct", "evidence_helped",
    "evidence_harmed", "false_confidence", "risk_reducer_helped",
    "calibration_bucket", "pre_update_weight", "post_update_weight",
    "sample_count_before", "sample_count_after", "advisory_only",
    "human_execution_required", "execution_gate", "broker_api_called",
    "ai_execution_count", "real_money_sizing_impact", "proof_status",
    "created_at_utc",
)


def _insert_outcome_row(conn: sqlite3.Connection, row: dict[str, Any]) -> bool:
    placeholders = ", ".join(["?"] * len(_OUTCOME_COLUMNS))
    cols = ", ".join(_OUTCOME_COLUMNS)
    vals = tuple(row.get(c) for c in _OUTCOME_COLUMNS)
    cur = conn.execute(
        f"INSERT OR IGNORE INTO external_evidence_outcomes ({cols})"
        f" VALUES ({placeholders})",
        vals,
    )
    return cur.rowcount > 0


def _result(
    *,
    status: str,
    records_created: int = 0,
    records_would_create: int = 0,
    records_skipped: int = 0,
    buckets_updated: int = 0,
    buckets_would_update: int = 0,
) -> dict[str, Any]:
    return {
        "status": status,
        "records_created": records_created,
        "records_would_create": records_would_create,
        "records_skipped": records_skipped,
        "buckets_updated": buckets_updated,
        "buckets_would_update": buckets_would_update,
        "real_money_sizing_impact": REAL_MONEY_SIZING_IMPACT,
        "proof_status": _PROOF[status],
        "advisory_only": True,
        "human_execution_required": True,
        "execution_gate": EXECUTION_GATE_LOCKED,
        "broker_api_called": False,
        "ai_execution_count": 0,
    }


def record_external_evidence_outcome_for_trade(
    trade_outcome: dict[str, Any],
    *,
    apply: bool = True,
    db_path: Path | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Link a closed trade outcome to its external-evidence snapshot(s).

    For each matching unlinked snapshot: compute learning metrics, insert one
    idempotent outcome record, mark the snapshot outcome-known, and update its
    calibration bucket.  ``apply=False`` performs a full dry-run (no writes).

    Returns a Section 9 summary.  Never raises — failures degrade to
    ``ERROR_SAFE``.  Real-money sizing is never affected.
    """
    trade = dict(trade_outcome or {})

    if not _is_closed(trade):
        return _result(status=STATUS_NOT_FINAL)

    entry_price = _f(trade.get("entry_price"))
    exit_price = _f(trade.get("exit_price"))
    if entry_price in (None, 0.0) or exit_price is None:
        return _result(status=STATUS_INSUFFICIENT)

    signal_id = _s(trade.get("signal_id"))
    ticker = _s(trade.get("ticker"))
    trade_id = _s(trade.get("trade_id"))
    exit_ts = _s(trade.get("exit_timestamp_utc")) or _s(trade.get("exit_at"))
    event_type = _s(trade.get("outcome_event_type")) or _s(
        trade.get("status")
    ) or "CLOSED"

    owned = conn is None
    try:
        if conn is None:
            conn = eep._open(db_path)
        else:
            eep.ensure_external_evidence_schema(conn)

        snapshots = eep.load_unlinked_external_evidence_for_trade(
            signal_id=signal_id, ticker=ticker, conn=conn
        )
        if not snapshots:
            return _result(status=STATUS_NO_MATCH)

        created = 0
        would_create = 0
        skipped = 0
        buckets_updated = 0
        now = utc_timestamp()

        for snap in snapshots:
            snapshot_id = _s(snap.get("snapshot_id"))
            learning_id = make_learning_id(
                snapshot_id=snapshot_id,
                trade_id=trade_id,
                exit_timestamp_utc=exit_ts,
                outcome_event_type=event_type,
            )
            already = conn.execute(
                "SELECT 1 FROM external_evidence_outcomes WHERE learning_id=? LIMIT 1",
                (learning_id,),
            ).fetchone()
            if already is not None:
                skipped += 1
                continue

            metrics = compute_outcome_metrics(snap, trade)
            would_create += 1
            if not apply:
                continue

            bucket = update_calibration_bucket(
                conn,
                bucket_id=metrics["calibration_bucket"],
                source_name=_s(snap.get("source_name")),
                evidence_type=_s(snap.get("evidence_type")),
                route_decision=metrics["evidence_route_decision"],
                confidence_band=confidence_band(
                    metrics["evidence_confidence_calibrated"]
                ),
                helped=metrics["evidence_helped"],
                harmed=metrics["evidence_harmed"],
                false_confidence=metrics["false_confidence"],
            )

            row = {
                "learning_id": learning_id,
                "snapshot_id": snapshot_id,
                "signal_id": _s(snap.get("signal_id")) or signal_id or None,
                "trade_id": trade_id or None,
                "ticker": (_s(snap.get("ticker")) or ticker or "").upper() or None,
                "source_name": _s(snap.get("source_name")),
                "evidence_type": _s(snap.get("evidence_type")),
                "entry_timestamp_utc": _s(trade.get("entry_timestamp_utc")) or None,
                "exit_timestamp_utc": exit_ts or None,
                "holding_days": trade.get("holding_days"),
                "entry_price": entry_price,
                "exit_price": exit_price,
                "realized_return_pct": metrics["realized_return_pct"],
                "realized_r_multiple": metrics["realized_r_multiple"],
                "outcome_y_0_or_1": metrics["outcome_y_0_or_1"],
                "outcome_direction": metrics["outcome_direction"],
                "evidence_score_delta": metrics["evidence_score_delta"],
                "evidence_alignment_score": metrics["evidence_alignment_score"],
                "evidence_confidence_calibrated": metrics[
                    "evidence_confidence_calibrated"
                ],
                "evidence_downside_risk": metrics["evidence_downside_risk"],
                "evidence_route_decision": metrics["evidence_route_decision"],
                "forecast_direction": metrics["forecast_direction"],
                "actual_direction": metrics["actual_direction"],
                "direction_correct": metrics["direction_correct"],
                "forecast_error_pct": metrics["forecast_error_pct"],
                "evidence_helped": metrics["evidence_helped"],
                "evidence_harmed": metrics["evidence_harmed"],
                "false_confidence": metrics["false_confidence"],
                "risk_reducer_helped": metrics["risk_reducer_helped"],
                "calibration_bucket": metrics["calibration_bucket"],
                "pre_update_weight": bucket["pre_update_weight"],
                "post_update_weight": bucket["post_update_weight"],
                "sample_count_before": bucket["sample_count_before"],
                "sample_count_after": bucket["sample_count_after"],
                "advisory_only": 1,
                "human_execution_required": 1,
                "execution_gate": EXECUTION_GATE_LOCKED,
                "broker_api_called": 0,
                "ai_execution_count": 0,
                "real_money_sizing_impact": REAL_MONEY_SIZING_IMPACT,
                "proof_status": "OUTCOME_RECORDED_ADVISORY_ONLY",
                "created_at_utc": now,
            }
            if _insert_outcome_row(conn, row):
                created += 1
                buckets_updated += 1
                eep.mark_external_evidence_outcome_known(
                    snapshot_id,
                    {
                        "outcome_trade_id": trade_id,
                        "outcome_event_type": event_type,
                        "outcome_realized_return_pct": metrics["realized_return_pct"],
                        "outcome_direction": metrics["outcome_direction"],
                        "outcome_holding_days": trade.get("holding_days"),
                        "outcome_linked_at_utc": now,
                    },
                    conn=conn,
                )

        if apply:
            conn.commit()
    except Exception:  # noqa: BLE001 - learning failure is failed-safe
        return _result(status=STATUS_ERROR_SAFE)
    finally:
        if conn is not None and owned:
            try:
                conn.close()
            except Exception:  # pragma: no cover - defensive
                pass

    return _result(
        status=STATUS_RECORDED,
        records_created=created,
        records_would_create=would_create,
        records_skipped=skipped,
        buckets_updated=buckets_updated,
        buckets_would_update=would_create,
    )


__all__ = [
    "THETA_ACTUAL",
    "THETA_FORECAST",
    "THETA_ALIGNMENT",
    "MISSED_OPPORTUNITY_THRESHOLD",
    "confidence_band",
    "actual_direction",
    "forecast_direction",
    "make_learning_id",
    "compute_outcome_metrics",
    "compute_bucket_weights",
    "update_calibration_bucket",
    "record_external_evidence_outcome_for_trade",
    "REAL_MONEY_SIZING_IMPACT",
    "STATUS_RECORDED",
    "STATUS_NO_MATCH",
    "STATUS_NOT_FINAL",
    "STATUS_INSUFFICIENT",
    "STATUS_ERROR_SAFE",
]
