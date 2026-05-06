from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.external_observation_lane import ExternalObservation, observations_to_scm_candidates
from scripts.integrity_diagnostics import (
    build_reproducibility_summary,
    build_signal_segmentation_summary,
    build_stable_health_snapshot,
    build_temporal_integrity_summary,
    compute_stable_health_snapshot_hash,
)
from scripts.pipeline_health_report import build_pipeline_health_report
from scripts.run_diagnostics_pipeline import run_diagnostics_pipeline
from scripts.runtime_common import REPO_ROOT


def _iso(minutes: int = 0) -> str:
    return (datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes)).isoformat()


def _observation(symbol: str, observed_at_utc: str) -> ExternalObservation:
    return ExternalObservation(
        symbol=symbol,
        provider="yahoo",
        observed_at_utc=observed_at_utc,
        price=100.0,
        previous_close=99.0,
        change_pct=0.01,
        volume=1_000.0,
        currency="USD",
        source_mode="SYNTHETIC_RUNTIME_FALLBACK",
        truth_origin="external",
        is_external=True,
        is_placeholder=False,
        data_quality="VALID_EXTERNAL",
    )


def test_reproducibility_surface_reports_local_requirements_and_ci():
    report = run_diagnostics_pipeline(write_runtime=False)
    summary = build_reproducibility_summary(repo_root=REPO_ROOT, report=report)

    assert summary["requirements_txt_exists"] is True
    assert summary["ci_workflow_exists"] is True
    assert "pytest.yml" in summary["ci_workflow_files"]
    assert summary["python_version"]
    assert summary["runtime_metadata_exposed"] is True
    assert summary["runtime_metadata_keys_present"] == [
        "commit_hash",
        "config_fingerprint",
        "run_id",
    ]


def test_health_report_exposes_runtime_reproducibility_keys():
    report = build_pipeline_health_report(write_runtime=False)
    assert report["run_id"]
    assert report["commit_hash"]
    assert report["config_fingerprint"]
    reproducibility = report["reproducibility_summary"]
    assert reproducibility["runtime_metadata_exposed"] is True


def test_golden_snapshot_matches_seeded_fixture():
    expected = json.loads(
        (REPO_ROOT / "tests" / "fixtures" / "golden_health_snapshot_seeded.json").read_text(
            encoding="utf-8"
        )
    )
    report = run_diagnostics_pipeline(write_runtime=False)
    snapshot = build_stable_health_snapshot(report)

    assert snapshot == expected
    assert report["golden_health_snapshot"] == expected


def test_stable_hash_excludes_volatile_fields():
    report = run_diagnostics_pipeline(write_runtime=False)
    original_hash = compute_stable_health_snapshot_hash(report)

    mutated = dict(report)
    mutated["run_id"] = "different"
    mutated["artifact_written_at"] = "2030-01-01T00:00:00+00:00"
    mutated["health_generated_at"] = "2030-01-01T00:00:00+00:00"

    assert compute_stable_health_snapshot_hash(mutated) == original_hash


def test_golden_snapshot_detects_drift_in_stable_fields():
    report = run_diagnostics_pipeline(write_runtime=False)
    mutated = dict(report)
    mutated["position_integrity_state"] = "CLEAN"

    assert compute_stable_health_snapshot_hash(mutated) != compute_stable_health_snapshot_hash(report)


def test_temporal_integrity_accepts_valid_observation():
    summary = build_temporal_integrity_summary(
        decision_timestamp=_iso(1),
        reconciliation_timestamp=_iso(2),
        observations=[_observation("TLT", _iso(0))],
    )
    assert summary["temporal_integrity_state"] == "CLEAN"
    assert summary["temporal_integrity_violation_count"] == 0


def test_missing_timestamp_is_rejected_fail_closed_for_candidate_admission():
    candidates = observations_to_scm_candidates(
        [_observation("TLT", "")],
        decision_timestamp=_iso(1),
    )
    summary = build_temporal_integrity_summary(
        decision_timestamp=_iso(1),
        observations=[_observation("TLT", "")],
    )
    assert candidates == []
    assert summary["temporal_integrity_state"] == "FAILED"
    assert "external_observation_missing_or_malformed_timestamp" in summary[
        "temporal_integrity_warnings"
    ]


def test_future_observation_timestamp_is_rejected():
    rejection_reasons: list[str] = []
    candidates = observations_to_scm_candidates(
        [_observation("TLT", _iso(5))],
        decision_timestamp=_iso(1),
        rejection_reasons=rejection_reasons,
    )
    summary = build_temporal_integrity_summary(
        decision_timestamp=_iso(1),
        observations=[_observation("TLT", _iso(5))],
    )
    assert candidates == []
    assert rejection_reasons == ["TLT:future_observation_timestamp"]
    assert summary["temporal_integrity_state"] == "FAILED"


def test_reconciliation_timestamp_before_decision_is_flagged():
    summary = build_temporal_integrity_summary(
        decision_timestamp=_iso(3),
        reconciliation_timestamp=_iso(2),
        observations=[_observation("TLT", _iso(1))],
    )
    assert summary["temporal_integrity_state"] == "WARNING"
    assert "reconciliation_timestamp_precedes_decision_timestamp" in summary[
        "temporal_integrity_warnings"
    ]


def test_seeded_external_segmentation_states_are_explicit():
    seeded_only = build_signal_segmentation_summary(
        per_signal_rows=[{"ticker": "TLT", "source_name": "signal_ledger", "signal_origin": "seeded"}],
        external_candidate_count=0,
        external_observation_valid_count=0,
        scm_external_row_count=0,
        scm_seeded_row_count=1,
    )
    external_only = build_signal_segmentation_summary(
        per_signal_rows=[
            {
                "ticker": "UNG",
                "source_name": "external_observation",
                "signal_origin": "external",
            }
        ],
        external_candidate_count=1,
        external_observation_valid_count=1,
        scm_external_row_count=1,
        scm_seeded_row_count=0,
    )
    mixed = build_signal_segmentation_summary(
        per_signal_rows=[
            {"ticker": "TLT", "source_name": "signal_ledger", "signal_origin": "seeded"},
            {
                "ticker": "UNG",
                "source_name": "external_observation",
                "signal_origin": "external",
            },
        ],
        external_candidate_count=1,
        external_observation_valid_count=1,
        scm_external_row_count=1,
        scm_seeded_row_count=1,
    )

    assert seeded_only["seeded_signal_count"] == 1
    assert seeded_only["external_signal_count"] == 0
    assert seeded_only["evidence_contamination_risk"] == "NONE"
    assert external_only["seeded_signal_count"] == 0
    assert external_only["external_signal_count"] == 1
    assert external_only["evidence_contamination_risk"] == "LOW"
    assert mixed["mixed_signal_metric_warning"] is not None
    assert mixed["evidence_contamination_risk"] == "HIGH"


def test_seeded_rows_do_not_inflate_external_validation_readiness():
    report = run_diagnostics_pipeline(write_runtime=False)
    assert report["seeded_signal_count"] > 0
    assert report["external_signal_count"] == 0
    assert report["external_candidate_count"] == 0
    assert report["can_deploy_capital"] is False
