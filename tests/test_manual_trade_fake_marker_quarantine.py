"""Locks in the stricter fake-marker contract for Manual Trade Log.

Background — the leaked-AAPL incident (2026-05-18) showed that the
``origin=manual_trade_log`` filter alone is insufficient: a fabricated
row stamped with that provenance and a placeholder thesis like
``"no currency given"`` survived the first round of fixes because the
classifier only checked exact-match thesis strings.

These tests pin the layered rules now enforced by
``scripts.manual_trade_origin.fake_manual_trade_reason`` and the
quarantine cleanup at ``scripts/quarantine_fake_manual_trades.py``:

* The exact visible row (``MT_6b11745fc3f3``) is excluded.
* ``EV_AAPL`` prefix is excluded.
* ``AAPL / 180 / qty 10 / "...probe..."`` is excluded.
* ``origin=manual_trade_log`` alone is NOT enough to be visible.
* Quarantine dry-run finds the row; ``--yes`` re-stamps without deleting.
* A genuine manual trade still appears.
* Future POSTs with ``"no currency given"`` or ``EV_AAPL`` are rejected
  with reason ``rejected_non_user_manual_trade_marker``.
* ``ai_model_used`` field still round-trips.
* Advisory-only safety invariants are unchanged.

No broker calls.  No execution.  Read-only assertions only.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts import persistence
from scripts import signal_inbox_api
from scripts.manual_trade_origin import (
    QUARANTINE_PROVENANCE,
    REJECT_REASON_NON_USER_MARKER,
    fake_manual_trade_reason,
    is_fake_manual_trade_row,
    is_visible_manual_trade,
)
from scripts.quarantine_fake_manual_trades import (
    apply_quarantine,
    find_candidates,
    main as quarantine_main,
)


def _rebind_defaults(fn, new_db: Path) -> None:
    """Replace ``db_path=DB_PATH`` defaults on a persistence helper so
    direct calls fall through to ``new_db``.  Mirrors the pattern from
    tests/test_manual_trade_ai_model_used.py.
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
    db = tmp_path / "fake_marker.db"
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


# ---------------------------------------------------------------------------
# Classifier-level rules — pure, no DB.
# ---------------------------------------------------------------------------


def test_specific_trade_id_is_fake():
    row = {
        "trade_id": "MT_6b11745fc3f3",
        "event_id": "EVT_NO_CUR",
        "ticker": "AAPL",
        "side": "BUY",
        "quantity": 5.0,
        "price": 180.0,
        "thesis": "no currency given",
        "logged_by": "human",
        "created_via": "manual_trade_log",
        "ai_model_used": "",
    }
    assert is_fake_manual_trade_row(row)
    assert fake_manual_trade_reason(row) == "fake_trade_id_blocklist"
    assert not is_visible_manual_trade(row)


def test_aapl_180_qty10_probe_is_fake():
    """``AAPL / 180 / qty 10 / "probe"`` is excluded even when stamped
    manual_trade_log."""
    row = {
        "trade_id": "MT_unknown",
        "event_id": "EV_AAPL",
        "ticker": "AAPL",
        "side": "BUY",
        "quantity": 10.0,
        "price": 180.0,
        "thesis": "probe",
        "logged_by": "human",
        "created_via": "manual_trade_log",
    }
    assert is_fake_manual_trade_row(row)
    # First hit wins — AAPL fingerprint is checked before event_id prefix.
    assert fake_manual_trade_reason(row) == "fake_aapl_fingerprint"


def test_ev_aapl_event_id_prefix_is_fake():
    """``event_id`` starting with ``EV_AAPL`` is excluded even with
    plausible thesis."""
    row = {
        "trade_id": "MT_anything",
        "event_id": "EV_AAPL_FOLLOWUP",
        "ticker": "MSFT",  # not AAPL → not caught by fingerprint
        "side": "BUY",
        "quantity": 1.0,
        "price": 421.0,
        "thesis": "real reasoning here",
        "logged_by": "human",
        "created_via": "manual_trade_log",
    }
    assert is_fake_manual_trade_row(row)
    assert fake_manual_trade_reason(row) == "fake_event_id_prefix"


def test_no_currency_given_thesis_is_fake():
    """``thesis="no currency given"`` is excluded — the leaked row."""
    row = {
        "trade_id": "MT_other",
        "event_id": "EVT_NORMAL",
        "ticker": "MSFT",
        "side": "BUY",
        "quantity": 1.0,
        "price": 421.0,
        "thesis": "no currency given",
        "logged_by": "human",
        "created_via": "manual_trade_log",
    }
    reason = fake_manual_trade_reason(row)
    assert reason and reason.startswith("fake_thesis_marker:")


