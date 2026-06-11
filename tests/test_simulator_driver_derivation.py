"""Driver derivation tests: violations from actual journal rows, with decay."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.simulator.driver_derivation import (
    derive_driver_state,
    derive_violations,
)

AS_OF = datetime(2026, 6, 1, tzinfo=timezone.utc)


def _trade(**overrides) -> dict:
    base = {
        "trade_id": "t1",
        "ticker": "GRIDCO",
        "side": "BUY",
        "quantity": 10,
        "price": 50.0,
        "executed_at": "2026-05-30T12:00:00+00:00",
        "thesis": "Backlog inflecting on AI grid demand",
        "invalidation_level": "Exit below 10% backlog growth",
        "entry_reason": "Filing-confirmed backlog acceleration",
        "confidence_before": 60.0,
        "leverage": 1.0,
        "leverage_ceiling": 1.0,
        "leverage_breach": 0,
        "gallardo_block_at_decision": 0,
        "reconciliation_status": "",
    }
    base.update(overrides)
    return base


def test_clean_trade_log_yields_no_violations() -> None:
    violations = derive_violations([_trade()], [], as_of=AS_OF)
    assert violations == []


def test_missing_thesis_is_no_helmet() -> None:
    violations = derive_violations([_trade(thesis="yolo")], [], as_of=AS_OF)
    assert [v["type"] for v in violations] == ["no_thesis_no_helmet"]


def test_missing_invalidation_is_detected() -> None:
    violations = derive_violations(
        [_trade(invalidation_level="")], [], as_of=AS_OF
    )
    assert [v["type"] for v in violations] == ["entered_without_invalidation"]


def test_ignored_block_flag_is_detected() -> None:
    violations = derive_violations(
        [_trade(gallardo_block_at_decision=1)], [], as_of=AS_OF
    )
    assert [v["type"] for v in violations] == ["ignored_black_flag"]


def test_leverage_breach_is_oversizing() -> None:
    violations = derive_violations(
        [_trade(leverage=3.0, leverage_ceiling=1.0, leverage_breach=1)],
        [],
        as_of=AS_OF,
    )
    assert [v["type"] for v in violations] == ["oversizing_under_crash_risk"]


def test_high_confidence_without_reason_is_tailgating() -> None:
    violations = derive_violations(
        [_trade(confidence_before=90.0, entry_reason="")], [], as_of=AS_OF
    )
    assert [v["type"] for v in violations] == ["tailgating_hype"]


def test_revenge_reentry_within_window_detected() -> None:
    loss_trade = _trade(trade_id="t_loss", executed_at="2026-05-20T10:00:00+00:00")
    reentry = _trade(trade_id="t_revenge", executed_at="2026-05-21T08:00:00+00:00")
    recon = {
        "trade_id": "t_loss",
        "reconciled_at": "2026-05-21T00:00:00+00:00",
        "outcome_status": "LOSS",
    }
    violations = derive_violations([loss_trade, reentry], [recon], as_of=AS_OF)
    types = [v["type"] for v in violations]
    assert "revenge_trading" in types
    revenge = next(v for v in violations if v["type"] == "revenge_trading")
    assert revenge["trade_id"] == "t_revenge"


def test_reentry_outside_window_is_not_revenge() -> None:
    reentry = _trade(trade_id="t_later", executed_at="2026-05-28T00:00:00+00:00")
    recon = {
        "trade_id": "t_other",
        "reconciled_at": "2026-05-21T00:00:00+00:00",
        "outcome_status": "LOSS",
    }
    other = _trade(trade_id="t_other", executed_at="2026-05-20T00:00:00+00:00")
    violations = derive_violations([other, reentry], [recon], as_of=AS_OF)
    assert "revenge_trading" not in [v["type"] for v in violations]


def test_cancelled_trades_are_ignored() -> None:
    violations = derive_violations(
        [_trade(thesis="", reconciliation_status="CANCELLED_DUPLICATE")],
        [],
        as_of=AS_OF,
    )
    assert violations == []


def test_derived_points_decay_with_age() -> None:
    fresh = derive_driver_state(
        [_trade(thesis="", executed_at="2026-05-31T12:00:00+00:00")],
        [],
        as_of=AS_OF,
    )
    old = derive_driver_state(
        [_trade(thesis="", executed_at="2026-01-01T12:00:00+00:00")],
        [],
        as_of=AS_OF,
    )
    assert fresh.derived_points > old.derived_points
    assert old.derived_points < 1.0  # five months of decay
    assert fresh.decay_applied and old.decay_applied


def test_derived_state_contract_and_demotion() -> None:
    # Stack violations until suspension: license is demoted one rank.
    bad_trades = [
        _trade(
            trade_id=f"t{i}",
            thesis="",
            invalidation_level="",
            gallardo_block_at_decision=1,
            leverage_breach=1,
            executed_at="2026-05-31T12:00:00+00:00",
        )
        for i in range(2)
    ]
    state = derive_driver_state(
        bad_trades, [], driver_id="local_user", license_level="pro_am", as_of=AS_OF
    )
    payload = state.to_dict()
    for key in (
        "driver_id", "derived_points", "violations", "decay_applied",
        "license_level_before", "license_level_after", "permission_multiplier",
    ):
        assert key in payload
    assert payload["driver_id"] == "local_user"
    assert state.derived_points > 80  # 2 × (15+12+15+12) decayed ~1 day
    assert state.status == "black_flag"
    assert state.permission_multiplier == 0.0
    assert state.license_level_before == "pro_am"
    assert state.license_level_after == "club_racer"
    assert state.trades_examined == 2


def test_violation_count_covers_at_least_five_types() -> None:
    trades = [
        _trade(trade_id="a", thesis=""),
        _trade(trade_id="b", invalidation_level=""),
        _trade(trade_id="c", gallardo_block_at_decision=1),
        _trade(trade_id="d", leverage_breach=1),
        _trade(trade_id="e", confidence_before=95.0, entry_reason=""),
    ]
    violations = derive_violations(trades, [], as_of=AS_OF)
    assert {
        "no_thesis_no_helmet",
        "entered_without_invalidation",
        "ignored_black_flag",
        "oversizing_under_crash_risk",
        "tailgating_hype",
    } <= {v["type"] for v in violations}
