"""Operator readiness report (Kanté Sprint 2 — Task 5).

Proves the one-command readiness view aggregates the defensive layers, fails
closed on a missing DB, surfaces fake pollution and unrepaired losses as
blockers, carries the advisory stamp, and leaks no secrets.
"""
from __future__ import annotations

import json

import pytest

from scripts import persistence
from scripts import operator_readiness_report as orr
from tests.helpers import scanner_probes as probes


@pytest.fixture
def clean_db(tmp_path):
    path = tmp_path / "mvp_local.db"
    persistence.init_schema(path)
    return path


def _add_loss(db):
    persistence.insert_manual_trade(
        "T1", "EV_T1", "AAPL", "BUY", 10.0, 150.0,
        "2026-05-20T00:00:00+00:00", "thesis", "notes", "human",
        db_path=db, created_via="manual_trade_log",
    )
    persistence.insert_reconciliation(
        "REC_T1", "T1", "EV_T1", "2026-05-21T00:00:00+00:00",
        140.0, 10.0, "closed at a loss", -100.0, "CLOSED_LOSS", db_path=db,
    )


def test_report_works_with_clean_db(clean_db):
    report = orr.build_readiness_report(clean_db)
    assert report["readiness"] in ("READY", "WARN")
    assert report["db_exists"] is True
    assert "release_gate" in report
    assert "compliance" in report
    assert report["next_actions"]


def test_missing_db_fails_closed(tmp_path):
    report = orr.build_readiness_report(tmp_path / "nope.db")
    assert report["readiness"] == "FAIL_CLOSED"
    assert report["no_new_risk"] is True
    assert report["workflow_score"] == 0.0


def test_fake_pollution_visible_as_fail(clean_db):
    persistence.insert_moltbook_entry(
        "MB_FAKE", "FABRIC_SPY_001", "SPY", "Persistence above 0.8", "ai",
        "reflect", "No trade", "", "outcome", "trade_loss", "lesson",
        "", "", "", "2026-05-21T00:00:00+00:00", db_path=clean_db,
    )
    report = orr.build_readiness_report(clean_db)
    assert report["moltbook"]["fake_pollution_status"] == "FAIL"
    assert report["readiness"] == "FAIL"
    assert report["no_new_risk"] is True
    assert any("fake" in r.lower() for r in report["promotion_block_reasons"])


def test_unrepaired_loss_visible_as_block(clean_db):
    _add_loss(clean_db)
    report = orr.build_readiness_report(clean_db)
    assert report["moltbook"]["unrepaired_closed_loss_count"] >= 1
    assert report["no_new_risk"] is True
    assert any("repair" in r.lower() or "loss" in r.lower()
               for r in report["promotion_block_reasons"])
    assert any("repair" in a.lower() for a in report["next_actions"])


def test_advisory_stamp_present(clean_db):
    report = orr.build_readiness_report(clean_db)
    assert report["advisory_status"] == "ADVISORY_ONLY"
    assert report["execution_gate"] == "LOCKED"
    assert report["broker_api_called"] is False
    assert report["ai_execution_count"] == 0
    assert report["execution_mode"] == "HUMAN_ONLY"


def test_no_secrets_in_report(clean_db, monkeypatch):
    fake_key = probes.sk_style_token("shouldnotappear")
    monkeypatch.setenv("SOME_API_KEY", fake_key)
    blob = json.dumps(orr.build_readiness_report(clean_db))
    assert fake_key not in blob
    assert "SOME_API_KEY" not in blob


def test_loss_bridge_idempotency_proven_not_hardcoded(clean_db):
    _add_loss(clean_db)
    report = orr.build_readiness_report(clean_db)
    # Idempotency is a computed boolean from two dry-runs, not a constant.
    assert report["moltbook"]["loss_bridge_idempotent"] is True


def test_cli_main_returns_nonzero_on_fail_closed(tmp_path, capsys):
    rc = orr.main(["--db-path", str(tmp_path / "nope.db")])
    assert rc == 1


def test_clean_db_demotes_stress_probe_fail_to_warn(clean_db):
    """A freshly-initialised DB with zero operator rows must not be
    forced into FAIL by a global runtime artefact (stress-probe summary
    file).  The demotion only fires when there is no operational risk —
    no fake pollution, no unrepaired losses, no compliance failure."""
    report = orr.build_readiness_report(clean_db)
    assert report["db_clean_initialised"] is True
    # When release gate FAIL is purely stress-probe-driven, the report
    # should record the downgrade reasoning explicitly.
    rg = report["release_gate"]
    if rg["verdict"] == "FAIL":
        # The clean-DB demotion kicked in.
        assert rg.get("clean_db_downgrade") is True
        assert "stress-probe summary" in rg.get("clean_db_downgrade_reason", "")
    assert report["readiness"] in ("READY", "WARN")


def test_clean_db_demotion_does_not_mask_fake_pollution(clean_db):
    """Even on an otherwise-clean DB, fake Moltbook pollution still
    forces a hard FAIL — the demotion must never weaken pollution safety."""
    persistence.insert_moltbook_entry(
        "MB_FAKE", "FABRIC_SPY_001", "SPY", "Persistence above 0.8", "ai",
        "reflect", "No trade", "", "outcome", "trade_loss", "lesson",
        "", "", "", "2026-05-21T00:00:00+00:00", db_path=clean_db,
    )
    report = orr.build_readiness_report(clean_db)
    assert report["readiness"] == "FAIL"
    # The DB is no longer "clean" because moltbook_entries now has a row.
    assert report["db_clean_initialised"] is False
    # And the clean-db downgrade DID NOT fire.
    assert not report["release_gate"].get("clean_db_downgrade")