def test_origin_alone_is_not_enough():
    """A row stamped ``created_via=manual_trade_log`` that nonetheless
    matches a fake-marker rule is NOT visible.  This is the contract
    the first-round origin-filter fix violated."""
    row = {
        "trade_id": "MT_6b11745fc3f3",  # known fake trade_id
        "ticker": "AAPL",
        "side": "BUY",
        "quantity": 5.0,
        "price": 180.0,
        "thesis": "no currency given",
        "created_via": "manual_trade_log",  # passed origin filter
        "trade_mode": "REAL_MANUAL",
        "logged_by": "human",
        "broker_api_called": 0,
        "ai_execution_count": 0,
    }
    # Canonical classifier reads this as USER_MANUAL — origin alone passes.
    from scripts.manual_trade_origin import is_user_manual_trade

    assert is_user_manual_trade(row) is True
    # But visibility veto kicks in.
    assert is_visible_manual_trade(row) is False


def test_genuine_user_trade_is_visible():
    row = {
        "trade_id": "MT_real_123",
        "event_id": "EV_USER_GENUINE",
        "ticker": "ICICIBANK.NS",
        "side": "BUY",
        "quantity": 3.8908,
        "price": 40.72,
        "thesis": "break of pivot on bank-nifty breadth confirmation",
        "logged_by": "human",
        "created_via": "manual_trade_log",
        "trade_mode": "REAL_MANUAL",
        "broker_api_called": 0,
        "ai_execution_count": 0,
        "ai_model_used": "Claude Code",
    }
    assert is_fake_manual_trade_row(row) is False
    assert fake_manual_trade_reason(row) == ""
    assert is_visible_manual_trade(row) is True


def test_empty_ai_model_with_marker_thesis_is_fake():
    row = {
        "trade_id": "MT_xyz",
        "event_id": "EV_LEGIT",
        "ticker": "MSFT",
        "side": "BUY",
        "quantity": 1.0,
        "price": 421.0,
        "thesis": "smoke run reasoning",  # contains marker substring
        "ai_model_used": "",
        "created_via": "manual_trade_log",
    }
    assert is_fake_manual_trade_row(row)


# ---------------------------------------------------------------------------
# Read-path integration — DB-backed.
# ---------------------------------------------------------------------------


def test_list_manual_trades_excludes_fake_aapl_visible_row(tmp_db: Path) -> None:
    """Plant the exact visible row from the operator's screenshot — it
    must NOT come back from ``list_manual_trades(origin='manual_trade_log')``."""
    persistence.insert_manual_trade(
        "MT_6b11745fc3f3",
        "EVT_NO_CUR",
        "AAPL",
        "BUY",
        5.0,
        180.0,
        "2026-05-16T07:51:44+00:00",
        "no currency given",
        "",
        "human",
        created_via="manual_trade_log",
    )
    # Genuine row alongside.
    user_resp = signal_inbox_api.log_manual_trade(
        event_id="EV_USER_GENUINE_X",
        ticker="ICICIBANK.NS",
        side="BUY",
        quantity=3.8908,
        price=40.72,
        thesis="break of pivot on bank-nifty breadth confirmation",
        ai_model_used="Claude Code",
    )
    assert user_resp["status"] == "logged"

    filtered = signal_inbox_api.list_manual_trades(origin="manual_trade_log")
    trade_ids = {t["trade_id"] for t in filtered["trades"]}
    assert "MT_6b11745fc3f3" not in trade_ids
    assert any(t["event_id"] == "EV_USER_GENUINE_X" for t in filtered["trades"])

    # Audit scope (origin=None) still returns the fake row for forensics.
    audit = signal_inbox_api.list_manual_trades(origin=None)
    audit_ids = {t["trade_id"] for t in audit["trades"]}
    assert "MT_6b11745fc3f3" in audit_ids


def test_list_manual_trades_excludes_ev_aapl_prefix(tmp_db: Path) -> None:
    persistence.insert_manual_trade(
        "MT_ev_aapl_test",
        "EV_AAPL_FOLLOWUP",
        "MSFT",
        "BUY",
        1.0,
        421.0,
        "2026-05-16T08:00:00+00:00",
        "follow-up reasoning paragraph",
        "",
        "human",
        created_via="manual_trade_log",
    )
    filtered = signal_inbox_api.list_manual_trades(origin="manual_trade_log")
    trade_ids = {t["trade_id"] for t in filtered["trades"]}
    assert "MT_ev_aapl_test" not in trade_ids


def test_list_manual_trades_excludes_aapl_180_qty10_probe(tmp_db: Path) -> None:
    persistence.insert_manual_trade(
        "MT_aapl_qty10",
        "EVT_PLAUSIBLE",
        "AAPL",
        "BUY",
        10.0,
        180.0,
        "2026-05-16T09:00:00+00:00",
        "probe",
        "",
        "human",
        created_via="manual_trade_log",
    )
    filtered = signal_inbox_api.list_manual_trades(origin="manual_trade_log")
    trade_ids = {t["trade_id"] for t in filtered["trades"]}
    assert "MT_aapl_qty10" not in trade_ids


