"""Tests for the calibration honesty layer."""
from __future__ import annotations

import pytest

from scripts.calibration_status import (
    CalibrationStatus,
    aggregate_calibration_status,
    classify_calibration_status,
)


class TestCalibrationClassify:
    def test_seeded_runtime_is_demo_only(self):
        report = classify_calibration_status(
            score_name="signal_score",
            has_outcome_labels=False,
            sample_count=0,
            runtime_mode="seeded",
        )
        assert report.status == CalibrationStatus.DEMO_ONLY
        assert report.supports_capital_permission is False
        assert report.supports_decision_ready_claim is False

    def test_no_labels_no_samples_is_heuristic(self):
        report = classify_calibration_status(
            score_name="x",
            has_outcome_labels=False,
            sample_count=0,
            runtime_mode="LIVE",
        )
        assert report.status == CalibrationStatus.UNCALIBRATED_HEURISTIC
        assert report.supports_capital_permission is False

    def test_threshold_without_outcomes_is_arbitrary(self):
        report = classify_calibration_status(
            score_name="threshold_x",
            has_outcome_labels=False,
            sample_count=10,
            is_threshold=True,
            threshold_value=0.5,
            runtime_mode="LIVE",
        )
        assert report.status == CalibrationStatus.ARBITRARY_THRESHOLD

    def test_labels_below_min_samples_is_insufficient(self):
        report = classify_calibration_status(
            score_name="x",
            has_outcome_labels=True,
            sample_count=5,
            runtime_mode="LIVE",
            min_samples=30,
        )
        assert report.status == CalibrationStatus.INSUFFICIENT_SAMPLES

    def test_calibrated_when_labels_and_samples(self):
        report = classify_calibration_status(
            score_name="x",
            has_outcome_labels=True,
            sample_count=200,
            runtime_mode="LIVE",
        )
        assert report.status == CalibrationStatus.CALIBRATED
        assert report.supports_capital_permission is True
        assert report.supports_decision_ready_claim is True

    def test_samples_without_labels_requires_external(self):
        report = classify_calibration_status(
            score_name="x",
            has_outcome_labels=False,
            sample_count=200,
            runtime_mode="LIVE",
        )
        assert report.status == CalibrationStatus.REQUIRES_EXTERNAL_LABELS


class TestCalibrationAggregate:
    def test_aggregate_demo_runtime(self):
        reports = [
            classify_calibration_status(
                score_name=name,
                has_outcome_labels=False,
                runtime_mode="seeded",
            )
            for name in ("a", "b", "c")
        ]
        agg = aggregate_calibration_status(reports)
        assert agg["calibration_status"] == "DEMO_ONLY"
        assert agg["supports_capital_permission"] is False
        assert agg["supports_decision_ready_claim"] is False

    def test_aggregate_all_calibrated(self):
        reports = [
            classify_calibration_status(
                score_name=name,
                has_outcome_labels=True,
                sample_count=200,
                runtime_mode="LIVE",
            )
            for name in ("a", "b")
        ]
        agg = aggregate_calibration_status(reports)
        assert agg["calibration_status"] == "CALIBRATED"
        assert agg["supports_capital_permission"] is True

    def test_aggregate_partial_calibrated_is_insufficient(self):
        reports = [
            classify_calibration_status(
                score_name="a",
                has_outcome_labels=True,
                sample_count=200,
                runtime_mode="LIVE",
            ),
            classify_calibration_status(
                score_name="b",
                has_outcome_labels=False,
                runtime_mode="LIVE",
            ),
        ]
        agg = aggregate_calibration_status(reports)
        assert agg["calibration_status"] == "INSUFFICIENT_SAMPLES"
        assert agg["supports_capital_permission"] is False

    def test_aggregate_empty_returns_uncalibrated(self):
        agg = aggregate_calibration_status([])
        assert agg["calibration_status"] == "UNCALIBRATED_HEURISTIC"
        assert agg["supports_capital_permission"] is False
