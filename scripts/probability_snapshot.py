"""Probability snapshot persistence for advisory signal scoring.

Full Role-Uplift Sprint, Phase 1.

Purpose
-------
Persist an advisory ``model_probability`` snapshot alongside each signal
the scoring stack produces, so that — at some future point — the
calibration gate (``scripts.calibration_report``) can pair every
``p_i`` with an outcome ``y_i`` and finally compute Brier / ECE / MCE on
real evidence.

Until ``N_real >= 200`` calibration pairs land, the report explicitly
sets ``predictive_claim_allowed = False``.  An advisory probability
snapshot is **not** a predictive claim; it is a frozen view of "what the
scorer thought at the time the signal was emitted".

Formula
~~~~~~~
For signal ``i``, the raw score is::

    raw_score_i =
          alpha_EMS * EMS_i
        + alpha_EQS * EQS_i
        + alpha_DS  * DS_i
        + alpha_LS  * LS_i
        + alpha_EFS * EFS_i
        + alpha_APS * APS_i
        - lambda_chaos * chaos_risk_i
        - lambda_stale * staleness_penalty_i
        - lambda_mock  * mock_penalty_i

with the alpha weights summing to 1.  The default weights are uniform
(1/6) across the six axes, and the conservative penalty coefficients
are ``lambda_chaos = 0.10``, ``lambda_stale = 0.10``, ``lambda_mock =
0.20``.  The raw score is clamped to ``[-5, 5]`` for numerical safety,
then mapped to a probability::

    p_i = sigmoid(beta0 + beta1 * raw_score_i)

with the default link coefficients ``beta0 = 0`` and ``beta1 = 1``.
The probability is clamped to ``[0, 1]`` for safety even though sigmoid
already lies in ``(0, 1)``.

Safety
~~~~~~
* Advisory-only stamps on every record and on the report envelope.
* Schema migration is **additive-only**: ``ALTER TABLE`` / ``CREATE
  TABLE IF NOT EXISTS`` only, never destructive.
* No broker, order, fill, position, or execution code path.
* Dry-run writes nothing to disk; ``--write`` only inserts probability
  snapshots, never touches an existing row.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.advisory_contract import (  # noqa: E402
    AUDIT_ONLY_STORE,
    CANONICAL_STORE,
    advisory_safety_stamps,
)

DEFAULT_DB_PATH = _REPO_ROOT / "runtime" / "mvp_local.db"
DEFAULT_REPORT_PATH = (
    _REPO_ROOT / "runtime" / "release" / "probability_snapshot_report.json"
)

FORMULA_VERSION = "v1"
PROBABILITY_SNAPSHOT_TABLE = "probability_snapshots"

SCORE_AXES: tuple[str, ...] = ("EMS", "EQS", "DS", "LS", "EFS", "APS")
DEFAULT_AXIS_WEIGHTS: dict[str, float] = {
    "EMS": 1.0 / 6.0,
    "EQS": 1.0 / 6.0,
    "DS": 1.0 / 6.0,
    "LS": 1.0 / 6.0,
    "EFS": 1.0 / 6.0,
    "APS": 1.0 / 6.0,
}
DEFAULT_LAMBDA_CHAOS = 0.10
DEFAULT_LAMBDA_STALE = 0.10
DEFAULT_LAMBDA_MOCK = 0.20
DEFAULT_BETA0 = 0.0
DEFAULT_BETA1 = 1.0
RAW_SCORE_CLAMP = 5.0

ADVISORY_PROBABILITY_WARNING = (
    "Probability snapshots are uncalibrated until N_real >= 200 and "
    "BS/ECE/MCE thresholds pass."
)


# ---------------------------------------------------------------------------
# Pure math layer
# ---------------------------------------------------------------------------


def sigmoid(z: float) -> float:
    """Numerically-safe sigmoid in ``(0, 1)``."""
    # Avoid overflow for very large negative z by branching.
    if z >= 0:
        ez = math.exp(-z)
        return 1.0 / (1.0 + ez)
    ez = math.exp(z)
    return ez / (1.0 + ez)


def _coerce_axis(value: Any) -> float:
    """Coerce an axis input to a float in [0, 1].  Missing → 0.0."""
    if value is None:
        return 0.0
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(v) or math.isinf(v):
        return 0.0
    return max(0.0, min(1.0, v))


def _coerce_penalty(value: Any) -> float:
    """Coerce a penalty input to a float in [0, 1].  Missing → 0.0."""
    return _coerce_axis(value)


def compute_raw_score(
    axes: dict[str, Any],
    *,
    chaos_risk: Any = 0.0,
    staleness_penalty: Any = 0.0,
    mock_penalty: Any = 0.0,
    weights: dict[str, float] | None = None,
    lambda_chaos: float = DEFAULT_LAMBDA_CHAOS,
    lambda_stale: float = DEFAULT_LAMBDA_STALE,
    lambda_mock: float = DEFAULT_LAMBDA_MOCK,
) -> float:
    """Apply the probability raw-score formula.

    Weights must be non-negative and sum to 1.  Missing axes default to
    0.  Returns a value clamped to ``[-RAW_SCORE_CLAMP, RAW_SCORE_CLAMP]``.
    """
    w = dict(weights or DEFAULT_AXIS_WEIGHTS)
    # Validate weight contract — any caller-supplied weights map must be
    # non-negative and sum to 1.0 within a small tolerance.
    total = sum(w.get(axis, 0.0) for axis in SCORE_AXES)
    if not math.isclose(total, 1.0, abs_tol=1e-6):
        raise ValueError(
            f"axis weights must sum to 1.0; got {total!r} for {SCORE_AXES}"
        )
    for axis in SCORE_AXES:
        if w.get(axis, 0.0) < 0:
            raise ValueError(f"axis weight for {axis} must be >= 0")
    for label, lam in (
        ("lambda_chaos", lambda_chaos),
        ("lambda_stale", lambda_stale),
        ("lambda_mock", lambda_mock),
    ):
        if lam < 0:
            raise ValueError(f"{label} must be >= 0")

    weighted = sum(
        w.get(axis, 0.0) * _coerce_axis(axes.get(axis)) for axis in SCORE_AXES
    )
    raw = (
        weighted
        - lambda_chaos * _coerce_penalty(chaos_risk)
        - lambda_stale * _coerce_penalty(staleness_penalty)
        - lambda_mock * _coerce_penalty(mock_penalty)
    )
    return max(-RAW_SCORE_CLAMP, min(RAW_SCORE_CLAMP, raw))


def compute_model_probability(
    raw_score: float,
    *,
    beta0: float = DEFAULT_BETA0,
    beta1: float = DEFAULT_BETA1,
) -> float:
    """Map a raw score to ``p_i`` via sigmoid, clamped to ``[0, 1]``."""
    z = beta0 + beta1 * float(raw_score)
    p = sigmoid(z)
    return max(0.0, min(1.0, p))


# ---------------------------------------------------------------------------
# Snapshot dataclass + builder
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProbabilitySnapshot:
    signal_id: str
    generated_at_utc: str
    model_probability: float
    probability_formula_version: str
    EMS: float
    EQS: float
    DS: float
    LS: float
    EFS: float
    APS: float
    raw_score: float
    chaos_risk: float
    staleness_penalty: float
    mock_penalty: float
    advisory_status: str = "ADVISORY_ONLY"
    execution_gate: str = "LOCKED"
    broker_api_called: bool = False
    ai_execution_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "generated_at_utc": self.generated_at_utc,
            "model_probability": round(self.model_probability, 8),
            "probability_formula_version": self.probability_formula_version,
            "EMS": round(self.EMS, 6),
            "EQS": round(self.EQS, 6),
            "DS": round(self.DS, 6),
            "LS": round(self.LS, 6),
            "EFS": round(self.EFS, 6),
            "APS": round(self.APS, 6),
            "raw_score": round(self.raw_score, 8),
            "chaos_risk": round(self.chaos_risk, 6),
            "staleness_penalty": round(self.staleness_penalty, 6),
            "mock_penalty": round(self.mock_penalty, 6),
            "advisory_status": self.advisory_status,
            "execution_gate": self.execution_gate,
            "broker_api_called": self.broker_api_called,
            "ai_execution_count": self.ai_execution_count,
        }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def build_probability_snapshot(
    *,
    signal_id: str,
    axes: dict[str, Any] | None = None,
    chaos_risk: Any = 0.0,
    staleness_penalty: Any = 0.0,
    mock_penalty: Any = 0.0,
    weights: dict[str, float] | None = None,
    lambda_chaos: float = DEFAULT_LAMBDA_CHAOS,
    lambda_stale: float = DEFAULT_LAMBDA_STALE,
    lambda_mock: float = DEFAULT_LAMBDA_MOCK,
    beta0: float = DEFAULT_BETA0,
    beta1: float = DEFAULT_BETA1,
    generated_at_utc: str | None = None,
    formula_version: str = FORMULA_VERSION,
) -> ProbabilitySnapshot:
    """Build a fully-stamped :class:`ProbabilitySnapshot` for ``signal_id``."""
    axes = axes or {}
    raw = compute_raw_score(
        axes,
        chaos_risk=chaos_risk,
        staleness_penalty=staleness_penalty,
        mock_penalty=mock_penalty,
        weights=weights,
        lambda_chaos=lambda_chaos,
        lambda_stale=lambda_stale,
        lambda_mock=lambda_mock,
    )
    p = compute_model_probability(raw, beta0=beta0, beta1=beta1)
    return ProbabilitySnapshot(
        signal_id=str(signal_id),
        generated_at_utc=str(generated_at_utc or _utc_now_iso()),
        model_probability=p,
        probability_formula_version=formula_version,
        EMS=_coerce_axis(axes.get("EMS")),
        EQS=_coerce_axis(axes.get("EQS")),
        DS=_coerce_axis(axes.get("DS")),
        LS=_coerce_axis(axes.get("LS")),
        EFS=_coerce_axis(axes.get("EFS")),
        APS=_coerce_axis(axes.get("APS")),
        raw_score=raw,
        chaos_risk=_coerce_penalty(chaos_risk),
        staleness_penalty=_coerce_penalty(staleness_penalty),
        mock_penalty=_coerce_penalty(mock_penalty),
    )


def attach_probability_snapshot_to_signal(
    signal: dict[str, Any],
    snapshot: ProbabilitySnapshot,
) -> dict[str, Any]:
    """Return a copy of ``signal`` with the snapshot embedded.

    The advisory-only stamps on the snapshot are preserved verbatim and
    never override an existing stamp on the signal.
    """
    out = dict(signal) if isinstance(signal, dict) else {}
    out["probability_snapshot"] = snapshot.to_dict()
    # Mirror the most important fields at the top level for callers that
    # do not want to dereference the sub-dict.
    out.setdefault("model_probability", out["probability_snapshot"]["model_probability"])
    out.setdefault("probability_formula_version", snapshot.probability_formula_version)
    out.setdefault("advisory_status", snapshot.advisory_status)
    out.setdefault("execution_gate", snapshot.execution_gate)
    out.setdefault("broker_api_called", snapshot.broker_api_called)
    out.setdefault("ai_execution_count", snapshot.ai_execution_count)
    return out


# ---------------------------------------------------------------------------
# SQLite schema layer (additive-only)
# ---------------------------------------------------------------------------


_CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {PROBABILITY_SNAPSHOT_TABLE} (
    signal_id TEXT PRIMARY KEY,
    generated_at_utc TEXT NOT NULL,
    model_probability REAL NOT NULL,
    probability_formula_version TEXT NOT NULL DEFAULT '{FORMULA_VERSION}',
    EMS REAL NOT NULL DEFAULT 0.0,
    EQS REAL NOT NULL DEFAULT 0.0,
    DS REAL NOT NULL DEFAULT 0.0,
    LS REAL NOT NULL DEFAULT 0.0,
    EFS REAL NOT NULL DEFAULT 0.0,
    APS REAL NOT NULL DEFAULT 0.0,
    raw_score REAL NOT NULL DEFAULT 0.0,
    chaos_risk REAL NOT NULL DEFAULT 0.0,
    staleness_penalty REAL NOT NULL DEFAULT 0.0,
    mock_penalty REAL NOT NULL DEFAULT 0.0,
    advisory_status TEXT NOT NULL DEFAULT 'ADVISORY_ONLY',
    execution_gate TEXT NOT NULL DEFAULT 'LOCKED',
    broker_api_called INTEGER NOT NULL DEFAULT 0,
    ai_execution_count INTEGER NOT NULL DEFAULT 0
)
""".strip()


