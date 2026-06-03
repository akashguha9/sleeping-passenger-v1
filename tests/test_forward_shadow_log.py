"""T7 — forward shadow log: record picks + would-block + outcomes; refuse
to declare rules 'validated' until >= 100 trades across >= 2 regimes.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import forward_shadow_log as fsl


@pytest.fixture()
def tmp_log(tmp_path: Path) -> Path:
    return tmp_path / "shadow.jsonl"


# ---------------------------------------------------------------------------
# Basic round-trip
# ---------------------------------------------------------------------------


def test_pick_decision_written_and_read_back(tmp_log):
    fsl.log_pick_decision(
        as_of="2026-06-03",
        ticker="AAPL",
        gate_pass=True,
        entry_quality_score=0.78,
        components={"trend_50": {"pass": True}},
        would_have_bought=True,
        regime_tag="trending_up",
        log_path=tmp_log,
    )
    events = fsl.read_events(tmp_log)
    assert len(events) == 1
    e = events[0]
    assert e["event_type"] == "pick_decision"
    assert e["ticker"] == "AAPL"
    assert e["gate_pass"] is True
    assert e["advisory_status"] == "ADVISORY_ONLY"
    assert e["broker_api_called"] is False


def test_trade_resolved_includes_gross_net_and_cost(tmp_log):
    fsl.log_trade_resolved(
        ticker="AAPL", buy_date="2026-06-03", result="TP1+TP2",
        pl_eur_gross=2.45, pl_eur_net=0.71, execution_cost_eur=1.74,
        regime_tag="trending_up", log_path=tmp_log,
    )
    e = fsl.read_events(tmp_log)[0]
    assert e["pl_eur_gross"] == 2.45
    assert e["pl_eur_net"] == 0.71
    assert e["execution_cost_eur"] == 1.74


# ---------------------------------------------------------------------------
# Readiness bar: 100 trades AND 2 regimes
# ---------------------------------------------------------------------------


def test_empty_log_is_not_ready(tmp_log):
    rep = fsl.readiness(tmp_log)
    assert rep.ready is False
    assert rep.resolved_trades == 0
    assert "Not ready" in rep.reason


def test_below_threshold_not_ready(tmp_log):
    # 50 trades in two regimes -- still under MIN_FORWARD_TRADES=100.
    for i in range(50):
        fsl.log_trade_resolved(
            ticker=f"T{i}", buy_date="2026-06-03",
            result="TP1", pl_eur_gross=0.5, pl_eur_net=0.2,
            execution_cost_eur=0.3,
            regime_tag="trending_up" if i % 2 == 0 else "chop",
            log_path=tmp_log,
        )
    rep = fsl.readiness(tmp_log)
    assert rep.ready is False
    assert rep.resolved_trades == 50
    assert len(rep.distinct_regimes) == 2


def test_meets_bar_only_when_both_trades_and_regimes_present(tmp_log):
    # 100 trades but ALL in one regime -- still not ready (regime gate).
    for i in range(100):
        fsl.log_trade_resolved(
            ticker=f"T{i}", buy_date="2026-06-03",
            result="TP1", pl_eur_gross=0.5, pl_eur_net=0.2,
            execution_cost_eur=0.3,
            regime_tag="trending_up",
            log_path=tmp_log,
        )
    rep = fsl.readiness(tmp_log)
    assert rep.ready is False, (
        "100 trades in one regime must not be enough; cross-regime evidence "
        "is what the brief requires."
    )
    # Adding 1 trade in a second regime still fails (bar is 100 in EACH? No
    # -- the bar is 100 total AND 2 regimes; we only had the regime gap)
    fsl.log_trade_resolved(
        ticker="T100", buy_date="2026-06-03",
        result="TP1", pl_eur_gross=0.5, pl_eur_net=0.2,
        execution_cost_eur=0.3,
        regime_tag="chop",
        log_path=tmp_log,
    )
    rep = fsl.readiness(tmp_log)
    assert rep.ready is True
    assert rep.resolved_trades == 101
    assert set(rep.distinct_regimes) == {"trending_up", "chop"}


def test_readiness_constants_match_brief():
    """The brief's bar: >= 100 forward trades across >= 1 non-trending
    regime. We pin at least 2 regimes (so at least one is not the
    dominant 'trending_up' regime)."""
    assert fsl.MIN_FORWARD_TRADES >= 100
    assert fsl.MIN_REGIMES >= 2


# ---------------------------------------------------------------------------
# Gate-blocked-but-resolved-wins: surface, never auto-act
# ---------------------------------------------------------------------------


def test_gate_blocked_but_won_is_surfaced(tmp_log):
    fsl.log_pick_decision(
        as_of="2026-05-01", ticker="FOO", gate_pass=False,
        entry_quality_score=0.4, components={"trend_50": {"pass": False}},
        would_have_bought=False, regime_tag="chop", log_path=tmp_log,
    )
    fsl.log_trade_resolved(
        ticker="FOO", buy_date="2026-05-01", result="TP1+TP2",
        pl_eur_gross=2.5, pl_eur_net=0.9, execution_cost_eur=1.6,
        regime_tag="chop", log_path=tmp_log,
    )
    blocked_wins = fsl.gate_blocked_but_resolved_wins(log_path=tmp_log)
    assert len(blocked_wins) == 1
    assert blocked_wins[0]["ticker"] == "FOO"
    assert blocked_wins[0]["pl_eur_net"] == 0.9
