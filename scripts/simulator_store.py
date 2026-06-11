"""Local persistence for simulator evaluations (advisory-only).

Follows the ``scripts/persistence.py`` pattern: SQLite in the runtime DB,
JSON payload columns, advisory stamps on every row, and the DB path read
dynamically from ``persistence.DB_PATH`` at call time so the test suite's
DB-isolation fixture applies automatically.

Stored rows give the simulator memory:
  * threshold hysteresis can read the previous ladder state per ticker/theme
  * the history endpoint can replay past verdicts
  * resolved outcomes accumulate into calibration evidence

No secrets, no credentials, no broker fields — there is nothing here that
could place an order.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

try:
    from scripts import persistence as _persistence
except ModuleNotFoundError:  # pragma: no cover
    import persistence as _persistence  # type: ignore[no-redef]

from src.simulator.telemetry import (
    CALIBRATION_RESOLVED,
    OUTCOME_CLASSES,
)
from src.utils.math_utils import clamp01
from src.utils.time_utils import utc_now_iso

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS simulator_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    theme TEXT NOT NULL,
    evaluated_at TEXT NOT NULL,
    final_state TEXT NOT NULL,
    final_score REAL NOT NULL,
    suspicion_score REAL NOT NULL DEFAULT 0.0,
    data_source TEXT NOT NULL DEFAULT 'caller_payload',
    decision_json TEXT NOT NULL,
    telemetry_json TEXT NOT NULL,
    advisory_status TEXT NOT NULL DEFAULT 'ADVISORY_ONLY',
    execution_gate TEXT NOT NULL DEFAULT 'LOCKED',
    broker_api_called INTEGER NOT NULL DEFAULT 0,
    ai_execution_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_simulator_eval_ticker_theme
    ON simulator_evaluations (ticker, theme, evaluated_at DESC);
"""


def _db_path(db_path: Path | None = None) -> Path:
    # Read at call time so test isolation of persistence.DB_PATH applies.
    return Path(db_path) if db_path is not None else Path(_persistence.DB_PATH)


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = _db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.executescript(_SCHEMA_SQL)
    return conn


def record_evaluation(
    result: dict[str, Any], *, db_path: Path | None = None
) -> int:
    """Persist one pipeline result (decision + telemetry). Returns row id."""
    decision = dict(result.get("decision") or {})
    telemetry = dict(result.get("telemetry") or {})
    with _connect(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO simulator_evaluations"
            " (ticker, theme, evaluated_at, final_state, final_score,"
            "  suspicion_score, data_source, decision_json, telemetry_json)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(decision.get("ticker", "UNKNOWN")).upper(),
                str(decision.get("theme", "")),
                str(telemetry.get("decision_time") or utc_now_iso()),
                str(decision.get("final_state", "reject")),
                float(decision.get("final_candidate_score", 0.0)),
                float(decision.get("suspicion_score", 0.0)),
                str(telemetry.get("data_source", "caller_payload")),
                json.dumps(decision, sort_keys=True),
                json.dumps(telemetry, sort_keys=True),
            ),
        )
        return int(cursor.lastrowid or 0)


def get_previous_state(
    ticker: str, theme: str = "", *, db_path: Path | None = None
) -> str | None:
    """Most recent persisted ladder state for hysteresis continuity.

    Theme-scoped when a theme is given; falls back to ticker-wide lookup.
    """
    with _connect(db_path) as conn:
        if theme:
            row = conn.execute(
                "SELECT final_state FROM simulator_evaluations"
                " WHERE ticker = ? AND theme = ?"
                " ORDER BY evaluated_at DESC, id DESC LIMIT 1",
                (str(ticker).upper(), str(theme)),
            ).fetchone()
            if row is not None:
                return str(row["final_state"])
        row = conn.execute(
            "SELECT final_state FROM simulator_evaluations"
            " WHERE ticker = ? ORDER BY evaluated_at DESC, id DESC LIMIT 1",
            (str(ticker).upper(),),
        ).fetchone()
        return str(row["final_state"]) if row is not None else None


def get_history(
    *,
    ticker: str | None = None,
    limit: int = 50,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Read-only evaluation history, newest first, advisory-stamped."""
    bounded = max(1, min(int(limit), 500))
    query = (
        "SELECT id, ticker, theme, evaluated_at, final_state, final_score,"
        " suspicion_score, data_source, decision_json, telemetry_json"
        " FROM simulator_evaluations"
    )
    params: tuple[Any, ...] = ()
    if ticker:
        query += " WHERE ticker = ?"
        params = (str(ticker).upper(),)
    query += " ORDER BY evaluated_at DESC, id DESC LIMIT ?"
    params += (bounded,)
    with _connect(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
    history: list[dict[str, Any]] = []
    for row in rows:
        entry = dict(row)
        entry["decision"] = json.loads(entry.pop("decision_json"))
        entry["telemetry"] = json.loads(entry.pop("telemetry_json"))
        entry["advisory_status"] = "ADVISORY_ONLY"
        entry["execution_gate"] = "LOCKED"
        entry["broker_api_called"] = False
        entry["ai_execution_count"] = 0
        history.append(entry)
    return history


def resolve_evaluation_outcome(
    evaluation_id: int,
    *,
    actual_outcome: float,
    outcome_class: str,
    db_path: Path | None = None,
) -> bool:
    """Attach a realized outcome to a stored evaluation's telemetry.

    This is the loop that turns journal history into calibration evidence.
    Returns False when the row does not exist.
    """
    if outcome_class not in OUTCOME_CLASSES:
        raise ValueError(f"unknown outcome class: {outcome_class!r}")
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT telemetry_json FROM simulator_evaluations WHERE id = ?",
            (int(evaluation_id),),
        ).fetchone()
        if row is None:
            return False
        telemetry = json.loads(row["telemetry_json"])
        telemetry["actual_outcome_placeholder"] = clamp01(float(actual_outcome))
        telemetry["outcome_class"] = outcome_class
        predicted = telemetry.get("predicted_probability")
        if predicted is not None:
            telemetry["calibration_error"] = float(predicted) - clamp01(
                float(actual_outcome)
            )
        telemetry["calibration_status"] = CALIBRATION_RESOLVED
        conn.execute(
            "UPDATE simulator_evaluations SET telemetry_json = ? WHERE id = ?",
            (json.dumps(telemetry, sort_keys=True), int(evaluation_id)),
        )
        return True


def load_all_telemetry(*, db_path: Path | None = None) -> list[dict[str, Any]]:
    """All stored telemetry rows (for the calibration bridge)."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT telemetry_json FROM simulator_evaluations"
            " ORDER BY evaluated_at ASC, id ASC"
        ).fetchall()
    return [json.loads(row["telemetry_json"]) for row in rows]
