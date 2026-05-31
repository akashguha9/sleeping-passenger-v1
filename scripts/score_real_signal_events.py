"""Score the Real Rows Sprint — Phase 4: persist real-row score vectors.

Reads real canonical ``signal_events`` from the approved SQLite store, runs each
through the pure :func:`scripts.real_signal_score_vector.score_signal_event`
contract, and persists the six-axis vector into an additive side table
``signal_event_score_vectors`` (the canonical ``signal_events`` table is never
destructively altered).

Honest, advisory-only by construction:

* It reuses the Phase 1-3 scorer — no scoring math is duplicated here.
* Mock rows and backfill rows are IGNORED (never scored as real); they are
  counted separately and excluded from the real-canonical denominator.
* Rows that lack required source fields persist a ``SCORE_UNAVAILABLE`` row with
  an explicit reason — values are never fabricated.
* It is idempotent: the side-table primary key is
  ``ScoreKey = hash(event_id | source_name | scoring_version)`` and writes use
  ``INSERT OR IGNORE`` so a second run never duplicates (count(ScoreKey) <= 1).
* Every persisted row carries the advisory-only stamps (``execution_gate =
  LOCKED``, ``broker_api_called = 0``, ``ai_execution_count = 0``).
* It NEVER claims calibration and NEVER claims edge.

Coverage math::

    n_real_canonical_rows = rows_seen - mock_rows - backfill_rows
    ScoringCoverage       = n_scored_real_rows / max(1, n_real_canonical_rows)

    CompleteScore_i = I(all six axes not null) · I(all axes in [0,1])
                    · I(score_status == "SCORED")
    ScoreQualityCoverage = n_complete_score_vectors / max(1, n_real_canonical_rows)

No broker / order / execution code path exists here.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

try:  # package layout
    from scripts import persistence
    from scripts.real_signal_score_vector import (
        SCORE_UNAVAILABLE,
        SCORED,
        SCORING_VERSION,
        axes_complete,
        score_key,
        score_signal_event,
    )
    from scripts.advisory_contract import advisory_safety_stamps
except ModuleNotFoundError:  # pragma: no cover - flat-layout fallback
    import persistence  # type: ignore[no-redef]
    from real_signal_score_vector import (  # type: ignore[no-redef]
        SCORE_UNAVAILABLE,
        SCORED,
        SCORING_VERSION,
        axes_complete,
        score_key,
        score_signal_event,
    )
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]

SCORE_VECTOR_TABLE = "signal_event_score_vectors"
DEFAULT_LIMIT = 10_000

# Mock / backfill markers we honour when present in a stored raw_payload.  The
# canary refuses to persist mock/backfill rows as canonical, but we still detect
# them defensively so a stray flagged row can never be scored as real.
_MOCK_MARKERS = ("mock_flag", "mock", "mock_fallback", "fallback_used", "is_mock")
_BACKFILL_MARKERS = ("backfill_flag", "backfill", "backfill_only", "is_backfill")

_AXES = ("EMS", "EQS", "DS", "LS", "EFS", "APS")

_CREATE_SQL = f"""
CREATE TABLE IF NOT EXISTS {SCORE_VECTOR_TABLE} (
    score_key                TEXT PRIMARY KEY,
    event_id                 TEXT,
    source_name              TEXT,
    ticker                   TEXT,
    timestamp_utc            TEXT,
    EMS                      REAL,
    EQS                      REAL,
    DS                       REAL,
    LS                       REAL,
    EFS                      REAL,
    APS                      REAL,
    score_status             TEXT,
    score_reason             TEXT,
    scoring_version          TEXT,
    model_version            TEXT,
    scored_at_utc            TEXT,
    real_row                 INTEGER,
    mock_flag                INTEGER,
    backfill_flag            INTEGER,
    advisory_status          TEXT NOT NULL DEFAULT 'ADVISORY_ONLY',
    human_execution_required INTEGER NOT NULL DEFAULT 1,
    execution_gate           TEXT NOT NULL DEFAULT 'LOCKED',
    broker_api_called        INTEGER NOT NULL DEFAULT 0,
    ai_execution_count       INTEGER NOT NULL DEFAULT 0
)
"""


# --------------------------------------------------------------------------- #
# Side-table helpers (additive; safe CREATE TABLE IF NOT EXISTS)
# --------------------------------------------------------------------------- #
def ensure_score_vector_schema(db_path: str | Path) -> None:
    """Create the side table if absent.  Additive-only; never destructive."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(_CREATE_SQL)
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_sesv_event ON {SCORE_VECTOR_TABLE}(event_id)"
        )
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_sesv_source ON {SCORE_VECTOR_TABLE}(source_name)"
        )
        conn.commit()
    finally:
        conn.close()


