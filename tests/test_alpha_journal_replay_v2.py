"""Journal replay bridge v2: calibrated lineage, CLI flags, API."""

from __future__ import annotations

import json

import pytest

from src.alpha.journal_replay_bridge import (
    apply_calibration_to_records,
    journal_replay_report,
    outcome_to_replay_record,
)


def _outcome(**overrides) -> dict:
    base = {
        "outcome_id": "OE_T1",
        "source_type": "REAL_MANUAL_TRADE",
        "ticker": "EXMPL",
        "signal_id": "SIG_1",
        "trade_id": "T1",
        "opened_at": "2026-01-05T10:00:00+00:00",
        "outcome_label": "WIN",
        "realized_return": 0.04,
        "score_at_entry": 62.0,
        "quality": 0.9,
        "is_calibration_eligible": True,
        "archetype": "VALIDATE",
    }
    base.update(overrides)
    return base


def test_v2_record_carries_raw_and_calibration_fields() -> None:
    record, _ = outcome_to_replay_record(_outcome())
    assert record["raw_score"] == 62.0
    assert record["raw_event_probability"] == pytest.approx(0.62)
    assert record["calibrated_event_probability"] is None
    assert record["calibration_method"] == "insufficient_data"
    assert record["calibration_artifact_id"] is None
    lineage = record["lineage"]
    assert lineage["raw_score_source"] == "journal_score_at_entry"
    assert lineage["probability_derivation"] == "score_proxy"
    assert lineage["calibration_source"] == "none"
    assert lineage["outcome_source"] == "journal_reconciliation"


def test_apply_calibration_updates_records_and_lineage() -> None:
    from src.alpha.calibration_bridge import fit_alpha_calibration_map

    records = []
    for i in range(60):
        probability = 0.9 if i % 2 == 0 else 0.85
        win = i % 5 != 0 and i % 3 != 0
        record, _ = outcome_to_replay_record(
            _outcome(
                outcome_id=f"OE_{i}",
                trade_id=f"T{i}",
                score_at_entry=probability * 100.0,
                outcome_label="WIN" if win else "LOSS",
                realized_return=0.04 if win else -0.04,
            )
        )
        records.append(record)
    cmap, summary = fit_alpha_calibration_map(records)
    assert summary["calibration_available"] is True
    applied = apply_calibration_to_records(records, cmap, artifact_id="abc123")
    assert applied == 60
    sample = records[0]
    assert sample["calibrated_event_probability"] is not None
    assert sample["calibrated_event_probability"] != sample["raw_event_probability"]
    assert sample["event_probability"] == sample["calibrated_event_probability"]
    assert sample["calibration_method"] in ("isotonic", "platt")
    assert sample["calibration_artifact_id"] == "abc123"
    assert sample["lineage"]["probability_derivation"] == "calibrated_score_proxy"
    assert sample["lineage"]["calibration_source"] == "artifact:abc123"
    assert 0.0 <= sample["calibrated_event_probability"] <= 1.0


def test_report_without_calibration_says_so(tmp_path) -> None:
    report = journal_replay_report(tmp_path / "missing.db")
    assert report["calibration"]["method"] == "insufficient_data"
    assert report["calibration"]["calibration_available"] is False
    assert "calibration_map" in report["calibration"]["missing_inputs"]
    assert "reliability" in report
    assert report["reliability"]["sample_size"] == 0


def test_report_fit_on_empty_journal_refuses_honestly(tmp_path) -> None:
    report = journal_replay_report(tmp_path / "missing.db", fit_calibration=True)
    assert report["calibration"]["method"] == "insufficient_data"
    assert report["calibration"]["calibration_available"] is False


def test_report_with_bad_artifact_degrades_safely(tmp_path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    report = journal_replay_report(
        tmp_path / "missing.db", calibration_artifact_path=bad
    )
    assert report["calibration"]["calibration_available"] is False
    assert any(
        "failed to load" in warning for warning in report["calibration"]["warnings"]
    )


def test_cli_fit_and_json_flags(capsys, tmp_path) -> None:
    from scripts.build_alpha_replay_from_journal import main

    artifact = tmp_path / "artifact.json"
    code = main(
        [
            "--db-path",
            str(tmp_path / "missing.db"),
            "--fit-calibration",
            "--calibration-artifact",
            str(artifact),
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["calibration"]["method"] == "insufficient_data"
    # Empty journal: refusal means no artifact is written.
    assert not artifact.exists()


def test_cli_apply_requires_artifact_path() -> None:
    from scripts.build_alpha_replay_from_journal import main

    with pytest.raises(SystemExit):
        main(["--apply-calibration"])
