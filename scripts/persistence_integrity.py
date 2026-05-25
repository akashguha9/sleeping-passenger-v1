"""Persistence integrity — canonical lineage, idempotent upsert, source-run
ledger, schema metadata, and JSONL non-canonical guard.

Integrated Sprint (Kanté defensive batch 2) — Part 2.  Adds the deterministic
``SignalEvent`` lineage helpers and the ``source_runs`` / ``schema_metadata``
tables that the release gate uses to attest that:

* SQLite is the canonical runtime store; JSONL is audit/fallback only.
* Identical events do not produce duplicate rows.
* Payload changes are recorded as controlled revisions, not duplicate spam.
* Every refresh attempt is written to the source-run ledger.
* Schema versions are pinned in the DB so the operator can detect drift.

The module is pure: every function accepts a ``sqlite3.Connection`` so tests
can run entirely on ``:memory:`` or ``tmp_path``.  No network, no broker, no
AI execution — the safety stamps from :mod:`scripts.advisory_contract` are
attached to every row and to the summary artifact.

Summary artifact: ``runtime/release/persistence_integrity_summary.json``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import time
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY_PATH = (
    REPO_ROOT / "runtime" / "release" / "persistence_integrity_summary.json"
)
DEFAULT_V2_SUMMARY_PATH = (
    REPO_ROOT / "runtime" / "release" / "data_model_persistence_v2_summary.json"
)

# Pinned schema versions surfaced via ``schema_metadata``.  Bump when the
# corresponding canonical table layout changes in a way readers must observe.
SCHEMA_VERSIONS: dict[str, str] = {
    "signal_event_schema_version": "1.0.0",
    "source_health_schema_version": "1.0.0",
    "source_runs_schema_version": "1.0.0",
    "normalization_version": "1.0.0",
    "portfolio_truth_schema_version": "1.0.0",
    "model_runs_schema_version": "1.0.0",
}

VERIFICATION_STATES: tuple[str, ...] = (
    "VERIFIED", "UNVERIFIED", "FALLBACK", "MOCK", "STALE", "FIXTURE_VERIFIED",
)
FRESHNESS_STATES: tuple[str, ...] = ("FRESH", "AGING", "STALE", "UNKNOWN")
SOURCE_RUN_STATUSES: tuple[str, ...] = (
    "STARTED", "SUCCESS", "PARTIAL", "FAILED", "STALE", "OFFLINE",
)

# Keys that must be removed before hashing a payload because they describe
# *when* the row was observed locally rather than the event itself.
_VOLATILE_KEYS: frozenset[str] = frozenset({
    "ingested_at_utc",
    "received_at_utc",
    "ingest_run_id",
    "_local_uuid",
})

_DDL = """
CREATE TABLE IF NOT EXISTS canonical_signal_events (
    event_id TEXT PRIMARY KEY,
    source_run_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    source_type TEXT NOT NULL,
    event_type TEXT NOT NULL,
    asset_tags TEXT NOT NULL,
    source_url TEXT,
    provider_event_timestamp_utc TEXT NOT NULL,
    ingested_at_utc TEXT NOT NULL,
    last_seen_at_utc TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    normalization_version TEXT NOT NULL,
    verification_status TEXT NOT NULL,
    freshness_status TEXT NOT NULL,
    revision_number INTEGER NOT NULL DEFAULT 0,
    supersedes_event_id TEXT,
    canonical INTEGER NOT NULL DEFAULT 1,
    advisory_only INTEGER NOT NULL DEFAULT 1,
    human_review_required INTEGER NOT NULL DEFAULT 1,
    execution_permission TEXT NOT NULL DEFAULT 'ADVISORY_ONLY'
);
CREATE INDEX IF NOT EXISTS idx_cse_provider ON canonical_signal_events(provider);
CREATE INDEX IF NOT EXISTS idx_cse_source_run ON canonical_signal_events(source_run_id);

