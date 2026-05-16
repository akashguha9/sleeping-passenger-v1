"""Tests for ``scripts/db_hygiene_report.py``.

The hygiene report is a *diagnostic-only* read-only snapshot of the
local SQLite DB.  These tests verify:

* The report shape is stable and includes all required fields.
* It degrades gracefully when the DB is missing.
* Table/row counts are accurate.
* Important tables are detected when present and reported as missing
  when absent.
* Timestamp coverage and source distribution are surfaced when the
  necessary columns exist.
* The DB bytes on disk are *not* modified by running the report
  (no DELETE, no INSERT, no VACUUM, no UPDATE).
* Safety stamps are present.
* Recommendations follow the documented thresholds.
* The module source contains no broker / execution / permission
  language and no VACUUM/DELETE/INSERT/UPDATE keywords.
"""
from __future__ import annotations

import inspect
import json
import re
import sqlite3
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts import db_hygiene_report as dhr  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_db(tmp_path: Path, *, signal_event_rows: int = 7) -> Path:
    """Build a temp DB that exercises the report.

    Includes:
      * ``signal_events`` (with a ``source`` column) to drive the
        source-distribution branch.
      * ``manual_trades`` (with ``created_at``) so timestamp coverage
        has something to surface.
      * ``source_run_log`` (with ``started_at``) to cover a second
        timestamp candidate.
      * An ``UNIMPORTANT`` table the report should count but not
        special-case.
      * An index so the index list isn't empty.
    """
    db = tmp_path / "hygiene.db"
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "CREATE TABLE signal_events ("
            "  event_id TEXT PRIMARY KEY, source TEXT, created_at TEXT"
            ")"
        )
        conn.execute(
            "CREATE TABLE manual_trades ("
            "  trade_id TEXT PRIMARY KEY, ticker TEXT, created_at TEXT"
            ")"
        )
        conn.execute(
            "CREATE TABLE source_run_log ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT, source_key TEXT, "
            "  started_at TEXT, finished_at TEXT"
            ")"
        )
        conn.execute(
            "CREATE TABLE unimportant ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT, x TEXT"
            ")"
        )
        conn.execute(
            "CREATE INDEX idx_signal_events_source ON signal_events(source)"
        )
        sources = ["gdelt", "newsapi", "gdelt", "polymarket", "newsapi"]
        rows: list[tuple[str, str, str]] = []
        for i in range(signal_event_rows):
            src = sources[i % len(sources)]
            ts = f"2026-05-{1 + (i % 28):02d}T12:00:00+00:00"
            rows.append((f"E{i}", src, ts))
        conn.executemany(
            "INSERT INTO signal_events (event_id, source, created_at) "
            "VALUES (?, ?, ?)",
            rows,
        )
        conn.executemany(
            "INSERT INTO manual_trades (trade_id, ticker, created_at) "
            "VALUES (?, ?, ?)",
            [
                ("T1", "X", "2026-05-01T09:00:00+00:00"),
                ("T2", "Y", "2026-05-02T09:00:00+00:00"),
                ("T3", "Z", "2026-05-10T09:00:00+00:00"),
            ],
        )
        conn.executemany(
            "INSERT INTO source_run_log (source_key, started_at, finished_at) "
            "VALUES (?, ?, ?)",
            [
                ("gdelt", "2026-05-15T10:00:00+00:00", "2026-05-15T10:00:05+00:00"),
                ("newsapi", "2026-05-15T11:00:00+00:00", "2026-05-15T11:00:02+00:00"),
            ],
        )
        conn.commit()
    finally:
        conn.close()
    return db


# ---------------------------------------------------------------------------
# Shape / missing-DB safety
# ---------------------------------------------------------------------------


def test_missing_db_returns_safe_shape(tmp_path: Path) -> None:
    missing = tmp_path / "absent.db"
    rep = dhr.build_report(missing)
    assert rep["report"] == "db_hygiene_report"
    assert rep["db_exists"] is False
    assert rep["db_size_bytes"] is None
    assert rep["table_count"] == 0
    assert rep["table_counts"] == {}
    assert rep["largest_tables"] == []
    assert rep["important_tables"] == {}
    assert rep["timestamp_coverage"] == {}
    assert rep["source_distribution"] is None
    assert rep["indexes"] == []
    assert "db_missing" in rep["warnings"]
    # Recommendations still well-formed.
    assert rep["recommendations"] == ["no_action"]


