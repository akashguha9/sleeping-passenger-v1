"""
Sprint H — Stale OHLCV repair: regression tests for the chart-structure
data freshness gate.

These tests prove (per the bug report where ICICIBANK.NS rendered a 2004
latest candle as if it were current data):

  A1  Latest N candles are selected, not oldest N.
  A2  Ancient (year << current) data is BLOCKED, not silently rendered.
  A3  Pure seed/demo data does not silently masquerade as real OHLCV.
  A4  Behaviour is symbol-agnostic across ICICIBANK.NS, RELIANCE.NS,
      AAPL, SPY, BTC-USD.
  A5  Out-of-order rows are sorted into chronological ascending order
      before the engine sees them, and latest_candle == max(timestamp).
  A6  Advisory-only safety invariants survive the freshness gate.

The tests run against a fresh tmp SQLite DB and never touch the
production runtime/mvp_local.db file.  No network calls.
"""
from __future__ import annotations

import datetime as _dt
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ohlcv_payload(symbol: str, day: date) -> dict:
    iso = f"{day.isoformat()}T16:00:00Z"
    return {
        "symbol": symbol,
        "timestamp": iso,
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "volume": 1_000_000,
        "advisory_status": "ADVISORY_ONLY",
        "execution_gate": "LOCKED",
        "human_review_required": True,
        "ai_execution_count": 0,
        "broker_api_called": False,
        "broker_order_id": "NONE",
    }


def _seed_real_history(
    p, *, symbol: str, db, start: date, days: int, fetched_at: str | None = None
) -> None:
    """Insert ``days`` real-backfill rows for ``symbol`` starting at ``start``.

    Mirrors backfill_global_ohlcv.py: every row gets the SAME ``fetched_at``
    (default now) so the bug-fix relies on payload-timestamp ordering, not
    fetched_at ordering.
    """
    if fetched_at is None:
        fetched_at = _dt.datetime.now(_dt.timezone.utc).isoformat()
    sym_clean = symbol.replace(".", "_").replace("-", "_").lower()
    for i in range(days):
        day = start + timedelta(days=i)
        p.insert_signal_event(
            event_id=f"ohlcv_{sym_clean}_1d_{day.isoformat()}",
            source_name="market_data",
            raw_payload=_ohlcv_payload(symbol, day),
            fetched_at=fetched_at,
            db_path=db,
        )


def _seed_demo_history(p, *, symbol: str, db, start: date, days: int) -> None:
    sym_clean = symbol.replace(".", "_").replace("-", "_").lower()
    for i in range(days):
        day = start + timedelta(days=i)
        # Seed script writes fetched_at = candle.timestamp.
        ts = f"{day.isoformat()}T16:00:00Z"
        p.insert_signal_event(
            event_id=f"seed_ohlcv_{sym_clean}_{day.isoformat()}",
            source_name="market_data",
            raw_payload=_ohlcv_payload(symbol, day),
            fetched_at=ts,
            db_path=db,
        )


# ---------------------------------------------------------------------------
# Module-level safety contract (sanity)
# ---------------------------------------------------------------------------


def test_freshness_module_constants_present():
    from scripts import market_data_freshness as m
    for name in ("FRESH", "DELAYED", "STALE", "ANCIENT", "MISSING",
                 "MOCK_OR_DEMO_BLOCKED", "PASS", "WARN", "BLOCK",
                 "CANONICAL_SQLITE", "READ_ONLY_PROVIDER", "JSONL_AUDIT_ONLY",
                 "MOCK", "DEMO", "SEED", "UNKNOWN"):
        assert hasattr(m, name), f"market_data_freshness missing constant {name!r}"


def test_freshness_classify_source_kind_buckets():
    from scripts import market_data_freshness as m
    assert m.classify_source_kind("market_data") == m.CANONICAL_SQLITE
    assert m.classify_source_kind("yfinance") == m.READ_ONLY_PROVIDER
    assert m.classify_source_kind("seed") == m.SEED
    assert m.classify_source_kind("demo") == m.DEMO
    assert m.classify_source_kind("MOCK") == m.MOCK
    assert m.classify_source_kind("") == m.UNKNOWN
    assert m.classify_source_kind(None) == m.UNKNOWN


def test_freshness_evaluate_no_candles_blocks():
    from scripts import market_data_freshness as m
    out = m.evaluate(candles=[], source_kind=m.CANONICAL_SQLITE)
    assert out["data_freshness_status"] == m.MISSING
    assert out["freshness_gate"] == m.BLOCK
    assert out["latest_candle_utc"] is None


def test_freshness_evaluate_ancient_blocks():
    from scripts import market_data_freshness as m
    cs = [{"timestamp": "2004-10-20T16:00:00Z"}]
    out = m.evaluate(candles=cs, source_kind=m.CANONICAL_SQLITE)
    assert out["data_freshness_status"] == m.ANCIENT
    assert out["freshness_gate"] == m.BLOCK


