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
    broker_api_called INTEGER NOT NULL DEFAULT 0,
    invalidation_level TEXT NOT NULL DEFAULT '',
    expected_horizon TEXT NOT NULL DEFAULT '',
    risk_reason TEXT NOT NULL DEFAULT '',
    entry_reason TEXT NOT NULL DEFAULT '',
    exit_plan TEXT NOT NULL DEFAULT '',
    confidence_before REAL,
    emotional_state TEXT NOT NULL DEFAULT '',
    mistake_tags TEXT NOT NULL DEFAULT '',
    lesson TEXT NOT NULL DEFAULT ''
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
    human_review_required INTEGER NOT NULL DEFAULT 1,
    outcome_quality TEXT NOT NULL DEFAULT '',
    process_error TEXT NOT NULL DEFAULT '',
    process_error_notes TEXT NOT NULL DEFAULT '',
    mistake_tags TEXT NOT NULL DEFAULT '',
    lesson TEXT NOT NULL DEFAULT ''
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
CREATE TABLE IF NOT EXISTS live_source_refresh_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    attempted INTEGER NOT NULL DEFAULT 1,
    success INTEGER NOT NULL DEFAULT 0,
    skipped INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    duration_seconds REAL NOT NULL DEFAULT 0,
    rows_before INTEGER NOT NULL DEFAULT 0,
    rows_after INTEGER NOT NULL DEFAULT 0,
    rows_added INTEGER NOT NULL DEFAULT 0,
    error_message TEXT NOT NULL DEFAULT '',
    skipped_reason TEXT NOT NULL DEFAULT '',
    db_path TEXT NOT NULL DEFAULT '',
    advisory_only INTEGER NOT NULL DEFAULT 1,
    execution_gate TEXT NOT NULL DEFAULT 'LOCKED',
    broker_api_called INTEGER NOT NULL DEFAULT 0,
    can_execute INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_lsrr_run ON live_source_refresh_runs(run_id);
CREATE INDEX IF NOT EXISTS idx_lsrr_source ON live_source_refresh_runs(source_name);
CREATE INDEX IF NOT EXISTS idx_lsrr_started ON live_source_refresh_runs(started_at);
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


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    """Apply local-MVP SQLite hardening pragmas to a fresh connection.

    Pragmas are read on every connect rather than at module import so test
    code can monkeypatch the env vars and observe the change.  All pragmas
    are best-effort: failures are silently ignored so a hostile filesystem
    (e.g. read-only mount during diagnostics) still allows reads.

    Reasons each pragma is here:
      * ``busy_timeout`` -- two MVP processes (api_server + a runner)
        occasionally race on a write.  A 5s wait turns ``database is locked``
        into a brief stall instead of a hard error.
      * ``journal_mode=WAL`` -- WAL lets readers run concurrently with the
        writer and is the mode that ``sqlite3.Connection.backup()`` handles
        most cleanly.  Day-1-10 backup_db.py already uses that API.
      * ``synchronous=NORMAL`` -- recommended SQLite default once WAL is on;
        durable across crashes for a single-machine deployment.
      * ``foreign_keys=ON`` -- defensive; we do not rely on FKs today but
        new tables added later will be enforced.
      * ``temp_store=MEMORY`` -- avoids spilling temp btrees to disk on
        large ``SELECT`` joins during reconciliation list/exports.
    """
    try:
        from scripts.runtime_config import (
            sqlite_busy_timeout_ms,
            sqlite_journal_mode,
        )
    except ModuleNotFoundError:  # loose-script path
        from runtime_config import (  # type: ignore[no-redef]
            sqlite_busy_timeout_ms,
            sqlite_journal_mode,
        )

    try:
        conn.execute(f"PRAGMA busy_timeout = {int(sqlite_busy_timeout_ms())}")
    except sqlite3.Error:
        pass

    mode = sqlite_journal_mode()
    if mode and mode != "DEFAULT":
        try:
            conn.execute(f"PRAGMA journal_mode = {mode}")
        except sqlite3.Error:
            pass

    for pragma in (
        "PRAGMA synchronous = NORMAL",
        "PRAGMA foreign_keys = ON",
        "PRAGMA temp_store = MEMORY",
    ):
        try:
            conn.execute(pragma)
        except sqlite3.Error:
            pass


