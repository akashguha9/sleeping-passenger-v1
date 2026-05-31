"""Objective 5 — snapshot model_probability at decision time (additive).

The calibration corpus could never grow ``n_valid_p`` because no advisory
decision persisted a ``model_probability`` *at the moment of decision*.  This
module fixes the plumbing — it does NOT claim calibration.

It is deliberately ISOLATED: it writes to its own additive
``decision_probability_snapshots`` table (CREATE TABLE IF NOT EXISTS) and
reuses the existing, tested probability math in
:mod:`scripts.probability_snapshot`.  Nothing in the heavily-tested
``calibration_report`` path is modified.

Each decision snapshot carries the fields a calibration dataset needs:

    signal_id, trade_id, timestamp_utc, ticker, country, signal_class,
    prediction_horizon_days, target_event_definition, model_probability,
    score_vector (EMS/EQS/DS/LS/EFS/APS), model_version, scoring_version,
    market_regime, advisory_only / human_execution_required / execution_gate

The calibration gate stays honest:

    CalibrationAllowed = I(N >= 200) · I(Brier <= 0.25) · I(ECE <= 0.10)

Until ``n_valid_p >= 200`` (and the Brier/ECE thresholds are met once outcomes
exist), ``calibration_status = INSUFFICIENT_EVIDENCE`` and
``predictive_claim_allowed = false``.  This module never sets either to a
predictive-positive value on its own.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

try:
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.probability_snapshot import (
        FORMULA_VERSION,
        build_probability_snapshot,
    )
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]
    from probability_snapshot import (  # type: ignore[no-redef]
        FORMULA_VERSION,
        build_probability_snapshot,
    )

TABLE = "decision_probability_snapshots"

# Calibration gate constants (mirrors calibration_report defaults).
N_MIN: int = 200
BRIER_THRESHOLD: float = 0.25
ECE_THRESHOLD: float = 0.10

MODEL_VERSION: str = "advisory-logistic-v1"
SCORING_VERSION: str = FORMULA_VERSION
DEFAULT_TARGET_EVENT = "manual_trade_reconciliation_win_loss"

_CREATE_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    snapshot_id            TEXT PRIMARY KEY,
    signal_id              TEXT NOT NULL,
    trade_id               TEXT,
    timestamp_utc          TEXT NOT NULL,
    ticker                 TEXT,
    country                TEXT,
    signal_class           TEXT,
    market_regime          TEXT,
    prediction_horizon_days REAL,
    target_event_definition TEXT,
    model_probability      REAL,
    model_probability_reason TEXT,
    score_vector_json      TEXT,
    model_version          TEXT,
    scoring_version        TEXT,
    advisory_status        TEXT NOT NULL DEFAULT 'ADVISORY_ONLY',
    execution_gate         TEXT NOT NULL DEFAULT 'LOCKED',
    human_execution_required INTEGER NOT NULL DEFAULT 1,
    outcome_label          INTEGER,
    outcome_timestamp_utc  TEXT
)
"""


# Additive forward-snapshot-contract columns (Phase 5).  All nullable so old
# snapshots stay readable and simply remain forward-ineligible.
_FORWARD_COLUMNS: dict[str, str] = {
    "target_return_threshold": "REAL",
    "target_source": "TEXT",
    "entry_price": "REAL",
    "entry_price_timestamp_utc": "TEXT",
    "entry_price_source": "TEXT",
    "horizon_close_utc": "TEXT",
    "forward_outcome_eligible": "INTEGER",
    "forward_outcome_unavailable_reason": "TEXT",
}


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(_CREATE_SQL)
    conn.commit()


