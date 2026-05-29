"""Canonical persistence for advisory external-evidence snapshots.

EXTERNAL_EVIDENCE_PERSISTENCE
=============================

Before this module the advisory external-evidence stage
(``scripts.external_advisory_evidence.build_external_evidence_bundle``) was
runtime-reachable from daily synthesis but *ephemeral*: the bundle was rendered
into the prompt and then discarded.  Nothing recorded *what evidence existed at
signal time*, so there was no way to later ask "did source X's evidence-at-time-t
actually help once the trade closed?".  That made the Moltbook calibration loop
(see ``scripts.external_evidence_moltbook_calibration``) impossible — you cannot
judge a forecast after the fact if the forecast was never stored.

This module is the canonical, SQLite-backed snapshot store.  It writes an
*immutable evidence-at-time-t* row for every accepted / rejected / error
evidence item, keyed by a deterministic ``snapshot_id`` so re-running a daily
synthesis never duplicates rows.

Truth model
-----------
* SQLite (``runtime/mvp_local.db``) is canonical.  JSONL is never canonical.
* The canonical DB path + connection conventions are reused from
  :mod:`scripts.persistence` (``DB_PATH`` / ``_get_conn``); this module does NOT
  open a parallel database.
* Schema is additive ``CREATE TABLE IF NOT EXISTS`` — safe to call repeatedly,
  never destructive.

Hard safety contract (every row, every return)
----------------------------------------------
``advisory_only=1``, ``human_execution_required=1``, ``execution_gate='LOCKED'``,
``broker_api_called=0``, ``ai_execution_count=0``,
``decision_impact in {NONE, ADVISORY_CONTEXT_ONLY}``,
``used_in_decision='EVIDENCE_ONLY'``,
``real_money_sizing_impact='PROHIBITED'``.

This module NEVER places a broker order, NEVER generates a BUY/SELL/ENTER/EXIT,
NEVER unlocks execution, and NEVER affects real-money sizing.  Any failure
degrades to a zero-decision-impact ``ERROR_SAFE`` result rather than raising —
persistence failure must never break the daily run.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

try:
    import scripts.persistence as _persistence
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import persistence as _persistence  # type: ignore[no-redef]

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

try:
    from scripts.runtime_common import utc_timestamp
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from runtime_common import utc_timestamp  # type: ignore[no-redef]


# --------------------------------------------------------------------------- vocab
DECISION_IMPACT_NONE = "NONE"
DECISION_IMPACT_ADVISORY = "ADVISORY_CONTEXT_ONLY"
USED_IN_DECISION = "EVIDENCE_ONLY"
REAL_MONEY_SIZING_IMPACT = "PROHIBITED"
EXECUTION_GATE_LOCKED = "LOCKED"

# Per-bundle persistence status vocabulary.
STATUS_PERSISTED = "PERSISTED"
STATUS_NO_EVIDENCE = "NO_EVIDENCE"
STATUS_DISABLED = "DISABLED"
STATUS_ERROR_SAFE = "ERROR_SAFE"

# Proof-status vocabulary for the persistence layer.
PROOF_PERSISTED = "PERSISTED_EVIDENCE_AT_TIME_T"
PROOF_NO_EVIDENCE = "NO_EVIDENCE_NO_DECISION_IMPACT"
PROOF_DISABLED = "DISABLED_NO_DECISION_IMPACT"
PROOF_FAILED_SAFE = "PERSISTENCE_FAILED_SAFE_NO_DECISION_IMPACT"

# The only out-going execution-permission strings a persisted snapshot may carry.
_SAFE_OUT_PERMISSIONS = frozenset({"WATCH_ONLY", "REJECT_ONLY"})

# Bundle statuses (from external_advisory_evidence) that mean "do not persist —
# nothing ran".  Anything else with items is persisted as evidence-at-time-t.
_DISABLED_BUNDLE_STATES = frozenset(
    {"DISABLED", "CONFIG_MISSING", "NO_ENABLED_ADAPTERS"}
)

# Status string an accepted item carries on the way out of the advisory stage.
_ACCEPTED_ITEM_STATUS = "ACCEPTED_EVIDENCE_ONLY"


_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS external_evidence_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id TEXT UNIQUE NOT NULL,
    signal_id TEXT,
    daily_run_id TEXT,
    candidate_id TEXT,
    ticker TEXT,
    asset_class TEXT,
    country TEXT,
    exchange TEXT,
    source_name TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    adapter_status TEXT NOT NULL,
    route_decision TEXT NOT NULL,
    execution_permission TEXT NOT NULL,
    advisory_only INTEGER NOT NULL DEFAULT 1,
    human_execution_required INTEGER NOT NULL DEFAULT 1,
    execution_gate TEXT NOT NULL DEFAULT 'LOCKED',
    broker_api_called INTEGER NOT NULL DEFAULT 0,
    ai_execution_count INTEGER NOT NULL DEFAULT 0,
    decision_impact TEXT NOT NULL DEFAULT 'ADVISORY_CONTEXT_ONLY',
    used_in_decision TEXT NOT NULL DEFAULT 'EVIDENCE_ONLY',
    real_money_sizing_impact TEXT NOT NULL DEFAULT 'PROHIBITED',
    score_delta REAL NOT NULL DEFAULT 0.0,
    score_delta_raw REAL,
    score_delta_clamped REAL,
    alignment_score REAL,
    reliability_weight REAL,
    router_multiplier REAL,
    evidence_quality REAL,
    confidence_raw REAL,
    confidence_calibrated REAL,
    risk_score REAL,
    downside_risk REAL,
    noise_penalty REAL,
    alignment_bonus REAL,
    downside_penalty REAL,
    -- Paper-only calibration readback (additive; nullable / default-safe).
    calibration_bucket_id TEXT,
    calibration_confidence_band TEXT,
    calibration_sample_count INTEGER,
    calibration_advisory_weight REAL,
    calibration_effective_weight REAL,
    calibration_harm_damping REAL,
    calibration_weight_source TEXT,
    calibration_reliability_label TEXT,
    score_delta_raw_uncalibrated REAL,
    score_delta_paper_calibrated REAL,
    paper_only_weight_applied INTEGER NOT NULL DEFAULT 0,
    real_money_weight_allowed INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT NOT NULL,
    payload_summary TEXT,
    reason TEXT,
    proof_status TEXT NOT NULL,
    generated_at_utc TEXT NOT NULL,
    persisted_at_utc TEXT NOT NULL,
    model_version TEXT,
    adapter_version TEXT,
    router_version TEXT,
    scoring_version TEXT,
    outcome_known INTEGER NOT NULL DEFAULT 0,
    outcome_linked_at_utc TEXT,
    outcome_trade_id TEXT,
    outcome_event_type TEXT,
    outcome_realized_return_pct REAL,
    outcome_direction TEXT,
    outcome_holding_days INTEGER,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_external_evidence_snapshot_id
    ON external_evidence_snapshots(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_external_evidence_signal_id
    ON external_evidence_snapshots(signal_id);
CREATE INDEX IF NOT EXISTS idx_external_evidence_daily_run_id
    ON external_evidence_snapshots(daily_run_id);
CREATE INDEX IF NOT EXISTS idx_external_evidence_ticker
    ON external_evidence_snapshots(ticker);
CREATE INDEX IF NOT EXISTS idx_external_evidence_source_name
    ON external_evidence_snapshots(source_name);
CREATE INDEX IF NOT EXISTS idx_external_evidence_outcome_known
    ON external_evidence_snapshots(outcome_known);
CREATE INDEX IF NOT EXISTS idx_external_evidence_generated_at_utc
    ON external_evidence_snapshots(generated_at_utc);

CREATE TABLE IF NOT EXISTS external_evidence_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    learning_id TEXT UNIQUE NOT NULL,
    snapshot_id TEXT NOT NULL,
    signal_id TEXT,
    trade_id TEXT,
    ticker TEXT,
    source_name TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    entry_timestamp_utc TEXT,
    exit_timestamp_utc TEXT,
    holding_days INTEGER,
    entry_price REAL,
    exit_price REAL,
    realized_return_pct REAL,
    realized_r_multiple REAL,
    outcome_y_0_or_1 INTEGER,
    outcome_direction TEXT,
    evidence_score_delta REAL,
    evidence_alignment_score REAL,
    evidence_confidence_calibrated REAL,
    evidence_downside_risk REAL,
    evidence_route_decision TEXT,
    forecast_direction TEXT,
    actual_direction TEXT,
    direction_correct INTEGER,
    forecast_error_pct REAL,
    evidence_helped INTEGER,
    evidence_harmed INTEGER,
    false_confidence INTEGER,
    risk_reducer_helped INTEGER,
    calibration_bucket TEXT,
    pre_update_weight REAL,
    post_update_weight REAL,
    sample_count_before INTEGER,
    sample_count_after INTEGER,
    advisory_only INTEGER NOT NULL DEFAULT 1,
    human_execution_required INTEGER NOT NULL DEFAULT 1,
    execution_gate TEXT NOT NULL DEFAULT 'LOCKED',
    broker_api_called INTEGER NOT NULL DEFAULT 0,
    ai_execution_count INTEGER NOT NULL DEFAULT 0,
    real_money_sizing_impact TEXT NOT NULL DEFAULT 'PROHIBITED',
    proof_status TEXT NOT NULL,
    created_at_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_external_evidence_outcomes_learning_id
    ON external_evidence_outcomes(learning_id);
CREATE INDEX IF NOT EXISTS idx_external_evidence_outcomes_snapshot_id
    ON external_evidence_outcomes(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_external_evidence_outcomes_trade_id
    ON external_evidence_outcomes(trade_id);
CREATE INDEX IF NOT EXISTS idx_external_evidence_outcomes_source_name
    ON external_evidence_outcomes(source_name);
CREATE INDEX IF NOT EXISTS idx_external_evidence_outcomes_bucket
    ON external_evidence_outcomes(calibration_bucket);

CREATE TABLE IF NOT EXISTS external_evidence_calibration_buckets (
    bucket_id TEXT PRIMARY KEY,
    source_name TEXT,
    evidence_type TEXT,
    route_decision TEXT,
    confidence_band TEXT,
    sample_count INTEGER,
    help_count INTEGER,
    harm_count INTEGER,
    false_confidence_count INTEGER,
    help_rate REAL,
    harm_rate REAL,
    false_confidence_rate REAL,
    raw_reliability REAL,
    sample_multiplier REAL,
    advisory_weight REAL,
    real_money_weight_allowed INTEGER NOT NULL DEFAULT 0,
    real_money_sizing_impact TEXT NOT NULL DEFAULT 'PROHIBITED',
    last_updated_utc TEXT,
    proof_status TEXT
);
"""