def _read_pragma(conn: sqlite3.Connection, name: str) -> str | int | None:
    """Read a single pragma value defensively; never raises."""
    try:
        row = conn.execute(f"PRAGMA {name}").fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    try:
        return row[0]
    except (IndexError, KeyError, TypeError):
        return None


def _additive_migrations(conn: sqlite3.Connection) -> None:
    """Apply additive column migrations for forward-compatibility.

    Safe to run on every connect; each ALTER is wrapped to be a no-op when
    the column already exists.  Never drops or renames columns.
    """
    migrations = (
        ("manual_trades", "leverage", "REAL NOT NULL DEFAULT 1.0"),
        # Operator-discipline / journal-quality columns. Additive only.
        # Each defaults to '' (TEXT) or NULL (REAL) so existing rows stay legal.
        ("manual_trades", "invalidation_level", "TEXT NOT NULL DEFAULT ''"),
        ("manual_trades", "expected_horizon", "TEXT NOT NULL DEFAULT ''"),
        ("manual_trades", "risk_reason", "TEXT NOT NULL DEFAULT ''"),
        ("manual_trades", "entry_reason", "TEXT NOT NULL DEFAULT ''"),
        ("manual_trades", "exit_plan", "TEXT NOT NULL DEFAULT ''"),
        ("manual_trades", "confidence_before", "REAL"),
        ("manual_trades", "emotional_state", "TEXT NOT NULL DEFAULT ''"),
        ("manual_trades", "mistake_tags", "TEXT NOT NULL DEFAULT ''"),
        ("manual_trades", "lesson", "TEXT NOT NULL DEFAULT ''"),
        # Reactor-at-decision snapshot columns (Sprint 7B). All optional;
        # NULL/'' means the operator did not capture a reactor snapshot when
        # logging this trade. Calibration code treats absence as "no
        # snapshot" and never invents values. None of these grant execution
        # permission; they are pure record-keeping for hindsight calibration.
        ("manual_trades", "reactor_state_at_decision", "TEXT NOT NULL DEFAULT ''"),
        ("manual_trades", "decision_grade_energy_at_decision", "REAL"),
        ("manual_trades", "echo_risk_score_at_decision", "REAL"),
        ("manual_trades", "meltdown_risk_at_decision", "REAL"),
        ("manual_trades", "fusion_validity_at_decision", "TEXT NOT NULL DEFAULT ''"),
        ("manual_trades", "fission_branch_clarity_at_decision", "REAL"),
        ("manual_trades", "operator_heat_at_decision", "REAL"),
        ("manual_trades", "gallardo_block_at_decision", "INTEGER NOT NULL DEFAULT 0"),
        ("manual_trades", "preflight_state_at_decision", "TEXT NOT NULL DEFAULT ''"),
        # Sprint 7B.2 — Paper-trade ledger support.  ``trade_mode`` is
        # additive; legacy rows default to 'REAL_MANUAL' (operator-entered
        # hand record of real activity), paper imports set 'PAPER'.  This
        # column NEVER grants execution permission.  Paper rows are
        # simulation/rehearsal data and never imply broker_api_called.
        ("manual_trades", "trade_mode", "TEXT NOT NULL DEFAULT 'REAL_MANUAL'"),
        # Soft-cancel columns for duplicate / mis-logged manual entries.
        # Empty reconciliation_status means "active / unreconciled".  Setting
        # it to 'CANCELLED_DUPLICATE' removes the row from the live
        # reconciliation queue without deleting the audit row.  This is pure
        # record-keeping: cancellation NEVER calls the broker, NEVER cancels
        # a real order, and NEVER touches ai_execution_count.
        ("manual_trades", "reconciliation_status", "TEXT NOT NULL DEFAULT ''"),
        ("manual_trades", "cancel_reason", "TEXT NOT NULL DEFAULT ''"),
        ("manual_trades", "cancelled_at", "TEXT NOT NULL DEFAULT ''"),
        # Sprint: Reconciliation provenance.  ``created_via`` records which
        # surface created the row.  Only rows where created_via='manual_trade_log'
        # appear in the live Reconciliation queue and Learning Completeness
        # report.  Legacy rows default to '' (unknown provenance) and are
        # excluded from the queue by design.  Storing this NEVER grants
        # execution permission; the safety stamps are unchanged.
        ("manual_trades", "created_via", "TEXT NOT NULL DEFAULT ''"),
        # Reconciliation outcome-quality / process-error fields.
        ("reconciliation_results", "outcome_quality", "TEXT NOT NULL DEFAULT ''"),
        ("reconciliation_results", "process_error", "TEXT NOT NULL DEFAULT ''"),
        ("reconciliation_results", "process_error_notes", "TEXT NOT NULL DEFAULT ''"),
        ("reconciliation_results", "mistake_tags", "TEXT NOT NULL DEFAULT ''"),
        ("reconciliation_results", "lesson", "TEXT NOT NULL DEFAULT ''"),
    )
    for table, column, ddl in migrations:
        try:
            table_info = conn.execute(f"PRAGMA table_info({table})").fetchall()
            if not table_info:
                # Table absent (e.g. partial test fixture) — skip cleanly.
                continue
            existing = {row[1] for row in table_info}
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        except sqlite3.OperationalError:
            pass


