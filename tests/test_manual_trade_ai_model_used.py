"""End-to-end coverage for the ``ai_model_used`` field on Manual Trade Log.

Locks in three contracts that were broken by the seed-leak incident:

1. ``ai_model_used`` round-trips through ``log_manual_trade`` →
   ``persistence.insert_manual_trade`` → ``list_manual_trades``.
2. Omitting the field is valid (legacy clients / operator-skip) and the
   row reads back with an empty string (the UI renders "—").
3. The POST guard rejects probe/seed/automation markers BEFORE they get
   stamped with ``created_via='manual_trade_log'``, so the UI never sees
   another leaked AAPL row.

No broker calls.  Safety invariants are asserted on every accepted
response: ADVISORY_ONLY, HUMAN_ONLY, broker_order_id=NONE,
ai_execution_count=0, execution_gate=LOCKED.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import persistence
from scripts import signal_inbox_api


def _rebind_defaults(fn, new_db: Path) -> None:
    """Replace ``db_path=DB_PATH`` defaults on a persistence helper so
    direct calls fall through to ``new_db``.  Mirrors the pattern used by
    tests/test_manual_trade_journal_api.py.
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
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "ai_model_used.db"
    persistence.init_schema(db)
    helper_names = [
        "init_schema",
        "_get_conn",
        "insert_manual_trade",
        "get_trades_for_event",
        "get_event_id_for_trade",
        "get_all_manual_trades",
        "get_manual_trade",
    ]
    originals: dict = {}
    for name in helper_names:
        fn = getattr(persistence, name, None)
        if fn is None:
            continue
        originals[name] = (fn.__defaults__, dict(fn.__kwdefaults__ or {}))
        _rebind_defaults(fn, db)
    monkeypatch.setattr(persistence, "DB_PATH", db, raising=True)
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
        for name, (defs, kwdefs) in originals.items():
            fn = getattr(persistence, name)
            fn.__defaults__ = defs
            fn.__kwdefaults__ = kwdefs or None


def _assert_safety_stamps(resp: dict) -> None:
    """Every accepted manual-trade response must carry the same locks."""
    assert resp["advisory_status"] == "ADVISORY_ONLY"
    assert resp["execution_mode"] == "HUMAN_ONLY"
    assert resp["ai_execution_count"] == 0
    assert resp["broker_api_called"] is False
    assert resp["broker_order_id"] == "NONE"
    assert resp["execution_gate"] == "LOCKED"
    assert resp["execution_permission"] is False
    assert resp["can_execute"] is False


def test_schema_has_ai_model_used_column(tmp_db: Path) -> None:
    """Idempotent schema migration produced the new column."""
    import sqlite3

    conn = sqlite3.connect(str(tmp_db))
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(manual_trades)")}
    finally:
        conn.close()
    assert "ai_model_used" in cols, (
        "ai_model_used column missing — _additive_migrations should have added it"
    )


def test_log_persists_ai_model_used(tmp_db: Path) -> None:
    resp = signal_inbox_api.log_manual_trade(
        event_id="EV_ANET_01",
        ticker="ANET",
        side="BUY",
        quantity=1.0,
        price=141.97,
        thesis="break of structure on increasing volume",
        ai_model_used="Claude Code",
    )
    _assert_safety_stamps(resp)
    assert resp["status"] == "logged"
    assert resp["ai_model_used"] == "Claude Code"
    listing = signal_inbox_api.list_manual_trades(origin="manual_trade_log")
    rows = [t for t in listing["trades"] if t["event_id"] == "EV_ANET_01"]
    assert len(rows) == 1
    assert rows[0]["ai_model_used"] == "Claude Code"


def test_log_without_ai_model_used_defaults_to_empty(tmp_db: Path) -> None:
    """Legacy/optional path: omit the field entirely, row still saves."""
    resp = signal_inbox_api.log_manual_trade(
        event_id="EV_NO_MODEL",
        ticker="XOM",
        side="BUY",
        quantity=1.0,
        price=157.92,
        thesis="oil follow-through after inventory print",
    )
    _assert_safety_stamps(resp)
    assert resp["status"] == "logged"
    assert resp["ai_model_used"] == ""
    listing = signal_inbox_api.list_manual_trades(origin="manual_trade_log")
    rows = [t for t in listing["trades"] if t["event_id"] == "EV_NO_MODEL"]
    assert len(rows) == 1
    assert rows[0]["ai_model_used"] == ""


def test_log_ai_model_used_trimmed_and_length_capped(tmp_db: Path) -> None:
    """Free text but bounded — defends against runaway paste bloating the row."""
    long_text = "Multi-model consensus " + ("x" * 500)
    resp = signal_inbox_api.log_manual_trade(
        event_id="EV_LONG_MODEL",
        ticker="RTX",
        side="BUY",
        quantity=1.0,
        price=171.18,
        thesis="defense bid follow-through",
        ai_model_used="  " + long_text + "  ",
    )
    _assert_safety_stamps(resp)
    assert resp["status"] == "logged"
    # Trimmed; capped at 120 chars.
    assert resp["ai_model_used"].startswith("Multi-model consensus")
    assert len(resp["ai_model_used"]) <= 120