# Additive paper-only calibration columns.  Stored as (name, column-def) so the
# same list drives both the CREATE TABLE body (above) and the idempotent
# ALTER TABLE migration for databases that predate this sprint.
_CALIBRATION_SNAPSHOT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("calibration_bucket_id", "TEXT"),
    ("calibration_confidence_band", "TEXT"),
    ("calibration_sample_count", "INTEGER"),
    ("calibration_advisory_weight", "REAL"),
    ("calibration_effective_weight", "REAL"),
    ("calibration_harm_damping", "REAL"),
    ("calibration_weight_source", "TEXT"),
    ("calibration_reliability_label", "TEXT"),
    ("score_delta_raw_uncalibrated", "REAL"),
    ("score_delta_paper_calibrated", "REAL"),
    ("paper_only_weight_applied", "INTEGER NOT NULL DEFAULT 0"),
    ("real_money_weight_allowed", "INTEGER NOT NULL DEFAULT 0"),
)


# ----------------------------------------------------------------------- helpers
def _migrate_calibration_columns(conn: sqlite3.Connection) -> None:
    """Idempotently ALTER TABLE to add any missing calibration columns.

    For a fresh DB the columns already exist (CREATE TABLE body).  For a DB that
    predates this sprint, each missing column is added with ``ADD COLUMN`` —
    purely additive, never destructive, and old rows still load (new columns
    read as NULL / their declared default).
    """
    try:
        existing = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(external_evidence_snapshots)"
            ).fetchall()
        }
    except sqlite3.Error:  # pragma: no cover - table absent is handled by CREATE
        return
    if not existing:
        return
    for name, coldef in _CALIBRATION_SNAPSHOT_COLUMNS:
        if name not in existing:
            conn.execute(
                f"ALTER TABLE external_evidence_snapshots ADD COLUMN {name} {coldef}"
            )