def test_report_includes_required_fields(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    rep = dhr.build_report(db)
    for key in (
        "report",
        "generated_at",
        "db_path",
        "db_exists",
        "db_size_bytes",
        "sqlite_page_count",
        "sqlite_page_size",
        "sqlite_freelist_count",
        "table_count",
        "table_counts",
        "largest_tables",
        "important_tables",
        "timestamp_coverage",
        "source_distribution",
        "indexes",
        "recommendations",
        "warnings",
        "no_claims",
    ):
        assert key in rep, f"missing field {key!r}"


# ---------------------------------------------------------------------------
# Counts / important-tables / timestamps
# ---------------------------------------------------------------------------


def test_table_counts_accurate(tmp_path: Path) -> None:
    db = _make_db(tmp_path, signal_event_rows=11)
    rep = dhr.build_report(db)
    counts = rep["table_counts"]
    assert counts["signal_events"] == 11
    assert counts["manual_trades"] == 3
    assert counts["source_run_log"] == 2
    # The unimportant table is still counted.
    assert counts["unimportant"] == 0


def test_largest_tables_sorted_desc(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    rep = dhr.build_report(db)
    counts = [entry["row_count"] for entry in rep["largest_tables"]]
    assert counts == sorted(counts, reverse=True)


def test_important_tables_present_and_missing(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    rep = dhr.build_report(db)
    important = rep["important_tables"]
    # Present ones expose row_count + column_count.
    assert important["signal_events"]["present"] is True
    assert important["signal_events"]["row_count"] >= 1
    assert important["manual_trades"]["present"] is True
    # Missing ones are reported as absent rather than omitted.
    assert important["reconciliations"]["present"] is False


def test_timestamp_coverage_uses_first_matching_column(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    rep = dhr.build_report(db)
    cov = rep["timestamp_coverage"]
    assert "manual_trades" in cov
    assert cov["manual_trades"]["column"] == "created_at"
    assert cov["manual_trades"]["oldest"] == "2026-05-01T09:00:00+00:00"
    assert cov["manual_trades"]["newest"] == "2026-05-10T09:00:00+00:00"
    # source_run_log has started_at, no created_at — the report should
    # pick started_at as the first candidate.
    assert cov["source_run_log"]["column"] == "started_at"


def test_source_distribution_when_signal_events_has_source(tmp_path: Path) -> None:
    db = _make_db(tmp_path, signal_event_rows=10)
    rep = dhr.build_report(db)
    dist = rep["source_distribution"]
    assert isinstance(dist, dict)
    assert sum(dist.values()) == 10
    # Top key must have the largest count (descending order).
    counts = list(dist.values())
    assert counts == sorted(counts, reverse=True)


def test_indexes_listed(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    rep = dhr.build_report(db)
    names = {entry["name"] for entry in rep["indexes"]}
    assert "idx_signal_events_source" in names


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------


def test_recommendations_default_to_no_action(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    rep = dhr.build_report(db)
    assert rep["recommendations"] == ["no_action"]


def test_recommendations_flag_large_signal_events(tmp_path: Path) -> None:
    # Bypass build_report directly to avoid inserting 100k rows in a
    # test; we exercise the pure recommendation helper.
    recs = dhr._build_recommendations(
        db_size=1_000_000,
        table_counts={"signal_events": dhr._SIGNAL_EVENTS_MONITOR_ROWS + 1},
        freelist_count=0,
    )
    assert "consider_archive_policy_later" in recs
    assert "no_action" not in recs


def test_recommendations_flag_db_size_thresholds() -> None:
    recs_small = dhr._build_recommendations(
        db_size=10 * 1024 * 1024, table_counts={}, freelist_count=0
    )
    assert recs_small == ["no_action"]
    recs_mid = dhr._build_recommendations(
        db_size=200 * 1024 * 1024, table_counts={}, freelist_count=0
    )
    assert "monitor_db_size" in recs_mid
    recs_large = dhr._build_recommendations(
        db_size=600 * 1024 * 1024, table_counts={}, freelist_count=0
    )
    assert "consider_archive_policy_later" in recs_large


def test_recommendations_freelist_advises_backup_first() -> None:
    recs = dhr._build_recommendations(
        db_size=1024, table_counts={}, freelist_count=12
    )
    assert "consider_vacuum_only_after_backup" in recs


# ---------------------------------------------------------------------------
# Read-only behaviour
# ---------------------------------------------------------------------------


def test_read_only_does_not_mutate_db(tmp_path: Path) -> None:
    db = _make_db(tmp_path)
    before = db.read_bytes()
    dhr.build_report(db)
    after = db.read_bytes()
    assert before == after


# ---------------------------------------------------------------------------
# Safety / no-claims / no broker-execution language
# ---------------------------------------------------------------------------


def test_safety_stamps_present(tmp_path: Path) -> None:
    rep = dhr.build_report(tmp_path / "missing.db")
    assert rep["advisory_only"] is True
    assert rep["advisory_status"] == "ADVISORY_ONLY"
    assert rep["execution_gate"] == "LOCKED"
    assert rep["broker_api_called"] is False
    assert rep["execution_permission"] is False
    assert rep["can_execute"] is False
    assert rep["ai_execution_count"] == 0


def test_no_claims_footer_present(tmp_path: Path) -> None:
    rep = dhr.build_report(tmp_path / "missing.db")
    joined = " ".join(rep["no_claims"]).lower()
    assert "diagnostic only" in joined
    assert "deleted" in joined and "archived" in joined and "vacuumed" in joined
    assert "performance/scalability is not solved" in joined


def test_no_secrets_in_serialized_output(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MVP_API_TOKEN", "hunter2_super_secret")
    monkeypatch.setenv("ETHERSCAN_API_KEY", "key_should_not_leak")
    rep = dhr.build_report(tmp_path / "absent.db")
    blob = json.dumps(rep, default=str)
    assert "hunter2_super_secret" not in blob
    assert "key_should_not_leak" not in blob


def test_module_has_no_broker_or_execution_language() -> None:
    src = inspect.getsource(dhr)
    lowered = src.lower()
    for forbidden in (
        "place_order",
        "submit_order",
        "execute_trade",
        "broker_execute",
        "trade now",
        "ai-approved",
        "permission to trade",
        "auto-trading",
        "order_id",
    ):
        assert forbidden not in lowered, (
            f"forbidden phrase {forbidden!r} present in db_hygiene_report"
        )
    for pat in (r"\balpaca\b", r"\bibkr\b", r"\boanda\b"):
        assert re.search(pat, src, flags=re.IGNORECASE) is None, pat


def test_module_has_no_mutation_sql() -> None:
    """The hygiene module must never issue mutating SQL.

    We scan for SQL verb keywords as standalone tokens.  The strings
    appearing inside docstrings (e.g. "never deletes") are negated and
    safe — we exclude lines that mention them in negated form.
    """
    src = inspect.getsource(dhr)
    forbidden_sql = ("DELETE FROM", "INSERT INTO", "UPDATE ", "DROP TABLE", "VACUUM")
    for kw in forbidden_sql:
        # Case-sensitive: we're checking executable SQL, not docstring
        # English ("never deletes" is fine).
        assert kw not in src, (
            f"db_hygiene_report module must not contain SQL {kw!r}"
        )


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------


def test_cli_json_runs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = _make_db(tmp_path)
    rc = dhr.main(["--db-path", str(db), "--json"])
    assert rc == 0
    captured = capsys.readouterr().out
    payload = json.loads(captured)
    assert payload["report"] == "db_hygiene_report"
    assert payload["db_exists"] is True


def test_cli_text_runs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = _make_db(tmp_path)
    rc = dhr.main(["--db-path", str(db)])
    assert rc == 0
    captured = capsys.readouterr().out
    assert "DB Hygiene Report" in captured
    assert "ADVISORY_ONLY" in captured
