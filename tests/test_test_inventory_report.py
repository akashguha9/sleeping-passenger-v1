"""Test inventory report — proof_loop_hardening_sprint, Phase 11."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.test_inventory_report import (
    build_inventory,
    classify_test_file,
)


pytestmark = [
    pytest.mark.reliability,
]


def test_classify_advisory_filename_is_safety_floor():
    cls = classify_test_file("test_advisory_contract.py")
    assert cls.bucket == "safety_floor"


def test_classify_calibration_filename_is_calibration():
    cls = classify_test_file("test_calibration_metrics.py")
    assert cls.bucket == "calibration"


def test_classify_moltbook_filename_is_moltbook():
    cls = classify_test_file("test_moltbook_dynamic_visibility.py")
    assert cls.bucket == "moltbook"


def test_classify_watchdog_is_reliability():
    cls = classify_test_file("test_watchdog_refresh.py")
    assert cls.bucket == "reliability"


def test_classify_truth_is_frontend_truth():
    cls = classify_test_file("test_customer_frontend_language.py")
    assert cls.bucket == "frontend_truth"


def test_classify_misc_is_unknown():
    cls = classify_test_file("test_random_thing.py")
    assert cls.bucket == "cosmetic_or_unknown"


def test_build_inventory_on_real_tests_dir():
    repo_root = Path(__file__).resolve().parents[1]
    report = build_inventory(repo_root / "tests")
    assert report["total_tests_collected"] > 0
    # Safety floor and calibration buckets must be populated.
    assert report["safety_floor_count"] > 0
    assert report["calibration_count"] > 0
    assert report["broker_api_called"] is False
    assert report["advisory_status"] == "ADVISORY_ONLY"


def test_build_inventory_handles_missing_dir(tmp_path):
    report = build_inventory(tmp_path / "no_tests_dir")
    assert report["total_tests_collected"] == 0
    assert "warning" in report
