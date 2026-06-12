"""Calibration import CLI proofs: the ledger is no longer empty
scaffolding — and tiers can never launder each other.

The seed file is SYNTHETIC by declaration; these tests pin that the
plumbing works AND that the output says so at every step.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.import_outcomes import import_grouped, main, read_rows

REPO = Path(__file__).resolve().parents[1]
SEED = REPO / "examples" / "outcomes" / "calibration_seed.jsonl"


def test_seed_file_imports_cleanly_and_is_synthetic() -> None:
    result = import_grouped(read_rows(SEED))
    assert result["rows_read"] == 6
    assert result["parse_errors"] == []
    assert result["tiers_present"] == ["synthetic_fixture"]
    report = result["by_tier"]["synthetic_fixture"]
    summary = report["summary"]
    assert summary["count"] == 6
    assert summary["rejected"] == 0
    assert summary["status"] == "require_more_data"  # 6 < floor of 10
    assert summary["data_tier"] == "synthetic_fixture"
    # The seed exercises both directions: wins and losses, expiry hits
    # and misses — calibration errors are real numbers, not zeros.
    assert summary["win_rate"] == pytest.approx(0.5)
    assert summary["mean_prediction_error"] > 0
    assert summary["mean_expiry_accuracy_days"] > 0


def test_tiers_are_never_mixed_in_one_summary() -> None:
    rows = read_rows(SEED)
    promoted = [dict(r) for r in rows]
    promoted[0]["data_tier"] = "backtest_replay"
    promoted[1]["data_tier"] = "empirical"
    result = import_grouped(promoted)
    assert result["tiers_present"] == [
        "synthetic_fixture", "backtest_replay", "empirical",
    ]
    assert result["by_tier"]["synthetic_fixture"]["summary"]["count"] == 4
    assert result["by_tier"]["backtest_replay"]["summary"]["count"] == 1
    assert result["by_tier"]["empirical"]["summary"]["count"] == 1
    # Each summary carries its OWN tier — no worst-of blending across
    # batches, and no synthetic row inside the empirical summary.
    assert (
        result["by_tier"]["empirical"]["summary"]["data_tier"]
        == "empirical"
    )
    assert "launder" in result["note"]


def test_unknown_tier_collapses_downward_to_synthetic() -> None:
    rows = read_rows(SEED)
    rows[0]["data_tier"] = "definitely_real_trust_me"
    result = import_grouped(rows)
    assert result["tiers_present"] == ["synthetic_fixture"]
    assert result["by_tier"]["synthetic_fixture"]["summary"]["count"] == 6


def test_malformed_jsonl_lines_are_reported_not_fatal() -> None:
    bad = SEED.read_text(encoding="utf-8") + "\n{not json}\n"
    scratch = REPO / "runtime"
    scratch.mkdir(exist_ok=True)
    path = scratch / "test_outcomes_bad.jsonl"
    try:
        path.write_text(bad, encoding="utf-8")
        result = import_grouped(read_rows(path))
        assert result["rows_read"] == 7
        assert len(result["parse_errors"]) == 1
        assert result["by_tier"]["synthetic_fixture"]["summary"]["count"] == 6
    finally:
        path.unlink(missing_ok=True)


def test_cli_main_prints_synthetic_disclaimer(capsys) -> None:
    assert main([str(SEED)]) == 0
    out = capsys.readouterr().out
    assert "ADVISORY_ONLY" in out
    assert "synthetic seed: proves the plumbing, never the model" in out


def test_cli_json_output_is_machine_clean(capsys) -> None:
    assert main([str(SEED), "--json", "--streak"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["advisory_status"] == "ADVISORY_ONLY"
    streak = payload["by_tier"]["synthetic_fixture"]["streak_audit"]
    # Synthetic tier caps causal confidence at 0.40 — three wins on
    # fixtures cannot mint conviction even through the CLI.
    assert streak["confidence_cap"] == pytest.approx(0.40)
    assert streak["data_tier"] == "synthetic_fixture"
    assert "_reports" not in payload  # objects never leak into JSON


def test_cli_missing_file_fails_safely() -> None:
    assert main([str(REPO / "nope.jsonl")]) == 2
