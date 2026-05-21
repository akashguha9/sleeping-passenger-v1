"""Bounded-load + query-plan evidence (Kanté Sprint 2 — Task 3).

Non-flaky proofs that the critical reads are indexed and row-capped:
the LIMIT clamp, index existence, EXPLAIN QUERY PLAN index usage, and a
synthetic-load probe that never touches the runtime DB.
"""
from __future__ import annotations

import sqlite3

import pytest

from scripts import persistence
from scripts import signal_index_query as siq
from scripts import sqlite_query_plan_audit as audit
from scripts import performance_probe as probe


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "mvp_local.db"
    persistence.init_schema(path)
    siq.ensure_indexes(path)
    return path


# ---------------------------------------------------------------------------
# LIMIT clamp
# ---------------------------------------------------------------------------


def test_max_limit_is_500():
    assert siq.MAX_LIMIT == 500


def test_limit_clamps_to_max():
    assert siq._clamp_limit(10 ** 9) == 500
    assert siq._clamp_limit(-5) == siq.DEFAULT_LIMIT
    assert siq._clamp_limit("garbage") == siq.DEFAULT_LIMIT
    assert siq._clamp_limit(10) == 10


def test_helper_refuses_unbounded_result(db):
    # 520 rows (> MAX_LIMIT) proves the clamp truncates a real overflow.
    for i in range(520):
        persistence.upsert_signal_cell(f"cell-{i}", sector="TECH", db_path=db)
    res = siq.query_signal_cells(db, sector="TECH", limit=10 ** 9)
    assert res["limit"] == 500
    assert res["row_count"] == 500


def test_offset_and_limit_paginate(db):
    for i in range(30):
        persistence.upsert_signal_cell(f"cell-{i}", sector="TECH", db_path=db)
    page1 = siq.query_signal_cells(db, sector="TECH", limit=10, offset=0)
    page2 = siq.query_signal_cells(db, sector="TECH", limit=10, offset=10)
    assert page1["row_count"] == 10
    assert page2["row_count"] == 10
    keys1 = {r["cell_key"] for r in page1["rows"]}
    keys2 = {r["cell_key"] for r in page2["rows"]}
    assert keys1.isdisjoint(keys2)


# ---------------------------------------------------------------------------
# Indexes exist
# ---------------------------------------------------------------------------


def test_query_indexes_exist(db):
    conn = sqlite3.connect(str(db))
    try:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()}
    finally:
        conn.close()
    for ix in ("idx_dfp_ticker", "idx_sci_sector", "idx_sci_source_type",
               "idx_mb_ticker", "idx_mt_event_id", "idx_rr_trade_id"):
        assert ix in names, ix


# ---------------------------------------------------------------------------
# Query plan uses index
# ---------------------------------------------------------------------------


def test_query_plan_audit_meets_coverage(db):
    report = audit.audit_query_plans(db)
    assert report["db_available"] is True
    assert report["indexed_coverage"] >= audit.INDEXED_COVERAGE_TARGET
    assert report["all_queries_bounded"] is True
    assert report["full_table_scans"] == []
    assert report["state"] == "PASS"


def test_query_plan_audit_missing_db_degrades(tmp_path):
    report = audit.audit_query_plans(tmp_path / "nope.db")
    assert report["db_available"] is False
    assert report["state"] == "INSUFFICIENT_DATA"


# ---------------------------------------------------------------------------
# Performance probe (synthetic temp DB only)
# ---------------------------------------------------------------------------


def test_probe_uses_temp_db_and_is_bounded():
    report = probe.probe(rows=250)
    assert report["used_temp_db"] is True
    assert report["all_bounded"] is True
    assert report["max_row_count"] <= siq.MAX_LIMIT
    assert report["state"] == "PASS"


def test_probe_does_not_touch_runtime_db(monkeypatch, tmp_path):
    # Point persistence.DB_PATH at a sentinel; the probe must not create it.
    sentinel = tmp_path / "should_not_be_created.db"
    monkeypatch.setattr(persistence, "DB_PATH", sentinel, raising=False)
    probe.probe(rows=200)
    assert not sentinel.exists()
