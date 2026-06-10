"""Journal-to-replay bridge: extraction, safety, and calibration math."""

from __future__ import annotations

import pytest

from src.alpha.journal_replay_bridge import (
    build_replay_records_from_journal,
    calibrated_confidence,
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


def test_win_outcome_converts_to_confirmed_record() -> None:
    record, skip = outcome_to_replay_record(_outcome())
    assert skip is None
    assert record["source"] == "journal_reconciliation"
    assert record["opportunity_score"] == 62.0
    assert record["observed_outcome"]["fundamental_confirmation"] is True
    assert record["observed_outcome"]["price_return"] == pytest.approx(0.04)
    assert record["event_probability"] == pytest.approx(0.62)
    assert record["lineage"]["probability_derivation"] == "score_proxy"


def test_loss_outcome_converts_to_refuted_record() -> None:
    record, _ = outcome_to_replay_record(
        _outcome(outcome_label="LOSS", realized_return=-0.06)
    )
    assert record["observed_outcome"]["fundamental_confirmation"] is False


def test_open_outcome_is_skipped_with_reason() -> None:
    record, skip = outcome_to_replay_record(_outcome(outcome_label="OPEN"))
    assert record is None
    assert skip == "open_or_unknown_outcome"


def test_synthetic_fixture_is_excluded() -> None:
    record, skip = outcome_to_replay_record(
        _outcome(source_type="SYNTHETIC_FIXTURE")
    )
    assert record is None
    assert skip == "synthetic_fixture_source"


def test_missing_score_is_skipped() -> None:
    record, skip = outcome_to_replay_record(_outcome(score_at_entry=None))
    assert record is None
    assert skip == "missing_score_at_entry"


def test_mixed_scale_scores_normalize_to_0_100() -> None:
    fraction, _ = outcome_to_replay_record(_outcome(score_at_entry=0.62))
    tenpoint, _ = outcome_to_replay_record(_outcome(score_at_entry=6.2))
    hundred, _ = outcome_to_replay_record(_outcome(score_at_entry=62.0))
    assert fraction["opportunity_score"] == pytest.approx(62.0)
    assert tenpoint["opportunity_score"] == pytest.approx(62.0)
    assert hundred["opportunity_score"] == pytest.approx(62.0)


def test_ineligible_record_gets_no_probability() -> None:
    record, _ = outcome_to_replay_record(_outcome(is_calibration_eligible=False))
    assert "event_probability" not in record
    assert record["lineage"]["probability_derivation"] == "none"


def test_absent_db_is_safe_and_reports_missing_inputs(tmp_path) -> None:
    result = build_replay_records_from_journal(tmp_path / "does_not_exist.db")
    assert result["discovered_records"] == 0
    assert result["usable_records"] == 0
    assert result["records"] == []
    assert "journal_outcomes" in result["missing_inputs"]
    assert result["outcome_coverage"] == 0.0


def test_full_report_on_empty_journal_is_safe(tmp_path) -> None:
    report = journal_replay_report(tmp_path / "missing.db")
    assert report["calibration_support"] == 0.0
    assert report["replay"]["record_count"] == 0
    assert "not performance results" in report["disclaimer"]


def test_bridge_extracts_from_monkeypatched_extractor(monkeypatch) -> None:
    import scripts.outcome_evidence_extractor as extractor

    class _FakeOutcome:
        def __init__(self, payload):
            self._payload = payload

        def to_dict(self):
            return self._payload

    fake = [
        _FakeOutcome(_outcome()),
        _FakeOutcome(_outcome(outcome_id="OE_T2", trade_id="T2", outcome_label="LOSS")),
        _FakeOutcome(_outcome(outcome_id="OE_T3", trade_id="T3", outcome_label="OPEN")),
    ]
    monkeypatch.setattr(extractor, "extract_from_db", lambda *a, **k: fake)
    result = build_replay_records_from_journal()
    assert result["discovered_records"] == 3
    assert result["usable_records"] == 2
    assert result["skip_reasons"] == {"open_or_unknown_outcome": 1}
    assert result["outcome_coverage"] == pytest.approx(2 / 3)


def test_calibrated_confidence_math_and_bounds() -> None:
    # Full support, full coverage: confidence preserved.
    assert calibrated_confidence(80.0, 100.0, 1.0) == pytest.approx(80.0)
    # No support: confidence halved (then scaled by coverage).
    assert calibrated_confidence(80.0, 0.0, 1.0) == pytest.approx(40.0)
    # No coverage: no confidence.
    assert calibrated_confidence(80.0, 100.0, 0.0) == 0.0
    assert 0.0 <= calibrated_confidence(500.0, 500.0, 5.0) <= 100.0


def test_bridge_module_makes_no_network_calls() -> None:
    import src.alpha.journal_replay_bridge as bridge

    source = open(bridge.__file__).read()
    for fragment in ("requests.", "urllib", "httpx", "socket"):
        assert fragment not in source


def test_cli_script_prints_report(capsys) -> None:
    import json

    from scripts.build_alpha_replay_from_journal import main

    assert main(["--db-path", "/nonexistent/path.db", "--k", "3"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["calibration_support"] == 0.0
    assert "disclaimer" in payload