def test_freshness_evaluate_seed_blocks_by_default():
    from scripts import market_data_freshness as m
    today = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
    cs = [{"timestamp": f"{today}T16:00:00Z"}]
    out = m.evaluate(candles=cs, source_kind=m.SEED)
    assert out["data_freshness_status"] == m.MOCK_OR_DEMO_BLOCKED
    assert out["freshness_gate"] == m.BLOCK


def test_freshness_evaluate_fresh_passes():
    from scripts import market_data_freshness as m
    today = _dt.datetime.now(_dt.timezone.utc).isoformat()
    cs = [{"timestamp": today}]
    out = m.evaluate(candles=cs, source_kind=m.CANONICAL_SQLITE)
    assert out["data_freshness_status"] == m.FRESH
    assert out["freshness_gate"] == m.PASS


# ---------------------------------------------------------------------------
# A1 — Latest N selected, not oldest N
# ---------------------------------------------------------------------------


def test_chart_structure_returns_latest_candles_not_oldest(tmp_path):
    """Fix the exact bug from the screenshot: 200 historical rows for
    ICICIBANK.NS spanning 2004→today must not produce a chart whose
    first candle is from 2004 when the operator asked for limit=100.
    """
    import scripts.persistence as p
    from scripts.chart_structure_api_context import _get_chart_structure
    db = tmp_path / "icicibank.db"

    today = _dt.datetime.now(_dt.timezone.utc).date()
    # 200 historical days ending today (so the latest candle is "fresh").
    _seed_real_history(p, symbol="ICICIBANK.NS", db=db,
                       start=today - timedelta(days=199), days=200)
    # Plus a separate batch of *very old* 2004 history that, under the old
    # bug, would have surfaced because all rows shared fetched_at.
    _seed_real_history(p, symbol="ICICIBANK.NS", db=db,
                       start=date(2004, 6, 2), days=120)

    resp = _get_chart_structure(symbol="ICICIBANK.NS", limit=100, db_path=db)

    assert resp["candle_count"] == 100, (
        f"expected 100 latest candles, got {resp['candle_count']}"
    )
    summary = resp["report"]["summary"]
    latest_ts = summary["latest_timestamp"]
    first_ts = summary["first_timestamp"]
    assert latest_ts.startswith(str(today.year)), (
        f"latest candle must be from this year, got {latest_ts}"
    )
    assert not first_ts.startswith("2004"), (
        f"first candle must NOT be from 2004 — got {first_ts}"
    )
    # Defence-in-depth: latest_candle_utc on the response also reflects
    # the freshest payload timestamp.
    assert resp["latest_candle_utc"].startswith(str(today.year))


# ---------------------------------------------------------------------------
# A2 — Ancient data BLOCKED, advisory verdict NOT rendered as normal
# ---------------------------------------------------------------------------


def test_ancient_data_is_blocked_not_rendered_as_normal(tmp_path):
    import scripts.persistence as p
    from scripts.chart_structure_api_context import _get_chart_structure
    db = tmp_path / "ancient.db"

    # ONLY 2004 candles — emulates the screenshotted broken state.
    _seed_real_history(p, symbol="ICICIBANK.NS", db=db,
                       start=date(2004, 6, 2), days=120)

    resp = _get_chart_structure(symbol="ICICIBANK.NS", limit=100, db_path=db)
    assert resp["freshness_gate"] == "BLOCK"
    assert resp["data_freshness_status"] == "ANCIENT"
    assert resp["report"] is None, (
        "ancient data must not produce a normal chart structure report"
    )
    assert resp["chart_state"] == "STALE_DATA_BLOCKED"
    assert resp["suggested_next_step"] in {
        "DATA_REFRESH_REQUIRED", "HUMAN_REVIEW_DATA_STALE",
    }
    # Safety stamps survive the block.
    assert resp["advisory_status"] == "ADVISORY_ONLY"
    assert resp["execution_gate"] == "LOCKED"
    assert resp["human_review_required"] is True
    assert resp["broker_api_called"] is False
    assert resp["ai_execution_count"] == 0
    assert resp["broker_order_id"] == "NONE"


# ---------------------------------------------------------------------------
# A3 — No silent demo/seed fallback
# ---------------------------------------------------------------------------


def test_pure_seed_data_does_not_silently_render_normal_verdict(tmp_path):
    import scripts.persistence as p
    from scripts.chart_structure_api_context import _get_chart_structure
    db = tmp_path / "seed_only.db"

    today = _dt.datetime.now(_dt.timezone.utc).date()
    _seed_demo_history(p, symbol="AAPL", db=db,
                       start=today - timedelta(days=119), days=120)

    resp = _get_chart_structure(symbol="AAPL", limit=100, db_path=db)
    assert resp["freshness_gate"] == "BLOCK"
    assert resp["data_freshness_status"] == "MOCK_OR_DEMO_BLOCKED"
    assert resp["report"] is None
    assert resp["source_kind"] == "SEED"