def ensure_external_evidence_schema(conn: sqlite3.Connection) -> None:
    """Idempotently create the external-evidence tables + indexes.

    Safe to run repeatedly; never drops or rewrites existing data.  Also runs
    the additive calibration-column migration for pre-existing databases.
    """
    conn.executescript(_SCHEMA_SQL)
    _migrate_calibration_columns(conn)
    conn.commit()


def _open(db_path: Path | None = None) -> sqlite3.Connection:
    """Open a canonical connection with the external-evidence schema ensured.

    Reuses :func:`scripts.persistence._get_conn` so the canonical DB path,
    pragmas and row factory are identical to the rest of the MVP.  Resolves
    ``persistence.DB_PATH`` lazily so the test isolation fixture (which
    monkeypatches it to a temp file) is honoured.
    """
    target = Path(db_path) if db_path is not None else Path(_persistence.DB_PATH)
    conn = _persistence._get_conn(target)
    ensure_external_evidence_schema(conn)
    return conn


def _f(value: Any) -> float | None:
    """Coerce to float or None (never raises)."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN guard
        return None
    return f


def _s(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _utc_minute_bucket(generated_at_utc: str) -> str:
    """Return a stable ``YYYY-MM-DDTHH:MMZ`` bucket from an ISO timestamp.

    Snapshot ids must be stable even if the exact second drifts between two
    runs of the same daily synthesis, so we bucket to the minute.  A
    non-parseable input degrades to its first 16 characters (still stable).
    """
    text = _s(generated_at_utc)
    if not text:
        return ""
    norm = text.replace("Z", "+00:00")
    try:
        from datetime import datetime

        dt = datetime.fromisoformat(norm)
        return dt.strftime("%Y-%m-%dT%H:%MZ")
    except (ValueError, TypeError):
        return text[:16]


def make_external_evidence_snapshot_id(
    *,
    daily_run_id: str = "",
    signal_id: str = "",
    candidate_id: str = "",
    ticker: str = "",
    source_name: str = "",
    evidence_type: str = "",
    generated_at_utc: str = "",
    route_decision: str = "",
) -> str:
    """Deterministic snapshot id.

    ``signal_id`` falls back to ``candidate_id``; when both are missing the
    remaining (ticker, daily_run_id, source_name) components keep the hash
    unique.  Bucketed to the minute so a re-run of the same synthesis is a
    no-op upsert rather than a duplicate row.
    """
    signal_key = _s(signal_id) or _s(candidate_id)
    bucket = _utc_minute_bucket(generated_at_utc)
    raw = "|".join(
        [
            _s(daily_run_id),
            signal_key,
            _s(ticker),
            _s(source_name),
            _s(evidence_type),
            bucket,
            _s(route_decision),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _safe_permission(value: Any) -> str:
    perm = _s(value).upper()
    return perm if perm in _SAFE_OUT_PERMISSIONS else "WATCH_ONLY"


def normalize_external_evidence_item(
    bundle_item: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Turn one advisory bundle item into a snapshot row dict.

    Forces the advisory safety stamps, WATCH_ONLY / EVIDENCE_ONLY, and
    ``real_money_sizing_impact=PROHIBITED`` regardless of what the adapter
    claimed.  The result is JSON-serializable and ready to insert.
    """
    item = dict(bundle_item or {})
    ctx = dict(context or {})

    source_name = _s(item.get("source_name")) or "unknown"
    evidence_type = _s(item.get("evidence_type")) or "UNKNOWN"
    route_decision = _s(item.get("route_decision")).upper() or "REJECT"
    status = _s(item.get("status"))

    payload_summary = item.get("payload_summary")
    if not isinstance(payload_summary, dict):
        payload_summary = {}

    # Accepted evidence carries advisory context; everything else (rejected /
    # error) is recorded with zero decision impact.
    accepted = status == _ACCEPTED_ITEM_STATUS
    decision_impact = DECISION_IMPACT_ADVISORY if accepted else DECISION_IMPACT_NONE

    generated_at = _s(ctx.get("generated_at_utc")) or utc_timestamp()
    ticker = _s(item.get("ticker")) or _s(ctx.get("ticker")) or _s(
        payload_summary.get("ticker")
    )
    daily_run_id = _s(ctx.get("daily_run_id"))
    signal_id = _s(ctx.get("signal_id")) or _s(item.get("signal_id"))
    candidate_id = _s(ctx.get("candidate_id"))

    snapshot_id = make_external_evidence_snapshot_id(
        daily_run_id=daily_run_id,
        signal_id=signal_id,
        candidate_id=candidate_id,
        ticker=ticker,
        source_name=source_name,
        evidence_type=evidence_type,
        generated_at_utc=generated_at,
        route_decision=route_decision,
    )

    score_delta = _f(item.get("score_delta")) or 0.0
    now = utc_timestamp()

    row = {
        "snapshot_id": snapshot_id,
        "signal_id": signal_id or None,
        "daily_run_id": daily_run_id or None,
        "candidate_id": candidate_id or None,
        "ticker": ticker or None,
        "asset_class": _s(ctx.get("asset_class")) or None,
        "country": _s(ctx.get("country")) or None,
        "exchange": _s(ctx.get("exchange")) or None,
        "source_name": source_name,
        "evidence_type": evidence_type,
        "adapter_status": _s(item.get("status")) or "UNKNOWN",
        "route_decision": route_decision,
        "execution_permission": _safe_permission(item.get("execution_permission")),
        # Hard safety stamps — forced, never trusted from the adapter.
        "advisory_only": 1,
        "human_execution_required": 1,
        "execution_gate": EXECUTION_GATE_LOCKED,
        "broker_api_called": 0,
        "ai_execution_count": 0,
        "decision_impact": decision_impact,
        "used_in_decision": USED_IN_DECISION,
        "real_money_sizing_impact": REAL_MONEY_SIZING_IMPACT,
        # Scoring fields.
        "score_delta": score_delta,
        "score_delta_raw": _f(item.get("score_delta_raw")),
        "score_delta_clamped": score_delta,
        "alignment_score": _f(item.get("alignment_score")),
        "reliability_weight": _f(item.get("reliability_weight")),
        "router_multiplier": _f(item.get("router_safety_multiplier")),
        "evidence_quality": _f(item.get("evidence_quality_multiplier")),
        "confidence_raw": _f(payload_summary.get("KRONOS_CONFIDENCE_RAW")),
        "confidence_calibrated": _f(
            payload_summary.get("KRONOS_CONFIDENCE_CALIBRATED")
        ),
        "risk_score": _f(payload_summary.get("KRONOS_DOWNSIDE_PATH_RISK")),
        "downside_risk": _f(payload_summary.get("KRONOS_DOWNSIDE_PATH_RISK")),
        "noise_penalty": _f(payload_summary.get("KRONOS_NOISE_PENALTY")),
        "alignment_bonus": _f(payload_summary.get("KRONOS_ALIGNMENT_BONUS")),
        "downside_penalty": _f(payload_summary.get("KRONOS_DOWNSIDE_PENALTY")),
        # Paper-only calibration readback (additive; null-safe for old rows).
        "calibration_bucket_id": _s(item.get("calibration_bucket_id")) or None,
        "calibration_confidence_band": _s(item.get("calibration_confidence_band"))
        or None,
        "calibration_sample_count": item.get("calibration_sample_count"),
        "calibration_advisory_weight": _f(item.get("calibration_advisory_weight")),
        "calibration_effective_weight": _f(item.get("calibration_effective_weight")),
        "calibration_harm_damping": _f(item.get("calibration_harm_damping")),
        "calibration_weight_source": _s(item.get("calibration_weight_source")) or None,
        "calibration_reliability_label": _s(item.get("calibration_reliability_label"))
        or None,
        "score_delta_raw_uncalibrated": _f(item.get("score_delta_raw_uncalibrated")),
        "score_delta_paper_calibrated": _f(item.get("score_delta_paper_calibrated")),
        # Hard safety stamps — forced, never trusted from the adapter.
        "paper_only_weight_applied": 1 if item.get("paper_only_weight_applied") else 0,
        "real_money_weight_allowed": 0,
        # Payloads (summary kept small; full payload retained for calibration).
        "payload_json": json.dumps(payload_summary, sort_keys=True, default=str),
        "payload_summary": _short_summary(payload_summary),
        "reason": _s(item.get("reason"))[:1000] or None,
        "proof_status": _s(item.get("proof_status")) or "UNKNOWN",
        "generated_at_utc": generated_at,
        "persisted_at_utc": now,
        "model_version": _s(payload_summary.get("KRONOS_MODEL_NAME")) or None,
        "adapter_version": _s(ctx.get("adapter_version")) or None,
        "router_version": _s(ctx.get("router_version")) or None,
        "scoring_version": _s(ctx.get("scoring_version")) or None,
        "outcome_known": 0,
        "outcome_linked_at_utc": None,
        "outcome_trade_id": None,
        "outcome_event_type": None,
        "outcome_realized_return_pct": None,
        "outcome_direction": None,
        "outcome_holding_days": None,
        "created_at_utc": now,
        "updated_at_utc": now,
    }
    return row


