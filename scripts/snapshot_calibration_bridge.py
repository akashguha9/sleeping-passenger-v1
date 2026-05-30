"""Phase 8 — Brier/ECE over decision snapshots + realized outcomes.

This does NOT claim calibration.  It starts the evidence pipeline: it pairs the
``model_probability`` persisted at decision time (``decision_probability_
snapshots``) with the realized binary ``outcome_label`` recorded after the
prediction horizon / reconciliation, then computes Brier / ECE / LogLoss / MCE
by *reusing* the audited primitives in :mod:`scripts.calibration_report`.

Calibration gate (honest)::

    CalibrationAllowed = I(N >= 200) · I(Brier <= 0.25) · I(ECE <= 0.10)

With today's corpus (N is ~0), ``calibration_status`` is
``INSUFFICIENT_EVIDENCE`` and ``predictive_claim_allowed`` is ``False``.  This
module can never flip the gate true on its own — the thresholds are real.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # pragma: no cover - exercised both ways
    from scripts.calibration_report import (
        DEFAULT_BS_THRESHOLD,
        DEFAULT_ECE_THRESHOLD,
        DEFAULT_N_MIN,
        Observation,
        brier_score,
        classify_n_real_status,
        expected_calibration_error,
        log_loss,
        maximum_calibration_error,
    )
    from scripts.decision_probability_snapshot import TABLE, ensure_schema
except ModuleNotFoundError:  # pragma: no cover - flat-layout fallback
    from calibration_report import (  # type: ignore[no-redef]
        DEFAULT_BS_THRESHOLD,
        DEFAULT_ECE_THRESHOLD,
        DEFAULT_N_MIN,
        Observation,
        brier_score,
        classify_n_real_status,
        expected_calibration_error,
        log_loss,
        maximum_calibration_error,
    )
    from decision_probability_snapshot import TABLE, ensure_schema  # type: ignore[no-redef]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def attach_outcome(
    db_path: str | Path,
    snapshot_id: str,
    outcome_label: int,
    *,
    outcome_timestamp_utc: str | None = None,
) -> dict[str, Any]:
    """Label a persisted decision snapshot with its realized binary outcome.

    ``outcome_label`` must be 0 or 1; anything else is rejected (we never
    fabricate an outcome).  Additive UPDATE on the existing snapshot row.
    """
    if outcome_label not in (0, 1):
        return {"updated": False, "reason": "OUTCOME_LABEL_MUST_BE_0_OR_1"}
    conn = sqlite3.connect(str(db_path))
    try:
        ensure_schema(conn)
        cur = conn.execute(
            f"UPDATE {TABLE} SET outcome_label = ?, outcome_timestamp_utc = ?"
            " WHERE snapshot_id = ?",
            (int(outcome_label), outcome_timestamp_utc or _utc_now_iso(), snapshot_id),
        )
        conn.commit()
        return {"updated": cur.rowcount > 0, "snapshot_id": snapshot_id}
    finally:
        conn.close()


def build_calibration_dataset_from_snapshots_and_outcomes(
    db_path: str | Path,
) -> dict[str, Any]:
    """Build ``D = {(p_i, y_i)}`` from snapshots that carry BOTH a usable
    probability and a realized outcome label.

    Returns the dataset plus honest accounting of what was excluded and why —
    we never silently drop rows.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        ensure_schema(conn)
        rows = conn.execute(
            f"SELECT model_probability, outcome_label FROM {TABLE}"
        ).fetchall()
    finally:
        conn.close()

    dataset: list[dict[str, Any]] = []
    n_total = len(rows)
    n_missing_probability = 0
    n_missing_outcome = 0
    n_invalid = 0
    for p, y in rows:
        if p is None:
            n_missing_probability += 1
            continue
        if y is None:
            n_missing_outcome += 1
            continue
        obs = Observation.from_raw({"p": p, "y": y})
        if obs is None:
            n_invalid += 1
            continue
        dataset.append({"p": obs.p, "y": obs.y})

    return {
        "dataset": dataset,
        "n_total_snapshots": n_total,
        "n_pairs": len(dataset),
        "n_missing_probability": n_missing_probability,
        "n_missing_outcome": n_missing_outcome,
        "n_invalid_excluded": n_invalid,
        "exclusion_reasons": {
            "missing_probability": "model_probability IS NULL",
            "missing_outcome": "outcome_label IS NULL (PENDING_OUTCOME_LABELS)",
            "invalid": "probability not finite in [0,1] or outcome not in {0,1}",
        },
    }


