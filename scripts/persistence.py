"""
SQLite persistence layer for the local advisory MVP.

DB: runtime/mvp_local.db  (auto-created; runtime/ is gitignored)
Schema: additive CREATE TABLE IF NOT EXISTS — safe to call at any time —
plus a single one-shot F3 rebuild migration that converts the journal
money columns (manual_trades.quantity/price/leverage,
reconciliation_results.actual_fill_price/actual_quantity/pnl_estimate)
from REAL to TEXT-stored canonical Decimal strings.  The rebuild is
fail-loud, runs only when a legacy REAL column is detected, and takes an
automatic backup (sqlite3 native backup API) before touching anything.

Money contract (F3): journal money columns store the canonical Decimal
string from scripts.money.money_to_str.  No float is ever bound into
these columns; arithmetic on them happens in Decimal.

Advisory invariants enforced on every write and read:
  advisory_status    = "ADVISORY_ONLY"
  execution_mode     = "HUMAN_ONLY"
  ai_execution_count = 0
  broker_api_called  = False  (stored as INTEGER 0)
  broker_order_id    = "NONE"
"""
from __future__ import annotations

import json
import logging
import sqlite3
from decimal import Decimal
from pathlib import Path
from typing import Any

try:
    from scripts.runtime_common import RUNTIME_DIR, utc_timestamp
except ModuleNotFoundError:
    from runtime_common import RUNTIME_DIR, utc_timestamp  # type: ignore[no-redef]

try:
    from scripts.money import MoneyError, money_to_str, parse_money
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from money import MoneyError, money_to_str, parse_money  # type: ignore[no-redef]

_logger = logging.getLogger("scripts.persistence")

# F12 audit fix: every table/column name interpolated into SQL f-strings
# (PRAGMA table_info / ALTER TABLE / the F3 rebuild) must pass this
# allowlist.  Today the names all come from hardcoded tuples; the assert
# ensures a future refactor can never feed hostile identifiers in.
import re as _re

_IDENTIFIER_RE = _re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_identifier(name: str) -> str:
    """Return ``name`` iff it is a bare SQL identifier; raise otherwise."""
    if not isinstance(name, str) or not _IDENTIFIER_RE.match(name):
        raise ValueError(f"unsafe SQL identifier: {name!r}")
    return name

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
    quantity TEXT NOT NULL,
    price TEXT NOT NULL,
    executed_at TEXT NOT NULL,
    thesis TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    logged_by TEXT NOT NULL DEFAULT 'human',
    leverage TEXT NOT NULL DEFAULT '1',
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
    lesson TEXT NOT NULL DEFAULT '',
    ai_model_used TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_mt_event_id ON manual_trades(event_id);