def _persist_vector(conn: sqlite3.Connection, row: Mapping[str, Any]) -> bool:
    """Insert one score-vector row idempotently.  Returns True if newly inserted.

    ``INSERT OR IGNORE`` on the ``score_key`` primary key guarantees
    ``count(ScoreKey) <= 1`` — a re-run never duplicates a score.
    """
    cur = conn.execute(
        f"INSERT OR IGNORE INTO {SCORE_VECTOR_TABLE} ("
        " score_key, event_id, source_name, ticker, timestamp_utc,"
        " EMS, EQS, DS, LS, EFS, APS,"
        " score_status, score_reason, scoring_version, model_version,"
        " scored_at_utc, real_row, mock_flag, backfill_flag,"
        " advisory_status, human_execution_required, execution_gate,"
        " broker_api_called, ai_execution_count"
        ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            row["score_key"], row["event_id"], row["source_name"], row.get("ticker"),
            row.get("timestamp_utc"),
            row.get("EMS"), row.get("EQS"), row.get("DS"),
            row.get("LS"), row.get("EFS"), row.get("APS"),
            row["score_status"], row["score_reason"], row["scoring_version"],
            row["model_version"], row["scored_at_utc"],
            int(bool(row.get("real_row"))), int(bool(row.get("mock_flag"))),
            int(bool(row.get("backfill_flag"))),
            "ADVISORY_ONLY", 1, "LOCKED", 0, 0,
        ),
    )
    return cur.rowcount > 0


