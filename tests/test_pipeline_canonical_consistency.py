"""End-to-end canonical-consistency tests.

These tests are the runtime contract that the second-pass audit said the
hackathon was missing: they fail if the spine is reported but not
enforced. Specifically, they cover:

1. Seeded mode → BLOCK_CAPITAL + zero non-advisory rows + DIAGNOSTIC_ONLY.
2. Replay-labeled fixture → externally checkable but capital still blocked.
3. No veto bypass — health report and action report cannot disagree.
4. Decision ledger respects ``--no-write`` and persists JSONL otherwise.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.action_engine import build_action_report
from scripts.pipeline_health_report import (
    REPO_ROOT,
    build_pipeline_health_report,
)
from scripts.replay_runner import run_replay


REPLAY_FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "replay_with_labels"
LABELED_FIXTURE = REPLAY_FIXTURE_DIR / "sample_replay.json"


@pytest.fixture(scope="module")
def health_report():
    return build_pipeline_health_report(include_tests=False, write_runtime=False)


@pytest.fixture(scope="module")
def action_report():
    return build_action_report(write_runtime=False)


# ----------------------------------------------------------------------
# 1. Seeded mode contract
# ----------------------------------------------------------------------


def test_seeded_truth_origin_is_seeded(health_report):
    assert health_report["truth_origin"] == "seeded"
    assert health_report["canonical_truth_origin"] == "SEEDED"
    assert health_report["external_signal_count"] == 0
    assert health_report["external_truth_status"] == "NO_EXTERNAL_TRUTH"


def test_seeded_canonical_action_permission_is_block_capital(health_report):
    assert health_report["canonical_action_permission"] == "BLOCK_CAPITAL"
    assert "capital deployment" in health_report["forbidden_use"]


def test_seeded_action_engine_output_is_diagnostic_only(action_report):
    assert action_report["canonical_action_permission"] == "BLOCK_CAPITAL"
    assert action_report["execution_status"] == "DIAGNOSTIC_ONLY"
    assert action_report["canonical_block_capital"] is True
    for row in action_report["actions"]:
        assert row["action"] == "ADVISORY_ONLY"
        assert row["action_executable"] is False
        # The diagnostic signal is preserved
        assert "raw_action_signal" in row
        assert row["execution_status"] == "DIAGNOSTIC_ONLY"


def test_seeded_action_engine_summary_only_advisory_only(action_report):
    summary = action_report["summary_by_action"]
    assert summary.get("ADVISORY_ONLY", 0) > 0
    for action in ("EXIT_NOW", "REDUCE", "HOLD", "MONITOR", "BLOCK_ENTRY"):
        assert summary.get(action, 0) == 0


# ----------------------------------------------------------------------
# 2. Replay-labelled mode contract
# ----------------------------------------------------------------------


def test_replay_labeled_records_are_externally_checkable_but_not_live():
    payload = run_replay(LABELED_FIXTURE)
    summary = payload["evidence_ledger_summary"]
    assert payload["labeled_record_count"] > 0
    assert summary["replay_labeled_signal_count"] > 0
    assert summary["external_signal_count"] == summary["replay_labeled_signal_count"]
    # Replay-labelled records are externally checkable, but the canonical
    # permission still blocks capital — replay never proves live validity.
    permission = payload["canonical_action_permission_block"]
    assert permission["canonical_action_permission"] == "BLOCK_CAPITAL"
    assert "capital deployment" in permission["forbidden_use"]


def test_replay_runner_supports_metrics_computation():
    payload = run_replay(LABELED_FIXTURE)
    accounting = payload["system_outcome_accounting"]
    assert accounting["sample_count"] >= 5
    assert accounting["labeled_count"] >= 5
    # Either precision and recall are computed numbers, or marked as None
    # when their denominator is zero — never silently faked.
    assert accounting["precision"] is None or 0.0 <= accounting["precision"] <= 1.0
    assert accounting["recall"] is None or 0.0 <= accounting["recall"] <= 1.0
    assert "replay/sample metrics" in accounting["note"] or "insufficient_sample" in accounting["note"]


# ----------------------------------------------------------------------
# 3. No veto bypass — health and action reports cannot disagree
# ----------------------------------------------------------------------


def test_health_report_and_action_report_share_canonical_permission(
    health_report, action_report
):
    assert (
        health_report["canonical_action_permission"]
        == action_report["canonical_action_permission"]
    )


def test_health_report_per_ticker_summary_carries_canonical_permission(
    health_report,
):
    summary = health_report["per_ticker_action_summary"]
    assert summary["canonical_action_permission"] == "BLOCK_CAPITAL"
    assert summary["execution_status"] == "DIAGNOSTIC_ONLY"
    assert summary["canonical_block_capital"] is True


def test_no_action_row_contradicts_health_report_block_capital(
    health_report, action_report
):
    assert health_report["canonical_action_permission"] == "BLOCK_CAPITAL"
    for row in action_report["actions"]:
        assert row["canonical_block_capital"] is True
        assert row["action_executable"] is False


# ----------------------------------------------------------------------
# 4. Decision ledger persistence and --no-write
# ----------------------------------------------------------------------


def test_decision_ledger_status_is_no_write_under_no_write_mode(health_report):
    assert health_report["decision_ledger_persist_status"] == "NO_WRITE_MODE"
    assert health_report["decision_ledger_status"] == "NO_WRITE_MODE"
    assert health_report["decision_ledger_record_count"] == 1
    assert health_report["decision_ledger_path"] is None


def test_decision_ledger_persists_jsonl_when_write_enabled(tmp_path, monkeypatch):
    # Redirect runtime/decision_ledger.jsonl to tmp_path so the test
    # never touches the real runtime artifact.
    fake_runtime = tmp_path / "runtime"
    fake_runtime.mkdir(parents=True, exist_ok=True)
    fake_repo_root = tmp_path
    # Symlink runtime back to the real one for everything except the
    # decision ledger by patching the path directly.
    real_root = REPO_ROOT
    import scripts.pipeline_health_report as health

    decision_path = fake_runtime / "decision_ledger.jsonl"
    monkeypatch.setattr(health, "REPO_ROOT", fake_repo_root)
    # The health report writes to many runtime files; we keep their real
    # location to avoid disrupting the rest of the run, but the decision
    # ledger uses REPO_ROOT/runtime which we just redirected.
    # Since the build_pipeline_health_report uses REPO_ROOT for the
    # ledger path, redirecting it through monkeypatch is sufficient.
    # Other artifacts use HEALTH_REPORT_PATH-style absolute paths
    # imported at module load and not re-resolved.
    report = build_pipeline_health_report(
        include_tests=False, write_runtime=True, repo_root=real_root
    )
    # write_runtime=True triggers persistence; the path lives under the
    # redirected REPO_ROOT.
    assert report["decision_ledger_persist_status"] == "PERSISTED"
    assert report["decision_ledger_record_count"] == 1
    assert decision_path.exists()
    serialized = decision_path.read_text(encoding="utf-8").strip()
    rows = [json.loads(line) for line in serialized.splitlines() if line]
    assert len(rows) == 1
    record = rows[0]
    assert record["canonical_action_permission"] == report["canonical_action_permission"]
    assert record["veto_reasons"]
    assert record["evidence_snapshot_hash"]


# ----------------------------------------------------------------------
# 5. Truth_origin_breakdown is real, not fabricated
# ----------------------------------------------------------------------


def test_truth_origin_breakdown_is_derived_from_evidence_ledger(health_report):
    breakdown = health_report["truth_origin_breakdown"]
    record_count = health_report["evidence_ledger_record_count"]
    # Sum of breakdown values should match the ledger record count
    assert sum(breakdown.values()) == record_count
    # Seeded mode must show a real seeded count, not a hardcoded 1
    assert breakdown.get("SEEDED", 0) >= 1


def test_evidence_ledger_status_reflects_external_count(health_report):
    summary = health_report["evidence_ledger_summary"]
    assert summary["external_signal_count"] == 0
    assert summary["has_external_truth"] is False
    assert health_report["evidence_ledger_status"] == "SEEDED_ONLY"