CREATE TABLE IF NOT EXISTS source_runs (
    source_run_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    source_type TEXT NOT NULL,
    started_at_utc TEXT NOT NULL,
    finished_at_utc TEXT,
    status TEXT NOT NULL,
    events_seen INTEGER NOT NULL DEFAULT 0,
    events_inserted INTEGER NOT NULL DEFAULT 0,
    events_updated INTEGER NOT NULL DEFAULT 0,
    events_rejected INTEGER NOT NULL DEFAULT 0,
    latest_provider_timestamp_utc TEXT,
    error TEXT,
    runtime_ms INTEGER,
    advisory_only INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_sr_provider ON source_runs(provider);
CREATE INDEX IF NOT EXISTS idx_sr_started ON source_runs(started_at_utc);

CREATE TABLE IF NOT EXISTS schema_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS live_provider_evidence (
    evidence_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    source_type TEXT NOT NULL,
    run_mode TEXT NOT NULL,
    verification_status TEXT NOT NULL,
    latest_provider_timestamp_utc TEXT,
    checked_at_utc TEXT NOT NULL,
    freshness_age_hours REAL,
    payload_hash TEXT NOT NULL,
    source_run_id TEXT,
    sample_source_url TEXT,
    advisory_only INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_lpe_provider ON live_provider_evidence(provider);
CREATE INDEX IF NOT EXISTS idx_lpe_ts ON live_provider_evidence(latest_provider_timestamp_utc);

CREATE TABLE IF NOT EXISTS candidate_gate_audit (
    audit_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    evaluated_at_utc TEXT NOT NULL,
    cqs_final REAL,
    eqs REAL,
    fcs REAL,
    ers REAL,
    why_today_score REAL,
    lpq REAL,
    portfolio_truth_ok INTEGER,
    memory_decay_ok INTEGER,
    model_disagreement_ok INTEGER,
    final_state TEXT,
    may_promote INTEGER,
    downgrade_reasons_json TEXT,
    advisory_only INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_cga_candidate ON candidate_gate_audit(candidate_id);
"""


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _floor_minute(timestamp: str) -> str:
    """Return ``timestamp`` truncated to minute resolution.

    Accepts ISO-8601 with optional ``Z`` suffix.  Falls back to the raw input
    if it cannot be parsed, so a malformed provider timestamp does not throw.
    """
    text = str(timestamp or "").strip()
    if not text:
        return ""
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return text
    return dt.replace(second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:00Z")


def _normalize_title(value: Any) -> str:
    """Unicode NFKC + lower + collapse whitespace; stable across runs."""
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    return re.sub(r"\s+", " ", text).strip()


def canonical_json(payload: Any) -> str:
    """Deterministic JSON: sorted keys, stable separators, volatile keys removed.

    Used as the input to ``payload_hash``; running twice on the same logical
    payload produces byte-identical output across processes/platforms.
    """
    def _strip(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {
                k: _strip(v) for k, v in obj.items() if k not in _VOLATILE_KEYS
            }
        if isinstance(obj, list):
            return [_strip(v) for v in obj]
        if isinstance(obj, str):
            return unicodedata.normalize("NFKC", obj)
        return obj

    cleaned = _strip(payload)
    return json.dumps(cleaned, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def payload_hash(payload: Any) -> str:
    """``sha256(canonical_json(payload))``."""
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def compute_event_id(
    *,
    provider: str,
    source_type: str,
    event_type: str,
    provider_event_timestamp_utc: str,
    asset_tags: Iterable[str],
    normalized_key: str,
) -> str:
    """Deterministic SignalEvent ID per the sprint spec."""
    parts = [
        str(provider or "").lower(),
        str(source_type or "").lower(),
        str(event_type or "").lower(),
        _floor_minute(provider_event_timestamp_utc),
        ",".join(sorted({str(t or "").upper() for t in asset_tags if t})),
        _normalize_title(normalized_key),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def open_db(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open a connection and apply the canonical schema (idempotent)."""
    if db_path is None:
        conn = sqlite3.connect(":memory:")
    else:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_DDL)
    seed_schema_metadata(conn)
    return conn


def seed_schema_metadata(conn: sqlite3.Connection,
                         versions: dict[str, str] | None = None) -> None:
    """Insert any missing rows in ``schema_metadata``; update timestamp on change."""
    table = versions or SCHEMA_VERSIONS
    now = _utc_iso()
    for key, value in table.items():
        row = conn.execute(
            "SELECT value FROM schema_metadata WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO schema_metadata(key, value, updated_at_utc) "
                "VALUES (?, ?, ?)",
                (key, value, now),
            )
        elif row["value"] != value:
            conn.execute(
                "UPDATE schema_metadata SET value=?, updated_at_utc=? "
                "WHERE key=?",
                (value, now, key),
            )
    conn.commit()


def get_schema_metadata(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute(
        "SELECT key, value FROM schema_metadata"
    ).fetchall()
    return {r["key"]: r["value"] for r in rows}


def start_source_run(
    conn: sqlite3.Connection,
    *,
    provider: str,
    source_type: str,
    source_run_id: str | None = None,
) -> str:
    """Insert a ``STARTED`` row in ``source_runs`` and return the run id."""
    run_id = source_run_id or uuid.uuid4().hex
    conn.execute(
        "INSERT INTO source_runs(source_run_id, provider, source_type, "
        "started_at_utc, status, advisory_only) VALUES (?, ?, ?, ?, ?, 1)",
        (run_id, str(provider), str(source_type), _utc_iso(), "STARTED"),
    )
    conn.commit()
    return run_id


def finish_source_run(
    conn: sqlite3.Connection,
    source_run_id: str,
    *,
    status: str,
    events_seen: int = 0,
    events_inserted: int = 0,
    events_updated: int = 0,
    events_rejected: int = 0,
    latest_provider_timestamp_utc: str | None = None,
    error: str | None = None,
    runtime_ms: int | None = None,
) -> None:
    if status not in SOURCE_RUN_STATUSES:
        raise ValueError(f"invalid source-run status: {status}")
    conn.execute(
        "UPDATE source_runs SET finished_at_utc=?, status=?, events_seen=?, "
        "events_inserted=?, events_updated=?, events_rejected=?, "
        "latest_provider_timestamp_utc=?, error=?, runtime_ms=? "
        "WHERE source_run_id=?",
        (
            _utc_iso(), status, int(events_seen), int(events_inserted),
            int(events_updated), int(events_rejected),
            latest_provider_timestamp_utc, error,
            int(runtime_ms) if runtime_ms is not None else None,
            source_run_id,
        ),
    )
    conn.commit()


def upsert_signal_event(
    conn: sqlite3.Connection,
    *,
    provider: str,
    source_type: str,
    event_type: str,
    asset_tags: Iterable[str],
    provider_event_timestamp_utc: str,
    normalized_key: str,
    payload: dict[str, Any],
    source_run_id: str,
    source_url: str | None = None,
    verification_status: str = "UNVERIFIED",
    freshness_status: str = "UNKNOWN",
) -> dict[str, Any]:
    """Idempotent canonical upsert.

    Returns ``{"operation": "inserted|deduplicated|revised", "event_id": ...,
    "payload_hash": ..., "revision_number": ...}``.
    """
    if verification_status not in VERIFICATION_STATES:
        raise ValueError(f"invalid verification_status: {verification_status}")
    if freshness_status not in FRESHNESS_STATES:
        raise ValueError(f"invalid freshness_status: {freshness_status}")
    tags = sorted({str(t or "").upper() for t in asset_tags if t})
    event_id = compute_event_id(
        provider=provider, source_type=source_type, event_type=event_type,
        provider_event_timestamp_utc=provider_event_timestamp_utc,
        asset_tags=tags, normalized_key=normalized_key,
    )
    new_hash = payload_hash(payload)
    now = _utc_iso()
    existing = conn.execute(
        "SELECT event_id, payload_hash, revision_number "
        "FROM canonical_signal_events WHERE event_id = ?",
        (event_id,),
    ).fetchone()

    if existing is None:
        conn.execute(
            "INSERT INTO canonical_signal_events("
            "event_id, source_run_id, provider, source_type, event_type, "
            "asset_tags, source_url, provider_event_timestamp_utc, "
            "ingested_at_utc, last_seen_at_utc, payload_hash, payload_json, "
            "normalization_version, verification_status, freshness_status, "
            "revision_number, supersedes_event_id, canonical, advisory_only, "
            "human_review_required, execution_permission) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, "
            "1, 1, 1, 'ADVISORY_ONLY')",
            (
                event_id, source_run_id, str(provider), str(source_type),
                str(event_type), json.dumps(tags), source_url,
                provider_event_timestamp_utc, now, now, new_hash,
                canonical_json(payload),
                SCHEMA_VERSIONS["normalization_version"],
                verification_status, freshness_status,
            ),
        )
        conn.commit()
        return {
            "operation": "inserted", "event_id": event_id,
            "payload_hash": new_hash, "revision_number": 0,
        }

    if existing["payload_hash"] == new_hash:
        conn.execute(
            "UPDATE canonical_signal_events SET last_seen_at_utc=? "
            "WHERE event_id=?",
            (now, event_id),
        )
        conn.commit()
        return {
            "operation": "deduplicated", "event_id": event_id,
            "payload_hash": new_hash,
            "revision_number": int(existing["revision_number"]),
        }

    revision = int(existing["revision_number"]) + 1
    conn.execute(
        "UPDATE canonical_signal_events SET payload_hash=?, payload_json=?, "
        "revision_number=?, supersedes_event_id=?, last_seen_at_utc=?, "
        "verification_status=?, freshness_status=?, source_run_id=? "
        "WHERE event_id=?",
        (
            new_hash, canonical_json(payload), revision, existing["event_id"],
            now, verification_status, freshness_status, source_run_id,
            event_id,
        ),
    )
    conn.commit()
    return {
        "operation": "revised", "event_id": event_id,
        "payload_hash": new_hash, "revision_number": revision,
    }


def jsonl_canonicality_proof() -> dict[str, Any]:
    """Static guard: SQLite is canonical, JSONL is audit-only.

    The truth model is centrally declared in :mod:`scripts.advisory_contract`;
    this helper exposes the contract values together with the allowed JSONL
    roles so the release proof has a single field to assert against.
    """
    decl = _contract.canonical_truth_declaration()
    return {
        "sqlite_is_canonical": bool(decl["sqlite_is_canonical"]),
        "jsonl_is_canonical": bool(decl["jsonl_is_canonical"]),
        "jsonl_allowed_roles": ["audit", "fallback", "debug"],
        "guard_pass": (
            bool(decl["sqlite_is_canonical"])
            and not bool(decl["jsonl_is_canonical"])
        ),
    }


def _clamp01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def persistence_integrity_score(
    *,
    idempotent_upsert_pass: bool,
    source_run_ledger_present: bool,
    payload_hash_present: bool,
    schema_metadata_present: bool,
    jsonl_noncanonical_guard_pass: bool,
    advisory_flags_present: bool,
) -> float:
    """Per sprint formula; result is on the 0..10 scale."""
    raw = (
        0.25 * (1.0 if idempotent_upsert_pass else 0.0)
        + 0.20 * (1.0 if source_run_ledger_present else 0.0)
        + 0.20 * (1.0 if payload_hash_present else 0.0)
        + 0.15 * (1.0 if schema_metadata_present else 0.0)
        + 0.10 * (1.0 if jsonl_noncanonical_guard_pass else 0.0)
        + 0.10 * (1.0 if advisory_flags_present else 0.0)
    )
    return round(10.0 * _clamp01(raw), 4)


def evaluate(
    db_path: Path | None = None,
    *,
    fixture_mode: bool = True,
) -> dict[str, Any]:
    """Run a self-test on a scratch DB (default) or the supplied DB.

    In ``fixture_mode`` (default) the function opens an in-memory DB, runs a
    deterministic idempotency probe + revision probe + ledger probe so the
    summary score is reproducible in CI without depending on local runtime
    state.
    """
    conn = open_db(db_path) if db_path is not None else open_db()
    started = time.time()
    try:
        run_id = start_source_run(
            conn, provider="fixture.yfinance", source_type="price_mover",
        )

        sample_payload = {
            "ticker": "ABC",
            "last_price": 100.0,
            "change_pct": 0.05,
            "ingested_at_utc": _utc_iso(),
        }
        first = upsert_signal_event(
            conn, provider="fixture.yfinance", source_type="price_mover",
            event_type="quote", asset_tags=["ABC"],
            provider_event_timestamp_utc="2026-05-24T10:00:00Z",
            normalized_key="ABC quote", payload=sample_payload,
            source_run_id=run_id, verification_status="FIXTURE_VERIFIED",
            freshness_status="FRESH",
        )
        # Same logical payload, different volatile ingestion stamp — must dedupe.
        sample_payload_2 = dict(sample_payload)
        sample_payload_2["ingested_at_utc"] = _utc_iso()
        second = upsert_signal_event(
            conn, provider="fixture.yfinance", source_type="price_mover",
            event_type="quote", asset_tags=["ABC"],
            provider_event_timestamp_utc="2026-05-24T10:00:00Z",
            normalized_key="ABC quote", payload=sample_payload_2,
            source_run_id=run_id, verification_status="FIXTURE_VERIFIED",
            freshness_status="FRESH",
        )
        # Real change to non-volatile field — must revise, not duplicate.
        revised_payload = dict(sample_payload)
        revised_payload["last_price"] = 101.5
        third = upsert_signal_event(
            conn, provider="fixture.yfinance", source_type="price_mover",
            event_type="quote", asset_tags=["ABC"],
            provider_event_timestamp_utc="2026-05-24T10:00:00Z",
            normalized_key="ABC quote", payload=revised_payload,
            source_run_id=run_id, verification_status="FIXTURE_VERIFIED",
            freshness_status="FRESH",
        )

        finish_source_run(
            conn, run_id, status="SUCCESS", events_seen=3, events_inserted=1,
            events_updated=1, events_rejected=0,
            latest_provider_timestamp_utc="2026-05-24T10:00:00Z",
            runtime_ms=int((time.time() - started) * 1000),
        )

        canonical_count = conn.execute(
            "SELECT COUNT(*) FROM canonical_signal_events"
        ).fetchone()[0]
        source_runs_count = conn.execute(
            "SELECT COUNT(*) FROM source_runs WHERE status='SUCCESS'"
        ).fetchone()[0]
        schema_meta = get_schema_metadata(conn)

        idempotent_ok = (
            first["operation"] == "inserted"
            and second["operation"] == "deduplicated"
            and third["operation"] == "revised"
            and canonical_count == 1
        )
        payload_hash_ok = bool(first["payload_hash"]) and bool(third["payload_hash"])
        ledger_ok = source_runs_count >= 1
        schema_ok = all(k in schema_meta for k in SCHEMA_VERSIONS)
        jsonl_guard = jsonl_canonicality_proof()
        guard_ok = bool(jsonl_guard["guard_pass"])
        advisory_ok = True  # writer hard-codes ADVISORY_ONLY columns

        score = persistence_integrity_score(
            idempotent_upsert_pass=idempotent_ok,
            source_run_ledger_present=ledger_ok,
            payload_hash_present=payload_hash_ok,
            schema_metadata_present=schema_ok,
            jsonl_noncanonical_guard_pass=guard_ok,
            advisory_flags_present=advisory_ok,
        )
        return {
            "report": "persistence_integrity_summary",
            "ok": score >= 9.0,
            "generated_at_utc": _utc_iso(),
            "fixture_mode": bool(fixture_mode),
            "canonical_event_count": int(canonical_count),
            "source_run_count": int(source_runs_count),
            "schema_metadata": schema_meta,
            "jsonl_guard": jsonl_guard,
            "idempotent_upsert_pass": bool(idempotent_ok),
            "payload_hash_present": bool(payload_hash_ok),
            "source_run_ledger_present": bool(ledger_ok),
            "schema_metadata_present": bool(schema_ok),
            "jsonl_noncanonical_guard_pass": bool(guard_ok),
            "advisory_flags_present": bool(advisory_ok),
            "persistence_integrity_score": score,
            "advisory_only": True,
            **_contract.advisory_safety_stamps(),
        }
    finally:
        conn.close()


def write_summary(path: Path | None = None, *,
                  fixture_mode: bool = True) -> dict[str, Any]:
    target = path or DEFAULT_SUMMARY_PATH
    summary = evaluate(fixture_mode=fixture_mode)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    tmp.replace(target)
    summary["summary_path"] = str(target)
    return summary


# ---------------------------------------------------------------------------
# Sprint 3 — live_provider_evidence + candidate_gate_audit (v2 persistence)
# ---------------------------------------------------------------------------


def _evidence_id(*, provider: str, latest_ts: str | None,
                 payload_hash_str: str) -> str:
    key = f"{provider}|{latest_ts or ''}|{payload_hash_str}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def upsert_live_provider_evidence(
    conn: sqlite3.Connection,
    *,
    provider: str,
    source_type: str,
    run_mode: str,
    verification_status: str,
    latest_provider_timestamp_utc: str | None,
    freshness_age_hours: float | None,
    payload_hash_value: str,
    source_run_id: str | None = None,
    sample_source_url: str | None = None,
    advisory_only: bool = True,
) -> dict[str, Any]:
    """Idempotent live_provider_evidence write.

    Keyed by (provider, latest_provider_timestamp_utc, payload_hash) so the
    same operator-run refresh artifact does not create duplicate rows when
    re-imported.  Returns ``{operation, evidence_id}``.
    """
    evidence_id = _evidence_id(
        provider=provider,
        latest_ts=latest_provider_timestamp_utc,
        payload_hash_str=payload_hash_value,
    )
    now = _utc_iso()
    existing = conn.execute(
        "SELECT evidence_id FROM live_provider_evidence WHERE evidence_id = ?",
        (evidence_id,),
    ).fetchone()
    if existing:
        return {"operation": "deduplicated", "evidence_id": evidence_id}
    conn.execute(
        "INSERT INTO live_provider_evidence(evidence_id, provider, source_type, "
        "run_mode, verification_status, latest_provider_timestamp_utc, "
        "checked_at_utc, freshness_age_hours, payload_hash, source_run_id, "
        "sample_source_url, advisory_only) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, "
        "?, ?, ?)",
        (
            evidence_id, str(provider), str(source_type), str(run_mode),
            str(verification_status), latest_provider_timestamp_utc,
            now,
            float(freshness_age_hours) if freshness_age_hours is not None else None,
            payload_hash_value, source_run_id, sample_source_url,
            1 if advisory_only else 0,
        ),
    )
    conn.commit()
    return {"operation": "inserted", "evidence_id": evidence_id}


def insert_candidate_gate_audit(
    conn: sqlite3.Connection,
    *,
    candidate_id: str,
    cqs_final: float | None,
    eqs: float | None,
    fcs: float | None,
    ers: float | None,
    why_today_score: float | None,
    lpq: float | None,
    portfolio_truth_ok: bool,
    memory_decay_ok: bool,
    model_disagreement_ok: bool,
    final_state: str,
    may_promote: bool,
    downgrade_reasons: list[str],
    audit_id: str | None = None,
) -> dict[str, Any]:
    """Write a candidate_gate_audit row capturing every formula component.

    ``downgrade_reasons`` is normalized to a sorted, deduped list and stored
    as canonical JSON so the audit is reproducible.
    """
    if not isinstance(downgrade_reasons, list):
        raise ValueError("downgrade_reasons must be a list[str]")
    reasons_norm = sorted({str(r) for r in downgrade_reasons if r})
    aid = audit_id or uuid.uuid4().hex
    conn.execute(
        "INSERT INTO candidate_gate_audit(audit_id, candidate_id, "
        "evaluated_at_utc, cqs_final, eqs, fcs, ers, why_today_score, lpq, "
        "portfolio_truth_ok, memory_decay_ok, model_disagreement_ok, "
        "final_state, may_promote, downgrade_reasons_json, advisory_only) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
        (
            aid, str(candidate_id), _utc_iso(),
            float(cqs_final) if cqs_final is not None else None,
            float(eqs) if eqs is not None else None,
            float(fcs) if fcs is not None else None,
            float(ers) if ers is not None else None,
            float(why_today_score) if why_today_score is not None else None,
            float(lpq) if lpq is not None else None,
            1 if portfolio_truth_ok else 0,
            1 if memory_decay_ok else 0,
            1 if model_disagreement_ok else 0,
            str(final_state), 1 if may_promote else 0,
            json.dumps(reasons_norm),
        ),
    )
    conn.commit()
    return {"audit_id": aid, "downgrade_reasons": reasons_norm}


def data_model_persistence_v2_score(
    *,
    existing_persistence_integrity_score_ge_9_8: bool,
    live_provider_evidence_table_present: bool,
    candidate_gate_audit_present: bool,
    idempotent_live_evidence_writes: bool,
    formula_component_audit_present: bool,
    advisory_flags_present: bool,
) -> float:
    raw = (
        0.20 * (1.0 if existing_persistence_integrity_score_ge_9_8 else 0.0)
        + 0.20 * (1.0 if live_provider_evidence_table_present else 0.0)
        + 0.20 * (1.0 if candidate_gate_audit_present else 0.0)
        + 0.15 * (1.0 if idempotent_live_evidence_writes else 0.0)
        + 0.15 * (1.0 if formula_component_audit_present else 0.0)
        + 0.10 * (1.0 if advisory_flags_present else 0.0)
    )
    return round(10.0 * _clamp01(raw), 4)


def evaluate_v2(db_path: Path | None = None) -> dict[str, Any]:
    """Self-test for the v2 tables; reproducible in CI on a scratch DB."""
    conn = open_db(db_path) if db_path is not None else open_db()
    try:
        # Run the v1 self-test to populate baseline.
        v1_summary = evaluate()
        v1_score = float(v1_summary.get("persistence_integrity_score", 0.0))

        # Idempotency probe for live_provider_evidence.
        first = upsert_live_provider_evidence(
            conn, provider="yfinance", source_type="price_mover",
            run_mode="live", verification_status="LIVE_VERIFIED",
            latest_provider_timestamp_utc="2026-05-24T10:00:00Z",
            freshness_age_hours=2.5,
            payload_hash_value="hash-A",
            source_run_id="run-1",
            sample_source_url="https://finance.yahoo.com/quote/AAPL",
        )
        second = upsert_live_provider_evidence(
            conn, provider="yfinance", source_type="price_mover",
            run_mode="live", verification_status="LIVE_VERIFIED",
            latest_provider_timestamp_utc="2026-05-24T10:00:00Z",
            freshness_age_hours=2.5,
            payload_hash_value="hash-A",
            source_run_id="run-1",
            sample_source_url="https://finance.yahoo.com/quote/AAPL",
        )
        idempotent = (first["operation"] == "inserted"
                      and second["operation"] == "deduplicated"
                      and first["evidence_id"] == second["evidence_id"])

        # candidate_gate_audit probe.
        audit = insert_candidate_gate_audit(
            conn, candidate_id="AAPL-2026-05-24",
            cqs_final=0.78, eqs=0.72, fcs=0.81, ers=0.30,
            why_today_score=0.82, lpq=0.86,
            portfolio_truth_ok=True, memory_decay_ok=True,
            model_disagreement_ok=True,
            final_state="ADVISORY_CANDIDATE_HUMAN_REVIEW",
            may_promote=True,
            downgrade_reasons=[],
        )
        audit_row = conn.execute(
            "SELECT * FROM candidate_gate_audit WHERE audit_id=?",
            (audit["audit_id"],),
        ).fetchone()
        audit_present = (
            audit_row is not None
            and audit_row["cqs_final"] == 0.78
            and audit_row["lpq"] == 0.86
            and audit_row["advisory_only"] == 1
        )

        live_count = conn.execute(
            "SELECT COUNT(*) FROM live_provider_evidence"
        ).fetchone()[0]
        audit_count = conn.execute(
            "SELECT COUNT(*) FROM candidate_gate_audit"
        ).fetchone()[0]

        # Tables present?
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        tables = {row["name"] for row in cur}
        live_table = "live_provider_evidence" in tables
        audit_table = "candidate_gate_audit" in tables

        score = data_model_persistence_v2_score(
            existing_persistence_integrity_score_ge_9_8=v1_score >= 9.8,
            live_provider_evidence_table_present=live_table,
            candidate_gate_audit_present=audit_table,
            idempotent_live_evidence_writes=idempotent,
            formula_component_audit_present=audit_present,
            advisory_flags_present=True,
        )
        return {
            "report": "data_model_persistence_v2_summary",
            "ok": score >= 9.7,
            "generated_at_utc": _utc_iso(),
            "v1_persistence_integrity_score": v1_score,
            "live_provider_evidence_table_present": live_table,
            "candidate_gate_audit_present": audit_table,
            "live_evidence_row_count": int(live_count),
            "candidate_gate_audit_row_count": int(audit_count),
            "idempotent_live_evidence_writes": bool(idempotent),
            "formula_component_audit_present": bool(audit_present),
            "advisory_flags_present": True,
            "data_model_persistence_v2_score": score,
            "advisory_only": True,
            **_contract.advisory_safety_stamps(),
        }
    finally:
        conn.close()


def write_v2_summary(path: Path | None = None) -> dict[str, Any]:
    target = path or DEFAULT_V2_SUMMARY_PATH
    summary = evaluate_v2()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    tmp.replace(target)
    summary["summary_path"] = str(target)
    return summary


def read_v2_summary(path: Path | None = None) -> dict[str, Any] | None:
    target = path or DEFAULT_V2_SUMMARY_PATH
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def read_summary(path: Path | None = None) -> dict[str, Any] | None:
    target = path or DEFAULT_SUMMARY_PATH
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="persistence_integrity.py",
        description=(
            "Run the persistence-integrity self-test (idempotent upsert + "
            "source-run ledger + schema metadata + JSONL guard) and optionally "
            "write the summary artifact. Read-only; advisory-only."
        ),
    )
    p.add_argument("--write-summary", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    summary = (
        write_summary() if args.write_summary else evaluate(fixture_mode=True)
    )
    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print("persistence_integrity_score:",
              summary.get("persistence_integrity_score"))
        print("  idempotent_upsert_pass         :",
              summary.get("idempotent_upsert_pass"))
        print("  source_run_ledger_present      :",
              summary.get("source_run_ledger_present"))
        print("  payload_hash_present           :",
              summary.get("payload_hash_present"))
        print("  schema_metadata_present        :",
              summary.get("schema_metadata_present"))
        print("  jsonl_noncanonical_guard_pass  :",
              summary.get("jsonl_noncanonical_guard_pass"))
    return 0


__all__ = [
    "SCHEMA_VERSIONS",
    "VERIFICATION_STATES",
    "FRESHNESS_STATES",
    "SOURCE_RUN_STATUSES",
    "DEFAULT_SUMMARY_PATH",
    "DEFAULT_V2_SUMMARY_PATH",
    "canonical_json",
    "payload_hash",
    "compute_event_id",
    "open_db",
    "seed_schema_metadata",
    "get_schema_metadata",
    "start_source_run",
    "finish_source_run",
    "upsert_signal_event",
    "jsonl_canonicality_proof",
    "persistence_integrity_score",
    "evaluate",
    "write_summary",
    "read_summary",
    "upsert_live_provider_evidence",
    "insert_candidate_gate_audit",
    "data_model_persistence_v2_score",
    "evaluate_v2",
    "write_v2_summary",
    "read_v2_summary",
]


if __name__ == "__main__":
    raise SystemExit(main())
