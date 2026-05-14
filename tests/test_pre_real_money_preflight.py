"""Tests for ``scripts.pre_real_money_preflight``.

Pin
---
- All subchecks pass against a healthy DB + repo => ok=True.
- DB failure -> ok=False with ``db_integrity_failed`` blocking issue.
- Large unreconciled backlog escalates to BLOCK / FULL_REVIEW.
- No secret values leak into the payload.
- Safety stamps locked.
- No DB writes.
"""
from __future__ import annotations

import datetime as _dt
import json
import sqlite3
from pathlib import Path

import pytest

from scripts import pre_real_money_preflight as prp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_full_repo(tmp_path: Path) -> tuple[Path, Path]:
    """Build a minimal repo + DB structure the preflight can run against."""
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
                lesson TEXT DEFAULT ''
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


def _insert_unreconciled(db: Path, count: int) -> None:
    conn = sqlite3.connect(str(db))
    try:
        for i in range(count):
            conn.execute(
                "INSERT INTO manual_trades (trade_id, event_id, ticker, side, quantity,"
                " price, executed_at, thesis, notes)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (f"T{i}", f"EV{i}", "QQQ", "BUY", 10, 100.0,
                 "2026-05-10T00:00:00Z", "test", ""),
            )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_preflight_passes_on_healthy_repo(tmp_path):
    root, db = _make_full_repo(tmp_path)
    payload = prp.run_preflight(db, repo_root=root, env={})
    assert payload["ok"] is True, payload.get("blocking_issues")
    assert payload["advisory_status"] == "ADVISORY_ONLY"
    assert payload["execution_permission"] is False


def test_preflight_includes_all_subchecks(tmp_path):
    root, db = _make_full_repo(tmp_path)
    payload = prp.run_preflight(db, repo_root=root, env={})
    subchecks = payload["subchecks"]
    assert "db_integrity" in subchecks
    assert "local_security" in subchecks
    assert "source_refresh" in subchecks
    assert "self_test_summary" in subchecks
    assert "reconciliation_queue" in subchecks


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


def test_db_failure_blocks(tmp_path):
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "api_server.py").write_text("# stub\n", encoding="utf-8")
    # No DB file at the expected path.
    db = root / "runtime" / "absent.db"
    payload = prp.run_preflight(db, repo_root=root, env={})
    assert payload["ok"] is False
    assert "db_integrity_failed" in payload["blocking_issues"]


def test_security_failure_blocks(tmp_path):
    root, db = _make_full_repo(tmp_path)
    # Plant a forbidden execution word in api_server.py to trip the audit.
    (root / "scripts" / "api_server.py").write_text(
        "def place_order():\n    pass\n", encoding="utf-8"
    )
    payload = prp.run_preflight(db, repo_root=root, env={})
    assert payload["ok"] is False
    assert "local_security_failed" in payload["blocking_issues"]


# ---------------------------------------------------------------------------
# Unreconciled backlog thresholds
# ---------------------------------------------------------------------------


def test_unreconciled_warn_at_threshold(tmp_path):
    root, db = _make_full_repo(tmp_path)
    _insert_unreconciled(db, prp.UNRECONCILED_WARN_THRESHOLD)
    payload = prp.run_preflight(db, repo_root=root, env={})
    assert "unreconciled_backlog_warn" in payload["warnings"]
    # Not blocking yet.
    assert payload["ok"] is True or "unreconciled_backlog_block" not in (
        payload["blocking_issues"]
    )


def test_unreconciled_block_threshold(tmp_path):
    root, db = _make_full_repo(tmp_path)
    _insert_unreconciled(db, prp.UNRECONCILED_BLOCK_THRESHOLD)
    payload = prp.run_preflight(db, repo_root=root, env={})
    assert payload["ok"] is False
    assert "unreconciled_backlog_block" in payload["blocking_issues"]


def test_unreconciled_full_review_threshold(tmp_path):
    root, db = _make_full_repo(tmp_path)
    _insert_unreconciled(db, prp.UNRECONCILED_FULL_REVIEW_THRESHOLD)
    payload = prp.run_preflight(db, repo_root=root, env={})
    assert payload["ok"] is False
    assert "unreconciled_backlog_full_review" in payload["blocking_issues"]


# ---------------------------------------------------------------------------
# Secret hygiene
# ---------------------------------------------------------------------------


def test_no_secret_exposure(tmp_path):
    root, db = _make_full_repo(tmp_path)
    payload = prp.run_preflight(
        db, repo_root=root,
        env={"MVP_API_TOKEN": "supersecret-token-zzz-999"},
    )
    serialized = json.dumps(payload)
    assert "supersecret-token-zzz-999" not in serialized


# ---------------------------------------------------------------------------
# Safety / structural
# ---------------------------------------------------------------------------


def test_safety_stamps_locked(tmp_path):
    root, db = _make_full_repo(tmp_path)
    payload = prp.run_preflight(db, repo_root=root, env={})
    assert payload["advisory_status"] == "ADVISORY_ONLY"
    assert payload["execution_gate"] == "LOCKED"
    assert payload["broker_api_called"] is False
    assert payload["ai_execution_count"] == 0
    assert payload["execution_permission"] is False
    assert payload["can_execute"] is False


def test_no_db_writes(tmp_path):
    root, db = _make_full_repo(tmp_path)
    _insert_unreconciled(db, 1)
    size = db.stat().st_size
    mtime = db.stat().st_mtime
    prp.run_preflight(db, repo_root=root, env={})
    assert db.stat().st_size == size
    assert db.stat().st_mtime == mtime


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_json(tmp_path, capsys):
    root, db = _make_full_repo(tmp_path)
    rc = prp.main([
        "--db-path", str(db),
        "--repo-root", str(root),
        "--json",
    ])
    out = capsys.readouterr().out
    assert "ADVISORY_ONLY" in out
    assert "pre_real_money_preflight" in out
    assert rc in (0, 1)


def test_cli_nonzero_on_missing_db(tmp_path):
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "api_server.py").write_text("# stub\n", encoding="utf-8")
    rc = prp.main([
        "--db-path", str(root / "runtime" / "absent.db"),
        "--repo-root", str(root),
    ])
    assert rc != 0
