"""Tests for the signal-reactor operational wiring sprint.

Covers
------
1. ``signal_inbox_api`` enriches inbox items with reactor fields and
   exposes aggregate reactor counts on ``list_inbox_items``.
2. Reactor enrichment NEVER grants execution permission — safety
   invariants survive the enrichment pass.
3. ``self_test_report`` includes a ``reactor_self_check`` block and
   bubbles compact reactor fields through ``build_self_test_summary``.
4. ``pre_real_money_preflight`` includes a sixth ``signal_reactor``
   subcheck and a healthy reactor does not unlock execution.
5. If the reactor is unavailable, every wiring point degrades safely.

Each test is read-only against the file system except where it builds
its own throwaway SQLite DB in a tmp_path.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

REACTOR_STATES = {
    "COLD_OBSERVE",
    "WARM_WATCH",
    "FUSION_REVIEW_CANDIDATE",
    "FISSION_MAP_ONLY",
    "HOT_CONTAINMENT_REQUIRED",
    "WASTE_DECAY",
    "ECHO_SUPPRESSED",
    "OPERATOR_CONTROL_RODS",
    "INSUFFICIENT_DATA",
}


# ---------------------------------------------------------------------------
# Inbox enrichment
# ---------------------------------------------------------------------------


def _import_inbox():
    import scripts.signal_inbox_api as api
    return api


def test_decorate_with_reactor_diagnostics_attaches_required_fields():
    api = _import_inbox()
    enriched = api._decorate_with_reactor_diagnostics(
        {
            "event_id": "FABRIC_TEST",
            "ticker": "TEST",
            "priority_score": 0.5,
            "persistence_score": 0.4,
            "kill_rate_score": 0.2,
            "contamination_score": 0.1,
            "entry_type": "news",
        }
    )
    for k in (
        "reactor_state",
        "decision_grade_energy",
        "echo_risk_score",
        "meltdown_risk_score",
        "fusion_validity",
        "fission_branch_clarity",
        "operator_heat_score",
        "gallardo_block",
        "reactor_recommendation",
        "reactor_available",
    ):
        assert k in enriched, f"missing enrichment key {k}"


def test_decorate_with_reactor_diagnostics_reports_valid_state():
    api = _import_inbox()
    enriched = api._decorate_with_reactor_diagnostics(
        {"priority_score": 0.3, "persistence_score": 0.3}
    )
    assert enriched["reactor_state"] in REACTOR_STATES
    assert enriched["reactor_available"] is True


def test_decorate_with_reactor_diagnostics_preserves_safety_invariants():
    api = _import_inbox()
    enriched = api._decorate_with_reactor_diagnostics(
        {"priority_score": 0.99, "contamination_score": 0.99}
    )
    assert enriched["advisory_status"] == "ADVISORY_ONLY"
    assert enriched["execution_gate"] == "LOCKED"
    assert enriched["broker_api_called"] is False
    assert enriched["ai_execution_count"] == 0
    assert enriched["execution_permission"] is False
    assert enriched["can_execute"] is False


def test_decorate_with_reactor_diagnostics_handles_empty_input():
    api = _import_inbox()
    enriched = api._decorate_with_reactor_diagnostics({})
    assert "reactor_state" in enriched
    # Empty input -> reactor should still emit a valid state (likely
    # COLD_OBSERVE or INSUFFICIENT_DATA).  Either is acceptable.
    assert enriched["reactor_state"] in REACTOR_STATES
    assert enriched["execution_permission"] is False


def test_decorate_with_reactor_diagnostics_degrades_when_reactor_missing(monkeypatch):
    """If the reactor module cannot be imported, enrichment must NOT crash."""
    api = _import_inbox()
    real_module = __import__("scripts.signal_reactor", fromlist=["evaluate_signal_reactor"])

    def _raise_import_error(*args, **kwargs):
        raise ImportError("simulated missing reactor")

    monkeypatch.setattr(real_module, "evaluate_signal_reactor", _raise_import_error)
    enriched = api._decorate_with_reactor_diagnostics(
        {"priority_score": 0.5, "persistence_score": 0.5}
    )
    # Defensive defaults remain; safety invariants still locked.  Whether
    # reactor_available ends up True or False depends on how the import
    # fallback unfolded; what must be true is no crash and no execution
    # permission.
    assert "reactor_state" in enriched
    assert enriched["execution_permission"] is False
    assert enriched["broker_api_called"] is False


def test_list_inbox_items_exposes_reactor_counts(tmp_path, monkeypatch):
    api = _import_inbox()
    monkeypatch.setattr(api, "INBOX_STATES_LOG", tmp_path / "inbox_states.jsonl")
    monkeypatch.setattr(api, "REFLECTIONS_LOG", tmp_path / "reflections.jsonl")
    monkeypatch.setattr(api, "AI_SUMMARIES_LOG", tmp_path / "ai_summaries.jsonl")
    result = api.list_inbox_items()
    assert "reactor_state_counts" in result
    assert isinstance(result["reactor_state_counts"], dict)
    assert "reactor_gallardo_block_count" in result
    assert isinstance(result["reactor_gallardo_block_count"], int)
    assert "reactor_unavailable_count" in result
    # Aggregate counts must total to the number of items returned (when
    # the inbox produced any items).
    total = sum(result["reactor_state_counts"].values())
    assert total == len(result["items"])


def test_list_inbox_items_every_item_carries_reactor_fields(tmp_path, monkeypatch):
    api = _import_inbox()
    monkeypatch.setattr(api, "INBOX_STATES_LOG", tmp_path / "inbox_states.jsonl")
    monkeypatch.setattr(api, "REFLECTIONS_LOG", tmp_path / "reflections.jsonl")
    monkeypatch.setattr(api, "AI_SUMMARIES_LOG", tmp_path / "ai_summaries.jsonl")
    result = api.list_inbox_items()
    for item in result["items"]:
        assert item["reactor_state"] in REACTOR_STATES
        # Reactor advisory enrichment must not break advisory stamps.
        assert item["advisory_status"] == "ADVISORY_ONLY"
        assert item["execution_permission"] is False
        assert item["can_execute"] is False


# ---------------------------------------------------------------------------
# Self-test report wiring
# ---------------------------------------------------------------------------


def _make_minimal_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE signal_events (
                id INTEGER PRIMARY KEY,
                event_id TEXT, source_name TEXT, raw_payload TEXT, fetched_at TEXT
            );
            CREATE TABLE manual_trades (
                trade_id TEXT PRIMARY KEY,
                event_id TEXT, ticker TEXT, side TEXT,
                quantity REAL, price REAL,
                executed_at TEXT, thesis TEXT DEFAULT '', notes TEXT DEFAULT ''
            );
            CREATE TABLE reconciliation_results (
                reconciliation_id TEXT PRIMARY KEY,
                trade_id TEXT, event_id TEXT,
                reconciled_at TEXT, actual_fill_price REAL, actual_quantity REAL,
                outcome_notes TEXT DEFAULT '', pnl_estimate REAL DEFAULT 0.0,
                outcome_status TEXT DEFAULT 'UNKNOWN'
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_self_test_report_contains_reactor_self_check(tmp_path):
    from scripts import self_test_report as report

    db = tmp_path / "mvp_local.db"
    _make_minimal_db(db)
    payload = report.build_report(db)
    assert "reactor_self_check" in payload
    rc = payload["reactor_self_check"]
    assert rc["available"] is True
    assert rc["safety_invariants_ok"] is True
    assert rc["reactor_state"] in REACTOR_STATES


def test_self_test_summary_bubbles_reactor_fields(tmp_path):
    from scripts import self_test_report as report

    db = tmp_path / "mvp_local.db"
    _make_minimal_db(db)
    summary = report.build_self_test_summary(db)
    assert "reactor_available" in summary
    assert summary["reactor_available"] is True
    assert summary["reactor_state"] in REACTOR_STATES
    assert summary["reactor_safety_invariants_ok"] is True
    # The summary must still carry the canonical advisory stamps.
    assert summary["advisory_status"] == "ADVISORY_ONLY"
    assert summary["execution_gate"] == "LOCKED"


def test_self_test_report_markdown_renders_reactor_section(tmp_path):
    from scripts import self_test_report as report

    db = tmp_path / "mvp_local.db"
    _make_minimal_db(db)
    payload = report.build_report(db)
    md = report._render_markdown(payload)
    assert "Signal Reactor Self-Check" in md


# ---------------------------------------------------------------------------
# Preflight wiring
# ---------------------------------------------------------------------------


def _make_full_repo(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "api_server.py").write_text("# stub\n", encoding="utf-8")
    (root / "runtime").mkdir()
    db = root / "runtime" / "mvp_local.db"
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript(
            """
            CREATE TABLE manual_trades (
                trade_id TEXT PRIMARY KEY,
                event_id TEXT, ticker TEXT, side TEXT, quantity REAL, price REAL,
                executed_at TEXT, thesis TEXT, notes TEXT,
                invalidation_level TEXT DEFAULT '',
                expected_horizon TEXT DEFAULT '',
                risk_reason TEXT DEFAULT '',
                entry_reason TEXT DEFAULT '',
                exit_plan TEXT DEFAULT '',
                confidence_before REAL,
                emotional_state TEXT DEFAULT '',
                mistake_tags TEXT DEFAULT '',
                lesson TEXT DEFAULT '',
                created_via TEXT DEFAULT ''
            );
            CREATE TABLE reconciliation_results (
                reconciliation_id TEXT PRIMARY KEY,
                trade_id TEXT, event_id TEXT,
                reconciled_at TEXT, actual_fill_price REAL, actual_quantity REAL,
                outcome_notes TEXT DEFAULT '', pnl_estimate REAL DEFAULT 0.0,
                outcome_status TEXT DEFAULT 'UNKNOWN',
                outcome_quality TEXT DEFAULT '',
                process_error TEXT DEFAULT '',
                process_error_notes TEXT DEFAULT '',
                mistake_tags TEXT DEFAULT '',
                lesson TEXT DEFAULT ''
            );
            CREATE TABLE source_run_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_name TEXT, status TEXT, fetched_count INTEGER DEFAULT 0,
                skipped_reason TEXT DEFAULT '', error_message TEXT DEFAULT '',
                timestamp_utc TEXT, duration_ms INTEGER DEFAULT 0
            );
            """
        )
        conn.commit()
    finally:
        conn.close()
    return root, db


def test_preflight_includes_signal_reactor_subcheck(tmp_path):
    from scripts import pre_real_money_preflight as prp

    root, db = _make_full_repo(tmp_path)
    payload = prp.run_preflight(db, repo_root=root, env={})
    assert "signal_reactor" in payload["subchecks"]
    sr = payload["subchecks"]["signal_reactor"]
    assert sr["ok"] is True
    assert sr["safety_invariants_ok"] is True
    assert sr["reactor_state"] in REACTOR_STATES


def test_preflight_signal_reactor_does_not_unlock_execution(tmp_path):
    from scripts import pre_real_money_preflight as prp

    root, db = _make_full_repo(tmp_path)
    payload = prp.run_preflight(db, repo_root=root, env={})
    # Even when reactor passes its subcheck, the overall preflight
    # response must keep the advisory stamps locked.
    assert payload["advisory_status"] == "ADVISORY_ONLY"
    assert payload["execution_gate"] == "LOCKED"
    assert payload["broker_api_called"] is False
    assert payload["ai_execution_count"] == 0
    assert payload["execution_permission"] is False
    assert payload["can_execute"] is False


def test_preflight_reactor_does_not_override_backlog_block(tmp_path):
    """If the unreconciled backlog is over the block threshold, the
    preflight must remain blocked regardless of how cheerful the reactor
    is.  (We don't manipulate reactor output here — we only confirm that
    the backlog block survives a normal reactor pass.)"""
    from scripts import pre_real_money_preflight as prp

    root, db = _make_full_repo(tmp_path)
    # Insert enough unreconciled trades to trip the BLOCK threshold.
    conn = sqlite3.connect(str(db))
    try:
        for i in range(prp.UNRECONCILED_BLOCK_THRESHOLD):
            conn.execute(
                "INSERT INTO manual_trades (trade_id, event_id, ticker, side, quantity,"
                " price, executed_at, thesis, notes, created_via)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (f"T{i}", f"EV{i}", "QQQ", "BUY", 10, 100.0,
                 "2026-05-10T00:00:00Z",
                 "preflight backlog fixture thesis", "", "manual_trade_log"),
            )
        conn.commit()
    finally:
        conn.close()
    payload = prp.run_preflight(db, repo_root=root, env={})
    assert payload["ok"] is False
    assert "unreconciled_backlog_block" in payload["blocking_issues"]
    # Reactor subcheck still exists and is healthy.
    assert payload["subchecks"]["signal_reactor"]["ok"] is True