# ---------------------------------------------------------------------------
# POST guard — backend prevention.
# ---------------------------------------------------------------------------


def test_post_rejects_no_currency_given_thesis(tmp_db: Path) -> None:
    """``thesis="no currency given"`` is rejected before insert."""
    resp = signal_inbox_api.log_manual_trade(
        event_id="EVT_NEW",
        ticker="MSFT",
        side="BUY",
        quantity=1.0,
        price=421.0,
        thesis="no currency given",
    )
    assert "error" in resp
    assert resp.get("reason") == REJECT_REASON_NON_USER_MARKER
    assert "trade_id" not in resp
    # And no row ended up in the DB.
    listing = signal_inbox_api.list_manual_trades(origin=None)
    assert listing["trade_count"] == 0


def test_post_rejects_ev_aapl_event_id_prefix(tmp_db: Path) -> None:
    resp = signal_inbox_api.log_manual_trade(
        event_id="EV_AAPL_FOLLOWUP",
        ticker="MSFT",
        side="BUY",
        quantity=1.0,
        price=421.0,
        thesis="reasonable reasoning sentence about the setup",
    )
    assert "error" in resp
    assert resp.get("reason") == REJECT_REASON_NON_USER_MARKER


def test_post_rejects_aapl_fingerprint(tmp_db: Path) -> None:
    """AAPL/$180/qty 5 with plausible thesis is rejected before insert."""
    resp = signal_inbox_api.log_manual_trade(
        event_id="EVT_OK",
        ticker="AAPL",
        side="BUY",
        quantity=5.0,
        price=180.0,
        thesis="reasonable reasoning sentence about the setup",
    )
    assert "error" in resp
    assert resp.get("reason") == REJECT_REASON_NON_USER_MARKER


# ---------------------------------------------------------------------------
# Quarantine script.
# ---------------------------------------------------------------------------


def _plant_fake_row(db: Path, trade_id: str, thesis: str, *, event_id="EVT_X",
                    ticker="AAPL", qty=5.0, price=180.0) -> None:
    persistence.insert_manual_trade(
        trade_id,
        event_id,
        ticker,
        "BUY",
        qty,
        price,
        "2026-05-16T07:51:44+00:00",
        thesis,
        "",
        "human",
        created_via="manual_trade_log",
    )


def _plant_real_row(db: Path) -> None:
    resp = signal_inbox_api.log_manual_trade(
        event_id="EV_USER_REAL_X",
        ticker="ICICIBANK.NS",
        side="BUY",
        quantity=3.8908,
        price=40.72,
        thesis="break of pivot on bank-nifty breadth confirmation",
        ai_model_used="Claude Code",
    )
    assert resp["status"] == "logged"


def test_quarantine_dry_run_finds_fake_aapl_row(tmp_db: Path) -> None:
    _plant_fake_row(tmp_db, "MT_6b11745fc3f3", "no currency given")
    _plant_real_row(tmp_db)
    candidates = find_candidates(tmp_db)
    trade_ids = {c.trade_id for c in candidates}
    assert "MT_6b11745fc3f3" in trade_ids
    # Real row not flagged.
    assert all(c.trade_id != "MT_real" for c in candidates)


