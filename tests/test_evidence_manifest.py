"""Evidence manifest invariants — proof_loop_hardening_sprint, Phase 4.

These are leakage controls.  The manifest must NEVER label the bundle
`SUFFICIENT_FOR_INVESTOR_DEMO` when `N_real < 20`, and must NEVER report
full freshness for a missing file.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from scripts.evidence_manifest import (
    _classify_evidence_status,
    build_manifest,
    file_age_days,
    freshness_score,
)


pytestmark = [
    pytest.mark.safety_floor,
]


def test_missing_file_has_zero_freshness():
    assert freshness_score(None, 7) == 0.0


def test_fresh_file_has_full_freshness():
    assert freshness_score(0.0, 7) == 1.0
    assert freshness_score(7.0, 7) == 1.0


def test_half_stale_file_at_50_percent():
    # max_age = 7.  age = 10.5 -> 1 - (3.5 / 7) = 0.5
    assert freshness_score(10.5, 7) == pytest.approx(0.5)


def test_fully_stale_file_has_zero_freshness():
    # age = 14, max_age = 7 -> 1 - (7/7) = 0
    assert freshness_score(14.0, 7) == pytest.approx(0.0)
    assert freshness_score(100.0, 7) == 0.0


def test_investor_demo_blocked_when_n_real_below_20():
    """N_real < 20 must never produce SUFFICIENT_FOR_INVESTOR_DEMO."""
    status = _classify_evidence_status(
        has_calibration=True,
        has_ledger=True,
        n_real=19,
        has_demo=True,
        has_screenshots=True,
        has_playwright=True,
        has_pytest=True,
        has_hosted_uptime=True,
    )
    assert status not in (
        "SUFFICIENT_FOR_INVESTOR_DEMO",
        "SUFFICIENT_FOR_PRIVATE_BETA",
    )


def test_investor_demo_requires_playwright_and_demo_and_screenshots():
    status = _classify_evidence_status(
        has_calibration=True,
        has_ledger=True,
        n_real=200,
        has_demo=False,
        has_screenshots=True,
        has_playwright=True,
        has_pytest=True,
        has_hosted_uptime=False,
    )
    assert status != "SUFFICIENT_FOR_INVESTOR_DEMO"


def test_local_demo_status_when_only_local_artifacts_present():
    status = _classify_evidence_status(
        has_calibration=True,
        has_ledger=False,
        n_real=0,
        has_demo=False,
        has_screenshots=True,
        has_playwright=False,
        has_pytest=True,
        has_hosted_uptime=False,
    )
    assert status == "SUFFICIENT_FOR_LOCAL_DEMO"


def test_empty_when_nothing_present():
    status = _classify_evidence_status(
        has_calibration=False,
        has_ledger=False,
        n_real=0,
        has_demo=False,
        has_screenshots=False,
        has_playwright=False,
        has_pytest=False,
        has_hosted_uptime=False,
    )
    assert status == "EMPTY"


def test_private_beta_requires_hosted_uptime():
    status = _classify_evidence_status(
        has_calibration=True,
        has_ledger=True,
        n_real=200,
        has_demo=True,
        has_screenshots=True,
        has_playwright=True,
        has_pytest=True,
        has_hosted_uptime=False,
    )
    # Without hosted uptime we can stop at investor demo.
    assert status == "SUFFICIENT_FOR_INVESTOR_DEMO"


def test_private_beta_unlocked_only_when_all_signals_present():
    status = _classify_evidence_status(
        has_calibration=True,
        has_ledger=True,
        n_real=200,
        has_demo=True,
        has_screenshots=True,
        has_playwright=True,
        has_pytest=True,
        has_hosted_uptime=True,
    )
    assert status == "SUFFICIENT_FOR_PRIVATE_BETA"


def test_build_manifest_returns_safety_stamps_and_disclaimer():
    manifest = build_manifest()
    assert manifest["advisory_status"] == "ADVISORY_ONLY"
    assert manifest["execution_gate"] == "LOCKED"
    assert manifest["broker_api_called"] is False
    assert manifest["ai_execution_count"] == 0
    assert "self_audit_disclaimer" in manifest


def test_build_manifest_n_real_is_read_from_calibration_report_or_zero():
    manifest = build_manifest()
    # We do NOT assert a specific number — only that it is an int and
    # that it is non-negative.  The truthful state today is 0.
    assert isinstance(manifest["n_real"], int)
    assert manifest["n_real"] >= 0


def test_file_age_days_returns_none_for_missing_file(tmp_path):
    assert file_age_days(tmp_path / "absent.json") is None
