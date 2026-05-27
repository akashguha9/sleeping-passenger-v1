"""Regression: an open/active/runner/watchlist trade cannot enter Moltbook
even if an upstream reconciliation/status field incorrectly says CLOSED,
STOP_LOSS_HIT, TAKE_PROFIT_HIT, or PARTIAL_TP_LOGGED.

The single canonical truth for OPEN positions is
``data/daily_payload/verified_current_holdings.json``. When a candidate
Moltbook entry's ticker is still present in that file, the learning
bridge MUST reject the candidate regardless of the upstream event/status
labelling — otherwise a contaminated upstream label can teach the
Moltbook from a position the operator has not actually closed.

This test pins both:
  (a) the existing precise rejection when ``status`` is one of
      OPEN/ACTIVE/RUNNER_ACTIVE/WATCHLIST/PENDING/SIGNAL_ONLY, even when
      ``event_type`` claims a terminal outcome; and
  (b) the new cross-check against ``verified_current_holdings.json`` —
      the case where the candidate lies about (or omits) ``status`` but
      the ticker is still verified-open.

Safety invariants must remain stamped on every response.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.moltbook_learning_bridge as bridge
import scripts.persistence as persistence


# Tickers actually present in the live verified holdings file.
_VERIFIED_OPEN = ("MSFT", "XOM", "RTX", "LMT", "CVX", "ANET", "ASML", "TSM")
# Operator note in verified_current_holdings.json: GLD is intentionally
# absent (sold). Anything not listed is safe to treat as terminal.
_NOT_VERIFIED_OPEN = ("GLD", "ZZZ_UNKNOWN")


@pytest.fixture
def db(tmp_path: Path) -> Path:
    target = tmp_path / "contamination.db"
    persistence.init_schema(target)
    return target


@pytest.fixture
def empty_verified_holdings(tmp_path: Path) -> Path:
    """A verified-holdings file with zero open positions — used to prove
    the cross-check is opt-in and does not affect callers that supply
    their own (empty) source."""
    path = tmp_path / "verified_current_holdings.json"
    path.write_text(
        json.dumps({"positions": [], "operator_note": "test fixture: empty"}),
        encoding="utf-8",
    )
    return path


def _candidate(**overrides):
    """Minimal closed-trade candidate the bridge would normally accept."""
    base = dict(
        trade_id="MT_TEST_OPEN_CONTAMINATION",
        event_id="EV_TEST_OPEN_CONTAMINATION",
        ticker="MSFT",
        side="BUY",
        post_trade_outcome="CLOSED_WIN",
        actual_exit_price=420.0,
        exit_quantity=0.1,
        entry_price=418.05,
        entry_quantity=0.1,
        realized_pl=0.2,
    )
    base.update(overrides)
    return base


def _assert_safety_stamps(result: dict) -> None:
    assert result["advisory_status"] == "ADVISORY_ONLY"
    assert result["execution_mode"] == "HUMAN_ONLY"
    assert result["broker_api_called"] is False
    assert result["ai_execution_count"] == 0
    assert result["execution_gate"] == "LOCKED"


# ---------------------------------------------------------------------------
# (a) Existing precise-status guard — pins current behaviour.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_event_type",
    ["CLOSED", "CLOSED_WIN", "STOP_LOSS_HIT", "TAKE_PROFIT_HIT", "PARTIAL_TP_LOGGED"],
)
@pytest.mark.parametrize(
    "open_status",
    ["OPEN", "ACTIVE", "RUNNER_ACTIVE", "WATCHLIST", "PENDING", "SIGNAL_ONLY"],
)
def test_open_status_blocks_even_when_event_type_is_terminal(
    db: Path, tmp_path: Path, bad_event_type: str, open_status: str,
) -> None:
    """Even when the upstream event_type lies (says terminal), an explicit
    open-ish ``reconciliation_status`` must reject the candidate."""
    result = bridge.record_reconciliation_learning(
        **_candidate(
            ticker="ZZZ_NEVER_REAL",  # not in verified holdings — isolates the status check
            explicit_event_type=bad_event_type,
            reconciliation_status=open_status,
            post_trade_outcome="CLOSED_WIN",
            db_path=db,
            jsonl_path=tmp_path / "audit.jsonl",
        )
    )
    assert result["status"] == "skipped", (
        f"event_type={bad_event_type} + status={open_status} must be rejected; "
        f"got {result}"
    )
    # Reason should clearly flag this as an open-trade contamination.
    assert result["reason"] in {
        bridge.SKIP_OPEN_TRADE,
        bridge.SKIP_SIGNAL_ONLY,
    }, f"Unexpected skip reason {result['reason']!r}; got {result}"
    _assert_safety_stamps(result)
    rows = persistence.get_moltbook_entries(db_path=db)
    assert rows == [], (
        "No Moltbook row may be written when the candidate is open-status; "
        f"found {len(rows)} row(s)."
    )


# ---------------------------------------------------------------------------
# (b) New cross-check against verified_current_holdings.json
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("verified_ticker", _VERIFIED_OPEN)
@pytest.mark.parametrize(
    "lying_event_type",
    ["CLOSED", "CLOSED_WIN", "STOP_LOSS_HIT", "TAKE_PROFIT_HIT", "PARTIAL_TP_LOGGED"],
)
def test_verified_open_ticker_blocks_even_when_status_says_closed(
    db: Path, tmp_path: Path, verified_ticker: str, lying_event_type: str,
) -> None:
    """An upstream caller may set status=CLOSED (or omit it entirely),
    yet the ticker may still be in the canonical verified holdings file.
    The bridge must reject these and surface a precise reason."""
    result = bridge.record_reconciliation_learning(
        **_candidate(
            ticker=verified_ticker,
            explicit_event_type=lying_event_type,
            reconciliation_status="CLOSED",  # the lie
            post_trade_outcome="CLOSED_WIN",
            db_path=db,
            jsonl_path=tmp_path / "audit.jsonl",
        ),
        cross_check_verified_holdings=True,
    )
    assert result["status"] == "skipped", (
        f"{verified_ticker} is in verified_current_holdings.json — must be "
        f"rejected as still-open. Got {result}"
    )
    assert result["reason"] == bridge.SKIP_TICKER_STILL_OPEN_IN_VERIFIED_HOLDINGS, (
        f"Expected precise reason "
        f"{bridge.SKIP_TICKER_STILL_OPEN_IN_VERIFIED_HOLDINGS}; got {result}"
    )
    _assert_safety_stamps(result)
    rows = persistence.get_moltbook_entries(db_path=db)
    assert rows == [], f"Expected zero Moltbook rows; found {len(rows)}"


def test_verified_open_ticker_with_no_status_field_is_still_blocked(
    db: Path, tmp_path: Path,
) -> None:
    """Upstream forgot to set ``reconciliation_status``. The existing
    open-status guard cannot help; only the verified-holdings cross-check
    can catch this contamination class."""
    result = bridge.record_reconciliation_learning(
        **_candidate(
            ticker="MSFT",
            explicit_event_type="CLOSED_WIN",
            reconciliation_status="",
            post_trade_outcome="CLOSED_WIN",
            db_path=db,
            jsonl_path=tmp_path / "audit.jsonl",
        ),
        cross_check_verified_holdings=True,
    )
    assert result["status"] == "skipped"
    assert result["reason"] == bridge.SKIP_TICKER_STILL_OPEN_IN_VERIFIED_HOLDINGS
    _assert_safety_stamps(result)


def test_verified_open_ticker_handles_exchange_prefix(
    db: Path, tmp_path: Path,
) -> None:
    """``NASDAQ:MSFT`` and ``MSFT`` must match the same verified holding —
    ticker normalization must mirror the daily_payload conventions."""
    result = bridge.record_reconciliation_learning(
        **_candidate(
            ticker="NASDAQ:MSFT",
            explicit_event_type="CLOSED_WIN",
            reconciliation_status="CLOSED",
            db_path=db,
            jsonl_path=tmp_path / "audit.jsonl",
        ),
        cross_check_verified_holdings=True,
    )
    assert result["status"] == "skipped"
    assert result["reason"] == bridge.SKIP_TICKER_STILL_OPEN_IN_VERIFIED_HOLDINGS


@pytest.mark.parametrize("not_verified", _NOT_VERIFIED_OPEN)
def test_non_verified_ticker_is_allowed_through_cross_check(
    db: Path, tmp_path: Path, not_verified: str,
) -> None:
    """Tickers that are NOT in verified_current_holdings.json (e.g. GLD —
    operator note explicitly says it was sold) must pass the cross-check.
    This proves the gate does not over-block."""
    result = bridge.record_reconciliation_learning(
        **_candidate(
            ticker=not_verified,
            trade_id=f"MT_{not_verified}_CLOSED",
            explicit_event_type="CLOSED_WIN",
            reconciliation_status="CLOSED",
            post_trade_outcome="CLOSED_WIN",
            db_path=db,
            jsonl_path=tmp_path / "audit.jsonl",
        ),
        cross_check_verified_holdings=True,
    )
    assert result["status"] == "created", (
        f"{not_verified} is NOT in verified holdings; must be accepted. "
        f"Got {result}"
    )
    _assert_safety_stamps(result)


def test_cross_check_opt_out_via_empty_verified_holdings_path(
    db: Path, tmp_path: Path, empty_verified_holdings: Path,
) -> None:
    """When a caller supplies an empty verified-holdings file, the
    cross-check must defer to that source — confirming the gate is
    file-driven and test-injectable."""
    result = bridge.record_reconciliation_learning(
        **_candidate(
            ticker="MSFT",
            explicit_event_type="CLOSED_WIN",
            reconciliation_status="CLOSED",
            db_path=db,
            jsonl_path=tmp_path / "audit.jsonl",
        ),
        cross_check_verified_holdings=True,
        verified_holdings_path=empty_verified_holdings,
    )
    assert result["status"] == "created", (
        "Empty verified-holdings file means no cross-check rejection. "
        f"Got {result}"
    )
    _assert_safety_stamps(result)


def test_default_cross_check_is_off_preserves_existing_behaviour(
    db: Path, tmp_path: Path,
) -> None:
    """Without opting in, the bridge behaves exactly as before — so
    existing fixtures keyed on XOM/MSFT/etc. keep working."""
    result = bridge.record_reconciliation_learning(
        **_candidate(
            ticker="MSFT",
            explicit_event_type="CLOSED_WIN",
            reconciliation_status="CLOSED",
            db_path=db,
            jsonl_path=tmp_path / "audit.jsonl",
        ),
    )
    assert result["status"] == "created"
    _assert_safety_stamps(result)
