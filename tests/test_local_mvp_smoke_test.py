"""
Tests for scripts/local_mvp_smoke_test.py.

Rules
-----
- Mocked/synthetic data only — no live internet, no real API keys, no broker API.
- Temporary SQLite DBs via tmp_path fixture — never touches runtime/mvp_local.db.
- Phase 1 runner is mocked to return a synthetic Phase1RunReport.
- Verifies all advisory invariants: advisory_status, execution_mode,
  ai_execution_count, broker_api_called, broker_order_id.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def p():
    import scripts.persistence as _p
    return _p


@pytest.fixture
def smoke():
    import scripts.local_mvp_smoke_test as _s
    return _s


def _synthetic_phase1_report(dry_run: bool = True):
    """Synthetic Phase1RunReport — no network required."""
    from scripts.live_source_runner import Phase1RunReport, SourceRunResult

    report = Phase1RunReport(dry_run=dry_run)
    report.sources = [
        SourceRunResult(
            source_name="synthetic_polymarket",
            status="ok",
            fetched_count=3,
            events_persisted=0 if dry_run else 3,
        ),
        SourceRunResult(
            source_name="synthetic_gdelt",
            status="ok",
            fetched_count=2,
            events_persisted=0 if dry_run else 2,
        ),
        SourceRunResult(
            source_name="sec_edgar",
            status="skipped",
            fetched_count=0,
            skipped_reason="SEC_USER_AGENT not set",
        ),
    ]
    report.total_fetched = sum(s.fetched_count for s in report.sources)
    report.total_persisted = sum(s.events_persisted for s in report.sources)
    return report


# ---------------------------------------------------------------------------
# check_db_init
# ---------------------------------------------------------------------------


def test_check_db_init_passes(tmp_path, smoke):
    db = tmp_path / "init.db"
    result = smoke.check_db_init(db)
    assert result.passed, result.message
    assert db.exists()


def test_check_db_init_all_tables_present(tmp_path, smoke):
    import sqlite3

    db = tmp_path / "tables.db"
    smoke.check_db_init(db)

    conn = sqlite3.connect(str(db))
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()

    required = {
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
    }
    assert required.issubset(tables), f"Missing tables: {required - tables}"


def test_check_db_init_idempotent(tmp_path, smoke):
    db = tmp_path / "idem.db"
    r1 = smoke.check_db_init(db)
    r2 = smoke.check_db_init(db)
    assert r1.passed
    assert r2.passed


# ---------------------------------------------------------------------------
# check_db_status
# ---------------------------------------------------------------------------


def test_check_db_status_passes(tmp_path, smoke, p):
    db = tmp_path / "status.db"
    p.init_schema(db)
    result = smoke.check_db_status(db)
    assert result.passed, result.message


def test_db_status_advisory_invariants(tmp_path, p):
    db = tmp_path / "status_inv.db"
    p.init_schema(db)
    status = p.get_db_status(db_path=db)
    assert status["advisory_status"] == "ADVISORY_ONLY"
    assert status["ai_execution_count"] == 0
    assert status["broker_api_called"] is False
    assert status["db_exists"] is True
    assert isinstance(status["table_row_counts"], dict)


def test_db_status_table_row_counts_present(tmp_path, p):
    db = tmp_path / "counts.db"
    p.init_schema(db)
    status = p.get_db_status(db_path=db)
    counts = status["table_row_counts"]
    expected_tables = {
        "signal_decisions",
        "user_reflections",
        "ai_discussion_summaries",
        "manual_trades",
        "reconciliation_results",
        "moltbook_entries",
        "source_health",
        "export_logs",
    }
    assert expected_tables.issubset(counts.keys()), (
        f"Missing from status: {expected_tables - counts.keys()}"
    )


# ---------------------------------------------------------------------------
# check_live_source_dry_run
# ---------------------------------------------------------------------------


def test_check_live_source_dry_run_passes_with_mock(smoke):
    mock_runner = MagicMock(return_value=_synthetic_phase1_report(dry_run=True))
    result = smoke.check_live_source_dry_run(phase1_runner=mock_runner)
    assert result.passed, result.message
    mock_runner.assert_called_once()


def test_check_live_source_dry_run_fails_if_dry_run_false(smoke):
    report = _synthetic_phase1_report(dry_run=False)
    mock_runner = MagicMock(return_value=report)
    result = smoke.check_live_source_dry_run(phase1_runner=mock_runner)
    assert not result.passed
    assert "dry_run" in result.message.lower() or "False" in result.message


def test_check_live_source_dry_run_fails_if_events_persisted(smoke):
    report = _synthetic_phase1_report(dry_run=True)
    report.total_persisted = 5
    mock_runner = MagicMock(return_value=report)
    result = smoke.check_live_source_dry_run(phase1_runner=mock_runner)
    assert not result.passed
    assert "persisted" in result.message.lower()


def test_check_live_source_dry_run_fails_if_wrong_advisory_status(smoke):
    report = _synthetic_phase1_report(dry_run=True)
    report.advisory_status = "LIVE_EXECUTION"
    mock_runner = MagicMock(return_value=report)
    result = smoke.check_live_source_dry_run(phase1_runner=mock_runner)
    assert not result.passed


def test_phase1_report_advisory_invariants():
    """Phase1RunReport dataclass enforces advisory invariants."""
    report = _synthetic_phase1_report(dry_run=True)
    assert report.advisory_status == "ADVISORY_ONLY"
    assert report.ai_execution_count == 0
    assert report.execution_gate == "LOCKED"
    assert report.human_review_required is True
    assert report.total_persisted == 0


# ---------------------------------------------------------------------------
# check_signal_event_persistence
# ---------------------------------------------------------------------------


def test_check_signal_event_persistence_passes(tmp_path, smoke, p):
    db = tmp_path / "sig.db"
    p.init_schema(db)
    result = smoke.check_signal_event_persistence(db)
    assert result.passed, result.message


def test_signal_event_advisory_stamps(tmp_path, p):
    db = tmp_path / "sig_stamps.db"
    p.init_schema(db)
    p.insert_signal_event(
        "test_evt_001",
        "synthetic",
        {"k": "v"},
        "2026-01-01T00:00:00Z",
        db_path=db,
    )
    events = p.get_signal_events(db_path=db)
    assert events
    ev = events[0]
    assert ev["advisory_status"] == "ADVISORY_ONLY"
    assert ev["ai_execution_count"] == 0
    assert ev["execution_gate"] == "LOCKED"
    assert ev["human_review_required"] is True


def test_signal_event_duplicate_ignored(tmp_path, p):
    db = tmp_path / "dup.db"
    p.init_schema(db)
    r1 = p.insert_signal_event("dup_001", "src", {}, "2026-01-01T00:00:00Z", db_path=db)
    r2 = p.insert_signal_event("dup_001", "src", {}, "2026-01-01T00:00:00Z", db_path=db)
    assert r1 is True
    assert r2 is False
    events = p.get_signal_events(db_path=db)
    assert len([e for e in events if e["event_id"] == "dup_001"]) == 1


# ---------------------------------------------------------------------------
# check_reflection_persistence
# ---------------------------------------------------------------------------


def test_check_reflection_persistence_passes(tmp_path, smoke, p):
    db = tmp_path / "refl.db"
    p.init_schema(db)
    # smoke check inserts smoke_evt_001
    result = smoke.check_reflection_persistence(db)
    assert result.passed, result.message


def test_reflection_advisory_stamps(tmp_path, p):
    db = tmp_path / "refl_stamps.db"
    p.init_schema(db)
    p.insert_reflection(
        "r001", "evt001", "human", "HIGH",
        "test reflection", "2026-01-01T00:00:00Z",
        db_path=db,
    )
    rows = p.get_reflections_for_event("evt001", db_path=db)
    assert rows
    r = rows[0]
    assert r["advisory_status"] == "ADVISORY_ONLY"
    assert r["execution_mode"] == "HUMAN_ONLY"
    assert r["ai_execution_count"] == 0
    assert r["human_review_required"] is True


def test_has_reflection_returns_correct_bool(tmp_path, p):
    db = tmp_path / "has_refl.db"
    p.init_schema(db)
    assert p.has_reflection("evt_absent", db_path=db) is False
    p.insert_reflection(
        "r002", "evt_present", "human", "MODERATE",
        "text", "2026-01-01T00:00:00Z", db_path=db,
    )
    assert p.has_reflection("evt_present", db_path=db) is True
    assert p.has_reflection("evt_absent", db_path=db) is False


# ---------------------------------------------------------------------------
# check_manual_trade_persistence
# ---------------------------------------------------------------------------


def test_check_manual_trade_persistence_passes(tmp_path, smoke):
    db = tmp_path / "mt.db"
    result = smoke.check_manual_trade_persistence(db)
    assert result.passed, result.message


def test_manual_trade_human_only_stamps(tmp_path, p):
    db = tmp_path / "mt_stamps.db"
    p.init_schema(db)
    p.insert_manual_trade(
        "t001", "e001", "TSLA", "BUY", 2.0, 200.0,
        "2026-01-01T00:00:00Z", "thesis", "", "human",
        db_path=db,
    )
    trades = p.get_all_manual_trades(db_path=db)
    assert trades
    t = trades[0]
    assert t["execution_mode"] == "HUMAN_ONLY"
    assert t["ai_execution_count"] == 0
    assert t["broker_api_called"] is False
    assert t["broker_order_id"] == "NONE"
    assert t["advisory_status"] == "ADVISORY_ONLY"
    assert t["human_review_required"] is True


def test_get_event_id_for_trade(tmp_path, p):
    db = tmp_path / "trade_evt.db"
    p.init_schema(db)
    p.insert_manual_trade(
        "t_lookup", "e_lookup", "MSFT", "SELL", 1.0, 300.0,
        "2026-01-01T00:00:00Z", "thesis", "", "human",
        db_path=db,
    )
    assert p.get_event_id_for_trade("t_lookup", db_path=db) == "e_lookup"
    assert p.get_event_id_for_trade("t_missing", db_path=db) == ""


# ---------------------------------------------------------------------------
# check_reconciliation_persistence
# ---------------------------------------------------------------------------


def test_check_reconciliation_persistence_passes(tmp_path, smoke, p):
    db = tmp_path / "rec.db"
    p.init_schema(db)
    p.insert_manual_trade(
        "smoke_mt_001", "smoke_evt_001", "AAPL", "BUY", 1.0, 100.0,
        "2026-01-01T00:00:00Z", "thesis", "", "human",
        db_path=db,
    )
    result = smoke.check_reconciliation_persistence(db)
    assert result.passed, result.message


def test_reconciliation_advisory_stamps(tmp_path, p):
    db = tmp_path / "rec_stamps.db"
    p.init_schema(db)
    p.insert_reconciliation(
        "rec001", "mt001", "evt001",
        "2026-01-01T00:00:00Z",
        100.0, 1.0, "notes", 0.0, "UNKNOWN",
        db_path=db,
    )
    recs = p.get_all_reconciliations(db_path=db)
    assert recs
    r = recs[0]
    assert r["advisory_status"] == "ADVISORY_ONLY"
    assert r["execution_mode"] == "HUMAN_ONLY"
    assert r["ai_execution_count"] == 0


def test_reconciliation_for_trade_lookup(tmp_path, p):
    db = tmp_path / "rec_lookup.db"
    p.init_schema(db)
    p.insert_reconciliation(
        "rec_lk", "mt_lk", "evt_lk",
        "2026-01-01T00:00:00Z",
        105.0, 1.0, "", 5.0, "WIN",
        db_path=db,
    )
    rows = p.get_reconciliations_for_trade("mt_lk", db_path=db)
    assert len(rows) == 1
    assert rows[0]["outcome_status"] == "WIN"
    assert p.get_reconciliations_for_trade("mt_absent", db_path=db) == []


# ---------------------------------------------------------------------------
# check_moltbook_persistence
# ---------------------------------------------------------------------------


def test_check_moltbook_persistence_passes(tmp_path, smoke):
    db = tmp_path / "molt.db"
    result = smoke.check_moltbook_persistence(db)
    assert result.passed, result.message


def test_moltbook_advisory_stamps(tmp_path, p):
    db = tmp_path / "molt_stamps.db"
    p.init_schema(db)
    p.insert_moltbook_entry(
        "mb001", "evt001", "NVDA",
        "", "", "", "no_trade", "", "",
        "late_entry", "lesson text", "", "", "",
        "2026-01-01T00:00:00Z",
        db_path=db,
    )
    entries = p.get_moltbook_entries(db_path=db)
    assert entries
    m = entries[0]
    assert m["advisory_status"] == "ADVISORY_ONLY"
    assert m["execution_mode"] == "HUMAN_ONLY"
    assert m["ai_execution_count"] == 0


def test_moltbook_filter_by_ticker(tmp_path, p):
    db = tmp_path / "molt_filter.db"
    p.init_schema(db)
    p.insert_moltbook_entry(
        "mb_t1", "evt_t1", "TSLA",
        "", "", "", "no_trade", "", "",
        "late_entry", "lesson", "", "", "",
        "2026-01-01T00:00:00Z", db_path=db,
    )
    p.insert_moltbook_entry(
        "mb_t2", "evt_t2", "AAPL",
        "", "", "", "no_trade", "", "",
        "late_entry", "lesson", "", "", "",
        "2026-01-01T00:00:00Z", db_path=db,
    )
    tsla = p.get_moltbook_entries(ticker="TSLA", db_path=db)
    aapl = p.get_moltbook_entries(ticker="AAPL", db_path=db)
    goog = p.get_moltbook_entries(ticker="GOOG", db_path=db)
    assert len(tsla) == 1 and tsla[0]["ticker"] == "TSLA"
    assert len(aapl) == 1 and aapl[0]["ticker"] == "AAPL"
    assert goog == []


# ---------------------------------------------------------------------------
# check_export_csv_output
# ---------------------------------------------------------------------------


def test_check_export_csv_output_passes(tmp_path, smoke, p):
    db = tmp_path / "export.db"
    p.init_schema(db)
    p.insert_manual_trade(
        "smoke_mt_001", "smoke_evt_001", "AAPL", "BUY", 1.0, 100.0,
        "2026-01-01T00:00:00Z", "thesis", "", "human",
        db_path=db,
    )
    p.insert_reflection(
        "smoke_ref_001", "smoke_evt_001", "human", "MODERATE",
        "test", "2026-01-01T00:00:00Z",
        db_path=db,
    )
    result = smoke.check_export_csv_output(db)
    assert result.passed, result.message


def test_export_csv_contains_advisory_column(tmp_path, p):
    db = tmp_path / "csv_adv.db"
    p.init_schema(db)
    p.insert_manual_trade(
        "t_csv", "e_csv", "GOOG", "BUY", 1.0, 100.0,
        "2026-01-01T00:00:00Z", "thesis", "", "human",
        db_path=db,
    )
    trades = p.get_all_manual_trades(db_path=db)
    assert trades
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(trades[0].keys()))
    writer.writeheader()
    writer.writerows(trades)
    output = buf.getvalue()
    assert "advisory_status" in output
    assert "ADVISORY_ONLY" in output
    assert "HUMAN_ONLY" in output


def test_export_csv_no_broker_order_ids(tmp_path, p):
    """No real broker order IDs appear in exported CSV — only 'NONE'."""
    db = tmp_path / "csv_broker.db"
    p.init_schema(db)
    p.insert_manual_trade(
        "t_bk1", "e_bk1", "AMZN", "BUY", 1.0, 100.0,
        "2026-01-01T00:00:00Z", "thesis", "", "human",
        db_path=db,
    )
    trades = p.get_all_manual_trades(db_path=db)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(trades[0].keys()))
    writer.writeheader()
    writer.writerows(trades)
    output = buf.getvalue()
    # broker_order_id column is present
    assert "broker_order_id" in output
    # only placeholder value allowed — no real order IDs
    assert "NONE" in output


# ---------------------------------------------------------------------------
# check_no_execution_permission
# ---------------------------------------------------------------------------


def test_check_no_execution_permission_passes(smoke):
    result = smoke.check_no_execution_permission()
    assert result.passed, result.message


def test_no_forbidden_functions_in_persistence():
    import ast

    src = (REPO_ROOT / "scripts" / "persistence.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    forbidden = {
        "place_order", "submit_order", "execute_trade", "auto_buy",
        "auto_sell", "broker_execute", "connect_broker", "broker_login",
        "grant_execution",
    }
    found = forbidden & defined
    assert not found, f"Forbidden functions in persistence.py: {found}"


def test_no_forbidden_functions_in_live_source_runner():
    import ast

    src = (REPO_ROOT / "scripts" / "live_source_runner.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    forbidden = {
        "place_order", "submit_order", "execute_trade", "auto_buy",
        "auto_sell", "broker_execute", "connect_broker", "broker_login",
        "grant_execution",
    }
    found = forbidden & defined
    assert not found, f"Forbidden functions in live_source_runner.py: {found}"


# ---------------------------------------------------------------------------
# check_ai_execution_count
# ---------------------------------------------------------------------------


def test_check_ai_execution_count_passes(tmp_path, smoke, p):
    db = tmp_path / "ai_zero.db"
    p.init_schema(db)
    p.insert_manual_trade(
        "smoke_mt_001", "smoke_evt_001", "AAPL", "BUY", 1.0, 100.0,
        "2026-01-01T00:00:00Z", "thesis", "", "human", db_path=db,
    )
    p.insert_reflection(
        "smoke_ref_001", "smoke_evt_001", "human", "MODERATE",
        "text", "2026-01-01T00:00:00Z", db_path=db,
    )
    p.insert_moltbook_entry(
        "smoke_mb_001", "smoke_evt_001", "AAPL",
        "", "", "", "no_trade", "", "",
        "late_entry", "lesson", "", "", "",
        "2026-01-01T00:00:00Z", db_path=db,
    )
    result = smoke.check_ai_execution_count(db)
    assert result.passed, result.message


def test_ai_execution_count_always_zero_all_tables(tmp_path, p):
    db = tmp_path / "ai_all.db"
    p.init_schema(db)

    p.insert_manual_trade(
        "t_ai", "e_ai", "MSFT", "SELL", 1.0, 200.0,
        "2026-01-01T00:00:00Z", "thesis", "", "human", db_path=db,
    )
    p.insert_reflection(
        "r_ai", "e_ai", "human", "LOW", "text",
        "2026-01-01T00:00:00Z", db_path=db,
    )
    p.insert_ai_summary(
        "s_ai", "e_ai", "AI_ADVISORY", "summary",
        "2026-01-01T00:00:00Z", db_path=db,
    )
    p.insert_moltbook_entry(
        "m_ai", "e_ai", "MSFT", "", "", "", "no_trade", "", "",
        "missed_signal", "lesson", "", "", "",
        "2026-01-01T00:00:00Z", db_path=db,
    )

    for t in p.get_all_manual_trades(db_path=db):
        assert t["ai_execution_count"] == 0, f"trade: {t}"
    for r in p.get_all_reflections(db_path=db):
        assert r["ai_execution_count"] == 0, f"reflection: {r}"
    for s in p.get_all_ai_summaries(db_path=db):
        assert s["ai_execution_count"] == 0, f"summary: {s}"
    for m in p.get_moltbook_entries(db_path=db):
        assert m["ai_execution_count"] == 0, f"moltbook: {m}"

    assert p.get_db_status(db_path=db)["ai_execution_count"] == 0


# ---------------------------------------------------------------------------
# check_broker_invariants
# ---------------------------------------------------------------------------


def test_check_broker_invariants_passes(tmp_path, smoke, p):
    db = tmp_path / "broker.db"
    p.init_schema(db)
    p.insert_manual_trade(
        "smoke_mt_001", "smoke_evt_001", "AAPL", "BUY", 1.0, 100.0,
        "2026-01-01T00:00:00Z", "thesis", "", "human", db_path=db,
    )
    result = smoke.check_broker_invariants(db)
    assert result.passed, result.message


def test_broker_api_called_always_false(tmp_path, p):
    db = tmp_path / "broker_false.db"
    p.init_schema(db)
    for i in range(3):
        p.insert_manual_trade(
            f"t_br{i}", f"e_br{i}", "AMZN", "BUY", 1.0, 100.0,
            "2026-01-01T00:00:00Z", "thesis", "", "human", db_path=db,
        )
    for t in p.get_all_manual_trades(db_path=db):
        assert t["broker_api_called"] is False, f"broker_api_called truthy: {t}"
        assert t["broker_order_id"] == "NONE", f"non-NONE broker_order_id: {t}"
    assert p.get_db_status(db_path=db)["broker_api_called"] is False


# ---------------------------------------------------------------------------
# Full smoke test integration
# ---------------------------------------------------------------------------


def test_run_smoke_tests_all_pass_with_mock():
    """Full smoke suite passes when live source runner is mocked."""
    import scripts.local_mvp_smoke_test as smoke

    mock_runner = MagicMock(return_value=_synthetic_phase1_report(dry_run=True))
    report = smoke.run_smoke_tests(live_source_runner=mock_runner)

    failed = [c for c in report.checks if not c.passed]
    assert not failed, f"Failed checks: {[(c.name, c.message) for c in failed]}"
    assert report.all_passed is True


def test_run_smoke_tests_skip_live_source():
    """Smoke suite passes with skip_live_source=True; check is marked SKIPPED."""
    import scripts.local_mvp_smoke_test as smoke

    report = smoke.run_smoke_tests(skip_live_source=True)
    live_check = next(c for c in report.checks if c.name == "live_source_dry_run")
    assert live_check.passed
    assert "SKIPPED" in live_check.message


def test_smoke_report_advisory_invariants():
    """SmokeTestReport itself carries the correct advisory stamps."""
    import scripts.local_mvp_smoke_test as smoke

    mock_runner = MagicMock(return_value=_synthetic_phase1_report(dry_run=True))
    report = smoke.run_smoke_tests(live_source_runner=mock_runner)

    assert report.advisory_status == "ADVISORY_ONLY"
    assert report.ai_execution_count == 0
    assert report.broker_api_called is False
    assert report.broker_order_id == "NONE"


def test_smoke_report_to_dict_shape():
    """to_dict() returns all required keys with correct types."""
    import scripts.local_mvp_smoke_test as smoke

    mock_runner = MagicMock(return_value=_synthetic_phase1_report(dry_run=True))
    report = smoke.run_smoke_tests(live_source_runner=mock_runner)
    d = report.to_dict()

    assert d["advisory_status"] == "ADVISORY_ONLY"
    assert d["ai_execution_count"] == 0
    assert d["broker_api_called"] is False
    assert d["broker_order_id"] == "NONE"
    assert isinstance(d["checks"], list)
    assert d["all_passed"] is True
    assert d["passed"] == len(d["checks"])
    assert d["failed"] == 0


def test_smoke_check_count():
    """All expected checks are present in the report."""
    import scripts.local_mvp_smoke_test as smoke

    mock_runner = MagicMock(return_value=_synthetic_phase1_report(dry_run=True))
    report = smoke.run_smoke_tests(live_source_runner=mock_runner)
    names = {c.name for c in report.checks}

    expected = {
        "db_init",
        "db_status",
        "signal_event_persistence",
        "reflection_persistence",
        "manual_trade_persistence",
        "reconciliation_persistence",
        "moltbook_persistence",
        "export_csv_output",
        "ai_execution_count",
        "broker_invariants",
        "no_execution_permission",
        "live_source_dry_run",
    }
    missing = expected - names
    assert not missing, f"Missing checks in report: {missing}"
