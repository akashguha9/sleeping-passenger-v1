"""Tests — daily discovery refresh orchestrator (P3).

Deterministic, offline, no broker. Proves the orchestrator refreshes price
marks via an injected provider, reports C_price / H_price_coverage / the
advisory new-risk gate, degrades honestly with no provider, and introduces no
execution surface.
"""
from __future__ import annotations

import ast
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.persistence import init_schema
from scripts.run_daily_discovery_refresh import _mock_price_provider, run_refresh

NOW = datetime(2026, 5, 29, 12, 0, 0, tzinfo=timezone.utc)
REPO_ROOT = Path(__file__).resolve().parents[1]

_FORBIDDEN = [
    "place_order", "submit_order", "execute_trade", "broker_execute",
    "broker_api(", "send_transaction", "auto_execute", "unlock_execution",
]


def _fresh_db():
    db = Path(tempfile.mkdtemp()) / "refresh.db"
    init_schema(db)
    return db


def test_refresh_with_mock_provider_populates_and_reports():
    db = _fresh_db()
    rep = run_refresh(
        db_path=db,
        price_provider=_mock_price_provider(NOW),
        holdings=["AAPL", "SAP.DE"],
        candidate_tickers=["RELIANCE.NS", "SHEL.L", "7203.T"],
        now_utc=NOW,
        market_state="open",
    )
    assert rep["price_status"] == "LIVE_PRICE_VERIFIED"
    assert rep["price_refresh"]["written"] == 5
    assert rep["C_price"] > 0.0
    assert rep["H_price_coverage"] == 1.0
    assert rep["valid_price_count"] == 5
    assert rep["synthesis_ran"] is False


def test_refresh_without_provider_is_honest():
    db = _fresh_db()
    rep = run_refresh(db_path=db, price_provider=None, holdings=["AAPL"], now_utc=NOW)
    assert rep["price_provider_configured"] is False
    assert rep["price_status"] == "PRICE_PROVIDER_NOT_CONFIGURED"
    assert rep["price_refresh"]["written"] == 0
    assert rep["C_price"] == 0.0


def test_refresh_report_carries_advisory_invariants():
    db = _fresh_db()
    rep = run_refresh(db_path=db, price_provider=_mock_price_provider(NOW),
                      candidate_tickers=["AAPL"], now_utc=NOW)
    assert rep["execution_gate"] == "LOCKED"
    assert rep["broker_api_called"] is False
    assert rep["ai_execution_count"] == 0
    assert rep["can_execute"] is False
    assert rep["safety"]["advisory_status"] == "ADVISORY_ONLY"


def test_refresh_modules_have_no_execution_tokens():
    for name in ("refresh_live_price_marks.py", "run_daily_discovery_refresh.py"):
        src = (REPO_ROOT / "scripts" / name).read_text(encoding="utf-8")
        ast.parse(src)  # compiles
        for tok in _FORBIDDEN:
            assert tok not in src, f"forbidden token {tok!r} in {name}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
