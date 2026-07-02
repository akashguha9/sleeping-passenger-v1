"""Retrocast: fixture corpus, category verdicts, imported/live separation."""
from __future__ import annotations

import json
from pathlib import Path

from scripts import retrocast_calibration as rc


def _run():
    markets, prices = rc.fixture_resolved_markets_and_prices()
    return rc.run_retrocast(markets, rc.fixture_taxonomy(), prices)


def test_fixture_produces_calibration_records():
    result = _run()
    assert len(result["records"]) >= 24
    for r in result["records"][:5]:
        assert r["evidence_class"] == rc.IMPORTED_BACKTEST
        assert r["data_mode"] == rc.FIXTURE_DEMONSTRATION
        assert f"fwd_return_{rc.PRIMARY_HORIZON}" in r


def test_transmission_category_validates_and_noise_does_not():
    report = _run()["category_report"]
    rates = report["policy_rates"]
    noise = report["elections_noise"]
    assert rates["n"] >= rc.MIN_N_FOR_VERDICT
    assert rates["status"] == rc.STATUS_VALIDATED, rates
    assert rates["hit_rate"] > noise["hit_rate"]
    assert noise["status"] in (rc.STATUS_BANNED, rc.STATUS_UNVALIDATED_WEAK,
                               rc.STATUS_UNVALIDATED_N), noise


def test_ban_list_is_the_kill_switch():
    result = _run()
    for cat in result["category_ban_list"]:
        assert result["category_report"][cat]["status"] == rc.STATUS_BANNED
    assert "policy_rates" not in result["category_ban_list"]


def test_imported_backtest_never_counts_toward_live_ladder(tmp_path: Path):
    result = _run()
    snaps = tmp_path / "forward_snapshots.jsonl"
    rows = [
        {"snapshot_id": "a", "data_mode": "LIVE", "outcome": "PENDING"},
        {"snapshot_id": "b", "data_mode": "LIVE", "outcome": "WIN"},
        {"snapshot_id": "c", "data_mode": "FIXTURE_DEMONSTRATION",
         "outcome": "WIN"},
    ]
    snaps.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    sep = rc.evidence_separation(result["records"], snaps)
    assert sep["n_imported_backtest"] == len(result["records"])
    assert sep["n_live_labeled"] == 1          # fixture row excluded
    assert sep["n_live_pending"] == 1
    assert sep["imported_counts_toward_ladder"] is False
    assert sep["ladder_status_live_only"] == "CAPTURE_STARTED_NO_LABELS"


def test_ladder_thresholds():
    assert rc.ladder_status(0) == "NO_LIVE_EVIDENCE"
    assert rc.ladder_status(5) == "CAPTURE_STARTED_NO_LABELS"
    assert rc.ladder_status(10) == "PROVISIONAL"
    assert rc.ladder_status(30) == "FIRST_PASS"
    assert rc.ladder_status(150) == "STRONGER"


def test_write_outputs_dry_run_by_default(tmp_path: Path):
    result = _run()
    rec = tmp_path / "retrocast.jsonl"
    rep = tmp_path / "report.json"
    out = rc.write_outputs(result, records_path=rec, report_path=rep,
                           snapshots_path=None)
    assert out["mode"] == "dry_run"
    assert not rec.exists() and not rep.exists()
    out2 = rc.write_outputs(result, records_path=rec, report_path=rep,
                            snapshots_path=None, mode="write")
    assert rec.exists() and rep.exists()
    assert out2["n_records"] == len(result["records"])
    saved = json.loads(rep.read_text(encoding="utf-8"))
    assert saved["data_mode"] == rc.FIXTURE_DEMONSTRATION
