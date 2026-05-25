"""Canonical SQLite reactor bridge (Kanté Sprint 2 — Task 2).

Proves the complex-systems / reactor layer is fed from canonical SQLite truth,
degrades honestly when tables are missing, never reintroduces fake pollution,
and never emits an execution instruction.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from scripts import persistence
from scripts import complex_systems_sqlite_bridge as csb
from scripts import reactor_canonical_inputs as rci

_FORBIDDEN = ("place_order", "submit_order", "execute_trade", "auto_trade",
              "buy now", "broker_execute")


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "mvp_local.db"
    persistence.init_schema(path)
    return path


def _add_trade(db, trade_id, *, ticker="AAPL", invalidation="below 100"):
    persistence.insert_manual_trade(
        trade_id, f"EV_{trade_id}", ticker, "BUY", 10.0, 150.0,
        "2026-05-20T00:00:00+00:00", "thesis", "notes", "human",
        db_path=db, created_via="manual_trade_log", invalidation_level=invalidation,
    )


def _close_loss(db, trade_id):
    persistence.insert_reconciliation(
        f"REC_{trade_id}", trade_id, f"EV_{trade_id}",
        "2026-05-21T00:00:00+00:00", 140.0, 10.0, "closed at a loss",
        -100.0, "CLOSED_LOSS", db_path=db,
    )


def _repair(db, trade_id, ticker="AAPL"):
    persistence.insert_moltbook_entry(
        f"MB_{trade_id}", f"EV_{trade_id}", ticker, "thesis", "ai", "reflect",
        "exit", trade_id, "loss", "trade_loss", "review sizing", "", "", "",
        "2026-05-21T00:00:00+00:00", db_path=db,
    )


# ---------------------------------------------------------------------------
# Canonical reads
# ---------------------------------------------------------------------------


def test_bridge_reads_duplicate_fingerprints(db):
    persistence.upsert_duplicate_fingerprint("fp-unique", ticker="AAPL", db_path=db)
    state = csb.build_canonical_complex_systems_state(db)
    fp = state["components"]["fingerprint_independence"]
    assert fp["available"] is True
    assert fp["distinct_fingerprints"] == 1


def test_bridge_reads_signal_cell_index(db):
    persistence.upsert_signal_cell("cell-1", sector="TECH", db_path=db)
    state = csb.build_canonical_complex_systems_state(db)
    cell = state["components"]["signal_cell_diffusion"]
    assert cell["available"] is True
    assert cell["unique_cells"] == 1


def test_missing_tables_degrade_safely(tmp_path):
    # A real SQLite file with NO tables → every component degrades, no mock.
    empty = tmp_path / "empty.db"
    sqlite3.connect(str(empty)).close()
    state = csb.build_canonical_complex_systems_state(empty)
    assert state["db_available"] is True
    assert state["state"] == "INSUFFICIENT_DATA"
    for comp in state["components"].values():
        assert comp["available"] is False


def test_missing_db_degrades_without_mock(tmp_path):
    state = csb.build_canonical_complex_systems_state(tmp_path / "nope.db")
    assert state["db_available"] is False
    assert state["state"] == "INSUFFICIENT_DATA"
    assert state["data_origin"] == "canonical_sqlite"


# ---------------------------------------------------------------------------
# Echo / independence
# ---------------------------------------------------------------------------


def test_source_independence_lowers_when_fingerprints_repeat(db):
    # Same fingerprint seen 3x → echoes dominate → independence collapses.
    for _ in range(3):
        persistence.upsert_duplicate_fingerprint("fp-echo", ticker="AAPL", db_path=db)
    state = csb.build_canonical_complex_systems_state(db)
    fp = state["components"]["fingerprint_independence"]
    assert fp["repeated_mentions"] == 2
    assert fp["echo_risk"] > 0.5
    assert fp["independence_score"] < 0.5


# ---------------------------------------------------------------------------
# Moltbook repair / unrepaired-loss debt
# ---------------------------------------------------------------------------


def test_closed_loss_without_moltbook_is_hard_warning(db):
    _add_trade(db, "T1")
    _close_loss(db, "T1")
    state = csb.build_canonical_complex_systems_state(db)
    repair = state["components"]["moltbook_repair"]
    assert repair["closed_losses"] == 1
    assert repair["closed_losses_without_moltbook"] == 1
    assert repair["promotion_block_if_unrepaired"] is True
    # The broken-windows bridge re-asserts the block.
    assert state["broken_windows"]["promotion_block_if_unrepaired"] is True


def test_repaired_loss_reduces_unrepaired_debt(db):
    _add_trade(db, "T1")
    _close_loss(db, "T1")
    before = csb.moltbook_repair_state(_conn(db))["unrepaired_loss_debt"]
    _repair(db, "T1")
    after = csb.moltbook_repair_state(_conn(db))["unrepaired_loss_debt"]
    assert after < before
    assert after == 0.0


def _conn(db):
    c = sqlite3.connect(str(db))
    c.row_factory = sqlite3.Row
    return c


# ---------------------------------------------------------------------------
# Reactor canonical inputs
# ---------------------------------------------------------------------------


def test_reactor_output_includes_canonical_summary(db):
    persistence.upsert_duplicate_fingerprint("fp-1", ticker="AAPL", db_path=db)
    _add_trade(db, "T1")
    _close_loss(db, "T1")
    _repair(db, "T1")
    inputs = rci.build_reactor_canonical_inputs(db)
    assert inputs["data_origin"] == "canonical_sqlite"
    assert "complex_system_summary" in inputs
    assert inputs["complex_system_summary"]["report"] == "complex_systems_sqlite_bridge"
    assert isinstance(inputs["routing_score"], float)


def test_reactor_routing_readiness_insufficient_on_empty_db(tmp_path):
    empty = tmp_path / "empty.db"
    sqlite3.connect(str(empty)).close()
    inputs = rci.build_reactor_canonical_inputs(empty)
    assert inputs["routing_readiness"] == "INSUFFICIENT_DATA"


def test_attach_canonical_diagnostics_preserves_safety(db):
    merged = rci.attach_canonical_diagnostics({"reactor_state": "WAIT"}, db)
    assert merged["reactor_state"] == "WAIT"
    assert merged["canonical_inputs"]["data_origin"] == "canonical_sqlite"
    assert merged["execution_gate"] == "LOCKED"
    assert merged["broker_api_called"] is False
    assert merged["ai_execution_count"] == 0


def test_no_execution_language_in_outputs(db):
    persistence.upsert_signal_cell("cell-1", sector="TECH", db_path=db)
    blob = json.dumps(rci.build_reactor_canonical_inputs(db)).lower()
    for token in _FORBIDDEN:
        assert token not in blob


def test_bridge_is_read_only_no_pollution(db):
    before = len(persistence.get_moltbook_entries(db_path=db))
    csb.build_canonical_complex_systems_state(db)
    rci.build_reactor_canonical_inputs(db)
    after = len(persistence.get_moltbook_entries(db_path=db))
    assert before == after == 0
