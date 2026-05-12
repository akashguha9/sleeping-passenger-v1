"""
SQLite persistence layer for the local advisory MVP.

DB: runtime/mvp_local.db  (auto-created; runtime/ is gitignored)
Schema: additive CREATE TABLE IF NOT EXISTS — safe to call at any time.

Advisory invariants enforced on every write and read:
  advisory_status    = "ADVISORY_ONLY"
  execution_mode     = "HUMAN_ONLY"
  ai_execution_count = 0
  broker_api_called  = False  (stored as INTEGER 0)
  broker_order_id    = "NONE"
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

try:
    from scripts.runtime_common import RUNTIME_DIR, utc_timestamp
except ModuleNotFoundError:
    from runtime_common import RUNTIME_DIR, utc_timestamp  # type: ignore[no-redef]

DB_PATH: Path = RUNTIME_DIR / "mvp_local.db"

_ADVISORY_STATUS = "ADVISORY_ONLY"
_EXECUTION_MODE = "HUMAN_ONLY"
_AI_EXECUTION_COUNT = 0

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS signal_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    user_status TEXT NOT NULL,
    marked_at TEXT NOT NULL,
    advisory_status TEXT NOT NULL DEFAULT 'ADVISORY_ONLY',
    human_review_required INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_sd_event_id ON signal_decisions(event_id);
CREATE TABLE IF NOT EXISTS user_reflections (
    reflection_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT 'human',
    conviction_level TEXT NOT NULL DEFAULT 'MODERATE',
    reflection_text TEXT NOT NULL,
    reflected_at TEXT NOT NULL,
    advisory_status TEXT NOT NULL DEFAULT 'ADVISORY_ONLY',
    human_review_required INTEGER NOT NULL DEFAULT 1,
    execution_mode TEXT NOT NULL DEFAULT 'HUMAN_ONLY',
    ai_execution_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_ur_event_id ON user_reflections(event_id);
CREATE TABLE IF NOT EXISTS ai_discussion_summaries (
    summary_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    model_label TEXT NOT NULL DEFAULT 'AI_ADVISORY',
    summary_text TEXT NOT NULL,
    summarized_at TEXT NOT NULL,
    advisory_status TEXT NOT NULL DEFAULT 'ADVISORY_ONLY',
    human_review_required INTEGER NOT NULL DEFAULT 1,
    execution_mode TEXT NOT NULL DEFAULT 'HUMAN_ONLY',
    ai_execution_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_ads_event_id ON ai_discussion_summaries(event_id);
CREATE TABLE IF NOT EXISTS manual_trades (
    trade_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    executed_at TEXT NOT NULL,
    thesis TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    logged_by TEXT NOT NULL DEFAULT 'human',
    leverage REAL NOT NULL DEFAULT 1.0,
    execution_mode TEXT NOT NULL DEFAULT 'HUMAN_ONLY',
    ai_execution_count INTEGER NOT NULL DEFAULT 0,
    advisory_status TEXT NOT NULL DEFAULT 'ADVISORY_ONLY',
    human_review_required INTEGER NOT NULL DEFAULT 1,
    broker_order_id TEXT NOT NULL DEFAULT 'NONE',
    broker_api_called INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_mt_event_id ON manual_trades(event_id);
CREATE TABLE IF NOT EXISTS reconciliation_results (
    reconciliation_id TEXT PRIMARY KEY,
    trade_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    reconciled_at TEXT NOT NULL,
    actual_fill_price REAL NOT NULL,
    actual_quantity REAL NOT NULL,
    outcome_notes TEXT NOT NULL DEFAULT '',
    pnl_estimate REAL NOT NULL DEFAULT 0.0,
    outcome_status TEXT NOT NULL DEFAULT 'UNKNOWN',
    execution_mode TEXT NOT NULL DEFAULT 'HUMAN_ONLY',
    ai_execution_count INTEGER NOT NULL DEFAULT 0,
    advisory_status TEXT NOT NULL DEFAULT 'ADVISORY_ONLY',
    human_review_required INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_rr_trade_id ON reconciliation_results(trade_id);
CREATE TABLE IF NOT EXISTS moltbook_entries (
    entry_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    original_signal_thesis TEXT NOT NULL DEFAULT '',
    ai_interpretation TEXT NOT NULL DEFAULT '',
    user_reflection TEXT NOT NULL DEFAULT '',
    final_human_decision TEXT NOT NULL DEFAULT '',
    manual_trade_log_id TEXT NOT NULL DEFAULT '',
    outcome TEXT NOT NULL DEFAULT '',
    mistake_type TEXT NOT NULL,
    lesson_learned TEXT NOT NULL,
    bias_detected TEXT NOT NULL DEFAULT '',
    recalibration_note TEXT NOT NULL DEFAULT '',
    future_rule_update TEXT NOT NULL DEFAULT '',
    logged_at TEXT NOT NULL,
    advisory_status TEXT NOT NULL DEFAULT 'ADVISORY_ONLY',
    human_review_required INTEGER NOT NULL DEFAULT 1,
    execution_mode TEXT NOT NULL DEFAULT 'HUMAN_ONLY',
    ai_execution_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_mb_ticker ON moltbook_entries(ticker);
CREATE INDEX IF NOT EXISTS idx_mb_mistake_type ON moltbook_entries(mistake_type);
CREATE TABLE IF NOT EXISTS source_health (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TEXT NOT NULL,
    snapshot_count INTEGER NOT NULL DEFAULT 0,
    signal_event_count INTEGER NOT NULL DEFAULT 0,
    ticker_count INTEGER NOT NULL DEFAULT 0,
    killed_count INTEGER NOT NULL DEFAULT 0,
    blocked_count INTEGER NOT NULL DEFAULT 0,
    fabric_bull_state TEXT NOT NULL DEFAULT 'UNKNOWN',
    advisory_status TEXT NOT NULL DEFAULT 'ADVISORY_ONLY'
);
CREATE TABLE IF NOT EXISTS export_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exported_at TEXT NOT NULL,
    export_type TEXT NOT NULL,
    row_count INTEGER NOT NULL DEFAULT 0,
    advisory_status TEXT NOT NULL DEFAULT 'ADVISORY_ONLY'
);
CREATE TABLE IF NOT EXISTS signal_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    source_name TEXT NOT NULL,
    raw_payload TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    advisory_status TEXT NOT NULL DEFAULT 'ADVISORY_ONLY',
    human_review_required INTEGER NOT NULL DEFAULT 1,
    execution_gate TEXT NOT NULL DEFAULT 'LOCKED',
    ai_execution_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_se_source ON signal_events(source_name);
CREATE INDEX IF NOT EXISTS idx_se_fetched ON signal_events(fetched_at);
CREATE TABLE IF NOT EXISTS source_run_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name TEXT NOT NULL,
    status TEXT NOT NULL,
    fetched_count INTEGER NOT NULL DEFAULT 0,
    skipped_reason TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    timestamp_utc TEXT NOT NULL,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    advisory_status TEXT NOT NULL DEFAULT 'ADVISORY_ONLY'
);
CREATE INDEX IF NOT EXISTS idx_srl_source ON source_run_log(source_name);
CREATE INDEX IF NOT EXISTS idx_srl_ts ON source_run_log(timestamp_utc);
CREATE TABLE IF NOT EXISTS global_securities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_symbol TEXT NOT NULL UNIQUE,
    provider_symbol TEXT NOT NULL DEFAULT '',
    yahoo_symbol TEXT NOT NULL DEFAULT '',
    isin TEXT,
    name TEXT NOT NULL DEFAULT '',
    exchange_code TEXT NOT NULL DEFAULT '',
    exchange_name TEXT NOT NULL DEFAULT '',
    country TEXT NOT NULL DEFAULT '',
    economy_rank INTEGER,
    currency TEXT,
    asset_type TEXT NOT NULL DEFAULT 'EQUITY',
    sector TEXT,
    industry TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    delisted_at TEXT,
    source TEXT NOT NULL DEFAULT '',
    raw_payload TEXT NOT NULL DEFAULT '{}',
    advisory_status TEXT NOT NULL DEFAULT 'ADVISORY_ONLY',
    execution_gate TEXT NOT NULL DEFAULT 'LOCKED',
    human_review_required INTEGER NOT NULL DEFAULT 1,
    ai_execution_count INTEGER NOT NULL DEFAULT 0,
    broker_api_called INTEGER NOT NULL DEFAULT 0,
    broker_order_id TEXT NOT NULL DEFAULT 'NONE'
);
CREATE INDEX IF NOT EXISTS idx_gs_canonical ON global_securities(canonical_symbol);
CREATE INDEX IF NOT EXISTS idx_gs_yahoo ON global_securities(yahoo_symbol);
CREATE INDEX IF NOT EXISTS idx_gs_exchange ON global_securities(exchange_code);
CREATE INDEX IF NOT EXISTS idx_gs_country ON global_securities(country);
CREATE INDEX IF NOT EXISTS idx_gs_active ON global_securities(active);
CREATE INDEX IF NOT EXISTS idx_gs_asset_type ON global_securities(asset_type);
CREATE TABLE IF NOT EXISTS global_security_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alias TEXT NOT NULL UNIQUE,
    canonical_symbol TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    source TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gsa_alias ON global_security_aliases(alias);
CREATE INDEX IF NOT EXISTS idx_gsa_canonical ON global_security_aliases(canonical_symbol);
"""

