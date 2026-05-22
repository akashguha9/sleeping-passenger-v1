"""
Tests proving Moltbook truth hygiene:

  1. log_moltbook_entry does NOT write SQLite when its JSONL path is
     monkeypatched (the historical pollution vector — only JSONL was
     isolated, the SQLite write leaked into runtime/mvp_local.db).
  2. The fake-SPY "Thesis A" cleanup script is narrowly scoped and
     idempotent, and never deletes a real user-linked entry.
  3. The mistake-type contract: original 12 categories unchanged; the
     loss-review categories are accepted only as an additive set.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import scripts.persistence as persistence
import scripts.moltbook_api as moltbook_api
import scripts.moltbook_cleanup_fake_seed as cleanup
from scripts import operator_permission_guard as _guard


def _allowed_cleanup_decision(db: Path) -> "_guard.PermissionDecision":
    """A clean OPERATOR REPAIR_WRITE allow for the function-level write guard."""
    return _guard.evaluate_permission(_guard.PermissionRequest(
        operation_name="moltbook_cleanup_fake_seed",
        operation_class=_guard.OperationClass.REPAIR_WRITE,
        operator_role=_guard.OperatorRole.OPERATOR,
        apply_requested=True,
        dry_run_completed=True,
        db_path=str(db),
        safety_stamps=_guard.caller_safety_stamps(),
    ))


def _sample_entry_kwargs(**over):
    base = dict(
        event_id="FABRIC_SPY",
        ticker="SPY",
        original_signal_thesis="Persistence above 0.8 in 3 consecutive runs",
        ai_interpretation="demo",
        user_reflection="demo",
        final_human_decision="No trade",
        mistake_type="no_trade_correct",
        lesson_learned="demo lesson",
    )
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# 1. SQLite isolation when JSONL is monkeypatched
# ---------------------------------------------------------------------------


def test_log_moltbook_entry_does_not_touch_sqlite_when_jsonl_isolated(
    tmp_path, monkeypatch
):
    # persistence.DB_PATH is already redirected to a temp file by the autouse
    # conftest fixture; point it at our own and init it so we can inspect it.
    db = tmp_path / "runtime_like.db"
    persistence.init_schema(db)
    monkeypatch.setattr(persistence, "DB_PATH", db, raising=False)
    # Monkeypatch the JSONL path → triggers the test-isolation sentinel that
    # MUST skip the canonical SQLite write.
    monkeypatch.setattr(moltbook_api, "MOLTBOOK_LOG", tmp_path / "mb.jsonl")

    result = moltbook_api.log_moltbook_entry(**_sample_entry_kwargs())
    assert result["status"] == "logged"

    # JSONL got the row (audit), SQLite did NOT (no runtime pollution).
    assert (tmp_path / "mb.jsonl").exists()
    conn = sqlite3.connect(str(db))
    try:
        n = conn.execute("SELECT COUNT(*) FROM moltbook_entries").fetchone()[0]
    finally:
        conn.close()
    assert n == 0, "log_moltbook_entry leaked a FABRIC_SPY row into SQLite"


def test_log_moltbook_entry_writes_sqlite_in_production_mode(tmp_path, monkeypatch):
    # When MOLTBOOK_LOG is the real default (not monkeypatched), the canonical
    # SQLite write happens — this is the production behaviour the bridge relies
    # on.  We isolate via persistence.DB_PATH only.
    db = tmp_path / "prod_like.db"
    persistence.init_schema(db)
    monkeypatch.setattr(persistence, "DB_PATH", db, raising=False)
    # JSONL left at its real default → sentinel passes → SQLite write occurs.
    # Use a loss-review category to also prove the widened acceptance set.
    result = moltbook_api.log_moltbook_entry(
        **_sample_entry_kwargs(event_id="USER_REAL", ticker="GLD",
                               mistake_type="manual_exit_loss")
    )
    assert result["status"] == "logged"
    rows = persistence.get_moltbook_entries(db_path=db)
    assert any(r["ticker"] == "GLD" for r in rows)


# ---------------------------------------------------------------------------
# 2. Cleanup script: narrow + idempotent + preserves real entries
# ---------------------------------------------------------------------------


def _insert_moltbook_raw(db: Path, **fields):
    cols = ", ".join(fields.keys())
    qs = ", ".join("?" for _ in fields)
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            f"INSERT INTO moltbook_entries ({cols}) VALUES ({qs})",
            tuple(fields.values()),
        )
        conn.commit()
    finally:
        conn.close()


def test_cleanup_removes_only_fake_spy_and_is_idempotent(tmp_path):
    db = tmp_path / "clean.db"
    persistence.init_schema(db)
    sig = cleanup.FAKE_SPY_SIGNATURE
    # Fake seed row (blank manual_trade_log_id) — should be deleted.
    _insert_moltbook_raw(
        db, entry_id="MB_fake", event_id="FABRIC_SPY", logged_at="t",
        manual_trade_log_id="", mistake_type="no_trade_correct", **sig,
    )
    # Real user-linked SPY row with the SAME text but a real trade link —
    # MUST be preserved (blank-id criterion protects it).
    _insert_moltbook_raw(
        db, entry_id="MB_real_linked", event_id="USER_SPY", logged_at="t",
        manual_trade_log_id="MT_real", mistake_type="no_trade_correct", **sig,
    )
    # Different ticker, same other text — MUST be preserved.
    real2 = dict(sig); real2["ticker"] = "QQQ"
    _insert_moltbook_raw(
        db, entry_id="MB_qqq", event_id="USER_QQQ", logged_at="t",
        manual_trade_log_id="", mistake_type="no_trade_correct", **real2,
    )

    rep = cleanup.cleanup(db, apply=True,
                          permission_decision=_allowed_cleanup_decision(db))
    assert rep["removed"] == 1
    remaining = {r["entry_id"] for r in persistence.get_moltbook_entries(db_path=db)}
    assert "MB_fake" not in remaining
    assert "MB_real_linked" in remaining
    assert "MB_qqq" in remaining

    # Idempotent: a second run removes nothing.
    rep2 = cleanup.cleanup(db, apply=True,
                           permission_decision=_allowed_cleanup_decision(db))
    assert rep2["removed"] == 0


def test_cleanup_dry_run_does_not_delete(tmp_path):
    db = tmp_path / "clean2.db"
    persistence.init_schema(db)
    _insert_moltbook_raw(
        db, entry_id="MB_fake", event_id="FABRIC_SPY", logged_at="t",
        manual_trade_log_id="", mistake_type="no_trade_correct",
        **cleanup.FAKE_SPY_SIGNATURE,
    )
    rep = cleanup.cleanup(db, apply=False)
    assert rep["matched"] == 1
    assert rep["removed"] == 0
    assert len(persistence.get_moltbook_entries(db_path=db)) == 1


# ---------------------------------------------------------------------------
# 3. Mistake-type contract
# ---------------------------------------------------------------------------


def test_original_12_categories_unchanged():
    assert len(moltbook_api.MISTAKE_CATEGORIES) == 12


def test_loss_review_categories_are_additive():
    assert moltbook_api.LOSS_REVIEW_CATEGORIES == frozenset(
        {"trade_loss", "manual_exit_loss", "stop_loss_breach"}
    )
    assert moltbook_api.LOSS_REVIEW_CATEGORIES.isdisjoint(moltbook_api.MISTAKE_CATEGORIES)
    assert moltbook_api.ACCEPTED_MISTAKE_TYPES == (
        moltbook_api.MISTAKE_CATEGORIES | moltbook_api.LOSS_REVIEW_CATEGORIES
    )


def test_invalid_mistake_type_still_rejected():
    result = moltbook_api.log_moltbook_entry(
        **_sample_entry_kwargs(mistake_type="auto_execute")
    )
    assert "error" in result
    assert result["ai_execution_count"] == 0
