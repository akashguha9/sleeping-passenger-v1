"""Non-destructive schema versioning (Kanté Sprint 2 — Task 7)."""
from __future__ import annotations

import pytest

from scripts import persistence
from scripts import schema_migrations as sm


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "mvp_local.db"
    persistence.init_schema(path)
    return path


def test_get_version_is_read_only_no_table(db):
    # A fresh DB has no schema_version table; get must NOT create it.
    assert sm.schema_version_table_exists(db) is False
    assert sm.get_schema_version(db) is None
    assert sm.schema_version_table_exists(db) is False


def test_init_records_current_version(db):
    result = sm.init_schema_version(db)
    assert result["version_inserted"] is True
    assert sm.get_schema_version(db) == sm.CODE_SCHEMA_VERSION
    assert sm.schema_version_table_exists(db) is True


def test_init_is_idempotent(db):
    sm.init_schema_version(db)
    second = sm.init_schema_version(db)
    assert second["version_inserted"] is False
    assert sm.get_schema_version(db) == sm.CODE_SCHEMA_VERSION


def test_check_version_matches_after_init(db):
    sm.init_schema_version(db)
    check = sm.check_version(db)
    assert check["matches"] is True
    assert check["runtime_version"] == sm.CODE_SCHEMA_VERSION
    assert check["behind"] is False


def test_init_is_non_destructive(db):
    persistence.insert_manual_trade(
        "T1", "EV1", "AAPL", "BUY", 1.0, 10.0, "2026-05-20T00:00:00+00:00",
        "t", "n", "human", db_path=db, created_via="manual_trade_log",
    )
    sm.init_schema_version(db)
    trades = persistence.get_all_manual_trades(db_path=db)
    assert any(t["trade_id"] == "T1" for t in trades)


def test_check_version_missing_db(tmp_path):
    check = sm.check_version(tmp_path / "nope.db")
    assert check["db_exists"] is False
    assert check["runtime_version"] is None
    assert check["matches"] is False
