"""Tests for the post-hoc benchmark comparison report (Close-the-Loop sprint).

Covers the forensic-audit requirements:
* benchmark comparison exists next to realized returns (SP-050),
* outcome labels are never re-labeled by analytics,
* the report can never unlock a predictive claim,
* unflattering results are reported as NO DEMONSTRATED EDGE, not hidden.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts.benchmark_outcome_report import (
    build_benchmark_comparison,
    write_report,
)

SNAP_DDL = """
CREATE TABLE decision_probability_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    ticker TEXT,
    model_probability REAL,
    outcome_label INTEGER,
    is_real_outcome INTEGER,
    outcome_kind TEXT,
    entry_price REAL,
    entry_price_timestamp_utc TEXT,
    horizon_close_utc TEXT
)
"""

EVENTS_DDL = """
CREATE TABLE signal_events (
    id INTEGER PRIMARY KEY,
    event_id TEXT,
    source_name TEXT,
    raw_payload TEXT,
    fetched_at TEXT
)
"""


def _bar(symbol: str, day: str, close: float) -> str:
    return json.dumps(
        {"symbol": symbol, "timestamp": f"{day}T16:00:00Z", "close": close}
    )


@pytest.fixture()
def seeded_db(tmp_path: Path) -> Path:
    db = tmp_path / "bench.db"
    conn = sqlite3.connect(db)
    conn.execute(SNAP_DDL)
    conn.execute(EVENTS_DDL)
    # Two matured snapshots: AAPL missed (label 0), SPY hit (label 1).
    conn.execute(
        "INSERT INTO decision_probability_snapshots VALUES (?,?,?,?,?,?,?,?,?)",
        ("S1", "AAPL", 0.60, 0, 1, "real_forward", 100.0,
         "2026-05-29T16:00:00Z", "2026-06-05T16:00:00Z"),
    )
    conn.execute(
        "INSERT INTO decision_probability_snapshots VALUES (?,?,?,?,?,?,?,?,?)",
        ("S2", "SPY", 0.55, 1, 1, "real_forward", 500.0,
         "2026-05-29T16:00:00Z", "2026-06-05T16:00:00Z"),
    )
    # An unmatured snapshot that must be ignored.
    conn.execute(
        "INSERT INTO decision_probability_snapshots VALUES (?,?,?,?,?,?,?,?,?)",
        ("S3", "MSFT", 0.55, None, None, None, 400.0,
         "2026-05-29T16:00:00Z", "2026-06-05T16:00:00Z"),
    )
    bars = [
        ("AAPL", "2026-05-29", 100.0),
        ("AAPL", "2026-06-05", 95.0),   # -5% realized
        ("SPY", "2026-05-29", 500.0),
        ("SPY", "2026-06-05", 510.0),   # +2% realized == benchmark
    ]
    for i, (sym, day, close) in enumerate(bars):
        conn.execute(
            "INSERT INTO signal_events VALUES (?,?,?,?,?)",
            (i + 1, f"e{i}", "market_data", _bar(sym, day, close),
             f"{day}T16:00:00Z"),
        )
    conn.commit()
    conn.close()
    return db


def test_alpha_math_and_benchmark_columns(seeded_db: Path) -> None:
    rep = build_benchmark_comparison(db_path=seeded_db, benchmark_symbol="SPY")
    assert rep["n_matured_real_forward"] == 2  # S3 (unmatured) excluded
    by_id = {r["snapshot_id"]: r for r in rep["per_row"]}
    aapl = by_id["S1"]
    assert aapl["realized_return"] == pytest.approx(-0.05)
    assert aapl["benchmark_return"] == pytest.approx(0.02)
    assert aapl["alpha"] == pytest.approx(-0.07)
    assert aapl["benchmark_status"] == "OK"
    spy = by_id["S2"]
    assert spy["alpha"] == pytest.approx(0.0)
    assert rep["mean_benchmark_return"] == pytest.approx(0.02)


def test_brier_baselines_and_honest_verdict(seeded_db: Path) -> None:
    rep = build_benchmark_comparison(db_path=seeded_db, benchmark_symbol="SPY")
    # labels [0,1], probs [0.60,0.55]
    assert rep["base_rate"] == pytest.approx(0.5)
    assert rep["brier_model"] == pytest.approx((0.6**2 + 0.45**2) / 2)
    assert rep["brier_always_half"] == pytest.approx(0.25)
    assert rep["brier_base_rate"] == pytest.approx(0.25)
    # model brier ~0.281 > 0.25: must say NO DEMONSTRATED EDGE, not hide it
    assert rep["beats_coin_baseline"] is False
    assert rep["beats_base_rate_baseline"] is False
    assert "NO DEMONSTRATED EDGE" in rep["honest_verdict"]


def test_analytics_never_unlocks_claims_or_mutates(seeded_db: Path) -> None:
    before = sqlite3.connect(seeded_db).execute(
        "SELECT snapshot_id, outcome_label, model_probability "
        "FROM decision_probability_snapshots ORDER BY snapshot_id"
    ).fetchall()
    rep = build_benchmark_comparison(db_path=seeded_db, benchmark_symbol="SPY")
    after = sqlite3.connect(seeded_db).execute(
        "SELECT snapshot_id, outcome_label, model_probability "
        "FROM decision_probability_snapshots ORDER BY snapshot_id"
    ).fetchall()
    assert before == after, "analytics must be read-only"
    assert rep["predictive_claim_allowed"] is False
    assert rep["report_kind"] == "POST_HOC_ANALYTICS"
    assert rep["advisory_status"] == "ADVISORY_ONLY"
    assert rep["execution_gate"] == "LOCKED"


def test_empty_corpus_reports_blocker_not_success(tmp_path: Path) -> None:
    db = tmp_path / "empty.db"
    conn = sqlite3.connect(db)
    conn.execute(SNAP_DDL)
    conn.execute(EVENTS_DDL)
    conn.commit()
    conn.close()
    rep = build_benchmark_comparison(db_path=db)
    assert rep["status"] == "NO_MATURED_OUTCOMES"
    assert rep["n_matured_real_forward"] == 0
    assert rep["predictive_claim_allowed"] is False


def test_missing_benchmark_bars_fail_visible(tmp_path: Path) -> None:
    db = tmp_path / "nobench.db"
    conn = sqlite3.connect(db)
    conn.execute(SNAP_DDL)
    conn.execute(EVENTS_DDL)
    conn.execute(
        "INSERT INTO decision_probability_snapshots VALUES (?,?,?,?,?,?,?,?,?)",
        ("S1", "AAPL", 0.60, 0, 1, "real_forward", 100.0,
         "2026-05-29T16:00:00Z", "2026-06-05T16:00:00Z"),
    )
    conn.execute(
        "INSERT INTO signal_events VALUES (1,'e1','market_data',?, '2026-06-05T16:00:00Z')",
        (_bar("AAPL", "2026-06-05", 95.0),),
    )
    conn.commit()
    conn.close()
    rep = build_benchmark_comparison(db_path=db, benchmark_symbol="SPY")
    assert rep["status"] == "BENCHMARK_UNAVAILABLE"
    assert rep["per_row"][0]["benchmark_status"] == "BENCHMARK_UNAVAILABLE"
    assert rep["per_row"][0]["alpha"] is None


def test_write_report_persists_json(seeded_db: Path, tmp_path: Path) -> None:
    rep = build_benchmark_comparison(db_path=seeded_db, benchmark_symbol="SPY")
    out = tmp_path / "release" / "benchmark_comparison.json"
    path = write_report(rep, out)
    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    assert loaded["report"] == "benchmark_outcome_comparison"
    assert loaded["predictive_claim_allowed"] is False
