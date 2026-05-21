"""
Phase E.4 — Global Securities Master persistence module.

Separate from scripts/persistence.py to avoid modifying the existing persistence layer.
Shares the same DB file (runtime/mvp_local.db) and uses the same _get_conn/_ADVISORY_STATUS
pattern for consistency.

Advisory invariants enforced on every write and read:
  advisory_status       = "ADVISORY_ONLY"
  execution_gate        = "LOCKED"
  human_review_required = 1  (True)
  ai_execution_count    = 0
  broker_api_called     = 0  (False)
  broker_order_id       = "NONE"

No broker API. No order placement. No execution logic.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.persistence import DB_PATH, _ADVISORY_STATUS
    from scripts.persistence import _get_conn as _base_get_conn
except ModuleNotFoundError:
    from persistence import DB_PATH, _ADVISORY_STATUS  # type: ignore[no-redef]
    from persistence import _get_conn as _base_get_conn  # type: ignore[no-redef]

_EXECUTION_GATE = "LOCKED"
_AI_EXECUTION_COUNT = 0

# ---------------------------------------------------------------------------
# Schema SQL
# ---------------------------------------------------------------------------

_GLOBAL_SECURITIES_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS security_master (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_symbol TEXT NOT NULL,
    raw_symbol TEXT,
    yahoo_symbol TEXT,
    exchange_code TEXT NOT NULL,
    exchange_name TEXT,
    mic TEXT,
    country_code TEXT,
    country_name TEXT,
    currency TEXT,
    instrument_type TEXT DEFAULT 'stock',
    issuer_name TEXT,
    sector TEXT,
    industry TEXT,
    listing_status TEXT NOT NULL DEFAULT 'ACTIVE',
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    discovery_source TEXT NOT NULL DEFAULT 'unknown',
    discovery_method TEXT NOT NULL DEFAULT 'unknown',
    data_quality_status TEXT DEFAULT 'unknown',
    notes TEXT,
    advisory_status TEXT NOT NULL DEFAULT 'ADVISORY_ONLY',
    execution_gate TEXT NOT NULL DEFAULT 'LOCKED',
    human_review_required INTEGER NOT NULL DEFAULT 1,
    ai_execution_count INTEGER NOT NULL DEFAULT 0,
    broker_api_called INTEGER NOT NULL DEFAULT 0,
    broker_order_id TEXT NOT NULL DEFAULT 'NONE',
    UNIQUE(canonical_symbol, exchange_code)
);
CREATE INDEX IF NOT EXISTS idx_sm_exchange ON security_master(exchange_code);
CREATE INDEX IF NOT EXISTS idx_sm_country ON security_master(country_code);
CREATE INDEX IF NOT EXISTS idx_sm_status ON security_master(listing_status);
CREATE INDEX IF NOT EXISTS idx_sm_yahoo ON security_master(yahoo_symbol);
CREATE TABLE IF NOT EXISTS security_discovery_run_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    country_code TEXT,
    exchange_code TEXT,
    status TEXT NOT NULL DEFAULT 'RUNNING',
    discovered_count INTEGER NOT NULL DEFAULT 0,
    inserted_count INTEGER NOT NULL DEFAULT 0,
    updated_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    advisory_status TEXT NOT NULL DEFAULT 'ADVISORY_ONLY',
    execution_gate TEXT NOT NULL DEFAULT 'LOCKED',
    human_review_required INTEGER NOT NULL DEFAULT 1,
    ai_execution_count INTEGER NOT NULL DEFAULT 0,
    broker_api_called INTEGER NOT NULL DEFAULT 0,
    broker_order_id TEXT NOT NULL DEFAULT 'NONE'
);
CREATE INDEX IF NOT EXISTS idx_sdrl_run_id ON security_discovery_run_log(run_id);
CREATE INDEX IF NOT EXISTS idx_sdrl_exchange ON security_discovery_run_log(exchange_code);
CREATE TABLE IF NOT EXISTS ohlcv_coverage_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_symbol TEXT NOT NULL,
    yahoo_symbol TEXT,
    exchange_code TEXT,
    country_code TEXT,
    interval_code TEXT NOT NULL DEFAULT '1d',
    first_candle_at TEXT,
    last_candle_at TEXT,
    candle_count INTEGER NOT NULL DEFAULT 0,
    last_backfill_at TEXT,
    last_incremental_update_at TEXT,
    status TEXT NOT NULL DEFAULT 'NOT_STARTED',
    error_message TEXT,
    advisory_status TEXT NOT NULL DEFAULT 'ADVISORY_ONLY',
    execution_gate TEXT NOT NULL DEFAULT 'LOCKED',
    human_review_required INTEGER NOT NULL DEFAULT 1,
    ai_execution_count INTEGER NOT NULL DEFAULT 0,
    broker_api_called INTEGER NOT NULL DEFAULT 0,
    broker_order_id TEXT NOT NULL DEFAULT 'NONE',
    UNIQUE(canonical_symbol, interval_code)
);
CREATE INDEX IF NOT EXISTS idx_ocs_symbol ON ohlcv_coverage_status(canonical_symbol);
CREATE INDEX IF NOT EXISTS idx_ocs_exchange ON ohlcv_coverage_status(exchange_code);
CREATE INDEX IF NOT EXISTS idx_ocs_country ON ohlcv_coverage_status(country_code);
"""

