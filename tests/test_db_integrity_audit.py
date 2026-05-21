"""Canonical DB integrity audit (Kanté Sprint 2 — Task 7)."""
from __future__ import annotations

import pytest

from scripts import persistence
from scripts import schema_migrations as sm
from scripts import db_integrity_audit as audit


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "mvp_local.db"
    persistence.init_schema(path)
    return path


def _moltbook(db, entry_id, *, event_id="EV1", ticker="AAPL", trade_link="",
              thesis="real thesis"):
    persistence.insert_moltbook_entry(
        entry_id, event_id, ticker, thesis, "ai", "reflect", "exit",
        trade_link, "outcome", "trade_loss", "lesson", "", "", "",
        "2026-05-21T00:00:00+00:00", db_path=db,
    )


def test_clean_db_passes(db):
    sm.init_schema_version(db)
    report = audit.run_integrity_audit(db)
    assert report["overall"] == "PASS", report["checks"]
    assert report["integrity_score"] == 1.0


def test_clean_db_without_version_warns(db):
    report = audit.run_integrity_audit(db)
    sv = next(c for c in report["checks"] if c["name"] == "schema_version_present")
    assert sv["status"] == "WARN"
    assert report["overall"] == "WARN"


def test_audit_is_read_only_does_not_create_version_table(db):
    audit.run_integrity_audit(db)
    assert sm.schema_version_table_exists(db) is False


def test_audit_fails_on_fake_pollution(db):
    sm.init_schema_version(db)
    _moltbook(db, "MB_FAKE", event_id="FABRIC_SPY_1", ticker="SPY",
              thesis="Persistence above 0.8", trade_link="")
    report = audit.run_integrity_audit(db)
    pol = next(c for c in report["checks"] if c["name"] == "moltbook_no_fake_pollution")
    assert pol["status"] == "FAIL"
    assert report["overall"] == "FAIL"


def test_audit_fails_on_duplicate_moltbook_trade_link(db):
    sm.init_schema_version(db)
    persistence.insert_manual_trade(
        "T1", "EV1", "AAPL", "BUY", 1.0, 10.0, "2026-05-20T00:00:00+00:00",
        "t", "n", "human", db_path=db, created_via="manual_trade_log",
    )
    _moltbook(db, "MB1", trade_link="T1")
    _moltbook(db, "MB2", trade_link="T1")
    report = audit.run_integrity_audit(db)
    dup = next(c for c in report["checks"]
               if c["name"] == "moltbook_no_duplicate_trade_link")
    assert dup["status"] == "FAIL"
    assert report["defect_breakdown"]["duplicate_keys"] >= 1


def test_audit_warns_on_orphaned_link(db):
    sm.init_schema_version(db)
    _moltbook(db, "MB_ORPHAN", trade_link="NO_SUCH_TRADE")
    report = audit.run_integrity_audit(db)
    orphan = next(c for c in report["checks"]
                  if c["name"] == "no_orphaned_moltbook_links")
    assert orphan["status"] == "WARN"
    assert report["defect_breakdown"]["broken_links"] >= 1


def test_missing_db_fails_closed(tmp_path):
    report = audit.run_integrity_audit(tmp_path / "nope.db")
    assert report["overall"] == "FAIL"
    assert report["integrity_score"] == 0.0
