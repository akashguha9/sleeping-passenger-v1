"""Canonical paper-outcome staging — the queryable, idempotent calibration stage.

KANTE_PAPER_OUTCOME_STAGING
===========================

Kanté Outcome Corpus Hardening Sprint, Workstream A.  Until now a closed paper
outcome had no canonical home: it lived in an audit-only JSON blob (not
queryable, not idempotent across runs) or, only once auto-linked, as an
advisory ``external_evidence_outcomes`` row.  This module adds the missing
middle: a canonical SQLite *staging* table where every imported closed paper
outcome lands, carries its intake classification + linkage confidence, and can
be reviewed before it becomes calibration-grade.

It is the Kanté ball-recovery work made durable: it records what genuinely
exists, de-duplicates by content hash so the same outcome never doubles, and
never touches execution or real-money sizing.

Hard safety contract
--------------------
* :func:`make_staging_key` / :func:`build_staging_row` are pure — no I/O.
* :func:`insert_staging_row` is an *idempotent advisory write*: a duplicate
  ``staging_key`` is skipped (``INSERT OR IGNORE``), never updated.  The write
  itself is authorized by the caller's operator permission guard (the importer /
  builder CLIs) — this module is the low-level recorder, like
  :func:`external_evidence_persistence.mark_external_evidence_outcome_known`.
* The loaders (:func:`load_staging_rows`, :func:`count_staging`) are strictly
  read-only.
* Staging is a *paper-only calibration staging area*.  It is NOT execution,
  NOT a real-money store: every row stamps ``execution_gate='LOCKED'``,
  ``broker_api_called=0``, ``ai_execution_count=0``,
  ``real_money_sizing_impact='PROHIBITED'``, ``real_money_weight_allowed=0``.
"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any

try:
    from scripts import external_evidence_persistence as _eep
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import external_evidence_persistence as _eep  # type: ignore[no-redef]

try:
    from scripts.runtime_common import utc_timestamp
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from runtime_common import utc_timestamp  # type: ignore[no-redef]


REAL_MONEY_SIZING_IMPACT = "PROHIBITED"
EXECUTION_GATE_LOCKED = "LOCKED"
_PROOF = "PAPER_OUTCOME_STAGING_PAPER_ONLY"

# The fields that compose the content-hash idempotency key (per the sprint
# spec).  Two rows with the same key are the same closed outcome and are never
# inserted twice.
_STAGING_KEY_FIELDS: tuple[str, ...] = (
    "trade_id",
    "signal_id",
    "ticker",
    "entry_timestamp_utc",
    "exit_timestamp_utc",
    "entry_price",
    "exit_price",
)


def _s(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _num(value: Any) -> str:
    """Stable string form of a numeric component for the hash (never invents)."""
    if value is None or value == "":
        return ""
    try:
        return repr(float(value))
    except (TypeError, ValueError):
        return _s(value)


def make_staging_key(record: dict[str, Any] | None) -> str:
    """Deterministic content hash for one closed paper outcome (pure).

    ``staging_key = SHA256(trade_id | signal_id | ticker | entry_ts | exit_ts |
    entry_price | exit_price)``.  Numeric fields are normalized so ``100`` and
    ``100.0`` hash identically; nothing is invented for absent fields.
    """
    rec = dict(record or {})
    parts = [
        _s(rec.get("trade_id")),
        _s(rec.get("signal_id")),
        _s(rec.get("ticker")).upper(),
        _s(rec.get("entry_timestamp_utc")),
        _s(rec.get("exit_timestamp_utc")),
        _num(rec.get("entry_price")),
        _num(rec.get("exit_price")),
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def is_open_outcome(record: dict[str, Any] | None) -> bool:
    """True when a row is an *open* trade (no exit price or no exit timestamp).

    Open trades are never staged — marking an open trade closed is a mission
    non-negotiable.  A missing exit price *or* a missing exit timestamp means
    the trade has not closed, full stop.
    """
    rec = dict(record or {})
    exit_price = rec.get("exit_price")
    exit_ts = _s(rec.get("exit_timestamp_utc"))
    return exit_price is None or exit_price == "" or not exit_ts


def build_staging_row(
    record: dict[str, Any],
    *,
    link_status: str = "NO_LINK",
    link_confidence: float | None = None,
    external_evidence_snapshot_id: str | None = None,
    moltbook_learning_status: str = "PENDING",
) -> dict[str, Any]:
    """Map one intake-normalized record + link metadata to a staging row (pure).

    ``record`` is a row from ``paper_outcome_intake.validate_outcome`` (so it
    already carries ``intake_classification`` + ``outcome_quality_score`` and
    has not been fabricated).  Linkage fields are advisory metadata only.  The
    advisory / no-execution / real-money-prohibited stamps are unconditional.
    """
    rec = dict(record or {})
    classification = _s(rec.get("intake_classification"))
    valid = 1 if classification == "VALID_FOR_CALIBRATION" else 0
    # A row needs operator review unless it is both calibration-valid AND
    # auto-linked to an evidence snapshot — otherwise a human must look.
    review_required = 0 if (valid and link_status == "AUTO_LINK") else 1

    return {
        "staging_key": make_staging_key(rec),
        "trade_id": _s(rec.get("trade_id")),
        "signal_id": _s(rec.get("signal_id")) or None,
        "ticker": _s(rec.get("ticker")).upper(),
        "entry_timestamp_utc": _s(rec.get("entry_timestamp_utc")) or None,
        "exit_timestamp_utc": _s(rec.get("exit_timestamp_utc")) or None,
        "entry_price": _eep._f(rec.get("entry_price")),
        "exit_price": _eep._f(rec.get("exit_price")),
        "exit_reason": _s(rec.get("exit_reason")) or None,
        "holding_days": rec.get("holding_days_expected"),
        "realized_return_pct": _eep._f(rec.get("realized_return_pct_input")),
        "realized_r_multiple": _eep._f(rec.get("realized_r_multiple")),
        "outcome_y_0_or_1": rec.get("outcome_y_0_or_1_input"),
        "source": _s(rec.get("source")) or None,
        "classification": classification or None,
        "outcome_quality_score": _eep._f(rec.get("outcome_quality_score")),
        "link_status": _s(link_status) or "NO_LINK",
        "link_confidence": _eep._f(link_confidence),
        "external_evidence_snapshot_id": _s(external_evidence_snapshot_id) or None,
        "operator_review_required": review_required,
        "valid_for_calibration": valid,
        "moltbook_learning_status": _s(moltbook_learning_status) or "PENDING",
        # The row's own outcome proof (PAPER_VERIFIED / OPERATOR_CONFIRMED / …),
        # preserved so the review queue can flag a weak/absent proof.  The
        # module-level paper-only proof tag travels on the report, not the row.
        "proof_status": _s(rec.get("proof_status")) or None,
        "advisory_only": 1,
        "human_execution_required": 1,
        "execution_gate": EXECUTION_GATE_LOCKED,
        "broker_api_called": 0,
        "ai_execution_count": 0,
        "real_money_sizing_impact": REAL_MONEY_SIZING_IMPACT,
        "real_money_weight_allowed": 0,
    }


_INSERT_COLUMNS: tuple[str, ...] = (
    "staging_key",
    "trade_id",
    "signal_id",
    "ticker",
    "entry_timestamp_utc",
    "exit_timestamp_utc",
    "entry_price",
    "exit_price",
    "exit_reason",
    "holding_days",
    "realized_return_pct",
    "realized_r_multiple",
    "outcome_y_0_or_1",
    "source",
    "classification",
    "outcome_quality_score",
    "link_status",
    "link_confidence",
    "external_evidence_snapshot_id",
    "operator_review_required",
    "valid_for_calibration",
    "moltbook_learning_status",
    "proof_status",
    "advisory_only",
    "human_execution_required",
    "execution_gate",
    "broker_api_called",
    "ai_execution_count",
    "real_money_sizing_impact",
    "real_money_weight_allowed",
    "created_at_utc",
    "updated_at_utc",
)


def insert_staging_row(
    row: dict[str, Any],
    *,
    db_path: Path | None = None,
    conn: sqlite3.Connection | None = None,
) -> str:
    """Idempotently insert one staging row (advisory write).  Returns a status.

    ``"inserted"`` when a new row was written, ``"skipped_duplicate"`` when the
    ``staging_key`` already exists.  Uses ``INSERT OR IGNORE`` so a duplicate is
    never updated and never doubled — re-importing the same outcome is a no-op.
    The write itself must be authorized by the caller's permission guard.
    """
    now = utc_timestamp()
    values = dict(row)
    values.setdefault("created_at_utc", now)
    values["updated_at_utc"] = now

    owned = conn is None
    if conn is None:
        conn = _eep._open(db_path)
    try:
        placeholders = ", ".join("?" for _ in _INSERT_COLUMNS)
        columns = ", ".join(_INSERT_COLUMNS)
        cur = conn.execute(
            f"INSERT OR IGNORE INTO paper_outcome_staging ({columns}) "
            f"VALUES ({placeholders})",
            tuple(values.get(c) for c in _INSERT_COLUMNS),
        )
        if owned:
            conn.commit()
        return "inserted" if cur.rowcount and cur.rowcount > 0 else "skipped_duplicate"
    finally:
        if owned:
            conn.close()


def load_staging_rows(
    db_path: Path | None = None,
    *,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Return every staging row (read-only).  Never mutates."""
    owned = conn is None
    if conn is None:
        conn = _eep._open(db_path)
    try:
        try:
            rows = conn.execute(
                "SELECT * FROM paper_outcome_staging ORDER BY id ASC"
            ).fetchall()
        except sqlite3.Error:  # pragma: no cover - table absent degrades to empty
            return []
        return [dict(r) for r in rows]
    finally:
        if owned:
            conn.close()


