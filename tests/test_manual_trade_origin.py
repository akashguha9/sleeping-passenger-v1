"""Tests for the canonical user-manual-trade origin classifier.

This module is the single source of truth for "does this row count as a
user-entered manual trade?".  The Reconciliation queue, Learning
Completeness report, and Cancel Log guard all import its predicate, so a
regression here cascades into the live operator surface.

Safety invariants:
- predicate is pure and read-only,
- no broker calls,
- no execution,
- safety_stamps are never altered by classification.
"""
from __future__ import annotations

import pytest

from scripts.manual_trade_origin import (
    ORIGIN_USER_MANUAL,
    ORIGIN_EXCLUDED_PROVENANCE,
    ORIGIN_EXCLUDED_TRADE_MODE,
    ORIGIN_EXCLUDED_LOGGED_BY,
    ORIGIN_EXCLUDED_PROBE_THESIS,
    ORIGIN_EXCLUDED_EVENT_ID,
    ORIGIN_EXCLUDED_BROKER_FLAG,
    ORIGIN_EXCLUDED_AI_COUNT,
    classify_manual_trade_origin,
    duplicate_group_key,
    is_cancelled_log,
    is_user_manual_trade,
)


def _user_row(**overrides):
    base = {
        "trade_id": "MT_user",
        "event_id": "EV_USER",
        "ticker": "ICICIBANK.NS",
        "side": "BUY",
        "quantity": 3.8908,
        "price": 40.72,
        "executed_at": "2026-05-15T12:00:00+00:00",
        "thesis": "trend continuation off prior pivot",
        "notes": "",
        "logged_by": "human",
        "trade_mode": "REAL_MANUAL",
        "created_via": "manual_trade_log",
        "broker_api_called": 0,
        "ai_execution_count": 0,
        "reconciliation_status": "",
    }
    base.update(overrides)
    return base


def test_real_user_row_classifies_as_user_manual():
    row = _user_row()
    assert classify_manual_trade_origin(row) == ORIGIN_USER_MANUAL
    assert is_user_manual_trade(row) is True


def test_paper_trade_mode_still_user_manual():
    # Paper-trade-mode rows the operator imported themselves are still
    # counted — paper imports are user-driven, just not real fills.
    row = _user_row(trade_mode="PAPER", logged_by="human")
    assert classify_manual_trade_origin(row) == ORIGIN_USER_MANUAL


def test_empty_provenance_is_excluded():
    row = _user_row(created_via="")
    assert classify_manual_trade_origin(row) == ORIGIN_EXCLUDED_PROVENANCE


def test_imported_csv_provenance_excluded():
    row = _user_row(created_via="imported_csv")
    assert classify_manual_trade_origin(row) == ORIGIN_EXCLUDED_PROVENANCE


@pytest.mark.parametrize(
    "thesis",
    ["probe", "PROBE", "  probe  ", "test", "seed", "demo", "fixture", "mock"],
)
def test_probe_theses_excluded(thesis):
    row = _user_row(thesis=thesis)
    assert classify_manual_trade_origin(row) == ORIGIN_EXCLUDED_PROBE_THESIS


def test_thesis_containing_probe_but_not_exact_is_kept():
    # Real user logs sometimes contain the word "probe" as part of a
    # sentence (e.g. paper "probe" thesis).  Only exact placeholder
    # match is excluded.
    row = _user_row(thesis="Codex-selected India bank paper probe — testing rebound")
    assert classify_manual_trade_origin(row) == ORIGIN_USER_MANUAL


@pytest.mark.parametrize(
    "event_id",
    ["SEED_AAPL", "DEMO_001", "FIXTURE_QQQ", "SMOKE_TEST", "TEST_X", "MOCK_Y", "SAMPLE_Z"],
)
def test_seed_event_id_prefixes_excluded(event_id):
    row = _user_row(event_id=event_id)
    assert classify_manual_trade_origin(row) == ORIGIN_EXCLUDED_EVENT_ID


def test_ev_prefix_event_id_is_kept_when_thesis_is_real():
    # EV_<something> is widely used in tests for ergonomic event IDs;
    # by itself it must not exclude a row with a real thesis.
    row = _user_row(event_id="EV_USER42")
    assert classify_manual_trade_origin(row) == ORIGIN_USER_MANUAL


@pytest.mark.parametrize(
    "logged_by", ["seed", "demo", "smoke_test", "paper_ledger_import", "mock", "fixture"],
)
def test_excluded_logged_by_values(logged_by):
    row = _user_row(logged_by=logged_by)
    assert classify_manual_trade_origin(row) == ORIGIN_EXCLUDED_LOGGED_BY


def test_broker_api_called_flag_excludes():
    row = _user_row(broker_api_called=1)
    assert classify_manual_trade_origin(row) == ORIGIN_EXCLUDED_BROKER_FLAG


def test_ai_execution_count_excludes():
    row = _user_row(ai_execution_count=1)
    assert classify_manual_trade_origin(row) == ORIGIN_EXCLUDED_AI_COUNT


@pytest.mark.parametrize(
    "mode", ["SEED", "DEMO", "FIXTURE", "TEST", "MOCK", "SAMPLE", "SYSTEM"],
)
def test_synthetic_trade_modes_excluded(mode):
    row = _user_row(trade_mode=mode)
    assert classify_manual_trade_origin(row) == ORIGIN_EXCLUDED_TRADE_MODE


def test_cancelled_log_status_detected():
    assert is_cancelled_log({"reconciliation_status": "CANCELLED_DUPLICATE"})
    assert is_cancelled_log({"reconciliation_status": "CANCELLED_LOG"})
    assert not is_cancelled_log({"reconciliation_status": ""})
    assert not is_cancelled_log({"reconciliation_status": "RECONCILED"})


def test_duplicate_group_key_collapses_same_minute_double_click():
    row_a = _user_row(executed_at="2026-05-15T12:34:56+00:00")
    row_b = _user_row(executed_at="2026-05-15T12:34:59+00:00")
    assert duplicate_group_key(row_a) == duplicate_group_key(row_b)


def test_duplicate_group_key_distinguishes_different_minutes():
    row_a = _user_row(executed_at="2026-05-15T12:00:00+00:00")
    row_b = _user_row(executed_at="2026-05-15T12:34:00+00:00")
    assert duplicate_group_key(row_a) != duplicate_group_key(row_b)


def test_duplicate_group_key_distinguishes_qty_or_price():
    row_a = _user_row()
    row_b = _user_row(quantity=row_a["quantity"] + 0.0001)
    assert duplicate_group_key(row_a) != duplicate_group_key(row_b)
    row_c = _user_row(price=row_a["price"] + 0.01)
    assert duplicate_group_key(row_a) != duplicate_group_key(row_c)


def test_classifier_tolerates_non_dict_input():
    assert classify_manual_trade_origin(None) == ORIGIN_EXCLUDED_PROVENANCE  # type: ignore[arg-type]
    assert classify_manual_trade_origin("not a row") == ORIGIN_EXCLUDED_PROVENANCE  # type: ignore[arg-type]
