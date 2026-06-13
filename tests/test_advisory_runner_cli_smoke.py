"""Operator-facing smoke tests for the advisory_runner CLI.

These lock the *documented* operator workflow (docs/OPERATOR_QUICKSTART.md and
examples/mythos_observations/) so the commands in the docs keep working:

  * the shipped sample observation file loads and routes to Fable;
  * the default CLI run NEVER writes;
  * capture writes ONLY when explicitly enabled, and only to the given path;
  * a missing corpus reports NO_CORPUS_FOUND;
  * every output is stamped advisory-only / real-money-prohibited;
  * the runtime decisions corpus is gitignored so it can't be committed.

No network. No writes outside tmp_path (the shipped sample is read-only).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.signal_arbitrage.advisory_runner import (
    cli,
    DEFAULT_CAPTURE_PATH,
    NO_CORPUS_FOUND,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SAMPLE = _REPO_ROOT / "examples" / "mythos_observations" / "reality_up_narrative_down.json"


def test_shipped_sample_file_exists_and_is_valid() -> None:
    """The documented sample must exist and be a non-empty JSON list of dicts."""
    assert _SAMPLE.is_file(), f"missing shipped sample: {_SAMPLE}"
    data = json.loads(_SAMPLE.read_text(encoding="utf-8"))
    assert isinstance(data, list) and len(data) >= 3
    assert all(isinstance(o, dict) and o.get("entity") for o in data)
    # Three distinct ecologies -> corroboration is possible.
    assert len({o["source"] for o in data}) >= 3


def test_documented_sample_run_routes_to_fable_and_is_advisory_only() -> None:
    """`--observations <sample>` reproduces the documented routing + stamps."""
    res = cli(["--observations", str(_SAMPLE)])
    assert res["pre_scoring_decision"] == "ROUTE_TO_FABLE5"
    assert res["routed_to_fable"] is True
    assert res["advisory_status"] == "ADVISORY_ONLY"
    assert res["real_money_execution"] == "PROHIBITED"
    assert res["broker_api_called"] is False


def test_sample_run_preserves_fable_and_confidence_invariants() -> None:
    """Live CLI output honours InvestableScore <= RawMerit and the confidence cap."""
    res = cli(["--observations", str(_SAMPLE)])
    adv = res["advisory"]
    fable = adv["fable"]
    assert fable["investable_score"] <= fable["raw_merit"] + 1e-9
    assert adv["capped_confidence"] <= adv["mythos_confidence_cap"] + 1e-9


def test_default_cli_run_does_not_write(tmp_path: Path) -> None:
    """Default run = capture disabled => no file is ever created."""
    target = tmp_path / "decisions.jsonl"
    res = cli(["--observations", str(_SAMPLE), "--capture-path", str(target)])
    assert res["capture_status"] == "CAPTURE_DISABLED"
    assert not target.exists()


def test_capture_dry_run_does_not_write(tmp_path: Path) -> None:
    """Even with capture enabled, dry_run computes but writes nothing."""
    target = tmp_path / "decisions.jsonl"
    res = cli(["--observations", str(_SAMPLE), "--capture-decisions",
               "--capture-mode", "dry_run", "--capture-path", str(target)])
    assert res["capture_status"] in {"CAPTURE_DRY_RUN", "DUPLICATE_SKIPPED"}
    assert not target.exists()


def test_capture_write_only_writes_when_explicitly_enabled(tmp_path: Path) -> None:
    """Explicit --capture-decisions --capture-mode write appends exactly once."""
    target = tmp_path / "decisions.jsonl"
    args = ["--observations", str(_SAMPLE), "--capture-decisions",
            "--capture-mode", "write", "--capture-path", str(target)]
    res = cli(args)
    assert res["capture_status"] == "CAPTURE_WRITTEN"
    assert target.exists()
    first = target.read_text(encoding="utf-8").strip().splitlines()
    assert len(first) == 1
    # Rerun is deduped by decision_id -> corpus is not polluted.
    res2 = cli(args)
    assert res2["capture_status"] == "DUPLICATE_SKIPPED"
    assert len(target.read_text(encoding="utf-8").strip().splitlines()) == 1


def test_check_corpus_missing_path_reports_no_corpus(tmp_path: Path) -> None:
    res = cli(["--check-corpus", "--capture-path", str(tmp_path / "absent.jsonl")])
    assert res["status"] == NO_CORPUS_FOUND
    assert res["total_snapshots"] == 0
    assert res["advisory_status"] == "ADVISORY_ONLY"


def test_cli_output_is_deterministic() -> None:
    """Same input -> identical advisory routing/scores across runs."""
    a = cli(["--observations", str(_SAMPLE)])
    b = cli(["--observations", str(_SAMPLE)])
    assert a["advisory"]["fable"] == b["advisory"]["fable"]
    assert a["pre_scoring_decision"] == b["pre_scoring_decision"]


def test_runtime_decisions_corpus_is_gitignored() -> None:
    """The runtime capture file must be ignored so `git add .` can't commit it."""
    gitignore = (_REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "data/calibration_corpus/decisions.jsonl" in gitignore
    # The default capture path is the one that must be protected.
    assert DEFAULT_CAPTURE_PATH == "data/calibration_corpus/decisions.jsonl"