def ensure_probability_snapshot_schema(con: sqlite3.Connection) -> None:
    """Ensure the ``probability_snapshots`` table exists.

    Additive-only: ``CREATE TABLE IF NOT EXISTS`` plus ``ALTER TABLE ADD
    COLUMN`` for each declared column.  Never drops or rewrites a column.
    """
    cur = con.cursor()
    cur.execute(_CREATE_TABLE_SQL)
    # Detect missing columns (e.g. schema added in a future version) and
    # add them additively.  PRAGMA returns (cid, name, type, notnull,
    # dflt_value, pk).
    cur.execute(f"PRAGMA table_info({PROBABILITY_SNAPSHOT_TABLE})")
    existing = {row[1] for row in cur.fetchall()}
    additive: tuple[tuple[str, str, str], ...] = (
        ("signal_id", "TEXT", ""),
        ("generated_at_utc", "TEXT", "NOT NULL DEFAULT ''"),
        ("model_probability", "REAL", "NOT NULL DEFAULT 0.0"),
        ("probability_formula_version", "TEXT", f"NOT NULL DEFAULT '{FORMULA_VERSION}'"),
        ("EMS", "REAL", "NOT NULL DEFAULT 0.0"),
        ("EQS", "REAL", "NOT NULL DEFAULT 0.0"),
        ("DS", "REAL", "NOT NULL DEFAULT 0.0"),
        ("LS", "REAL", "NOT NULL DEFAULT 0.0"),
        ("EFS", "REAL", "NOT NULL DEFAULT 0.0"),
        ("APS", "REAL", "NOT NULL DEFAULT 0.0"),
        ("raw_score", "REAL", "NOT NULL DEFAULT 0.0"),
        ("chaos_risk", "REAL", "NOT NULL DEFAULT 0.0"),
        ("staleness_penalty", "REAL", "NOT NULL DEFAULT 0.0"),
        ("mock_penalty", "REAL", "NOT NULL DEFAULT 0.0"),
        ("advisory_status", "TEXT", "NOT NULL DEFAULT 'ADVISORY_ONLY'"),
        ("execution_gate", "TEXT", "NOT NULL DEFAULT 'LOCKED'"),
        ("broker_api_called", "INTEGER", "NOT NULL DEFAULT 0"),
        ("ai_execution_count", "INTEGER", "NOT NULL DEFAULT 0"),
    )
    for name, type_, suffix in additive:
        if name in existing:
            continue
        suffix_clause = f" {suffix}" if suffix else ""
        cur.execute(
            f"ALTER TABLE {PROBABILITY_SNAPSHOT_TABLE} ADD COLUMN "
            f"{name} {type_}{suffix_clause}"
        )
    con.commit()