CREATE TABLE IF NOT EXISTS reconciliation_results (
    reconciliation_id TEXT PRIMARY KEY,
    trade_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    reconciled_at TEXT NOT NULL,
    actual_fill_price TEXT NOT NULL,
    actual_quantity TEXT NOT NULL,
    outcome_notes TEXT NOT NULL DEFAULT '',
    pnl_estimate TEXT NOT NULL DEFAULT '0',
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
CREATE TABLE IF NOT EXISTS duplicate_fingerprints (
    fingerprint TEXT PRIMARY KEY,
    source_type TEXT NOT NULL DEFAULT '',
    event_type TEXT NOT NULL DEFAULT '',
    ticker TEXT NOT NULL DEFAULT '',
    event_id TEXT NOT NULL DEFAULT '',
    observed_date TEXT NOT NULL DEFAULT '',
    thesis_excerpt TEXT NOT NULL DEFAULT '',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    seen_count INTEGER NOT NULL DEFAULT 1,
    advisory_status TEXT NOT NULL DEFAULT 'ADVISORY_ONLY',
    human_review_required INTEGER NOT NULL DEFAULT 1,
    advisory_only INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_dfp_ticker ON duplicate_fingerprints(ticker);
CREATE INDEX IF NOT EXISTS idx_dfp_event ON duplicate_fingerprints(event_id);
CREATE TABLE IF NOT EXISTS signal_cell_index (
    cell_key TEXT PRIMARY KEY,
    source_type TEXT NOT NULL DEFAULT '',
    jurisdiction TEXT NOT NULL DEFAULT '',
    geography TEXT NOT NULL DEFAULT '',
    sector TEXT NOT NULL DEFAULT '',
    asset_tags TEXT NOT NULL DEFAULT '',
    event_type TEXT NOT NULL DEFAULT '',
    time_bucket TEXT NOT NULL DEFAULT '',
    narrative_cluster TEXT NOT NULL DEFAULT '',
    freshness_state TEXT NOT NULL DEFAULT 'unknown',
    chaos_score REAL NOT NULL DEFAULT 0.0,
    mvp_state TEXT NOT NULL DEFAULT 'candidate',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    seen_count INTEGER NOT NULL DEFAULT 1,
    advisory_only INTEGER NOT NULL DEFAULT 1,
    human_review_required INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_sci_sector ON signal_cell_index(sector);
CREATE INDEX IF NOT EXISTS idx_sci_cluster ON signal_cell_index(narrative_cluster);
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
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name TEXT NOT NULL,
    row_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    old_state_json TEXT NOT NULL DEFAULT '{}',
    changed_at TEXT NOT NULL,
    advisory_status TEXT NOT NULL DEFAULT 'ADVISORY_ONLY'
);
CREATE INDEX IF NOT EXISTS idx_audit_table_row ON audit_log(table_name, row_id);
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
CREATE TABLE IF NOT EXISTS ohlcv_bars (
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    adjusted_close REAL,
    volume REAL,
    source TEXT NOT NULL DEFAULT '',
    data_vendor TEXT NOT NULL DEFAULT '',
    exchange TEXT NOT NULL DEFAULT '',
    currency TEXT NOT NULL DEFAULT '',
    corporate_action_adjusted INTEGER NOT NULL DEFAULT 0,
    imported_at TEXT NOT NULL DEFAULT '',
    advisory_only TEXT NOT NULL DEFAULT 'ADVISORY_ONLY',
    human_execution_required INTEGER NOT NULL DEFAULT 1,
    broker_api_called INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (ticker, date, source)
);
CREATE INDEX IF NOT EXISTS idx_ohlcv_ticker ON ohlcv_bars(ticker);
CREATE TABLE IF NOT EXISTS imported_outcomes (
    outcome_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    ticker TEXT NOT NULL DEFAULT '',
    direction TEXT NOT NULL DEFAULT 'UNKNOWN',
    signal_id TEXT,
    trade_id TEXT,
    opened_at TEXT,
    closed_at TEXT,
    entry_price REAL,
    exit_price REAL,
    realized_pnl REAL,
    capital_at_risk REAL,
    leverage REAL NOT NULL DEFAULT 1.0,
    score_at_entry REAL,
    archetype TEXT,
    signal_class TEXT,
    jurisdiction_group TEXT NOT NULL DEFAULT 'UNKNOWN',
    notes TEXT NOT NULL DEFAULT '',
    imported_at TEXT NOT NULL DEFAULT '',
    advisory_only TEXT NOT NULL DEFAULT 'ADVISORY_ONLY',
    human_execution_required INTEGER NOT NULL DEFAULT 1,
    broker_api_called INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_imported_outcomes_src ON imported_outcomes(source_type);
"""

# Track which DB paths have been initialized this process (avoids repeat schema runs)
_initialized: set[str] = set()


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    """Apply local-MVP SQLite hardening pragmas to a fresh connection.

    Pragmas are read on every connect rather than at module import so test
    code can monkeypatch the env vars and observe the change.  All pragmas
    are best-effort so a hostile filesystem (e.g. read-only mount during
    diagnostics) still allows reads — but failures are logged at ERROR
    (F7b audit fix), never silently dropped.

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

    # F7b: pragma failures are tolerated (reads must still work on a
    # hostile filesystem) but NEVER silent — an unenforced foreign_keys or
    # missing busy_timeout is invisible data-integrity loss otherwise.
    try:
        conn.execute(f"PRAGMA busy_timeout = {int(sqlite_busy_timeout_ms())}")
    except sqlite3.Error as exc:
        _logger.error("pragma busy_timeout failed: %s", exc)

    mode = sqlite_journal_mode()
    if mode and mode != "DEFAULT":
        try:
            row = conn.execute(f"PRAGMA journal_mode = {mode}").fetchone()
            # H4: verify the pragma actually took effect — SQLite returns
            # the RESULTING mode, which can silently differ (e.g. WAL
            # refused on a network/odd filesystem).
            applied = str(row[0]).upper() if row else ""
            if mode.upper() == "WAL" and applied != "WAL":
                global _WAL_VERIFY_FAILURES
                _WAL_VERIFY_FAILURES += 1
                _logger.error(
                    "journal_mode=WAL requested but got %r (cumulative=%d) — "
                    "reader/writer concurrency is degraded",
                    applied,
                    _WAL_VERIFY_FAILURES,
                )
        except sqlite3.Error as exc:
            _logger.error("pragma journal_mode=%s failed: %s", mode, exc)

    for pragma in (
        "PRAGMA synchronous = NORMAL",
        "PRAGMA foreign_keys = ON",
        "PRAGMA temp_store = MEMORY",
    ):
        try:
            conn.execute(pragma)
        except sqlite3.Error as exc:
            _logger.error("%s failed: %s", pragma, exc)


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
        # Sprint I — Native-currency support for operator-entered trades.
        # ``currency`` is the ISO code the operator selected at log time
        # (USD, INR, EUR, JPY, …).  Legacy rows default to '' (treated as
        # UNKNOWN on read).  Storing this NEVER grants execution
        # permission; reconciliation P/L still respects the existing
        # advisory stamps.
        ("manual_trades", "currency", "TEXT NOT NULL DEFAULT ''"),
        # Operator-supplied label naming which AI/model/source produced the
        # signal the operator acted on (e.g. "GPT-5.5", "Claude Code",
        # "Grok", "Gemini", "DeepSeek", "Perplexity", "Copilot",
        # "Human-only", "Multi-model consensus").  Free-text on purpose —
        # this is a manual audit field, not an authentication token.
        # Storing it NEVER grants execution permission; it never reaches a
        # broker.  Legacy rows default to '' and read back as the explicit
        # "—" placeholder in the UI.
        ("manual_trades", "ai_model_used", "TEXT NOT NULL DEFAULT ''"),
        # P0 leverage governance.  Computed at log time from the product
        # doctrine (scripts/leverage_governance.py): India equities up to 4.0x,
        # rest-of-world spot-only (1.0x), unknown jurisdiction fails closed to
        # 1.0x.  ``leverage_breach`` (0/1) marks a recorded trade that exceeded
        # its ceiling — the row is still kept (journal, not execution blocker)
        # so the breach is visible.  Additive; legacy rows default to the
        # safe spot-only / no-breach / UNKNOWN stamp.  None of these grant
        # execution permission; the broker stamps are unchanged.
        ("manual_trades", "leverage_ceiling", "REAL NOT NULL DEFAULT 1.0"),
        ("manual_trades", "leverage_breach", "INTEGER NOT NULL DEFAULT 0"),
        ("manual_trades", "leverage_policy_severity", "TEXT NOT NULL DEFAULT 'NONE'"),
        ("manual_trades", "leverage_policy_reason", "TEXT NOT NULL DEFAULT ''"),
        ("manual_trades", "jurisdiction_group", "TEXT NOT NULL DEFAULT 'UNKNOWN'"),
        # How the jurisdiction was resolved (EXPLICIT / SECURITIES_MASTER /
        # TICKER_HEURISTIC / UNKNOWN_FAIL_CLOSED). Additive; legacy rows default
        # to UNKNOWN_FAIL_CLOSED. Record-only; never grants execution.
        ("manual_trades", "jurisdiction_resolution_source", "TEXT NOT NULL DEFAULT 'UNKNOWN_FAIL_CLOSED'"),
        # Reconciliation outcome-quality / process-error fields.
        ("reconciliation_results", "outcome_quality", "TEXT NOT NULL DEFAULT ''"),
        ("reconciliation_results", "process_error", "TEXT NOT NULL DEFAULT ''"),
        ("reconciliation_results", "process_error_notes", "TEXT NOT NULL DEFAULT ''"),
        ("reconciliation_results", "mistake_tags", "TEXT NOT NULL DEFAULT ''"),
        ("reconciliation_results", "lesson", "TEXT NOT NULL DEFAULT ''"),
    )
    # F9 audit fix: a swallowed ALTER left code assuming a column that
    # doesn't exist ("no such column" much later, origin invisible).
    # Collect every failure and raise with the full list; verify each
    # successful ALTER actually took effect.
    failed: list[tuple[str, str, str]] = []
    for table, column, ddl in migrations:
        table_q = _safe_identifier(table)
        column_q = _safe_identifier(column)
        try:
            table_info = conn.execute(f"PRAGMA table_info({table_q})").fetchall()
            if not table_info:
                # Table absent (e.g. partial test fixture) — skip cleanly.
                continue
            existing = {row[1] for row in table_info}
            if column not in existing:
                conn.execute(f"ALTER TABLE {table_q} ADD COLUMN {column_q} {ddl}")
                verify = {
                    row[1]
                    for row in conn.execute(f"PRAGMA table_info({table_q})")
                }
                if column not in verify:
                    failed.append((table, column, "ALTER did not take effect"))
        except sqlite3.OperationalError as exc:
            failed.append((table, column, str(exc)))
    if failed:
        details = "; ".join(f"{t}.{c}: {e}" for t, c, e in failed)
        raise RuntimeError(
            f"schema migrations FAILED (DB may be missing columns): {details}"
        )


# ---------------------------------------------------------------------------
# F3 money migration: REAL → TEXT-stored canonical Decimal strings
# ---------------------------------------------------------------------------

# Journal money columns per table.  These are the ONLY columns the F3
# rebuild retypes; everything else keeps its declared type verbatim.
_MONEY_COLUMNS: dict[str, tuple[str, ...]] = {
    "manual_trades": ("quantity", "price", "leverage"),
    "reconciliation_results": (
        "actual_fill_price",
        "actual_quantity",
        "pnl_estimate",
    ),
}

# Money-column defaults change representation in the rebuilt table.
_MONEY_DEFAULTS: dict[str, str] = {"leverage": "'1'", "pnl_estimate": "'0'"}

_REBUILD_INDEXES: dict[str, tuple[str, ...]] = {
    "manual_trades": (
        "CREATE INDEX IF NOT EXISTS idx_mt_event_id ON manual_trades(event_id)",
    ),
    "reconciliation_results": (
        "CREATE INDEX IF NOT EXISTS idx_rr_trade_id ON reconciliation_results(trade_id)",
    ),
}


# ---------------------------------------------------------------------------
# F6: INSERT OR IGNORE visibility — silent constraint drops are counted,
# logged at WARNING, and surfaced on /health/full.
# ---------------------------------------------------------------------------

_IGNORED_INSERT_COUNT = 0

# H4: WAL post-set verification.  Non-zero means a connection asked for
# WAL and got something else — concurrency assumptions are void; the
# health surface flags it.
_WAL_VERIFY_FAILURES = 0


def wal_verify_failure_count() -> int:
    return _WAL_VERIFY_FAILURES


def _reset_wal_verify_failures() -> None:
    global _WAL_VERIFY_FAILURES
    _WAL_VERIFY_FAILURES = 0


def ignored_insert_count() -> int:
    """Total INSERT OR IGNORE rows silently dropped since process start."""
    return _IGNORED_INSERT_COUNT


def _reset_ignored_insert_count() -> None:
    """Test helper: zero the F6 ignored-insert counter."""
    global _IGNORED_INSERT_COUNT
    _IGNORED_INSERT_COUNT = 0


def _track_ignored(cur: sqlite3.Cursor, table: str, key: str) -> bool:
    """F6: detect an INSERT OR IGNORE that wrote nothing.

    Returns True when the row was actually inserted.  A zero rowcount
    means a constraint (usually the primary key) silently dropped the
    row — count it and log a WARNING naming the table and key so the
    operator can distinguish intended-duplicate retries from data loss.
    """
    global _IGNORED_INSERT_COUNT
    if cur.rowcount and cur.rowcount > 0:
        return True
    _IGNORED_INSERT_COUNT += 1
    _logger.warning(
        "persistence: ignored duplicate insert into %s (key=%s, cumulative=%d)",
        table,
        key,
        _IGNORED_INSERT_COUNT,
    )
    return False


def _write_audit_row(
    conn: sqlite3.Connection,
    table_name: str,
    row_id: str,
    operation: str,
    old_state: dict[str, Any],
) -> None:
    """F13: record the pre-mutation state of an UPDATE/DELETE.

    Written on the caller's connection WITHOUT committing, so the audit
    row and the mutation land in the same transaction — either both
    persist or neither does.
    """
    conn.execute(
        "INSERT INTO audit_log"
        " (table_name, row_id, operation, old_state_json, changed_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (
            table_name,
            row_id,
            operation,
            json.dumps(old_state, default=str, sort_keys=True),
            utc_timestamp(),
        ),
    )


def _money_text(value: Any, field: str) -> str:
    """Normalise any money-like input to the canonical Decimal string.

    Raises :class:`scripts.money.MoneyError` (a ValueError) on NaN / Inf /
    non-numeric input — the persistence boundary refuses garbage instead
    of silently storing it.
    """
    try:
        return money_to_str(parse_money(value))  # type: ignore[return-value]
    except MoneyError as exc:
        raise MoneyError(f"invalid money value for {field}: {value!r}") from exc


def _money_table_needs_rebuild(conn: sqlite3.Connection, table: str) -> bool:
    table = _safe_identifier(table)
    info = conn.execute(f"PRAGMA table_info({table})").fetchall()
    if not info:
        return False
    declared = {row[1]: str(row[2] or "").strip().upper() for row in info}
    return any(
        declared.get(col) not in (None, "", "TEXT")
        for col in _MONEY_COLUMNS[table]
        if col in declared
    )


def _money_text_migration(db_path: Path) -> None:
    """One-shot F3 rebuild: convert journal money columns REAL → TEXT.

    Fail-loud by design (audit F9 rules): any failure rolls back the
    rebuild transaction and raises RuntimeError — a half-migrated journal
    must never look healthy.  The source DB is backed up first via the
    native sqlite3 backup API; every converted value that carries float-
    repr noise beyond 8 fractional digits is listed in a JSON report next
    to the DB.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        tables = [
            t for t in _MONEY_COLUMNS if _money_table_needs_rebuild(conn, t)
        ]
        if not tables:
            return

        # Automatic backup BEFORE any rewrite (native backup API).
        stamp = utc_timestamp().replace(":", "").replace("-", "")
        backup_dir = db_path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"{db_path.stem}.pre-f3-money.{stamp}.db"
        dst = sqlite3.connect(str(backup_path))
        try:
            conn.backup(dst)
        finally:
            dst.close()

        ambiguous: list[dict[str, Any]] = []
        converted_rows = 0
        conn.execute("BEGIN IMMEDIATE")
        try:
            for table in tables:
                table = _safe_identifier(table)
                info = conn.execute(f"PRAGMA table_info({table})").fetchall()
                money_cols = set(_MONEY_COLUMNS[table])
                col_names = [row[1] for row in info]
                defs: list[str] = []
                for row in info:
                    name, decl_type = row[1], str(row[2] or "")
                    notnull, dflt, pk = row[3], row[4], row[5]
                    if name in money_cols:
                        decl_type = "TEXT"
                        dflt = _MONEY_DEFAULTS.get(name, dflt)
                        if dflt is not None and not str(dflt).startswith("'"):
                            dflt = f"'{dflt}'"
                    d = f"{name} {decl_type}"
                    if pk:
                        d += " PRIMARY KEY"
                    if notnull:
                        d += " NOT NULL"
                    if dflt is not None:
                        d += f" DEFAULT {dflt}"
                    defs.append(d)
                tmp = f"{table}__f3_rebuild"
                conn.execute(f"DROP TABLE IF EXISTS {tmp}")
                conn.execute(f"CREATE TABLE {tmp} ({', '.join(defs)})")

                rows = conn.execute(f"SELECT * FROM {table}").fetchall()
                placeholders = ", ".join(["?"] * len(col_names))
                insert_sql = (
                    f"INSERT INTO {tmp} ({', '.join(col_names)})"
                    f" VALUES ({placeholders})"
                )
                for r in rows:
                    vals: list[Any] = []
                    for name in col_names:
                        v = r[name]
                        if name in money_cols and v is not None:
                            dec = Decimal(str(v))
                            text = money_to_str(dec)
                            exponent = dec.as_tuple().exponent
                            if isinstance(exponent, int) and exponent < -8:
                                ambiguous.append(
                                    {
                                        "table": table,
                                        "column": name,
                                        "raw_repr": str(v),
                                        "stored_as": text,
                                    }
                                )
                            v = text
                        vals.append(v)
                    conn.execute(insert_sql, vals)
                    converted_rows += 1
                conn.execute(f"DROP TABLE {table}")
                conn.execute(f"ALTER TABLE {tmp} RENAME TO {table}")
                for idx_sql in _REBUILD_INDEXES.get(table, ()):
                    conn.execute(idx_sql)
            conn.commit()
        except Exception as exc:
            conn.rollback()
            raise RuntimeError(
                f"F3 money migration FAILED for {db_path} (rolled back; "
                f"backup at {backup_path}): {type(exc).__name__}: {exc}"
            ) from exc

        report = {
            "migration": "f3_money_real_to_text",
            "db_path": str(db_path),
            "backup_path": str(backup_path),
            "tables_rebuilt": tables,
            "rows_converted": converted_rows,
            "ambiguous_float_values": ambiguous,
            "generated_at": utc_timestamp(),
        }
        # Lives in backups/ (not the runtime root) so artifact-coherence
        # scans of runtime/*.json don't classify it as a legacy artifact.
        report_path = backup_dir / f"f3_money_migration_report_{stamp}.json"
        report_path.write_text(json.dumps(report, indent=2))
        _logger.warning(
            "F3 money migration rebuilt %s (%d rows, %d ambiguous float "
            "values). Backup: %s Report: %s",
            ", ".join(tables),
            converted_rows,
            len(ambiguous),
            backup_path,
            report_path,
        )
    finally:
        conn.close()


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
    # F3: one-shot rebuild of legacy REAL money columns to TEXT-stored
    # Decimal strings.  No-op on already-migrated / fresh DBs.  Fail-loud
    # on error (raises) — see _money_text_migration.
    _money_text_migration(db_path)
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
        # F3: leverage is TEXT-stored Decimal.  Clamp to >= 1 without ever
        # converting through float; emit the canonical string.
        try:
            lev_dec = parse_money(d["leverage"] if d["leverage"] is not None else "1")
        except MoneyError:
            lev_dec = Decimal(1)
        if lev_dec < 1:
            lev_dec = Decimal(1)
        d["leverage"] = money_to_str(lev_dec)
    # Currency: legacy rows wrote '' or NULL; both should read back as
    # the explicit UNKNOWN sentinel so the frontend can render it
    # without a hardcoded $ fallback.
    if "currency" in d:
        raw_cur = d.get("currency") or ""
        text = str(raw_cur).strip().upper()
        d["currency"] = text if text else "UNKNOWN"
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
        cur = conn.execute(
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
        _track_ignored(cur, "user_reflections", reflection_id)
        conn.commit()
    finally:
        conn.close()


def soft_delete_reflection(
    reflection_id: str, db_path: Path = DB_PATH
) -> dict[str, Any]:
    """D1 fix: GDPR-style erasure of a single reflection row.

    Hard-deletes the row.  Reflections are operator-authored PII; the
    audit explicitly flagged the absence of any deletion endpoint as a
    privacy gap.  Hard delete (vs. tombstone) matches the operator's
    intent — they want it GONE.  ai_execution_count never changes;
    execution_gate is not consulted; this never reaches a broker.

    Returns a small audit record: ``{"deleted": True/False, "reflection_id": ...}``.
    """
    conn = _get_conn(db_path)
    try:
        before = conn.execute(
            "SELECT * FROM user_reflections WHERE reflection_id=?",
            (reflection_id,),
        ).fetchone()
        if not before:
            return {
                "deleted": False,
                "reflection_id": reflection_id,
                "reason": "not_found",
            }
        # F13 audit fix: the deletion and its audit row commit atomically —
        # a deleted reflection can never be unaccounted for.
        _write_audit_row(
            conn, "user_reflections", reflection_id, "DELETE", dict(before)
        )
        conn.execute(
            "DELETE FROM user_reflections WHERE reflection_id=?",
            (reflection_id,),
        )
        conn.commit()
    finally:
        conn.close()
    return {"deleted": True, "reflection_id": reflection_id}


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
        cur = conn.execute(
            "INSERT OR IGNORE INTO ai_discussion_summaries"
            " (summary_id, event_id, model_label, summary_text, summarized_at,"
            "  advisory_status, human_review_required, execution_mode, ai_execution_count)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                summary_id, event_id, model_label, summary_text, summarized_at,
                _ADVISORY_STATUS, 1, _EXECUTION_MODE, _AI_EXECUTION_COUNT,
            ),
        )
        _track_ignored(cur, "ai_discussion_summaries", summary_id)
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
    quantity: Any,  # F3: Decimal | str | int | float → stored as Decimal TEXT
    price: Any,  # F3: Decimal | str | int | float → stored as Decimal TEXT
    executed_at: str,
    thesis: str,
    notes: str,
    logged_by: str,
    db_path: Path = DB_PATH,
    *,
    leverage: Any = 1,  # F3: Decimal | str | int | float → Decimal TEXT
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
    currency: str = "",
    ai_model_used: str = "",
    leverage_ceiling: float = 1.0,
    leverage_breach: bool | int | None = None,
    leverage_policy_severity: str = "NONE",
    leverage_policy_reason: str = "",
    jurisdiction_group: str = "UNKNOWN",
    jurisdiction_resolution_source: str = "UNKNOWN_FAIL_CLOSED",
) -> None:
    """Insert a manual trade record. ``leverage`` is record-only (record-keeping
    of human leverage choice — no broker margin/execution implications).

    ``currency`` is the operator-selected native currency for the trade
    (e.g. INR for BHARTIARTL.NS, USD for AAPL, EUR for SAP.DE).  Legacy
    rows default to '' and read back as UNKNOWN.  Storing the currency
    NEVER grants execution permission and never calls a broker.

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
    # F3: money values are normalised to canonical Decimal strings at this
    # boundary; no float ever reaches the money columns.
    qty_text = _money_text(quantity, "quantity")
    price_text = _money_text(price, "price")
    try:
        lev_dec = parse_money(leverage if leverage is not None else "1")
    except MoneyError:
        lev_dec = Decimal(1)
    if lev_dec < 1:
        lev_dec = Decimal(1)
    lev = money_to_str(lev_dec)
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

    # Normalise currency at the persistence boundary.  Unsupported /
    # hostile / typo currencies fall through to '' (which reads back as
    # UNKNOWN), never to a hardcoded USD.
    try:
        try:
            from scripts.supported_currencies import normalise_currency
        except ModuleNotFoundError:  # pragma: no cover - script-style fallback
            from supported_currencies import normalise_currency  # type: ignore[no-redef]
        currency_norm = normalise_currency(currency)
        # Persist '' for UNKNOWN so legacy rows and explicit-unknown rows
        # share the same on-disk representation; the read path maps
        # both back to UNKNOWN consistently.
        if currency_norm == "UNKNOWN":
            currency_norm = ""
    except Exception:  # pragma: no cover - defensive
        currency_norm = ""

    # Normalise ai_model_used at the persistence boundary.  Free-text
    # operator label, trimmed and length-capped so a runaway paste cannot
    # bloat the row.  Empty / hostile input falls through to '' which the
    # UI renders as "—".  Storing this NEVER grants execution permission.
    ai_model_used_norm = str(ai_model_used or "").strip()
    if len(ai_model_used_norm) > 120:
        ai_model_used_norm = ai_model_used_norm[:120]

    # Normalise leverage-governance stamps at the persistence boundary.  These
    # are record-only: they never grant execution permission.
    try:
        lev_ceiling_norm = float(leverage_ceiling) if leverage_ceiling is not None else 1.0
    except (TypeError, ValueError):
        lev_ceiling_norm = 1.0
    lev_breach_norm = 1 if leverage_breach else 0
    lev_sev_norm = str(leverage_policy_severity or "NONE").strip().upper()
    if lev_sev_norm not in {"NONE", "WARNING", "POLICY_BREACH"}:
        lev_sev_norm = "NONE"
    lev_reason_norm = str(leverage_policy_reason or "").strip()
    if len(lev_reason_norm) > 500:
        lev_reason_norm = lev_reason_norm[:500]
    jur_group_norm = str(jurisdiction_group or "UNKNOWN").strip().upper()
    if jur_group_norm not in {"INDIA", "REST_OF_WORLD", "UNKNOWN"}:
        jur_group_norm = "UNKNOWN"
    jur_src_norm = str(jurisdiction_resolution_source or "UNKNOWN_FAIL_CLOSED").strip().upper()
    if jur_src_norm not in {
        "EXPLICIT", "SECURITIES_MASTER", "TICKER_HEURISTIC", "UNKNOWN_FAIL_CLOSED"
    }:
        jur_src_norm = "UNKNOWN_FAIL_CLOSED"

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
            trade_id, event_id, ticker, side, qty_text, price_text, executed_at,
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
        has_currency = "currency" in cols
        if has_currency:
            cols_sql = cols_sql + ", currency"
            vals = vals + (currency_norm,)
        has_ai_model_used = "ai_model_used" in cols
        if has_ai_model_used:
            cols_sql = cols_sql + ", ai_model_used"
            vals = vals + (ai_model_used_norm,)
        if "leverage_ceiling" in cols:
            cols_sql = cols_sql + (
                ", leverage_ceiling, leverage_breach,"
                " leverage_policy_severity, leverage_policy_reason, jurisdiction_group"
            )
            vals = vals + (
                lev_ceiling_norm,
                lev_breach_norm,
                lev_sev_norm,
                lev_reason_norm,
                jur_group_norm,
            )
        if "jurisdiction_resolution_source" in cols:
            cols_sql = cols_sql + ", jurisdiction_resolution_source"
            vals = vals + (jur_src_norm,)
        placeholders = ", ".join(["?"] * len(vals))
        cur = conn.execute(
            f"INSERT OR IGNORE INTO manual_trades ({cols_sql}) VALUES ({placeholders})",
            vals,
        )
        _track_ignored(cur, "manual_trades", trade_id)
        conn.commit()
    finally:
        conn.close()


def count_manual_trades_by_provenance(
    created_via: str, db_path: Path = DB_PATH
) -> int:
    """F10: count manual_trades rows with the given created_via stamp."""
    conn = _get_conn(db_path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(manual_trades)")}
        if "created_via" not in cols:
            return 0
        row = conn.execute(
            "SELECT COUNT(*) FROM manual_trades WHERE COALESCE(created_via,'')=?",
            (created_via,),
        ).fetchone()
        return int(row[0]) if row else 0
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
        # F13 audit fix: capture the pre-mutation state and commit it
        # atomically with the UPDATE so a bad cancellation is auditable.
        before = conn.execute(
            "SELECT trade_id, reconciliation_status, cancel_reason,"
            " cancelled_at FROM manual_trades WHERE trade_id=?",
            (str(trade_id or ""),),
        ).fetchone()
        if before is None:
            return False
        _write_audit_row(
            conn, "manual_trades", str(trade_id or ""), "UPDATE", dict(before)
        )
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
    actual_fill_price: Any,  # F3: Decimal | str | int | float → Decimal TEXT
    actual_quantity: Any,  # F3: Decimal | str | int | float → Decimal TEXT
    outcome_notes: str,
    pnl_estimate: Any,  # F3: Decimal | str | int | float → Decimal TEXT
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
    # F3: normalise money to canonical Decimal strings; refuse NaN/Inf.
    fill_text = _money_text(actual_fill_price, "actual_fill_price")
    qty_text = _money_text(actual_quantity, "actual_quantity")
    pnl_text = _money_text(
        pnl_estimate if pnl_estimate is not None else "0", "pnl_estimate"
    )
    conn = _get_conn(db_path)
    try:
        cur = conn.execute(
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
                fill_text, qty_text, outcome_notes,
                pnl_text, outcome_status,
                _EXECUTION_MODE, _AI_EXECUTION_COUNT,
                _ADVISORY_STATUS, 1,
                str(outcome_quality or ""),
                str(process_error or ""),
                str(process_error_notes or ""),
                str(mistake_tags or ""),
                str(lesson or ""),
            ),
        )
        _track_ignored(cur, "reconciliation_results", reconciliation_id)
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
# OHLCV bars (read-only historical price store for backtest evidence)
# ---------------------------------------------------------------------------


def insert_ohlcv_bars(bars: list[dict[str, Any]], db_path: Path = DB_PATH) -> int:
    """Idempotently upsert validated OHLCV bars. Returns rows written.

    Read-only historical data: every row carries advisory stamps and NEVER
    implies broker connectivity. Uniqueness is (ticker, date, source) so
    re-importing the same file is a no-op.
    """
    if not bars:
        return 0
    conn = _get_conn(db_path)
    written = 0
    try:
        for b in bars:
            cur = conn.execute(
                "INSERT OR IGNORE INTO ohlcv_bars"
                " (ticker, date, open, high, low, close, adjusted_close, volume,"
                "  source, data_vendor, exchange, currency, corporate_action_adjusted,"
                "  imported_at, advisory_only, human_execution_required, broker_api_called)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(b["ticker"]).strip().upper(),
                    str(b["date"]).strip(),
                    _coerce_num(b.get("open")),
                    _coerce_num(b.get("high")),
                    _coerce_num(b.get("low")),
                    _coerce_num(b.get("close")),
                    _coerce_num(b.get("adjusted_close")),
                    _coerce_num(b.get("volume")),
                    str(b.get("source", "")).strip(),
                    str(b.get("data_vendor", "")).strip(),
                    str(b.get("exchange", "")).strip(),
                    str(b.get("currency", "")).strip(),
                    1 if b.get("corporate_action_adjusted") else 0,
                    str(b.get("imported_at", "") or utc_timestamp()),
                    "ADVISORY_ONLY",
                    1,
                    0,
                ),
            )
            written += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        conn.commit()
    finally:
        conn.close()
    # F6: batch imports are idempotent by design, but the caller and the
    # health surface must still see how many rows were dropped.
    skipped = len(bars) - written
    if skipped > 0:
        global _IGNORED_INSERT_COUNT
        _IGNORED_INSERT_COUNT += skipped
        _logger.warning(
            "persistence: ignored duplicate insert into ohlcv_bars"
            " (%d of %d rows skipped, cumulative=%d)",
            skipped, len(bars), _IGNORED_INSERT_COUNT,
        )
    return written


