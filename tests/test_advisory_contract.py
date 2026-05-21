"""Shared advisory contract — one safety stamp, no inconsistent duplicates.

Kanté "tactical discipline": every active diagnostic / persistence module
draws its safety vocabulary from one shared contract, the diagnostics layer
stays pure, persistence modules never import the frontend, and nothing imports
a broker execution library.
"""
from __future__ import annotations

import pathlib

from scripts import advisory_contract as contract
from scripts import complex_systems_diagnostics as csd
from scripts import signal_geometry_persistence as sgp
from scripts import moltbook_reconciliation_bridge as bridge
from scripts import reconciliation_queue as rq

_ACTIVE_MODULES = (contract, csd, sgp, bridge, rq)


def _src(mod) -> str:
    return pathlib.Path(mod.__file__).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Canonical stamp + truth model
# ---------------------------------------------------------------------------


def test_canonical_stamp_shape():
    stamp = contract.advisory_safety_stamps()
    assert stamp["advisory_status"] == "ADVISORY_ONLY"
    assert stamp["execution_gate"] == "LOCKED"
    assert stamp["execution_permission"] is False
    assert stamp["can_execute"] is False
    assert stamp["broker_api_called"] is False
    assert stamp["broker_order_id"] == "NONE"
    assert stamp["ai_execution_count"] == 0
    assert stamp["human_review_required"] is True


def test_truth_model_sqlite_canonical_jsonl_audit_only():
    truth = contract.canonical_truth_declaration()
    assert truth["sqlite_is_canonical"] is True
    assert truth["jsonl_is_canonical"] is False


def test_safe_degradation_states_are_not_execution():
    for state in contract.SAFE_DEGRADATION_STATES:
        assert contract.is_safe_degradation(state) is True
    for bad in ("BUY", "SELL", "EXECUTE", "PLACE_ORDER"):
        assert contract.is_safe_degradation(bad) is False


# ---------------------------------------------------------------------------
# Active modules use the shared stamp (no duplicated inconsistent stamp)
# ---------------------------------------------------------------------------


def test_active_modules_import_shared_contract():
    for mod in (csd, sgp, bridge, rq):
        assert "advisory_contract" in _src(mod), mod.__name__


def test_complex_systems_uses_canonical_stamp():
    assert csd.SAFETY_STAMPS == contract.advisory_safety_stamps()


def test_reconciliation_queue_stamp_consistent_with_contract():
    canonical = contract.advisory_safety_stamps()
    for key in ("advisory_status", "execution_gate", "broker_api_called",
                "ai_execution_count", "execution_permission", "can_execute"):
        assert rq._SAFETY_STAMPS[key] == canonical[key], key


def test_signal_geometry_persistence_declares_sqlite_canonical():
    out = sgp.persist_signal_geometry({"ticker": "AAPL", "thesis": "t"})
    # conftest isolates DB_PATH to a temp file, so this write is throwaway.
    assert out["canonical_source"] == contract.CANONICAL_STORE
    assert out["human_review_required"] is True


def test_moltbook_bridge_report_stamps_match_contract(tmp_path):
    import scripts.persistence as persistence
    db = tmp_path / "bridge.db"
    persistence.init_schema(db)
    report = bridge.sync_reconciliation_losses_to_moltbook(db, write=False)
    assert report["advisory_status"] == contract.ADVISORY_STATUS
    assert report["execution_gate"] == contract.EXECUTION_GATE_LOCKED
    assert report["execution_mode"] == contract.EXECUTION_MODE_HUMAN_ONLY
    assert report["ai_execution_count"] == contract.AI_EXECUTION_COUNT


# ---------------------------------------------------------------------------
# Purity / boundary invariants
# ---------------------------------------------------------------------------


def test_diagnostics_module_stays_pure():
    """complex_systems_diagnostics is a pure diagnostic layer: no DB, no
    filesystem, no network."""
    src = _src(csd)
    for forbidden in ("import sqlite3", "scripts.persistence", "import urllib",
                      "import requests", "open("):
        assert forbidden not in src, forbidden


def test_contract_module_is_pure():
    src = _src(contract)
    for forbidden in ("import sqlite3", "import urllib", "import requests",
                      "import socket", "open("):
        assert forbidden not in src, forbidden


def test_persistence_modules_do_not_import_frontend():
    for mod in (sgp, bridge, rq):
        assert "frontend" not in _src(mod).lower(), mod.__name__


def test_no_broker_execution_imports():
    for mod in _ACTIVE_MODULES:
        lowered = _src(mod).lower()
        for forbidden in ("import alpaca", "import ib_insync", "import ccxt",
                          "place_order(", "submit_order(", "execute_trade("):
            assert forbidden not in lowered, (mod.__name__, forbidden)
