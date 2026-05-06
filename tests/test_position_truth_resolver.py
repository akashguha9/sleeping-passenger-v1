"""Tests for position_truth_resolver — visibility-only divergence detection."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.position_truth_resolver import (
    build_position_reconciliation_report,
    build_position_truth_summary,
)


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_neither_source_present_reports_no_active_truth(scratch_path: Path):
    curated = scratch_path / "moltbook" / "open_positions.json"
    runtime = scratch_path / "runtime" / "paper_positions.json"
    summary = build_position_truth_summary(curated, runtime)
    assert summary["canonical_position_source"] == "curated_moltbook"
    assert summary["position_integrity_state"] == "MISSING_CANONICAL"
    assert summary["position_source_divergence_detected"] is False
    assert summary["canonical_position_count"] == 0
    assert summary["curated_moltbook_positions_count"] == 0
    assert summary["runtime_paper_positions_count"] == 0
    assert "no active position truth" in summary["position_truth_warning"].lower()


def test_only_curated_present_is_canonical_without_divergence(scratch_path: Path):
    curated = scratch_path / "moltbook" / "open_positions.json"
    runtime = scratch_path / "runtime" / "paper_positions.json"
    _write(
        curated,
        [
            {"ticker": "TLT", "status": "OPEN"},
            {"ticker": "TIP", "status": "OPEN"},
        ],
    )
    summary = build_position_truth_summary(curated, runtime)
    assert summary["canonical_position_source"] == "curated_moltbook"
    assert summary["position_integrity_state"] == "CLEAN"
    assert summary["curated_moltbook_positions_count"] == 2
    assert summary["runtime_paper_positions_count"] == 0
    assert summary["position_source_divergence_detected"] is False
    assert "runtime paper-position ledger has not been created" in summary["position_truth_warning"]


def test_only_runtime_present_is_canonical_and_flagged(scratch_path: Path):
    curated = scratch_path / "moltbook" / "open_positions.json"
    runtime = scratch_path / "runtime" / "paper_positions.json"
    _write(runtime, [{"symbol": "UNG"}])
    summary = build_position_truth_summary(curated, runtime)
    assert summary["canonical_position_source"] == "curated_moltbook"
    assert summary["position_integrity_state"] == "MISSING_CANONICAL"
    assert summary["runtime_paper_positions_count"] == 1
    assert summary["curated_moltbook_positions_count"] == 0
    assert summary["position_source_divergence_detected"] is False
    assert summary["advisory_position_sources"] == ["runtime_paper"]
    assert "runtime remains advisory only" in summary["position_truth_warning"]


def test_both_present_symbols_match_no_divergence(scratch_path: Path):
    curated = scratch_path / "moltbook" / "open_positions.json"
    runtime = scratch_path / "runtime" / "paper_positions.json"
    _write(curated, [{"ticker": "TLT"}, {"ticker": "TIP"}])
    _write(runtime, [{"ticker": "TLT"}, {"ticker": "TIP"}])
    summary = build_position_truth_summary(curated, runtime)
    assert summary["position_source_divergence_detected"] is False
    assert summary["position_integrity_state"] == "CLEAN"
    assert summary["overlap_symbols"] == ["TIP", "TLT"]
    assert summary["missing_from_runtime"] == []
    assert summary["missing_from_curated"] == []
    assert summary["position_truth_warning"] is None


def test_both_present_symbol_divergence_is_reported(scratch_path: Path):
    curated = scratch_path / "moltbook" / "open_positions.json"
    runtime = scratch_path / "runtime" / "paper_positions.json"
    _write(curated, [{"ticker": "TLT"}, {"ticker": "TIP"}])
    _write(runtime, [{"ticker": "UNG"}])
    summary = build_position_truth_summary(curated, runtime)
    assert summary["position_source_divergence_detected"] is True
    assert summary["position_integrity_state"] == "DIVERGED"
    assert summary["curated_moltbook_positions_count"] == 2
    assert summary["runtime_paper_positions_count"] == 1
    assert summary["missing_from_runtime"] == ["TIP", "TLT"]
    assert summary["missing_from_curated"] == ["UNG"]
    assert summary["overlap_symbols"] == []
    assert "diverge" in summary["position_truth_warning"].lower()


def test_malformed_position_file_is_treated_as_empty(scratch_path: Path):
    curated = scratch_path / "moltbook" / "open_positions.json"
    runtime = scratch_path / "runtime" / "paper_positions.json"
    curated.parent.mkdir(parents=True, exist_ok=True)
    curated.write_text("not-json", encoding="utf-8")
    _write(runtime, [{"ticker": "UNG"}])
    summary = build_position_truth_summary(curated, runtime)
    assert summary["curated_moltbook_positions_count"] == 0
    assert summary["runtime_paper_positions_count"] == 1
    # Both files exist on disk but curated parsed to empty list, so divergence
    # is still reported against runtime having a symbol.
    assert summary["position_source_divergence_detected"] is True


def test_positions_nested_under_positions_key_are_understood(scratch_path: Path):
    curated = scratch_path / "moltbook" / "open_positions.json"
    runtime = scratch_path / "runtime" / "paper_positions.json"
    curated.parent.mkdir(parents=True, exist_ok=True)
    curated.write_text(
        json.dumps({"positions": [{"ticker": "TLT"}, {"ticker": "TIP"}]}),
        encoding="utf-8",
    )
    _write(runtime, [{"ticker": "TLT"}, {"ticker": "TIP"}])
    summary = build_position_truth_summary(curated, runtime)
    assert summary["curated_moltbook_positions_count"] == 2
    assert summary["position_source_divergence_detected"] is False


def test_position_reconciliation_report_exposes_visibility_fields(scratch_path: Path):
    curated = scratch_path / "moltbook" / "open_positions.json"
    runtime = scratch_path / "runtime" / "paper_positions.json"
    _write(curated, [{"ticker": "TLT"}, {"ticker": "TIP"}])
    _write(runtime, [{"ticker": "TLT"}, {"ticker": "UNG"}])

    report = build_position_reconciliation_report(curated, runtime)

    assert report["curated_only_symbols"] == ["TIP"]
    assert report["runtime_only_symbols"] == ["UNG"]
    assert report["overlapping_symbols"] == ["TLT"]
    assert report["recommended_canonical_source"] == "curated_moltbook"
    assert report["divergence_severity"] == "HIGH"
    assert "do not auto-migrate" in report["safe_next_action"].lower()


def test_position_checksums_change_when_symbols_or_counts_change(scratch_path: Path):
    curated = scratch_path / "moltbook" / "open_positions.json"
    runtime = scratch_path / "runtime" / "paper_positions.json"
    _write(curated, [{"ticker": "TLT"}])
    _write(runtime, [{"ticker": "TLT"}])
    first = build_position_truth_summary(curated, runtime)

    _write(runtime, [{"ticker": "TLT"}, {"ticker": "TIP"}])
    second = build_position_truth_summary(curated, runtime)

    assert first["canonical_position_checksum"] == second["canonical_position_checksum"]
    assert first["advisory_position_checksum"] != second["advisory_position_checksum"]


def test_advisory_source_cannot_silently_become_canonical(scratch_path: Path):
    curated = scratch_path / "moltbook" / "open_positions.json"
    runtime = scratch_path / "runtime" / "paper_positions.json"
    _write(runtime, [{"ticker": "UNG"}])

    report = build_position_reconciliation_report(curated, runtime)
    summary = build_position_truth_summary(curated, runtime)

    assert report["recommended_canonical_source"] == "curated_moltbook"
    assert summary["canonical_position_source"] == "curated_moltbook"
    assert summary["position_integrity_state"] == "MISSING_CANONICAL"
    assert report["divergence_severity"] == "CRITICAL"
