"""NBI store — canonical SQLite persistence for Narrative Branch Intelligence.

Closes the "NBI is stateless per run" gap.  Persists events, claims, source
clusters, branch snapshots, ticker scores, operator cards, and backtest
cases into the canonical DB (``runtime/mvp_local.db`` by default — same
truth store as ``scripts/persistence.py``; SQLite is canonical, JSONL never).

Contamination guard: every event and backtest case carries ``is_fixture``.
Fixture rows are excluded from ``load_active_nbi_reports`` and from the
real-case counts in ``summarize_nbi_backtest_readiness`` — demo data can
never masquerade as canonical truth.

Migration is idempotent: ``init_nbi_schema`` only issues
``CREATE TABLE/INDEX IF NOT EXISTS`` — never drops, never rewrites rows.

Calibration honesty thresholds (advisory doctrine, tested):

    N_real < 10   -> INSUFFICIENT_EVIDENCE
    10 <= N < 30  -> DESCRIPTIVE_ONLY
    N >= 30       -> CALIBRATION_POSSIBLE

Advisory-only.  No broker calls, no execution surface, no order language.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.advisory_contract import advisory_safety_stamps
from scripts.narrative_branch_engine import build_backtest_case, render_event_card
from scripts.persistence import DB_PATH as CANONICAL_DB_PATH

NBI_STORE_VERSION = "nbi-store-v1.0"

READINESS_INSUFFICIENT = "INSUFFICIENT_EVIDENCE"
READINESS_DESCRIPTIVE = "DESCRIPTIVE_ONLY"
READINESS_CALIBRATION = "CALIBRATION_POSSIBLE"
REAL_CASE_MIN_DESCRIPTIVE = 10
REAL_CASE_MIN_CALIBRATION = 30

_ACTIVE_EXCLUDED_STATES = ("DEAD", "RESOLVED")

_SCHEMA: tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS nbi_events (
        event_id TEXT PRIMARY KEY,
        name TEXT NOT NULL DEFAULT '',
        category TEXT NOT NULL DEFAULT '',
        country_scope TEXT NOT NULL DEFAULT '',
        state TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        core_probability REAL,
        venue_probability REAL,
        delegation_probability REAL,
        deals_probability REAL,
        sector_probability REAL,
        priced_probability REAL,
        confidence REAL,
        rumor_risk REAL,
        disagreement_index REAL,
        narrative_drift REAL,
        is_fixture INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS nbi_claims (
        claim_id TEXT NOT NULL,
        event_id TEXT NOT NULL,
        claim_text TEXT NOT NULL DEFAULT '',
        layer TEXT NOT NULL DEFAULT '',
        source_cluster_id TEXT NOT NULL DEFAULT '',
        source_type TEXT NOT NULL DEFAULT '',
        jurisdiction TEXT NOT NULL DEFAULT '',
        claim_magnitude REAL,
        evidence_strength REAL,
        causal_leap REAL,
        rumor_risk REAL,
        evidence_refs_json TEXT NOT NULL DEFAULT '[]',
        first_seen TEXT,
        last_seen TEXT,
        PRIMARY KEY (event_id, claim_id)
    )""",
    """CREATE TABLE IF NOT EXISTS nbi_source_clusters (
        source_cluster_id TEXT PRIMARY KEY,
        root_domain TEXT NOT NULL DEFAULT '',
        provider TEXT NOT NULL DEFAULT '',
        source_type TEXT NOT NULL DEFAULT '',
        authority_score REAL,
        accuracy_score REAL,
        independence_score REAL,
        jurisdiction_score REAL,
        recency_score REAL,
        source_quality_score REAL,
        first_seen TEXT,
        last_seen TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS nbi_branch_snapshots (
        snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        p_core REAL, p_venue REAL, p_delegation REAL,
        p_deals REAL, p_sector REAL, p_priced REAL,
        state TEXT NOT NULL DEFAULT '',
        evidence_refs_json TEXT NOT NULL DEFAULT '[]'
    )""",
    """CREATE TABLE IF NOT EXISTS nbi_ticker_scores (
        score_id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT NOT NULL,
        ticker TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        narrative_relevance REAL,
        branch_probability REAL,
        value_chain_exposure REAL,
        filing_support REAL,
        price_dislocation REAL,
        liquidity_adjustment REAL,
        confidence_decay REAL,
        hard_gate_factor REAL,
        final_stock_score REAL,
        hedge_need REAL,
        operator_action REAL,
        action_reason TEXT NOT NULL DEFAULT '',
        evidence_refs_json TEXT NOT NULL DEFAULT '[]'
    )""",
    """CREATE TABLE IF NOT EXISTS nbi_operator_cards (
        card_id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        card_json TEXT NOT NULL,
        card_text TEXT NOT NULL DEFAULT '',
        action_class TEXT NOT NULL DEFAULT '',
        confidence REAL,
        evidence_refs_json TEXT NOT NULL DEFAULT '[]'
    )""",
    """CREATE TABLE IF NOT EXISTS nbi_backtest_cases (
        case_id TEXT PRIMARY KEY,
        event_id TEXT NOT NULL,
        initial_narrative TEXT NOT NULL DEFAULT '',
        rumor_peak_timestamp TEXT,
        resolution_timestamp TEXT,
        branch_probabilities_json TEXT NOT NULL DEFAULT '{}',
        resolution_labels_json TEXT NOT NULL DEFAULT '{}',
        affected_basket_json TEXT NOT NULL DEFAULT '[]',
        benchmark_json TEXT NOT NULL DEFAULT '""',
        false_positive INTEGER NOT NULL DEFAULT 0,
        false_negative INTEGER NOT NULL DEFAULT 0,
        r_multiple REAL,
        return_vs_benchmark REAL,
        evidence_refs_json TEXT NOT NULL DEFAULT '[]',
        is_fixture INTEGER NOT NULL DEFAULT 0
    )""",
    "CREATE INDEX IF NOT EXISTS idx_nbi_claims_event ON nbi_claims(event_id)",
    "CREATE INDEX IF NOT EXISTS idx_nbi_snapshots_event "
    "ON nbi_branch_snapshots(event_id, timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_nbi_scores_event "
    "ON nbi_ticker_scores(event_id, ticker)",
    "CREATE INDEX IF NOT EXISTS idx_nbi_cards_event "
    "ON nbi_operator_cards(event_id, timestamp)",
)