def _short_summary(payload_summary: dict[str, Any]) -> str:
    """A compact, frontend-safe summary string (never a payload blob dump)."""
    keys = (
        "KRONOS_STATUS",
        "KRONOS_FORECAST_RETURN_PCT",
        "KRONOS_CONFIDENCE_CALIBRATED",
        "forecast_direction",
    )
    parts = []
    for k in keys:
        if k in payload_summary:
            parts.append(f"{k}={payload_summary[k]}")
    return "; ".join(parts)[:500]


_SNAPSHOT_COLUMNS = (
    "snapshot_id", "signal_id", "daily_run_id", "candidate_id", "ticker",
    "asset_class", "country", "exchange", "source_name", "evidence_type",
    "adapter_status", "route_decision", "execution_permission",
    "advisory_only", "human_execution_required", "execution_gate",
    "broker_api_called", "ai_execution_count", "decision_impact",
    "used_in_decision", "real_money_sizing_impact", "score_delta",
    "score_delta_raw", "score_delta_clamped", "alignment_score",
    "reliability_weight", "router_multiplier", "evidence_quality",
    "confidence_raw", "confidence_calibrated", "risk_score", "downside_risk",
    "noise_penalty", "alignment_bonus", "downside_penalty",
    "calibration_bucket_id", "calibration_confidence_band",
    "calibration_sample_count", "calibration_advisory_weight",
    "calibration_effective_weight", "calibration_harm_damping",
    "calibration_weight_source", "calibration_reliability_label",
    "score_delta_raw_uncalibrated", "score_delta_paper_calibrated",
    "paper_only_weight_applied", "real_money_weight_allowed", "payload_json",
    "payload_summary", "reason", "proof_status", "generated_at_utc",
    "persisted_at_utc", "model_version", "adapter_version", "router_version",
    "scoring_version", "outcome_known", "outcome_linked_at_utc",
    "outcome_trade_id", "outcome_event_type", "outcome_realized_return_pct",
    "outcome_direction", "outcome_holding_days", "created_at_utc",
    "updated_at_utc",
)


