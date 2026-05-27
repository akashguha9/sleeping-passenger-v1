"""Hosted uptime report — proof_loop_hardening_sprint, Phase 9."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.hosted_uptime_report import (
    PRIVATE_BETA_UPTIME_PCT_FLOOR,
    PingRow,
    compute_uptime_report,
    load_pings,
)


pytestmark = [
    pytest.mark.reliability,
]


def test_empty_input_returns_empty_evidence_status_with_safety_stamps():
    report = compute_uptime_report([])
    assert report["total_checks"] == 0
    assert report["successful_checks"] == 0
    assert report["failed_checks"] == 0
    assert report["uptime_pct"] is None
    assert report["evidence_status"] == "EMPTY"
    assert report["broker_api_called"] is False
    assert report["ai_execution_count"] == 0


def test_uptime_pct_formula():
    pings = [PingRow("t1", True)] * 99 + [PingRow("t2", False)]
    report = compute_uptime_report(pings)
    assert report["total_checks"] == 100
    assert report["successful_checks"] == 99
    assert report["failed_checks"] == 1
    assert report["uptime_pct"] == pytest.approx(99.0)
    assert report["evidence_status"] == "MEETS_UPTIME_FLOOR"


def test_uptime_below_floor_marked_below():
    pings = [PingRow("t1", True)] * 90 + [PingRow("t2", False)] * 10
    report = compute_uptime_report(pings)
    assert report["uptime_pct"] == pytest.approx(90.0)
    assert report["evidence_status"] == "BELOW_UPTIME_FLOOR"


def test_load_pings_json(tmp_path: Path):
    path = tmp_path / "pings.json"
    path.write_text(
        json.dumps(
            [
                {"timestamp_utc": "2026-05-20T00:00:00Z", "success": True},
                {"timestamp_utc": "2026-05-20T01:00:00Z", "success": False},
            ]
        ),
        encoding="utf-8",
    )
    pings = load_pings(path)
    assert len(pings) == 2
    assert pings[0].success is True
    assert pings[1].success is False


def test_load_pings_csv(tmp_path: Path):
    path = tmp_path / "pings.csv"
    path.write_text(
        "timestamp_utc,success\n"
        "2026-05-20T00:00:00Z,true\n"
        "2026-05-20T01:00:00Z,false\n",
        encoding="utf-8",
    )
    pings = load_pings(path)
    assert len(pings) == 2


def test_uptime_floor_constant_is_99():
    assert PRIVATE_BETA_UPTIME_PCT_FLOOR == 99.0


def test_no_live_url_does_not_imply_check():
    """Even with an --url, the script never marks fake successes."""
    report = compute_uptime_report([], expected_url="https://example.invalid")
    assert report["expected_url"] == "https://example.invalid"
    assert report["total_checks"] == 0