def _resolve(db_path: Path | str | None) -> Path:
    return Path(db_path) if db_path is not None else CANONICAL_DB_PATH


def _connect(db_path: Path | str | None) -> sqlite3.Connection:
    path = _resolve(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _now_iso(now_iso: str | None) -> str:
    if now_iso:
        return now_iso
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# Case kinds (v1.2 evidence factory).  REAL is the only kind that can ever
# count toward calibration; FIXTURE = demo/test data; TEMPLATE = retro-label
# seed awaiting real outcome + price evidence.
CASE_KIND_REAL = "REAL"
CASE_KIND_FIXTURE = "FIXTURE"
CASE_KIND_TEMPLATE = "TEMPLATE"
CASE_KINDS: tuple[str, ...] = (CASE_KIND_REAL, CASE_KIND_FIXTURE, CASE_KIND_TEMPLATE)


def _ensure_column(
    conn: sqlite3.Connection, table: str, column: str, decl: str,
) -> None:
    """Additive idempotent column migration (no data rewrite, never drops)."""
    existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def init_nbi_schema(db_path: Path | str | None = None) -> None:
    """Idempotent additive migration: CREATE IF NOT EXISTS + ADD COLUMN only."""
    conn = _connect(db_path)
    try:
        for statement in _SCHEMA:
            conn.execute(statement)
        # v1.2 additive columns.
        _ensure_column(
            conn, "nbi_backtest_cases", "case_kind",
            f"TEXT NOT NULL DEFAULT '{CASE_KIND_REAL}'",
        )
        conn.commit()
    finally:
        conn.close()


def update_nbi_event_state(
    event_id: str, state: str, db_path: Path | str | None = None,
    *, now_iso: str | None = None,
) -> bool:
    """Set an event's state (e.g. RESOLVED on closeout).  Returns found."""
    init_nbi_schema(db_path)
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "UPDATE nbi_events SET state = ?, updated_at = ? WHERE event_id = ?",
            (state, _now_iso(now_iso), event_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------


def _report_evidence_refs(report: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for c in report.get("claims", []):
        refs.extend(c.get("evidence_refs", []))
    return sorted(set(refs))


def save_nbi_report(
    report: dict[str, Any],
    *,
    db_path: Path | str | None = None,
    is_fixture: bool = False,
    now_iso: str | None = None,
) -> dict[str, Any]:
    """Persist one NBI report: event upsert + claims + clusters + snapshot +
    ticker scores + operator card.  Returns a small persistence receipt."""
    init_nbi_schema(db_path)
    stamp = _now_iso(now_iso)
    event_id = str(report.get("event_id") or "UNKNOWN_EVENT")
    branches = report.get("branches", {})
    scores = report.get("scores", {})

    def branch_p(name: str) -> float | None:
        info = branches.get(name)
        return float(info["p"]) if isinstance(info, dict) else None

    conn = _connect(db_path)
    try:
        existing = conn.execute(
            "SELECT created_at FROM nbi_events WHERE event_id = ?", (event_id,)
        ).fetchone()
        created_at = existing["created_at"] if existing else stamp
        conn.execute(
            """INSERT OR REPLACE INTO nbi_events (
                event_id, name, category, country_scope, state,
                created_at, updated_at,
                core_probability, venue_probability, delegation_probability,
                deals_probability, sector_probability, priced_probability,
                confidence, rumor_risk, disagreement_index, narrative_drift,
                is_fixture
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                event_id,
                str(report.get("event_name") or ""),
                str(report.get("category") or ""),
                ",".join(report.get("decision_jurisdictions", [])),
                str(report.get("EVENT_STATE") or ""),
                created_at, stamp,
                branch_p("core_event"), branch_p("venue_specific"),
                branch_p("delegation_intact"), branch_p("deals_or_mous"),
                branch_p("sector_impact"), branch_p("already_priced_in"),
                float(report.get("confidence_decay", {}).get("C_t") or 0.0),
                float(scores.get("RUMOR_RISK") or 0.0),
                float(scores.get("SOURCE_DISAGREEMENT") or 0.0),
                (float(report["narrative_drift"])
                 if report.get("narrative_drift") is not None else None),
                1 if is_fixture else 0,
            ),
        )

        rumor = report.get("rumor", {})
        for c in report.get("claims", []):
            conn.execute(
                """INSERT OR REPLACE INTO nbi_claims (
                    claim_id, event_id, claim_text, layer, source_cluster_id,
                    source_type, jurisdiction, claim_magnitude,
                    evidence_strength, causal_leap, rumor_risk,
                    evidence_refs_json, first_seen, last_seen
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    c.get("claim_id"), event_id, c.get("claim_text", ""),
                    c.get("layer", ""), c.get("source_cluster", ""),
                    c.get("source_class", ""), c.get("jurisdiction", ""),
                    c.get("claim_magnitude"), c.get("evidence_strength"),
                    max(0.0, (c.get("claim_magnitude") or 0.0)
                        - (c.get("evidence_strength") or 0.0)) / 10.0,
                    (float(rumor.get("RUMOR_RISK") or 0.0)
                     if c.get("layer") == "RUMOR" else None),
                    json.dumps(c.get("evidence_refs", [])),
                    c.get("timestamp") or stamp, stamp,
                ),
            )
            cluster_id = c.get("source_cluster", "")
            if cluster_id:
                conn.execute(
                    """INSERT INTO nbi_source_clusters (
                        source_cluster_id, root_domain, provider, source_type,
                        first_seen, last_seen
                    ) VALUES (?,?,?,?,?,?)
                    ON CONFLICT(source_cluster_id)
                    DO UPDATE SET last_seen = excluded.last_seen""",
                    (
                        cluster_id, c.get("root_domain", ""),
                        c.get("provider", ""), c.get("source_class", ""),
                        stamp, stamp,
                    ),
                )

        conn.execute(
            """INSERT INTO nbi_branch_snapshots (
                event_id, timestamp, p_core, p_venue, p_delegation,
                p_deals, p_sector, p_priced, state, evidence_refs_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                event_id, stamp,
                branch_p("core_event"), branch_p("venue_specific"),
                branch_p("delegation_intact"), branch_p("deals_or_mous"),
                branch_p("sector_impact"), branch_p("already_priced_in"),
                str(report.get("EVENT_STATE") or ""),
                json.dumps(_report_evidence_refs(report)),
            ),
        )

        for t in report.get("tickers", []):
            mult = t.get("multipliers", {})
            price = t.get("price_validation", {})
            conn.execute(
                """INSERT INTO nbi_ticker_scores (
                    event_id, ticker, timestamp, narrative_relevance,
                    branch_probability, value_chain_exposure, filing_support,
                    price_dislocation, liquidity_adjustment, confidence_decay,
                    hard_gate_factor, final_stock_score, hedge_need,
                    operator_action, action_reason, evidence_refs_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    event_id, t.get("ticker"), stamp,
                    t.get("VALIDATED_RELEVANCE"), t.get("branch_p"),
                    t.get("BASE_RELEVANCE"), mult.get("m_filing"),
                    price.get("dislocation"), mult.get("m_liquidity"),
                    mult.get("m_confidence_decay"), mult.get("m_rumor"),
                    t.get("FINAL_TICKER_SCORE"),
                    float(scores.get("HEDGE_NEED") or 0.0),
                    float(scores.get("OPERATOR_ACTION") or 0.0),
                    t.get("status", ""),
                    json.dumps(t.get("evidence_refs", [])),
                ),
            )

        conn.execute(
            """INSERT INTO nbi_operator_cards (
                event_id, timestamp, card_json, card_text, action_class,
                confidence, evidence_refs_json
            ) VALUES (?,?,?,?,?,?,?)""",
            (
                event_id, stamp,
                json.dumps(report, default=str),
                render_event_card(report),
                str(report.get("ACTION") or ""),
                float(report.get("confidence_decay", {}).get("C_t") or 0.0),
                json.dumps(_report_evidence_refs(report)),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "saved": True, "event_id": event_id, "timestamp": stamp,
        "is_fixture": is_fixture, "store_version": NBI_STORE_VERSION,
        "safety": advisory_safety_stamps(),
    }


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------


def load_nbi_event(
    event_id: str, db_path: Path | str | None = None,
) -> dict[str, Any] | None:
    init_nbi_schema(db_path)
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM nbi_events WHERE event_id = ?", (event_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def load_latest_report(
    event_id: str, db_path: Path | str | None = None,
) -> dict[str, Any] | None:
    """Latest persisted full report (card_json round-trip)."""
    init_nbi_schema(db_path)
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT card_json FROM nbi_operator_cards WHERE event_id = ? "
            "ORDER BY timestamp DESC, card_id DESC LIMIT 1",
            (event_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    try:
        return json.loads(row["card_json"])
    except ValueError:
        return None


def load_event_action_history(
    event_id: str, db_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Chronological operator-card action history for one event."""
    init_nbi_schema(db_path)
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT timestamp, action_class, confidence FROM nbi_operator_cards "
            "WHERE event_id = ? ORDER BY timestamp, card_id",
            (event_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def load_active_nbi_reports(
    db_path: Path | str | None = None, *, include_fixtures: bool = False,
) -> list[dict[str, Any]]:
    """Latest report per non-DEAD/RESOLVED event; fixtures excluded by
    default so demo data never reaches the daily operator surface."""
    init_nbi_schema(db_path)
    conn = _connect(db_path)
    try:
        query = (
            "SELECT event_id FROM nbi_events WHERE state NOT IN (?, ?)"
        )
        params: list[Any] = list(_ACTIVE_EXCLUDED_STATES)
        if not include_fixtures:
            query += " AND is_fixture = 0"
        rows = conn.execute(query + " ORDER BY event_id", params).fetchall()
    finally:
        conn.close()
    reports = []
    for row in rows:
        report = load_latest_report(row["event_id"], db_path)
        if report is not None:
            reports.append(report)
    return reports


# ---------------------------------------------------------------------------
# Backtest corpus
# ---------------------------------------------------------------------------

# The schema-checked constructor lives in the engine; re-exported here so the
# store is the one-stop corpus API.
create_nbi_backtest_case = build_backtest_case


def persist_nbi_backtest_case(
    case: dict[str, Any],
    *,
    db_path: Path | str | None = None,
    is_fixture: bool = False,
    case_kind: str | None = None,
    case_id: str | None = None,
    rumor_peak_timestamp: str | None = None,
    resolution_timestamp: str | None = None,
    return_vs_benchmark: float | None = None,
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    init_nbi_schema(db_path)
    resolved_id = case_id or f"{case.get('event_id')}::case"
    if case_kind is None:
        case_kind = CASE_KIND_FIXTURE if is_fixture else CASE_KIND_REAL
    if case_kind not in CASE_KINDS:
        raise ValueError(f"case_kind must be one of {CASE_KINDS}")
    # Safety double-lock: anything not REAL is also flagged is_fixture so
    # every pre-v1.2 exclusion path still quarantines it.
    if case_kind != CASE_KIND_REAL:
        is_fixture = True
    conn = _connect(db_path)
    try:
        conn.execute(
            """INSERT OR REPLACE INTO nbi_backtest_cases (
                case_id, event_id, initial_narrative, rumor_peak_timestamp,
                resolution_timestamp, branch_probabilities_json,
                resolution_labels_json, affected_basket_json, benchmark_json,
                false_positive, false_negative, r_multiple,
                return_vs_benchmark, evidence_refs_json, is_fixture, case_kind
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                resolved_id, case.get("event_id"),
                str(case.get("initial_narrative") or ""),
                rumor_peak_timestamp, resolution_timestamp,
                json.dumps(case.get("branch_probabilities_at_rumor_peak", {})),
                # outcome_label is folded into resolution_labels so the
                # calibration report can recover y from the persisted row.
                json.dumps({
                    **(case.get("resolution_labels") or {}),
                    "outcome_label": case.get("outcome_label"),
                }),
                json.dumps(case.get("affected_basket", [])),
                json.dumps(case.get("benchmark", "")),
                1 if case.get("false_positive") else 0,
                1 if case.get("false_negative") else 0,
                case.get("r_multiple"), return_vs_benchmark,
                json.dumps(evidence_refs or []),
                1 if is_fixture else 0,
                case_kind,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "saved": True, "case_id": resolved_id,
        "is_fixture": is_fixture, "case_kind": case_kind,
    }


def load_nbi_backtest_cases(
    db_path: Path | str | None = None, *, include_fixtures: bool = False,
) -> list[dict[str, Any]]:
    init_nbi_schema(db_path)
    conn = _connect(db_path)
    try:
        query = "SELECT * FROM nbi_backtest_cases"
        if not include_fixtures:
            query += " WHERE is_fixture = 0"
        rows = conn.execute(query + " ORDER BY case_id").fetchall()
    finally:
        conn.close()
    cases = []
    for row in rows:
        case = dict(row)
        for key in (
            "branch_probabilities_json", "resolution_labels_json",
            "affected_basket_json", "benchmark_json", "evidence_refs_json",
        ):
            try:
                case[key.removesuffix("_json")] = json.loads(case.pop(key))
            except ValueError:
                case[key.removesuffix("_json")] = None
        cases.append(case)
    return cases


def summarize_nbi_backtest_readiness(
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Honest corpus census.  Fixtures counted but never as real cases."""
    all_cases = load_nbi_backtest_cases(db_path, include_fixtures=True)
    real = [
        c for c in all_cases
        if not c.get("is_fixture")
        and c.get("case_kind", CASE_KIND_REAL) == CASE_KIND_REAL
    ]
    templates = [
        c for c in all_cases if c.get("case_kind") == CASE_KIND_TEMPLATE
    ]
    resolved_real = [c for c in real if c.get("resolution_timestamp")]
    n_real = len(resolved_real)
    if n_real >= REAL_CASE_MIN_CALIBRATION:
        status = READINESS_CALIBRATION
    elif n_real >= REAL_CASE_MIN_DESCRIPTIVE:
        status = READINESS_DESCRIPTIVE
    else:
        status = READINESS_INSUFFICIENT
    return {
        "report": "nbi_backtest_readiness",
        "store_version": NBI_STORE_VERSION,
        "cases_total": len(all_cases),
        "cases_fixture": len(all_cases) - len(real),
        "cases_template_seed_inventory": len(templates),
        "cases_real": len(real),
        "cases_real_closed": n_real,
        "calibration_status": status,
        "thresholds": {
            "descriptive_min": REAL_CASE_MIN_DESCRIPTIVE,
            "calibration_min": REAL_CASE_MIN_CALIBRATION,
        },
        # Edge claims are NEVER auto-permitted by a row count; a human
        # calibration review is required even past the threshold.
        "edge_claim_permitted": False,
        "safety": advisory_safety_stamps(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="NBI store: schema init + backtest readiness census."
    )
    parser.add_argument("--db", default=None, help="DB path (default canonical)")
    parser.add_argument("--init", action="store_true", help="Run idempotent migration")
    parser.add_argument(
        "--readiness", action="store_true", help="Print backtest readiness census"
    )
    args = parser.parse_args(argv)
    if args.init:
        init_nbi_schema(args.db)
        print(f"nbi schema ensured on {_resolve(args.db)}")
    if args.readiness or not args.init:
        print(json.dumps(summarize_nbi_backtest_readiness(args.db), indent=2))
    return 0


__all__ = [
    "NBI_STORE_VERSION", "CANONICAL_DB_PATH",
    "READINESS_INSUFFICIENT", "READINESS_DESCRIPTIVE", "READINESS_CALIBRATION",
    "CASE_KIND_REAL", "CASE_KIND_FIXTURE", "CASE_KIND_TEMPLATE", "CASE_KINDS",
    "init_nbi_schema", "save_nbi_report", "load_nbi_event",
    "load_latest_report", "load_active_nbi_reports", "update_nbi_event_state",
    "load_event_action_history",
    "create_nbi_backtest_case", "persist_nbi_backtest_case",
    "load_nbi_backtest_cases", "summarize_nbi_backtest_readiness", "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