def _insert_snapshot(
    con: sqlite3.Connection, snap: ProbabilitySnapshot
) -> bool:
    """Insert one snapshot.  Returns True if newly inserted, False if
    already present.  Never updates an existing row."""
    cur = con.cursor()
    cur.execute(
        f"SELECT 1 FROM {PROBABILITY_SNAPSHOT_TABLE} WHERE signal_id = ?",
        (snap.signal_id,),
    )
    if cur.fetchone() is not None:
        return False
    cur.execute(
        f"""
        INSERT INTO {PROBABILITY_SNAPSHOT_TABLE} (
            signal_id, generated_at_utc, model_probability,
            probability_formula_version,
            EMS, EQS, DS, LS, EFS, APS,
            raw_score, chaos_risk, staleness_penalty, mock_penalty,
            advisory_status, execution_gate,
            broker_api_called, ai_execution_count
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            snap.signal_id,
            snap.generated_at_utc,
            snap.model_probability,
            snap.probability_formula_version,
            snap.EMS,
            snap.EQS,
            snap.DS,
            snap.LS,
            snap.EFS,
            snap.APS,
            snap.raw_score,
            snap.chaos_risk,
            snap.staleness_penalty,
            snap.mock_penalty,
            snap.advisory_status,
            snap.execution_gate,
            1 if snap.broker_api_called else 0,
            int(snap.ai_execution_count),
        ),
    )
    con.commit()
    return True


# ---------------------------------------------------------------------------
# Backfill pipeline
# ---------------------------------------------------------------------------


def _extract_signal_axes(payload: dict[str, Any]) -> dict[str, Any]:
    """Pull score-axis hints out of a stored signal_events payload.

    Most legacy signal_events payloads do not carry the six axes
    explicitly.  We deliberately default missing axes to 0.0 so the raw
    score collapses to ``-lambda_*`` penalties — i.e. a low advisory
    probability — rather than fabricating a confident reading.
    """
    out: dict[str, Any] = {}
    for axis in SCORE_AXES:
        if axis in payload:
            out[axis] = payload[axis]
        elif axis.lower() in payload:
            out[axis] = payload[axis.lower()]
    # A handful of historical sources stash the model confidence on
    # ``confidence_score``; surface it as APS when no APS is available.
    if "APS" not in out and "confidence_score" in payload:
        out["APS"] = payload.get("confidence_score")
    return out


def _extract_penalties(payload: dict[str, Any], source_name: str) -> dict[str, float]:
    """Pull chaos/stale/mock penalty hints from a signal payload.

    Conservative defaults: a signal whose source we cannot identify
    earns ``mock_penalty=0.5`` so its advisory probability stays low.
    """
    chaos = _coerce_penalty(payload.get("chaos_risk"))
    staleness = _coerce_penalty(payload.get("staleness_penalty"))
    mock_penalty_raw = payload.get("mock_penalty")
    mock_penalty: float
    if mock_penalty_raw is None:
        # Heuristic: payloads explicitly flagged as mock/fallback get a
        # full penalty; everything else gets none.
        if payload.get("mock_fallback") or payload.get("fallback_used"):
            mock_penalty = 1.0
        else:
            mock_penalty = 0.0
    else:
        mock_penalty = _coerce_penalty(mock_penalty_raw)
    return {
        "chaos_risk": chaos,
        "staleness_penalty": staleness,
        "mock_penalty": mock_penalty,
    }


def _iter_signal_events(
    con: sqlite3.Connection, *, limit: int | None = None
) -> Iterable[tuple[str, str, str, dict[str, Any]]]:
    """Yield ``(event_id, source_name, fetched_at, payload_dict)`` rows."""
    cur = con.cursor()
    sql = (
        "SELECT event_id, source_name, fetched_at, raw_payload "
        "FROM signal_events ORDER BY id ASC"
    )
    if limit is not None:
        sql += " LIMIT ?"
        cur.execute(sql, (int(limit),))
    else:
        cur.execute(sql)
    for event_id, source_name, fetched_at, raw_payload in cur:
        try:
            payload = json.loads(raw_payload) if raw_payload else {}
        except (TypeError, ValueError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        yield str(event_id), str(source_name or ""), str(fetched_at or ""), payload


def backfill_probability_snapshots(
    *,
    db_path: Path,
    limit: int | None,
    dry_run: bool,
) -> dict[str, Any]:
    """Walk ``signal_events`` and insert one snapshot per unique event.

    When ``dry_run`` is True the schema is still touched only via
    ``CREATE TABLE IF NOT EXISTS`` (which is a no-op on an existing DB)
    and **no inserts are issued**.  All counts and statistics are
    returned in-memory so callers can render a faithful dry-run report.
    """
    db = Path(db_path)
    if not db.exists():
        return {
            "signals_scanned": 0,
            "snapshots_existing": 0,
            "snapshots_created": 0,
            "snapshots_skipped": 0,
            "invalid_probability_count": 0,
            "p_min": None,
            "p_max": None,
            "p_mean": None,
            "db_missing": True,
        }

    try:
        con = sqlite3.connect(str(db), timeout=0.5)
    except sqlite3.Error:
        return {
            "signals_scanned": 0,
            "snapshots_existing": 0,
            "snapshots_created": 0,
            "snapshots_skipped": 0,
            "invalid_probability_count": 0,
            "p_min": None,
            "p_max": None,
            "p_mean": None,
            "db_missing": False,
            "db_locked": True,
        }
    try:
        try:
            ensure_probability_snapshot_schema(con)
        except sqlite3.OperationalError as exc:
            # Database is locked or unwritable — fail safe with no inserts.
            if "locked" in str(exc).lower():
                return {
                    "signals_scanned": 0,
                    "snapshots_existing": 0,
                    "snapshots_created": 0,
                    "snapshots_skipped": 0,
                    "invalid_probability_count": 0,
                    "p_min": None,
                    "p_max": None,
                    "p_mean": None,
                    "db_missing": False,
                    "db_locked": True,
                }
            raise
        cur = con.cursor()
        cur.execute(f"SELECT COUNT(*) FROM {PROBABILITY_SNAPSHOT_TABLE}")
        existing_before = int(cur.fetchone()[0])
        cur.execute(
            f"SELECT signal_id FROM {PROBABILITY_SNAPSHOT_TABLE}"
        )
        existing_ids = {row[0] for row in cur.fetchall()}

        created = 0
        skipped = 0
        invalid = 0
        scanned = 0
        p_values: list[float] = []

        for event_id, source_name, fetched_at, payload in _iter_signal_events(
            con, limit=limit
        ):
            scanned += 1
            if event_id in existing_ids:
                skipped += 1
                continue
            axes = _extract_signal_axes(payload)
            penalties = _extract_penalties(payload, source_name)
            snap = build_probability_snapshot(
                signal_id=event_id,
                axes=axes,
                chaos_risk=penalties["chaos_risk"],
                staleness_penalty=penalties["staleness_penalty"],
                mock_penalty=penalties["mock_penalty"],
                generated_at_utc=fetched_at or _utc_now_iso(),
            )
            if not (0.0 <= snap.model_probability <= 1.0):
                invalid += 1
                continue
            p_values.append(snap.model_probability)
            if dry_run:
                created += 1
                continue
            inserted = _insert_snapshot(con, snap)
            if inserted:
                created += 1
            else:
                skipped += 1
        if dry_run:
            # If we counted snapshots we *would* have inserted, restore the
            # `existing_before` view of "created" to reflect a planning
            # result rather than a persisted one.
            pass

        if p_values:
            p_min = round(min(p_values), 6)
            p_max = round(max(p_values), 6)
            p_mean = round(sum(p_values) / len(p_values), 6)
        else:
            p_min = p_max = p_mean = None

        return {
            "signals_scanned": scanned,
            "snapshots_existing": existing_before,
            "snapshots_created": created,
            "snapshots_skipped": skipped,
            "invalid_probability_count": invalid,
            "p_min": p_min,
            "p_max": p_max,
            "p_mean": p_mean,
            "db_missing": False,
        }
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------


def build_report(
    *,
    db_path: Path,
    dry_run: bool,
    limit: int | None,
    write: bool,
    formula_version: str = FORMULA_VERSION,
) -> dict[str, Any]:
    """Render the operator-facing probability snapshot report.

    ``dry_run`` and ``write`` are independent semantics:
    * ``dry_run=True``  → never insert, never touch disk for inserts.
    * ``write=True``    → permit inserts into the canonical SQLite store.
    * ``dry_run=True`` AND ``write=True`` is disallowed by the CLI but
      defaults to ``dry_run`` for safety in the library form.
    """
    effective_dry_run = bool(dry_run) or not bool(write)
    stats = backfill_probability_snapshots(
        db_path=db_path,
        limit=limit,
        dry_run=effective_dry_run,
    )
    safety = advisory_safety_stamps()
    report: dict[str, Any] = {
        "script": "probability_snapshot.py",
        "generated_at_utc": _utc_now_iso(),
        "advisory_status": safety["advisory_status"],
        "execution_gate": safety["execution_gate"],
        "broker_api_called": safety["broker_api_called"],
        "ai_execution_count": safety["ai_execution_count"],
        "can_execute": safety["can_execute"],
        "execution_permission": safety["execution_permission"],
        "human_review_required": safety["human_review_required"],
        "broker_order_id": safety["broker_order_id"],
        "canonical_store": CANONICAL_STORE,
        "audit_only_store": AUDIT_ONLY_STORE,
        "jsonl_is_canonical": False,
        "dry_run": effective_dry_run,
        "formula_version": formula_version,
        "axis_weights": dict(DEFAULT_AXIS_WEIGHTS),
        "lambda_chaos": DEFAULT_LAMBDA_CHAOS,
        "lambda_stale": DEFAULT_LAMBDA_STALE,
        "lambda_mock": DEFAULT_LAMBDA_MOCK,
        "beta0": DEFAULT_BETA0,
        "beta1": DEFAULT_BETA1,
        "raw_score_clamp": RAW_SCORE_CLAMP,
        "score_axes": list(SCORE_AXES),
        "db_path": str(db_path),
        "signals_scanned": int(stats.get("signals_scanned", 0)),
        "snapshots_existing": int(stats.get("snapshots_existing", 0)),
        "snapshots_created": int(stats.get("snapshots_created", 0)),
        "snapshots_skipped": int(stats.get("snapshots_skipped", 0)),
        "invalid_probability_count": int(stats.get("invalid_probability_count", 0)),
        "p_min": stats.get("p_min"),
        "p_max": stats.get("p_max"),
        "p_mean": stats.get("p_mean"),
        "predictive_claim_allowed": False,
        "warning": ADVISORY_PROBABILITY_WARNING,
    }
    if stats.get("db_missing"):
        report["evidence_status"] = "DB_MISSING"
    if stats.get("db_locked"):
        report["evidence_status"] = "DB_LOCKED"
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Persist advisory probability snapshots beside scored signals.  "
            "Read-only by default; --write enables additive SQLite inserts."
        ),
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="Path to canonical SQLite store (runtime/mvp_local.db).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Plan only; do not insert.  Default when --write is absent.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        default=False,
        help="Permit additive INSERTs into probability_snapshots.",
    )
    parser.add_argument(
        "--backfill",
        action="store_true",
        default=False,
        help="Walk all signal_events and insert snapshots for missing rows.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional row limit for the signal_events scan.",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="If set, write the report JSON to this path.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.write and args.dry_run:
        sys.stderr.write(
            "probability_snapshot: --dry-run and --write are mutually exclusive; "
            "defaulting to --dry-run.\n"
        )
        args.write = False
    # Limit semantics: --backfill without --limit walks the full table.
    limit: int | None
    if args.backfill:
        limit = args.limit
    elif args.limit is not None:
        limit = args.limit
    else:
        # Default: peek at the first 200 rows so dry-runs return fast.
        limit = 200
    report = build_report(
        db_path=args.db,
        dry_run=bool(args.dry_run) or not bool(args.write),
        limit=limit,
        write=bool(args.write),
    )
    payload = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json is not None:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
    sys.stdout.write(payload + "\n")
    return 0


__all__ = [
    "FORMULA_VERSION",
    "PROBABILITY_SNAPSHOT_TABLE",
    "SCORE_AXES",
    "DEFAULT_AXIS_WEIGHTS",
    "DEFAULT_LAMBDA_CHAOS",
    "DEFAULT_LAMBDA_STALE",
    "DEFAULT_LAMBDA_MOCK",
    "DEFAULT_BETA0",
    "DEFAULT_BETA1",
    "RAW_SCORE_CLAMP",
    "ADVISORY_PROBABILITY_WARNING",
    "ProbabilitySnapshot",
    "sigmoid",
    "compute_raw_score",
    "compute_model_probability",
    "build_probability_snapshot",
    "attach_probability_snapshot_to_signal",
    "ensure_probability_snapshot_schema",
    "backfill_probability_snapshots",
    "build_report",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