def init_schema(db_path: Path = DB_PATH) -> None:
    """Create runtime dir and initialize all tables. Idempotent."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        _apply_pragmas(conn)
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
    _apply_pragmas(conn)
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


def _normalize_confidence_before(value: Any) -> float | None:
    """Accept None / numeric in [0,1] / numeric in [0,100]. Reject other types.

    None -> None (not yet recorded).  Numeric > 1 and <= 100 is treated as a
    percentage and returned unchanged so future readers can decide their
    own scale; the journal-quality scorer treats any positive number as
    "filled".  Anything else returns None so a bad client payload cannot
    break the insert.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if n != n:  # NaN guard
        return None
    if n < 0.0 or n > 100.0:
        return None
    return n


def _normalize_unit_score(value: Any) -> float | None:
    """Coerce a reactor score to a float in [0, 1] or None.

    Reactor scores live in the unit interval. A bad payload (string, NaN,
    out-of-range, bool) yields None so the insert cannot fail and the
    calibration report can see "no snapshot" instead of garbage.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if n != n:
        return None
    if n < 0.0 or n > 1.0:
        return None
    return n


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
    invalidation_level: str = "",
    expected_horizon: str = "",
    risk_reason: str = "",
    entry_reason: str = "",
    exit_plan: str = "",
    confidence_before: float | None = None,
    emotional_state: str = "",
    mistake_tags: str = "",
    lesson: str = "",
    reactor_state_at_decision: str = "",
    decision_grade_energy_at_decision: float | None = None,
    echo_risk_score_at_decision: float | None = None,
    meltdown_risk_at_decision: float | None = None,
    fusion_validity_at_decision: str = "",
    fission_branch_clarity_at_decision: float | None = None,
    operator_heat_at_decision: float | None = None,
    gallardo_block_at_decision: bool | int | None = None,
    preflight_state_at_decision: str = "",
    trade_mode: str = "REAL_MANUAL",
    created_via: str = "",
) -> None:
    """Insert a manual trade record. ``leverage`` is record-only (record-keeping
    of human leverage choice — no broker margin/execution implications).

    The operator-discipline keyword args (invalidation_level, expected_horizon,
    risk_reason, entry_reason, exit_plan, confidence_before, emotional_state,
    mistake_tags, lesson) are all optional. They are journal-quality fields and
    never grant any execution permission; broker_api_called stays False and
    ai_execution_count stays 0.

    The reactor-at-decision snapshot kwargs (reactor_state_at_decision,
    decision_grade_energy_at_decision, …) are also optional. They capture
    the Signal Reactor advisory state the operator saw at decision time so
    later calibration can ask "did the reactor warn correctly?".  Storing
    them never authorises trades; the safety stamps below are unchanged.
    """
    try:
        lev = float(leverage) if leverage is not None else 1.0
    except (TypeError, ValueError):
        lev = 1.0
    if lev < 1.0:
        lev = 1.0
    conf = _normalize_confidence_before(confidence_before)
    dge = _normalize_unit_score(decision_grade_energy_at_decision)
    echo = _normalize_unit_score(echo_risk_score_at_decision)
    meltdown = _normalize_unit_score(meltdown_risk_at_decision)
    fission = _normalize_unit_score(fission_branch_clarity_at_decision)
    heat = _normalize_unit_score(operator_heat_at_decision)
    gallardo = 1 if gallardo_block_at_decision else 0

    # Normalise trade_mode at the persistence boundary so hostile / typo
    # values can never corrupt calibration filters.  Unknown values fall
    # through to REAL_MANUAL (the safe legacy semantic).
    mode_norm = str(trade_mode or "REAL_MANUAL").strip().upper()
    if mode_norm not in {"PAPER", "REAL_MANUAL", "UNKNOWN"}:
        mode_norm = "REAL_MANUAL"

    # Normalise created_via at persistence boundary so hostile/typo values
    # cannot pollute the provenance contract.  Empty string is the safe
    # legacy default ("unknown provenance" — excluded from Reconciliation).
    created_via_norm = str(created_via or "").strip()

    conn = _get_conn(db_path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(manual_trades)")}
        has_reactor_cols = "reactor_state_at_decision" in cols
        has_trade_mode = "trade_mode" in cols
        has_created_via = "created_via" in cols
        base_cols = (
            "trade_id, event_id, ticker, side, quantity, price, executed_at,"
            " thesis, notes, logged_by, leverage, execution_mode, ai_execution_count,"
            " advisory_status, human_review_required, broker_order_id, broker_api_called,"
            " invalidation_level, expected_horizon, risk_reason, entry_reason,"
            " exit_plan, confidence_before, emotional_state, mistake_tags, lesson"
        )
        base_vals: tuple[Any, ...] = (
            trade_id, event_id, ticker, side, quantity, price, executed_at,
            thesis, notes, logged_by, lev,
            _EXECUTION_MODE, _AI_EXECUTION_COUNT,
            _ADVISORY_STATUS, 1, "NONE", 0,
            str(invalidation_level or ""),
            str(expected_horizon or ""),
            str(risk_reason or ""),
            str(entry_reason or ""),
            str(exit_plan or ""),
            conf,
            str(emotional_state or ""),
            str(mistake_tags or ""),
            str(lesson or ""),
        )
        if has_reactor_cols:
            cols_sql = (
                base_cols
                + ", reactor_state_at_decision, decision_grade_energy_at_decision,"
                "   echo_risk_score_at_decision, meltdown_risk_at_decision,"
                "   fusion_validity_at_decision, fission_branch_clarity_at_decision,"
                "   operator_heat_at_decision, gallardo_block_at_decision,"
                "   preflight_state_at_decision"
            )
            vals = base_vals + (
                str(reactor_state_at_decision or ""),
                dge,
                echo,
                meltdown,
                str(fusion_validity_at_decision or ""),
                fission,
                heat,
                gallardo,
                str(preflight_state_at_decision or ""),
            )
        else:
            cols_sql = base_cols
            vals = base_vals
        if has_trade_mode:
            cols_sql = cols_sql + ", trade_mode"
            vals = vals + (mode_norm,)
        if has_created_via:
            cols_sql = cols_sql + ", created_via"
            vals = vals + (created_via_norm,)
        placeholders = ", ".join(["?"] * len(vals))
        conn.execute(
            f"INSERT OR IGNORE INTO manual_trades ({cols_sql}) VALUES ({placeholders})",
            vals,
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


def get_manual_trade(
    trade_id: str, db_path: Path = DB_PATH
) -> dict[str, Any] | None:
    """Return one manual-trade row by trade_id, or None if absent."""
    conn = _get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM manual_trades WHERE trade_id=? LIMIT 1",
            (trade_id,),
        ).fetchone()
    finally:
        conn.close()
    return _to_dict(row) if row else None


def get_manual_trade_raw_broker_flag(
    trade_id: str, db_path: Path = DB_PATH
) -> int | None:
    """Return the *raw* broker_api_called column for one trade.

    ``_to_dict`` rewrites broker_api_called to False on every read to lock
    the advisory invariant.  The Reconciliation tab's "Cancel Log" path
    needs the *unsanitized* value as a defence-in-depth check: if a row
    somehow ever carried broker_api_called=1 (corrupt/imported data), we
    refuse to silently soft-cancel it.  Returns None when the row or
    column is absent.
    """
    conn = _get_conn(db_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(manual_trades)")}
        if "broker_api_called" not in cols:
            return None
        row = conn.execute(
            "SELECT broker_api_called FROM manual_trades WHERE trade_id=? LIMIT 1",
            (trade_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    try:
        return int(row[0] or 0)
    except (TypeError, ValueError):
        return 0


def cancel_manual_trade(
    trade_id: str,
    cancelled_at: str,
    *,
    cancel_reason: str = "",
    status: str = "CANCELLED_DUPLICATE",
    db_path: Path = DB_PATH,
) -> bool:
    """Soft-cancel a manual trade log row.

    Sets ``reconciliation_status`` to ``status`` (defaults to
    ``CANCELLED_DUPLICATE``) and records the cancellation timestamp and
    reason on the existing row.  Never deletes the row — the audit trail
    of "this log was created then cancelled" is preserved.  Never calls
    a broker; never touches ai_execution_count or broker_api_called.

    Returns True when a row was updated, False when no row matched.
    """
    conn = _get_conn(db_path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(manual_trades)")}
        if "reconciliation_status" not in cols:
            return False
        cur = conn.execute(
            "UPDATE manual_trades"
            " SET reconciliation_status=?, cancel_reason=?, cancelled_at=?"
            " WHERE trade_id=?",
            (
                str(status or "CANCELLED_DUPLICATE"),
                str(cancel_reason or ""),
                str(cancelled_at or ""),
                str(trade_id or ""),
            ),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


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
    *,
    outcome_quality: str = "",
    process_error: str = "",
    process_error_notes: str = "",
    mistake_tags: str = "",
    lesson: str = "",
) -> None:
    """Insert a reconciliation row.

    The keyword-only outcome-quality / process-error / mistake-tag / lesson
    arguments are optional and exist for skill-vs-luck / skill-vs-process
    attribution.  None of them grant execution permission; this is
    record-keeping only.
    """
    conn = _get_conn(db_path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO reconciliation_results"
            " (reconciliation_id, trade_id, event_id, reconciled_at,"
            "  actual_fill_price, actual_quantity, outcome_notes,"
            "  pnl_estimate, outcome_status, execution_mode, ai_execution_count,"
            "  advisory_status, human_review_required,"
            "  outcome_quality, process_error, process_error_notes,"
            "  mistake_tags, lesson)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                reconciliation_id, trade_id, event_id, reconciled_at,
                actual_fill_price, actual_quantity, outcome_notes,
                pnl_estimate, outcome_status,
                _EXECUTION_MODE, _AI_EXECUTION_COUNT,
                _ADVISORY_STATUS, 1,
                str(outcome_quality or ""),
                str(process_error or ""),
                str(process_error_notes or ""),
                str(mistake_tags or ""),
                str(lesson or ""),
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
    pragmas: dict[str, Any] = {
        "journal_mode": None,
        "busy_timeout_ms": None,
        "synchronous": None,
        "foreign_keys": None,
    }
    try:
        conn = _get_conn(db_path)
        try:
            for table in tables:
                row = conn.execute(
                    f"SELECT COUNT(*) AS n FROM {table}"  # noqa: S608
                ).fetchone()
                counts[table] = int(row["n"]) if row else 0
            pragmas["journal_mode"] = _read_pragma(conn, "journal_mode")
            pragmas["busy_timeout_ms"] = _read_pragma(conn, "busy_timeout")
            pragmas["synchronous"] = _read_pragma(conn, "synchronous")
            pragmas["foreign_keys"] = _read_pragma(conn, "foreign_keys")
        finally:
            conn.close()
    except Exception:
        counts = {t: -1 for t in tables}

    # Surface a repo-relative display path so /db/status does not leak the
    # user's home directory when rendered in screenshots/demos.  Falls back
    # to just the filename if the DB lives outside the repo (e.g. tmp_path
    # in tests).
    try:
        repo_root = Path(__file__).resolve().parents[1]
        display_path = str(db_path.resolve().relative_to(repo_root).as_posix())
    except Exception:
        display_path = db_path.name

    return {
        "db_path": display_path,
        "db_exists": db_path.exists(),
        "table_row_counts": counts,
        "pragmas": pragmas,
        "wal_enabled": (
            isinstance(pragmas["journal_mode"], str)
            and pragmas["journal_mode"].lower() == "wal"
        ),
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

    Sort order: by the *candle* timestamp embedded in raw_payload.timestamp,
    descending — NOT by fetched_at.  fetched_at is the wall-clock time the
    backfill ran, which is identical across an entire historical batch and
    therefore unreliable for "give me the latest N candles".  Sorting by the
    payload timestamp guarantees the latest N candles regardless of how the
    rows were inserted.
    """
    conn = _get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM signal_events"
            " WHERE source_name = ?"
            " AND json_extract(raw_payload, '$.symbol') = ?"
            " ORDER BY"
            "   COALESCE(json_extract(raw_payload, '$.timestamp'), fetched_at) DESC,"
            "   id DESC"
            " LIMIT ?",
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