def _insert_snapshot_row(conn: sqlite3.Connection, row: dict[str, Any]) -> bool:
    """Insert one snapshot row; returns True if a new row was written.

    Idempotent on ``snapshot_id`` via ``INSERT OR IGNORE`` + the UNIQUE
    constraint.  Re-persisting identical evidence-at-time-t is a no-op.
    """
    placeholders = ", ".join(["?"] * len(_SNAPSHOT_COLUMNS))
    cols = ", ".join(_SNAPSHOT_COLUMNS)
    vals = tuple(row.get(c) for c in _SNAPSHOT_COLUMNS)
    cur = conn.execute(
        f"INSERT OR IGNORE INTO external_evidence_snapshots ({cols})"
        f" VALUES ({placeholders})",
        vals,
    )
    return cur.rowcount > 0


def _summary(
    *,
    status: str,
    persisted_count: int,
    skipped_count: int,
    snapshot_ids: list[str],
    decision_impact: str,
    proof_status: str,
    enabled: bool,
) -> dict[str, Any]:
    return {
        "enabled": enabled,
        "status": status,
        "persisted_count": persisted_count,
        "skipped_count": skipped_count,
        "snapshot_ids": snapshot_ids,
        "decision_impact": decision_impact,
        "proof_status": proof_status,
        "canonical_store": "SQLITE",
        "jsonl_is_canonical": False,
        "real_money_sizing_impact": REAL_MONEY_SIZING_IMPACT,
        "advisory_only": True,
        "human_execution_required": True,
        "execution_gate": EXECUTION_GATE_LOCKED,
        "broker_api_called": False,
        "ai_execution_count": 0,
    }