def ensure_forward_columns(conn: sqlite3.Connection) -> None:
    """Add the nullable forward-snapshot-contract columns if absent.

    Safe runtime migration (``ALTER TABLE ... ADD COLUMN`` only) — never drops or
    rewrites a column, so existing snapshots remain fully readable.
    """
    ensure_schema(conn)
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({TABLE})")}
    for col, decl in _FORWARD_COLUMNS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE {TABLE} ADD COLUMN {col} {decl}")
    conn.commit()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_decision_snapshot(
    *,
    signal_id: str,
    axes: Mapping[str, Any] | None = None,
    trade_id: str | None = None,
    ticker: str | None = None,
    country: str | None = None,
    signal_class: str | None = None,
    market_regime: str | None = None,
    prediction_horizon_days: float | None = None,
    target_event_definition: str = DEFAULT_TARGET_EVENT,
    chaos_risk: Any = 0.0,
    staleness_penalty: Any = 0.0,
    mock_penalty: Any = 0.0,
    timestamp_utc: str | None = None,
) -> dict[str, Any]:
    """Build a decision snapshot dict with a model_probability in [0, 1].

    If ``axes`` is None/empty, ``model_probability`` is left ``None`` with an
    explicit reason — we never fabricate a probability.
    """
    stamps = advisory_safety_stamps()
    ts = timestamp_utc or _utc_now_iso()
    axes_map = dict(axes or {})

    if not axes_map:
        model_probability: float | None = None
        reason = "NO_SCORE_VECTOR_AT_DECISION"
        score_vector: dict[str, float] = {}
    else:
        snap = build_probability_snapshot(
            signal_id=signal_id,
            axes=axes_map,
            chaos_risk=chaos_risk,
            staleness_penalty=staleness_penalty,
            mock_penalty=mock_penalty,
            generated_at_utc=ts,
        )
        model_probability = float(snap.model_probability)
        reason = "OK"
        score_vector = {
            "EMS": snap.EMS, "EQS": snap.EQS, "DS": snap.DS,
            "LS": snap.LS, "EFS": snap.EFS, "APS": snap.APS,
        }

    snapshot_id = f"DPS_{signal_id}_{ts}".replace(" ", "_")
    return {
        "snapshot_id": snapshot_id,
        "signal_id": str(signal_id),
        "trade_id": trade_id,
        "timestamp_utc": ts,
        "ticker": ticker,
        "country": country,
        "signal_class": signal_class,
        "market_regime": market_regime,
        "prediction_horizon_days": prediction_horizon_days,
        "target_event_definition": target_event_definition,
        "model_probability": model_probability,
        "model_probability_reason": reason,
        "score_vector": score_vector,
        "model_version": MODEL_VERSION,
        "scoring_version": SCORING_VERSION,
        # Advisory-only invariants.
        "advisory_status": stamps.get("advisory_status", "ADVISORY_ONLY"),
        "execution_gate": stamps["execution_gate"],
        "broker_api_called": stamps["broker_api_called"],
        "ai_execution_count": stamps["ai_execution_count"],
        "human_execution_required": True,
    }


def persist_decision_snapshot(
    snapshot: Mapping[str, Any],
    db_path: str | Path,
) -> dict[str, Any]:
    """Insert (idempotent on snapshot_id) a decision snapshot.  Additive."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        ensure_schema(conn)
        conn.execute(
            f"INSERT OR IGNORE INTO {TABLE} ("
            " snapshot_id, signal_id, trade_id, timestamp_utc, ticker, country,"
            " signal_class, market_regime, prediction_horizon_days,"
            " target_event_definition, model_probability,"
            " model_probability_reason, score_vector_json, model_version,"
            " scoring_version, advisory_status, execution_gate,"
            " human_execution_required"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                snapshot["snapshot_id"], snapshot["signal_id"],
                snapshot.get("trade_id"), snapshot["timestamp_utc"],
                snapshot.get("ticker"), snapshot.get("country"),
                snapshot.get("signal_class"), snapshot.get("market_regime"),
                snapshot.get("prediction_horizon_days"),
                snapshot.get("target_event_definition"),
                snapshot.get("model_probability"),
                snapshot.get("model_probability_reason"),
                json.dumps(snapshot.get("score_vector") or {}),
                snapshot.get("model_version"), snapshot.get("scoring_version"),
                "ADVISORY_ONLY", "LOCKED", 1,
            ),
        )
        conn.commit()
        return {"persisted": True, "snapshot_id": snapshot["snapshot_id"]}
    finally:
        conn.close()


def record_decision_probability(
    *,
    db_path: str | Path,
    signal_id: str,
    axes: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Build + persist a decision snapshot in one call.  Returns the snapshot."""
    snap = build_decision_snapshot(signal_id=signal_id, axes=axes, **kwargs)
    persist_decision_snapshot(snap, db_path)
    return snap


