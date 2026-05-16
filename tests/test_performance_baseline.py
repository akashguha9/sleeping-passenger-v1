"""Tests for ``scripts/performance_baseline.py``.

The baseline is measurement-only and read-only.  These tests cover:

* Shape — required fields present even when the DB is missing.
* Safety stamps + no-claims footer.
* Read-only behaviour — the DB is not mutated.
* Timings are numeric and non-negative.
* No secrets leak into the report; no broker / execution language is
  present in the module source.
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

from scripts import performance_baseline as pb  # noqa: E402


def _make_db(tmp_path: Path) -> Path:
    db = tmp_path / "mvp_local.db"
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("CREATE TABLE manual_trades (trade_id TEXT, trade_mode TEXT)")
        conn.execute("CREATE TABLE signal_events (event_id TEXT)")
        conn.execute(
            "INSERT INTO manual_trades (trade_id, trade_mode) VALUES "
            "('T1','PAPER'),('T2','PAPER'),('T3','REAL_MANUAL')"
        )
        conn.executemany(
            "INSERT INTO signal_events (event_id) VALUES (?)",
            [(f"S{i}",) for i in range(7)],
        )
        conn.commit()
    finally:
        conn.close()
    return db


# ---------------------------------------------------------------------------
# Shape / contract
# ---------------------------------------------------------------------------


def test_report_includes_required_top_level_fields(tmp_path):
    db = _make_db(tmp_path)
    rep = pb.build_report(db)

    for key in (
        "report",
        "generated_at",
        "db_path",
        "db_exists",
        "db_size_bytes",
        "table_count",
        "top_tables",
        "table_counts",
        "timing_ms",
        "warnings",
        "no_claims",
        "calibration_gate",
        "audit",
        "refresh_summary",
        "backups",
        "logs",
    ):
        assert key in rep, f"missing top-level field {key!r}"
    assert rep["report"] == "performance_baseline"
    assert rep["db_exists"] is True
    assert isinstance(rep["table_count"], int) and rep["table_count"] >= 2


def test_no_db_safe_output(tmp_path):
    missing = tmp_path / "does_not_exist.db"
    rep = pb.build_report(missing)
    assert rep["db_exists"] is False
    assert rep["db_size_bytes"] is None
    assert rep["table_count"] == 0
    assert rep["top_tables"] == []
    # Warnings surface db_missing; nothing raised.
    assert "db_missing" in rep["warnings"]


def test_table_counts_match_inserted_rows(tmp_path):
    db = _make_db(tmp_path)
    rep = pb.build_report(db)
    counts = rep["table_counts"]
    assert counts.get("manual_trades") == 3
    assert counts.get("signal_events") == 7


def test_top_tables_sorted_by_row_count_descending(tmp_path):
    db = _make_db(tmp_path)
    rep = pb.build_report(db)
    counts = [entry["row_count"] for entry in rep["top_tables"]]
    assert counts == sorted(counts, reverse=True)


# ---------------------------------------------------------------------------
# Timings
# ---------------------------------------------------------------------------


def test_timings_are_numeric_and_non_negative(tmp_path):
    db = _make_db(tmp_path)
    rep = pb.build_report(db)
    timing = rep["timing_ms"]
    db_timings = timing.get("db") or {}
    for key in ("open_readonly", "list_tables", "count_all_tables"):
        assert key in db_timings
        val = db_timings[key]
        assert isinstance(val, (int, float))
        assert val >= 0.0
    total = timing.get("total_ms")
    assert isinstance(total, (int, float))
    assert total >= 0.0


# ---------------------------------------------------------------------------
# Safety stamps and no-claims footer
# ---------------------------------------------------------------------------


def test_safety_stamps_present(tmp_path):
    db = _make_db(tmp_path)
    rep = pb.build_report(db)
    assert rep["advisory_only"] is True
    assert rep["advisory_status"] == "ADVISORY_ONLY"
    assert rep["execution_gate"] == "LOCKED"
    assert rep["broker_api_called"] is False
    assert rep["execution_permission"] is False
    assert rep["can_execute"] is False
    assert rep["ai_execution_count"] == 0


def test_no_claims_footer_present(tmp_path):
    rep = pb.build_report(tmp_path / "missing.db")
    claims = " ".join(rep["no_claims"]).lower()
    assert "measurement only" in claims
    assert "no optimization" in claims or "no scalability" in claims


# ---------------------------------------------------------------------------
# Read-only / safety
# ---------------------------------------------------------------------------


def test_read_only_behavior_does_not_mutate_db(tmp_path):
    db = _make_db(tmp_path)
    before = db.read_bytes()
    pb.build_report(db)
    after = db.read_bytes()
    assert before == after


def test_no_secrets_in_serialized_output(tmp_path, monkeypatch):
    """Even when the environment has a token set, the baseline output
    must not contain its value."""
    monkeypatch.setenv("MVP_API_TOKEN", "hunter2_super_secret")
    monkeypatch.setenv("ETHERSCAN_API_KEY", "key_should_not_leak")
    rep = pb.build_report(tmp_path / "missing.db")
    serialized = json.dumps(rep, default=str)
    assert "hunter2_super_secret" not in serialized
    assert "key_should_not_leak" not in serialized
    assert "MVP_API_TOKEN=" not in serialized


def test_module_has_no_broker_or_execution_language() -> None:
    src = inspect.getsource(pb)
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
            f"forbidden phrase {forbidden!r} present in performance_baseline"
        )
    for pat in (
        r"\balpaca\b",
        r"\bibkr\b",
        r"\binteractive[\s_-]?brokers\b",
        r"\boanda\b",
    ):
        assert re.search(pat, src, flags=re.IGNORECASE) is None, pat


def test_module_does_not_open_env_or_make_network_calls() -> None:
    """Lightweight static check: the baseline must not import network
    libraries or read .env.  We look for actual *code-level* uses, not
    literal substrings inside docstrings (the module's docstring
    legitimately states "never reads .env")."""
    src = inspect.getsource(pb)
    for forbidden in (
        "import requests",
        "from requests",
        "import urllib.request",
        "urllib.request.urlopen",
        "from dotenv",
        "load_dotenv(",
        "open('.env'",
        'open(".env"',
        'Path(".env"',
        "Path('.env'",
    ):
        assert forbidden not in src, (
            f"performance_baseline must not contain {forbidden!r}"
        )