def record_live_source_refresh_run(
    run_id: str,
    source_name: str,
    attempted: bool,
    success: bool,
    skipped: bool,
    started_at: str,
    finished_at: str,
    duration_seconds: float,
    rows_before: int = 0,
    rows_after: int = 0,
    rows_added: int = 0,
    error_message: str = "",
    skipped_reason: str = "",
    db_path: Path | None = None,
) -> None:
    """Persist one per-source refresh outcome row.

    Advisory invariants stamped on every row. Never raises into the caller —
    a missing schema or transient lock must not crash the orchestrator.

    ``db_path`` resolves to the *current* module-level ``DB_PATH`` when not
    supplied, so tests that monkeypatch ``persistence.DB_PATH`` see the
    override (Python function defaults bind at definition time, which we
    deliberately avoid here).
    """
    target = db_path if db_path is not None else DB_PATH
    conn = _get_conn(target)
    try:
        conn.execute(
            "INSERT INTO live_source_refresh_runs"
            " (run_id, source_name, attempted, success, skipped, started_at,"
            "  finished_at, duration_seconds, rows_before, rows_after,"
            "  rows_added, error_message, skipped_reason, db_path,"
            "  advisory_only, execution_gate, broker_api_called, can_execute)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'LOCKED', 0, 0)",
            (
                run_id,
                source_name,
                1 if attempted else 0,
                1 if success else 0,
                1 if skipped else 0,
                started_at,
                finished_at,
                float(duration_seconds),
                int(rows_before),
                int(rows_after),
                int(rows_added),
                str(error_message or "")[:500],
                str(skipped_reason or "")[:500],
                str(target),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_latest_refresh_run_per_source(
    db_path: Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Return one row per source — the most recent refresh attempt.

    Used by the live-signals API to surface refresh_age_hours and stale state.
    Returns an empty dict if the table is missing (degrade gracefully).

    Resolves ``DB_PATH`` lazily so tests that monkeypatch
    ``persistence.DB_PATH`` see the override.
    """
    target = db_path if db_path is not None else DB_PATH
    conn = _get_conn(target)
    try:
        try:
            rows = conn.execute(
                "SELECT lsrr.*"
                " FROM live_source_refresh_runs lsrr"
                " INNER JOIN ("
                "   SELECT source_name, MAX(id) AS max_id"
                "   FROM live_source_refresh_runs GROUP BY source_name"
                " ) latest ON latest.source_name = lsrr.source_name"
                " AND latest.max_id = lsrr.id"
            ).fetchall()
        except sqlite3.OperationalError:
            return {}
    finally:
        conn.close()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        d = dict(row)
        d["advisory_status"] = _ADVISORY_STATUS
        d["execution_gate"] = "LOCKED"
        d["broker_api_called"] = False
        d["can_execute"] = False
        out[str(d["source_name"])] = d
    return out


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
    "get_manual_trade",
    "get_manual_trade_raw_broker_flag",
    "cancel_manual_trade",
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
    "record_live_source_refresh_run",
    "get_latest_refresh_run_per_source",
    "count_signal_events_by_source",
    "upsert_global_security",
    "get_global_security",
    "search_global_securities",
    "upsert_security_alias",
    "resolve_alias",
    "get_security_coverage",
]
