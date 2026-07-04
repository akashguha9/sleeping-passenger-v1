"""Tests: Kalshi settlement reconciliation (Feed-the-Loop sprint)."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.kalshi_settlement_reconciliation import (
    brier,
    classify_settlement,
    logloss,
    reconcile_settlements,
)

NOW = datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc)


def _ledger(tmp_path: Path, rows: list[dict]) -> Path:
    f = tmp_path / "ledger.jsonl"
    f.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )
    return f


def _obs(oid: str, ticker: str, p: float) -> dict:
    return {
        "observation_id": oid, "market_ticker": ticker,
        "event_ticker": ticker.rsplit("-", 1)[0], "p": p,
        "fetch_timestamp": "2026-07-02T07:18:50+00:00",
    }


def test_classify_settlement_mapping() -> None:
    assert classify_settlement({"status": "settled", "result": "yes"}) == ("WON", 1)
    assert classify_settlement({"market": {"status": "finalized", "result": "no"}}) == ("LOST", 0)
    assert classify_settlement({"status": "settled", "result": ""}) == ("VOID", None)
    assert classify_settlement({"status": "open"}) == ("UNSETTLED", None)
    assert classify_settlement(None) == ("UNKNOWN", None)


def test_brier_and_logloss_math() -> None:
    assert brier(0.11, 0) == pytest.approx(0.0121)
    assert brier(0.11, 1) == pytest.approx(0.7921)
    assert logloss(0.11, 0) == pytest.approx(-math.log(0.89))
    # epsilon clip keeps p=1.0/y=0 finite instead of inf
    assert math.isfinite(logloss(1.0, 0))


def test_dry_run_never_touches_provider(tmp_path: Path) -> None:
    calls: list[str] = []

    def fetcher(t: str):  # pragma: no cover - must never run
        calls.append(t)
        return {"status": "settled", "result": "yes"}

    result = reconcile_settlements(
        ledger_path=_ledger(tmp_path, [_obs("o1", "KX-A", 0.5)]),
        settlements_path=tmp_path / "settle.jsonl",
        market_fetcher=fetcher, poll=False, write=False, now_utc=NOW,
    )
    assert calls == []
    assert result["provider_state"] == "DRY_RUN_NO_NETWORK"
    assert result["unsettled_rows"] == 1
    assert result["rows_persisted"] == 0


def test_settlement_appends_and_never_duplicates(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, [
        _obs("o1", "KX-A", 0.11), _obs("o2", "KX-A", 0.20),
        _obs("o3", "KX-B", 0.70),
    ])
    spath = tmp_path / "settle.jsonl"

    def fetcher(ticker: str):
        return {
            "KX-A": {"status": "settled", "result": "no"},
            "KX-B": {"status": "open"},
        }[ticker]

    first = reconcile_settlements(
        ledger_path=ledger, settlements_path=spath,
        market_fetcher=fetcher, poll=True, write=True, now_utc=NOW,
    )
    assert first["rows_persisted"] == 2  # both KX-A observations settle LOST
    assert first["statuses"]["LOST"] == 2
    assert first["statuses"]["UNSETTLED"] == 1
    rows = [json.loads(x) for x in spath.read_text().splitlines()]
    assert {r["observation_id"] for r in rows} == {"o1", "o2"}
    assert all(r["y"] == 0 for r in rows)
    assert rows[0]["brier"] == pytest.approx(brier(0.11, 0), abs=1e-6)
    # second pass: settled rows are skipped, no duplicates ever
    second = reconcile_settlements(
        ledger_path=ledger, settlements_path=spath,
        market_fetcher=fetcher, poll=True, write=True, now_utc=NOW,
    )
    assert second["rows_persisted"] == 0
    assert second["already_settled"] == 2
    assert len(spath.read_text().splitlines()) == 2


def test_unknown_settlement_never_fakes_outcome(tmp_path: Path) -> None:
    result = reconcile_settlements(
        ledger_path=_ledger(tmp_path, [_obs("o1", "KX-A", 0.5)]),
        settlements_path=tmp_path / "settle.jsonl",
        market_fetcher=lambda t: None, poll=True, write=True, now_utc=NOW,
    )
    assert result["rows_persisted"] == 0
    assert result["statuses"].get("UNKNOWN") == 1


def test_provider_crash_is_blocked_and_visible(tmp_path: Path) -> None:
    def fetcher(t: str):
        raise ConnectionError("provider down")

    result = reconcile_settlements(
        ledger_path=_ledger(tmp_path, [_obs("o1", "KX-A", 0.5)]),
        settlements_path=tmp_path / "settle.jsonl",
        market_fetcher=fetcher, poll=True, write=True, now_utc=NOW,
    )
    assert result["provider_state"] == "BLOCKED"
    assert result["provider_errors"] == 1
    assert result["rows_persisted"] == 0


def test_aggregates_over_won_lost_only(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, [
        _obs("o1", "KX-WIN", 0.8), _obs("o2", "KX-VOID", 0.5),
    ])
    spath = tmp_path / "settle.jsonl"

    def fetcher(ticker: str):
        return {
            "KX-WIN": {"status": "settled", "result": "yes"},
            "KX-VOID": {"status": "settled", "result": "void"},
        }[ticker]

    result = reconcile_settlements(
        ledger_path=ledger, settlements_path=spath,
        market_fetcher=fetcher, poll=True, write=True, now_utc=NOW,
    )
    assert result["n_scored_settlements"] == 1
    assert result["brier_mean"] == pytest.approx(brier(0.8, 1), abs=1e-6)