@pytest.mark.parametrize(
    "thesis",
    ["probe", "PROBE", "  probe  ", "test", "seed", "demo", "fixture", "smoke", "sample", "mock"],
)
def test_log_rejects_probe_thesis(tmp_db: Path, thesis: str) -> None:
    """The exact placeholder strings the leaked AAPL rows used are now blocked."""
    resp = signal_inbox_api.log_manual_trade(
        event_id="EV_OK",
        ticker="AAPL",
        side="BUY",
        quantity=1.0,
        price=180.0,
        thesis=thesis,
    )
    # _error_response shape — operation key + error message, no trade_id.
    assert "error" in resp
    assert "trade_id" not in resp
    # Row was NOT inserted.
    listing = signal_inbox_api.list_manual_trades(origin="manual_trade_log")
    assert listing["trade_count"] == 0


@pytest.mark.parametrize(
    "event_id",
    ["SEED_AAPL", "DEMO_001", "FIXTURE_X", "SMOKE_Y", "TEST_Z", "MOCK_Q", "SAMPLE_R"],
)
def test_log_rejects_seed_event_id_prefix(tmp_db: Path, event_id: str) -> None:
    resp = signal_inbox_api.log_manual_trade(
        event_id=event_id,
        ticker="AAPL",
        side="BUY",
        quantity=1.0,
        price=180.0,
        thesis="genuine thesis sentence",
    )
    assert "error" in resp
    assert "trade_id" not in resp


@pytest.mark.parametrize(
    # Test/fixture markers with no legitimate user workflow — must be
    # rejected at the POST boundary so they can never get the
    # 'manual_trade_log' provenance stamp.  paper_ledger_import is
    # intentionally NOT in this list — paper imports are a legitimate
    # non-UI workflow that the read-side classifier already filters out.
    "logged_by",
    ["seed", "demo", "smoke_test", "smoke", "mock", "fixture", "calibration_seed", "sample"],
)
def test_log_rejects_automation_logged_by(tmp_db: Path, logged_by: str) -> None:
    resp = signal_inbox_api.log_manual_trade(
        event_id="EV_OK",
        ticker="AAPL",
        side="BUY",
        quantity=1.0,
        price=180.0,
        thesis="genuine thesis sentence",
        logged_by=logged_by,
    )
    assert "error" in resp
    assert "trade_id" not in resp


def test_log_accepts_paper_ledger_import_but_read_filter_excludes(tmp_db: Path) -> None:
    """Paper-ledger CSV imports flow through log_manual_trade with
    logged_by='paper_ledger_import' — that path must remain open
    (otherwise the paper workflow breaks).  But the read-side
    user-manual filter must STILL exclude those rows so they never
    pollute the live Manual Trade Log."""
    resp = signal_inbox_api.log_manual_trade(
        event_id="EV_PAPER",
        ticker="TSLA",
        side="SELL",
        quantity=1.0,
        price=310.0,
        thesis="fade pop into prior pivot",
        logged_by="paper_ledger_import",
        trade_mode="PAPER",
    )
    assert resp.get("status") == "logged", resp
    filtered = signal_inbox_api.list_manual_trades(origin="manual_trade_log")
    paper_rows = [t for t in filtered["trades"] if t["event_id"] == "EV_PAPER"]
    # Filtered list is the live Manual Trade Log surface — paper rows are
    # excluded by is_user_manual_trade because logged_by is in
    # EXCLUDED_LOGGED_BY.
    assert paper_rows == []


def test_list_default_origin_excludes_legacy_unbranded_rows(tmp_db: Path) -> None:
    """Simulate the bug: seed/probe rows with empty created_via co-exist
    with real user rows.  ``list_manual_trades(origin='manual_trade_log')``
    must return only the user row.  This is the same predicate the GET
    route defaults to."""
    # Seed row, inserted directly through persistence — no provenance stamp.
    persistence.insert_manual_trade(
        "MT_seed_aapl",
        "EV_AAPL",
        "AAPL",
        "BUY",
        10.0,
        180.0,
        "2026-05-15T15:23:50+00:00",
        "probe",  # placeholder thesis — the leaked-row fingerprint
        "",
        "human",
        # NOTE: created_via NOT set => stays empty.
    )
    # Real user row, inserted through the API path (stamps created_via).
    user_resp = signal_inbox_api.log_manual_trade(
        event_id="EV_USER_GENUINE",
        ticker="ICICIBANK.NS",
        side="BUY",
        quantity=3.8908,
        price=40.72,
        thesis="break of pivot on bank-nifty breadth confirmation",
        ai_model_used="Claude Code",
    )
    assert user_resp["status"] == "logged"

    filtered = signal_inbox_api.list_manual_trades(origin="manual_trade_log")
    # Only the genuine user row passes the filter.
    assert filtered["trade_count"] == 1
    tickers = {t["ticker"] for t in filtered["trades"]}
    assert tickers == {"ICICIBANK.NS"}
    # And the user row carries the new field.
    assert filtered["trades"][0]["ai_model_used"] == "Claude Code"

    # Audit (origin=None) returns both rows.
    audit = signal_inbox_api.list_manual_trades(origin=None)
    assert audit["trade_count"] == 2


def test_reconcile_route_cannot_insert_manual_trade_rows(tmp_db: Path) -> None:
    """Defence in depth — calling reconcile_trade against a non-existent
    trade_id never creates a manual_trades row.  This locks the
    contract that reconciliation/source-refresh/signal paths cannot
    smuggle rows into the Manual Trade Log."""
    before = signal_inbox_api.list_manual_trades(origin=None)
    signal_inbox_api.reconcile_trade(
        "MT_never_existed",
        actual_fill_price=1.0,
        actual_quantity=1.0,
        outcome_notes="reconcile against ghost trade",
        pnl_estimate=0.0,
        outcome_status="UNKNOWN",
    )
    after = signal_inbox_api.list_manual_trades(origin=None)
    assert after["trade_count"] == before["trade_count"]
