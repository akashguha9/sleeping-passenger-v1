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


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(_CREATE_SQL)
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
    "build_decision_snapshot",
    "persist_decision_snapshot",
    "record_decision_probability",
    "count_valid_p",
    "calibration_corpus_status",
]