# Track initialized paths to avoid redundant schema runs
_gs_initialized: set[str] = set()


# ---------------------------------------------------------------------------
# Schema initialization
# ---------------------------------------------------------------------------


def init_global_securities_schema(db_path: Path = DB_PATH) -> None:
    """Create/extend DB with global securities tables. Idempotent."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    key = str(db_path.resolve())
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(_GLOBAL_SECURITIES_SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()
    _gs_initialized.add(key)


def _get_gs_conn(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Return an open connection with global securities schema guaranteed."""
    db_path = Path(db_path)
    key = str(db_path.resolve())
    if key not in _gs_initialized:
        init_global_securities_schema(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Advisory stamp helper
# ---------------------------------------------------------------------------


def _stamp(d: dict[str, Any]) -> dict[str, Any]:
    """Enforce advisory invariants on a dict in-place and return it."""
    d["advisory_status"] = _ADVISORY_STATUS
    d["execution_gate"] = _EXECUTION_GATE
    d["human_review_required"] = 1
    d["ai_execution_count"] = _AI_EXECUTION_COUNT
    d["broker_api_called"] = 0
    d["broker_order_id"] = "NONE"
    return d


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a Row to a plain stamped dict."""
    return _stamp(dict(row))


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# security_master CRUD
# ---------------------------------------------------------------------------


def upsert_security_master_record(
    record: dict[str, Any],
    db_path: Path = DB_PATH,
) -> str:
    """Insert or update a security_master record.

    Returns 'inserted' if new, 'updated' if existing.
    Advisory invariants are always enforced regardless of input.
    """
    db_path = Path(db_path)
    now = _utcnow()
    canonical_symbol = str(record.get("canonical_symbol", "")).strip().upper()
    exchange_code = str(record.get("exchange_code", "")).strip().upper()

    if not canonical_symbol or not exchange_code:
        raise ValueError("canonical_symbol and exchange_code are required")

    conn = _get_gs_conn(db_path)
    try:
        existing = conn.execute(
            "SELECT id FROM security_master WHERE canonical_symbol=? AND exchange_code=?",
            (canonical_symbol, exchange_code),
        ).fetchone()

        if existing:
            conn.execute(
                """
                UPDATE security_master SET
                    raw_symbol=?, yahoo_symbol=?, exchange_name=?, mic=?,
                    country_code=?, country_name=?, currency=?, instrument_type=?,
                    issuer_name=?, sector=?, industry=?, listing_status=?,
                    last_seen=?, discovery_source=?, discovery_method=?,
                    data_quality_status=?, notes=?,
                    advisory_status='ADVISORY_ONLY', execution_gate='LOCKED',
                    human_review_required=1, ai_execution_count=0,
                    broker_api_called=0, broker_order_id='NONE'
                WHERE canonical_symbol=? AND exchange_code=?
                """,
                (
                    record.get("raw_symbol"),
                    record.get("yahoo_symbol"),
                    record.get("exchange_name"),
                    record.get("mic"),
                    record.get("country_code"),
                    record.get("country_name"),
                    record.get("currency"),
                    record.get("instrument_type", "stock"),
                    record.get("issuer_name"),
                    record.get("sector"),
                    record.get("industry"),
                    record.get("listing_status", "ACTIVE"),
                    now,
                    record.get("discovery_source", "unknown"),
                    record.get("discovery_method", "unknown"),
                    record.get("data_quality_status", "unknown"),
                    record.get("notes"),
                    canonical_symbol,
                    exchange_code,
                ),
            )
            conn.commit()
            return "updated"
        else:
            conn.execute(
                """
                INSERT INTO security_master (
                    canonical_symbol, raw_symbol, yahoo_symbol,
                    exchange_code, exchange_name, mic,
                    country_code, country_name, currency, instrument_type,
                    issuer_name, sector, industry, listing_status,
                    first_seen, last_seen, discovery_source, discovery_method,
                    data_quality_status, notes,
                    advisory_status, execution_gate, human_review_required,
                    ai_execution_count, broker_api_called, broker_order_id
                ) VALUES (
                    ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,
                    'ADVISORY_ONLY','LOCKED',1,0,0,'NONE'
                )
                """,
                (
                    canonical_symbol,
                    record.get("raw_symbol"),
                    record.get("yahoo_symbol"),
                    exchange_code,
                    record.get("exchange_name"),
                    record.get("mic"),
                    record.get("country_code"),
                    record.get("country_name"),
                    record.get("currency"),
                    record.get("instrument_type", "stock"),
                    record.get("issuer_name"),
                    record.get("sector"),
                    record.get("industry"),
                    record.get("listing_status", "ACTIVE"),
                    record.get("first_seen", now),
                    record.get("last_seen", now),
                    record.get("discovery_source", "unknown"),
                    record.get("discovery_method", "unknown"),
                    record.get("data_quality_status", "unknown"),
                    record.get("notes"),
                ),
            )
            conn.commit()
            return "inserted"
    finally:
        conn.close()


def bulk_upsert_security_master(
    records: list[dict[str, Any]],
    db_path: Path = DB_PATH,
) -> tuple[int, int]:
    """Bulk upsert a list of security_master records.

    Returns (inserted_count, updated_count).
    """
    db_path = Path(db_path)
    inserted = 0
    updated = 0
    for rec in records:
        try:
            result = upsert_security_master_record(rec, db_path=db_path)
            if result == "inserted":
                inserted += 1
            else:
                updated += 1
        except Exception:
            pass
    return inserted, updated


def get_security_master_records(
    country_code: str | None = None,
    exchange_code: str | None = None,
    status: str | None = None,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db_path: Path = DB_PATH,
) -> list[dict[str, Any]]:
    """Retrieve security_master records with optional filters.

    All returned records have advisory invariants enforced.
    """
    db_path = Path(db_path)
    conn = _get_gs_conn(db_path)
    try:
        clauses: list[str] = []
        params: list[Any] = []

        if country_code:
            clauses.append("country_code=?")
            params.append(country_code.upper())
        if exchange_code:
            clauses.append("exchange_code=?")
            params.append(exchange_code.upper())
        if status:
            clauses.append("listing_status=?")
            params.append(status.upper())
        if q:
            search = f"%{q}%"
            clauses.append(
                "(canonical_symbol LIKE ? OR issuer_name LIKE ? OR yahoo_symbol LIKE ?)"
            )
            params.extend([search, search, search])

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.extend([limit, offset])
        rows = conn.execute(
            f"SELECT * FROM security_master {where} ORDER BY canonical_symbol LIMIT ? OFFSET ?",
            params,
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_security_by_symbol(
    symbol: str,
    db_path: Path = DB_PATH,
) -> dict[str, Any] | None:
    """Look up a security by canonical_symbol, yahoo_symbol, or raw_symbol.

    Returns the first match or None.
    """
    db_path = Path(db_path)
    sym = symbol.strip().upper()
    conn = _get_gs_conn(db_path)
    try:
        row = conn.execute(
            """
            SELECT * FROM security_master
            WHERE canonical_symbol=? OR yahoo_symbol=? OR raw_symbol=?
            ORDER BY listing_status ASC
            LIMIT 1
            """,
            (sym, sym, sym),
        ).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def mark_security_inactive(
    canonical_symbol: str,
    exchange_code: str,
    reason: str = "delisted",
    db_path: Path = DB_PATH,
) -> bool:
    """Mark a security as inactive (e.g. delisted).

    Returns True if a record was found and updated, False otherwise.
    """
    db_path = Path(db_path)
    now = _utcnow()
    sym = canonical_symbol.strip().upper()
    exc = exchange_code.strip().upper()
    conn = _get_gs_conn(db_path)
    try:
        cursor = conn.execute(
            """
            UPDATE security_master
            SET listing_status='INACTIVE', last_seen=?, notes=?,
                advisory_status='ADVISORY_ONLY', execution_gate='LOCKED',
                human_review_required=1, ai_execution_count=0,
                broker_api_called=0, broker_order_id='NONE'
            WHERE canonical_symbol=? AND exchange_code=?
            """,
            (now, f"Marked inactive: {reason}", sym, exc),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# security_discovery_run_log
# ---------------------------------------------------------------------------


def insert_security_discovery_run_log(
    run_id: str,
    country_code: str,
    exchange_code: str,
    db_path: Path = DB_PATH,
) -> None:
    """Start a new discovery run log entry."""
    db_path = Path(db_path)
    now = _utcnow()
    conn = _get_gs_conn(db_path)
    try:
        conn.execute(
            """
            INSERT INTO security_discovery_run_log
            (run_id, started_at, country_code, exchange_code, status,
             advisory_status, execution_gate, human_review_required,
             ai_execution_count, broker_api_called, broker_order_id)
            VALUES (?,?,?,?,'RUNNING','ADVISORY_ONLY','LOCKED',1,0,0,'NONE')
            """,
            (run_id, now, country_code, exchange_code),
        )
        conn.commit()
    finally:
        conn.close()


def update_security_discovery_run_log(
    run_id: str,
    status: str,
    discovered_count: int,
    inserted_count: int,
    updated_count: int,
    failed_count: int,
    notes: str = "",
    db_path: Path = DB_PATH,
) -> None:
    """Complete a discovery run log entry."""
    db_path = Path(db_path)
    now = _utcnow()
    conn = _get_gs_conn(db_path)
    try:
        conn.execute(
            """
            UPDATE security_discovery_run_log SET
                completed_at=?, status=?, discovered_count=?,
                inserted_count=?, updated_count=?, failed_count=?,
                notes=?, advisory_status='ADVISORY_ONLY',
                execution_gate='LOCKED', human_review_required=1,
                ai_execution_count=0, broker_api_called=0, broker_order_id='NONE'
            WHERE run_id=?
            """,
            (
                now, status, discovered_count,
                inserted_count, updated_count, failed_count,
                notes, run_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# ohlcv_coverage_status
# ---------------------------------------------------------------------------


def upsert_ohlcv_coverage_status(
    canonical_symbol: str,
    exchange_code: str,
    interval_code: str,
    status: str,
    yahoo_symbol: str | None = None,
    country_code: str | None = None,
    first_candle_at: str | None = None,
    last_candle_at: str | None = None,
    candle_count: int = 0,
    last_backfill_at: str | None = None,
    last_incremental_update_at: str | None = None,
    error_message: str | None = None,
    db_path: Path = DB_PATH,
) -> None:
    """Insert or update OHLCV coverage status for a symbol+interval pair."""
    db_path = Path(db_path)
    sym = canonical_symbol.strip().upper()
    conn = _get_gs_conn(db_path)
    try:
        existing = conn.execute(
            "SELECT id FROM ohlcv_coverage_status WHERE canonical_symbol=? AND interval_code=?",
            (sym, interval_code),
        ).fetchone()

        if existing:
            conn.execute(
                """
                UPDATE ohlcv_coverage_status SET
                    yahoo_symbol=?, exchange_code=?, country_code=?,
                    first_candle_at=COALESCE(?, first_candle_at),
                    last_candle_at=?, candle_count=?,
                    last_backfill_at=COALESCE(?, last_backfill_at),
                    last_incremental_update_at=COALESCE(?, last_incremental_update_at),
                    status=?, error_message=?,
                    advisory_status='ADVISORY_ONLY', execution_gate='LOCKED',
                    human_review_required=1, ai_execution_count=0,
                    broker_api_called=0, broker_order_id='NONE'
                WHERE canonical_symbol=? AND interval_code=?
                """,
                (
                    yahoo_symbol, exchange_code.upper() if exchange_code else None, country_code,
                    first_candle_at, last_candle_at, candle_count,
                    last_backfill_at, last_incremental_update_at,
                    status, error_message,
                    sym, interval_code,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO ohlcv_coverage_status (
                    canonical_symbol, yahoo_symbol, exchange_code, country_code,
                    interval_code, first_candle_at, last_candle_at, candle_count,
                    last_backfill_at, last_incremental_update_at, status, error_message,
                    advisory_status, execution_gate, human_review_required,
                    ai_execution_count, broker_api_called, broker_order_id
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'ADVISORY_ONLY','LOCKED',1,0,0,'NONE')
                """,
                (
                    sym, yahoo_symbol,
                    exchange_code.upper() if exchange_code else None,
                    country_code, interval_code,
                    first_candle_at, last_candle_at, candle_count,
                    last_backfill_at, last_incremental_update_at,
                    status, error_message,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def get_ohlcv_coverage_status(
    symbol: str | None = None,
    canonical_symbol: str | None = None,
    country_code: str | None = None,
    exchange_code: str | None = None,
    interval_code: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db_path: Path = DB_PATH,
) -> list[dict[str, Any]]:
    """Retrieve OHLCV coverage status records with optional filters.

    ``canonical_symbol`` is an alias for ``symbol`` for API compatibility.
    """
    db_path = Path(db_path)
    effective_symbol = canonical_symbol or symbol
    conn = _get_gs_conn(db_path)
    try:
        clauses: list[str] = []
        params: list[Any] = []

        if effective_symbol:
            clauses.append("canonical_symbol=?")
            params.append(effective_symbol.strip().upper())
        if country_code:
            clauses.append("country_code=?")
            params.append(country_code.upper())
        if exchange_code:
            clauses.append("exchange_code=?")
            params.append(exchange_code.upper())
        if interval_code:
            clauses.append("interval_code=?")
            params.append(interval_code)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.extend([limit, offset])
        rows = conn.execute(
            f"SELECT * FROM ohlcv_coverage_status {where} ORDER BY canonical_symbol LIMIT ? OFFSET ?",
            params,
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()