def count_staging(
    db_path: Path | None = None,
    *,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Read-only summary counts over the staging table.

    Never raises — a missing table / DB degrades to all-zero counts.
    """
    rows = load_staging_rows(db_path, conn=conn)
    total = len(rows)
    valid = sum(1 for r in rows if int(r.get("valid_for_calibration") or 0) == 1)
    review = sum(1 for r in rows if int(r.get("operator_review_required") or 0) == 1)
    rejected = sum(
        1 for r in rows if _s(r.get("classification")) == "REJECTED_INSUFFICIENT_PROOF"
    )
    auto = sum(1 for r in rows if _s(r.get("link_status")) == "AUTO_LINK")
    review_link = sum(1 for r in rows if _s(r.get("link_status")) == "REVIEW_LINK")
    no_link = sum(1 for r in rows if _s(r.get("link_status")) in ("NO_LINK", ""))
    # calibration-ready = valid AND auto-linked AND no outstanding review.
    calibration_ready = sum(
        1
        for r in rows
        if int(r.get("valid_for_calibration") or 0) == 1
        and _s(r.get("link_status")) == "AUTO_LINK"
        and int(r.get("operator_review_required") or 0) == 0
    )
    return {
        "staged_outcomes_count": total,
        "valid_count": valid,
        "review_required_count": review,
        "rejected_count": rejected,
        "calibration_ready_count": calibration_ready,
        "auto_link_count": auto,
        "review_link_count": review_link,
        "no_link_count": no_link,
        "real_money_sizing_impact": REAL_MONEY_SIZING_IMPACT,
        "real_money_weight_allowed": False,
        "proof_status": _PROOF,
    }


__all__ = [
    "REAL_MONEY_SIZING_IMPACT",
    "make_staging_key",
    "is_open_outcome",
    "build_staging_row",
    "insert_staging_row",
    "load_staging_rows",
    "count_staging",
]