def _coerce_num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def get_ohlcv_bars(ticker: str, db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    """Return all bars for a ticker ordered by date ascending."""
    conn = _get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM ohlcv_bars WHERE ticker=? ORDER BY date ASC",
            (str(ticker).strip().upper(),),
        ).fetchall()
    finally:
        conn.close()
    return [_to_dict(r) for r in rows]


def count_ohlcv_bars(db_path: Path = DB_PATH) -> int:
    conn = _get_conn(db_path)
    try:
        row = conn.execute("SELECT COUNT(*) AS c FROM ohlcv_bars").fetchone()
    finally:
        conn.close()
    return int(row["c"]) if row else 0


# ---------------------------------------------------------------------------
# Imported outcomes (paper / real-manual / backtest evidence, idempotent)
# ---------------------------------------------------------------------------

_IMPORTED_OUTCOME_COLS = (
    "outcome_id", "source_type", "ticker", "direction", "signal_id", "trade_id",
    "opened_at", "closed_at", "entry_price", "exit_price", "realized_pnl",
    "capital_at_risk", "leverage", "score_at_entry", "archetype", "signal_class",
    "jurisdiction_group", "notes",
)


def insert_imported_outcomes(rows: list[dict[str, Any]], db_path: Path = DB_PATH) -> int:
    """Idempotently upsert imported outcome rows (raw inputs). PK = outcome_id.

    Stores only the raw inputs; eligibility/quality/labels are recomputed on
    read via outcome_evidence.build_outcome so the math stays centralised.
    Read-only journal evidence — advisory stamps, never a broker call.
    """
    if not rows:
        return 0
    conn = _get_conn(db_path)
    written = 0
    try:
        for r in rows:
            cur = conn.execute(
                "INSERT OR IGNORE INTO imported_outcomes"
                " (outcome_id, source_type, ticker, direction, signal_id, trade_id,"
                "  opened_at, closed_at, entry_price, exit_price, realized_pnl,"
                "  capital_at_risk, leverage, score_at_entry, archetype, signal_class,"
                "  jurisdiction_group, notes, imported_at, advisory_only,"
                "  human_execution_required, broker_api_called)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(r["outcome_id"]),
                    str(r.get("source_type", "")).upper(),
                    str(r.get("ticker", "")).upper(),
                    str(r.get("direction", "UNKNOWN")).upper(),
                    _opt_str(r.get("signal_id")),
                    _opt_str(r.get("trade_id")),
                    _opt_str(r.get("opened_at")),
                    _opt_str(r.get("closed_at")),
                    _coerce_num(r.get("entry_price")),
                    _coerce_num(r.get("exit_price")),
                    _coerce_num(r.get("realized_pnl")),
                    _coerce_num(r.get("capital_at_risk")),
                    _coerce_num(r.get("leverage")) or 1.0,
                    _coerce_num(r.get("score_at_entry")),
                    _opt_str(r.get("archetype")),
                    _opt_str(r.get("signal_class")),
                    str(r.get("jurisdiction_group", "UNKNOWN")).upper(),
                    str(r.get("notes", "")),
                    utc_timestamp(),
                    "ADVISORY_ONLY", 1, 0,
                ),
            )
            written += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        conn.commit()
    finally:
        conn.close()
    # F6: surface dropped rows (idempotent re-imports included).
    skipped = len(rows) - written
    if skipped > 0:
        global _IGNORED_INSERT_COUNT
        _IGNORED_INSERT_COUNT += skipped
        _logger.warning(
            "persistence: ignored duplicate insert into imported_outcomes"
            " (%d of %d rows skipped, cumulative=%d)",
            skipped, len(rows), _IGNORED_INSERT_COUNT,
        )
    return written


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def get_imported_outcome_rows(db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    """Return raw imported-outcome input rows (for rebuilding evidence)."""
    conn = _get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM imported_outcomes ORDER BY outcome_id"
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
    db_path: Path | None = None,
) -> None:
    # Resolve DB_PATH lazily so tests that monkeypatch ``persistence.DB_PATH``
    # (or the conftest runtime-DB isolation fixture) see the override.  An
    # eager ``db_path=DB_PATH`` default binds at import time and would write
    # to the real runtime DB regardless of any later override.
    target = db_path if db_path is not None else DB_PATH
    conn = _get_conn(target)
    try:
        cur = conn.execute(
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
        _track_ignored(cur, "moltbook_entries", entry_id)
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
# Signal geometry — duplicate fingerprints + signal-cell index
#
# These tables persist the (probabilistic) duplicate-fingerprint hint and the
# (coarse) signal-cell index computed in scripts/signal_geometry_reflection.py
# so the audit trail survives process restarts.  Neither is canonical truth
# about a trade — SQLite's moltbook_entries / manual_trades remain canonical.
# Both upserts are advisory-only and never touch broker / execution state.
# ---------------------------------------------------------------------------


def upsert_duplicate_fingerprint(
    fingerprint: str,
    *,
    source_type: str = "",
    event_type: str = "",
    ticker: str = "",
    event_id: str = "",
    observed_date: str = "",
    thesis_excerpt: str = "",
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Record (or bump the seen-count of) one duplicate fingerprint.

    Returns ``{"is_new": bool, "seen_count": int}``.  The first sighting
    inserts; later sightings increment ``seen_count`` and refresh
    ``last_seen_at`` so the operator can audit how often an echo recurs.
    """
    target = db_path if db_path is not None else DB_PATH
    now = utc_timestamp()
    conn = _get_conn(target)
    try:
        # F6: SELECT-then-INSERT is check-then-act — without an immediate
        # write lock two concurrent callers both see "not found", one
        # INSERT is silently dropped, and seen_count undercounts.
        # BEGIN IMMEDIATE serialises the whole upsert.
        conn.execute("BEGIN IMMEDIATE")
        try:
            existing = conn.execute(
                "SELECT seen_count FROM duplicate_fingerprints WHERE fingerprint=?",
                (fingerprint,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    "INSERT INTO duplicate_fingerprints"
                    " (fingerprint, source_type, event_type, ticker, event_id,"
                    "  observed_date, thesis_excerpt, first_seen_at, last_seen_at,"
                    "  seen_count, advisory_status, human_review_required, advisory_only)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 1, 1)",
                    (
                        fingerprint, source_type, event_type, str(ticker).upper(),
                        event_id, observed_date, thesis_excerpt[:280], now, now,
                        _ADVISORY_STATUS,
                    ),
                )
                conn.commit()
                return {"is_new": True, "seen_count": 1}
            new_count = int(existing["seen_count"]) + 1
            conn.execute(
                "UPDATE duplicate_fingerprints SET seen_count=?, last_seen_at=?"
                " WHERE fingerprint=?",
                (new_count, now, fingerprint),
            )
            conn.commit()
            return {"is_new": False, "seen_count": new_count}
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()


def get_duplicate_fingerprints(
    ticker: str | None = None,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    target = db_path if db_path is not None else DB_PATH
    conn = _get_conn(target)
    try:
        if ticker:
            rows = conn.execute(
                "SELECT * FROM duplicate_fingerprints WHERE ticker=?"
                " ORDER BY last_seen_at DESC",
                (str(ticker).upper(),),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM duplicate_fingerprints ORDER BY last_seen_at DESC"
            ).fetchall()
    finally:
        conn.close()
    return [_to_dict(r) for r in rows]


def upsert_signal_cell(
    cell_key: str,
    *,
    source_type: str = "",
    jurisdiction: str = "",
    geography: str = "",
    sector: str = "",
    asset_tags: str = "",
    event_type: str = "",
    time_bucket: str = "",
    narrative_cluster: str = "",
    freshness_state: str = "unknown",
    chaos_score: float = 0.0,
    mvp_state: str = "candidate",
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Insert or refresh one signal-cell index row keyed by ``cell_key``."""
    target = db_path if db_path is not None else DB_PATH
    now = utc_timestamp()
    conn = _get_conn(target)
    try:
        existing = conn.execute(
            "SELECT seen_count FROM signal_cell_index WHERE cell_key=?",
            (cell_key,),
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO signal_cell_index"
                " (cell_key, source_type, jurisdiction, geography, sector,"
                "  asset_tags, event_type, time_bucket, narrative_cluster,"
                "  freshness_state, chaos_score, mvp_state, first_seen_at,"
                "  last_seen_at, seen_count, advisory_only, human_review_required)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, 1)",
                (
                    cell_key, source_type, jurisdiction, geography, sector,
                    asset_tags, event_type, time_bucket, narrative_cluster,
                    freshness_state, float(chaos_score), mvp_state, now, now,
                ),
            )
            conn.commit()
            return {"is_new": True, "seen_count": 1}
        new_count = int(existing["seen_count"]) + 1
        conn.execute(
            "UPDATE signal_cell_index SET seen_count=?, last_seen_at=?,"
            " freshness_state=?, chaos_score=?, mvp_state=? WHERE cell_key=?",
            (new_count, now, freshness_state, float(chaos_score), mvp_state, cell_key),
        )
        conn.commit()
        return {"is_new": False, "seen_count": new_count}
    finally:
        conn.close()


def get_signal_cells(db_path: Path | None = None) -> list[dict[str, Any]]:
    target = db_path if db_path is not None else DB_PATH
    conn = _get_conn(target)
    try:
        rows = conn.execute(
            "SELECT * FROM signal_cell_index ORDER BY last_seen_at DESC"
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
        "duplicate_fingerprints",
        "signal_cell_index",
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
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Return recent signal events, optionally filtered by source.

    Resolves ``DB_PATH`` lazily so tests that monkeypatch
    ``persistence.DB_PATH`` see the override.  Python default arguments
    bind at function-definition time, which we deliberately avoid here so
    /live-signals reads do not leak into the runtime DB during isolated
    tests.
    """
    target = db_path if db_path is not None else DB_PATH
    conn = _get_conn(target)
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
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Return the most recent source_run_log entry for each distinct source.

    One row per source_name, ordered newest-first.  Used by the
    /source-health/summary endpoint to drive the frontend warnings banner
    and per-source empty-state messages.

    Resolves ``DB_PATH`` lazily so tests that monkeypatch
    ``persistence.DB_PATH`` see the override — mirrors the sibling
    ``get_latest_refresh_run_per_source`` helper.
    """
    target = db_path if db_path is not None else DB_PATH
    conn = _get_conn(target)
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


def get_persisted_row_stats_per_source(
    db_path: Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Return per-source persisted-row statistics for the live-signals tabs.

    For each source_name present in ``signal_events`` this returns::

        {
          "row_count": int,
          "latest_fetched_at": str | None,
        }

    ``latest_fetched_at`` is the MAX(fetched_at) across all persisted rows
    for that source — the value the UI used to call "Latest fetched".  It
    is now exposed separately so the UI can render it as "Latest archived
    row" / "Latest persisted row" when the source is no longer current
    live (optional + missing config, planned, or otherwise non-live).

    DB_PATH is resolved lazily so tests that monkeypatch
    ``persistence.DB_PATH`` see the override.  Missing table -> empty dict.
    """
    target = db_path if db_path is not None else DB_PATH
    conn = _get_conn(target)
    try:
        try:
            rows = conn.execute(
                "SELECT source_name,"
                "       COUNT(*) AS n,"
                "       MAX(fetched_at) AS latest_fetched_at"
                "  FROM signal_events"
                " GROUP BY source_name"
            ).fetchall()
        except sqlite3.OperationalError:
            return {}
    finally:
        conn.close()
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        out[str(r["source_name"])] = {
            "row_count": int(r["n"] or 0),
            "latest_fetched_at": (
                str(r["latest_fetched_at"]) if r["latest_fetched_at"] else None
            ),
        }
    return out


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
    "upsert_duplicate_fingerprint",
    "get_duplicate_fingerprints",
    "upsert_signal_cell",
    "get_signal_cells",
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