def fetch_score_vectors(
    db_path: str | Path,
    *,
    event_id: str | None = None,
) -> list[dict[str, Any]]:
    """Read score-vector rows back (read-only).  Optionally filter by event."""
    ensure_score_vector_schema(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        if event_id is not None:
            rows = conn.execute(
                f"SELECT * FROM {SCORE_VECTOR_TABLE} WHERE event_id=?", (event_id,)
            ).fetchall()
        else:
            rows = conn.execute(f"SELECT * FROM {SCORE_VECTOR_TABLE}").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def lookup_score_vector(
    db_path: str | Path,
    event_id: str,
    *,
    scoring_version: str = SCORING_VERSION,
) -> dict[str, Any] | None:
    """Return the persisted score-vector row for ``event_id`` (or None).

    Read-only.  The ``score_key`` is hash(event_id|source_name|scoring_version)
    and we do not know the source_name at the call site, so this resolves by
    ``event_id`` + ``scoring_version`` (the newest row wins).
    """
    ensure_score_vector_schema(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            f"SELECT * FROM {SCORE_VECTOR_TABLE}"
            " WHERE event_id=? AND scoring_version=?"
            " ORDER BY scored_at_utc DESC LIMIT 1",
            (str(event_id), scoring_version),
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def complete_axes_from_row(row: Mapping[str, Any] | None) -> dict[str, float] | None:
    """Return the six axes as floats iff ``row`` is a CompleteScore vector.

    CompleteScore = score_status == "SCORED" AND every axis is a non-null float
    in [0, 1].  Returns None for missing / incomplete / out-of-range vectors so
    the caller never feeds a fabricated probability downstream.
    """
    if not row:
        return None
    if str(row.get("score_status")) != SCORED:
        return None
    if not int(row.get("real_row") or 0):
        return None
    out: dict[str, float] = {}
    for axis in _AXES:
        v = row.get(axis)
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


def scoring_coverage_summary(db_path: str | Path) -> dict[str, Any]:
    """Read-only coverage summary computed from the persisted side table.

    Does NOT re-score anything — it aggregates what the runner already wrote, so
    it is safe for a read-only API route.  Every persisted side-table row is a
    real (non-mock, non-backfill) canonical row, so the row count is exactly
    ``n_real_canonical_rows`` for the scored corpus.

        ScoringCoverage      = n_scored_real_rows      / max(1, n_real_canonical_rows)
        ScoreQualityCoverage = n_complete_score_vectors / max(1, n_real_canonical_rows)
    """
    ensure_score_vector_schema(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"SELECT score_status, score_reason, source_name, real_row,"
            f" EMS, EQS, DS, LS, EFS, APS FROM {SCORE_VECTOR_TABLE}"
        ).fetchall()
    finally:
        conn.close()

    n_real_canonical_rows = len(rows)
    n_scored = 0
    n_complete = 0
    reasons: dict[str, int] = {}
    sources: dict[str, int] = {}
    for r in rows:
        status = str(r["score_status"])
        if status == SCORE_UNAVAILABLE:
            _bump(reasons, str(r["score_reason"] or "UNKNOWN"))
            continue
        n_scored += 1
        _bump(sources, str(r["source_name"] or "unknown"))
        if status == SCORED and complete_axes_from_row(dict(r)) is not None:
            n_complete += 1

    denom = max(1, n_real_canonical_rows)
    return {
        "n_real_canonical_rows": n_real_canonical_rows,
        "n_scored_real_rows": n_scored,
        "n_complete_score_vectors": n_complete,
        "scoring_coverage": round(n_scored / denom, 6),
        "score_quality_coverage": round(n_complete / denom, 6),
        "score_unavailable_reasons": reasons,
        "sources_scored": sorted(sources.keys()),
        "scoring_version": SCORING_VERSION,
    }


def count_score_vectors(db_path: str | Path, *, complete_only: bool = False) -> int:
    """Count persisted score vectors (optionally only CompleteScore rows)."""
    ensure_score_vector_schema(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        if complete_only:
            n = conn.execute(
                f"SELECT COUNT(*) FROM {SCORE_VECTOR_TABLE}"
                " WHERE score_status=?"
                "   AND EMS IS NOT NULL AND EQS IS NOT NULL AND DS IS NOT NULL"
                "   AND LS IS NOT NULL AND EFS IS NOT NULL AND APS IS NOT NULL",
                (SCORED,),
            ).fetchone()[0]
        else:
            n = conn.execute(f"SELECT COUNT(*) FROM {SCORE_VECTOR_TABLE}").fetchone()[0]
        return int(n)
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Payload field extractors
# --------------------------------------------------------------------------- #
def _detect_mock(payload: Mapping[str, Any]) -> bool:
    return any(bool(payload.get(k)) for k in _MOCK_MARKERS)


def _detect_backfill(payload: Mapping[str, Any]) -> bool:
    return any(bool(payload.get(k)) for k in _BACKFILL_MARKERS)


def _extract_ticker(payload: Mapping[str, Any]) -> str | None:
    for key in ("ticker", "symbol", "entity_name", "market_id"):
        v = payload.get(key)
        if v:
            return str(v)
    return None


def _extract_timestamp(payload: Mapping[str, Any], fetched_at: str | None) -> str | None:
    for key in ("timestamp", "filing_date", "end_date"):
        v = payload.get(key)
        if v:
            return str(v)
    return fetched_at


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
def score_real_signal_events(
    *,
    db_path: Any = None,
    limit: int = DEFAULT_LIMIT,
    now_iso: str | None = None,
    ttl_hours: float | None = None,
    write: bool = True,
) -> dict[str, Any]:
    """Score real canonical ``signal_events`` and persist the score vectors.

    ``write=False`` runs the whole pipeline (read + score + coverage) without
    persisting anything — useful for a safe dry-run.  Returns an honest summary.
    """
    stamps = advisory_safety_stamps()
    target = db_path if db_path is not None else persistence.DB_PATH

    # Ensure both the canonical table (so reads do not crash on a fresh DB) and
    # the additive side table exist.  Both are idempotent.
    persistence.init_schema(target)
    ensure_score_vector_schema(target)

    rows = persistence.get_signal_events(limit=max(1, int(limit)), db_path=target)
    scored_at = now_iso or _utc_now_iso()

    rows_seen = len(rows)
    mock_rows = 0
    backfill_rows = 0
    rows_scored = 0
    n_complete = 0
    newly_persisted = 0
    score_unavailable_reasons: dict[str, int] = {}
    sources_scored: dict[str, int] = {}

    conn: sqlite3.Connection | None = None
    if write:
        conn = sqlite3.connect(str(target))
    try:
        for row in rows:
            payload = row.get("raw_payload")
            if not isinstance(payload, Mapping):
                payload = {}
            source_name = str(row.get("source_name") or payload.get("source") or "").strip()
            event_id = str(row.get("event_id") or "")
            fetched_at = row.get("fetched_at")

            mock_flag = _detect_mock(payload)
            backfill_flag = _detect_backfill(payload)

            # Mock / backfill rows are ignored (never scored as real).  They are
            # counted but excluded from the real-canonical denominator and are
            # NOT persisted to the side table.
            if mock_flag:
                mock_rows += 1
                _bump(score_unavailable_reasons, "MOCK_ROW_NOT_REAL")
                continue
            if backfill_flag:
                backfill_rows += 1
                _bump(score_unavailable_reasons, "BACKFILL_ROW_NOT_FRESH_LIVE")
                continue

            vector = score_signal_event(
                payload,
                source_name=source_name,
                now_iso=now_iso,
                ttl_hours=ttl_hours,
                fetched_at=str(fetched_at) if fetched_at else None,
            )

            status = vector.get("score_status")
            if status == SCORE_UNAVAILABLE:
                _bump(score_unavailable_reasons, str(vector.get("score_reason") or "UNKNOWN"))
            else:
                rows_scored += 1
                _bump(sources_scored, source_name or "unknown")
                if axes_complete(vector):
                    n_complete += 1

            if write and conn is not None:
                db_row = {
                    "score_key": score_key(event_id, source_name, SCORING_VERSION),
                    "event_id": event_id,
                    "source_name": source_name,
                    "ticker": _extract_ticker(payload),
                    "timestamp_utc": _extract_timestamp(payload, str(fetched_at) if fetched_at else None),
                    "scored_at_utc": scored_at,
                    "scoring_version": SCORING_VERSION,
                    "model_version": vector.get("model_version"),
                    "real_row": vector.get("real_row"),
                    "mock_flag": False,
                    "backfill_flag": False,
                    "score_status": status,
                    "score_reason": vector.get("score_reason"),
                }
                for axis in _AXES:
                    db_row[axis] = vector.get(axis)
                if _persist_vector(conn, db_row):
                    newly_persisted += 1
        if write and conn is not None:
            conn.commit()
    finally:
        if conn is not None:
            conn.close()

    n_real_canonical_rows = rows_seen - mock_rows - backfill_rows
    rows_unscored = rows_seen - rows_scored
    denom = max(1, n_real_canonical_rows)
    scoring_coverage = round(rows_scored / denom, 6)
    score_quality_coverage = round(n_complete / denom, 6)

    summary = {
        "rows_seen": rows_seen,
        "rows_scored": rows_scored,
        "rows_unscored": rows_unscored,
        "mock_rows": mock_rows,
        "backfill_rows": backfill_rows,
        "n_real_canonical_rows": n_real_canonical_rows,
        "n_scored_real_rows": rows_scored,
        "n_complete_score_vectors": n_complete,
        "scoring_coverage": scoring_coverage,
        "score_quality_coverage": score_quality_coverage,
        "score_unavailable_reasons": score_unavailable_reasons,
        "sources_scored": sorted(sources_scored.keys()),
        "sources_scored_counts": sources_scored,
        "scoring_version": SCORING_VERSION,
        "newly_persisted": newly_persisted if write else 0,
        "wrote_artifacts": bool(write),
        # Honest gates — this runner can NEVER unlock either.
        "predictive_claim_allowed": False,
        "edge_claimed": False,
    }
    summary.update(stamps)
    summary["advisory_only"] = True
    summary["human_execution_required"] = True
    return summary


def _bump(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Score real canonical signal_events into a side table (advisory-only)."
    )
    p.add_argument("--write", action="store_true", help="persist score vectors to the side table")
    p.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    p.add_argument("--ttl-hours", type=float, default=None)
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    persistence.init_schema()
    summary = score_real_signal_events(
        limit=args.limit, ttl_hours=args.ttl_hours, write=bool(args.write)
    )
    # Print a redacted, secret-free summary (counts / booleans only).
    print(json.dumps({
        "rows_seen": summary["rows_seen"],
        "rows_scored": summary["rows_scored"],
        "rows_unscored": summary["rows_unscored"],
        "n_real_canonical_rows": summary["n_real_canonical_rows"],
        "n_scored_real_rows": summary["n_scored_real_rows"],
        "n_complete_score_vectors": summary["n_complete_score_vectors"],
        "scoring_coverage": summary["scoring_coverage"],
        "score_quality_coverage": summary["score_quality_coverage"],
        "score_unavailable_reasons": summary["score_unavailable_reasons"],
        "sources_scored": summary["sources_scored"],
        "scoring_version": summary["scoring_version"],
        "newly_persisted": summary["newly_persisted"],
        "predictive_claim_allowed": summary["predictive_claim_allowed"],
        "edge_claimed": summary["edge_claimed"],
    }, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))


__all__ = [
    "SCORE_VECTOR_TABLE",
    "ensure_score_vector_schema",
    "fetch_score_vectors",
    "lookup_score_vector",
    "complete_axes_from_row",
    "scoring_coverage_summary",
    "count_score_vectors",
    "score_real_signal_events",
    "main",
]