def persist_external_evidence_bundle(
    bundle: dict[str, Any],
    context: dict[str, Any] | None = None,
    *,
    db_path: Path | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Persist accepted/rejected/error evidence items from a bundle.

    Returns a summary dict (Section 4 + Section 11 superset).  Disabled
    bundles and empty bundles write nothing.  Any failure degrades to an
    ``ERROR_SAFE`` summary with zero decision impact — it never raises, so
    the daily run is never blocked.
    """
    ctx = dict(context or {})
    bundle = dict(bundle or {})

    bundle_status = _s(bundle.get("external_evidence_status"))
    enabled = bool(bundle.get("external_evidence_enabled"))

    # Disabled / config-missing / no-adapters → record DISABLED, write nothing.
    if not enabled or bundle_status in _DISABLED_BUNDLE_STATES:
        return _summary(
            status=STATUS_DISABLED,
            persisted_count=0,
            skipped_count=0,
            snapshot_ids=[],
            decision_impact=DECISION_IMPACT_NONE,
            proof_status=PROOF_DISABLED,
            enabled=False,
        )

    items = bundle.get("external_evidence_items") or []
    if not items:
        return _summary(
            status=STATUS_NO_EVIDENCE,
            persisted_count=0,
            skipped_count=0,
            snapshot_ids=[],
            decision_impact=DECISION_IMPACT_NONE,
            proof_status=PROOF_NO_EVIDENCE,
            enabled=True,
        )

    # Carry the bundle's generation timestamp so snapshot ids bucket stably.
    ctx.setdefault("generated_at_utc", _s(bundle.get("generated_at_utc")))

    owned = conn is None
    try:
        if conn is None:
            conn = _open(db_path)
        else:
            ensure_external_evidence_schema(conn)

        persisted: list[str] = []
        skipped = 0
        for raw_item in items:
            if not isinstance(raw_item, dict):
                continue
            row = normalize_external_evidence_item(raw_item, ctx)
            if _insert_snapshot_row(conn, row):
                persisted.append(row["snapshot_id"])
            else:
                skipped += 1
        conn.commit()
    except Exception:  # noqa: BLE001 - persistence failure is failed-safe
        if conn is not None and owned:
            try:
                conn.close()
            except Exception:  # pragma: no cover - defensive
                pass
        return _summary(
            status=STATUS_ERROR_SAFE,
            persisted_count=0,
            skipped_count=0,
            snapshot_ids=[],
            decision_impact=DECISION_IMPACT_NONE,
            proof_status=PROOF_FAILED_SAFE,
            enabled=True,
        )
    finally:
        if conn is not None and owned:
            try:
                conn.close()
            except Exception:  # pragma: no cover - defensive
                pass

    # Accepted items carry advisory context; a bundle of only rejected/error
    # items has zero decision impact.
    has_advisory = any(
        _s(i.get("status")) == _ACCEPTED_ITEM_STATUS
        for i in items
        if isinstance(i, dict)
    )
    return _summary(
        status=STATUS_PERSISTED,
        persisted_count=len(persisted),
        skipped_count=skipped,
        snapshot_ids=persisted,
        decision_impact=(
            DECISION_IMPACT_ADVISORY if has_advisory else DECISION_IMPACT_NONE
        ),
        proof_status=PROOF_PERSISTED,
        enabled=True,
    )


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a snapshot/outcome row to a dict with safety stamps enforced."""
    d = dict(row)
    if "advisory_only" in d:
        d["advisory_only"] = True
    if "human_execution_required" in d:
        d["human_execution_required"] = True
    if "execution_gate" in d:
        d["execution_gate"] = EXECUTION_GATE_LOCKED
    if "broker_api_called" in d:
        d["broker_api_called"] = False
    if "ai_execution_count" in d:
        d["ai_execution_count"] = 0
    if "real_money_sizing_impact" in d:
        d["real_money_sizing_impact"] = REAL_MONEY_SIZING_IMPACT
    if "real_money_weight_allowed" in d:
        d["real_money_weight_allowed"] = False
    return d


def load_external_evidence_for_signal(
    signal_id: str,
    *,
    db_path: Path | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Return all persisted snapshots for a signal id (read-only)."""
    owned = conn is None
    if conn is None:
        conn = _open(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM external_evidence_snapshots WHERE signal_id=?"
            " ORDER BY generated_at_utc ASC, id ASC",
            (_s(signal_id),),
        ).fetchall()
    finally:
        if owned:
            conn.close()
    return [_row_to_dict(r) for r in rows]


def load_unlinked_external_evidence_for_trade(
    *,
    signal_id: str = "",
    ticker: str = "",
    db_path: Path | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Return snapshots not yet linked to an outcome, matched by signal/ticker.

    Matching precedence: a non-empty ``signal_id`` matches exactly; otherwise
    a non-empty ``ticker`` matches.  Only ``outcome_known=0`` rows are
    returned so an outcome is never double-counted.
    """
    sig = _s(signal_id)
    tkr = _s(ticker).upper()
    if not sig and not tkr:
        return []
    owned = conn is None
    if conn is None:
        conn = _open(db_path)
    try:
        if sig:
            rows = conn.execute(
                "SELECT * FROM external_evidence_snapshots"
                " WHERE outcome_known=0 AND signal_id=?"
                " ORDER BY generated_at_utc ASC, id ASC",
                (sig,),
            ).fetchall()
            if rows:
                return [_row_to_dict(r) for r in rows]
        if tkr:
            rows = conn.execute(
                "SELECT * FROM external_evidence_snapshots"
                " WHERE outcome_known=0 AND UPPER(ticker)=?"
                " ORDER BY generated_at_utc ASC, id ASC",
                (tkr,),
            ).fetchall()
            return [_row_to_dict(r) for r in rows]
        return []
    finally:
        if owned:
            conn.close()


def mark_external_evidence_outcome_known(
    snapshot_id: str,
    outcome_fields: dict[str, Any] | None = None,
    *,
    db_path: Path | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Mark a snapshot as outcome-linked and record the realized outcome.

    Pure record-keeping: never touches execution / broker state.
    """
    fields = dict(outcome_fields or {})
    owned = conn is None
    if conn is None:
        conn = _open(db_path)
    try:
        conn.execute(
            "UPDATE external_evidence_snapshots SET"
            "  outcome_known=1,"
            "  outcome_linked_at_utc=?,"
            "  outcome_trade_id=?,"
            "  outcome_event_type=?,"
            "  outcome_realized_return_pct=?,"
            "  outcome_direction=?,"
            "  outcome_holding_days=?,"
            "  updated_at_utc=?"
            " WHERE snapshot_id=?",
            (
                _s(fields.get("outcome_linked_at_utc")) or utc_timestamp(),
                _s(fields.get("outcome_trade_id")) or None,
                _s(fields.get("outcome_event_type")) or None,
                _f(fields.get("outcome_realized_return_pct")),
                _s(fields.get("outcome_direction")) or None,
                fields.get("outcome_holding_days"),
                utc_timestamp(),
                _s(snapshot_id),
            ),
        )
        conn.commit()
    finally:
        if owned:
            conn.close()


__all__ = [
    "ensure_external_evidence_schema",
    "make_external_evidence_snapshot_id",
    "normalize_external_evidence_item",
    "persist_external_evidence_bundle",
    "load_external_evidence_for_signal",
    "load_unlinked_external_evidence_for_trade",
    "mark_external_evidence_outcome_known",
    "STATUS_PERSISTED",
    "STATUS_NO_EVIDENCE",
    "STATUS_DISABLED",
    "STATUS_ERROR_SAFE",
    "PROOF_PERSISTED",
    "PROOF_FAILED_SAFE",
    "DECISION_IMPACT_NONE",
    "DECISION_IMPACT_ADVISORY",
    "REAL_MONEY_SIZING_IMPACT",
]
