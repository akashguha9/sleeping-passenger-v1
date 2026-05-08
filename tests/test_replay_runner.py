"""Tests for the replay runner CLI."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.replay_runner import build_replay_summary, run_replay


REPO_ROOT = Path(__file__).resolve().parents[1]
LABELED_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "replay_with_labels" / "sample_replay.json"
UNLABELED_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "replay_with_labels" / "sample_unlabeled.json"
DIRECTORY_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "replay_with_labels"


def test_replay_runner_loads_labeled_fixture_and_marks_externally_checkable():
    payload = run_replay(LABELED_FIXTURE)
    assert payload["record_count"] == 12
    assert payload["labeled_record_count"] == 12
    assert payload["unlabeled_record_count"] == 0
    assert payload["externally_checkable_count"] == 12
    summary = payload["evidence_ledger_summary"]
    assert summary["replay_labeled_signal_count"] == 12
    assert summary["external_signal_count"] == 12
    # Even with external truth from replay-labelled records, capital
    # remains blocked because position state is unknown and calibration
    # is missing — replay never upgrades to DEPLOY_CAPITAL.
    permission = payload["canonical_action_permission_block"]
    assert permission["canonical_action_permission"] == "BLOCK_CAPITAL"


def test_replay_runner_handles_unlabeled_fixture():
    payload = run_replay(UNLABELED_FIXTURE)
    assert payload["record_count"] == 3
    assert payload["labeled_record_count"] == 0
    assert payload["unlabeled_record_count"] == 3
    assert payload["externally_checkable_count"] == 0
    summary = payload["evidence_ledger_summary"]
    assert summary["replay_labeled_signal_count"] == 0
    assert summary["replay_signal_count"] == 3
    assert summary["external_signal_count"] == 0
    permission = payload["canonical_action_permission_block"]
    assert permission["canonical_action_permission"] == "BLOCK_CAPITAL"
    assert "NO_EXTERNAL_TRUTH" in permission["veto_reasons"]


def test_replay_runner_loads_directory_fixture():
    payload = run_replay(DIRECTORY_FIXTURE)
    assert payload["record_count"] == 15
    assert payload["labeled_record_count"] == 12
    assert payload["unlabeled_record_count"] == 3


def test_replay_runner_baseline_metrics_are_deterministic():
    a = run_replay(LABELED_FIXTURE)
    b = run_replay(LABELED_FIXTURE)
    assert a["evidence_ledger_summary"]["payload_hash"] == b["evidence_ledger_summary"]["payload_hash"]
    a_baselines = {
        block["summary"]["baseline_name"]: block["outcome_accounting"]
        for block in a["baselines"]
    }
    b_baselines = {
        block["summary"]["baseline_name"]: block["outcome_accounting"]
        for block in b["baselines"]
    }
    assert a_baselines == b_baselines


def test_replay_runner_cli_emits_canonical_block():
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "replay_runner.py"),
            "--fixture",
            str(DIRECTORY_FIXTURE),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "canonical_action_permission=BLOCK_CAPITAL" in result.stdout
    assert "labeled_records=12" in result.stdout
    assert "honesty_note=replay-labeled records are externally checkable but never live external truth." in result.stdout


def test_replay_runner_json_output_is_deterministic():
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "replay_runner.py"),
            "--fixture",
            str(LABELED_FIXTURE),
            "--json",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    assert payload["record_count"] == 12
    assert payload["evidence_ledger_summary"]["external_signal_count"] == 12


def test_build_replay_summary_does_not_count_seed_as_external():
    seeded_records = [
        {
            "record_id": "seed-1",
            "instrument": "RTX",
            "timestamp": "2026-04-01T00:00:00Z",
            "feature_value": 0.1,
            "predicted_action": "MONITOR",
        }
    ]
    payload = build_replay_summary(seeded_records)
    summary = payload["evidence_ledger_summary"]
    assert summary["replay_labeled_signal_count"] == 0
    assert summary["external_signal_count"] == 0