def compute_brier_ece(
    dataset: list[dict[str, Any]],
    *,
    n_min: int = DEFAULT_N_MIN,
    bs_threshold: float = DEFAULT_BS_THRESHOLD,
    ece_threshold: float = DEFAULT_ECE_THRESHOLD,
    n_buckets: int = 10,
) -> dict[str, Any]:
    """Compute Brier / ECE / LogLoss / MCE for a ``[{p, y}]`` dataset.

    Empty dataset -> all metrics ``None`` and INSUFFICIENT_EVIDENCE.  The gate
    is True ONLY when N>=n_min AND Brier<=threshold AND ECE<=threshold.
    """
    observations = [
        o for o in (Observation.from_raw(r) for r in dataset) if o is not None
    ]
    n = len(observations)
    if n == 0:
        return {
            "n": 0,
            "brier": None,
            "ece": None,
            "log_loss": None,
            "mce": None,
            "n_min": n_min,
            "brier_threshold": bs_threshold,
            "ece_threshold": ece_threshold,
            "calibration_status": "INSUFFICIENT_EVIDENCE",
            "predictive_claim_allowed": False,
        }

    bs = brier_score(observations)
    ece = expected_calibration_error(observations, n_buckets=n_buckets)
    ll = log_loss(observations)
    mce = maximum_calibration_error(observations, n_buckets=n_buckets)

    n_ok = n >= n_min
    bs_ok = bs <= bs_threshold
    ece_ok = ece <= ece_threshold
    predictive_claim_allowed = bool(n_ok and bs_ok and ece_ok)
    # Below the sample-size floor we report the warning tier honestly; the gate
    # stays locked regardless of how good a tiny sample looks.
    calibration_status = (
        "MEASURED" if predictive_claim_allowed else classify_n_real_status(n)
    )

    return {
        "n": n,
        "brier": round(bs, 6),
        "ece": round(ece, 6),
        "log_loss": round(ll, 6),
        "mce": round(mce, 6),
        "n_min": n_min,
        "brier_threshold": bs_threshold,
        "ece_threshold": ece_threshold,
        "n_satisfies_min": n_ok,
        "brier_satisfies_threshold": bs_ok,
        "ece_satisfies_threshold": ece_ok,
        "calibration_status": calibration_status,
        "predictive_claim_allowed": predictive_claim_allowed,
    }


def build_snapshot_calibration_report(
    db_path: str | Path,
    *,
    n_min: int = DEFAULT_N_MIN,
) -> dict[str, Any]:
    """One-call report: dataset accounting + metrics + advisory stamps."""
    built = build_calibration_dataset_from_snapshots_and_outcomes(db_path)
    metrics = compute_brier_ece(built["dataset"], n_min=n_min)
    return {
        **metrics,
        "corpus": {
            "n_total_snapshots": built["n_total_snapshots"],
            "n_pairs": built["n_pairs"],
            "n_missing_probability": built["n_missing_probability"],
            "n_missing_outcome": built["n_missing_outcome"],
            "n_invalid_excluded": built["n_invalid_excluded"],
        },
        "advisory_status": "ADVISORY_ONLY",
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "ai_execution_count": 0,
    }


__all__ = [
    "attach_outcome",
    "build_calibration_dataset_from_snapshots_and_outcomes",
    "compute_brier_ece",
    "build_snapshot_calibration_report",
]
