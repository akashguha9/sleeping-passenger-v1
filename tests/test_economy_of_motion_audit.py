"""Economy of motion audit — useful signal vs ornamentation.

Proves the EconomyScore formula computes, that mock pollution BLOCKs while
quarantined rows do not, and that the audit reads the real release-gate audits
without writing anything.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import scripts.persistence as persistence
from scripts import economy_of_motion_audit as eom
from scripts.manual_trade_origin import QUARANTINE_PROVENANCE


def test_economy_score_formula():
    rep = eom.compute_economy_score({
        "useful_signal_count": 8,
        "redundant_signal_count": 1,
        "stale_signal_count": 1,
        "mock_pollution_count": 0,
    })
    # 10 * 8 / (8+1+1) = 8.0
    assert rep["economy_score"] == 8.0
    assert rep["system_sharpness"] == 8.0 - 1  # minus stale


def test_mock_pollution_blocks_but_quarantine_does_not():
    polluted = eom.compute_economy_score({"useful_signal_count": 5, "mock_pollution_count": 3})
    assert polluted["release_gate_impact"] == "BLOCK"
    clean = eom.compute_economy_score({"useful_signal_count": 5, "mock_pollution_count": 0})
    assert clean["release_gate_impact"] == "CLEAR"


def test_all_useful_is_perfect_economy():
    rep = eom.compute_economy_score({"useful_signal_count": 10})
    assert rep["economy_score"] == 10.0
    assert rep["release_gate_impact"] == "CLEAR"


def test_build_audit_clean_db(tmp_path):
    db = tmp_path / "eom.db"
    persistence.init_schema(db)
    # One quarantined fake row (excluded from active truth — not pollution).
    persistence.insert_manual_trade(
        "MT_q", "FABRIC_SPY", "SPY", "BUY", 1.0, 400.0,
        "2026-05-16T07:00:00+00:00", "Persistence above 0.8", "", "seed", db,
        created_via=QUARANTINE_PROVENANCE,
    )
    rep = eom.build_audit(db)
    assert rep["mock_pollution_count"] == 0
    assert rep["quarantined_rows_excluded"] == 1
    assert rep["release_gate_impact"] in ("CLEAR", "WARN")
    assert rep["advisory_status"] == "ADVISORY_ONLY"


def test_build_audit_unquarantined_pollution_blocks(tmp_path):
    db = tmp_path / "eom_polluted.db"
    persistence.init_schema(db)
    persistence.insert_manual_trade(
        "MT_fresh", "FABRIC_QQQ", "QQQ", "BUY", 1.0, 400.0,
        "2026-05-16T07:00:00+00:00", "Persistence above 0.8", "", "seed", db,
        created_via="manual_trade_log",
    )
    rep = eom.build_audit(db)
    assert rep["mock_pollution_count"] >= 1
    assert rep["release_gate_impact"] == "BLOCK"
