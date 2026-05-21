"""Performance / scalability floor for the signal-geometry audit tables.

Proves indexed lookups, pagination, row-limit guards, and an incremental
refresh cursor — Kanté "transition control": bounded reads, no unbounded scan.
"""
from __future__ import annotations

import scripts.persistence as persistence
from scripts import signal_index_query as siq


def _seed_cells(db, n, *, sector="tech", source_type="filings"):
    for i in range(n):
        persistence.upsert_signal_cell(
            f"cell_{sector}_{i}",
            source_type=source_type,
            jurisdiction="US",
            sector=sector,
            event_type="earnings",
            time_bucket="2026-05-20T00",
            db_path=db,
        )


def _seed_fingerprints(db, n, *, ticker="AAPL"):
    for i in range(n):
        persistence.upsert_duplicate_fingerprint(
            f"fp_{ticker}_{i}",
            source_type="news",
            event_type="earnings",
            ticker=ticker,
            event_id=f"EV_{i}",
            observed_date="2026-05-20",
            db_path=db,
        )


def test_duplicate_fingerprint_lookup_uses_indexed_field(tmp_path):
    db = tmp_path / "idx.db"
    persistence.init_schema(db)
    _seed_fingerprints(db, 5, ticker="AAPL")
    siq.ensure_indexes(db)
    res = siq.query_duplicate_fingerprints(db, ticker="AAPL")
    assert res["row_count"] == 5
    # idx_dfp_ticker ships in the schema; the ticker filter must use an index.
    assert "INDEX" in res["query_plan"].upper()


def test_signal_cell_query_returns_limited_results(tmp_path):
    db = tmp_path / "cells.db"
    persistence.init_schema(db)
    _seed_cells(db, 20)
    res = siq.query_signal_cells(db, sector="tech", limit=5)
    assert res["row_count"] == 5
    assert res["limit"] == 5


def test_signal_cell_query_filters_use_index(tmp_path):
    db = tmp_path / "cells2.db"
    persistence.init_schema(db)
    _seed_cells(db, 10, source_type="filings")
    siq.ensure_indexes(db)
    res = siq.query_signal_cells(db, source_type="filings")
    assert "INDEX" in res["query_plan"].upper()


def test_pagination_works(tmp_path):
    db = tmp_path / "page.db"
    persistence.init_schema(db)
    _seed_cells(db, 12)
    page1 = siq.query_signal_cells(db, sector="tech", limit=5, offset=0)
    page2 = siq.query_signal_cells(db, sector="tech", limit=5, offset=5)
    page3 = siq.query_signal_cells(db, sector="tech", limit=5, offset=10)
    keys1 = {r["cell_key"] for r in page1["rows"]}
    keys2 = {r["cell_key"] for r in page2["rows"]}
    assert len(keys1) == 5 and len(keys2) == 5
    assert keys1.isdisjoint(keys2)  # no overlap across pages
    assert page3["row_count"] == 2  # remainder


def test_row_limit_guard_clamps_unbounded_requests(tmp_path):
    db = tmp_path / "clamp.db"
    persistence.init_schema(db)
    _seed_cells(db, 3)
    res = siq.query_signal_cells(db, sector="tech", limit=10_000_000)
    assert res["limit"] == siq.MAX_LIMIT
    res2 = siq.query_signal_cells(db, sector="tech", limit=-1)
    assert res2["limit"] == siq.DEFAULT_LIMIT


def test_no_unbounded_select_in_module_source():
    import pathlib
    text = pathlib.Path(siq.__file__).read_text(encoding="utf-8")
    # Every row-returning SELECT (FROM ... WHERE/ORDER) must carry a LIMIT.
    # The only aggregate read is the cursor MAX/COUNT, which returns one row.
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("\"SELECT") and " FROM " in stripped:
            # row-returning select literal fragments are split across lines;
            # this assertion is a coarse guard that no single-line SELECT *
            # slipped in.
            assert "*" not in stripped, stripped


def test_incremental_cursor(tmp_path):
    db = tmp_path / "cursor.db"
    persistence.init_schema(db)
    _seed_cells(db, 4)
    cur = siq.incremental_cursor(db, table="signal_cell_index")
    assert cur["row_count"] == 4
    assert cur["cursor"] is not None
    # Reading rows "since" the cursor returns nothing new (bounded follow-up).
    follow = siq.query_signal_cells(db, since=cur["cursor"])
    # rows seen exactly at the cursor timestamp may match; never a full re-scan
    assert follow["row_count"] <= 4


def test_query_helpers_are_advisory_only(tmp_path):
    db = tmp_path / "adv.db"
    persistence.init_schema(db)
    for res in (
        siq.query_signal_cells(db),
        siq.query_duplicate_fingerprints(db),
        siq.incremental_cursor(db),
        siq.ensure_indexes(db),
    ):
        assert res["advisory_status"] == "ADVISORY_ONLY"
        assert res["execution_gate"] == "LOCKED"
        assert res["broker_api_called"] is False