def stamp_forward_contract(
    db_path: str | Path,
    snapshot_id: str,
    *,
    entry_price: float | None = None,
    entry_price_timestamp_utc: str | None = None,
    entry_price_source: str | None = None,
    target_return_threshold: float | None = None,
    target_source: str | None = None,
    prediction_horizon_days: float | None = None,
    target_event_definition: str | None = None,
    ticker: str | None = None,
) -> dict[str, Any]:
    """Stamp forward-contract fields onto an existing snapshot and recompute
    its ``forward_outcome_eligible`` flag + unavailable reason.

    Reads the snapshot's persisted ticker / probability / horizon / target /
    decision-timestamp, combines them with the (optional) entry-price evidence,
    and evaluates :func:`forward_snapshot_contract.forward_outcome_eligible`.  It
    NEVER fabricates a price — a missing entry price simply yields
    ``forward_outcome_eligible = 0`` with reason ``MISSING_ENTRY_PRICE``.  The
    advisory-only stamps on the row are left untouched.
    """
    try:
        from scripts.forward_snapshot_contract import (
            DEFAULT_TARGET_RETURN_THRESHOLD,
            TARGET_SOURCE,
            forward_outcome_eligible,
            horizon_close_utc,
        )
    except ModuleNotFoundError:  # pragma: no cover - flat-layout fallback
        from forward_snapshot_contract import (  # type: ignore[no-redef]
            DEFAULT_TARGET_RETURN_THRESHOLD,
            TARGET_SOURCE,
            forward_outcome_eligible,
            horizon_close_utc,
        )

    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        ensure_forward_columns(conn)
        row = conn.execute(
            f"SELECT ticker, timestamp_utc, model_probability,"
            f" prediction_horizon_days, target_event_definition FROM {TABLE}"
            " WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        if row is None:
            return {"stamped": False, "reason": "SNAPSHOT_NOT_FOUND"}

        eff_ticker = ticker if ticker is not None else row["ticker"]
        eff_horizon = (
            prediction_horizon_days
            if prediction_horizon_days is not None
            else row["prediction_horizon_days"]
        )
        eff_target = (
            target_event_definition
            if target_event_definition is not None
            else row["target_event_definition"]
        )
        threshold = (
            float(target_return_threshold)
            if target_return_threshold is not None
            else DEFAULT_TARGET_RETURN_THRESHOLD
        )
        source = target_source if target_source is not None else TARGET_SOURCE
        close_utc = horizon_close_utc(row["timestamp_utc"], eff_horizon)

        eligible, reason = forward_outcome_eligible(
            ticker=eff_ticker,
            model_probability=row["model_probability"],
            prediction_horizon_days=eff_horizon,
            target_event_definition=eff_target,
            entry_price=entry_price,
            entry_price_timestamp_utc=entry_price_timestamp_utc,
            decision_timestamp_utc=row["timestamp_utc"],
            is_real_forward=True,
            advisory_status="ADVISORY_ONLY",
            execution_gate="LOCKED",
        )

        conn.execute(
            f"UPDATE {TABLE} SET"
            "  entry_price = ?,"
            "  entry_price_timestamp_utc = ?,"
            "  entry_price_source = ?,"
            "  target_return_threshold = ?,"
            "  target_source = ?,"
            "  horizon_close_utc = ?,"
            "  forward_outcome_eligible = ?,"
            "  forward_outcome_unavailable_reason = ?"
            " WHERE snapshot_id = ?",
            (
                float(entry_price) if entry_price is not None else None,
                entry_price_timestamp_utc,
                entry_price_source,
                threshold,
                source,
                close_utc,
                1 if eligible else 0,
                None if eligible else reason,
                snapshot_id,
            ),
        )
        conn.commit()
        return {
            "stamped": True,
            "snapshot_id": snapshot_id,
            "forward_outcome_eligible": bool(eligible),
            "forward_outcome_unavailable_reason": None if eligible else reason,
            "entry_price": float(entry_price) if entry_price is not None else None,
            "horizon_close_utc": close_utc,
        }
    finally:
        conn.close()


def forward_outcome_counts(db_path: str | Path, *, now_utc: str | None = None) -> dict[str, Any]:
    """Honest tally of forward-eligible / ineligible / due / pending snapshots.

    ``n_due_forward``  = eligible AND horizon elapsed AND not yet labelled.
    ``n_pending_horizon`` = eligible AND horizon NOT elapsed AND not yet labelled.
    """
    from datetime import datetime, timezone

    try:
        from scripts.attach_due_outcomes import horizon_elapsed
    except ModuleNotFoundError:  # pragma: no cover - flat-layout fallback
        from attach_due_outcomes import horizon_elapsed  # type: ignore[no-redef]

    now_dt = datetime.now(timezone.utc)
    if now_utc:
        try:
            parsed = datetime.fromisoformat(str(now_utc).replace("Z", "+00:00"))
            now_dt = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        ensure_forward_columns(conn)
        rows = conn.execute(
            f"SELECT forward_outcome_eligible, forward_outcome_unavailable_reason,"
            f" entry_price, timestamp_utc, prediction_horizon_days, outcome_label"
            f" FROM {TABLE}"
        ).fetchall()
    finally:
        conn.close()

    eligible = 0
    ineligible = 0
    entry_price_present = 0
    due_forward = 0
    pending_horizon = 0
    reasons: dict[str, int] = {}
    for r in rows:
        if int(r["forward_outcome_eligible"] or 0) == 1:
            eligible += 1
            if r["outcome_label"] is None:
                if horizon_elapsed(
                    decision_ts=r["timestamp_utc"],
                    horizon_days=r["prediction_horizon_days"],
                    now_utc=now_dt,
                ):
                    due_forward += 1
                else:
                    pending_horizon += 1
        else:
            ineligible += 1
            key = r["forward_outcome_unavailable_reason"] or "UNSPECIFIED"
            reasons[key] = reasons.get(key, 0) + 1
        if r["entry_price"] is not None:
            entry_price_present += 1
    return {
        "n_forward_outcome_eligible": eligible,
        "n_forward_outcome_ineligible": ineligible,
        "n_due_forward": due_forward,
        "n_pending_horizon": pending_horizon,
        "entry_price_present_count": entry_price_present,
        "forward_outcome_unavailable_reasons": reasons,
    }


def count_valid_p(db_path: str | Path) -> int:
    """Number of decision snapshots carrying a usable model_probability."""
    conn = sqlite3.connect(str(db_path))
    try:
        ensure_schema(conn)
        return int(
            conn.execute(
                f"SELECT COUNT(*) FROM {TABLE}"
                " WHERE model_probability IS NOT NULL"
                " AND model_probability >= 0.0 AND model_probability <= 1.0"
            ).fetchone()[0]
        )
    finally:
        conn.close()


def calibration_corpus_status(
    db_path: str | Path,
    *,
    n_min: int = N_MIN,
) -> dict[str, Any]:
    """Honest corpus status.  predictive_claim_allowed stays False until the
    sample-size AND Brier/ECE gates are all satisfied (outcomes required)."""
    n_valid_p = count_valid_p(db_path)
    # Outcomes (and therefore Brier/ECE) are not computed here — so the gate
    # can NEVER be unlocked by this module alone.
    calibration_allowed = False
    status = (
        "INSUFFICIENT_EVIDENCE"
        if n_valid_p < n_min
        else "PENDING_OUTCOME_LABELS"
    )
    return {
        "n_valid_p": n_valid_p,
        "n_min": n_min,
        "brier_threshold": BRIER_THRESHOLD,
        "ece_threshold": ECE_THRESHOLD,
        "calibration_status": status,
        "predictive_claim_allowed": calibration_allowed,
        "advisory_status": "ADVISORY_ONLY",
        "execution_gate": "LOCKED",
    }


__all__ = [
    "TABLE",
    "N_MIN",
    "MODEL_VERSION",
    "SCORING_VERSION",
    "DEFAULT_TARGET_EVENT",
    "ensure_schema",
    "ensure_forward_columns",
    "stamp_forward_contract",
    "forward_outcome_counts",
    "build_decision_snapshot",
    "persist_decision_snapshot",
    "record_decision_probability",
    "count_valid_p",
    "calibration_corpus_status",
]