def test_quarantine_apply_yes_hides_row_without_deleting(tmp_db: Path) -> None:
    _plant_fake_row(tmp_db, "MT_6b11745fc3f3", "no currency given")
    _plant_real_row(tmp_db)

    # Before: visible in audit list as manual_trade_log row.
    pre_audit = signal_inbox_api.list_manual_trades(origin=None)
    pre_audit_ids = {t["trade_id"] for t in pre_audit["trades"]}
    assert "MT_6b11745fc3f3" in pre_audit_ids

    candidates = find_candidates(tmp_db)
    updated = apply_quarantine(tmp_db, candidates)
    assert updated >= 1

    # After: row STILL exists in DB (no deletes) but provenance changed.
    conn = sqlite3.connect(str(tmp_db))
    try:
        row = conn.execute(
            "SELECT trade_id, created_via FROM manual_trades WHERE trade_id=?",
            ("MT_6b11745fc3f3",),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, "Row was deleted — quarantine script must not delete."
    assert row[1] == QUARANTINE_PROVENANCE

    # Manual Trade Log GET filter no longer surfaces it.
    listing = signal_inbox_api.list_manual_trades(origin="manual_trade_log")
    listing_ids = {t["trade_id"] for t in listing["trades"]}
    assert "MT_6b11745fc3f3" not in listing_ids
    # Genuine row still visible.
    assert any(t["event_id"] == "EV_USER_REAL_X" for t in listing["trades"])


def test_quarantine_main_default_is_dry_run(tmp_db: Path, capsys) -> None:
    _plant_fake_row(tmp_db, "MT_6b11745fc3f3", "no currency given")
    rc = quarantine_main(["--db", str(tmp_db)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    # Provenance NOT changed.
    conn = sqlite3.connect(str(tmp_db))
    try:
        row = conn.execute(
            "SELECT created_via FROM manual_trades WHERE trade_id=?",
            ("MT_6b11745fc3f3",),
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == "manual_trade_log"  # untouched


def test_quarantine_main_yes_applies(tmp_db: Path) -> None:
    _plant_fake_row(tmp_db, "MT_6b11745fc3f3", "no currency given")
    _plant_real_row(tmp_db)
    rc = quarantine_main(["--db", str(tmp_db), "--yes"])
    assert rc == 0
    # Fake row re-stamped.
    conn = sqlite3.connect(str(tmp_db))
    try:
        fake_row = conn.execute(
            "SELECT created_via FROM manual_trades WHERE trade_id=?",
            ("MT_6b11745fc3f3",),
        ).fetchone()
        real_row = conn.execute(
            "SELECT created_via FROM manual_trades WHERE event_id=?",
            ("EV_USER_REAL_X",),
        ).fetchone()
    finally:
        conn.close()
    assert fake_row[0] == QUARANTINE_PROVENANCE
    # Genuine row's provenance NEVER touched.
    assert real_row[0] == "manual_trade_log"


def test_quarantine_does_not_touch_genuine_rows(tmp_db: Path) -> None:
    """Plant only genuine rows — quarantine must find zero candidates
    and must not modify any provenance."""
    _plant_real_row(tmp_db)
    # Another genuine row with a different thesis.
    resp = signal_inbox_api.log_manual_trade(
        event_id="EV_ANET_REAL",
        ticker="ANET",
        side="BUY",
        quantity=1.0,
        price=141.97,
        thesis="break of structure on increasing volume",
        ai_model_used="Claude Code",
    )
    assert resp["status"] == "logged"
    candidates = find_candidates(tmp_db)
    assert candidates == []
    updated = apply_quarantine(tmp_db, candidates)
    assert updated == 0


# ---------------------------------------------------------------------------
# Pre-existing contracts still hold.
# ---------------------------------------------------------------------------


def test_ai_model_used_field_round_trips(tmp_db: Path) -> None:
    """Regression — ai_model_used must still flow through after the
    fake-marker layer was added."""
    resp = signal_inbox_api.log_manual_trade(
        event_id="EV_ANET_AI",
        ticker="ANET",
        side="BUY",
        quantity=1.0,
        price=141.97,
        thesis="break of structure on increasing volume",
        ai_model_used="Claude Code",
    )
    assert resp["status"] == "logged"
    assert resp["ai_model_used"] == "Claude Code"
    listing = signal_inbox_api.list_manual_trades(origin="manual_trade_log")
    rows = [t for t in listing["trades"] if t["event_id"] == "EV_ANET_AI"]
    assert len(rows) == 1
    assert rows[0]["ai_model_used"] == "Claude Code"


def test_advisory_safety_invariants_unchanged_on_accept(tmp_db: Path) -> None:
    resp = signal_inbox_api.log_manual_trade(
        event_id="EV_SAFETY",
        ticker="MSFT",
        side="BUY",
        quantity=1.0,
        price=421.0,
        thesis="real reasoning paragraph here",
    )
    assert resp["status"] == "logged"
    assert resp["advisory_status"] == "ADVISORY_ONLY"
    assert resp["execution_mode"] == "HUMAN_ONLY"
    assert resp["ai_execution_count"] == 0
    assert resp["broker_api_called"] is False
    assert resp["broker_order_id"] == "NONE"
    assert resp["execution_gate"] == "LOCKED"
    assert resp["execution_permission"] is False
    assert resp["can_execute"] is False


def test_advisory_safety_invariants_unchanged_on_reject(tmp_db: Path) -> None:
    """The rejection path must STILL preserve the safety stamps — the
    operator's downstream UI pattern-matches on them."""
    resp = signal_inbox_api.log_manual_trade(
        event_id="EV_REJ",
        ticker="MSFT",
        side="BUY",
        quantity=1.0,
        price=421.0,
        thesis="no currency given",  # marker → rejected
    )
    assert "error" in resp
    assert resp.get("reason") == REJECT_REASON_NON_USER_MARKER
    assert resp["advisory_status"] == "ADVISORY_ONLY"
    assert resp["execution_mode"] == "HUMAN_ONLY"
    assert resp["ai_execution_count"] == 0