# ---------------------------------------------------------------------------
# A4 — Symbol-agnostic across markets
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "symbol",
    ["ICICIBANK.NS", "RELIANCE.NS", "AAPL", "SPY", "BTC-USD"],
)
def test_freshness_block_is_symbol_agnostic(symbol, tmp_path):
    import scripts.persistence as p
    from scripts.chart_structure_api_context import _get_chart_structure
    db = tmp_path / f"sym_{symbol.replace('.', '_').replace('-', '_').lower()}.db"

    _seed_real_history(p, symbol=symbol, db=db,
                       start=date(2004, 1, 1), days=80)
    resp = _get_chart_structure(symbol=symbol, limit=100, db_path=db)
    assert resp["freshness_gate"] == "BLOCK", (
        f"{symbol}: ancient data must block but got gate={resp.get('freshness_gate')}"
    )
    assert resp["report"] is None


# ---------------------------------------------------------------------------
# A5 — Out-of-order rows still produce chronological ascending output
# ---------------------------------------------------------------------------


def test_out_of_order_rows_are_sorted_chronologically(tmp_path):
    import random
    import scripts.persistence as p
    from scripts.chart_structure_api_context import _get_chart_structure
    db = tmp_path / "shuffled.db"

    today = _dt.datetime.now(_dt.timezone.utc).date()
    days = [today - timedelta(days=i) for i in range(50)]
    random.Random(7).shuffle(days)
    sym_clean = "spy"
    fetched_at = _dt.datetime.now(_dt.timezone.utc).isoformat()
    for d in days:
        p.insert_signal_event(
            event_id=f"ohlcv_{sym_clean}_1d_{d.isoformat()}",
            source_name="market_data",
            raw_payload=_ohlcv_payload("SPY", d),
            fetched_at=fetched_at,
            db_path=db,
        )
    resp = _get_chart_structure(symbol="SPY", limit=50, db_path=db)
    summary = resp["report"]["summary"]
    assert summary["latest_timestamp"].startswith(today.isoformat()), (
        f"latest timestamp must be today, got {summary['latest_timestamp']}"
    )
    # First timestamp must be 49 days back.
    assert summary["first_timestamp"].startswith(
        (today - timedelta(days=49)).isoformat()
    )
    # Engine sees chronologically ascending rows.
    assert summary["candle_count"] == 50


# ---------------------------------------------------------------------------
# A6 — Advisory-only invariants preserved on FRESH path
# ---------------------------------------------------------------------------


def test_advisory_invariants_preserved_on_fresh_response(tmp_path):
    import scripts.persistence as p
    from scripts.chart_structure_api_context import _get_chart_structure
    db = tmp_path / "fresh.db"

    today = _dt.datetime.now(_dt.timezone.utc).date()
    _seed_real_history(p, symbol="AAPL", db=db,
                       start=today - timedelta(days=99), days=100)
    resp = _get_chart_structure(symbol="AAPL", limit=100, db_path=db)

    assert resp["freshness_gate"] == "PASS"
    assert resp["data_freshness_status"] == "FRESH"
    assert resp["advisory_status"] == "ADVISORY_ONLY"
    assert resp["execution_gate"] == "LOCKED"
    assert resp["human_review_required"] is True
    assert resp["broker_api_called"] is False
    assert resp["ai_execution_count"] == 0
    assert resp["broker_order_id"] == "NONE"
    assert resp["report"]["broker_api_called"] is False
    assert resp["report"]["ai_execution_count"] == 0


# ---------------------------------------------------------------------------
# Source-kind classification on combined seed+real datasets
# ---------------------------------------------------------------------------


def test_real_plus_seed_classifies_as_canonical_sqlite(tmp_path):
    """When both real backfill rows AND seed rows exist for a symbol,
    the merged dataset should be treated as CANONICAL_SQLITE so the
    operator is not punished for having demo seeds in the same DB."""
    import scripts.persistence as p
    from scripts.chart_structure_api_context import _get_chart_structure
    db = tmp_path / "mixed.db"

    today = _dt.datetime.now(_dt.timezone.utc).date()
    _seed_real_history(p, symbol="AAPL", db=db,
                       start=today - timedelta(days=99), days=100)
    _seed_demo_history(p, symbol="AAPL", db=db,
                       start=today - timedelta(days=119), days=20)
    resp = _get_chart_structure(symbol="AAPL", limit=100, db_path=db)
    assert resp["source_kind"] == "CANONICAL_SQLITE"
    assert resp["freshness_gate"] == "PASS"
