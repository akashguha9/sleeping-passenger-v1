"""
Tests for the reconciliation → Moltbook learning bridge (Sprint J).

Covers the contract:
  - STOP_HIT reconciliation creates a Moltbook STOP_LOSS_HIT entry.
  - PARTIAL_TP_HIT creates a Moltbook success entry.
  - PARTIAL_TP_LOGGED creates / updates exactly one entry.
  - CLOSED reconciliation creates a Moltbook entry (win and loss).
  - Saving the same reconciliation twice does not duplicate rows.
  - Moltbook learns from both losses AND wins.
  - Advisory-only / human-only safety invariants remain unchanged.
  - Mistake-tag classification: bad-process tags downgrade GOOD→BAD.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import scripts.persistence as persistence
import scripts.moltbook_learning_bridge as bridge


@pytest.fixture
def db(tmp_path: Path) -> Path:
    target = tmp_path / "learning.db"
    persistence.init_schema(target)
    return target


def _record(db: Path, **overrides):
    """Helper that fills sensible defaults for a learning entry call."""
    kwargs = dict(
        trade_id="MT_DEFAULT",
        event_id="EV_DEFAULT",
        ticker="ZZZ",
        side="BUY",
        post_trade_outcome="CLOSED_WIN",
        actual_exit_price=110.0,
        exit_quantity=1.0,
        entry_price=100.0,
        entry_quantity=1.0,
        realized_pl=10.0,
        db_path=db,
        jsonl_path=db.parent / "audit.jsonl",
    )
    kwargs.update(overrides)
    return bridge.record_reconciliation_learning(**kwargs)


# ---------------------------------------------------------------------------
# STOP_HIT
# ---------------------------------------------------------------------------


def test_stop_hit_creates_moltbook_entry(db):
    result = _record(
        db,
        trade_id="MT_XOM",
        event_id="USER_XOM_LONG",
        ticker="XOM",
        post_trade_outcome="STOPPED_OUT",
        stop_loss_hit=True,
        actual_exit_price=98.5,
        exit_quantity=10.0,
        entry_price=105.0,
        entry_quantity=10.0,
        stop_loss_price=98.5,
        realized_pl=-65.0,
        exit_reason="Stop-loss breached on close.",
    )
    assert result["status"] == "created"
    assert result["event_type"] == "STOP_LOSS_HIT"
    assert result["learning_direction"] == "MISTAKE_OR_INVALIDATION"
    assert result["outcome_quality"] in {"GOOD_PROCESS_LOSS", "BAD_PROCESS_LOSS"}
    assert "created" in result["message"].lower()
    # Safety invariants survive.
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["execution_mode"] == "HUMAN_ONLY"
    assert result["broker_api_called"] is False
    assert result["ai_execution_count"] == 0
    rows = persistence.get_moltbook_entries(db_path=db)
    assert len(rows) == 1
    row = rows[0]
    assert row["ticker"] == "XOM"
    assert row["event_type"] == "STOP_LOSS_HIT"
    assert row["learning_direction"] == "MISTAKE_OR_INVALIDATION"
    assert row["trade_id"] == "MT_XOM"
    assert row["stop_loss_price"] == 98.5
    assert row["exit_price"] == 98.5
    assert row["realized_pl"] == -65.0
    assert row["idempotency_key"]


def test_stop_hit_with_bad_process_tags_classifies_as_bad_process_loss(db):
    result = _record(
        db,
        trade_id="MT_CVX",
        ticker="CVX",
        post_trade_outcome="STOPPED_OUT",
        stop_loss_hit=True,
        actual_exit_price=140.0,
        exit_quantity=5.0,
        entry_price=150.0,
        entry_quantity=5.0,
        realized_pl=-50.0,
        mistake_tags="oversized,fomo",
    )
    assert result["event_type"] == "STOP_LOSS_HIT"
    assert result["outcome_quality"] == "BAD_PROCESS_LOSS"
    assert result["learning_direction"] == "MISTAKE_OR_INVALIDATION"


def test_stop_hit_without_bad_tags_classifies_as_good_process_loss(db):
    # No bad-process tags → preserve good exit discipline classification.
    result = _record(
        db,
        trade_id="MT_TSM",
        ticker="TSM",
        post_trade_outcome="STOPPED_OUT",
        stop_loss_hit=True,
        actual_exit_price=373.6,
        exit_quantity=2.0,
        entry_price=393.26,
        entry_quantity=2.0,
        realized_pl=-39.32,
    )
    assert result["outcome_quality"] == "GOOD_PROCESS_LOSS"


def test_explicit_outcome_quality_overrides_tag_heuristic(db):
    # Operator's explicit choice wins over the mistake-tag heuristic.
    result = _record(
        db,
        trade_id="MT_OVR",
        post_trade_outcome="STOPPED_OUT",
        stop_loss_hit=True,
        outcome_quality="GOOD_PROCESS_LOSS",
        mistake_tags="oversized,fomo",
        actual_exit_price=10.0,
        exit_quantity=1.0,
        entry_price=11.0,
        entry_quantity=1.0,
        realized_pl=-1.0,
    )
    assert result["outcome_quality"] == "GOOD_PROCESS_LOSS"


# ---------------------------------------------------------------------------
# PARTIAL_TP_HIT / PARTIAL_TP_LOGGED
# ---------------------------------------------------------------------------


def test_partial_tp_hit_creates_success_entry(db):
    result = _record(
        db,
        trade_id="MT_ANET",
        ticker="ANET",
        post_trade_outcome="PARTIAL_TP",
        actual_exit_price=420.0,
        exit_quantity=7.0,  # 70% of 10
        entry_price=380.0,
        entry_quantity=10.0,
        partial_take_profit_price=420.0,
        partial_take_profit_quantity=7.0,
        runner_quantity=3.0,
        take_profit_plan="70% TP / 30% runner",
        realized_pl=280.0,
        success_tags="planned_partial,trailing_runner",
    )
    assert result["status"] == "created"
    assert result["event_type"] == "PARTIAL_TP_HIT"
    assert result["learning_direction"] == "SUCCESS_PATTERN"
    assert result["outcome_quality"] == "GOOD_PROCESS_WIN"
    assert result["booked_percent"] == pytest.approx(70.0, abs=0.001)
    assert result["ride_percent"] == pytest.approx(30.0, abs=0.001)
    rows = persistence.get_moltbook_entries(db_path=db)
    row = next(r for r in rows if r["ticker"] == "ANET")
    assert row["event_type"] == "PARTIAL_TP_HIT"
    assert row["take_profit_price"] == 420.0
    assert row["success_tags"]


def test_partial_tp_logged_creates_exactly_one_entry_then_updates(db):
    first = _record(
        db,
        trade_id="MT_ASML",
        ticker="ASML",
        post_trade_outcome="PARTIAL_TP",
        actual_exit_price=0.0,  # plan only — not yet filled
        exit_quantity=0.0,
        entry_price=900.0,
        entry_quantity=4.0,
        partial_take_profit_price=980.0,
        partial_take_profit_quantity=2.8,  # 70%
        realized_pl=0.0,
    )
    assert first["status"] == "created"
    assert first["event_type"] == "PARTIAL_TP_LOGGED"
    assert first["learning_direction"] == "SUCCESS_PATTERN"

    # Re-save the same planning event — must update, not duplicate.
    second = _record(
        db,
        trade_id="MT_ASML",
        ticker="ASML",
        post_trade_outcome="PARTIAL_TP",
        actual_exit_price=0.0,
        exit_quantity=0.0,
        entry_price=900.0,
        entry_quantity=4.0,
        partial_take_profit_price=985.0,  # updated plan price
        partial_take_profit_quantity=2.8,
        realized_pl=0.0,
    )
    assert second["status"] == "updated"
    assert "already existed" in second["message"]
    rows = persistence.get_moltbook_entries(db_path=db)
    asml = [r for r in rows if r["ticker"] == "ASML"]
    assert len(asml) == 1
    assert asml[0]["take_profit_price"] == 985.0  # update applied
    assert asml[0]["event_type"] == "PARTIAL_TP_LOGGED"


# ---------------------------------------------------------------------------
# CLOSED
# ---------------------------------------------------------------------------


def test_closed_win_creates_success_entry(db):
    result = _record(
        db,
        trade_id="MT_GLD_WIN",
        ticker="GLD",
        post_trade_outcome="CLOSED_WIN",
        actual_exit_price=440.0,
        exit_quantity=0.5,
        entry_price=418.0,
        entry_quantity=0.5,
        realized_pl=11.0,
    )
    assert result["status"] == "created"
    # Outcome-correctness contract: CLOSED + P>0 normalizes to CLOSED_WIN.
    assert result["event_type"] == "CLOSED_WIN"
    assert result["outcome_quality"] == "GOOD_PROCESS_WIN"
    assert result["learning_direction"] == "SUCCESS_PATTERN"


def test_closed_loss_creates_loss_entry(db):
    result = _record(
        db,
        trade_id="MT_GLD_LOSS",
        ticker="GLD",
        post_trade_outcome="CLOSED_LOSS",
        actual_exit_price=411.5,
        exit_quantity=0.1114,
        entry_price=418.07,
        entry_quantity=0.1114,
        realized_pl=-0.7319,
    )
    # CLOSED + P<0 normalizes to CLOSED_LOSS.
    assert result["event_type"] == "CLOSED_LOSS"
    assert result["outcome_quality"] == "GOOD_PROCESS_LOSS"
    assert result["learning_direction"] == "MISTAKE_OR_INVALIDATION"


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_saving_same_reconciliation_twice_does_not_duplicate(db):
    args = dict(
        trade_id="MT_DUP",
        ticker="DUP",
        post_trade_outcome="CLOSED_WIN",
        actual_exit_price=210.0,
        exit_quantity=4.0,
        entry_price=200.0,
        entry_quantity=4.0,
        realized_pl=40.0,
    )
    first = _record(db, **args)
    second = _record(db, **args)
    assert first["status"] == "created"
    assert second["status"] == "updated"
    assert first["idempotency_key"] == second["idempotency_key"]
    rows = persistence.get_moltbook_entries(db_path=db)
    dup = [r for r in rows if r["ticker"] == "DUP"]
    assert len(dup) == 1


def test_idempotency_key_is_deterministic_for_same_inputs():
    k1 = bridge.compute_idempotency_key(
        trade_id="MT_X", event_type="STOP_LOSS_HIT",
        exit_price=98.5, exit_quantity=10.0,
    )
    k2 = bridge.compute_idempotency_key(
        trade_id="MT_X", event_type="STOP_LOSS_HIT",
        exit_price=98.5, exit_quantity=10.0,
    )
    assert k1 == k2
    k3 = bridge.compute_idempotency_key(
        trade_id="MT_X", event_type="STOP_LOSS_HIT",
        exit_price=98.5, exit_quantity=11.0,
    )
    assert k3 != k1


# ---------------------------------------------------------------------------
# Moltbook learns from both wins AND losses
# ---------------------------------------------------------------------------


def test_moltbook_learns_from_both_losses_and_wins(db):
    _record(
        db, trade_id="MT_LOSS", ticker="ABC",
        post_trade_outcome="STOPPED_OUT", stop_loss_hit=True,
        actual_exit_price=80.0, exit_quantity=2.0,
        entry_price=100.0, entry_quantity=2.0, realized_pl=-40.0,
    )
    _record(
        db, trade_id="MT_WIN", ticker="XYZ",
        post_trade_outcome="CLOSED_WIN",
        actual_exit_price=120.0, exit_quantity=2.0,
        entry_price=100.0, entry_quantity=2.0, realized_pl=40.0,
    )
    rows = persistence.get_moltbook_entries(db_path=db)
    directions = {r["learning_direction"] for r in rows}
    assert "MISTAKE_OR_INVALIDATION" in directions
    assert "SUCCESS_PATTERN" in directions


# ---------------------------------------------------------------------------
# Skipping
# ---------------------------------------------------------------------------


def test_open_reconciliation_skipped_no_entry(db):
    result = _record(
        db, trade_id="MT_OPEN", ticker="OPN",
        post_trade_outcome="OPEN",
        actual_exit_price=0.0, exit_quantity=0.0,
    )
    assert result["status"] == "skipped"
    rows = persistence.get_moltbook_entries(db_path=db)
    assert [r for r in rows if r["ticker"] == "OPN"] == []


# ---------------------------------------------------------------------------
# Safety invariants
# ---------------------------------------------------------------------------


def test_safety_invariants_unchanged_on_persisted_row(db):
    _record(
        db, trade_id="MT_SAFE", ticker="SAFE",
        post_trade_outcome="CLOSED_WIN",
        actual_exit_price=110.0, exit_quantity=1.0,
        entry_price=100.0, entry_quantity=1.0, realized_pl=10.0,
    )
    rows = persistence.get_moltbook_entries(db_path=db)
    row = next(r for r in rows if r["ticker"] == "SAFE")
    assert row["advisory_status"] == "ADVISORY_ONLY"
    assert row["execution_mode"] == "HUMAN_ONLY"
    assert row["ai_execution_count"] == 0
    assert row["human_review_required"] in (1, True)


# ---------------------------------------------------------------------------
# Pure classification helpers
# ---------------------------------------------------------------------------


def test_classify_event_type_stop_hit_synonyms():
    for pto in ("STOPPED_OUT", "STOP_HIT", "STOP_LOSS"):
        assert bridge.classify_event_type(
            post_trade_outcome=pto, stop_loss_hit=False,
            actual_exit_price=10.0, exit_quantity=1.0,
            partial_take_profit_price=None, partial_take_profit_quantity=None,
        ) == "STOP_LOSS_HIT"


def test_classify_event_type_explicit_event_wins():
    assert bridge.classify_event_type(
        post_trade_outcome="CLOSED_WIN", stop_loss_hit=False,
        actual_exit_price=10.0, exit_quantity=1.0,
        partial_take_profit_price=None, partial_take_profit_quantity=None,
        explicit_event_type="PARTIAL_TP_LOGGED",
    ) == "PARTIAL_TP_LOGGED"


def test_classify_learning_direction_partial_tp_is_success():
    assert bridge.classify_learning_direction(
        "PARTIAL_TP_HIT", ""
    ) == "SUCCESS_PATTERN"
    assert bridge.classify_learning_direction(
        "PARTIAL_TP_LOGGED", ""
    ) == "SUCCESS_PATTERN"


# ---------------------------------------------------------------------------
# Eligibility helper (single authoritative gate)
# ---------------------------------------------------------------------------


def _elig(event_type, **kwargs):
    base = {
        "event_type": event_type,
        "symbol": kwargs.pop("symbol", "AAPL"),
        "trade_id": kwargs.pop("trade_id", "MT_X"),
        "exit_price": kwargs.pop("exit_price", 110.0),
        "realized_pl": kwargs.pop("realized_pl", 10.0),
        "thesis": kwargs.pop("thesis", "Real operator thesis."),
    }
    base.update(kwargs)
    return bridge.is_moltbook_eligible_reconciliation_event(base)


def test_eligibility_stop_loss_hit_with_exit_price_is_eligible():
    v = _elig("STOP_LOSS_HIT", exit_price=98.5, realized_pl=-65.0)
    assert v["eligible"] is True
    assert v["normalized_event_type"] == "STOP_LOSS_HIT"
    assert v["reason"] == bridge.ELIGIBLE_STOP_LOSS_HIT


def test_eligibility_take_profit_hit_is_eligible():
    v = _elig("TAKE_PROFIT_HIT", exit_price=120.0, realized_pl=20.0)
    assert v["eligible"] is True
    assert v["reason"] == bridge.ELIGIBLE_TAKE_PROFIT_HIT


def test_eligibility_partial_tp_logged_is_eligible_without_fill():
    v = _elig("PARTIAL_TP_LOGGED", exit_price=0.0, realized_pl=0.0)
    assert v["eligible"] is True
    assert v["reason"] == bridge.ELIGIBLE_PARTIAL_TP


def test_eligibility_closed_positive_pl_normalizes_to_closed_win():
    v = _elig("CLOSED", exit_price=110.0, realized_pl=10.0)
    assert v["eligible"] is True
    assert v["normalized_event_type"] == "CLOSED_WIN"
    assert v["reason"] == bridge.ELIGIBLE_CLOSED_WIN


def test_eligibility_closed_negative_pl_normalizes_to_closed_loss():
    v = _elig("CLOSED", exit_price=80.0, realized_pl=-20.0)
    assert v["eligible"] is True
    assert v["normalized_event_type"] == "CLOSED_LOSS"
    assert v["reason"] == bridge.ELIGIBLE_CLOSED_LOSS


def test_eligibility_closed_zero_pl_normalizes_to_breakeven():
    v = _elig("CLOSED", exit_price=100.0, realized_pl=0.0)
    assert v["eligible"] is True
    assert v["normalized_event_type"] == "BREAKEVEN_EXIT"
    assert v["reason"] == bridge.ELIGIBLE_BREAKEVEN


def test_eligibility_open_trade_not_eligible():
    v = _elig("OPENED", status="OPEN", exit_price=0.0, realized_pl=0.0)
    assert v["eligible"] is False
    assert v["reason"] == bridge.SKIP_OPEN_TRADE


def test_eligibility_watchlist_signal_not_eligible():
    v = _elig("WATCHLISTED", status="WATCHLIST", exit_price=0.0, realized_pl=0.0)
    assert v["eligible"] is False
    assert v["reason"] == bridge.SKIP_SIGNAL_ONLY


def test_eligibility_price_mark_not_eligible():
    v = _elig("PRICE_MARK", exit_price=0.0, realized_pl=0.0)
    assert v["eligible"] is False
    assert v["reason"] == bridge.SKIP_PRICE_MARK_ONLY


def test_eligibility_unrealized_pnl_update_not_eligible():
    v = _elig("UNREALIZED_PNL_UPDATE", exit_price=0.0, realized_pl=0.0)
    assert v["eligible"] is False
    assert v["reason"] == bridge.SKIP_UNREALIZED_ONLY


def test_eligibility_thesis_test_is_test_demo_fixture():
    v = _elig("CLOSED_WIN", thesis="test")
    assert v["eligible"] is False
    assert v["reason"] == bridge.SKIP_TEST_DEMO_FIXTURE


def test_eligibility_thesis_single_letter_t_is_fixture():
    v = _elig("CLOSED_WIN", thesis="t")
    assert v["eligible"] is False
    assert v["reason"] == bridge.SKIP_TEST_DEMO_FIXTURE


def test_eligibility_thesis_probe_is_fixture():
    v = _elig("STOP_LOSS_HIT", thesis="probe")
    assert v["eligible"] is False
    assert v["reason"] == bridge.SKIP_TEST_DEMO_FIXTURE


def test_eligibility_explicit_is_test_flag():
    v = _elig("CLOSED_WIN", is_test=True)
    assert v["eligible"] is False
    assert v["reason"] == bridge.SKIP_TEST_DEMO_FIXTURE


def test_eligibility_missing_trade_identity():
    v = _elig("CLOSED_WIN", trade_id="", symbol="AAPL")
    assert v["eligible"] is False
    assert v["reason"] == bridge.SKIP_MISSING_TRADE_IDENTITY


def test_eligibility_missing_exit_and_pl_not_eligible():
    v = _elig("STOP_LOSS_HIT", exit_price=0.0, realized_pl=None, exit_reason="")
    assert v["eligible"] is False
    assert v["reason"] == bridge.SKIP_MISSING_EXIT_OR_REALIZED_PL


def test_eligibility_exit_reason_terminal_text_admits_entry():
    v = _elig("CLOSED", exit_price=0.0, realized_pl=None,
              exit_reason="closed at market")
    # No P/L direction; exit_reason carries terminal intent so it should
    # still pass the has_exit_or_realized_pl gate.
    assert v["eligible"] is True


def test_eligibility_buy_signal_only_not_eligible():
    v = _elig("BUY", status="PENDING", exit_price=0.0, realized_pl=0.0)
    assert v["eligible"] is False
    assert v["reason"] in {bridge.SKIP_OPEN_TRADE, bridge.SKIP_SIGNAL_ONLY}


def test_record_reconciliation_skips_test_thesis(db):
    # A test/demo thesis must not create a Moltbook entry even though the
    # other fields look terminal.
    result = _record(
        db,
        trade_id="MT_SPY_TEST",
        ticker="SPY",
        thesis="test",
        post_trade_outcome="CLOSED_WIN",
        actual_exit_price=452.0,
        exit_quantity=1.0,
        entry_price=450.0,
        entry_quantity=1.0,
        realized_pl=2.0,
    )
    assert result["status"] == "skipped"
    assert result["reason"] == bridge.SKIP_TEST_DEMO_FIXTURE
    assert persistence.get_moltbook_entries(db_path=db) == []


def test_record_reconciliation_skips_thesis_t(db):
    result = _record(
        db, trade_id="MT_SPY_T", ticker="SPY", thesis="t",
        post_trade_outcome="CLOSED_LOSS",
        actual_exit_price=448.0, exit_quantity=1.0,
        entry_price=450.0, entry_quantity=1.0,
        realized_pl=-2.0,
    )
    assert result["status"] == "skipped"
    assert result["reason"] == bridge.SKIP_TEST_DEMO_FIXTURE
    assert persistence.get_moltbook_entries(db_path=db) == []


def test_contradictory_positive_pl_cannot_be_trade_loss(db):
    # Even when the operator passes a confused outcome_quality, positive
    # realized_pl must not collapse to legacy mistake_type='trade_loss'.
    _record(
        db, trade_id="MT_CTR", ticker="CTR",
        post_trade_outcome="CLOSED_WIN",
        actual_exit_price=110.0, exit_quantity=1.0,
        entry_price=100.0, entry_quantity=1.0,
        realized_pl=10.0,
        outcome_quality="BAD_PROCESS_WIN",
    )
    rows = persistence.get_moltbook_entries(db_path=db)
    ctr = next(r for r in rows if r["ticker"] == "CTR")
    assert ctr["mistake_type"] != "trade_loss"
    assert ctr["realized_pl"] == 10.0


def test_double_save_creates_exactly_one_entry(db):
    args = dict(
        trade_id="MT_ONCE", ticker="ONCE",
        post_trade_outcome="STOPPED_OUT", stop_loss_hit=True,
        actual_exit_price=98.0, exit_quantity=10.0,
        entry_price=100.0, entry_quantity=10.0,
        realized_pl=-20.0,
    )
    _record(db, **args)
    _record(db, **args)
    rows = persistence.get_moltbook_entries(db_path=db)
    assert len([r for r in rows if r["ticker"] == "ONCE"]) == 1


def test_normalize_event_type_handles_manual_exit():
    assert bridge.normalize_event_type(
        event_type="MANUAL_EXIT", realized_pl=5.0, exit_reason="",
    ) == "MANUAL_EXIT_WIN"
    assert bridge.normalize_event_type(
        event_type="MANUAL_EXIT", realized_pl=-5.0, exit_reason="",
    ) == "MANUAL_EXIT_LOSS"


def test_allowed_event_types_contains_full_finalized_vocabulary():
    expected = {
        "STOP_LOSS_HIT", "TRAILING_STOP_HIT", "TAKE_PROFIT_HIT",
        "PARTIAL_TP_HIT", "PARTIAL_TP_LOGGED",
        "CLOSED", "CLOSED_WIN", "CLOSED_LOSS",
        "MANUAL_EXIT_WIN", "MANUAL_EXIT_LOSS",
        "BREAKEVEN_EXIT", "RULE_FOLLOWED_LOSS",
        "BAD_PROCESS_WIN", "BAD_PROCESS_LOSS",
    }
    assert bridge.ALLOWED_MOLTBOOK_EVENT_TYPES == expected