# Track which DB paths have been initialized this process (avoids repeat schema runs)
_initialized: set[str] = set()


def _additive_migrations(conn: sqlite3.Connection) -> None:
    """Apply additive column migrations for forward-compatibility.

    Safe to run on every connect; each ALTER is wrapped to be a no-op when
    the column already exists.  Never drops or renames columns.
    """
    migrations = (
        ("manual_trades", "leverage", "REAL NOT NULL DEFAULT 1.0"),
    )
    for table, column, ddl in migrations:
        try:
            existing = {
                row[1]
                for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        except sqlite3.OperationalError:
            pass


def init_schema(db_path: Path = DB_PATH) -> None:
    """Create runtime dir and initialize all tables. Idempotent."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(_SCHEMA_SQL)
        _additive_migrations(conn)
        conn.commit()
    finally:
        conn.close()
    _initialized.add(str(db_path.resolve()))


def _get_conn(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Return an open connection, initializing the schema on first use."""
    key = str(db_path.resolve())
    if key not in _initialized:
        init_schema(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a Row to a plain dict with advisory stamps enforced."""
    d = dict(row)
    d["advisory_status"] = _ADVISORY_STATUS
    if "execution_mode" in d:
        d["execution_mode"] = _EXECUTION_MODE
    if "ai_execution_count" in d:
        d["ai_execution_count"] = _AI_EXECUTION_COUNT
    if "broker_api_called" in d:
        d["broker_api_called"] = False
    if "broker_order_id" in d:
        d["broker_order_id"] = d.get("broker_order_id") or "NONE"
    if "human_review_required" in d and isinstance(d["human_review_required"], int):
        d["human_review_required"] = bool(d["human_review_required"])
    if "leverage" in d:
        try:
            lev = float(d["leverage"]) if d["leverage"] is not None else 1.0
        except (TypeError, ValueError):
            lev = 1.0
        d["leverage"] = lev if lev >= 1.0 else 1.0
    return d


# ---------------------------------------------------------------------------
# Signal decisions
# ---------------------------------------------------------------------------


def insert_signal_decision(
    event_id: str,
    user_status: str,
    marked_at: str,
    db_path: Path = DB_PATH,
) -> None:
    conn = _get_conn(db_path)
    try:
        conn.execute(
            "INSERT INTO signal_decisions"
            " (event_id, user_status, marked_at, advisory_status, human_review_required)"
            " VALUES (?, ?, ?, ?, ?)",
            (event_id, user_status, marked_at, _ADVISORY_STATUS, 1),
        )
        conn.commit()
    finally:
        conn.close()


def get_latest_signal_decision(
    event_id: str, db_path: Path = DB_PATH
) -> dict[str, Any] | None:
    conn = _get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM signal_decisions WHERE event_id=? ORDER BY id DESC LIMIT 1",
            (event_id,),
        ).fetchone()
    finally:
        conn.close()
    return _to_dict(row) if row else None


def get_all_signal_decisions(db_path: Path = DB_PATH) -> dict[str, str]:
    """Return {event_id: latest_user_status}."""
    conn = _get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT event_id, user_status FROM signal_decisions"
            " WHERE id IN (SELECT MAX(id) FROM signal_decisions GROUP BY event_id)"
        ).fetchall()
    finally:
        conn.close()
    return {row["event_id"]: row["user_status"] for row in rows}


# ---------------------------------------------------------------------------
# User reflections
# ---------------------------------------------------------------------------


def insert_reflection(
    reflection_id: str,
    event_id: str,
    author: str,
    conviction_level: str,
    reflection_text: str,
    reflected_at: str,
    db_path: Path = DB_PATH,
) -> None:
    conn = _get_conn(db_path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO user_reflections"
            " (reflection_id, event_id, author, conviction_level, reflection_text,"
            "  reflected_at, advisory_status, human_review_required,"
            "  execution_mode, ai_execution_count)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                reflection_id, event_id, author, conviction_level,
                reflection_text, reflected_at,
                _ADVISORY_STATUS, 1, _EXECUTION_MODE, _AI_EXECUTION_COUNT,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_reflections_for_event(
    event_id: str, db_path: Path = DB_PATH
) -> list[dict[str, Any]]:
    conn = _get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM user_reflections WHERE event_id=? ORDER BY reflected_at",
            (event_id,),
        ).fetchall()
    finally:
        conn.close()
    return [_to_dict(r) for r in rows]


def has_reflection(event_id: str, db_path: Path = DB_PATH) -> bool:
    conn = _get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT 1 FROM user_reflections WHERE event_id=? LIMIT 1",
            (event_id,),
        ).fetchone()
    finally:
        conn.close()
    return row is not None


def get_all_reflections(db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    conn = _get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM user_reflections ORDER BY reflected_at"
        ).fetchall()
    finally:
        conn.close()
    return [_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# AI discussion summaries
# ---------------------------------------------------------------------------


def insert_ai_summary(
    summary_id: str,
    event_id: str,
    model_label: str,
    summary_text: str,
    summarized_at: str,
    db_path: Path = DB_PATH,
) -> None:
    conn = _get_conn(db_path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO ai_discussion_summaries"
            " (summary_id, event_id, model_label, summary_text, summarized_at,"
            "  advisory_status, human_review_required, execution_mode, ai_execution_count)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                summary_id, event_id, model_label, summary_text, summarized_at,
                _ADVISORY_STATUS, 1, _EXECUTION_MODE, _AI_EXECUTION_COUNT,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_ai_summaries_for_event(
    event_id: str, db_path: Path = DB_PATH
) -> list[dict[str, Any]]:
    conn = _get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM ai_discussion_summaries WHERE event_id=? ORDER BY summarized_at",
            (event_id,),
        ).fetchall()
    finally:
        conn.close()
    return [_to_dict(r) for r in rows]


def has_ai_summary(event_id: str, db_path: Path = DB_PATH) -> bool:
    conn = _get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT 1 FROM ai_discussion_summaries WHERE event_id=? LIMIT 1",
            (event_id,),
        ).fetchone()
    finally:
        conn.close()
    return row is not None


def get_all_ai_summaries(db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    conn = _get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM ai_discussion_summaries ORDER BY summarized_at"
        ).fetchall()
    finally:
        conn.close()
    return [_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Manual trades
# ---------------------------------------------------------------------------


def insert_manual_trade(
    trade_id: str,
    event_id: str,
    ticker: str,
    side: str,
    quantity: float,
    price: float,
    executed_at: str,
    thesis: str,
    notes: str,
    logged_by: str,
    db_path: Path = DB_PATH,
    *,
    leverage: float = 1.0,
) -> None:
    """Insert a manual trade record. ``leverage`` is record-only (record-keeping
    of human leverage choice — no broker margin/execution implications)."""
    try:
        lev = float(leverage) if leverage is not None else 1.0
    except (TypeError, ValueError):
        lev = 1.0
    if lev < 1.0:
        lev = 1.0
    conn = _get_conn(db_path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO manual_trades"
            " (trade_id, event_id, ticker, side, quantity, price, executed_at,"
            "  thesis, notes, logged_by, leverage, execution_mode, ai_execution_count,"
            "  advisory_status, human_review_required, broker_order_id, broker_api_called)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                trade_id, event_id, ticker, side, quantity, price, executed_at,
                thesis, notes, logged_by, lev,
                _EXECUTION_MODE, _AI_EXECUTION_COUNT,
                _ADVISORY_STATUS, 1, "NONE", 0,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_trades_for_event(
    event_id: str, db_path: Path = DB_PATH
) -> list[dict[str, Any]]:
    conn = _get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM manual_trades WHERE event_id=? ORDER BY executed_at",
            (event_id,),
        ).fetchall()
    finally:
        conn.close()
    return [_to_dict(r) for r in rows]


def get_event_id_for_trade(trade_id: str, db_path: Path = DB_PATH) -> str:
    conn = _get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT event_id FROM manual_trades WHERE trade_id=? LIMIT 1",
            (trade_id,),
        ).fetchone()
    finally:
        conn.close()
    return str(row["event_id"]) if row else ""


def get_all_manual_trades(db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    conn = _get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM manual_trades ORDER BY executed_at DESC"
        ).fetchall()
    finally:
        conn.close()
    return [_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Reconciliation results
# ---------------------------------------------------------------------------


def insert_reconciliation(
    reconciliation_id: str,
    trade_id: str,
    event_id: str,
    reconciled_at: str,
    actual_fill_price: float,
    actual_quantity: float,
    outcome_notes: str,
    pnl_estimate: float,
    outcome_status: str,
    db_path: Path = DB_PATH,
) -> None:
    conn = _get_conn(db_path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO reconciliation_results"
            " (reconciliation_id, trade_id, event_id, reconciled_at,"
            "  actual_fill_price, actual_quantity, outcome_notes,"
            "  pnl_estimate, outcome_status, execution_mode, ai_execution_count,"
            "  advisory_status, human_review_required)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                reconciliation_id, trade_id, event_id, reconciled_at,
                actual_fill_price, actual_quantity, outcome_notes,
                pnl_estimate, outcome_status,
                _EXECUTION_MODE, _AI_EXECUTION_COUNT,
                _ADVISORY_STATUS, 1,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_reconciliations_for_trade(
    trade_id: str, db_path: Path = DB_PATH
) -> list[dict[str, Any]]:
    conn = _get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM reconciliation_results WHERE trade_id=? ORDER BY reconciled_at",
            (trade_id,),
        ).fetchall()
    finally:
        conn.close()
    return [_to_dict(r) for r in rows]


def get_all_reconciliations(db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    conn = _get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM reconciliation_results ORDER BY reconciled_at DESC"
        ).fetchall()
    finally:
        conn.close()
    return [_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Moltbook entries
# ---------------------------------------------------------------------------


def insert_moltbook_entry(
    entry_id: str,
    event_id: str,
    ticker: str,
    original_signal_thesis: str,
    ai_interpretation: str,
    user_reflection: str,
    final_human_decision: str,
    manual_trade_log_id: str,
    outcome: str,
    mistake_type: str,
    lesson_learned: str,
    bias_detected: str,
    recalibration_note: str,
    future_rule_update: str,
    logged_at: str,
    db_path: Path = DB_PATH,
) -> None:
    conn = _get_conn(db_path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO moltbook_entries"
            " (entry_id, event_id, ticker, original_signal_thesis, ai_interpretation,"
            "  user_reflection, final_human_decision, manual_trade_log_id, outcome,"
            "  mistake_type, lesson_learned, bias_detected, recalibration_note,"
            "  future_rule_update, logged_at, advisory_status, human_review_required,"
            "  execution_mode, ai_execution_count)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                entry_id, event_id, ticker, original_signal_thesis, ai_interpretation,
                user_reflection, final_human_decision, manual_trade_log_id, outcome,
                mistake_type, lesson_learned, bias_detected, recalibration_note,
                future_rule_update, logged_at,
                _ADVISORY_STATUS, 1, _EXECUTION_MODE, _AI_EXECUTION_COUNT,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_moltbook_entries(
    ticker: str | None = None,
    mistake_type: str | None = None,
    db_path: Path = DB_PATH,
) -> list[dict[str, Any]]:
    conn = _get_conn(db_path)
    try:
        if ticker and mistake_type:
            rows = conn.execute(
                "SELECT * FROM moltbook_entries WHERE ticker=? AND mistake_type=?"
                " ORDER BY logged_at DESC",
                (ticker.upper(), mistake_type),
            ).fetchall()
        elif ticker:
            rows = conn.execute(
                "SELECT * FROM moltbook_entries WHERE ticker=? ORDER BY logged_at DESC",
                (ticker.upper(),),
            ).fetchall()
        elif mistake_type:
            rows = conn.execute(
                "SELECT * FROM moltbook_entries WHERE mistake_type=? ORDER BY logged_at DESC",
                (mistake_type,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM moltbook_entries ORDER BY logged_at DESC"
            ).fetchall()
    finally:
        conn.close()
    return [_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Source health
# ---------------------------------------------------------------------------


def insert_source_health(
    snapshot_count: int,
    signal_event_count: int,
    ticker_count: int,
    killed_count: int,
    blocked_count: int,
    fabric_bull_state: str,
    db_path: Path = DB_PATH,
) -> None:
    conn = _get_conn(db_path)
    try:
        conn.execute(
            "INSERT INTO source_health"
            " (run_at, snapshot_count, signal_event_count, ticker_count,"
            "  killed_count, blocked_count, fabric_bull_state, advisory_status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                utc_timestamp(),
                snapshot_count, signal_event_count, ticker_count,
                killed_count, blocked_count, fabric_bull_state,
                _ADVISORY_STATUS,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_latest_source_health(db_path: Path = DB_PATH) -> dict[str, Any] | None:
    conn = _get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM source_health ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    d = dict(row)
    d["advisory_status"] = _ADVISORY_STATUS
    return d


# ---------------------------------------------------------------------------
# Export logs
# ---------------------------------------------------------------------------


def log_export(export_type: str, row_count: int, db_path: Path = DB_PATH) -> None:
    conn = _get_conn(db_path)
    try:
        conn.execute(
            "INSERT INTO export_logs (exported_at, export_type, row_count, advisory_status)"
            " VALUES (?, ?, ?, ?)",
            (utc_timestamp(), export_type, row_count, _ADVISORY_STATUS),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# DB status
# ---------------------------------------------------------------------------


def get_db_status(db_path: Path = DB_PATH) -> dict[str, Any]:
    """Return table row counts for /db/status endpoint."""
    tables = [
        "signal_decisions",
        "user_reflections",
        "ai_discussion_summaries",
        "manual_trades",
        "reconciliation_results",
        "moltbook_entries",
        "source_health",
        "export_logs",
        "signal_events",
        "source_run_log",
        "global_securities",
        "global_security_aliases",
    ]
    counts: dict[str, int] = {}
    try:
        conn = _get_conn(db_path)
        try:
            for table in tables:
                row = conn.execute(
                    f"SELECT COUNT(*) AS n FROM {table}"  # noqa: S608
                ).fetchone()
                counts[table] = int(row["n"]) if row else 0
        finally:
            conn.close()
    except Exception:
        counts = {t: -1 for t in tables}

    return {
        "db_path": str(db_path),
        "db_exists": db_path.exists(),
        "table_row_counts": counts,
        "advisory_status": _ADVISORY_STATUS,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "broker_api_called": False,
        "generated_at": utc_timestamp(),
    }


# ---------------------------------------------------------------------------
# Signal events (live-fetched, normalized)
# ---------------------------------------------------------------------------


def insert_signal_event(
    event_id: str,
    source_name: str,
    raw_payload: dict[str, Any],
    fetched_at: str,
    db_path: Path = DB_PATH,
) -> bool:
    """Insert a normalized signal event. Returns True if new, False if duplicate."""
    conn = _get_conn(db_path)
    try:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO signal_events"
            " (event_id, source_name, raw_payload, fetched_at,"
            "  advisory_status, human_review_required, execution_gate, ai_execution_count)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event_id, source_name, json.dumps(raw_payload), fetched_at,
                _ADVISORY_STATUS, 1, "LOCKED", _AI_EXECUTION_COUNT,
            ),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_signal_events(
    source_name: str | None = None,
    limit: int = 100,
    db_path: Path = DB_PATH,
) -> list[dict[str, Any]]:
    """Return recent signal events, optionally filtered by source."""
    conn = _get_conn(db_path)
    try:
        if source_name:
            rows = conn.execute(
                "SELECT * FROM signal_events WHERE source_name=?"
                " ORDER BY fetched_at DESC LIMIT ?",
                (source_name, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM signal_events ORDER BY fetched_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    finally:
        conn.close()

    result = []
    for row in rows:
        d = dict(row)
        d["advisory_status"] = _ADVISORY_STATUS
        d["ai_execution_count"] = _AI_EXECUTION_COUNT
        if isinstance(d.get("human_review_required"), int):
            d["human_review_required"] = bool(d["human_review_required"])
        try:
            d["raw_payload"] = json.loads(d["raw_payload"])
        except (json.JSONDecodeError, TypeError):
            pass
        result.append(d)
    return result


def delete_signal_events_by_ids(
    row_ids: list[int],
    db_path: Path = DB_PATH,
) -> int:
    """Delete signal_events rows by primary-key id. Returns count deleted."""
    if not row_ids:
        return 0
    conn = _get_conn(db_path)
    try:
        placeholders = ",".join("?" * len(row_ids))
        cursor = conn.execute(
            f"DELETE FROM signal_events WHERE id IN ({placeholders})",
            row_ids,
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def get_signal_events_for_symbol(
    symbol: str,
    source_name: str = "market_data",
    limit: int = 200,
    db_path: Path = DB_PATH,
) -> list[dict[str, Any]]:
    """Return signal events for a specific symbol, filtered via JSON payload field.

    Uses SQLite json_extract to filter by raw_payload.symbol at the DB level.
    This avoids the per-symbol cap issue when multiple symbols share source_name
    and the table has many rows (e.g., after a full historical backfill).
    """
    conn = _get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM signal_events"
            " WHERE source_name = ?"
            " AND json_extract(raw_payload, '$.symbol') = ?"
            " ORDER BY fetched_at DESC LIMIT ?",
            (source_name, symbol.upper(), limit),
        ).fetchall()
    finally:
        conn.close()

    result = []
    for row in rows:
        d = dict(row)
        d["advisory_status"] = _ADVISORY_STATUS
        d["ai_execution_count"] = _AI_EXECUTION_COUNT
        if isinstance(d.get("human_review_required"), int):
            d["human_review_required"] = bool(d["human_review_required"])
        try:
            d["raw_payload"] = json.loads(d["raw_payload"])
        except (json.JSONDecodeError, TypeError):
            pass
        result.append(d)
    return result


# ---------------------------------------------------------------------------
# Source run log (per-source ingestion health)
# ---------------------------------------------------------------------------


def log_source_run(
    source_name: str,
    status: str,
    fetched_count: int,
    skipped_reason: str,
    error_message: str,
    timestamp_utc: str,
    duration_ms: int,
    db_path: Path = DB_PATH,
) -> None:
    """Record a source ingestion run result."""
    conn = _get_conn(db_path)
    try:
        conn.execute(
            "INSERT INTO source_run_log"
            " (source_name, status, fetched_count, skipped_reason, error_message,"
            "  timestamp_utc, duration_ms, advisory_status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                source_name, status, fetched_count, skipped_reason,
                error_message, timestamp_utc, duration_ms, _ADVISORY_STATUS,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_source_run_log(limit: int = 50, db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    """Return recent source run log entries, newest first."""
    conn = _get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM source_run_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    result = []
    for row in rows:
        d = dict(row)
        d["advisory_status"] = _ADVISORY_STATUS
        result.append(d)
    return result


def get_latest_source_run_per_source(
    db_path: Path = DB_PATH,
) -> list[dict[str, Any]]:
    """Return the most recent source_run_log entry for each distinct source.

    One row per source_name, ordered newest-first.  Used by the
    /source-health/summary endpoint to drive the frontend warnings banner
    and per-source empty-state messages.
    """
    conn = _get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT srl.*"
            " FROM source_run_log srl"
            " INNER JOIN ("
            "   SELECT source_name, MAX(id) AS max_id"
            "   FROM source_run_log GROUP BY source_name"
            " ) latest ON latest.source_name = srl.source_name"
            " AND latest.max_id = srl.id"
            " ORDER BY srl.timestamp_utc DESC"
        ).fetchall()
    finally:
        conn.close()
    result = []
    for row in rows:
        d = dict(row)
        d["advisory_status"] = _ADVISORY_STATUS
        result.append(d)
    return result


def count_signal_events_by_source(
    db_path: Path = DB_PATH,
) -> dict[str, int]:
    """Return {source_name: row_count} across the signal_events table."""
    conn = _get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT source_name, COUNT(*) AS n FROM signal_events"
            " GROUP BY source_name"
        ).fetchall()
    finally:
        conn.close()
    return {str(r["source_name"]): int(r["n"]) for r in rows}


# ---------------------------------------------------------------------------
# Global securities master
# ---------------------------------------------------------------------------

def _sec_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["advisory_status"] = _ADVISORY_STATUS
    d["ai_execution_count"] = _AI_EXECUTION_COUNT
    d["broker_api_called"] = False
    d["broker_order_id"] = "NONE"
    d["active"] = bool(d.get("active", 1))
    d["human_review_required"] = bool(d.get("human_review_required", 1))
    try:
        d["raw_payload"] = json.loads(d["raw_payload"])
    except (json.JSONDecodeError, TypeError):
        d["raw_payload"] = {}
    return d


def upsert_global_security(
    canonical_symbol: str,
    name: str = "",
    exchange_code: str = "",
    exchange_name: str = "",
    country: str = "",
    currency: str | None = None,
    asset_type: str = "EQUITY",
    sector: str | None = None,
    industry: str | None = None,
    isin: str | None = None,
    economy_rank: int | None = None,
    provider_symbol: str = "",
    yahoo_symbol: str = "",
    active: bool = True,
    source: str = "",
    raw_payload: dict[str, Any] | None = None,
    db_path: Path = DB_PATH,
) -> bool:
    """Upsert a global security record. Returns True if newly inserted, False if updated."""
    now = utc_timestamp()
    sym = canonical_symbol.strip().upper()
    raw_str = json.dumps(raw_payload or {})
    conn = _get_conn(db_path)
    try:
        existing = conn.execute(
            "SELECT id FROM global_securities WHERE canonical_symbol=?", (sym,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE global_securities SET name=?, exchange_code=?, exchange_name=?,"
                " country=?, currency=?, asset_type=?, sector=?, industry=?, isin=?,"
                " economy_rank=?, provider_symbol=?, yahoo_symbol=?, active=?,"
                " source=?, raw_payload=?, last_seen_at=?"
                " WHERE canonical_symbol=?",
                (
                    name, exchange_code, exchange_name, country, currency,
                    asset_type, sector, industry, isin, economy_rank,
                    provider_symbol, yahoo_symbol, int(active),
                    source, raw_str, now, sym,
                ),
            )
            conn.commit()
            return False
        conn.execute(
            "INSERT INTO global_securities"
            " (canonical_symbol, provider_symbol, yahoo_symbol, isin, name,"
            "  exchange_code, exchange_name, country, economy_rank, currency,"
            "  asset_type, sector, industry, active, first_seen_at, last_seen_at,"
            "  source, raw_payload, advisory_status, execution_gate,"
            "  human_review_required, ai_execution_count, broker_api_called, broker_order_id)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                sym, provider_symbol, yahoo_symbol, isin, name,
                exchange_code, exchange_name, country, economy_rank, currency,
                asset_type, sector, industry, int(active), now, now,
                source, raw_str,
                _ADVISORY_STATUS, "LOCKED", 1, _AI_EXECUTION_COUNT, 0, "NONE",
            ),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def get_global_security(
    canonical_symbol: str, db_path: Path = DB_PATH
) -> dict[str, Any] | None:
    """Return a single global security by canonical symbol, or None."""
    conn = _get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM global_securities WHERE canonical_symbol=?",
            (canonical_symbol.strip().upper(),),
        ).fetchone()
    finally:
        conn.close()
    return _sec_row_to_dict(row) if row else None


def search_global_securities(
    q: str,
    limit: int = 20,
    db_path: Path = DB_PATH,
) -> list[dict[str, Any]]:
    """Search global securities by symbol prefix or name substring."""
    q_like = f"%{q.strip().upper()}%"
    conn = _get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM global_securities"
            " WHERE canonical_symbol LIKE ? OR name LIKE ? OR exchange_code LIKE ?"
            " ORDER BY active DESC,"
            " CASE WHEN economy_rank IS NULL THEN 1 ELSE 0 END ASC,"
            " economy_rank ASC, canonical_symbol ASC"
            " LIMIT ?",
            (q_like, q_like, q_like, limit),
        ).fetchall()
    finally:
        conn.close()
    return [_sec_row_to_dict(r) for r in rows]


def upsert_security_alias(
    alias: str,
    canonical_symbol: str,
    confidence: float = 1.0,
    source: str = "",
    db_path: Path = DB_PATH,
) -> bool:
    """Insert or update a symbol alias mapping. Returns True on success."""
    now = utc_timestamp()
    alias_upper = alias.strip().upper()
    canonical_upper = canonical_symbol.strip().upper()
    conn = _get_conn(db_path)
    try:
        existing = conn.execute(
            "SELECT id FROM global_security_aliases WHERE alias=?", (alias_upper,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE global_security_aliases SET canonical_symbol=?, confidence=?, source=?"
                " WHERE alias=?",
                (canonical_upper, confidence, source, alias_upper),
            )
        else:
            conn.execute(
                "INSERT INTO global_security_aliases"
                " (alias, canonical_symbol, confidence, source, created_at)"
                " VALUES (?,?,?,?,?)",
                (alias_upper, canonical_upper, confidence, source, now),
            )
        conn.commit()
        return True
    finally:
        conn.close()


def resolve_alias(alias: str, db_path: Path = DB_PATH) -> str | None:
    """Resolve an alias to its canonical symbol, or return None if not found."""
    conn = _get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT canonical_symbol FROM global_security_aliases WHERE alias=?",
            (alias.strip().upper(),),
        ).fetchone()
    finally:
        conn.close()
    return str(row["canonical_symbol"]) if row else None


def get_security_coverage(
    canonical_symbol: str, db_path: Path = DB_PATH
) -> dict[str, Any]:
    """Return OHLCV candle coverage and metadata for a canonical symbol."""
    sym = canonical_symbol.strip().upper()
    conn = _get_conn(db_path)
    try:
        sec_row = conn.execute(
            "SELECT * FROM global_securities WHERE canonical_symbol=?", (sym,)
        ).fetchone()
        candle_row = conn.execute(
            "SELECT COUNT(*) AS n,"
            " MIN(json_extract(raw_payload,'$.timestamp')) AS first_ts,"
            " MAX(json_extract(raw_payload,'$.timestamp')) AS last_ts"
            " FROM signal_events"
            " WHERE source_name='market_data'"
            " AND json_extract(raw_payload,'$.symbol')=?",
            (sym,),
        ).fetchone()
        alias_rows = conn.execute(
            "SELECT alias FROM global_security_aliases WHERE canonical_symbol=?", (sym,)
        ).fetchall()
    finally:
        conn.close()

    candle_count = int(candle_row["n"]) if candle_row else 0
    first_ts = candle_row["first_ts"] if candle_row and candle_count > 0 else None
    last_ts = candle_row["last_ts"] if candle_row and candle_count > 0 else None
    aliases = [r["alias"] for r in alias_rows]

    return {
        "canonical_symbol": sym,
        "in_securities_master": sec_row is not None,
        "security": _sec_row_to_dict(sec_row) if sec_row else None,
        "candle_count": candle_count,
        "first_candle_at": first_ts,
        "last_candle_at": last_ts,
        "aliases": aliases,
        "discovery_command": (
            f"python scripts/global_security_master_discovery.py --symbols {sym} --write"
        ),
        "backfill_command": (
            f"python scripts/backfill_global_ohlcv.py --symbols {sym} --period max --interval 1d --write"
        ),
        "advisory_status": _ADVISORY_STATUS,
        "execution_gate": "LOCKED",
        "human_review_required": True,
        "ai_execution_count": _AI_EXECUTION_COUNT,
        "broker_api_called": False,
        "broker_order_id": "NONE",
    }


__all__ = [
    "DB_PATH",
    "init_schema",
    "insert_signal_decision",
    "get_latest_signal_decision",
    "get_all_signal_decisions",
    "insert_reflection",
    "get_reflections_for_event",
    "has_reflection",
    "get_all_reflections",
    "insert_ai_summary",
    "get_ai_summaries_for_event",
    "has_ai_summary",
    "get_all_ai_summaries",
    "insert_manual_trade",
    "get_trades_for_event",
    "get_event_id_for_trade",
    "get_all_manual_trades",
    "insert_reconciliation",
    "get_reconciliations_for_trade",
    "get_all_reconciliations",
    "insert_moltbook_entry",
    "get_moltbook_entries",
    "insert_source_health",
    "get_latest_source_health",
    "log_export",
    "get_db_status",
    "insert_signal_event",
    "get_signal_events",
    "log_source_run",
    "get_source_run_log",
    "get_latest_source_run_per_source",
    "count_signal_events_by_source",
    "upsert_global_security",
    "get_global_security",
    "search_global_securities",
    "upsert_security_alias",
    "resolve_alias",
    "get_security_coverage",
]
