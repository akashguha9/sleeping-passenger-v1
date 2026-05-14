"""API-layer tests for the operator-discipline journal fields.

Verify that the new keyword arguments to ``log_manual_trade`` and
``reconcile_trade`` round-trip through SQLite and that ``list_manual_trades``
returns the new fields together with journal-quality metadata.

No FastAPI client is required for these tests — the helpers are exercised
directly so the assertions hold even when fastapi isn't installed.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from scripts import persistence
from scripts import signal_inbox_api


def _rebind_defaults(fn, new_db: Path):
    """Replace the ``db_path=DB_PATH`` default in a persistence helper.

    Persistence functions all bind ``DB_PATH`` as a default arg at definition
    time, so monkeypatching ``persistence.DB_PATH`` after the fact has no
    effect.  We replace the function's ``__defaults__`` / ``__kwdefaults__``
    tuple so calls fall through to ``new_db``.
    """
    if fn.__defaults__:
        new_defs = tuple(new_db if isinstance(d, Path) else d for d in fn.__defaults__)
        fn.__defaults__ = new_defs
    if fn.__kwdefaults__:
        fn.__kwdefaults__ = {
            k: (new_db if isinstance(v, Path) else v)
            for k, v in fn.__kwdefaults__.items()
        }


@pytest.fixture()
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db = tmp_path / "journal_api.db"
    persistence.init_schema(db)
    # Rebind every persistence helper that takes a ``db_path=DB_PATH`` default
    # so the signal_inbox_api helpers route through the tmp DB instead of
    # runtime/mvp_local.db.
    helper_names = [
        "init_schema",
        "_get_conn",
        "insert_manual_trade",
        "get_trades_for_event",
        "get_event_id_for_trade",
        "get_all_manual_trades",
        "insert_reconciliation",
        "get_reconciliations_for_trade",
        "get_all_reconciliations",
        "insert_signal_decision",
        "get_latest_signal_decision",
        "get_all_signal_decisions",
        "insert_reflection",
        "get_reflections_for_event",
        "has_reflection",
        "get_all_reflections",
        "insert_ai_summary",
        "get_ai_summaries_for_event",
        "has_ai_summary",
        "get_all_ai_summaries",
    ]
    originals: dict = {}
    for name in helper_names:
        fn = getattr(persistence, name, None)
        if fn is None:
            continue
        originals[name] = (fn.__defaults__, dict(fn.__kwdefaults__ or {}))
        _rebind_defaults(fn, db)
    monkeypatch.setattr(persistence, "DB_PATH", db, raising=True)
    # JSONL append paths use LOG_DIR; isolate them too so the test doesn't
    # pollute the operator's logs directory.
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr(signal_inbox_api, "MANUAL_TRADE_LOG", log_dir / "mt.jsonl")
    monkeypatch.setattr(signal_inbox_api, "RECONCILIATIONS_LOG", log_dir / "rec.jsonl")
    monkeypatch.setattr(signal_inbox_api, "REFLECTIONS_LOG", log_dir / "ref.jsonl")
    monkeypatch.setattr(signal_inbox_api, "AI_SUMMARIES_LOG", log_dir / "ai.jsonl")
    monkeypatch.setattr(signal_inbox_api, "INBOX_STATES_LOG", log_dir / "inbox.jsonl")
    try:
        yield db
    finally:
        # Restore original defaults so subsequent tests aren't affected.
        for name, (defs, kwdefs) in originals.items():
            fn = getattr(persistence, name)
            fn.__defaults__ = defs
            fn.__kwdefaults__ = kwdefs or None


def _safety_stamps_ok(resp: dict) -> None:
    assert resp["advisory_status"] == "ADVISORY_ONLY"
    assert resp["ai_execution_count"] == 0
    assert resp["broker_api_called"] is False
    # New stamps added by the sprint
    assert resp.get("execution_gate") == "LOCKED"
    assert resp.get("execution_permission") is False
    assert resp.get("can_execute") is False


def test_log_manual_trade_accepts_new_fields(tmp_db: Path) -> None:
    resp = signal_inbox_api.log_manual_trade(
        event_id="EV1",
        ticker="ETH",
        side="BUY",
        quantity=2.0,
        price=1500.0,
        thesis="reclaim of 1500",
        notes="day-trade idea",
        logged_by="human",
        leverage=1.0,
        invalidation_level="1450",
        expected_horizon="2-5d",
        risk_reason="<=0.5R",
        entry_reason="break of structure",
        exit_plan="trim 50% at 1600, stop 1450",
        confidence_before=0.65,
        emotional_state="calm",
        mistake_tags="",
        lesson="",
    )
    _safety_stamps_ok(resp)
    assert resp["status"] == "logged"
    assert resp["invalidation_level"] == "1450"
    assert resp["expected_horizon"] == "2-5d"
    assert resp["risk_reason"] == "<=0.5R"
    assert resp["entry_reason"] == "break of structure"
    assert resp["exit_plan"] == "trim 50% at 1600, stop 1450"
    assert resp["confidence_before"] == pytest.approx(0.65)
    assert resp["emotional_state"] == "calm"


def test_log_manual_trade_missing_fields_backwards_compatible(tmp_db: Path) -> None:
    """A frontend that omits the new fields entirely must keep working."""
    resp = signal_inbox_api.log_manual_trade(
        event_id="EV_OLD",
        ticker="BTC",
        side="BUY",
        quantity=1.0,
        price=100.0,
        thesis="old client thesis",
    )
    _safety_stamps_ok(resp)
    assert resp["status"] == "logged"
    assert resp["invalidation_level"] == ""
    assert resp["expected_horizon"] == ""
    assert resp["confidence_before"] is None


def test_list_manual_trades_returns_new_fields_and_journal_quality(tmp_db: Path) -> None:
    # Log one disciplined trade and one bare-bones trade.
    signal_inbox_api.log_manual_trade(
        event_id="EV_FULL",
        ticker="SOL",
        side="BUY",
        quantity=10.0,
        price=20.0,
        thesis="trend continuation",
        invalidation_level="18",
        expected_horizon="1w",
        risk_reason="<=1R",
        entry_reason="higher-low pullback",
        exit_plan="trim at 24, stop at 18",
        confidence_before=0.6,
        emotional_state="focused",
        mistake_tags="",
        lesson="watch volume next time",
    )
    signal_inbox_api.log_manual_trade(
        event_id="EV_BARE",
        ticker="DOGE",
        side="BUY",
        quantity=100.0,
        price=0.10,
        thesis="vibes",
    )
    listing = signal_inbox_api.list_manual_trades()
    _safety_stamps_ok(listing)
    assert listing["canonical"] is True
    assert listing["truth_source"] == "sqlite"
    assert listing["trade_count"] == 2

    full = next(t for t in listing["trades"] if t["event_id"] == "EV_FULL")
    bare = next(t for t in listing["trades"] if t["event_id"] == "EV_BARE")

    # Full trade has the new fields persisted.
    assert full["invalidation_level"] == "18"
    assert full["expected_horizon"] == "1w"
    assert full["confidence_before"] == pytest.approx(0.6)
    assert full["emotional_state"] == "focused"
    assert full["lesson"] == "watch volume next time"
    # Journal-quality metadata appears.
    assert "journal_completeness_score" in full
    assert "learning_readiness_score" in full
    assert "learning_ready" in full
    assert isinstance(full["missing_journal_fields"], list)

    # Bare trade is marked not learning-ready.
    assert bare["learning_ready"] is False
    assert bare["journal_completeness_score"] >= 0.0
    # Missing-fields should list at least invalidation_level / exit_plan.
    missing = set(bare["missing_journal_fields"])
    assert "invalidation_level" in missing
    assert "exit_plan" in missing

    # Aggregate stats present
    agg = listing["journal_quality_aggregate"]
    assert agg is not None
    assert agg["entry_count"] == 2
    assert agg["learning_ready_count"] >= 0
    assert agg["average_completeness"] >= 0.0


def test_list_manual_trades_can_skip_journal_quality(tmp_db: Path) -> None:
    signal_inbox_api.log_manual_trade(
        event_id="EV_SKIP",
        ticker="BTC",
        side="BUY",
        quantity=1.0,
        price=100.0,
        thesis="t",
    )
    listing = signal_inbox_api.list_manual_trades(include_journal_quality=False)
    assert listing["trade_count"] == 1
    assert listing["journal_quality_aggregate"] is None
    # Trade row still includes raw fields but no quality-scored keys.
    row = listing["trades"][0]
    assert "journal_completeness_score" not in row


def test_log_manual_trade_handles_bad_confidence_before(tmp_db: Path) -> None:
    """Garbage confidence_before should silently become None, not 500."""
    for bad in ("not a number", float("nan"), -5, 999, True):
        resp = signal_inbox_api.log_manual_trade(
            event_id="EV_BAD_CONF",
            ticker="BTC",
            side="BUY",
            quantity=1.0,
            price=100.0,
            thesis="x",
            confidence_before=bad,
        )
        _safety_stamps_ok(resp)
        assert resp["status"] == "logged"
        assert resp["confidence_before"] is None


def test_reconcile_trade_accepts_new_attribution_fields(tmp_db: Path) -> None:
    log_resp = signal_inbox_api.log_manual_trade(
        event_id="EV_REC",
        ticker="BTC",
        side="BUY",
        quantity=1.0,
        price=100.0,
        thesis="t",
    )
    trade_id = log_resp["trade_id"]
    rec_resp = signal_inbox_api.reconcile_trade(
        trade_id,
        actual_fill_price=99.0,
        actual_quantity=1.0,
        outcome_notes="stopped",
        pnl_estimate=-1.0,
        outcome_status="LOSS",
        outcome_quality="process_error",
        process_error="no_stop_set",
        process_error_notes="forgot to set hard stop",
        mistake_tags="no_stop,oversized",
        lesson="never enter without a stop",
    )
    _safety_stamps_ok(rec_resp)
    assert rec_resp["status"] == "logged"
    assert rec_resp["outcome_quality"] == "process_error"
    assert rec_resp["process_error"] == "no_stop_set"
    assert rec_resp["mistake_tags"] == "no_stop,oversized"
    assert rec_resp["lesson"] == "never enter without a stop"


def test_log_manual_trade_long_text_truncated(tmp_db: Path) -> None:
    """Belt-and-braces: a 10k-char lesson should not be persisted in full."""
    huge = "x" * 10_000
    resp = signal_inbox_api.log_manual_trade(
        event_id="EV_LONG",
        ticker="BTC",
        side="BUY",
        quantity=1.0,
        price=100.0,
        thesis="t",
        lesson=huge,
    )
    _safety_stamps_ok(resp)
    assert len(resp["lesson"]) <= 2000


def test_journal_quality_aggregate_safety_stamps(tmp_db: Path) -> None:
    """The aggregate stats block must never claim execution permission."""
    signal_inbox_api.log_manual_trade(
        event_id="EV_A",
        ticker="BTC",
        side="BUY",
        quantity=1.0,
        price=100.0,
        thesis="t",
    )
    listing = signal_inbox_api.list_manual_trades()
    agg = listing["journal_quality_aggregate"]
    assert agg["advisory_status"] == "ADVISORY_ONLY"
    assert agg["execution_gate"] == "LOCKED"
    assert agg["broker_api_called"] is False
    assert agg["ai_execution_count"] == 0
    assert agg["execution_permission"] is False
    assert agg["can_execute"] is False
